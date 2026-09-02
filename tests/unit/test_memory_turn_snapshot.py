"""EVO-20260827-ed4c1350 批次1（P0-A/T2）: 注入 turn 级快照幂等.

覆盖:
- memory_snapshot 同 turn 多次重入（模拟 10+ tool rounds/重试轮）→ 恰 1 条
- 新 user turn（新 turn_ref）→ 允许新 snapshot；同 turn 重入不膨胀
- 旧会话消息无 turn_ref → 不参与幂等碰撞（零回归）
- memory 检索异常 → fail-open（fault feedback 注入，不抛）
- experience tip run 级 flag: 已注入过本 turn → 跳过；命中注入 → flag 置位
  + metadata 带 turn_ref
背景: 09c44093 实测 67 条/54.6K 字符/同帧 x18（旧尾部 8 条文本比对幂等失效）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from llm_loop.core.injection_labels import PROGRAM_APPENDIX_NOTICE, REFERENCE_LABEL
from llm_loop.core.loop.engine import LoopEngine
from llm_loop.core.loop.engine_services.tool_cycle import ToolCycleService
from llm_loop.core.message import Message, MessageSource

_EXP_MD = """---
title: web_fetch 抓取最短路径
scenario: web_fetch 抓网页失败需换路径
root_cause: 反爬/JS 壳
solution: 用 curl 直取 HTML 再解析
evidence: test
tags: [web_fetch, 抓取]
source: {}
status: active
created_at: "2026-08-16T00:00:00+08:00"
updated_at: "2026-08-16T00:00:00+08:00"
---
"""


class _MemStore:
    """MemoryStore 最小桩（build_memory_messages 依赖面: search/mark_injected）."""

    def __init__(self, entries: list) -> None:
        self._entries = entries
        self.injected: list = []

    def search(self, keywords, top_k=5, session_id=""):
        hits = [e for e in self._entries if any(k in e.content for k in keywords)]
        return hits[:top_k]

    def _by_id(self, eid):
        return next((e for e in self._entries if e.id == eid), None)

    def mark_injected(self, entries):
        self.injected.extend(entries)


class _BoomStore:
    def search(self, *a, **k):
        raise RuntimeError("store down")


def _entry(eid: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=eid,
        content=content,
        type="fact",
        scope="global",
        source_session_id="",
        inject_policy="auto",
    )


def _engine(store) -> LoopEngine:
    eng = object.__new__(LoopEngine)
    eng.memory = store
    eng.semantic_retriever = None
    eng.runtime = None
    eng.settings = SimpleNamespace(memory_top_k=5)
    from llm_loop.core.loop.engine_services.runtime_params import RuntimeParamsService

    eng._runtime_params = RuntimeParamsService(eng)  # B5-W4-02a: 裸实例补 service 注入（沿 self._host = self 先例）
    eng._events = []
    eng._faults = []
    eng._append_message_event = lambda sess, msg: eng._events.append(msg)
    eng._fault_feedback = (
        lambda kind, exc: Message(
            role="system",
            content=f"[程序异常反馈:{kind}] {exc}",
            source=MessageSource.SYSTEM,
        )
    )
    eng._record_program_fault = lambda kind: eng._faults.append(kind)
    return eng


def _sess() -> SimpleNamespace:
    return SimpleNamespace(messages=[], session_id="s1")


def _snapshots(sess) -> list:
    return [
        m
        for m in sess.messages
        if (m.metadata or {}).get("injection_kind") == "memory_snapshot"
    ]


def test_turn_snapshot_idempotent_across_rounds():
    """同 turn 重入 12 次（模拟 10+ tool rounds/重试轮）→ memory 注入恰 1 条."""
    eng = _engine(_MemStore([_entry("m1", "database migration runbook 索引重建步骤")]))
    sess = _sess()
    for _ in range(12):
        eng._inject_turn_memory_snapshot(sess, "database migration deploy", turn_ref=0)
    snaps = _snapshots(sess)
    assert len(snaps) == 1
    msg = snaps[0]
    assert msg.role == "user"
    assert "[memory:fact]" in msg.content
    assert "ref=memory:m1" in msg.content
    assert msg.content.startswith(PROGRAM_APPENDIX_NOTICE)
    assert REFERENCE_LABEL in msg.content
    md = msg.metadata or {}
    assert md.get("persisted_injection") is True
    assert md.get("origin_layer") == "reference"
    assert md.get("program_origin") is True
    assert md.get("turn_ref") == 0
    assert md.get("query_fp")
    assert len(md.get("query_fp")) == 12


def test_new_turn_same_reference_is_not_reinjected():
    """R3: 新 user turn 再命中同一 stable ref → 不重复完整注入。"""
    eng = _engine(_MemStore([_entry("m1", "database migration runbook 索引重建步骤")]))
    sess = _sess()
    eng._inject_turn_memory_snapshot(sess, "database migration deploy", turn_ref=0)
    assert len(_snapshots(sess)) == 1
    sess.messages.append(
        Message(role="assistant", content="ok", source=MessageSource.SYSTEM)
    )  # turn 内消息推进
    eng._inject_turn_memory_snapshot(sess, "database migration deploy", turn_ref=0)
    assert len(_snapshots(sess)) == 1  # 同 turn 重入不膨胀
    sess.messages.append(
        Message(role="user", content="next question", source=MessageSource.USER)
    )  # 新 user msg
    eng._inject_turn_memory_snapshot(sess, "database rollback steps", turn_ref=2)
    assert len(_snapshots(sess)) == 1  # memory:m1 已 seen，完整正文每 session 仅一次
    assert _snapshots(sess)[0].metadata.get("reference_key") == "ref:memory:m1"


def test_legacy_messages_no_turn_ref_no_collision():
    """旧会话消息（metadata 无 turn_ref）→ 不参与幂等碰撞（零回归）."""
    eng = _engine(_MemStore([_entry("m1", "database migration runbook 索引重建步骤")]))
    sess = _sess()
    legacy = Message(
        role="user",
        content="[上下文注入·非新指令] 旧格式注入（无 turn 身份）",
        source=MessageSource.USER,
        metadata={"persisted_injection": True},
    )
    sess.messages.append(legacy)
    eng._inject_turn_memory_snapshot(sess, "database migration deploy", turn_ref=0)
    snaps = _snapshots(sess)
    assert len(snaps) == 1  # 旧消息 turn_ref=None ≠ 0 → 不误判 dup
    assert snaps[0] is not legacy


def test_memory_fault_fail_open():
    """检索异常 → fail-open: 只记 observability，不生成 memory_snapshot prompt."""
    eng = _engine(_BoomStore())
    sess = _sess()
    eng._inject_turn_memory_snapshot(sess, "database migration deploy", turn_ref=0)
    assert _snapshots(sess) == []
    assert sess.messages == []
    assert eng._faults == ["memory"]
    # 同一 turn 重入仍不生成程序 fault prompt；fault 计数可重复反映真实调用失败。
    eng._inject_turn_memory_snapshot(sess, "database migration deploy", turn_ref=0)
    assert _snapshots(sess) == []



class _TipStub(ToolCycleService):
    """LoopEngine 最小桩（_inject_experience_tips 依赖面）."""

    def __init__(self, exp_dir: str | Path, turn_ref=None) -> None:
        self._host = self  # R9-B5-W3-01: 替身自给宿主面（迁移前 self.X → 现 self._host.X → 同一字段）
        self.settings = SimpleNamespace(
            tool_experience_inject=True,
            experiences_dir=str(exp_dir),
            skills_dir="nonexistent_skills",
        )
        self.messages = []
        self.events = []
        self._tip_tail_messages = []
        # T5: shadow flag 已删——turn 身份与注入历史均从 sess.messages SoT 派生
        self._current_turn_ref = turn_ref
        self._cache_last_model_by_session = {}
        self._cache_last_model = ""
        type(self)._skills_cache = (0.0, [])

    def _append_message_event(self, sess, msg) -> None:
        self.events.append(msg)


def _make_exp_dir(tmp_path: Path) -> Path:
    d = tmp_path / "experiences"
    d.mkdir()
    (d / "EXPERIENCE-test-web-fetch.md").write_text(_EXP_MD, encoding="utf-8")
    return d


def test_tip_turn_done_blocks_reinject_sot(tmp_path):
    """T5: 本 turn 已注入（消息已有 experience_tip ∧ turn_ref 匹配）→ 零新增."""
    d = _make_exp_dir(tmp_path)
    stub = _TipStub(d, turn_ref=3)
    stub.messages.append(
        Message(
            role="user",
            content="[经验提示] 已注入",
            source=MessageSource.USER,
            metadata={
                "persisted_injection": True,
                "injection_kind": "experience_tip",
                "turn_ref": 3,
                "experience_tip_tools": ["web_fetch"],
            },
        )
    )
    ToolCycleService._inject_experience_tips(stub, stub, ["web_fetch"])
    assert len(stub.messages) == 1  # SoT 判定本 turn 已注入 → 不再追加


def test_tip_inject_persists_turn_ref_and_quota(tmp_path):
    """E08: generic tip is not persisted, so no turn-ref prompt quota is created."""
    d = _make_exp_dir(tmp_path)
    stub = _TipStub(d, turn_ref=3)
    ToolCycleService._inject_experience_tips(stub, stub, ["web_fetch"])
    ToolCycleService._inject_experience_tips(stub, stub, ["web_fetch", "other_tool"])
    assert stub.messages == []

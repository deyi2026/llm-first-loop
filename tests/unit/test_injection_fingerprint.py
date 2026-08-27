"""err1210 注入形态黄金指纹回归（tasks 7.2；spec 5.2.1-4b 红灯机制）.

以附录 C/D.2 实测形态为黄金指纹（spec 5.4-2/5.2.1-4b，design 风险 5 约束固化）:
- 尾部 5 条连续 user（chars 形态 252/1117/254/116/85 对照——末位为固定 gate_note，
  现 64 字符；85 为当时形态，槽位↔chars 精确对应属 P2 oracle 待定项，spec D.2 注）；
- 公共前缀 wire 哈希一致结构（注入只追加尾部、前缀逐字节不变，附录 C 92/135 条一致）。
- 注入槽结构变更（增删槽/改包装/绕过 wrap_injection/改固定文本）→ 黄金摘要失配
  显式 fail（红灯），提示更新指纹（spec 5.2.1-4b"红灯提示更新"）。

黄金摘要 = sha256(tail 注入群 (role, content) 序列)。固定夹具内容 → 确定性摘要；
任何结构变更（包装前缀文本/槽数/槽序/固定文本）必然改变摘要 → 红灯触发。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import llm_loop.core.loop.build as build_mod
import llm_loop.core.loop.focus as focus_mod
from llm_loop.core.cache_health import GATE_NOTE_CONTENT
from llm_loop.core.loop.err1210 import InjectionSpan
from llm_loop.core.loop.focus import _INJECTION_PREFIX
from llm_loop.core.loop.hotcard import write_hotcard
from llm_loop.core.message import Message, MessageSource

# 附录 C/D.2 实测形态的确定性夹具（等长占位正文；wrap 后命中目标 chars）
_WRAP_OVERHEAD = len(_INJECTION_PREFIX) + 1  # prefix + "\n"（anchor 空时）
_HOTCARD_RENDER_OVERHEAD = 78  # 热卡渲染模板固定开销（头部/换行/尾部，实测 2026-08-27）
# 槽位↔chars 对应为 P2 待定项——此处按附录 C 观察序构造: 记忆兜底/协调/提示/热卡/gate_note
_TARGET_CHARS = (252, 1117, 254, 116, 64)  # 附录 C 252/1117/254/116/85 的当前 gate_note 形态


def _fixture(target: int, head: str) -> str:
    """确定性夹具内容: head + 占位填充至 target（wrap 后字符数）."""
    return head + "注" * (target - _WRAP_OVERHEAD - len(head))


_MEMORY_FIX = _fixture(_TARGET_CHARS[0], "记忆检索结果：")
_INTEROP_FIX = _fixture(_TARGET_CHARS[1], "任务协调信息：")
_TIP_FIX = _fixture(_TARGET_CHARS[2], "经验提示：")
_HOTCARD_ANCHOR = "热卡AAA"  # 5 字符 → 渲染后 83 字符 → wrap 后 116


def _tail_digest(messages: list[dict], n: int = 5) -> str:
    """注入群黄金摘要（role/content 序列 sha256，固定口径——变更即红灯）."""
    h = hashlib.sha256()
    for m in messages[-n:]:
        h.update(m["role"].encode())
        h.update(b"\0")
        h.update(str(m["content"]).encode())
        h.update(b"\0")
    return h.hexdigest()


# 黄金摘要（P1 9.1 聚合形态，2026-08-28 实测重算; 注入槽结构变更时此值失配 → 红灯）
_GOLDEN_TAIL_DIGEST = "9d44eec3caed2573052bf0d3438afd593cfd39a88215304cc6f8dc66ec3cc32f"


def _engine(tmp_path: Path):
    """最小 LoopEngine（复用 test_model_attribution 装配，单一真相）."""
    os.environ.setdefault("ZHIPU_API_KEY", "k")
    from tests.unit.test_model_attribution import (
        _FakeLLMClient,
        _make_engine,
        _make_pool,
        _settings,
    )

    providers = json.dumps(
        {
            "zhipu": {
                "base_url": "https://api.zhipu.local/v1",
                "api_key_env": "ZHIPU_API_KEY",
                "models": {"glm-5": {"context": 300000, "thinking": True, "cost_tier": "low"}},
                "default_model": "glm-5",
            },
        }
    )
    settings = _settings(
        tmp_path,
        model_providers_raw=providers,
        llm_model="zhipu/glm-5",
        history_max_chars=300_000,
    )
    fake = _FakeLLMClient("zhipu/glm-5")
    pool = _make_pool(settings, fake, cached={"zhipu": fake})
    engine = _make_engine(tmp_path, pool, settings)
    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.messages.append(
        Message(role="user", content="固定任务：继续当前工作。", source=MessageSource.USER)
    )
    return engine, sess


def _arm_all_slots(engine, sess, *, memory: bool = True, hotcard: bool = True,
                   tip_extra: int = 0, gate_note: bool = True):
    """武装四槽 + 记忆兜底（构造附录 C 形态的 5 条尾部 user 注入群）."""
    engine._interop_tail_messages = [
        Message(role="system", content=_INTEROP_FIX, source=MessageSource.SYSTEM)
    ]
    tips = [Message(role="system", content=_TIP_FIX, source=MessageSource.SYSTEM)]
    tips += [
        Message(role="system", content=_TIP_FIX + f"#{i}", source=MessageSource.SYSTEM)
        for i in range(tip_extra)
    ]
    engine._tip_tail_messages = tips
    if hotcard:
        write_hotcard(
            origin_session="other-session", anchor=_HOTCARD_ANCHOR,
            data_dir=engine.settings.data_dir,
        )
    if gate_note:
        engine._cache_monitor._get_bucket(sess.session_id).gate_note_pending = True
    memory_msgs = (
        [Message(role="system", content=_MEMORY_FIX, source=MessageSource.SYSTEM)]
        if memory
        else []
    )
    return memory_msgs


def _build(engine, sess, memory_msgs) -> list[dict]:
    return engine._build_llm_messages(
        sess, memory_msgs, max_chars=200_000, planned_label="zhipu/glm-5"
    )


def _assert_red_light(engine, sess, *, what: str, **arm_kwargs) -> None:
    """红灯机制: 结构变更后摘要必须与黄金摘要失配（== 指纹用例显式 fail）.

    arm_kwargs 透传 _arm_all_slots（槽增/删等结构变更与首次构建一致）。
    """
    memory_msgs = _arm_all_slots(engine, sess, **arm_kwargs)
    out = _build(engine, sess, memory_msgs)
    digest = _tail_digest(out)
    assert digest != _GOLDEN_TAIL_DIGEST, (
        f"指纹红灯未触发: {what} 后黄金摘要竟未变化（摘要 {digest[:16]}…）。"
        "若这是有意的结构变更，请同步更新 _GOLDEN_TAIL_DIGEST 并评审注入槽设计"
        "（spec 5.2.1-4b：注入槽结构变更须显式红灯提示更新指纹）"
    )


class TestGoldenFingerprint:
    def test_golden_tail_morphology(self, tmp_path):
        """P1 9.1 聚合形态: 尾部 1 条聚合 user（memory+四槽段标记，wrap 包装，段序恒定）."""
        engine, sess = _engine(tmp_path)
        memory_msgs = _arm_all_slots(engine, sess)
        out = _build(engine, sess, memory_msgs)
        tail = out[-1:]
        assert [m["role"] for m in tail] == ["user"], "尾部注入恒为 1 条聚合 user（P1 9.1）"
        agg = tail[0]["content"]
        assert agg.startswith(_INJECTION_PREFIX), "聚合消息统一 wrap_injection 包装"
        for slot in ("memory", "interop", "tip", "hotcard", "gate_note"):
            assert f"--- [slot:{slot}] ---" in agg, f"聚合含 {slot} 段"
        assert GATE_NOTE_CONTENT in agg, "gate_note 固定文本保真入段"
        # 段序恒定: memory→interop→tip→hotcard→gate_note（build 收集顺序）
        idxs = [
            agg.index(f"--- [slot:{s}] ---")
            for s in ("memory", "interop", "tip", "hotcard", "gate_note")
        ]
        assert idxs == sorted(idxs), "段序与收集顺序一致"
        # 黄金摘要（结构变更的显式红灯锚点）
        assert _tail_digest(out) == _GOLDEN_TAIL_DIGEST

    def test_registration_matches_tail(self, tmp_path):
        """P1 9.1: 旁路登记退化为单 AGGREGATED entry（msg_idx 指聚合消息尾位）."""
        engine, sess = _engine(tmp_path)
        memory_msgs = _arm_all_slots(engine, sess)
        out = _build(engine, sess, memory_msgs)
        entries = engine._last_build_injections
        assert len(entries) == 1  # 聚合单 entry（memory 兜底不登记）
        assert str(entries[0].slot_kind) == "aggregated"
        assert entries[0].msg_idx == len(out) - 1  # 指向聚合消息（尾位）
        # 登记构成尾部连续段（P0 剥离前置校验）
        assert InjectionSpan(tuple(entries)).is_tail_contiguous(out) is True

    def test_four_slot_no_memory_tail(self, tmp_path):
        """常态（记忆已持久化）: 尾部 1 条聚合 user 含四槽段（无 memory 段）."""
        engine, sess = _engine(tmp_path)
        memory_msgs = _arm_all_slots(engine, sess, memory=False)
        out = _build(engine, sess, memory_msgs)
        tail = out[-1:]
        assert [m["role"] for m in tail] == ["user"]
        agg = tail[0]["content"]
        assert agg.startswith(_INJECTION_PREFIX)
        assert "--- [slot:memory] ---" not in agg
        for slot in ("interop", "tip", "hotcard", "gate_note"):
            assert f"--- [slot:{slot}] ---" in agg
        assert [e.msg_idx for e in engine._last_build_injections] == [len(out) - 1]

    def test_wire_prefix_invariant(self, tmp_path):
        """公共前缀 wire 哈希一致结构（附录 C: 注入只追加尾部，前缀逐字节不变）."""
        engine, sess = _engine(tmp_path)
        base = _build(engine, sess, [])  # 无任何注入
        memory_msgs = _arm_all_slots(engine, sess)
        full = _build(engine, sess, memory_msgs)
        assert full[: len(base)] == base, "注入轮公共前缀与基线逐字节一致（92/135 条对照性质）"


class TestRedLightMutations:
    """注入槽结构变更 → 黄金摘要失配（显式红灯，spec 5.2.1-4b）."""

    def test_slot_added(self, tmp_path):
        engine, sess = _engine(tmp_path)
        memory_msgs = _arm_all_slots(engine, sess, tip_extra=1)  # tip 槽多一条
        out = _build(engine, sess, memory_msgs)
        assert out[-1]["content"].count("--- [slot:tip] ---") == 2, "tip 槽增加消息 → 2 个 tip 段"
        _assert_red_light(engine, sess, what="tip 槽增加消息", tip_extra=1)

    def test_slot_removed(self, tmp_path):
        engine, sess = _engine(tmp_path)
        memory_msgs = _arm_all_slots(engine, sess, hotcard=False)  # 移除 hotcard 槽
        out = _build(engine, sess, memory_msgs)
        assert "--- [slot:hotcard] ---" not in out[-1]["content"]
        _assert_red_light(engine, sess, what="移除 hotcard 槽", hotcard=False)

    def test_wrap_bypassed(self, tmp_path, monkeypatch):
        """绕过 wrap_injection（新槽不接统一包装 → design 风险 5）→ 红灯."""
        monkeypatch.setattr(build_mod, "wrap_injection", lambda content, anchor="": content)
        engine, sess = _engine(tmp_path)
        memory_msgs = _arm_all_slots(engine, sess)
        out = _build(engine, sess, memory_msgs)
        assert not out[-2]["content"].startswith(_INJECTION_PREFIX)
        _assert_red_light(engine, sess, what="绕过 wrap_injection 直接追加")

    def test_wrap_prefix_text_changed(self, tmp_path, monkeypatch):
        """统一包装前缀文案变更（wrap_injection 行为不变）→ 红灯."""
        monkeypatch.setattr(focus_mod, "_INJECTION_PREFIX", "[新包装前缀·非新指令] ")
        engine, sess = _engine(tmp_path)
        memory_msgs = _arm_all_slots(engine, sess)
        out = _build(engine, sess, memory_msgs)
        assert not out[-2]["content"].startswith("[上下文注入·非新指令]")
        _assert_red_light(engine, sess, what="_INJECTION_PREFIX 文案变更")

    def test_gate_note_text_changed(self, tmp_path, monkeypatch):
        """gate_note 固定文本变更 → 红灯（85/64 形态锚点同时被保护）."""
        monkeypatch.setattr(build_mod, "GATE_NOTE_CONTENT", "[门禁干预] 新文本。")
        engine, sess = _engine(tmp_path)
        memory_msgs = _arm_all_slots(engine, sess)
        out = _build(engine, sess, memory_msgs)
        assert out[-1]["content"] != GATE_NOTE_CONTENT
        _assert_red_light(engine, sess, what="GATE_NOTE_CONTENT 固定文本变更")

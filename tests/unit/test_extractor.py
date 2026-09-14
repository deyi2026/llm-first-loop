"""单元测试: MemoryExtractor 独立记忆提取（T32 / FR-P1-EXT 系列）."""

from __future__ import annotations

import json

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore
from llm_loop.llm.client import LLMResponse
from llm_loop.memory.extractor import MemoryExtractor, _fingerprint
from llm_loop.memory.store import MemoryEntry, MemoryStore


class _FakeLLMExtract:
    """提取用 FakeLLM: 返回记忆块或抛异常."""

    def __init__(self, answer: str = "", error: Exception | None = None) -> None:
        self._answer = answer
        self._error = error

    def chat(self, messages, tools) -> LLMResponse:
        if self._error is not None:
            raise self._error
        return LLMResponse(content=self._answer, tool_calls=[], provider="fake")


def _mk_session(store, n_msgs: int, sid: str | None = None) -> str:
    sid = sid or store.create()
    for i in range(n_msgs):
        store.append(
            sid, Message(role="user", content=f"消息 {i} 关于蓝色", source=MessageSource.USER)
        )
    return sid


def test_trigger_below_threshold_no_action(tmp_path):
    """消息数 < 阈值 → 不触发（不产生审计噪音）."""
    store = SessionStore(tmp_path / "sessions")
    sid = _mk_session(store, 3)  # interval=20
    mem = MemoryStore(tmp_path / "memory")
    ex = MemoryExtractor(
        llm_client=_FakeLLMExtract(),
        memory=mem,
        session_store=store,
        interval_msgs=20,
        audit_dir=tmp_path / "audit",
    )
    assert ex.maybe_trigger(sid) is False


def test_trigger_async_when_threshold_met(tmp_path):
    """消息数 ≥ 阈值且过冷却 → 异步提交."""
    store = SessionStore(tmp_path / "sessions")
    sid = _mk_session(store, 25)
    mem = MemoryStore(tmp_path / "memory")
    ex = MemoryExtractor(
        llm_client=_FakeLLMExtract(),
        memory=mem,
        session_store=store,
        interval_msgs=20,
        cooldown_s=0,
        audit_dir=tmp_path / "audit",
    )
    assert ex.maybe_trigger(sid) is True


def test_cooldown_blocks_repeat(tmp_path):
    """冷却期内不重复触发."""
    store = SessionStore(tmp_path / "sessions")
    sid = _mk_session(store, 25)
    mem = MemoryStore(tmp_path / "memory")
    ex = MemoryExtractor(
        llm_client=_FakeLLMExtract(),
        memory=mem,
        session_store=store,
        interval_msgs=20,
        cooldown_s=600,
        audit_dir=tmp_path / "audit",
    )
    # 诊断断言（CI 平台差异排查用；失败时输出 meta 实际值）
    meta = store.get_meta(sid)
    assert meta is not None and meta.message_count >= 20, f"诊断: meta={meta!r}"
    assert ex.maybe_trigger(sid) is True
    assert ex.maybe_trigger(sid) is False  # 冷却内


def test_cooldown_first_trigger_when_monotonic_starts_at_zero(tmp_path):
    """容器/新命名空间场景回归（CI 抓到的平台 bug）：monotonic 从 0 开始（< cooldown_s）
    时首次触发不被误判为冷却期."""
    from unittest import mock

    import llm_loop.memory.extractor as extractor_mod

    store = SessionStore(tmp_path / "sessions")
    sid = _mk_session(store, 25)
    ex = extractor_mod.MemoryExtractor(
        llm_client=_FakeLLMExtract(),
        memory=MemoryStore(tmp_path / "memory"),
        session_store=store,
        interval_msgs=20,
        cooldown_s=600,
        audit_dir=tmp_path / "audit",
    )
    with mock.patch.object(extractor_mod.time, "monotonic", return_value=1.0):
        assert ex.maybe_trigger(sid) is True  # 首次（从未触发）→ 只查消息数阈值
        assert ex.maybe_trigger(sid) is False  # 冷却内（now - last = 0 < 600）


def test_cooldown_timestamp_state_retires_after_semantic_expiry(tmp_path, monkeypatch):
    """P4: cooldown hints retain only the live cooldown window, not all historical sessions."""
    import llm_loop.memory.extractor as extractor_mod

    store = SessionStore(tmp_path / "sessions")
    s1 = _mk_session(store, 25)
    s2 = _mk_session(store, 25)
    s3 = _mk_session(store, 25)
    ex = extractor_mod.MemoryExtractor(
        llm_client=_FakeLLMExtract(),
        memory=MemoryStore(tmp_path / "memory"),
        session_store=store,
        interval_msgs=20,
        cooldown_s=600,
        audit_dir=tmp_path / "audit",
    )
    monkeypatch.setattr(ex, "_run_async", lambda *args, **kwargs: None)
    now = [1.0]
    monkeypatch.setattr(extractor_mod.time, "monotonic", lambda: now[0])

    assert ex.maybe_trigger(s1) is True
    now[0] = 2.0
    assert ex.maybe_trigger(s2) is True
    assert len(ex._last_trigger_ts) == 2  # noqa: SLF001

    # At t=700 both prior timestamps are already semantically expired under the
    # existing 600s cooldown rule, so retiring them cannot change trigger behavior.
    now[0] = 700.0
    assert ex.maybe_trigger(s3) is True
    assert list(ex._last_trigger_ts) == [s3]  # noqa: SLF001


def test_extract_same_structure_and_dedup(tmp_path):
    """同构解析 + 指纹去重（即时沉淀 + 独立提取不重复）."""
    store = SessionStore(tmp_path / "sessions")
    sid = _mk_session(store, 5)
    mem = MemoryStore(tmp_path / "memory")
    # 先即时沉淀一条（含指纹）
    e = MemoryEntry(
        id="", type="fact", content="用户喜欢蓝色", keywords=["蓝色"], deposit_path="inline"
    )
    e.content_fingerprint = _fingerprint(e.content)
    mem.save_entry(e)
    answer = (
        '[[memory]] {"type": "fact", "content": "用户喜欢蓝色", "keywords": ["蓝色"]} [[/memory]]'
    )
    ex = MemoryExtractor(
        llm_client=_FakeLLMExtract(answer=answer),
        memory=mem,
        session_store=store,
        audit_dir=tmp_path / "audit",
    )
    result = ex.extract_session(sid, trigger="manual")
    assert result.skipped_duplicates == 1  # 指纹去重
    assert len(result.entries) == 0  # 新条目 0（已去重）
    assert mem.count() == 1  # 不产生重复条目


def test_extract_invalid_block_failures(tmp_path):
    """非法条目 → 不落库 + failures 如实记录."""
    store = SessionStore(tmp_path / "sessions")
    sid = _mk_session(store, 5)
    mem = MemoryStore(tmp_path / "memory")
    answer = '[[memory]] {"type": "fact"} [[/memory]]'  # 缺 content → 非法
    ex = MemoryExtractor(
        llm_client=_FakeLLMExtract(answer=answer),
        memory=mem,
        session_store=store,
        audit_dir=tmp_path / "audit",
    )
    result = ex.extract_session(sid, trigger="manual")
    assert result.entries == []
    assert mem.count() == 0
    # 审计记录 failures 非空
    log = tmp_path / "audit" / "memory_extract_log.jsonl"
    records = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert records
    assert records[-1]["failures"]  # 含非法原因


def test_extract_async_failure_isolated(tmp_path):
    """异步失败隔离: FakeLLM 抛异常 → 审计记录 failure，不抛穿."""
    store = SessionStore(tmp_path / "sessions")
    sid = _mk_session(store, 5)
    mem = MemoryStore(tmp_path / "memory")
    ex = MemoryExtractor(
        llm_client=_FakeLLMExtract(error=RuntimeError("LLM 崩了")),
        memory=mem,
        session_store=store,
        audit_dir=tmp_path / "audit",
    )
    result = ex.extract_session(sid, trigger="manual")
    assert result.entries == []
    # 不抛穿，且审计有失败记录
    log = tmp_path / "audit" / "memory_extract_log.jsonl"
    records = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert records
    assert records[-1]["failures"]


def test_extract_audit_fields(tmp_path):
    """审计字段完整（trigger/input_scope/entries/failures）."""
    store = SessionStore(tmp_path / "sessions")
    sid = _mk_session(store, 5)
    mem = MemoryStore(tmp_path / "memory")
    answer = (
        '[[memory]] {"type": "fact", "content": "新的记忆内容", "keywords": ["新"]} [[/memory]]'
    )
    ex = MemoryExtractor(
        llm_client=_FakeLLMExtract(answer=answer),
        memory=mem,
        session_store=store,
        audit_dir=tmp_path / "audit",
    )
    ex.extract_session(sid, trigger="manual")
    log = tmp_path / "audit" / "memory_extract_log.jsonl"
    records = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    r = records[-1]
    assert r["trigger"] == "manual"
    assert r["input_scope"]
    assert r["input_chars"] > 0
    assert r["entries"] >= 0


def test_late_a1_extractor_cannot_overwrite_a2_current_memory(tmp_path) -> None:
    """P3: late semantic extraction may be retained, but cannot retake current memory state."""
    import threading

    class _BlockingLLM:
        def __init__(self) -> None:
            self.entered = threading.Event()
            self.release = threading.Event()

        def chat(self, messages, tools):  # noqa: ANN001, ANN201, ARG002
            self.entered.set()
            assert self.release.wait(timeout=3.0)
            return LLMResponse(
                content=(
                    '[[memory]] {"type": "fact", "content": "A1 old project state", '
                    '"keywords": ["project"]} [[/memory]]'
                ),
                tool_calls=[],
                provider="fake",
            )

    sessions = SessionStore(tmp_path / "sessions")
    sid = _mk_session(sessions, 5)
    memory = MemoryStore(tmp_path / "memory")
    llm = _BlockingLLM()
    extractor = MemoryExtractor(
        llm_client=llm,
        memory=memory,
        session_store=sessions,
        audit_dir=tmp_path / "audit",
    )
    result_box = []
    worker = threading.Thread(
        target=lambda: result_box.append(extractor.extract_session(sid, trigger="interval")),
        name="a1-memory-extractor",
    )
    worker.start()
    assert llm.entered.wait(timeout=2.0)

    a2 = MemoryEntry(
        id="",
        type="fact",
        content="A2 current project state",
        keywords=["project"],
        source_session_id=sid,
        source_message_id="a2",
        deposit_path="inline",
    )
    current = memory.save_entry(a2)
    assert current.content == "A2 current project state"

    llm.release.set()
    worker.join(timeout=3.0)
    assert not worker.is_alive()
    assert len(result_box) == 1

    rows = memory.all()
    assert len(rows) == 1
    assert rows[0].content == "A2 current project state"
    # The old result is still retained as provenance/history, just not promoted current.
    late = [
        item
        for item in rows[0].observation_history
        if item.get("disposition") == "late_observation_not_promoted"
    ]
    assert late and late[-1]["content"] == "A1 old project state"

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

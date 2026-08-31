from __future__ import annotations

from llm_loop.core.episode_history import (
    EPISODE_KEEP_PROVIDER_KEY,
    RESOLVED_EPISODE_REF_KEY,
    provider_view_without_resolved_episodes,
)
from llm_loop.core.message import Message, MessageSource
from llm_loop.introspection.search import RecordSearcher
from llm_loop.memory.extract import memory_blocks_to_entries
from llm_loop.memory.retrieve import build_memory_messages
from llm_loop.memory.store import MemoryEntry, MemoryStore


def _entry(kind: str, content: str, keyword: str, *, inject_policy: str = "auto") -> MemoryEntry:
    return MemoryEntry(
        id="",
        type=kind,
        content=content,
        keywords=[keyword],
        inject_policy=inject_policy,
    )


def test_legacy_auto_decision_and_convention_do_not_auto_project(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory")
    decision = store.save_entry(_entry("decision", "旧决策：使用方案 A", "方案"))
    convention = store.save_entry(_entry("convention", "长期约定：不要自动 stage", "stage"))
    fact = store.save_entry(_entry("fact", "事实：方案 A 的接口名是 foo", "方案"))

    messages = build_memory_messages("方案 stage", store, top_k=5)

    assert len(messages) == 1
    wire = messages[0].content
    assert decision.content not in wire
    assert convention.content not in wire
    assert fact.content in wire
    assert decision.inject_count == 0
    assert convention.inject_count == 0
    assert fact.inject_count == 1


def test_explicit_memory_search_still_finds_recall_only_state(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory")
    decision = store.save_entry(
        _entry("decision", "旧决策：使用方案 A", "方案", inject_policy="recall_only")
    )
    convention = store.save_entry(
        _entry("convention", "长期约定：不要自动 stage", "stage", inject_policy="recall_only")
    )
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", memory_store=store)

    decision_hits = searcher.search(kind="memory", query="方案", limit=10)
    convention_hits = searcher.search(kind="memory", query="stage", limit=10)

    assert any(hit.get("id") == decision.id for hit in decision_hits)
    assert any(hit.get("id") == convention.id for hit in convention_hits)
    assert searcher.search(kind="memory", query=f"memory:{decision.id}", limit=1)[0]["id"] == decision.id


def test_new_decision_and_convention_extract_as_recall_only() -> None:
    entries, failures = memory_blocks_to_entries(
        [
            {"type": "decision", "content": "决定使用 A", "keywords": ["方案"]},
            {"type": "convention", "content": "不要自动 stage", "keywords": ["stage"]},
            {"type": "fact", "content": "端口是 8080", "keywords": ["端口"]},
            {"type": "procedure", "content": "先测试再提交", "keywords": ["测试"]},
        ],
        session_id="sid",
        message_id="m1",
    )

    assert failures == []
    policy = {entry.type: entry.inject_policy for entry in entries}
    assert policy == {
        "decision": "recall_only",
        "convention": "recall_only",
        "fact": "auto",
        "procedure": "auto",
    }


def test_legacy_keep_provider_marker_cannot_resurrect_resolved_source() -> None:
    message = Message(
        role="user",
        content="以后一直使用旧规则",
        source=MessageSource.USER,
        metadata={
            RESOLVED_EPISODE_REF_KEY: "episode:sid:0:legacy",
            EPISODE_KEEP_PROVIDER_KEY: True,
        },
    )

    assert provider_view_without_resolved_episodes([message]) == []

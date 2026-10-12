"""Phase 2 记忆增强测试（EVO-20260810-baae4016）."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

from llm_loop.memory.extract import extract_memory_blocks, memory_blocks_to_entries
from llm_loop.memory.store import MemoryEntry, MemoryStore


def _mk_store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path)


def test_extract_procedure_type():
    blocks = extract_memory_blocks(
        '[[memory]] {"type": "procedure", "content": "部署流程: build→test→push", "keywords": ["部署"]} [[/memory]]'
    )
    entries, failures = memory_blocks_to_entries(blocks, session_id="s1", message_id="m1")
    assert failures == []
    assert entries[0].type == "procedure"


def test_extract_unknown_type_fallback():
    blocks = extract_memory_blocks(
        '[[memory]] {"type": "weird", "content": "x", "keywords": []} [[/memory]]'
    )
    entries, _ = memory_blocks_to_entries(blocks, session_id="s1", message_id="m1")
    assert entries[0].type == "fact"  # 既有行为不破坏


def test_old_entry_backward_compat(tmp_path):
    store = _mk_store(tmp_path)
    # 模拟旧数据（无 Phase 2 字段）
    store._entries = [
        MemoryEntry(id="MEM-OLD-1", type="fact", content="旧条目", created_at="2026-01-01T00:00:00+00:00")
    ]
    store._save()
    store2 = MemoryStore(tmp_path)  # 重新加载
    e = store2.all()[0]
    assert e.access_count == 0 and e.decay_score == 1.0 and e.citations == []


def test_decay_ranking(tmp_path):
    store = _mk_store(tmp_path)
    old = MemoryEntry(
        id="M1", type="fact", content="关键词A", keywords=["k"],
        created_at="2026-01-01T00:00:00+00:00",
        last_access_at=(datetime.now(UTC) - timedelta(days=60)).isoformat(),
    )
    fresh = MemoryEntry(
        id="M2", type="fact", content="关键词A", keywords=["k"],
        created_at="2026-08-01T00:00:00+00:00",
        last_access_at=datetime.now(UTC).isoformat(),
    )
    store._entries = [old, fresh]
    hits = store.search(["关键词"], top_k=5)
    assert hits[0].id == "M2"  # 关键词分相同 → decay 高者优先
    assert old.decay_score < 0.3  # 60 天 → 0.5^2 = 0.25


def test_citations_passthrough():
    blocks = extract_memory_blocks(
        '[[memory]] {"type": "fact", "content": "决策", "keywords": [], "citations": [{"kind": "tool_result", "ref": "session:s1/msg:m9", "note": "来源"}]} [[/memory]]'
    )
    entries, _ = memory_blocks_to_entries(blocks, session_id="s1", message_id="m1")
    assert entries[0].citations[0]["ref"] == "session:s1/msg:m9"


def test_search_no_frequent_save(tmp_path):
    store = _mk_store(tmp_path)
    store.save_entry(MemoryEntry(id="", type="fact", content="hello world", keywords=["hello"]))
    before = store._index_path.stat().st_mtime_ns
    for _ in range(10):
        store.search(["hello"])
    # search 不应触发全量落盘（mtime 不变）
    assert store._index_path.stat().st_mtime_ns == before

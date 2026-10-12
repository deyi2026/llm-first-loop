from __future__ import annotations

from types import SimpleNamespace

from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.tools_status import run_search_records
from llm_loop.memory.archive import ArchiveStore
from llm_loop.memory.store import MemoryEntry, MemoryStore


class _SemanticStub:
    def __init__(self, entries: list[dict], mode: str = "semantic") -> None:
        self.entries = entries
        self.mode = mode
        self.calls = 0

    def semantic_available(self) -> bool:
        return True

    def search(self, *args, **kwargs):
        self.calls += 1
        return SimpleNamespace(entries=list(self.entries), mode=self.mode, note="")


def _tool_receipt(searcher: RecordSearcher, *, kind: str, query: str, sid: str = ""):
    return run_search_records(
        None,
        lambda **kw: searcher.search(**kw),
        {"kind": kind, "query": query, "limit": 5},
        lambda: sid,
    )


def test_memory_semantic_hit_is_canonically_rehydrated_before_render(tmp_path):
    memory = MemoryStore(tmp_path / "memory")
    entry = memory.save_entry(
        MemoryEntry(
            id="MEM-CANONICAL",
            type="fact",
            content="权威 memory 正文，校验码 CANON-7319。",
            keywords=["权威记忆"],
            summary="",
        )
    )
    semantic = _SemanticStub(
        [
            {
                "kind": "memory",
                "id": entry.id,
                "key": f"memory:{entry.id}",
                "content": "vectorization-only payload",
                "_semantic_score": 0.99,
            }
        ]
    )
    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit",
        memory_store=memory,
        semantic_retriever=semantic,
        semantic_memory_enabled=True,
    )

    receipt = _tool_receipt(searcher, kind="memory", query="完全不同的同义问法")

    assert semantic.calls == 1
    assert "CANON-7319" in receipt.content
    assert "[] memory:" not in receipt.content
    assert "vectorization-only payload" not in receipt.content
    assert searcher.semantic_diagnostics == {
        "scope": "memory",
        "canonical_hydration_failures": 0,
        "empty_render_count": 0,
    }


def test_memory_semantic_projection_cannot_erase_keyword_control(tmp_path):
    memory = MemoryStore(tmp_path / "memory")
    entry = memory.save_entry(
        MemoryEntry(
            id="MEM-KEYWORD",
            type="fact",
            content="event_logs request.usage tokens_in 校验码 CTRL-2048。",
            keywords=["event_logs", "request.usage", "tokens_in"],
            summary="",
        )
    )
    semantic = _SemanticStub(
        [
            {
                "kind": "memory",
                "id": entry.id,
                "key": f"memory:{entry.id}",
                "content": "semantic compact projection",
            }
        ],
        mode="mixed",
    )
    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit",
        memory_store=memory,
        semantic_retriever=semantic,
        semantic_memory_enabled=True,
    )

    receipt = _tool_receipt(
        searcher,
        kind="memory",
        query="event_logs request.usage tokens_in",
    )

    assert "CTRL-2048" in receipt.content
    assert "[] memory:" not in receipt.content


def test_memory_semantic_scope_off_never_calls_semantic(tmp_path):
    memory = MemoryStore(tmp_path / "memory")
    memory.save_entry(
        MemoryEntry(
            id="MEM-OFF",
            type="fact",
            content="keyword-only visible",
            keywords=["keyword-only"],
        )
    )
    semantic = _SemanticStub([])
    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit",
        memory_store=memory,
        semantic_retriever=semantic,
        semantic_memory_enabled=False,
    )

    receipt = _tool_receipt(searcher, kind="memory", query="keyword-only")

    assert semantic.calls == 0
    assert "keyword-only visible" in receipt.content


def test_archive_semantic_hit_is_canonically_rehydrated(tmp_path):
    archive = ArchiveStore(tmp_path / "archive")
    sid = "semantic-archive"
    archive.archive(
        sid,
        role="user",
        source="user",
        content="用户声明喜欢蓝色。档案校验码 ARCH-7492。",
        summary_override="用户声明喜欢蓝色。",
        key_facts_override=["ARCH-7492"],
    )
    canonical = archive.search(sid, "", limit=1)[0]
    semantic = _SemanticStub(
        [
            {
                "kind": "archive",
                "id": canonical["id"],
                "key": f"archive:{canonical['id']}",
                "content": "vectorization-only archive payload",
            }
        ]
    )
    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit",
        archive_store=archive,
        semantic_retriever=semantic,
        semantic_archive_enabled=True,
    )

    hits = searcher.search(
        kind="archive",
        query="喜欢的色彩",
        limit=5,
        session_id=sid,
    )

    assert semantic.calls == 1
    assert len(hits) == 1
    assert hits[0]["id"] == canonical["id"]
    assert hits[0]["summary"] == canonical["summary"]
    assert hits[0]["content_preview"] == canonical["content_preview"]
    assert "vectorization-only archive payload" not in str(hits[0])
    assert searcher.semantic_diagnostics == {
        "scope": "archive",
        "canonical_hydration_failures": 0,
        "empty_render_count": 0,
    }
    receipt = _tool_receipt(
        searcher,
        kind="archive",
        query="喜欢的色彩",
        sid=sid,
    )
    assert "archive_ref=" in receipt.content
    assert "ARCH-7492" in receipt.content
    assert "vectorization-only archive payload" not in receipt.content

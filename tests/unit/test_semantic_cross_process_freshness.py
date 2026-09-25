from __future__ import annotations

import time

from llm_loop.memory.retriever import SemanticRetriever
from llm_loop.memory.store import MemoryEntry, MemoryStore


class _MeaningAPI:
    provider = "api"
    vector_version = "api-v1:freshness-test"
    timeout_s = 1.0
    _BATCH_CHUNK = 16

    @staticmethod
    def _vec(text: str) -> list[float]:
        lowered = text.lower()
        if "new meaning" in lowered or "new query" in lowered:
            return [1.0, 0.0]
        return [0.0, 1.0]

    def embed_with_timeout(self, text: str, *, timeout_s: float, request_class: str):
        return self._vec(text)

    def embed(self, text: str):
        return self._vec(text)

    def embed_batch(self, texts: list[str]):
        return [self._vec(text) for text in texts]


def _wait_background(r: SemanticRetriever, timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not r._background_diag_snapshot()["background_prewarm_inflight"]:
            return
        time.sleep(0.005)
    raise AssertionError("background prewarm did not finish")


def test_long_lived_memory_reader_refreshes_remote_new_and_updated_value(tmp_path):
    root = tmp_path / "memory"
    writer = MemoryStore(root)
    initial = writer.save_entry(
        MemoryEntry(
            id="shared",
            type="fact",
            content="old meaning topic",
            keywords=["topic"],
        )
    )
    reader = MemoryStore(root)
    assert reader._by_id(initial.id).content == "old meaning topic"

    created = writer.save_entry(
        MemoryEntry(
            id="remote-new",
            type="fact",
            content="another independent fact",
            keywords=["independent"],
        )
    )
    assert reader._by_id(created.id) is not None

    updated = writer.save_entry(
        MemoryEntry(
            id="ignored-on-update",
            type="fact",
            content="new meaning topic",
            keywords=["topic"],
        )
    )
    assert updated.id == initial.id
    refreshed = reader._by_id(initial.id)
    assert refreshed is not None
    assert refreshed.version == 2
    assert refreshed.content == "new meaning topic"


def test_independent_retriever_writes_merge_without_losing_vectors(tmp_path):
    root = tmp_path / "memory"
    root.mkdir()
    a = SemanticRetriever(_MeaningAPI(), timeout_s=1.0, memory_dir=root)
    b = SemanticRetriever(_MeaningAPI(), timeout_s=1.0, memory_dir=root)
    cand_a = {
        "kind": "memory",
        "id": "a",
        "key": "memory:a",
        "content": "old meaning a",
    }
    cand_b = {
        "kind": "memory",
        "id": "b",
        "key": "memory:b",
        "content": "new meaning b",
    }

    assert a._schedule_background_prewarm([cand_a], a._primary_engine())
    _wait_background(a)
    assert b._schedule_background_prewarm([cand_b], b._primary_engine())
    _wait_background(b)

    c = SemanticRetriever(_MeaningAPI(), timeout_s=1.0, memory_dir=root)
    key_a = c._vector_cache_key(cand_a)
    key_b = c._vector_cache_key(cand_b)
    assert key_a in c._mem_emb_cache
    assert key_b in c._mem_emb_cache
    assert c._mem_cache_path is not None
    assert "-ck2.json" in c._mem_cache_path.name


def test_long_lived_reader_observes_remote_vector_update_without_restart(tmp_path):
    root = tmp_path / "memory"
    writer_mem = MemoryStore(root)
    initial = writer_mem.save_entry(
        MemoryEntry(
            id="shared",
            type="fact",
            content="old meaning topic",
            keywords=["topic"],
        )
    )
    reader_mem = MemoryStore(root)

    writer_ret = SemanticRetriever(_MeaningAPI(), timeout_s=1.0, memory_dir=root)
    reader_ret = SemanticRetriever(_MeaningAPI(), timeout_s=1.0, memory_dir=root)
    writer_mem.add_post_save_hook(writer_ret.schedule_memory_entry)
    # Seed the first durable vector after both retrievers have loaded their independent
    # in-memory cache snapshots.
    assert writer_ret.schedule_memory_entry(initial)
    _wait_background(writer_ret)

    old = reader_ret.search(
        "old query",
        scope="memory",
        memory=reader_mem,
        keyword_results=[],
        top_k=5,
    )
    assert old.diagnostics["cache_files_refreshed"] >= 1
    assert [row["id"] for row in old.entries] == ["shared"]

    updated = writer_mem.save_entry(
        MemoryEntry(
            id="ignored-on-update",
            type="fact",
            content="new meaning topic",
            keywords=["topic"],
        )
    )
    assert updated.id == "shared"
    _wait_background(writer_ret)

    new = reader_ret.search(
        "new query",
        scope="memory",
        memory=reader_mem,
        keyword_results=[],
        top_k=5,
    )
    assert new.diagnostics["cache_files_refreshed"] >= 1
    assert [row["id"] for row in new.entries] == ["shared"]
    assert reader_mem._by_id("shared").content == "new meaning topic"

    # Old vector may still exist physically under its old content-bound ck2 key, but
    # current candidate lookup cannot consume it because the content fingerprint changed.
    stale = reader_ret.search(
        "old query",
        scope="memory",
        memory=reader_mem,
        keyword_results=[],
        top_k=5,
    )
    assert stale.diagnostics["semantic_hit_count"] == 0
    assert stale.entries == []

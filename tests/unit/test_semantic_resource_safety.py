from __future__ import annotations

import time

from llm_loop.memory.archive import ArchiveStore
from llm_loop.memory.embedder import APIEmbedder, HashEmbedder
from llm_loop.memory.retriever import SemanticRetriever
from llm_loop.memory.store import MemoryEntry, MemoryStore
from llm_loop.methods.store import MethodStore


class _FakeAPI:
    provider = "api"
    vector_version = "api-v1:resource-test"
    timeout_s = 5.0

    def __init__(
        self,
        *,
        query_delay: float = 0.0,
        prewarm_delay: float = 0.0,
        rank_batch_delay: float = 0.0,
    ) -> None:
        self.query_delay = query_delay
        self.prewarm_delay = prewarm_delay
        self.rank_batch_delay = rank_batch_delay
        self.query_timeouts: list[float] = []
        self.query_classes: list[str] = []
        self.rank_batch_timeouts: list[float] = []
        self.rank_batch_classes: list[str] = []
        self.rank_batch_chunk_sizes: list[int] = []
        self.batch_calls = 0

    def embed_with_timeout(self, text: str, *, timeout_s: float, request_class: str):
        self.query_timeouts.append(timeout_s)
        self.query_classes.append(request_class)
        if self.query_delay:
            time.sleep(min(self.query_delay, timeout_s + 0.02))
            if self.query_delay >= timeout_s:
                return None
        return [1.0, 0.0]

    def embed(self, text: str):
        return [1.0, 0.0]

    def embed_batch(self, texts: list[str]):
        self.batch_calls += 1
        if self.prewarm_delay:
            time.sleep(self.prewarm_delay)
        return [[1.0, 0.0] for _ in texts]

    def embed_batch_with_timeout(
        self,
        texts: list[str],
        *,
        timeout_s: float,
        request_class: str,
        chunk_size: int = 16,
    ):
        self.rank_batch_timeouts.append(timeout_s)
        self.rank_batch_classes.append(request_class)
        self.rank_batch_chunk_sizes.append(chunk_size)
        if self.rank_batch_delay:
            time.sleep(min(self.rank_batch_delay, timeout_s + 0.02))
            if self.rank_batch_delay >= timeout_s:
                return [None] * len(texts)
        return [[1.0, 0.0] for _ in texts]


def _memory(tmp_path, n: int = 4) -> MemoryStore:
    mem = MemoryStore(tmp_path / "memory")
    for i in range(n):
        mem.save_entry(
            MemoryEntry(
                id=f"m{i}",
                type="fact",
                content=f"semantic resource fact {i}",
                keywords=[f"k{i}"],
            )
        )
    return mem


def _wait_background(r: SemanticRetriever, timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not r._background_diag_snapshot()["background_prewarm_inflight"]:
            return
        time.sleep(0.005)
    raise AssertionError("background prewarm did not finish")


def test_foreground_query_uses_retrieval_owned_deadline(tmp_path):
    mem = _memory(tmp_path)
    emb = _FakeAPI(query_delay=1.0)
    r = SemanticRetriever(emb, timeout_s=0.1, memory_dir=tmp_path / "memory")
    keyword = [{"id": "kw", "key": "memory:kw", "content": "keyword fallback"}]

    started = time.monotonic()
    result = r.search("query", scope="memory", memory=mem, keyword_results=keyword)
    elapsed = time.monotonic() - started

    assert elapsed < 0.2
    assert result.mode == "keyword"
    assert result.entries == keyword
    assert result.diagnostics["semantic_fallback_reason"] == "query_embedding_timeout"
    assert emb.query_timeouts and emb.query_timeouts[0] <= 0.081
    assert emb.query_classes == ["foreground"]


def test_foreground_queue_timeout_is_preserved_as_fallback_reason(tmp_path):
    mem = _memory(tmp_path)

    class QueueTimeoutAPI(_FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self.last_diagnostics = {"error": "queue_timeout"}

        def embed_with_timeout(
            self, text: str, *, timeout_s: float, request_class: str
        ):
            self.query_timeouts.append(timeout_s)
            self.query_classes.append(request_class)
            return None

    emb = QueueTimeoutAPI()
    r = SemanticRetriever(emb, timeout_s=1.0, memory_dir=tmp_path / "memory")
    result = r.search("query", scope="memory", memory=mem, keyword_results=[])
    assert result.mode == "keyword"
    assert result.diagnostics["semantic_fallback_reason"] == "queue_timeout"


def test_rank_texts_candidate_batch_obeys_retrieval_deadline():
    emb = _FakeAPI(rank_batch_delay=1.0)
    r = SemanticRetriever(emb, timeout_s=0.1)

    started = time.monotonic()
    ranked = r.rank_texts("query", [f"candidate {i}" for i in range(20)])
    elapsed = time.monotonic() - started

    assert ranked == []
    assert elapsed < 0.2
    assert emb.rank_batch_timeouts
    assert emb.rank_batch_timeouts[0] <= 0.101
    assert emb.rank_batch_classes == ["foreground"]
    assert emb.rank_batch_chunk_sizes == [8]
    assert r.last_rank_texts_diagnostics["semantic_effective"] is False
    assert r.last_rank_texts_diagnostics["semantic_fallback_reason"]


def test_rank_texts_primary_failure_does_not_hash_reorder_docs():
    emb = _FakeAPI(query_delay=1.0)
    r = SemanticRetriever(
        emb,
        timeout_s=0.1,
        fallback_embedder=HashEmbedder(dim=32),
    )

    ranked = r.rank_texts("飞书", ["unrelated 飞书", "飞书渲染支持矩阵"])

    assert ranked == []
    assert r.last_rank_texts_diagnostics["semantic_effective"] is False
    assert r.last_rank_texts_diagnostics["engine"] == ""
    assert (
        r.last_rank_texts_diagnostics["semantic_fallback_reason"]
        == "query_embedding_timeout"
    )


def test_api_cold_cache_prewarm_is_background_and_next_query_consumes_it(tmp_path):
    mem = _memory(tmp_path, n=8)
    emb = _FakeAPI(prewarm_delay=0.2)
    r = SemanticRetriever(emb, timeout_s=1.0, memory_dir=tmp_path / "memory")

    started = time.monotonic()
    cold = r.search("query", scope="memory", memory=mem)
    elapsed = time.monotonic() - started

    assert elapsed < 0.1
    assert cold.entries == []
    assert cold.diagnostics["candidate_missing_count"] == 8
    assert cold.diagnostics["prewarm_scheduled"] is True
    assert cold.diagnostics["background_prewarm_inflight"] is True

    _wait_background(r)
    warm = r.search("query", scope="memory", memory=mem)
    assert warm.entries
    assert warm.diagnostics["candidate_missing_count"] == 0
    assert warm.diagnostics["prewarm_scheduled"] is False
    assert emb.batch_calls == 1
    assert r._mem_cache_path is not None and r._mem_cache_path.exists()


def test_runtime_background_prewarm_is_incrementally_capped(tmp_path):
    """运行时只小批修补；大规模冷缓存必须交给显式 warmup job."""
    mem = _memory(tmp_path, n=100)
    emb = _FakeAPI()
    r = SemanticRetriever(emb, timeout_s=1.0, memory_dir=tmp_path / "memory")

    cold = r.search("query", scope="memory", memory=mem)
    assert cold.diagnostics["candidate_missing_count"] == 100
    assert cold.diagnostics["prewarm_scheduled"] is True
    _wait_background(r)

    assert len(r._mem_emb_cache) == r._BACKGROUND_PREWARM_MAX == 32
    assert r._background_diag_snapshot()["last_prewarm_count"] == 32


def test_api_embedder_emits_foreground_deadline_and_background_class(monkeypatch):
    api = APIEmbedder(
        api_key="",
        base_url="http://127.0.0.1:9/v1",
        model="bge",
        timeout_s=5.0,
    )
    calls: list[dict] = []

    class _Resp:
        status_code = 200

        def __init__(self, n: int):
            self.n = n

        def json(self):
            return {
                "x_lfl": {
                    "queue_wait_ms": 3.0,
                    "encode_ms": 7.0,
                    "batch_size": self.n,
                },
                "data": [{"embedding": [1.0, 0.0]} for _ in range(self.n)],
            }

    def fake_post(_url, **kwargs):
        calls.append(kwargs)
        payload = kwargs["json"]["input"]
        return _Resp(len(payload) if isinstance(payload, list) else 1)

    monkeypatch.setattr(api._client, "post", fake_post)

    assert api.embed_with_timeout("q", timeout_s=0.25, request_class="foreground")
    assert api.last_diagnostics["queue_wait_ms"] == 3.0
    assert calls[-1]["timeout"] == 0.25
    assert calls[-1]["headers"]["X-LFL-Embedding-Class"] == "foreground"
    assert calls[-1]["headers"]["X-LFL-Embedding-Deadline-Ms"] == "87"

    assert api.embed_batch(["a", "b"])
    assert calls[-1]["headers"]["X-LFL-Embedding-Class"] == "background"


def test_startup_warm_makes_existing_api_memory_available_on_first_search(tmp_path):
    mem = _memory(tmp_path, n=3)
    emb = _FakeAPI()
    r = SemanticRetriever(emb, timeout_s=1.0, memory_dir=tmp_path / "memory")

    diag = r.warm_memory_store(mem)
    assert diag["initial_missing"] == 3
    assert diag["remaining_missing"] == 0

    result = r.search("query", scope="memory", memory=mem)
    assert result.entries
    assert result.diagnostics["candidate_missing_count"] == 0
    assert result.diagnostics["prewarm_scheduled"] is False


def test_startup_warm_caches_session_memory_without_granting_cross_session_visibility(
    tmp_path,
):
    mem = MemoryStore(tmp_path / "memory")
    mem.save_entry(
        MemoryEntry(
            id="session-only",
            type="fact",
            content="session scoped semantic fact",
            keywords=["scoped"],
            scope="session",
            source_session_id="owner-session",
        )
    )
    emb = _FakeAPI()
    r = SemanticRetriever(emb, timeout_s=1.0, memory_dir=tmp_path / "memory")

    diag = r.warm_memory_store(mem)
    assert diag["initial_missing"] == 1
    assert diag["remaining_missing"] == 0

    hidden = r.search("query", scope="memory", memory=mem, session_id="")
    assert hidden.entries == []
    visible = r.search(
        "query", scope="memory", memory=mem, session_id="owner-session"
    )
    assert [row["id"] for row in visible.entries] == ["session-only"]


def test_archive_write_vectors_in_background_and_first_query_is_hot(tmp_path):
    archive = ArchiveStore(tmp_path / "archive")
    emb = _FakeAPI(prewarm_delay=0.05)
    retriever = SemanticRetriever(
        emb,
        timeout_s=1.0,
        archive_dir=tmp_path / "archive",
    )
    archive.add_post_save_hook(retriever.schedule_archive_entry)

    started = time.monotonic()
    target = archive.archive(
        "owner-session",
        role="user",
        source="user",
        content="new meaning archive target",
        summary_override="new meaning archive target",
        key_facts_override=["new meaning"],
    )
    save_ms = (time.monotonic() - started) * 1000
    assert save_ms < 30
    _wait_background(retriever)

    owner = retriever.search(
        "new query",
        scope="archive",
        session_id="owner-session",
        archive=archive,
        keyword_results=[],
        top_k=5,
    )
    assert owner.diagnostics["candidate_missing_count"] == 0
    assert owner.entries and owner.entries[0]["id"] == target.id

    other = retriever.search(
        "new query",
        scope="archive",
        session_id="other-session",
        archive=archive,
        keyword_results=[],
        top_k=5,
    )
    assert all(row.get("id") != target.id for row in other.entries)


def test_method_startup_warm_makes_existing_candidates_hot(tmp_path):
    methods = MethodStore(tmp_path / "methods")
    target = methods.save_candidate(
        name="Service restart verification",
        description="Verify runtime artifacts after restarting a long-lived service.",
        body=(
            "## Trigger\nafter restart\n\n## Discriminator\nlong-lived service\n\n"
            "## Short path\ninspect live process identity\n\n## Stop conditions\nconfig matches artifacts\n\n"
            "## Verification\ncurrentness action recorded\n\n## Counterexamples\nnone yet"
        ),
    )
    emb = _FakeAPI()
    retriever = SemanticRetriever(emb, timeout_s=1.0)
    retriever.configure_method_dir(tmp_path / "methods")

    diag = retriever.warm_method_store(methods)
    assert diag["candidate_count"] == 1
    assert diag["initial_missing"] == 1
    assert diag["remaining_missing"] == 0

    result = retriever.search(
        "how do I verify a restarted daemon really loaded the change",
        scope="method",
        method=methods,
        keyword_results=[],
        top_k=5,
    )
    assert result.diagnostics["candidate_missing_count"] == 0
    assert result.entries and result.entries[0]["key"] == target.method_ref


def test_new_method_candidate_vectors_after_durable_write(tmp_path):
    methods = MethodStore(tmp_path / "methods")
    emb = _FakeAPI(prewarm_delay=0.05)
    retriever = SemanticRetriever(emb, timeout_s=1.0)
    retriever.configure_method_dir(tmp_path / "methods")
    methods.add_post_save_hook(
        lambda record: retriever.schedule_method_candidate(
            methods.semantic_candidate(record)
        )
    )

    started = time.monotonic()
    target = methods.save_candidate(
        name="Cache truth source",
        description="Use provider usage counters as the authoritative cache-hit source.",
        body=(
            "## Trigger\nmeasuring cache hits\n\n## Discriminator\nprovider usage counters available\n\n"
            "## Short path\nread usage counters\n\n## Stop conditions\ncounters unavailable\n\n"
            "## Verification\ncompare counter delta\n\n## Counterexamples\nprompt length inference"
        ),
    )
    save_ms = (time.monotonic() - started) * 1000
    assert save_ms < 30
    _wait_background(retriever)

    result = retriever.search(
        "how should cache hit truth be measured",
        scope="method",
        method=methods,
        keyword_results=[],
        top_k=5,
    )
    assert result.diagnostics["candidate_missing_count"] == 0
    assert result.entries and result.entries[0]["key"] == target.method_ref


def test_memory_save_hook_schedules_new_vector_without_blocking_save(tmp_path):
    mem = MemoryStore(tmp_path / "memory")
    emb = _FakeAPI(prewarm_delay=0.05)
    r = SemanticRetriever(emb, timeout_s=1.0, memory_dir=tmp_path / "memory")
    mem.add_post_save_hook(r.schedule_memory_entry)

    started = time.monotonic()
    saved = mem.save_entry(
        MemoryEntry(
            id="new-memory",
            type="fact",
            content="new semantic fact",
            keywords=["new"],
        )
    )
    save_ms = (time.monotonic() - started) * 1000
    assert save_ms < 30
    assert saved.id == "new-memory"
    _wait_background(r)
    assert any(k.startswith("memory:new-memory#sha256:") for k in r._mem_emb_cache)


def test_memory_saves_during_active_prewarm_are_coalesced_not_lost(tmp_path):
    mem = MemoryStore(tmp_path / "memory")
    emb = _FakeAPI(prewarm_delay=0.08)
    r = SemanticRetriever(emb, timeout_s=1.0, memory_dir=tmp_path / "memory")
    mem.add_post_save_hook(r.schedule_memory_entry)

    mem.save_entry(
        MemoryEntry(id="m-a", type="fact", content="fact a", keywords=["a"])
    )
    time.sleep(0.01)
    mem.save_entry(
        MemoryEntry(id="m-b", type="fact", content="fact b", keywords=["b"])
    )
    _wait_background(r)
    assert any(k.startswith("memory:m-a#sha256:") for k in r._mem_emb_cache)
    assert any(k.startswith("memory:m-b#sha256:") for k in r._mem_emb_cache)


def test_memory_post_save_hook_failure_never_breaks_durable_save(tmp_path):
    mem = MemoryStore(tmp_path / "memory")

    def boom(_entry):
        raise RuntimeError("derived cache failed")

    mem.add_post_save_hook(boom)
    saved = mem.save_entry(
        MemoryEntry(id="durable", type="fact", content="still durable")
    )
    assert saved.id == "durable"
    assert MemoryStore(tmp_path / "memory")._by_id("durable") is not None

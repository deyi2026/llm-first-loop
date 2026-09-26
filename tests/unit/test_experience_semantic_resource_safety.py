from __future__ import annotations

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.memory.retriever import SemanticRetriever


class _FakeAPIEmbedder:
    provider = "api"
    vector_version = "experience-test-v1"
    model = "fake"
    base_url = "http://127.0.0.1:9/v1"
    timeout_s = 1.0

    def __init__(self) -> None:
        self.query_calls = 0
        self.batch_calls = 0
        self.last_diagnostics: dict = {}

    def embed_with_timeout(self, text: str, *, timeout_s: float, request_class: str = "foreground"):
        self.query_calls += 1
        self.last_diagnostics = {
            "request_class": request_class,
            "queue_wait_ms": 0.0,
            "encode_ms": 1.0,
            "http_ms": 1.0,
            "error": "",
        }
        return [1.0, 0.0] if "target" in text or text == "query" else [0.0, 1.0]

    def embed(self, text: str):
        return self.embed_with_timeout(text, timeout_s=1.0)

    def embed_batch(self, texts: list[str]):
        self.batch_calls += 1
        return [[1.0, 0.0] if "target" in text else [0.0, 1.0] for text in texts]


def _candidate(key: str, content: str, *, kind: str = "experience") -> dict:
    return {"kind": kind, "id": key, "key": f"experience:{key}", "content": content}


def _doc(title: str, *, kind: str = "experience") -> ExperienceDocument:
    return ExperienceDocument(
        title=title,
        scenario=f"scenario {title}",
        root_cause=f"cause {title}",
        solution=f"solution {title}",
        evidence="fixture",
        tags=["fixture"],
        source={"kind": "test"},
        record_kind=kind,
        verification_state="verified",
    )


def test_remote_cache_cold_fails_open_without_foreground_embedding(tmp_path, monkeypatch):
    embedder = _FakeAPIEmbedder()
    retriever = SemanticRetriever(embedder, timeout_s=0.2)
    retriever.configure_experience_cache_dir(tmp_path / "cache")
    scheduled: list[list[dict]] = []
    monkeypatch.setattr(
        retriever,
        "_schedule_background_prewarm",
        lambda candidates, _engine: scheduled.append(list(candidates)) or True,
    )
    candidates = [_candidate("a", "target alpha"), _candidate("b", "beta")]

    ranked = retriever.rank_cached_candidates("query", candidates)

    assert ranked == []
    assert embedder.query_calls == 0
    assert len(scheduled) == 1
    assert retriever.last_cached_rank_diagnostics["semantic_fallback_reason"] == "candidate_cache_cold"
    assert retriever.last_cached_rank_diagnostics["candidate_missing_count"] == 2
    assert retriever.last_cached_rank_diagnostics["prewarm_scheduled"] is True


def test_hot_cache_ranking_embeds_only_query(tmp_path):
    embedder = _FakeAPIEmbedder()
    retriever = SemanticRetriever(embedder, timeout_s=0.2)
    retriever.configure_experience_cache_dir(tmp_path / "cache")
    candidates = [_candidate("a", "target alpha"), _candidate("b", "beta")]
    retriever._experience_emb_cache[retriever._vector_cache_key(candidates[0])] = [1.0, 0.0]  # noqa: SLF001
    retriever._experience_emb_cache[retriever._vector_cache_key(candidates[1])] = [0.0, 1.0]  # noqa: SLF001

    ranked = retriever.rank_cached_candidates("query", candidates)

    assert ranked[0][0] == 0
    assert embedder.query_calls == 1
    assert embedder.batch_calls == 0
    assert retriever.last_cached_rank_diagnostics["semantic_effective"] is True
    assert retriever.last_cached_rank_diagnostics["candidate_missing_count"] == 0


def test_startup_warm_persists_experience_vectors(tmp_path):
    exp_dir = tmp_path / "experiences"
    store = ExperienceStore(exp_dir)
    store.save(_doc("target alpha"))
    store.save(_doc("beta"))
    store.save(_doc("lesson gamma", kind="lesson"))
    embedder = _FakeAPIEmbedder()
    retriever = SemanticRetriever(embedder, timeout_s=0.2)
    cache_dir = tmp_path / "experience-cache"
    retriever.configure_experience_cache_dir(cache_dir)

    result = retriever.warm_experience_store(store)

    assert result["candidate_count"] == 3
    assert result["initial_missing"] == 3
    assert result["remaining_missing"] == 0
    assert embedder.batch_calls >= 1
    assert any(cache_dir.glob("embeddings-*.json"))


def test_store_cached_ranker_can_recall_lexical_miss_without_crossing_record_kind(tmp_path):
    exp_dir = tmp_path / "experiences"
    writer = ExperienceStore(exp_dir)
    exp_a = writer.save(_doc("alpha reusable"))
    exp_b = writer.save(_doc("semantic target"))
    writer.save(_doc("lesson semantic target", kind="lesson"))

    class _Ranker:
        last_cached_rank_diagnostics = {
            "semantic_requested": True,
            "semantic_effective": True,
            "semantic_fallback_reason": "",
        }

        def rank_cached_candidates(self, _query, candidates, *, top_k=None):
            rows = []
            for index, candidate in enumerate(candidates):
                score = 0.99 if candidate["id"] == exp_b.removesuffix(".md") else 0.1
                rows.append((index, score))
            return sorted(rows, key=lambda item: item[1], reverse=True)[:top_k]

    ranker = _Ranker()
    store = ExperienceStore(exp_dir, semantic_ranker=ranker.rank_cached_candidates)

    rows = store.search_outcome("完全不同的改写", 5, record_kind="experience").records

    assert rows[0]["id"] == exp_b.removesuffix(".md")
    assert exp_a.removesuffix(".md") in {row["id"] for row in rows}
    assert all(row["record_kind"] == "experience" for row in rows)
    assert store.last_semantic_diagnostics["semantic_effective"] is True


def test_store_cache_cold_preserves_lexical_results_and_marks_degradation(tmp_path):
    exp_dir = tmp_path / "experiences"
    writer = ExperienceStore(exp_dir)
    target = writer.save(_doc("service control restart"))

    class _ColdRanker:
        last_cached_rank_diagnostics = {
            "semantic_requested": True,
            "semantic_effective": False,
            "semantic_fallback_reason": "candidate_cache_cold",
        }

        def rank_cached_candidates(self, _query, _candidates, *, top_k=None):
            return []

    ranker = _ColdRanker()
    store = ExperienceStore(exp_dir, semantic_ranker=ranker.rank_cached_candidates)

    rows = store.search_outcome("service control restart", 5, record_kind="experience").records

    assert rows[0]["id"] == target.removesuffix(".md")
    assert "[语义检索降级]" in rows[0]["degraded"]
    assert store.last_semantic_diagnostics["semantic_fallback_reason"] == "candidate_cache_cold"


def test_post_save_hook_receives_stable_semantic_candidate(tmp_path):
    store = ExperienceStore(tmp_path / "experiences")
    captured: list[dict] = []
    store.add_post_save_hook(captured.append)

    filename = store.save(_doc("post save vector"))

    assert len(captured) == 1
    assert captured[0]["key"] == f"experience:{filename.removesuffix('.md')}"
    assert captured[0]["kind"] == "experience"
    assert "post save vector" in captured[0]["content"]


def test_cross_process_cache_refresh_uses_persisted_experience_vectors(tmp_path):
    exp_dir = tmp_path / "experiences"
    store = ExperienceStore(exp_dir)
    store.save(_doc("target alpha"))
    store.save(_doc("beta"))
    cache_dir = tmp_path / "experience-cache"

    writer_embedder = _FakeAPIEmbedder()
    writer = SemanticRetriever(writer_embedder, timeout_s=0.2)
    writer.configure_experience_cache_dir(cache_dir)
    reader_embedder = _FakeAPIEmbedder()
    reader = SemanticRetriever(reader_embedder, timeout_s=0.2)
    reader.configure_experience_cache_dir(cache_dir)

    warm = writer.warm_experience_store(store)
    candidates = store.semantic_candidates(record_kind="experience")
    ranked = reader.rank_cached_candidates("query", candidates)

    assert warm["remaining_missing"] == 0
    assert ranked
    assert reader_embedder.query_calls == 1
    assert reader_embedder.batch_calls == 0
    assert reader.last_cached_rank_diagnostics["cache_files_refreshed"] >= 1

from __future__ import annotations

from dataclasses import replace

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore


def _doc(
    title: str,
    *,
    scenario: str = "",
    root_cause: str = "",
    solution: str = "",
    tags: list[str] | None = None,
) -> ExperienceDocument:
    return ExperienceDocument(
        title=title,
        scenario=scenario,
        root_cause=root_cause,
        solution=solution,
        evidence="e",
        tags=tags or [],
        source={"test": "ranking-cache"},
        status="active",
    )


class _CountingEmbedder:
    provider = "counting"
    vector_version = "v1"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        total = sum(ord(ch) for ch in text)
        return [float((total % 17) + 1), float((len(text) % 13) + 1)]


class _AdversarialEmbedder:
    provider = "adversarial"
    vector_version = "v1"

    def embed(self, text: str) -> list[float]:
        if text == "fail-open callsite argument evaluation":
            return [1.0, 0.0]
        if "semantic-distractor" in text:
            return [1.0, 0.0]
        return [0.0, 1.0]


def test_long_natural_query_uses_weighted_terms_instead_of_whole_query_substring(tmp_path):
    store = ExperienceStore(tmp_path / "exp")
    store.save(
        _doc(
            "fail-open callsite argument evaluation",
            scenario="observer 内部 try except 捕获范围与调用点参数求值",
            root_cause="ValueError 在进入被调函数之前由参数表达式求值抛出",
            solution="把可能失败的参数求值移动到 try 内部再调用",
            tags=["observer", "fail-open"],
        )
    )
    store.save(
        _doc(
            "PDF report rendering",
            scenario="生成报告并修复图片布局",
            solution="调整 Markdown 与页面排版",
            tags=["pdf"],
        )
    )

    results = store.list_active(
        "observer 内部 try except 为什么接不住调用点参数求值 ValueError 怎么修",
        5,
    )

    assert results
    assert results[0]["summary"] == "fail-open callsite argument evaluation"
    assert results[0]["score"] is not None


def test_weighted_lexical_prefers_title_over_solution_only_match(tmp_path):
    store = ExperienceStore(tmp_path / "exp")
    store.save(_doc("cache prefix stability", scenario="provider prefix reuse"))
    store.save(_doc("unrelated transport note", solution="cache"))

    results = store.list_active("cache", 5)

    assert [row["summary"] for row in results[:2]] == [
        "cache prefix stability",
        "unrelated transport note",
    ]
    assert results[0]["score"] > results[1]["score"]


def test_document_embedding_cache_reuses_unchanged_docs_and_invalidates_changed_doc(tmp_path):
    embedder = _CountingEmbedder()
    store = ExperienceStore(tmp_path / "exp", embedder=embedder)
    first = store.save(_doc("alpha retrieval", solution="stable solution"))
    store.save(_doc("beta retrieval", solution="other solution"))

    store.list_active("retrieval query", 5)
    assert len(embedder.calls) == 3  # query + two documents

    store.list_active("retrieval query", 5)
    assert len(embedder.calls) == 4  # unchanged documents reused; query is intentionally fresh

    first_path = tmp_path / "exp" / first
    parsed = ExperienceDocument.from_md(first_path.read_text(encoding="utf-8"))
    first_path.write_text(replace(parsed, solution="changed solution").to_md(), encoding="utf-8")

    store.list_active("retrieval query", 5)
    assert len(embedder.calls) == 6  # query + only the changed document


def test_hybrid_ranking_keeps_strong_lexical_hit_above_semantic_only_noise(tmp_path):
    store = ExperienceStore(tmp_path / "exp", embedder=_AdversarialEmbedder())
    store.save(
        _doc(
            "fail-open callsite argument evaluation",
            scenario="argument evaluation happens before entering the callee",
            solution="move evaluation inside try",
        )
    )
    store.save(
        _doc(
            "semantic-distractor",
            scenario="unrelated PDF and browser workflow",
            solution="no relation to fail open",
        )
    )

    results = store.list_active("fail-open callsite argument evaluation", 5)

    assert results[0]["summary"] == "fail-open callsite argument evaluation"

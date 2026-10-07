"""EVO-20261007 method 消费闭环（B 面）: 记忆检索附带 Method 候选尾注.

B 面机制：search_records(kind=experience/lesson/memory) 时，searcher 用同一 query
附带检索 method（≤2 张 compact 卡，词法/语义 RRF），工具层在回执尾渲染
[Method 候选提示]；零命中/其他 kind/开关关闭时零噪声消失（无尾注）。

边界纪律（L2-2 可检索≠可注入 + 09-24 开场列表注入退役）：
- 条件触发：仅记忆检索已发生时附带，非开场无条件常驻
- query 对齐：附带候选与主检索同一 query，相关性由检索器背书
- 候选不裁决：尾注明示 task_applicability=not_evaluated，不替模型选方法
"""

from pathlib import Path

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.tools_status import run_search_records
from llm_loop.methods.store import MethodStore


def _doc(
    *,
    title: str,
    record_kind: str = "experience",
    verification_state: str = "verified",
) -> ExperienceDocument:
    return ExperienceDocument(
        title=title,
        scenario="browser edit retry scenario",
        root_cause="fixture cause",
        solution="fixture solution",
        evidence="fixture:evidence",
        tags=["browser"],
        source={"kind": "fixture"},
        status="active",
        record_kind=record_kind,
        verification_state=verification_state,
    )


def _seed_method(root: Path, key: str, *, status: str = "active", body: str = "") -> None:
    method_dir = root / key
    method_dir.mkdir(parents=True, exist_ok=True)
    (method_dir / "METHOD.md").write_text(
        "---\n"
        f"method_id: {key}\n"
        f"name: {key}\n"
        f"description: fixture method {key}\n"
        f"status: {status}\n"
        "---\n"
        f"{body or key}\n",
        encoding="utf-8",
    )


def _make_searcher(
    tmp_path: Path,
    *,
    with_experience: bool,
    with_method: bool,
    hint_enabled: bool = True,
) -> RecordSearcher:
    exp_store = ExperienceStore(tmp_path / "experiences")
    if with_experience:
        exp_store.save(_doc(title="browser retry lesson learned"))
    method_store = MethodStore(tmp_path / "methods")
    if with_method:
        _seed_method(tmp_path / "methods", "browser-retry", body="snapshot edit_file before retry browser")
    return RecordSearcher(
        audit_dir=tmp_path / "audit",
        experience_store=exp_store,
        method_store=method_store,
        method_related_hint_enabled=hint_enabled,
    )


def _render(searcher: RecordSearcher, *, kind: str, query: str) -> str:
    result = run_search_records(
        None,
        searcher.search,
        {"kind": kind, "query": query, "limit": 5},
        lambda: "",
    )
    return result.content


def test_experience_hit_appends_related_method_hint(tmp_path: Path) -> None:
    searcher = _make_searcher(tmp_path, with_experience=True, with_method=True)
    rendered = _render(searcher, kind="experience", query="browser retry")

    assert "[Method 候选提示（同 query 附带）]" in rendered
    assert "method:browser-retry" in rendered
    assert "task_applicability=not_evaluated" in rendered
    assert searcher.related_methods is not None
    assert len(searcher.related_methods) <= 2


def test_experience_miss_still_shows_method_hint(tmp_path: Path) -> None:
    """经验零命中但 method 有候选——消费缺口典型场景，尾注仍渲染."""
    searcher = _make_searcher(tmp_path, with_experience=False, with_method=True)
    rendered = _render(searcher, kind="experience", query="browser retry")

    assert "未找到匹配" in rendered
    assert "[Method 候选提示（同 query 附带）]" in rendered


def test_method_store_empty_yields_no_hint(tmp_path: Path) -> None:
    """method 零命中 → 零噪声降级，无尾注."""
    searcher = _make_searcher(tmp_path, with_experience=True, with_method=False)
    rendered = _render(searcher, kind="experience", query="browser retry")

    assert "[Method 候选提示" not in rendered
    assert searcher.related_methods is None


def test_other_kinds_do_not_collect_related_methods(tmp_path: Path) -> None:
    searcher = _make_searcher(tmp_path, with_experience=True, with_method=True)

    rendered_method = _render(searcher, kind="method", query="browser retry")
    assert searcher.related_methods is None
    assert "[Method 候选提示" not in rendered_method

    _render(searcher, kind="lesson", query="browser retry")
    assert searcher.related_methods is not None  # lesson 属记忆类，附带
    _render(searcher, kind="memory", query="browser retry")
    assert searcher.related_methods is not None  # memory 属记忆类，附带
    _render(searcher, kind="method", query="browser retry")
    assert searcher.related_methods is None  # 下一次非记忆检索重置


def test_exact_ref_query_does_not_collect(tmp_path: Path) -> None:
    """exact-ref 水合形态不是任务发现场景，不附带."""
    searcher = _make_searcher(tmp_path, with_experience=True, with_method=True)
    rendered = _render(searcher, kind="experience", query="experience:some-lesson-01")

    assert searcher.related_methods is None
    assert "[Method 候选提示" not in rendered


def test_hint_disabled_switch_suppresses_collection(tmp_path: Path) -> None:
    """METHOD_RELATED_HINT_ENABLED=False → 回到纯模型自律触发（A 面）."""
    searcher = _make_searcher(
        tmp_path, with_experience=True, with_method=True, hint_enabled=False
    )
    rendered = _render(searcher, kind="experience", query="browser retry")

    assert searcher.related_methods is None
    assert "[Method 候选提示" not in rendered


def test_related_collection_does_not_pollute_semantic_diagnostics(tmp_path: Path) -> None:
    """附带检索不得覆盖主结果的语义诊断透传（保存/恢复契约）."""
    _make_searcher(tmp_path, with_experience=True, with_method=True)

    class FakeSemanticEmbedder:
        provider = "fake"
        vector_version = "fake-v1"

        def embed(self, text: str) -> list[float]:
            return [1.0, 0.0] if "browser" in text.lower() else [0.0, 1.0]

    from llm_loop.memory.retriever import SemanticRetriever

    searcher_with_sem = RecordSearcher(
        audit_dir=tmp_path / "audit",
        experience_store=ExperienceStore(tmp_path / "experiences"),
        method_store=MethodStore(tmp_path / "methods"),
        semantic_retriever=SemanticRetriever(FakeSemanticEmbedder(), threshold=0.8),
        semantic_method_enabled=True,
    )
    searcher_with_sem.search(kind="experience", query="browser retry", limit=5)
    # related 被收集且主语义诊断未被附带检索污染（仍属 experience 主路径或 None）
    assert searcher_with_sem.related_methods is not None
    diag = searcher_with_sem.semantic_diagnostics
    if diag is not None:
        assert str(diag.get("scope", diag)).find("method") == -1

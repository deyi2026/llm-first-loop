"""docs/ 文档语义检索单元测试（DocsSearcher + run_search_docs）.

覆盖正常/边界/异常路径：分类/元数据提取/关键词匹配/检索流程/语义降级/路径限定/工具层回执。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.docs_search import (
    DocMeta,
    DocsSearcher,
    _classify_doc_type,
    _extract_doc_meta,
    _keyword_match,
)
from llm_loop.introspection.tools_docs import run_search_docs

# ── §6.1 DocsSearcher 单元测试 ──


class TestClassifyDocType:
    """_classify_doc_type: 14 种前缀分类."""

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("ASSESSMENT-20260813-system-optimization-review.md", "assessment"),
            ("ANALYSIS-20260812-feishu-audit.md", "analysis"),
            ("DESIGN-20260813-recovery-channel.md", "design"),
            ("SPEC-20260813-docs-search.md", "spec"),
            ("TASKS-20260813-docs-search.md", "tasks"),
            ("REFLECTION-20260813-m11.md", "reflection"),
            ("REPORT-20260813-weekly.md", "report"),
            ("ISSUE-20260813-bug123.md", "issue"),
            ("CHANGES.md", "changes"),
            ("INDEX.md", "index"),
            ("ai_rules.md", "rules"),
            ("ai_guidance_playbook.md", "playbook"),
            ("m11_audit_report.md", "milestone"),
            ("m48_model_switch_design.md", "milestone"),
            ("random_doc.md", "other"),
        ],
    )
    def test_classify(self, filename: str, expected: str) -> None:
        assert _classify_doc_type(Path(filename)) == expected


class TestExtractDocMeta:
    """_extract_doc_meta: 元数据提取."""

    def test_normal_markdown(self, tmp_path: Path) -> None:
        f = tmp_path / "DESIGN-test.md"
        f.write_text("# 设计文档标题\n\n这是摘要内容。", encoding="utf-8")
        meta = _extract_doc_meta(f)
        assert meta is not None
        assert meta.title == "设计文档标题"
        assert "摘要内容" in meta.summary
        assert meta.doc_type == "design"
        assert meta.ts != ""
        assert "设计文档标题" in meta.content

    def test_no_title_fallback_stem(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.md"
        f.write_text("无标题行直接正文。", encoding="utf-8")
        meta = _extract_doc_meta(f)
        assert meta is not None
        assert meta.title == "notes"

    def test_corrupt_file_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.md"
        f.write_bytes(b"\xff\xfe\x00\x01")
        meta = _extract_doc_meta(f)
        assert meta is None

    def test_nonexistent_file_returns_none(self, tmp_path: Path) -> None:
        meta = _extract_doc_meta(tmp_path / "nonexistent.md")
        assert meta is None


class TestKeywordMatch:
    """_keyword_match: 关键词全文匹配."""

    def test_match_in_title(self) -> None:
        meta = DocMeta(Path("x.md"), "优化策略", "", "design", "", "")
        assert _keyword_match("优化", meta)

    def test_match_in_summary(self) -> None:
        meta = DocMeta(Path("x.md"), "", "摘要含关键词", "design", "", "")
        assert _keyword_match("关键词", meta)

    def test_match_in_content(self) -> None:
        meta = DocMeta(Path("x.md"), "", "", "design", "", "正文含秘密词")
        assert _keyword_match("秘密", meta)

    def test_no_match(self) -> None:
        meta = DocMeta(Path("x.md"), "标题", "摘要", "design", "", "内容")
        assert not _keyword_match("不存在的词", meta)

    def test_empty_query_returns_true(self) -> None:
        meta = DocMeta(Path("x.md"), "标题", "摘要", "design", "", "内容")
        assert _keyword_match("", meta)


class TestDocsSearcherSearch:
    """DocsSearcher.search: 检索流程."""

    def _make_docs(self, tmp_path: Path) -> Path:
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "DESIGN-alpha.md").write_text("# Alpha 设计\n\n关键词: 优化", encoding="utf-8")
        (docs / "ANALYSIS-beta.md").write_text("# Beta 分析\n\n关键词: 飞书", encoding="utf-8")
        (docs / "ai_rules.md").write_text("# AI 规则\n\n关键词: 优化", encoding="utf-8")
        return docs

    def test_no_docs_dir_returns_empty(self, tmp_path: Path) -> None:
        s = DocsSearcher(docs_dir=tmp_path / "nonexistent")
        assert s.search("anything") == []

    def test_match_returns_results(self, tmp_path: Path) -> None:
        docs = self._make_docs(tmp_path)
        s = DocsSearcher(docs_dir=docs)
        results = s.search("优化")
        assert len(results) == 2
        for r in results:
            assert r["kind"] == "docs"
            assert "file" in r
            assert "title" in r
            assert "summary" in r
            assert "relevance" in r
            assert "doc_type" in r
            assert "ts" in r

    def test_no_match_returns_empty(self, tmp_path: Path) -> None:
        docs = self._make_docs(tmp_path)
        s = DocsSearcher(docs_dir=docs)
        assert s.search("不存在的词") == []

    def test_doc_type_filter(self, tmp_path: Path) -> None:
        docs = self._make_docs(tmp_path)
        s = DocsSearcher(docs_dir=docs)
        results = s.search("优化", doc_type="design")
        assert len(results) == 1
        assert results[0]["doc_type"] == "design"

    def test_limit_constraint(self, tmp_path: Path) -> None:
        docs = self._make_docs(tmp_path)
        s = DocsSearcher(docs_dir=docs)
        results = s.search("优化", limit=1)
        assert len(results) <= 1

    def test_path_confined_to_docs_dir(self, tmp_path: Path) -> None:
        docs = self._make_docs(tmp_path)
        (tmp_path / "outside.md").write_text("# 外部文件\n\n优化", encoding="utf-8")
        s = DocsSearcher(docs_dir=docs)
        results = s.search("优化")
        for r in results:
            assert "outside" not in r["file"]


class TestSemanticDegradation:
    """语义降级: semantic_retriever=None / unavailable / exception."""

    def test_no_semantic_pure_keyword(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "DESIGN-test.md").write_text("# 测试\n\n关键词", encoding="utf-8")
        s = DocsSearcher(docs_dir=docs, semantic_retriever=None)
        results = s.search("关键词")
        assert len(results) == 1
        assert "note" not in results[0]

    def test_semantic_unavailable_degrades(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "DESIGN-test.md").write_text("# 测试\n\n关键词", encoding="utf-8")

        class FakeSemantic:
            def semantic_available(self) -> bool:
                return False

        s = DocsSearcher(docs_dir=docs, semantic_retriever=FakeSemantic())
        results = s.search("关键词")
        assert len(results) == 1
        assert "note" not in results[0]

    def test_semantic_exception_degrades(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "DESIGN-test.md").write_text("# 测试\n\n关键词", encoding="utf-8")

        class FakeSemantic:
            def semantic_available(self) -> bool:
                return True

            def search(self, *args: object, **kwargs: object) -> list:
                raise RuntimeError("embedder down")

        s = DocsSearcher(docs_dir=docs, semantic_retriever=FakeSemantic())
        results = s.search("关键词")
        assert len(results) == 1
        assert "note" not in results[0]


# ── §6.2 run_search_docs 工具层单元测试 ──


class TestRunSearchDocs:
    """run_search_docs: 五种回执路径."""

    def test_fn_none_returns_failure(self) -> None:
        r = run_search_docs(None, {"query": "test"})
        assert r.status == ToolResultStatus.FAILURE
        assert "不可用" in r.content

    def test_empty_query_returns_failure(self) -> None:
        r = run_search_docs(lambda **kw: [], {"query": ""})
        assert r.status == ToolResultStatus.FAILURE
        assert "参数错误" in r.content

    def test_limit_clamped(self) -> None:
        calls: list[dict] = []

        def fn(**kw: object) -> list[dict]:
            calls.append(kw)  # type: ignore[arg-type]
            return []

        run_search_docs(fn, {"query": "x", "limit": 100})
        assert calls[0]["limit"] == 50
        run_search_docs(fn, {"query": "x", "limit": -1})
        assert calls[1]["limit"] == 1

    def test_hit_returns_success(self) -> None:
        def fn(**kw: object) -> list[dict]:
            return [
                {
                    "kind": "docs",
                    "file": "/docs/test.md",
                    "title": "测试",
                    "summary": "摘要",
                    "relevance": 1.0,
                    "doc_type": "design",
                    "ts": "2026-08-13",
                }
            ]

        r = run_search_docs(fn, {"query": "测试"})
        assert r.status == ToolResultStatus.SUCCESS
        assert "命中" in r.content
        assert "测试" in r.content

    def test_hit_over_six_adds_note(self) -> None:
        def fn(**kw: object) -> list[dict]:
            return [
                {
                    "kind": "docs",
                    "file": f"/docs/{i}.md",
                    "title": f"标题{i}",
                    "summary": "摘要",
                    "relevance": 1.0,
                    "doc_type": "design",
                    "ts": "2026-08-13",
                }
                for i in range(10)
            ]

        r = run_search_docs(fn, {"query": "标题"})
        assert r.status == ToolResultStatus.SUCCESS
        assert "仅显示前 6 条" in r.content
        assert "共 10 条" in r.content

    def test_no_hit_returns_success(self) -> None:
        r = run_search_docs(lambda **kw: [], {"query": "不存在的"})
        assert r.status == ToolResultStatus.SUCCESS
        assert "未找到" in r.content

    def test_degradation_note_in_result(self) -> None:
        def fn(**kw: object) -> list[dict]:
            return [
                {
                    "kind": "docs",
                    "file": "/docs/test.md",
                    "title": "测试",
                    "summary": "摘要",
                    "relevance": 0.5,
                    "doc_type": "design",
                    "ts": "2026-08-13",
                    "note": "语义检索不可用，已降级为关键词检索",
                }
            ]

        r = run_search_docs(fn, {"query": "测试"})
        assert r.status == ToolResultStatus.SUCCESS
        assert "降级标注" in r.content

    def test_oserror_returns_failure(self) -> None:
        def fn(**kw: object) -> list[dict]:
            raise OSError("disk full")

        r = run_search_docs(fn, {"query": "test"})
        assert r.status == ToolResultStatus.FAILURE
        assert "程序异常" in r.content


# ── A4: recent_docs + search_docs 未命中引导 ──


class TestRecentDocs:
    """A4-T1: DocsSearcher.recent_docs 按 ts 降序返回最近 N 篇."""

    def _make_docs(self, tmp_path: Path) -> Path:
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "DESIGN-alpha.md").write_text("# Alpha 设计\n\n内容", encoding="utf-8")
        (docs / "ANALYSIS-beta.md").write_text("# Beta 分析\n\n内容", encoding="utf-8")
        (docs / "ai_rules.md").write_text("# AI 规则\n\n内容", encoding="utf-8")
        return docs

    def test_recent_docs_recent_first(self, tmp_path: Path) -> None:
        docs = self._make_docs(tmp_path)
        s = DocsSearcher(docs_dir=docs)
        recent = s.recent_docs(5)
        assert len(recent) == 3
        for r in recent:
            assert "file" in r
            assert "title" in r
            assert "summary" in r
            assert "doc_type" in r
            assert "ts" in r
        ts_list = [r["ts"] for r in recent]
        assert ts_list == sorted(ts_list, reverse=True)

    def test_recent_docs_no_dir_returns_empty(self, tmp_path: Path) -> None:
        s = DocsSearcher(docs_dir=tmp_path / "nonexistent")
        assert s.recent_docs(5) == []

    def test_recent_docs_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        s = DocsSearcher(docs_dir=docs)
        assert s.recent_docs(5) == []

    def test_recent_docs_limit_respected(self, tmp_path: Path) -> None:
        docs = self._make_docs(tmp_path)
        s = DocsSearcher(docs_dir=docs)
        assert len(s.recent_docs(2)) == 2

    def test_recent_docs_corrupt_file_fail_open(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "good.md").write_text("# 好文档\n\n内容", encoding="utf-8")
        (docs / "bad.md").write_bytes(b"\xff\xfe\x00\x01")
        s = DocsSearcher(docs_dir=docs)
        assert len(s.recent_docs(5)) == 1


class TestSearchDocsNoHitGuide:
    """A4-T2: search_docs 未命中 → 近 N 篇文档标题引导；recent 通道不可用 → 回退既有文案."""

    def test_no_hit_with_recent_channel(self) -> None:
        def fn(**kw: object) -> list[dict]:
            return []

        fn.recent_docs = lambda limit=5: [  # type: ignore[attr-defined]
            {"title": "Alpha 设计"},
            {"title": "Beta 分析"},
        ]
        r = run_search_docs(fn, {"query": "不存在的词"})
        assert r.status == ToolResultStatus.SUCCESS
        assert "未命中" in r.content
        assert "参考引导" in r.content
        assert "Alpha 设计" in r.content
        assert "Beta 分析" in r.content

    def test_no_hit_recent_channel_unavailable_fallback(self) -> None:
        r = run_search_docs(lambda **kw: [], {"query": "不存在的词"})
        assert r.status == ToolResultStatus.SUCCESS
        assert "未找到" in r.content
        assert "不伪造结果" in r.content

    def test_no_hit_recent_channel_exception_fallback(self) -> None:
        def fn(**kw: object) -> list[dict]:
            return []

        def _boom(limit: int = 5) -> list:
            raise RuntimeError("recent down")

        fn.recent_docs = _boom  # type: ignore[attr-defined]
        r = run_search_docs(fn, {"query": "不存在的词"})
        assert r.status == ToolResultStatus.SUCCESS
        assert "不伪造结果" in r.content

    def test_no_hit_recent_channel_empty_fallback(self) -> None:
        def fn(**kw: object) -> list[dict]:
            return []

        fn.recent_docs = lambda limit=5: []  # type: ignore[attr-defined]
        r = run_search_docs(fn, {"query": "不存在的词"})
        assert r.status == ToolResultStatus.SUCCESS
        assert "不伪造结果" in r.content

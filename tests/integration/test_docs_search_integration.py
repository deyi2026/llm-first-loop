"""docs/ 文档语义检索集成测试（装配链路 + 端到端 + 向后兼容）.

覆盖：build_engine 装配注入、tool_defs 注册、execute 分派、端到端检索、向后兼容。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.config import Settings


def _settings(tmp_path: Path, docs_dir: str | None = None) -> Settings:
    kwargs: dict = {
        "llm_api_key": "k",
        "llm_base_url": "https://x/v1",
        "llm_model": "m",
        "data_dir": str(tmp_path / "data"),
        "self_inspection_enabled": True,
        "extract_enabled": False,
    }
    if docs_dir is not None:
        kwargs["docs_dir"] = docs_dir
    return Settings(**kwargs)


# ── §7.1 装配链路集成测试 ──


class TestAssemblyChain:
    def test_search_docs_fn_injected(self, tmp_path: Path) -> None:
        """build_engine 后 corrections._search_docs_fn 已注入（非 None）."""
        from llm_loop.factory import build_engine

        settings = _settings(tmp_path, docs_dir=str(tmp_path / "docs"))
        engine = build_engine(settings)  # type: ignore[arg-type]
        assert engine.corrections._search_docs_fn is not None  # noqa: SLF001

    def test_tool_defs_contains_search_docs(self, tmp_path: Path) -> None:
        """corrections.tool_defs() 含 search_docs 工具定义."""
        from llm_loop.factory import build_engine

        settings = _settings(tmp_path)
        engine = build_engine(settings)  # type: ignore[arg-type]
        names = [td["name"] for td in engine.corrections.tool_defs()]
        assert "search_docs" in names

    def test_execute_dispatches_search_docs(self, tmp_path: Path) -> None:
        """corrections.execute('search_docs', args) 正确分派."""
        from llm_loop.factory import build_engine

        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "DESIGN-test.md").write_text("# 测试文档\n\n关键词: 优化", encoding="utf-8")
        settings = _settings(tmp_path, docs_dir=str(docs))
        engine = build_engine(settings)  # type: ignore[arg-type]
        result = engine.corrections.execute("search_docs", {"query": "优化"})
        assert result.tool_name == "search_docs"
        assert "命中" in result.content


# ── §7.2 端到端检索流程测试 ──


class TestEndToEndSearch:
    """使用真实 docs/ 目录（项目根 docs/）测试端到端检索."""

    PROJECT_DOCS = Path(__file__).resolve().parents[2] / "docs"

    @pytest.mark.skipif(
        not PROJECT_DOCS.exists(),
        reason="项目 docs/ 目录不存在",
    )
    def test_real_docs_search(self, tmp_path: Path) -> None:
        """search_docs(query='优化') → 返回匹配文档条目."""
        from llm_loop.factory import build_engine

        settings = _settings(tmp_path, docs_dir=str(self.PROJECT_DOCS))
        engine = build_engine(settings)  # type: ignore[arg-type]
        result = engine.corrections.execute("search_docs", {"query": "优化"})
        assert result.tool_name == "search_docs"
        assert result.status.value == "success"

    @pytest.mark.skipif(
        not PROJECT_DOCS.exists(),
        reason="项目 docs/ 目录不存在",
    )
    def test_doc_type_filter(self, tmp_path: Path) -> None:
        """search_docs(query='飞书', doc_type='analysis') → 仅返回 analysis 类型."""
        from llm_loop.factory import build_engine

        settings = _settings(tmp_path, docs_dir=str(self.PROJECT_DOCS))
        engine = build_engine(settings)  # type: ignore[arg-type]
        result = engine.corrections.execute(
            "search_docs", {"query": "飞书", "doc_type": "analysis"}
        )
        assert result.tool_name == "search_docs"

    def test_dynamic_content(self, tmp_path: Path) -> None:
        """新增临时 .md 文件 → 检索可命中；删除 → 不再命中."""
        from llm_loop.factory import build_engine

        docs = tmp_path / "docs"
        docs.mkdir()
        settings = _settings(tmp_path, docs_dir=str(docs))
        engine = build_engine(settings)  # type: ignore[arg-type]
        f = docs / "DESIGN-dynamic.md"
        f.write_text("# 动态文档\n\n独特关键词: zzz_unique_token", encoding="utf-8")
        result = engine.corrections.execute("search_docs", {"query": "zzz_unique_token"})
        assert "命中" in result.content
        f.unlink()
        result = engine.corrections.execute("search_docs", {"query": "zzz_unique_token"})
        assert "未找到" in result.content


# ── §7.3 向后兼容集成测试 ──


class TestBackwardCompat:
    def test_no_docs_dir_build_engine_ok(self, tmp_path: Path) -> None:
        """无 docs/ 目录时 build_engine 正常启动（零回归）."""
        from llm_loop.factory import build_engine

        settings = _settings(tmp_path, docs_dir=str(tmp_path / "nonexistent_docs"))
        engine = build_engine(settings)  # type: ignore[arg-type]
        assert engine is not None

    def test_no_docs_dir_search_returns_empty(self, tmp_path: Path) -> None:
        """无 docs/ 目录时 search_docs 如实返回未命中不报错."""
        from llm_loop.factory import build_engine

        settings = _settings(tmp_path, docs_dir=str(tmp_path / "nonexistent_docs"))
        engine = build_engine(settings)  # type: ignore[arg-type]
        result = engine.corrections.execute("search_docs", {"query": "anything"})
        assert result.status.value == "success"
        assert "未找到" in result.content

    def test_docs_dir_env_var(self, tmp_path: Path, monkeypatch) -> None:
        """设置 DOCS_DIR 环境变量 → DocsSearcher 使用该路径."""
        from llm_loop.config import load_settings

        docs = tmp_path / "custom_docs"
        docs.mkdir()
        (docs / "DESIGN-env.md").write_text("# 环境变量文档\n\nenv_token", encoding="utf-8")
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("DOCS_DIR", str(docs))
        monkeypatch.setenv("LLM_API_KEY", "k")
        monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
        monkeypatch.setenv("LLM_MODEL", "m")
        settings = load_settings()
        assert settings.docs_dir == str(docs)
        from llm_loop.factory import build_engine

        engine = build_engine(settings)  # type: ignore[arg-type]
        result = engine.corrections.execute("search_docs", {"query": "env_token"})
        assert "命中" in result.content

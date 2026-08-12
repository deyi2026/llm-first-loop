"""Web 折叠重构静态断言测试（spec 5.2.1 / design §2.4.2 / tasks 2.4）.

断言:
1. app.js 含 collapseUnit 函数（节点分离方案落地）
2. collapseLongContent 不含 innerHTML = fullHtml 整体重建（消除缺陷 1：按钮引用失效）
3. 摘要走 renderMarkdown（非 textContent 纯文本，消除缺陷 3：摘要丢 MD 格式）
4. app.js 不含 React/Vue import
5. sanitize 白名单 MD_ALLOWED_TAGS 未放宽
6. style.css 含 .collapsed-summary/.collapsed-full 显隐类
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src" / "llm_loop" / "web" / "static" / "app.js"
STYLE_CSS = ROOT / "src" / "llm_loop" / "web" / "static" / "style.css"


@pytest.fixture(scope="module")
def app_js_src() -> str:
    return APP_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css_src() -> str:
    return STYLE_CSS.read_text(encoding="utf-8")


class TestCollapseRefactor:
    def test_collapse_unit_defined(self, app_js_src: str):
        assert "function collapseUnit" in app_js_src

    def test_collapse_long_content_still_defined(self, app_js_src: str):
        assert "function collapseLongContent" in app_js_src

    def test_no_innerhtml_full_rebuild(self, app_js_src: str):
        # 缺陷 1 根因：innerHTML = fullHtml 整体重建 → 按钮引用失效；重构改为显隐切换
        assert "innerHTML = fullHtml" not in app_js_src

    def test_summary_uses_render_markdown(self, app_js_src: str):
        # 缺陷 3 根因：摘要 textContent 纯文本丢格式；重构后摘要走 renderMarkdown
        assert "renderMarkdown(summaryMd)" in app_js_src
        assert "textContent = summary" not in app_js_src

    def test_fail_open_error_handling(self, app_js_src: str):
        assert "长内容折叠失败（fail-open）" in app_js_src

    def test_no_react_import(self, app_js_src: str):
        assert "import React" not in app_js_src
        assert 'from "react"' not in app_js_src

    def test_no_vue_import(self, app_js_src: str):
        assert 'from "vue"' not in app_js_src
        assert "require('vue')" not in app_js_src

    def test_sanitize_whitelist_not_relaxed(self, app_js_src: str):
        m = re.search(r"MD_ALLOWED_TAGS\s*=\s*new Set\(\[([^\]]+)\]", app_js_src)
        assert m, "MD_ALLOWED_TAGS 定义未找到"
        tags = m.group(1)
        assert "script" not in tags
        assert "iframe" not in tags
        assert "style" not in tags
        assert "object" not in tags
        assert "embed" not in tags


class TestCollapseRefactorStyle:
    def test_collapsed_summary_class_present(self, css_src: str):
        assert ".collapsed-summary" in css_src

    def test_collapsed_full_class_present(self, css_src: str):
        assert ".collapsed-full" in css_src

    def test_collapsed_full_hidden_by_default(self, css_src: str):
        assert "display: none" in css_src

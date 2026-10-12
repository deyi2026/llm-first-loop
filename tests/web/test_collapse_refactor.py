"""Web 折叠代码移除守护测试（2026-08-15 用户需求：回复不折叠）.

原折叠重构断言（spec 5.2.1）随折叠方案废止而改写为"移除守护"：
1. app.js 不再含 collapseUnit / collapseLongContent（折叠实现整体移除）
2. app.js 不含 innerHTML = fullHtml 整体重建（历史缺陷防复活）
3. style.css 不再含 .collapsed-summary/.collapsed-full/.expand-btn 折叠样式
4. sanitize 白名单 MD_ALLOWED_TAGS 未放宽（保留安全守护）
5. app.js 不含 React/Vue import（保留 spec 5.2.1 第 8 条禁止项守护）
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STYLE_CSS = ROOT / "src" / "llm_loop" / "web" / "static" / "style.css"


@pytest.fixture(scope="module")
def css_src() -> str:
    return STYLE_CSS.read_text(encoding="utf-8")


class TestCollapseRemoved:
    def test_collapse_unit_removed(self, app_js_src: str):
        assert "function collapseUnit" not in app_js_src

    def test_collapse_long_content_removed(self, app_js_src: str):
        assert "function collapseLongContent" not in app_js_src

    def test_no_innerhtml_full_rebuild(self, app_js_src: str):
        assert "innerHTML = fullHtml" not in app_js_src

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
        for banned in ("script", "iframe", "style", "object", "embed"):
            assert banned not in tags


class TestCollapseStyleRemoved:
    def test_collapsed_summary_class_removed(self, css_src: str):
        assert ".collapsed-summary" not in css_src

    def test_collapsed_full_class_removed(self, css_src: str):
        assert ".collapsed-full" not in css_src

    def test_expand_btn_class_removed(self, css_src: str):
        assert ".expand-btn" not in css_src

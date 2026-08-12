"""T3 Web 长文本折叠静态断言测试（spec.md 5.2.1 / design.md §2.5 / tasks.md T3.5）.

断言:
1. app.js 含 collapseLongContent 函数 + LONG_LINE_THRESHOLD/LONG_CHAR_THRESHOLD 常量
2. app.js 截断标注含续读建议
3. style.css 含 .collapsed/.expand-btn 样式
4. app.js 不含 React/Vue import（spec.md 5.2.1 第 8 条禁止项静态守护）
5. sanitize 白名单 MD_ALLOWED_TAGS 未放宽（不含 script/iframe/style，spec.md 5.2.1 第 9 条）
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


class TestLongContentCollapse:
    def test_collapse_function_defined(self, app_js_src: str):
        assert "function collapseLongContent" in app_js_src

    def test_line_threshold_constant(self, app_js_src: str):
        assert "LONG_LINE_THRESHOLD" in app_js_src

    def test_char_threshold_constant(self, app_js_src: str):
        assert "LONG_CHAR_THRESHOLD" in app_js_src

    def test_collapse_called_in_render_messages(self, app_js_src: str):
        assert "collapseLongContent(node)" in app_js_src

    def test_truncated_note_has_continue_hint(self, app_js_src: str):
        assert "回答被截断" in app_js_src
        assert "新建会话" in app_js_src
        assert "调整 prompt" in app_js_src

    def test_fail_open_error_handling(self, app_js_src: str):
        assert "长内容折叠失败（fail-open）" in app_js_src

    def test_no_react_import(self, app_js_src: str):
        assert "import React" not in app_js_src
        assert "from \"react\"" not in app_js_src

    def test_no_vue_import(self, app_js_src: str):
        assert "from \"vue\"" not in app_js_src
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


class TestCollapseStyle:
    @pytest.fixture(scope="module")
    def css_src(self) -> str:
        return STYLE_CSS.read_text(encoding="utf-8")

    def test_collapsed_class_present(self, css_src: str):
        assert ".collapsed" in css_src

    def test_collapsed_has_max_height(self, css_src: str):
        m = re.search(r"\.collapsed\s*\{[^}]*\}", css_src)
        assert m and "max-height" in m.group(0)

    def test_expand_btn_class_present(self, css_src: str):
        assert ".expand-btn" in css_src

    def test_expand_btn_has_cursor_pointer(self, css_src: str):
        m = re.search(r"\.expand-btn\s*\{[^}]*\}", css_src)
        assert m and "cursor" in m.group(0)

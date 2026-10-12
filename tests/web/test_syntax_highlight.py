"""Web 代码块语法高亮静态断言测试（spec 5.3.1 D1 / design §2.4.3 / tasks 3.3）.

断言:
1. app.js 含 highlightCodeBlock 函数（自研简版落地）
2. app.js 不含 hljs/highlight.js CDN import（零新依赖）
3. app.js 不含 React/Vue import（零框架）
4. sanitize 白名单未放宽
5. 高亮用 DOM API（createElement/textContent/className）构建，不用 innerHTML 注入
6. style.css 含 .code-kw/.code-str/.code-comment/.code-num 着色类
7. 高亮在复制/折叠之前调用（顺序）
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src" / "llm_loop" / "web" / "static" / "app.js"
STYLE_CSS = ROOT / "src" / "llm_loop" / "web" / "static" / "style.css"


@pytest.fixture(scope="module")

def css_src() -> str:
    return STYLE_CSS.read_text(encoding="utf-8")


class TestSyntaxHighlight:
    def test_highlight_function_defined(self, app_js_src: str):
        assert "function highlightCodeBlock" in app_js_src

    def test_no_hljs_cdn(self, app_js_src: str):
        assert "hljs" not in app_js_src
        assert "highlight.js" not in app_js_src

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

    def test_uses_dom_api_not_innerhtml(self, app_js_src: str):
        # 高亮用 DOM API 构建 span（textContent + className），不注入 HTML
        assert 'createElement("span")' in app_js_src
        assert "span.className = cls" in app_js_src
        assert "span.textContent = full" in app_js_src
        # highlightCodeBlock 函数体内不含 innerHTML（防 XSS）
        body = app_js_src.split("function highlightCodeBlock", 1)[1].split("function highlightCodeBlocks", 1)[0]
        assert "innerHTML" not in body

    def test_highlight_before_copy_and_collapse(self, app_js_src: str):
        assert "highlightCodeBlocks(node);" in app_js_src
        # 顺序：高亮先于复制
        assert app_js_src.index("highlightCodeBlocks(node)") < app_js_src.index("addCodeBlockCopyButtons(node)")


class TestHighlightStyle:
    def test_color_classes_present(self, css_src: str):
        assert ".code-kw" in css_src
        assert ".code-str" in css_src
        assert ".code-comment" in css_src
        assert ".code-num" in css_src

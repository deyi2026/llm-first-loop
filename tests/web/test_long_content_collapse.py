"""Web 长内容分块静态断言测试（2026-08-15 用户需求：回复不折叠，过长分块输出）.

替代原折叠断言（spec 5.2.1 折叠方案已由用户决策废止）：
1. app.js 含 chunkLongContent 函数（分块全量展示，无折叠隐藏）
2. 消息体级折叠已移除（无 LONG_CHAR_THRESHOLD / bodyCollapsed）
3. 超长代码块顺序分段（段标注含「段 · 共 N 行」），无「展开全文」按钮
4. app.js 不含 React/Vue import（spec.md 5.2.1 第 8 条禁止项静态守护）
5. sanitize 白名单 MD_ALLOWED_TAGS 未放宽（不含 script/iframe/style）
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STYLE_CSS = ROOT / "src" / "llm_loop" / "web" / "static" / "style.css"


class TestLongContentChunk:
    def test_chunk_function_defined(self, app_js_src: str):
        assert "function chunkLongContent" in app_js_src

    def test_chunk_called_in_render_messages(self, app_js_src: str):
        assert "chunkLongContent(node)" in app_js_src

    def test_body_fold_removed(self, app_js_src: str):
        """消息体级折叠已移除：回复正文全量渲染，不再摘要+隐藏."""
        assert "LONG_CHAR_THRESHOLD" not in app_js_src
        assert "bodyCollapsed" not in app_js_src

    def test_no_expand_button(self, app_js_src: str):
        """不再有折叠交互：无 collapseUnit / 展开全文按钮."""
        assert "function collapseUnit" not in app_js_src
        assert "展开全文" not in app_js_src

    def test_chunk_segment_marker(self, app_js_src: str):
        """分段标注：段序 + 总行数 + 未折叠如实声明."""
        assert "段 · 共" in app_js_src
        assert "未折叠" in app_js_src

    def test_line_threshold_kept_as_chunk_size(self, app_js_src: str):
        assert "LONG_LINE_THRESHOLD" in app_js_src

    def test_fail_open_error_handling(self, app_js_src: str):
        assert "长内容分块失败（fail-open）" in app_js_src

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


class TestChunkStyle:
    def test_chunk_marker_class_present(self):
        css = STYLE_CSS.read_text(encoding="utf-8")
        assert ".chunk-marker" in css

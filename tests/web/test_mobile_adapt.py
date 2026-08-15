"""P4-2 移动端适配 Web 测试（design 2.5.2 T1-T12）.

覆盖：断点单一性与缩放保留、侧栏入口与响应式 JS 模块、触控目标与 hover-only 常显、
会话收起与视口高度回退、安全约束与既有能力零回归。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src" / "llm_loop" / "web" / "static" / "app.js"
STYLE_CSS = ROOT / "src" / "llm_loop" / "web" / "static" / "style.css"
INDEX_HTML = ROOT / "src" / "llm_loop" / "web" / "static" / "index.html"


@pytest.fixture(scope="module")

def style_css_src() -> str:
    return STYLE_CSS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index_html_src() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


# ── T1/T2: 断点单一性与缩放保留 ──


def test_single_breakpoint(style_css_src):
    """全文仅一个 @media (max-width: 767.98px) 断点，无多级断点."""
    assert "@media (max-width: 767.98px)" in style_css_src
    breakpoints = re.findall(r"@media\s+\(max-width:\s*[^)]+\)", style_css_src)
    assert len(breakpoints) == 1, f"应仅一个窄屏断点，实际: {breakpoints}"
    assert "@media (max-width: 768px)" not in style_css_src


def test_viewport_zoom_kept(index_html_src):
    """viewport meta 含 width=device-width 且不禁用缩放."""
    assert 'width=device-width' in index_html_src
    assert "user-scalable=no" not in index_html_src


# ── T3/T6: 侧栏入口与响应式 JS 模块 ──


def test_sidebar_nodes_present(index_html_src):
    """侧栏汉堡入口与遮罩节点存在."""
    assert 'id="sidebar-toggle"' in index_html_src
    assert 'id="sidebar-scrim"' in index_html_src


def test_responsive_js_modules(app_js_src):
    """响应式 JS 模块全部落地."""
    for fn in ("isNarrowScreen", "setSidebarOpen", "initResponsive", "handleVisualViewportChange"):
        assert f"function {fn}" in app_js_src, f"{fn} 未定义"
    assert 'matchMedia("(max-width: 767.98px)")' in app_js_src


# ── T4/T5: 触控目标与 hover-only 常显 ──


def test_touch_targets_44px(style_css_src):
    """窄屏触控目标 ≥44×44 扩充规则落地."""
    assert "min-height: 44px" in style_css_src
    assert "min-width: 44px" in style_css_src
    # 关键交互元素（发送/上传/会话项）均纳入扩充
    for sel in ("#send-btn", "#upload-btn", ".session-item", ".session-del", ".session-pin"):
        assert sel in style_css_src


def test_hover_only_visible_on_narrow(style_css_src):
    """窄屏块内 .session-del/.session-pin 常显（覆盖 hover-only）."""
    media_block = style_css_src.split("@media (max-width: 767.98px)")[1]
    assert "display: inline-flex" in media_block


# ── T7/T8: 会话收起集成与视口高度回退 ──


def test_session_close_sidebar(app_js_src):
    """selectSession/newSession 体内含 setSidebarOpen(false)（选会话/新建后收起）."""
    sel = app_js_src.split("function selectSession", 1)[1].split("function newSession", 1)[0]
    assert "setSidebarOpen(false)" in sel
    new = app_js_src.split("function newSession", 1)[1]
    assert "setSidebarOpen(false)" in new


def test_dvh_with_vh_fallback(style_css_src):
    """100dvh + 100vh 回退（软键盘/地址栏视口适配）."""
    assert "100dvh" in style_css_src
    assert "100vh" in style_css_src


# ── T9/T10/T11/T12: 安全约束与既有能力零回归 ──


def test_no_framework(app_js_src):
    """无框架引入."""
    assert "import React" not in app_js_src
    assert 'from "react"' not in app_js_src
    assert 'from "vue"' not in app_js_src
    assert "require('vue')" not in app_js_src


def test_sanitize_whitelist_not_relaxed(app_js_src):
    """XSS 白名单未放宽."""
    m = re.search(r"MD_ALLOWED_TAGS\s*=\s*new Set\(\[([^\]]+)\]", app_js_src)
    assert m, "MD_ALLOWED_TAGS 定义未找到"
    tags = m.group(1)
    for dangerous in ("script", "iframe", "style", "object", "embed"):
        assert dangerous not in tags, f"白名单含危险标签 {dangerous}"


def test_existing_symbols_kept(app_js_src, style_css_src):
    """既有关键函数与类名未删除（桌面与既有能力零回归）."""
    for fn in ("renderMessages", "chunkLongContent", "isMessagesAtBottom",
               "renderToolCalls", "sanitizeHtml"):
        assert f"function {fn}" in app_js_src, f"{fn} 被删除"
    for cls in (".tool-call-chain", ".chunk-marker", ".chunked-pre"):
        assert cls in style_css_src, f"{cls} 被删除"


def test_input_behavior_kept(app_js_src):
    """既有输入行为保留（IME 组合态回车 + Shift+Enter 换行）. """
    assert "isComposing" in app_js_src
    assert "keyCode === 229" in app_js_src
    assert "Shift+Enter" in app_js_src or "shiftKey" in app_js_src

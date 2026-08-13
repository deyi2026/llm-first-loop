"""P4-3 数学公式渲染 Web 测试（design 2.5.2 T1-T11）.

覆盖：公式模块函数与定界符、代码区豁免与转义、降级路径与引擎按需加载、
静态资源与样式、安全约束与既有能力零回归。
无 node/jsdom，以"函数/常量/资源可静态核验 + 降级路径显式标注"为验收基线。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_loop.web import build_app

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src" / "llm_loop" / "web" / "static" / "app.js"
STYLE_CSS = ROOT / "src" / "llm_loop" / "web" / "static" / "style.css"
INDEX_HTML = ROOT / "src" / "llm_loop" / "web" / "static" / "index.html"
KATEX_DIR = ROOT / "src" / "llm_loop" / "web" / "static" / "katex"


@pytest.fixture(scope="module")
def app_js_src() -> str:
    return APP_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def style_css_src() -> str:
    return STYLE_CSS.read_text(encoding="utf-8")


# ── T1/T2: 公式模块函数与定界符 ──


def test_formula_functions_present(app_js_src):
    """公式模块四个函数全部落地."""
    for fn in ("extractMath", "restoreMathInHtml", "renderMathElement", "loadMathEngine"):
        assert f"function {fn}" in app_js_src, f"{fn} 未定义"


def test_delimiters_and_placeholder(app_js_src):
    """四类定界符与占位符机制落地."""
    assert '"$$"' in app_js_src
    assert '"\\\\["' in app_js_src or '"\\["' in app_js_src
    assert '"\\\\("' in app_js_src or '"\\("' in app_js_src
    assert '"$"' in app_js_src
    assert "MATH_PLACEHOLDER_PREFIX" in app_js_src
    assert "@@MATH_" in app_js_src


# ── T3: 代码区豁免与转义判定 ──


def test_code_escape_handling(app_js_src):
    """代码区豁免状态标记与转义判定逻辑落地."""
    assert "fenced" in app_js_src  # 围栏代码区豁免
    assert "inCodeBlock" in app_js_src or "fenced" in app_js_src
    assert "backtickLen" in app_js_src or "repeat" in app_js_src  # 行内代码豁免
    # 转义判定：反斜杠计数逻辑
    assert "% 2 === 1" in app_js_src or "% 2 == 1" in app_js_src


# ── T4/T5: 降级路径与引擎按需加载 ──


def test_render_safety_and_fallback(app_js_src):
    """renderMathElement 含 throwOnError/trust 安全配置与 try/catch 降级."""
    assert "throwOnError" in app_js_src
    assert "trust" in app_js_src
    assert "try {" in app_js_src or "try{" in app_js_src
    assert "公式渲染失败（fail-open" in app_js_src
    assert "公式引擎不可用（fail-open" in app_js_src


def test_engine_lazy_load(app_js_src):
    """loadMathEngine 含动态 script 创建 + onerror 降级 + 预算常量."""
    assert 'document.createElement("script")' in app_js_src
    assert "onerror" in app_js_src
    assert "MATH_FORMULA_MAX" in app_js_src
    assert "MATH_RENDER_BUDGET_MS" in app_js_src
    assert "/static/katex/katex.min.js" in app_js_src
    assert "/static/katex/katex.min.css" in app_js_src


# ── T6/T7: 静态资源与样式 ──


def test_katex_resources_present():
    """本地 KaTeX 资源完整（min.js/min.css/woff2/License/README）."""
    assert (KATEX_DIR / "katex.min.js").exists()
    assert (KATEX_DIR / "katex.min.css").exists()
    fonts = list((KATEX_DIR / "fonts").glob("*.woff2"))
    assert len(fonts) >= 10, f"woff2 字体不完整: {len(fonts)} 个"
    # 无 ttf/woff 残留
    assert not list((KATEX_DIR / "fonts").glob("*.ttf"))
    assert not list((KATEX_DIR / "fonts").glob("*.woff"))
    license_text = (KATEX_DIR / "LICENSE").read_text(encoding="utf-8")
    assert "MIT" in license_text
    readme = (KATEX_DIR / "README.md").read_text(encoding="utf-8")
    assert "0.16.47" in readme


def test_katex_reachable_via_static(build_test_engine):
    """静态资源经 /static/ 本地分发 HTTP 200 可达."""
    engine, _ = build_test_engine([])
    client = TestClient(build_app(engine=engine))
    resp_js = client.get("/static/katex/katex.min.js")
    assert resp_js.status_code == 200
    assert "javascript" in resp_js.headers["content-type"]
    resp_css = client.get("/static/katex/katex.min.css")
    assert resp_css.status_code == 200
    assert "css" in resp_css.headers["content-type"]


def test_katex_style_present(style_css_src):
    """公式样式类落地（.katex / .katex-display，块级横向滚动）."""
    assert ".katex {" in style_css_src or ".katex" in style_css_src
    assert ".katex-display" in style_css_src
    assert "overflow-x: auto" in style_css_src


# ── T8/T9/T10/T11: 安全约束与既有能力零回归 ──


def test_no_cdn_reference():
    """index.html/app.js 无外部 http(s) 引用（本地分发）."""
    for f in ("index.html", "app.js"):
        content = (Path(ROOT / "src" / "llm_loop" / "web" / "static" / f)).read_text(encoding="utf-8")
        assert "http://" not in content.replace("http://127.0.0.1", "")
        assert "https://" not in content.replace("https://api", "")


def test_no_hljs_in_app_js(app_js_src):
    """app.js 不引入 hljs 字样（test_no_new_cdn 零回归）."""
    assert "hljs" not in app_js_src


def test_sanitize_whitelist_not_relaxed(app_js_src):
    """XSS 白名单未放宽."""
    m = re.search(r"MD_ALLOWED_TAGS\s*=\s*new Set\(\[([^\]]+)\]", app_js_src)
    assert m, "MD_ALLOWED_TAGS 定义未找到"
    tags = m.group(1)
    for dangerous in ("script", "iframe", "style", "object", "embed"):
        assert dangerous not in tags, f"白名单含危险标签 {dangerous}"


def test_existing_symbols_and_calls_kept(app_js_src):
    """既有关键符号与调用点零回归 + 公式内嵌 renderMarkdown 入口."""
    for fn in ("renderMarkdown", "sanitizeHtml", "highlightCodeBlocks", "collapseLongContent"):
        assert f"function {fn}" in app_js_src, f"{fn} 被删除"
    assert "renderMarkdown(msg.content)" in app_js_src
    assert "marked.parse" in app_js_src
    # 公式能力内嵌于 renderMarkdown 内部
    rmd = app_js_src.split("function renderMarkdown", 1)[1]
    assert "extractMath" in rmd
    assert "restoreMathInHtml" in rmd

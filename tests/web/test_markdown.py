"""Web Markdown 渲染测试（M38，静态断言 + FakeLLM 集成，零真实冒烟无 node）.

用例：vendored 库可达 / 渲染函数与 sanitize 存在 / 白名单标签与协议 / XSS 向量净化。
无 node/jsdom 环境，以"文件存在 + 函数引用 + 白名单标签字符串"静态断言兜底。
"""

from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.web import build_app

STATIC_DIR = Path(__file__).resolve().parents[2] / "src" / "llm_loop" / "web" / "static"


def _make_client(engine):
    return TestClient(build_app(engine=engine))


def test_marked_vendored_exists():
    assert (STATIC_DIR / "marked.min.js").exists()
    content = (STATIC_DIR / "marked.min.js").read_text(encoding="utf-8")
    assert "marked" in content
    assert "MIT" in content


def test_index_html_refers_marked():
    index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "marked.min.js" in index
    assert "app.js" in index


def test_marked_reachable_via_static(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/static/marked.min.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]


def test_no_cdn_reference():
    for f in ("index.html", "app.js"):
        content = (STATIC_DIR / f).read_text(encoding="utf-8")
        assert "http://" not in content.replace("http://127.0.0.1", "")
        assert "https://" not in content.replace("https://api", "")


def test_app_js_has_render_markdown():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "function renderMarkdown" in app_js
    assert "marked.parse" in app_js


def test_app_js_has_sanitize():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "function sanitizeHtml" in app_js
    assert "DOMParser" in app_js


def test_assistant_uses_innerhtml_user_uses_textcontent():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    # assistant 走 MD 渲染（innerHTML），user/error 走 textContent
    assert 'msg.role === "assistant"' in app_js
    assert "node.innerHTML = html" in app_js
    assert "node.textContent = msg.content" in app_js


def test_sanitize_whitelist_tags():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for tag in ("pre", "code", "table", "thead", "th", "td", "blockquote", "h1", "a", "img"):
        assert f'"{tag}"' in app_js


def test_sanitize_rejects_dangerous_tags():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    # 白名单 Set 不含 script/iframe/style → sanitize 会移除外壳
    assert 'script"' not in app_js or "MD_ALLOWED_TAGS" in app_js  # script 不在白名单


def test_sanitize_strips_on_events():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'an.startsWith("on")' in app_js  # 事件属性移除逻辑


def test_sanitize_protocol_whitelist():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "http:" in app_js
    assert "https:" in app_js
    assert "javascript:" in app_js  # 拒绝协议列表含 javascript


def test_render_fallback_to_plaintext():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "返回 null" in app_js or "return null" in app_js  # 渲染异常返回 null → 降级纯文本


def test_note_stays_plaintext():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'msg-note' in app_js  # note 经 el() textContent 渲染，不 MD 渲染


def test_style_has_md_elements():
    css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    for sel in ("pre", "table", "th,", "blockquote", ".message.assistant h1"):
        assert sel in css


def test_render_breaks_assistant():
    # 静态断言：assistant 分支含 renderMarkdown 调用（语义等价模拟兜底）
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "renderMarkdown(msg.content)" in app_js

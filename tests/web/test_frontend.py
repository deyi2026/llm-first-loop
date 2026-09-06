"""Web 前端测试（M37，静态检查 + API 集成断言，FakeLLM 装配零真实冒烟）.

用例：HTML 存在性 / root 返回 HTML / /static 静态资源可达 / /api/info / 前端页面关键元素。
"""

from fastapi.testclient import TestClient

from llm_loop.web import build_app


def _make_client(engine):
    return TestClient(build_app(engine=engine))


def test_index_html_exists():
    from pathlib import Path

    index = Path(__file__).resolve().parents[2] / "src" / "llm_loop" / "web" / "static" / "index.html"
    assert index.exists()
    content = index.read_text(encoding="utf-8")
    assert "id=\"messages\"" in content
    assert "id=\"session-list\"" in content
    assert "id=\"message-input\"" in content
    assert "app.js" in content


def test_root_redirects_to_ui_v2(build_test_engine, fake_settings, tmp_path, monkeypatch):
    """默认入口为 Web V2：产物存在 → 307 重定向 /ui/v2/（2026-08-20 起旧版逐步弃用）."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>Web V2</body></html>", encoding="utf-8")
    monkeypatch.setenv("UI_V2_DIR", str(dist))
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/ui/v2/"


def test_root_reports_missing_v2_without_legacy_fallback(build_test_engine, fake_settings, tmp_path, monkeypatch):
    """V2 产物缺失时如实 503；已退役 v1 不再被静默复活."""
    monkeypatch.setenv("UI_V2_DIR", str(tmp_path / "nonexistent"))
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/")
    assert resp.status_code == 503
    assert resp.json()["error"] == "frontend_missing"


def test_legacy_static_app_js_not_served(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/static/app.js")
    assert resp.status_code == 404


def test_legacy_static_style_css_not_served(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/static/style.css")
    assert resp.status_code == 404


def test_api_info_returns_json(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/api/info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "llm-first-loop-web"
    assert "api/v1/chat" in str(body["endpoints"])

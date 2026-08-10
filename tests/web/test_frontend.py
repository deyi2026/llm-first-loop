"""Web 前端测试（M37，静态检查 + API 集成断言，FakeLLM 装配零真实冒烟）.

用例：HTML 存在性 / root 返回 HTML / /static 静态资源可达 / /api/info / 前端页面关键元素。
"""

from fastapi.testclient import TestClient

from llm_loop.web import build_app


def _make_client(engine):
    return TestClient(build_app(engine=engine))


def test_index_html_exists():
    import os
    from pathlib import Path

    index = Path(__file__).resolve().parents[2] / "src" / "llm_loop" / "web" / "static" / "index.html"
    assert index.exists()
    content = index.read_text(encoding="utf-8")
    assert "id=\"messages\"" in content
    assert "id=\"session-list\"" in content
    assert "id=\"message-input\"" in content
    assert "app.js" in content


def test_root_returns_html(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "<!DOCTYPE html>" in resp.text
    assert "LLM-First Loop" in resp.text


def test_static_app_js_reachable(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/static/app.js")
    assert resp.status_code == 200
    assert "application/javascript" in resp.headers["content-type"] or "text/javascript" in resp.headers["content-type"]
    assert "sendMessage" in resp.text


def test_static_style_css_reachable(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/static/style.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]
    assert "#sidebar" in resp.text


def test_api_info_returns_json(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/api/info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "llm-first-loop-web"
    assert "api/v1/chat" in str(body["endpoints"])
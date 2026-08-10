"""Web 鉴权测试（M36，FakeLLM 装配零真实冒烟）.

用例 15-18：远程无令牌 401 / 有效令牌 200 / 回环免鉴权 / 敏感信息不外泄。
复用 tests/conftest.py 的 build_test_engine fixture（既有装配，不复制逻辑）。
"""

from fastapi.testclient import TestClient

from llm_loop.web import build_app


def _make_client(engine):
    return TestClient(build_app(engine=engine))


def test_remote_no_token_401(build_test_engine, fake_settings, monkeypatch):
    monkeypatch.setenv("WEB_API_KEY", "secret-key")
    monkeypatch.setenv("WEB_HOST", "0.0.0.0")
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/health")
    assert resp.status_code == 401


def test_remote_valid_token_200(build_test_engine, fake_settings, monkeypatch):
    monkeypatch.setenv("WEB_API_KEY", "secret-key")
    monkeypatch.setenv("WEB_HOST", "0.0.0.0")
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/health", headers={"Authorization": "Bearer secret-key"})
    assert resp.status_code == 200


def test_loopback_no_auth_required(build_test_engine, fake_settings, monkeypatch):
    monkeypatch.delenv("WEB_API_KEY", raising=False)
    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    monkeypatch.delenv("WEB_AUTH_REQUIRE", raising=False)
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_sensitive_keys_not_leaked(build_test_engine, fake_settings, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "llm-secret-xyz")
    monkeypatch.setenv("WEB_API_KEY", "web-secret-xyz")
    engine, _ = build_test_engine([{"content": "ok"}])
    client = _make_client(engine)
    resp = client.post("/api/v1/chat", json={"message": "x"})
    assert resp.status_code == 200
    assert "llm-secret-xyz" not in resp.text
    assert "web-secret-xyz" not in resp.text
    health = client.get("/health")
    assert "llm-secret-xyz" not in health.text

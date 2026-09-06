"""Web 鉴权测试（M36，FakeLLM 装配零真实冒烟）.

用例 15-18：远程无令牌 401 / 有效令牌 200 / 回环免鉴权 / 敏感信息不外泄。
复用 tests/conftest.py 的 build_test_engine fixture（既有装配，不复制逻辑）。
"""

import pytest
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


def test_public_domain_browser_login_cookie_protects_api_and_ui(
    build_test_engine, monkeypatch, tmp_path
):
    from llm_loop.web.auth import SESSION_COOKIE_NAME, hash_login_password

    ui = tmp_path / "dist"
    ui.mkdir()
    (ui / "index.html").write_text("<html>private-ui</html>", encoding="utf-8")
    monkeypatch.setenv("UI_V2_DIR", str(ui))
    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_ORIGIN_ALLOWLIST", "https://app.llmfirstloop.com,https://llmfirstloop.com")
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", hash_login_password("correct-horse-battery"))
    monkeypatch.delenv("WEB_API_KEY", raising=False)

    engine, _ = build_test_engine([])
    client = TestClient(build_app(engine=engine), base_url="https://app.llmfirstloop.com")

    ui_resp = client.get("/ui/v2/", follow_redirects=False)
    assert ui_resp.status_code == 303
    assert ui_resp.headers["location"].startswith("/login?next=")
    assert client.get("/health").status_code == 401

    bad = client.post(
        "/auth/login",
        data={"password": "wrong-password", "next": "/ui/v2/"},
        headers={"Origin": "https://app.llmfirstloop.com"},
        follow_redirects=False,
    )
    assert bad.status_code == 401
    assert SESSION_COOKIE_NAME not in bad.cookies

    good = client.post(
        "/auth/login",
        data={"password": "correct-horse-battery", "next": "/ui/v2/"},
        headers={"Origin": "https://app.llmfirstloop.com", "X-Forwarded-Proto": "https"},
        follow_redirects=False,
    )
    assert good.status_code == 303
    cookie_header = good.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "SameSite=strict" in cookie_header
    assert "Secure" in cookie_header

    assert client.get("/health").status_code == 200
    private_ui = client.get("/ui/v2/")
    assert private_ui.status_code == 200
    assert "private-ui" in private_ui.text

    logout = client.post("/auth/logout")
    assert logout.status_code == 200
    assert client.get("/health").status_code == 401



def test_browser_login_preserves_pasted_complex_password_exactly(
    build_test_engine, monkeypatch, tmp_path
):
    """Form decoding must preserve password-manager/paste content exactly, including reserved chars."""
    from llm_loop.web.auth import hash_login_password

    password = "Paste Me +&=$%# 12345"
    ui = tmp_path / "dist"
    ui.mkdir()
    (ui / "index.html").write_text("<html>private-ui</html>", encoding="utf-8")
    monkeypatch.setenv("UI_V2_DIR", str(ui))
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_ORIGIN_ALLOWLIST", "https://app.llmfirstloop.com")
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", hash_login_password(password))
    monkeypatch.delenv("WEB_API_KEY", raising=False)

    engine, _ = build_test_engine([])
    client = TestClient(build_app(engine=engine), base_url="https://app.llmfirstloop.com")
    page = client.get("/login")
    assert page.status_code == 200
    assert "手机端使用普通键盘" in page.text
    assert 'id="password"' in page.text
    assert 'type="text"' in page.text
    assert 'inputmode="text"' in page.text
    assert 'autocomplete="off"' in page.text
    assert 'type="password"' not in page.text
    assert 'password-paste' not in page.text
    assert '-webkit-text-security:disc' in page.text
    assert 'autofocus' not in page.text

    response = client.post(
        "/auth/login",
        data={"password": password, "next": "/ui/v2/"},
        headers={"X-Forwarded-Proto": "https"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert client.get("/health").status_code == 200

def test_domain_allowlist_with_login_hash_satisfies_fail_closed(monkeypatch):
    from llm_loop.web.auth import hash_login_password, validate_origin_allowlist

    monkeypatch.setenv("WEB_ORIGIN_ALLOWLIST", "https://app.llmfirstloop.com")
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", hash_login_password("correct-horse-battery"))
    monkeypatch.delenv("WEB_API_KEY", raising=False)
    validate_origin_allowlist()


def test_login_redirect_rejects_cross_origin_normalization_tricks():
    from llm_loop.web.auth_routes import _safe_next

    assert _safe_next("/ui/v2/?x=1") == "/ui/v2/?x=1"
    for unsafe in (
        "https://evil.example/",
        "//evil.example/",
        "///evil.example/",
        "/%2F%2Fevil.example/",
        "/%0D%0ALocation:%20https://evil.example/",
        "/%5C%5Cevil.example/",
        "/\\evil.example/",
        "/ui/v2/\nLocation: https://evil.example/",
    ):
        assert _safe_next(unsafe) == "/ui/v2/"


def test_invalid_origin_allowlist_fails_startup(monkeypatch):
    from llm_loop.web.auth import hash_login_password, validate_origin_allowlist

    monkeypatch.setenv("WEB_ORIGIN_ALLOWLIST", "https://app.example.com/not-an-origin")
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", hash_login_password("correct-horse-battery"))
    try:
        validate_origin_allowlist()
    except RuntimeError as exc:
        assert "WEB_ORIGIN_ALLOWLIST" in str(exc)
    else:
        raise AssertionError("invalid origin allowlist must fail closed")


def test_bare_origin_allowlist_means_https_exact_origin(monkeypatch):
    from llm_loop.web.auth import configured_origin_allowlist

    monkeypatch.setenv("WEB_ORIGIN_ALLOWLIST", "App.Example.COM,https://api.example.com:443")
    assert configured_origin_allowlist() == frozenset({
        "https://app.example.com",
        "https://api.example.com",
    })


def test_login_payload_size_is_bounded_before_password_verification(
    build_test_engine, monkeypatch
):
    from llm_loop.web.auth import hash_login_password

    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", hash_login_password("correct-horse-battery"))
    engine, _ = build_test_engine([])
    client = TestClient(build_app(engine=engine), base_url="https://app.example.com")
    huge = "x" * (17 * 1024)
    response = client.post(
        "/auth/login",
        data={"password": huge},
        headers={"Origin": "https://app.example.com"},
    )
    assert response.status_code == 413


def test_api_key_only_does_not_validate_unused_browser_session_ttl(monkeypatch):
    from llm_loop.web.auth import validate_auth_require

    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_API_KEY", "k-" + "x" * 20)
    monkeypatch.delenv("WEB_LOGIN_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("WEB_SESSION_TTL_SECONDS", "not-used")
    validate_auth_require()


def test_public_https_origin_forces_secure_cookie_even_if_local_proxy_hop_is_http(
    build_test_engine, monkeypatch
):
    from llm_loop.web.auth import hash_login_password

    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_ORIGIN_ALLOWLIST", "https://app.example.com")
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", hash_login_password("correct-horse-battery"))
    engine, _ = build_test_engine([])
    client = TestClient(build_app(engine=engine), base_url="http://127.0.0.1:8902")
    response = client.post(
        "/auth/login",
        data={"password": "correct-horse-battery", "next": "/ui/v2/"},
        headers={"Origin": "https://app.example.com"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "Secure" in response.headers["set-cookie"]


@pytest.mark.parametrize("base_url", [
    "http://127.0.0.1:8903", "https://app.example.com",
])
def test_html_login_preserves_same_origin_on_first_attempt_and_retry(
    base_url, build_test_engine, monkeypatch
):
    """HTML POST needs a non-null Origin; no-referrer breaks that even same-origin."""
    from llm_loop.web.auth import hash_login_password

    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", hash_login_password("test-login-password"))
    monkeypatch.delenv("WEB_ORIGIN_ALLOWLIST", raising=False)
    engine, _ = build_test_engine([])
    client = TestClient(build_app(engine=engine), base_url=base_url)
    for path in ("/login", "/auth/login"):
        page = client.get(path)
        assert page.status_code == 200
        assert page.headers["Referrer-Policy"] == "same-origin"
        assert page.headers["Cache-Control"] == "no-store"
        assert "form-action 'self'" in page.headers["Content-Security-Policy"]
        assert 'method="post" action="/auth/login"' in page.text

    rejected = client.post(
        "/auth/login", data={"password": "wrong-password"}, headers={"Origin": base_url}
    )
    assert rejected.status_code == 401
    assert rejected.headers["Referrer-Policy"] == "same-origin"
    accepted = client.post(
        "/auth/login", data={"password": "test-login-password"},
        headers={"Origin": base_url}, follow_redirects=False,
    )
    assert accepted.status_code == 303
    assert client.get("/health").status_code == 200

    for origin in ("null", "https://evil.example", base_url + ":8443"):
        blocked = client.post("/auth/logout", headers={"Origin": origin})
        assert blocked.status_code == 403
        assert blocked.json()["error"] == "foreign_origin_forbidden"
    assert client.get("/health").status_code == 200
    assert client.post("/auth/logout", headers={"Origin": base_url}).status_code == 200
    assert client.get("/health").status_code == 401

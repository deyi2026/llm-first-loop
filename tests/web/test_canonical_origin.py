"""2026-09-30 登录循环修复回归 II：http→https 与别名主机名 308 归一。

事故背景：父域 cookie 上线后，web.log 仍出现 favicon.svg 200/303 交替——
同一浏览器 https 会话有效，但历史记录/自动补全里的 http://llmfirstloop.com
入口不携带 Secure cookie、app.llmfirstloop.com 旧入口同样分裂，用户偶发
"刚输完密码又弹登录框"。

修复：WEB_CANONICAL_HOST=llmfirstloop.com 时，经可信回环代理回源的请求
proto=http 一律升级 https，别名主机名一律 308 到 canonical（保留方法与请求体）。
本地直连（无 x-forwarded-proto）完全不受影响。
"""

import pytest
from fastapi.testclient import TestClient

import llm_loop.web as web_module
from llm_loop.web import build_app
from llm_loop.web.auth import SESSION_COOKIE_NAME, hash_login_password

TEST_PASSWORD = "test-password-12345"


@pytest.fixture()
def canonical_env(fake_settings, monkeypatch):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", hash_login_password(TEST_PASSWORD))
    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    monkeypatch.setenv("WEB_CANONICAL_HOST", "llmfirstloop.com")
    monkeypatch.setattr(web_module, "is_loopback", lambda _h: True)  # TestClient peer


def _client(engine, base_url: str) -> TestClient:
    return TestClient(build_app(engine=engine), base_url=base_url)


def test_http_public_upgrades_to_https_308(build_test_engine, canonical_env):
    engine, _ = build_test_engine([])
    with _client(engine, "http://llmfirstloop.com") as client:
        resp = client.get(
            "/ui/v2/",
            headers={"x-forwarded-proto": "http"},
            follow_redirects=False,
        )
    assert resp.status_code == 308
    assert resp.headers["location"] == "https://llmfirstloop.com/ui/v2/"


def test_alias_host_redirects_to_canonical_308(build_test_engine, canonical_env):
    engine, _ = build_test_engine([])
    with _client(engine, "https://app.llmfirstloop.com") as client:
        resp = client.get(
            "/ui/v2/?session=abc",
            headers={"x-forwarded-proto": "https"},
            follow_redirects=False,
        )
    assert resp.status_code == 308
    assert resp.headers["location"] == "https://llmfirstloop.com/ui/v2/?session=abc"


def test_canonical_https_passes_through(build_test_engine, canonical_env):
    engine, _ = build_test_engine([])
    with _client(engine, "https://llmfirstloop.com") as client:
        resp = client.get(
            "/login",
            headers={"x-forwarded-proto": "https"},
            follow_redirects=False,
        )
    assert resp.status_code == 200  # 登录页直达，不重定向


def test_direct_loopback_without_xfp_untouched(build_test_engine, canonical_env):
    engine, _ = build_test_engine([])
    with _client(engine, "http://127.0.0.1:8903") as client:
        resp = client.get("/login", follow_redirects=False)
    assert resp.status_code == 200


def test_post_login_http_upgrades_method_preserved(build_test_engine, canonical_env):
    engine, _ = build_test_engine([])
    with _client(engine, "http://llmfirstloop.com") as client:
        resp = client.post(
            "/auth/login",
            data={"password": TEST_PASSWORD, "next": "/ui/v2/"},
            headers={"x-forwarded-proto": "http"},
            follow_redirects=False,
        )
    assert resp.status_code == 308  # 308 保留方法/请求体 → 浏览器以 https 重发表单
    assert resp.headers["location"] == "https://llmfirstloop.com/auth/login"


def test_unset_canonical_host_disables_middleware(build_test_engine, fake_settings, monkeypatch):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", hash_login_password(TEST_PASSWORD))
    monkeypatch.delenv("WEB_CANONICAL_HOST", raising=False)
    monkeypatch.setattr(web_module, "is_loopback", lambda _h: True)
    engine, _ = build_test_engine([])
    with _client(engine, "https://app.llmfirstloop.com") as client:
        resp = client.get(
            "/ui/v2/",
            headers={"x-forwarded-proto": "https"},
            follow_redirects=False,
        )
    assert resp.status_code == 303  # 走原有 auth gate → /login
    assert "/login" in resp.headers["location"]


def test_session_cookie_name_is_v2(build_test_engine, canonical_env):
    """cookie 名版本化：历史同名多值污染(lfl_web_session)永不再被发送。"""
    assert SESSION_COOKIE_NAME == "lfl_web_session_v2"
    engine, _ = build_test_engine([])
    with _client(engine, "https://llmfirstloop.com") as client:
        resp = client.post(
            "/auth/login",
            data={"password": TEST_PASSWORD, "next": "/ui/v2/"},
            headers={"x-forwarded-proto": "https"},
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert resp.headers["set-cookie"].startswith("lfl_web_session_v2=")

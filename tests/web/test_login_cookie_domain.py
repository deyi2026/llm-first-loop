"""2026-09-30 登录循环修复回归：双主机名共享会话。

事故背景：app.llmfirstloop.com 与 llmfirstloop.com 经同一 Cloudflare tunnel
路由到同一源站，但 session cookie 默认 host-only，浏览器给两个主机名各存一份
cookie。用户在两域间切换（书签/历史建议）时被反复弹回登录页——服务端日志
表现为 POST /auth/login 303（密码正确）紧跟 GET /ui/v2/ 303（该主机名下无
有效会话）的循环。

修复：WEB_SESSION_COOKIE_DOMAIN=llmfirstloop.com 使 Set-Cookie 带 Domain=，
浏览器（RFC 6265）对 llmfirstloop.com 及其全部子域携带同一 cookie，登录一次
全域有效。测试直断 Set-Cookie 属性与服务端 token 全局有效性，跨主机名携带
本身是浏览器标准行为。
"""

import pytest
from fastapi.testclient import TestClient

from llm_loop.web import build_app
from llm_loop.web.auth import SESSION_COOKIE_NAME, hash_login_password

TEST_PASSWORD = "test-password-12345"


@pytest.fixture(autouse=True)
def ui_v2_stub_dist(tmp_path, monkeypatch):
    """/ui/v2/ 依构建产物存在性条件挂载（webui/dist 在 .gitignore，CI 无产物）。

    本文件全部流程围绕 /ui/v2/ 展开：注入临时产物目录使挂载确定发生，
    摆脱对本机构建产物的隐性依赖（远端 CI 首跑实测 404）。
    """
    ui = tmp_path / "dist"
    ui.mkdir()
    (ui / "index.html").write_text("<html>stub-ui</html>", encoding="utf-8")
    monkeypatch.setenv("UI_V2_DIR", str(ui))


@pytest.fixture()
def auth_env(fake_settings, monkeypatch):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", hash_login_password(TEST_PASSWORD))
    monkeypatch.setenv("WEB_HOST", "127.0.0.1")


def _client(engine, *, base_url: str = "http://testserver"):
    return TestClient(build_app(engine=engine), base_url=base_url)


def _login(client):
    return client.post(
        "/auth/login",
        data={"password": TEST_PASSWORD, "next": "/ui/v2/"},
        follow_redirects=False,
    )


def _cookie_header(resp) -> str:
    return resp.headers.get("set-cookie", "")


def _session_token(resp) -> str:
    """Extract token from raw Set-Cookie header (jar may reject test hosts)."""
    header = _cookie_header(resp)
    prefix = f"{SESSION_COOKIE_NAME}="
    if not header.startswith(prefix):
        return ""
    return header[len(prefix):].split(";", 1)[0]


def test_default_host_only_cookie_reproduces_loop(build_test_engine, auth_env, monkeypatch):
    """旧行为：无 Domain 属性 → 浏览器 per-host 隔离，另一主机名下无会话。"""
    monkeypatch.delenv("WEB_SESSION_COOKIE_DOMAIN", raising=False)
    engine, _ = build_test_engine([])
    app = build_app(engine=engine)
    client = TestClient(app)
    sibling_browser = TestClient(app)  # 另一主机名的浏览器：独立 jar，无 cookie

    resp = _login(client)
    assert resp.status_code == 303
    assert SESSION_COOKIE_NAME in _cookie_header(resp)
    assert "domain=" not in _cookie_header(resp).lower()

    # sibling 浏览器不带 cookie 打开页面：弹回登录页
    bounced = sibling_browser.get("/ui/v2/", follow_redirects=False)
    assert bounced.status_code == 303
    assert bounced.headers["location"].startswith("/login")


def test_parent_domain_cookie_marks_shared_scope(build_test_engine, auth_env, monkeypatch):
    """修复后：Set-Cookie 带 Domain=llmfirstloop.com，token 服务端全局有效。"""
    monkeypatch.setenv("WEB_SESSION_COOKIE_DOMAIN", "llmfirstloop.com")
    engine, _ = build_test_engine([])
    client = _client(engine, base_url="https://app.llmfirstloop.com")

    resp = _login(client)
    assert resp.status_code == 303
    cookie = _cookie_header(resp)
    assert "domain=llmfirstloop.com" in cookie.lower()

    token = _session_token(resp)
    assert token
    # 携带该 cookie 的请求（任意主机名）直接放行进入 UI
    ok = client.get(
        "/ui/v2/",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
        follow_redirects=False,
    )
    assert ok.status_code == 200


def test_parent_domain_config_keeps_loopback_cookie_host_only(build_test_engine, auth_env, monkeypatch):
    """本机运维入口不能发送公网 Domain，否则浏览器会直接拒绝整个 cookie。"""
    monkeypatch.setenv("WEB_SESSION_COOKIE_DOMAIN", "llmfirstloop.com")
    engine, _ = build_test_engine([])
    client = TestClient(build_app(engine=engine), base_url="http://127.0.0.1:8903")

    resp = _login(client)
    assert resp.status_code == 303
    cookie = _cookie_header(resp)
    assert SESSION_COOKIE_NAME in cookie
    assert "domain=" not in cookie.lower()

    # The browser jar accepts the host-only cookie and the immediate redirect
    # target is authenticated instead of looping back to /login.
    ok = client.get("/ui/v2/", follow_redirects=False)
    assert ok.status_code == 200


def test_logout_delete_cookie_keeps_domain_scope(build_test_engine, auth_env, monkeypatch):
    monkeypatch.setenv("WEB_SESSION_COOKIE_DOMAIN", "llmfirstloop.com")
    engine, _ = build_test_engine([])
    client = _client(engine, base_url="https://app.llmfirstloop.com")

    resp = _login(client)
    token = _session_token(resp)
    out = client.post("/auth/logout", headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"})
    assert out.status_code == 200
    assert "domain=llmfirstloop.com" in _cookie_header(out).lower()

    after = client.get(
        "/ui/v2/",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
        follow_redirects=False,
    )
    assert after.status_code == 303

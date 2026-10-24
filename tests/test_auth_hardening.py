"""Web 鉴权面加固回归（建议书 2026-10-25：P1-4 / P2-6 / S3 系列）。

覆盖：
- S3-1/P2-6a  openapi/docs/redoc 默认关闭，LFL_WEB_OPENAPI=1 恢复；
- P1-4b       HostGuard 中间件（Host 白名单 / X-Forwarded-Host 仅信 TRUST_PROXY）；
- S3-4/P2-6b  PBKDF2 600k + 登录成功后 rehash-on-login（旧 310k 哈希原地升级）；
- S3-6/P2-6c  secure 场景 __Host- 前缀 cookie 名 + 新旧双名读取兼容；
- S3-8        限流键不可被客户端头伪造（TRUST_PROXY 显式开启才信任）+ 容量上限/过期清理；
- S3-2        realtime WS 真实麦克风会话要求浏览器会话 cookie（Bearer-only →
              ws_requires_browser_session/4405）+ Origin 白名单；
- S3-3        登录页 SameSite 文案与实现（Lax）一致；
- S3-5        auth 模块 docstring 声明"会话仅存内存、重启即失效"能力边界。

既有 fail-closed 行为（require_api_key 未配密钥 503、validate_* 启动硬失败）已在
auth.py 内实现并有既有测试覆盖，此处不重复。
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from llm_loop.web import auth as web_auth
from llm_loop.web import build_app
from llm_loop.web.auth import (
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_NAME_SECURE,
    LoginRateLimiter,
    WebSessionStore,
    client_rate_limit_key,
    hash_login_password,
    rehash_login_password_if_needed,
)
from llm_loop.web.realtime_ws import (
    CLOSE_REQUIRES_BROWSER_SESSION,
    REALTIME_WS_PATH,
    HandshakeFacts,
    HandshakeRejection,
    close_code_for,
    evaluate_handshake,
    register_realtime_ws,
)

_TEST_PASSWORD = "correct-horse-battery"

_WEB_ENV_VARS = (
    "WEB_AUTH_REQUIRE",
    "WEB_API_KEY",
    "WEB_LOGIN_PASSWORD_HASH",
    "WEB_ORIGIN_ALLOWLIST",
    "WEB_CANONICAL_HOST",
    "WEB_SESSION_COOKIE_DOMAIN",
    "WEB_HOST",
    "WEB_SESSION_TTL_SECONDS",
    "LFL_WEB_ALLOWED_HOSTS",
    "LFL_WEB_ALLOWED_ORIGINS",
    "LFL_WEB_TRUST_PROXY",
    "LFL_WEB_OPENAPI",
    "LFL_ENV_FILE",
    "UI_V2_DIR",
)


@pytest.fixture(autouse=True)
def _clean_web_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _WEB_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("WEB_HOST", "127.0.0.1")


def _client(engine, base_url: str, client_addr=("127.0.0.1", 50000)) -> TestClient:
    return TestClient(build_app(engine=engine), base_url=base_url, client=client_addr)


# ── S3-1 / P2-6a：openapi/docs/redoc 默认关闭 ────────────────────────────────


def test_openapi_docs_redoc_disabled_by_default(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = TestClient(build_app(engine=engine))
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_openapi_docs_restored_with_env_flag(build_test_engine, fake_settings, monkeypatch):
    monkeypatch.setenv("LFL_WEB_OPENAPI", "1")
    engine, _ = build_test_engine([])
    client = TestClient(build_app(engine=engine))
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


# ── P1-4b：HostGuard ──────────────────────────────────────────────────────────


def test_hostguard_rejects_foreign_host_with_400(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _client(engine, "http://evil.example:8903")
    resp = client.get("/auth/status")
    assert resp.status_code == 400
    assert resp.json()["error"] == "host_not_allowed"


@pytest.mark.parametrize(
    "base_url",
    ["http://127.0.0.1:8903", "http://127.0.0.1:8090", "http://localhost:8903"],
)
def test_hostguard_allows_loopback_hosts(build_test_engine, fake_settings, base_url):
    engine, _ = build_test_engine([])
    assert _client(engine, base_url).get("/auth/status").status_code == 200


def test_hostguard_allows_ipv6_loopback_via_host_header(build_test_engine, fake_settings):
    # starlette TestClient 解析不了 IPv6 base_url（int(':1]:8903')），
    # 改用 Host 头走同一条 HostGuard 判定路径，避免测试夹具限制掩盖真实行为
    engine, _ = build_test_engine([])
    resp = _client(engine, "http://127.0.0.1:8903").get("/auth/status", headers={"host": "[::1]:8903"})
    assert resp.status_code == 200


def test_hostguard_honors_lfl_web_allowed_hosts(build_test_engine, fake_settings, monkeypatch):
    monkeypatch.setenv("LFL_WEB_ALLOWED_HOSTS", "box.example, alt.example:9000")
    engine, _ = build_test_engine([])
    assert _client(engine, "http://box.example:8903").get("/auth/status").status_code == 200
    assert _client(engine, "http://alt.example:9000").get("/auth/status").status_code == 200
    assert _client(engine, "http://other.example:8903").get("/auth/status").status_code == 400


def test_hostguard_x_forwarded_host_only_trusted_with_env(
    build_test_engine, fake_settings, monkeypatch
):
    engine, _ = build_test_engine([])
    # 未声明可信代理：X-Forwarded-Host 不参与判定，Host(127.0.0.1) 放行。
    resp = _client(engine, "http://127.0.0.1:8903").get(
        "/auth/status", headers={"X-Forwarded-Host": "evil.example"}
    )
    assert resp.status_code == 200

    # 声明可信代理后：X-Forwarded-Host 参与判定 → 伪造值被拒绝。
    monkeypatch.setenv("LFL_WEB_TRUST_PROXY", "1")
    engine2, _ = build_test_engine([])
    resp = _client(engine2, "http://127.0.0.1:8903").get(
        "/auth/status", headers={"X-Forwarded-Host": "evil.example"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "host_not_allowed"
    # 可信代理 + 白名单主机 → 放行。
    monkeypatch.setenv("LFL_WEB_ALLOWED_HOSTS", "box.example")
    engine3, _ = build_test_engine([])
    resp = _client(engine3, "http://127.0.0.1:8903").get(
        "/auth/status", headers={"X-Forwarded-Host": "box.example"}
    )
    assert resp.status_code == 200


def test_hostguard_allows_canonical_host_and_its_subdomains(
    build_test_engine, fake_settings, monkeypatch
):
    monkeypatch.setenv("WEB_CANONICAL_HOST", "example.com")
    engine, _ = build_test_engine([])
    assert _client(engine, "http://example.com").get("/auth/status").status_code == 200
    assert _client(engine, "http://sub.example.com").get("/auth/status").status_code == 200
    assert _client(engine, "http://notexample.com").get("/auth/status").status_code == 400


def test_hostguard_allows_origin_allowlist_hosts(build_test_engine, fake_settings, monkeypatch):
    monkeypatch.setenv("WEB_ORIGIN_ALLOWLIST", "https://app.example.com")
    engine, _ = build_test_engine([])
    assert _client(engine, "https://app.example.com").get("/auth/status").status_code == 200


def test_hostguard_keeps_default_testclient_host_usable(build_test_engine, fake_settings):
    """兼容哨兵：进程内 TestClient（peer=testclient，不可来自真实网络）不受 Host 门禁影响。"""
    engine, _ = build_test_engine([])
    client = TestClient(build_app(engine=engine))  # 默认 Host: testserver
    assert client.get("/auth/status").status_code == 200


# ── S3-4 / P2-6b：PBKDF2 600k + rehash-on-login ──────────────────────────────


def test_password_iterations_raised_to_600k():
    assert web_auth._PASSWORD_ITERATIONS == 600_000


def test_old_310k_hash_login_succeeds_and_upgrades_in_place(
    build_test_engine, fake_settings, monkeypatch, tmp_path
):
    old_hash = hash_login_password(_TEST_PASSWORD, iterations=310_000)
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"WEB_LOGIN_PASSWORD_HASH={old_hash}\nWEB_PORT=8903\n", encoding="utf-8"
    )
    monkeypatch.setenv("LFL_ENV_FILE", str(env_file))
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", old_hash)
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    engine, _ = build_test_engine([])
    client = TestClient(build_app(engine=engine), base_url="https://app.example.com")

    first = client.post(
        "/auth/login",
        data={"password": _TEST_PASSWORD, "next": "/ui/v2/"},
        headers={"Origin": "https://app.example.com"},
        follow_redirects=False,
    )
    assert first.status_code == 303  # 旧 310k 哈希仍可登录（按哈希串内记录的迭代数校验）

    upgraded = os.environ["WEB_LOGIN_PASSWORD_HASH"]
    assert "$310000$" not in upgraded and "$600000$" in upgraded
    file_text = env_file.read_text(encoding="utf-8")
    assert "$600000$" in file_text  # 原子写回 .env
    assert "WEB_PORT=8903" in file_text  # 仅替换目标行

    # 升级后同一密码仍可登录（600k 校验路径）。
    second = client.post(
        "/auth/login",
        data={"password": _TEST_PASSWORD, "next": "/ui/v2/"},
        headers={"Origin": "https://app.example.com"},
        follow_redirects=False,
    )
    assert second.status_code == 303


def test_rehash_never_clobbers_hash_with_wrong_password(monkeypatch):
    old_hash = hash_login_password(_TEST_PASSWORD, iterations=310_000)
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", old_hash)
    assert rehash_login_password_if_needed("wrong-wrong-wrong-123") is False
    assert os.environ["WEB_LOGIN_PASSWORD_HASH"] == old_hash


def test_rehash_noop_when_already_at_current_iterations(monkeypatch):
    modern = hash_login_password(_TEST_PASSWORD)  # 600k
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", modern)
    assert rehash_login_password_if_needed(_TEST_PASSWORD) is False
    assert os.environ["WEB_LOGIN_PASSWORD_HASH"] == modern


# ── S3-6 / P2-6c：__Host- 前缀 + 双名读取 ────────────────────────────────────


def test_secure_login_uses_host_prefixed_cookie_and_legacy_twin(
    build_test_engine, fake_settings, monkeypatch
):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", hash_login_password(_TEST_PASSWORD))
    engine, _ = build_test_engine([])
    client = TestClient(build_app(engine=engine), base_url="https://app.example.com")
    resp = client.post(
        "/auth/login",
        data={"password": _TEST_PASSWORD, "next": "/ui/v2/"},
        headers={"Origin": "https://app.example.com", "X-Forwarded-Proto": "https"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    cookies = resp.headers.get_list("set-cookie")
    prefixed = [c for c in cookies if c.startswith(f"{SESSION_COOKIE_NAME_SECURE}=")]
    assert prefixed, f"__Host- 前缀 cookie 缺失: {cookies}"
    assert "Secure" in prefixed[0] and "Path=/" in prefixed[0] and "Domain" not in prefixed[0]
    # 过渡孪生：旧名同值 cookie（供仅读旧名的既有读者），属性一致。
    legacy = [c for c in cookies if c.startswith(f"{SESSION_COOKIE_NAME}=")]
    assert legacy and "Secure" in legacy[0]

    # 会话在双名读取下生效（jar 会同时带两个名字回传）。
    status = client.get("/auth/status").json()
    assert status["authenticated"] is True

    # 登出后两个名字都被清理。
    logout = client.post("/auth/logout", headers={"Origin": "https://app.example.com"})
    assert logout.status_code == 200
    assert client.get("/auth/status").json()["authenticated"] is False


def test_non_secure_loopback_login_keeps_legacy_cookie_name(
    build_test_engine, fake_settings, monkeypatch
):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", hash_login_password(_TEST_PASSWORD))
    engine, _ = build_test_engine([])
    client = TestClient(build_app(engine=engine), base_url="http://127.0.0.1:8903")
    resp = client.post(
        "/auth/login",
        data={"password": _TEST_PASSWORD, "next": "/ui/v2/"},
        headers={"Origin": "http://127.0.0.1:8903"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    cookies = resp.headers.get_list("set-cookie")
    assert cookies and all(c.startswith(f"{SESSION_COOKIE_NAME}=") for c in cookies)
    assert client.get("/auth/status").json()["authenticated"] is True


def test_secure_login_with_cookie_domain_keeps_legacy_name(
    build_test_engine, fake_settings, monkeypatch
):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", hash_login_password(_TEST_PASSWORD))
    monkeypatch.setenv("WEB_SESSION_COOKIE_DOMAIN", "app.example.com")
    engine, _ = build_test_engine([])
    client = TestClient(build_app(engine=engine), base_url="https://app.example.com")
    resp = client.post(
        "/auth/login",
        data={"password": _TEST_PASSWORD, "next": "/ui/v2/"},
        headers={"Origin": "https://app.example.com", "X-Forwarded-Proto": "https"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    cookies = resp.headers.get_list("set-cookie")
    # __Host- 与 Domain 属性互斥：设了 Domain 时不使用前缀名。
    assert all(not c.startswith("__Host-") for c in cookies)
    assert any("Domain=app.example.com" in c for c in cookies)


def test_legacy_cookie_name_still_authenticated(build_test_engine, fake_settings, monkeypatch):
    """双读兼容：仅携带旧名 cookie 的既有浏览器仍被识别。"""
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    engine, _ = build_test_engine([])
    app = build_app(engine=engine)
    store = app.state.web_sessions
    token = store.create(ttl_seconds=300)
    client = TestClient(app, base_url="http://127.0.0.1:8903")
    legacy = client.get("/auth/status", headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"})
    assert legacy.json()["authenticated"] is True
    token2 = store.create(ttl_seconds=300)
    prefixed = client.get(
        "/auth/status", headers={"Cookie": f"{SESSION_COOKIE_NAME_SECURE}={token2}"}
    )
    assert prefixed.json()["authenticated"] is True


# ── S3-8：限流键不可伪造 + 容量上限/过期清理 ─────────────────────────────────


class _FakeRequest:
    def __init__(self, peer: str, headers: dict | None = None) -> None:
        self.client = SimpleNamespace(host=peer)
        self.headers = headers or {}


def test_rate_limit_key_ignores_forged_headers_by_default():
    request = _FakeRequest(
        "127.0.0.1",
        {"cf-connecting-ip": "203.0.113.9", "x-forwarded-for": "198.51.100.7"},
    )
    assert client_rate_limit_key(request) == "127.0.0.1"  # 头伪造不改变键


def test_rate_limit_key_trusts_forwarded_headers_only_with_trust_proxy(monkeypatch):
    request = _FakeRequest(
        "127.0.0.1",
        {"cf-connecting-ip": "203.0.113.9", "x-forwarded-for": "198.51.100.7, 10.0.0.1"},
    )
    monkeypatch.setenv("LFL_WEB_TRUST_PROXY", "1")
    assert client_rate_limit_key(request) == "203.0.113.9"  # cf 优先
    request_xff_only = _FakeRequest("127.0.0.1", {"x-forwarded-for": "198.51.100.7, 10.0.0.1"})
    assert client_rate_limit_key(request_xff_only) == "198.51.100.7"  # 首跳
    request_junk = _FakeRequest("127.0.0.1", {"cf-connecting-ip": "not-an-ip"})
    assert client_rate_limit_key(request_junk) == "127.0.0.1"  # 非法值回退 peer


def test_login_rate_limiter_map_is_bounded_and_lru_evicted():
    limiter = LoginRateLimiter(max_failures=5, window_seconds=300, max_keys=4)
    for i in range(10):
        limiter.record_failure(f"key-{i}")
    assert len(limiter._failures) == 4
    assert "key-0" not in limiter._failures  # 最旧的先被淘汰
    assert "key-9" in limiter._failures
    assert limiter.check("key-9").allowed is True  # 未超失败次数
    for _ in range(5):
        limiter.record_failure("key-9")
    assert limiter.check("key-9").allowed is False  # 超限生效
    limiter.record_success("key-9")
    assert limiter.check("key-9").allowed is True


def test_login_rate_limiter_prunes_expired_buckets():
    limiter = LoginRateLimiter(max_failures=2, window_seconds=0)  # 立即过期
    limiter.record_failure("k")
    assert limiter.check("k").allowed is True
    assert len(limiter._failures) == 0  # 过期桶被清理，防内存膨胀


# ── S3-2：realtime WS 需浏览器会话 + Origin ──────────────────────────────────


def _ws_facts(**over: object) -> HandshakeFacts:
    base: dict[str, object] = {
        "authenticated": True,
        "origin": "https://app.example.com",
        "allowed_origins": frozenset({"https://app.example.com"}),
        "trusted_local": False,
        "browser_session": True,
        "target_owned": True,
    }
    base.update(over)
    return HandshakeFacts(**base)  # type: ignore[arg-type]


def test_bearer_only_handshake_maps_to_ws_requires_browser_session():
    facts = _ws_facts(browser_session=False)
    assert evaluate_handshake(facts) is HandshakeRejection.REQUIRES_BROWSER_SESSION
    assert evaluate_handshake(facts).value == "ws_requires_browser_session"
    assert close_code_for(HandshakeRejection.REQUIRES_BROWSER_SESSION) == CLOSE_REQUIRES_BROWSER_SESSION


def test_browser_session_check_precedes_origin_and_target():
    facts = _ws_facts(browser_session=False, origin="https://evil.example", target_owned=False)
    assert evaluate_handshake(facts) is HandshakeRejection.REQUIRES_BROWSER_SESSION


def test_unauthenticated_still_takes_precedence():
    facts = _ws_facts(authenticated=False, browser_session=False)
    assert evaluate_handshake(facts) is HandshakeRejection.UNAUTHENTICATED


class _FakeRegistry:
    def __init__(self, owned: bool) -> None:
        self.owned = owned
        self.calls: list[tuple[str, str]] = []

    def owns(self, media_session_id: str, *, session_cookie: str) -> bool:
        self.calls.append((media_session_id, session_cookie))
        return self.owned


def _ws_path(media_session_id: str = "m1") -> str:
    return REALTIME_WS_PATH.replace("{media_session_id}", media_session_id)


def _ws_app(registry: _FakeRegistry) -> FastAPI:
    app = FastAPI()
    app.state.web_sessions = WebSessionStore()
    app.state.realtime_media_sessions = registry
    register_realtime_ws(app)
    return app


def test_ws_bearer_only_rejected_without_querying_ownership(monkeypatch):
    monkeypatch.setenv("WEB_API_KEY", "secret-key")
    registry = _FakeRegistry(owned=True)
    client = TestClient(_ws_app(registry))
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
        _ws_path(),
        headers={"origin": "http://testserver", "authorization": "Bearer secret-key"},
    ):
        pass
    assert registry.calls == []  # 浏览器会话先决失败：不查询归属、不建副作用


def test_ws_without_cookie_rejected(monkeypatch):
    monkeypatch.delenv("WEB_API_KEY", raising=False)
    registry = _FakeRegistry(owned=True)
    client = TestClient(_ws_app(registry))
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
        _ws_path(), headers={"origin": "http://testserver"}
    ):
        pass
    assert registry.calls == []


def test_ws_valid_cookie_with_same_origin_accepted(monkeypatch):
    monkeypatch.delenv("WEB_API_KEY", raising=False)
    registry = _FakeRegistry(owned=True)
    app = _ws_app(registry)
    token = app.state.web_sessions.create(ttl_seconds=60)
    client = TestClient(app)
    with client.websocket_connect(
        _ws_path("mine"),
        headers={"origin": "http://testserver", "cookie": f"{SESSION_COOKIE_NAME}={token}"},
    ) as ws:
        ws.close()
    assert registry.calls == [("mine", token)]


def test_ws_valid_cookie_with_cross_origin_rejected(monkeypatch):
    monkeypatch.delenv("WEB_API_KEY", raising=False)
    registry = _FakeRegistry(owned=True)
    app = _ws_app(registry)
    token = app.state.web_sessions.create(ttl_seconds=60)
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
        _ws_path(),
        headers={"origin": "https://evil.example", "cookie": f"{SESSION_COOKIE_NAME}={token}"},
    ):
        pass
    assert registry.calls == []


def test_ws_prefixed_cookie_name_accepted(monkeypatch):
    """S3-6 联动：__Host- 前缀名 cookie 同样建立浏览器会话并匹配归属。"""
    monkeypatch.delenv("WEB_API_KEY", raising=False)
    registry = _FakeRegistry(owned=True)
    app = _ws_app(registry)
    token = app.state.web_sessions.create(ttl_seconds=60)
    client = TestClient(app)
    with client.websocket_connect(
        _ws_path("mine2"),
        headers={
            "origin": "http://testserver",
            "cookie": f"{SESSION_COOKIE_NAME_SECURE}={token}",
        },
    ) as ws:
        ws.close()
    assert registry.calls == [("mine2", token)]


# ── S3-3 / S3-5：文案一致 + 能力边界声明 ─────────────────────────────────────


def test_login_page_copy_matches_lax_implementation(build_test_engine, fake_settings, monkeypatch):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_LOGIN_PASSWORD_HASH", hash_login_password(_TEST_PASSWORD))
    engine, _ = build_test_engine([])
    client = TestClient(build_app(engine=engine), base_url="http://127.0.0.1:8903")
    page = client.get("/login")
    assert page.status_code == 200
    assert "SameSite=Lax" in page.text
    assert "SameSite=Strict" not in page.text


def test_auth_module_docstring_declares_in_memory_session_boundary():
    assert web_auth.__doc__ is not None
    assert "内存" in web_auth.__doc__
    assert "重启" in web_auth.__doc__

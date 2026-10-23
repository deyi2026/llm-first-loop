"""T-CONTRACT-4：实时会话控制通道 WS 握手鉴权与拒绝路径测试。

覆盖 RTM：SES-02/03/07、SEC-01/06/08、CAP-05、IDN-02。

三类拒绝（未登录 / 跨站 Origin / 越权）与「拒绝后不建立副作用」分别验证：
- 拒绝码由纯函数 `evaluate_handshake` + `close_code_for` 确定性覆盖；
- 端点行为以 TestClient 覆盖：拒绝时连接不可用且归属登记未被建立副作用。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from llm_loop.web.auth import SESSION_COOKIE_NAME, WebSessionStore
from llm_loop.web.realtime_ws import (
    CLOSE_CROSS_SITE_ORIGIN,
    CLOSE_FORBIDDEN_TARGET,
    CLOSE_UNAUTHENTICATED,
    REALTIME_WS_PATH,
    HandshakeFacts,
    HandshakeRejection,
    close_code_for,
    evaluate_handshake,
    register_realtime_ws,
)


def _facts(**over: object) -> HandshakeFacts:
    base: dict[str, object] = {
        "authenticated": True,
        "origin": "https://app.example.com",
        "allowed_origins": frozenset({"https://app.example.com"}),
        "trusted_local": False,
        "target_owned": True,
    }
    base.update(over)
    return HandshakeFacts(**base)  # type: ignore[arg-type]


class TestEvaluateHandshake:
    def test_allow_when_all_checks_pass(self):
        assert evaluate_handshake(_facts()) is HandshakeRejection.ALLOW

    def test_unauthenticated_maps_to_4401(self):
        facts = _facts(authenticated=False)
        assert evaluate_handshake(facts) is HandshakeRejection.UNAUTHENTICATED
        assert close_code_for(evaluate_handshake(facts)) == CLOSE_UNAUTHENTICATED

    def test_identity_takes_precedence_over_origin_and_target(self):
        facts = _facts(authenticated=False, origin="https://evil.example", target_owned=False)
        assert evaluate_handshake(facts) is HandshakeRejection.UNAUTHENTICATED

    def test_cross_site_origin_maps_to_4403(self):
        facts = _facts(origin="https://evil.example")
        assert evaluate_handshake(facts) is HandshakeRejection.CROSS_SITE_ORIGIN
        assert close_code_for(evaluate_handshake(facts)) == CLOSE_CROSS_SITE_ORIGIN

    def test_malformed_origin_is_rejected(self):
        facts = _facts(origin="https://evil.example/path")
        assert evaluate_handshake(facts) is HandshakeRejection.CROSS_SITE_ORIGIN

    def test_missing_origin_rejected_when_not_trusted_local(self):
        facts = _facts(origin="", trusted_local=False)
        assert evaluate_handshake(facts) is HandshakeRejection.CROSS_SITE_ORIGIN

    def test_missing_origin_allowed_when_trusted_local(self):
        facts = _facts(origin="", trusted_local=True)
        assert evaluate_handshake(facts) is HandshakeRejection.ALLOW

    def test_forbidden_target_maps_to_4404(self):
        facts = _facts(target_owned=False)
        assert evaluate_handshake(facts) is HandshakeRejection.FORBIDDEN_TARGET
        assert close_code_for(evaluate_handshake(facts)) == CLOSE_FORBIDDEN_TARGET

    def test_pending_target_when_not_yet_queried(self):
        assert evaluate_handshake(_facts(target_owned=None)) is HandshakeRejection.PENDING_TARGET

    def test_pending_not_reached_when_identity_or_origin_fails(self):
        assert (
            evaluate_handshake(_facts(authenticated=False, target_owned=None))
            is HandshakeRejection.UNAUTHENTICATED
        )
        assert (
            evaluate_handshake(_facts(origin="https://evil.example", target_owned=None))
            is HandshakeRejection.CROSS_SITE_ORIGIN
        )

    def test_allow_close_code_is_normal(self):
        assert close_code_for(HandshakeRejection.ALLOW) == 1000


class _FakeRegistry:
    def __init__(self, owned: bool) -> None:
        self.owned = owned
        self.calls: list[tuple[str, str]] = []

    def owns(self, media_session_id: str, *, session_cookie: str) -> bool:
        self.calls.append((media_session_id, session_cookie))
        return self.owned


def _make_app(registry: object | None) -> tuple[FastAPI, WebSessionStore]:
    app = FastAPI()
    store = WebSessionStore()
    app.state.web_sessions = store
    if registry is not None:
        app.state.realtime_media_sessions = registry
    register_realtime_ws(app)
    return app, store


def _path(media_session_id: str = "m1") -> str:
    return REALTIME_WS_PATH.replace("{media_session_id}", media_session_id)


class TestHandshakeEndpoint:
    def test_unauthenticated_connection_rejected_without_side_effects(self):
        registry = _FakeRegistry(owned=True)
        app, _ = _make_app(registry)
        client = TestClient(app)
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(_path(), headers={"origin": "http://testserver"}),
        ):
            pass
        assert registry.calls == []  # 身份先失败：不查询归属，不建立副作用

    def test_cross_site_origin_rejected(self):
        registry = _FakeRegistry(owned=True)
        app, store = _make_app(registry)
        token = store.create(ttl_seconds=60)
        client = TestClient(app)
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(
            _path(),
            headers={
                "origin": "https://evil.example",
                "cookie": f"{SESSION_COOKIE_NAME}={token}",
            },
        ):
            pass
        assert registry.calls == []  # Origin 先失败：仍不查询归属

    def test_forbidden_target_rejected(self):
        registry = _FakeRegistry(owned=False)
        app, store = _make_app(registry)
        token = store.create(ttl_seconds=60)
        client = TestClient(app)
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(
            _path("foreign-session"),
            headers={
                "origin": "http://testserver",
                "cookie": f"{SESSION_COOKIE_NAME}={token}",
            },
        ):
            pass
        # 归属被核实（防枚举按统一拒绝处理），但连接未建立
        assert registry.calls == [("foreign-session", token)]

    def test_owned_target_with_valid_session_is_accepted(self):
        registry = _FakeRegistry(owned=True)
        app, store = _make_app(registry)
        token = store.create(ttl_seconds=60)
        client = TestClient(app)
        with client.websocket_connect(
            _path("mine"),
            headers={
                "origin": "http://testserver",
                "cookie": f"{SESSION_COOKIE_NAME}={token}",
            },
        ) as ws:
            ws.close()
        assert registry.calls == [("mine", token)]

    def test_missing_registry_rejects_unknown_target(self):
        app, store = _make_app(None)
        token = store.create(ttl_seconds=60)
        client = TestClient(app)
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(
            _path(),
            headers={
                "origin": "http://testserver",
                "cookie": f"{SESSION_COOKIE_NAME}={token}",
            },
        ):
            pass

"""Voice admission must preserve local no-login UX without weakening media ownership."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from llm_loop.realtime.media_registry import MediaSessionRegistry
from llm_loop.web import _OriginGuardMiddleware
from llm_loop.web.auth import SESSION_COOKIE_NAME, WebSessionStore
from llm_loop.web.realtime_routes import router as realtime_router
from llm_loop.web.realtime_ws import register_realtime_ws


class _QuietTransport:
    def next_event(self, *, timeout=None):
        return None

    def close(self):
        pass


def _app() -> FastAPI:
    app = FastAPI()
    app.state.web_sessions = WebSessionStore()
    app.state.realtime_media_sessions = MediaSessionRegistry()
    app.state.realtime_transport_factory = lambda: (_QuietTransport(), "http://127.0.0.1:8000")
    app.include_router(realtime_router)
    register_realtime_ws(app)
    app.add_middleware(_OriginGuardMiddleware)
    return app


def _local_client(app: FastAPI) -> TestClient:
    return TestClient(app, base_url="http://127.0.0.1:8903", client=("127.0.0.1", 20001))


def test_loopback_voice_bootstraps_session_cookie_and_websocket(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    app = _app()
    with _local_client(app) as client:
        result = client.post("/api/v1/realtime/sessions", json={"session_id": "s-local"})
        assert result.status_code == 201
        token = client.cookies.get(SESSION_COOKIE_NAME)
        assert token and app.state.web_sessions.valid(token)
        assert "httponly" in result.headers["set-cookie"].lower()
        assert "samesite=lax" in result.headers["set-cookie"].lower()
        media_id = result.json()["media_session_id"]
        assert app.state.realtime_media_sessions.owns(media_id, session_cookie=token)
        with client.websocket_connect(
            f"ws://127.0.0.1:8903/api/v1/realtime/sessions/{media_id}/events",
            headers={"origin": "http://127.0.0.1:8903"},
        ) as socket:
            socket.close()
        # REST close is idempotent with the WS disconnect cleanup, which can be
        # scheduled just after the test client's context manager returns.
        assert client.delete(f"/api/v1/realtime/sessions/{media_id}").status_code == 200
        assert app.state.realtime_media_sessions.count_active() == 0


def test_stale_browser_cookie_is_replaced_after_web_restart(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    app = _app()
    with _local_client(app) as client:
        client.cookies.set(SESSION_COOKIE_NAME, "old-server-restart-token", domain="127.0.0.1")
        result = client.post("/api/v1/realtime/sessions", json={"session_id": "s-restart"})
        assert result.status_code == 201
        fresh = client.cookies.get(SESSION_COOKIE_NAME)
        assert fresh and fresh != "old-server-restart-token"
        assert app.state.web_sessions.valid(fresh)
        media_id = result.json()["media_session_id"]
        with client.websocket_connect(
            f"ws://127.0.0.1:8903/api/v1/realtime/sessions/{media_id}/events",
            headers={"origin": "http://127.0.0.1:8903"},
        ) as socket:
            socket.close()


def test_remote_anonymous_or_proxy_marked_request_cannot_mint_cookie(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_API_KEY", "configured-in-test-only")
    app = _app()
    with TestClient(app, base_url="https://app.example", client=("198.51.100.5", 20002)) as remote:
        result = remote.post("/api/v1/realtime/sessions", json={"session_id": "s-remote"})
        assert result.status_code == 401
        assert "set-cookie" not in result.headers
    with _local_client(app) as direct:
        result = direct.post(
            "/api/v1/realtime/sessions", json={"session_id": "s-proxied"},
            headers={"x-forwarded-for": "198.51.100.5"},
        )
        assert result.status_code == 401
        assert "set-cookie" not in result.headers
    assert app.state.realtime_media_sessions.count_active() == 0


def test_remote_authenticated_browser_cookie_still_works_without_reissuing(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_API_KEY", "configured-in-test-only")
    app = _app()
    authenticated = app.state.web_sessions.create(ttl_seconds=60)
    with TestClient(app, base_url="https://app.example", client=("198.51.100.5", 20002)) as client:
        client.cookies.set(SESSION_COOKIE_NAME, authenticated, domain="app.example")
        response = client.post("/api/v1/realtime/sessions", json={"session_id": "s-remote-auth"})
        assert response.status_code == 201
        assert "set-cookie" not in response.headers
        media_id = response.json()["media_session_id"]
        assert app.state.realtime_media_sessions.owns(media_id, session_cookie=authenticated)
        with client.websocket_connect(
            f"wss://app.example/api/v1/realtime/sessions/{media_id}/events",
            headers={"origin": "https://app.example"},
        ) as socket:
            socket.close()


def test_remote_stale_cookie_cannot_bypass_login(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_API_KEY", "configured-in-test-only")
    app = _app()
    with TestClient(app, base_url="https://app.example", client=("198.51.100.5", 20002)) as client:
        client.cookies.set(SESSION_COOKIE_NAME, "expired", domain="app.example")
        response = client.post("/api/v1/realtime/sessions", json={"session_id": "s-stale"})
        assert response.status_code == 401
        assert "set-cookie" not in response.headers
    assert app.state.realtime_media_sessions.count_active() == 0


def test_cross_site_origin_cannot_mint_cookie_or_create_media(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    app = _app()
    with _local_client(app) as client:
        response = client.post(
            "/api/v1/realtime/sessions", json={"session_id": "s-forgery"},
            headers={"origin": "https://evil.example"},
        )
        assert response.status_code == 403
        assert "set-cookie" not in response.headers
    assert app.state.realtime_media_sessions.count_active() == 0


def test_two_local_browsers_cannot_read_each_others_media(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    app = _app()
    with _local_client(app) as first, _local_client(app) as second:
        first_response = first.post("/api/v1/realtime/sessions", json={"session_id": "s-one"})
        second_response = second.post("/api/v1/realtime/sessions", json={"session_id": "s-two"})
        assert first_response.status_code == 201 and second_response.status_code == 201
        media_id = first_response.json()["media_session_id"]
        assert second.get(f"/api/v1/realtime/sessions/{media_id}").status_code == 404
        with pytest.raises(WebSocketDisconnect), second.websocket_connect(
            f"ws://127.0.0.1:8903/api/v1/realtime/sessions/{media_id}/events",
            headers={"origin": "http://127.0.0.1:8903"},
        ):
            pass


def test_conflicting_local_writer_does_not_leave_orphan_browser_sessions(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    app = _app()
    with _local_client(app) as first, _local_client(app) as second:
        assert first.post("/api/v1/realtime/sessions", json={"session_id": "s-busy"}).status_code == 201
        before = len(app.state.web_sessions._expires)
        denied = second.post("/api/v1/realtime/sessions", json={"session_id": "s-busy"})
        assert denied.status_code == 409
        assert "set-cookie" not in denied.headers
        assert len(app.state.web_sessions._expires) == before

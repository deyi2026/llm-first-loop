"""M1：实时媒体会话 REST 路由测试（A1/A2/A3）。

覆盖 RTM：SES-01/02/03/06/07、LIF-01/02/03、IDN-03、SEC-06/08。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from llm_loop.realtime.media_registry import MediaSessionRegistry
from llm_loop.web.realtime_routes import router

OWNER = {"authorization": "Bearer tok-1"}
OTHER = {"authorization": "Bearer tok-evil"}


@pytest.fixture(autouse=True)
def _clean_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEB_AUTH_REQUIRE", raising=False)
    monkeypatch.delenv("WEB_ORIGIN_ALLOWLIST", raising=False)
    monkeypatch.setenv("WEB_HOST", "127.0.0.1")


def _client() -> TestClient:
    app = FastAPI()
    app.state.realtime_media_sessions = MediaSessionRegistry()
    app.include_router(router)
    return TestClient(app)


class TestA1Create:
    def test_create_returns_media_session_and_epoch(self):
        client = _client()
        resp = client.post("/api/v1/realtime/sessions", json={"session_id": "sess-1"}, headers=OWNER)
        assert resp.status_code == 201
        body = resp.json()
        assert body["media_session_id"]
        assert body["connection_epoch"] == 1
        assert body["connection_state"] == "opening"
        assert body["capability_profile"]["recovery_mode"] == "local_rebuild_only"

    def test_create_without_identity_is_401(self):
        client = _client()
        resp = client.post("/api/v1/realtime/sessions", json={"session_id": "sess-1"})
        assert resp.status_code == 401

    def test_create_conflict_without_take_over_is_409(self):
        client = _client()
        first = client.post("/api/v1/realtime/sessions", json={"session_id": "sess-1"}, headers=OWNER)
        assert first.status_code == 201
        conflict = client.post("/api/v1/realtime/sessions", json={"session_id": "sess-1"}, headers=OWNER)
        assert conflict.status_code == 409

    def test_create_with_take_over_gets_new_epoch(self):
        client = _client()
        first = client.post("/api/v1/realtime/sessions", json={"session_id": "sess-1"}, headers=OWNER).json()
        second = client.post(
            "/api/v1/realtime/sessions",
            json={"session_id": "sess-1", "take_over": True},
            headers=OWNER,
        ).json()
        assert second["connection_epoch"] == first["connection_epoch"] + 1

    def test_preflight_failure_is_503(self):
        app = FastAPI()
        app.state.realtime_media_sessions = MediaSessionRegistry()
        app.state.realtime_preflight = lambda: False
        app.include_router(router)
        client = TestClient(app)
        resp = client.post("/api/v1/realtime/sessions", json={"session_id": "sess-1"}, headers=OWNER)
        assert resp.status_code == 503


class TestA2Get:
    def test_get_returns_four_facts(self):
        client = _client()
        created = client.post("/api/v1/realtime/sessions", json={"session_id": "sess-1"}, headers=OWNER).json()
        mid = created["media_session_id"]
        resp = client.get(f"/api/v1/realtime/sessions/{mid}", headers=OWNER)
        assert resp.status_code == 200
        body = resp.json()
        assert body["connection_state"] == "opening"
        assert body["mic_enabled"] is False
        assert body["playback_state"] == "idle"
        assert body["task_state"] == "idle"

    def test_get_cross_owner_is_404_enumeration_safe(self):
        client = _client()
        created = client.post("/api/v1/realtime/sessions", json={"session_id": "sess-1"}, headers=OWNER).json()
        mid = created["media_session_id"]
        assert client.get(f"/api/v1/realtime/sessions/{mid}", headers=OTHER).status_code == 404
        assert client.get("/api/v1/realtime/sessions/ms-missing", headers=OWNER).status_code == 404


class TestA3Delete:
    def test_delete_closes_and_reports_incomplete_usage(self):
        client = _client()
        created = client.post("/api/v1/realtime/sessions", json={"session_id": "sess-1"}, headers=OWNER).json()
        mid = created["media_session_id"]
        resp = client.delete(f"/api/v1/realtime/sessions/{mid}", headers=OWNER)
        assert resp.status_code == 200
        body = resp.json()
        assert body["close_state"] == "closed"
        assert body["usage"]["status"] == "incomplete"  # 缺最终用量不标零

    def test_delete_is_idempotent(self):
        client = _client()
        created = client.post("/api/v1/realtime/sessions", json={"session_id": "sess-1"}, headers=OWNER).json()
        mid = created["media_session_id"]
        first = client.delete(f"/api/v1/realtime/sessions/{mid}", headers=OWNER)
        second = client.delete(f"/api/v1/realtime/sessions/{mid}", headers=OWNER)
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["close_state"] == "closed"

    def test_delete_cross_owner_is_404(self):
        client = _client()
        created = client.post("/api/v1/realtime/sessions", json={"session_id": "sess-1"}, headers=OWNER).json()
        mid = created["media_session_id"]
        assert client.delete(f"/api/v1/realtime/sessions/{mid}", headers=OTHER).status_code == 404

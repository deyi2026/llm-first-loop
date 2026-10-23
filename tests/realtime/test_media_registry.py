"""T-CONTRACT-6 / M1：媒体会话登记与归属测试。

覆盖 RTM：SES-01/02/03/06、IDN-02/03、SEC-06/08。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from llm_loop.realtime.media_registry import MediaSessionRegistry
from llm_loop.realtime.media_session import ConnectionState
from llm_loop.web.auth import SESSION_COOKIE_NAME, require_api_key
from llm_loop.web.realtime_routes import router


class TestCreateAndOwn:
    def test_create_binds_owner_and_epoch(self):
        reg = MediaSessionRegistry()
        rec = reg.create(session_id="sess-1", workspace_scope="ws-1", owner_cookie="tok-1")
        assert rec.connection_epoch == 1
        assert rec.session.state is ConnectionState.OPENING
        assert reg.owns(rec.media_session_id, session_cookie="tok-1") is True

    def test_owns_rejects_wrong_cookie(self):
        reg = MediaSessionRegistry()
        rec = reg.create(session_id="sess-1", workspace_scope="ws-1", owner_cookie="tok-1")
        assert reg.owns(rec.media_session_id, session_cookie="tok-2") is False

    def test_owns_rejects_unknown_and_empty(self):
        reg = MediaSessionRegistry()
        assert reg.owns("ms-unknown", session_cookie="tok-1") is False
        assert reg.owns("ms-unknown", session_cookie="") is False

    def test_second_writer_gets_new_epoch(self):
        reg = MediaSessionRegistry()
        first = reg.create(session_id="sess-1", workspace_scope="ws-1", owner_cookie="tok-1")
        second = reg.create(session_id="sess-1", workspace_scope="ws-1", owner_cookie="tok-1", take_over=True)
        assert second.connection_epoch == first.connection_epoch + 1

    def test_closed_writer_reopening_still_increments_epoch(self):
        reg = MediaSessionRegistry()
        first = reg.create(session_id="s1", workspace_scope="ws", owner_cookie="tok")
        reg.close(first.media_session_id, session_cookie="tok")
        second = reg.create(session_id="s1", workspace_scope="ws", owner_cookie="tok")
        assert second.connection_epoch > first.connection_epoch

    def test_active_writer_conflict(self):
        reg = MediaSessionRegistry()
        assert reg.active_writer_conflict("sess-1") is False
        rec = reg.create(session_id="sess-1", workspace_scope="ws-1", owner_cookie="tok-1")
        assert reg.active_writer_conflict("sess-1") is True
        reg.close(rec.media_session_id, session_cookie="tok-1")
        assert reg.active_writer_conflict("sess-1") is False


class TestGetAndClose:
    def test_get_is_enumeration_safe(self):
        reg = MediaSessionRegistry()
        rec = reg.create(session_id="sess-1", workspace_scope="ws-1", owner_cookie="tok-1")
        assert reg.get(rec.media_session_id, session_cookie="tok-1") is not None
        # 越权与未知返回一致的 None（不泄露存在性）
        assert reg.get(rec.media_session_id, session_cookie="tok-evil") is None
        assert reg.get("ms-missing", session_cookie="tok-1") is None

    def test_close_is_idempotent(self):
        reg = MediaSessionRegistry()
        rec = reg.create(session_id="sess-1", workspace_scope="ws-1", owner_cookie="tok-1")
        first = reg.close(rec.media_session_id, session_cookie="tok-1")
        second = reg.close(rec.media_session_id, session_cookie="tok-1")
        assert first is not None and second is not None
        assert first.session.state is ConnectionState.CLOSED
        assert second.session.state is ConnectionState.CLOSED

    def test_close_wrong_owner_returns_none(self):
        reg = MediaSessionRegistry()
        rec = reg.create(session_id="sess-1", workspace_scope="ws-1", owner_cookie="tok-1")
        assert reg.close(rec.media_session_id, session_cookie="tok-2") is None
        assert reg.count_active() == 1

    def test_closed_session_is_not_owned(self):
        reg = MediaSessionRegistry()
        rec = reg.create(session_id="sess-1", workspace_scope="ws-1", owner_cookie="tok-1")
        reg.close(rec.media_session_id, session_cookie="tok-1")
        assert reg.owns(rec.media_session_id, session_cookie="tok-1") is False
        assert reg.count_active() == 0


class TestTakeOver:
    def test_take_over_closes_previous_writer(self):
        reg = MediaSessionRegistry()
        first = reg.create(session_id="s1", workspace_scope="ws", owner_cookie="tok")
        second = reg.create(session_id="s1", workspace_scope="ws", owner_cookie="tok", take_over=True)
        assert second.connection_epoch == first.connection_epoch + 1
        assert first.closed is True  # 旧写入者被显式关闭
        assert first.session.state is ConnectionState.CLOSED
        assert reg.count_active() == 1  # 不并存两个 active writer

    def test_without_take_over_rejects_second_writer_atomically(self):
        reg = MediaSessionRegistry()
        first = reg.create(session_id="s1", workspace_scope="ws", owner_cookie="tok")
        with pytest.raises(ValueError, match="active writer"):
            reg.create(session_id="s1", workspace_scope="ws", owner_cookie="tok")
        assert reg.count_active() == 1
        assert reg.owns(first.media_session_id, session_cookie="tok")

    def test_take_over_cannot_close_a_different_owner_writer(self):
        reg = MediaSessionRegistry()
        first = reg.create(session_id="s1", workspace_scope="ws", owner_cookie="owner-a")
        with pytest.raises(ValueError, match="active writer"):
            reg.create(session_id="s1", workspace_scope="ws", owner_cookie="owner-b", take_over=True)
        assert reg.count_active() == 1
        assert reg.owns(first.media_session_id, session_cookie="owner-a")


def test_rest_writer_admission_conflict_and_takeover():
    app = FastAPI()
    app.state.realtime_media_sessions = MediaSessionRegistry()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: None
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE_NAME, "owner-a")
        first = client.post("/api/v1/realtime/sessions", json={"session_id": "s1"})
        assert first.status_code == 201
        assert client.post("/api/v1/realtime/sessions", json={"session_id": "s1"}).status_code == 409
        client.cookies.set(SESSION_COOKIE_NAME, "owner-b")
        assert client.post(
            "/api/v1/realtime/sessions",
            json={"session_id": "s1", "take_over": True},
        ).status_code == 409
        assert app.state.realtime_media_sessions.count_active() == 1
        client.cookies.set(SESSION_COOKIE_NAME, "owner-a")
        new = client.post("/api/v1/realtime/sessions", json={"session_id": "s1", "take_over": True})
        assert new.status_code == 201
        assert new.json()["connection_epoch"] > first.json()["connection_epoch"]
        assert app.state.realtime_media_sessions.count_active() == 1

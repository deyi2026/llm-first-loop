"""T-CONTRACT-4：实时会话控制通道 WS 握手鉴权与拒绝路径测试。

覆盖 RTM：SES-02/03/07、SEC-01/06/08、CAP-05、IDN-02。

三类拒绝（未登录 / 跨站 Origin / 越权）与「拒绝后不建立副作用」分别验证：
- 拒绝码由纯函数 `evaluate_handshake` + `close_code_for` 确定性覆盖；
- 端点行为以 TestClient 覆盖：拒绝时连接不可用且归属登记未被建立副作用。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from llm_loop.realtime.media_registry import MediaSessionRegistry
from llm_loop.web.auth import SESSION_COOKIE_NAME, WebSessionStore
from llm_loop.web.realtime_ws import (
    CLOSE_CROSS_SITE_ORIGIN,
    CLOSE_FORBIDDEN_TARGET,
    CLOSE_UNAUTHENTICATED,
    REALTIME_WS_PATH,
    HandshakeFacts,
    HandshakeRejection,
    _record_closed,
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


class _ClosableMediaRegistry:
    """带 closed 标志的登记替身：驱动 _serve 收包循环的 take_over 场景。"""

    def __init__(self) -> None:
        self.record = SimpleNamespace(session_id="sess-1", connection_epoch=1, closed=False)
        self._by_id = {"ms-1": self.record}

    def owns(self, media_session_id: str, *, session_cookie: str) -> bool:
        return media_session_id == "ms-1" and bool(session_cookie)


class _ServeTransport:
    """_serve 最小传输替身：只记录 append/synthesize/close（不触网）。"""

    def __init__(self) -> None:
        self.appended: list[bytes] = []
        self.closed = False

    def append(self, frame: bytes) -> None:
        self.appended.append(frame)

    def synthesize(self, text: str) -> bytes:  # noqa: ARG002 - 回 PCM 即可
        return b"PCM"

    def close(self) -> None:
        self.closed = True


class TestClosedRecordGuard:
    """缺陷②回归：take_over 置 closed 后，旧 WS 下一条消息即退出并清理。"""

    def _app_with(self, registry: _ClosableMediaRegistry) -> tuple[FastAPI, WebSessionStore, _ServeTransport]:
        app, store = _make_app(registry)
        transport = _ServeTransport()
        app.state.realtime_transport_factory = lambda: (
            transport,
            "http://127.0.0.1:8000/v1/audio/transcriptions",
        )
        return app, store, transport

    def _headers(self, token: str) -> dict[str, str]:
        return {"origin": "http://testserver", "cookie": f"{SESSION_COOKIE_NAME}={token}"}

    def test_record_closed_reflects_registry_closed_flag(self):
        registry = _ClosableMediaRegistry()
        fake_ws = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(realtime_media_sessions=registry))
        )
        assert _record_closed(fake_ws, "ms-1") is False
        registry.record.closed = True  # take_over：旧记录被置 closed
        assert _record_closed(fake_ws, "ms-1") is True
        assert _record_closed(fake_ws, "ms-2") is False  # 无记录不误杀

    def test_missing_registry_keeps_connection_open(self):
        fake_ws = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        assert _record_closed(fake_ws, "ms-1") is False

    def test_closed_record_next_message_exits_loop_and_cleans_up(self):
        registry = _ClosableMediaRegistry()
        app, store, transport = self._app_with(registry)
        token = store.create(ttl_seconds=60)
        client = TestClient(app)
        with client.websocket_connect(_path("ms-1"), headers=self._headers(token)) as ws:
            registry.record.closed = True  # 新连接 take_over：旧记录被置 closed
            ws.send_bytes(b"\x00\x00" * 8)  # 旧连接仍在说话：下一条消息
            error = json.loads(ws.receive_text())
            assert error["type"] == "error"
            assert error["code"] == 409
            assert error["reason"] == "session_closed"  # 契约 §5 枚举值，非自造
            assert error["media_session_id"] == "ms-1"
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()  # 收包循环已退出：连接随后关闭
        assert transport.appended == []  # closed 后不再 ingest（无双写窗口）
        assert transport.closed is True  # 既有 finally 清理：transport.close 已调用

    def test_open_record_keeps_serving(self):
        # 反例：未 closed 时同一循环继续 ingest/应答（守卫不误伤正常路径）
        registry = _ClosableMediaRegistry()
        app, store, transport = self._app_with(registry)
        token = store.create(ttl_seconds=60)
        client = TestClient(app)
        with client.websocket_connect(_path("ms-1"), headers=self._headers(token)) as ws:
            ws.send_bytes(b"\x00\x00" * 8)
            ws.send_text(json.dumps({"type": "tts.request", "text": "hi", "response_id": "r1"}))
            assert ws.receive_bytes() == b"PCM"  # tts 先下行二进制音频
            playback = json.loads(ws.receive_text())
            assert playback["type"] == "audio.playback"
        assert transport.appended == [b"\x00\x00" * 8]  # 帧在回包前已被正常处理


class TestMainlinePortedSemantics:
    """main 侧 e8a1d0a19 语义移植到候选架构（closed 标志 + 0.25s 轮询）的回归。"""

    def test_revoked_quiet_writer_is_evicted_without_new_messages(self):
        # 撤销（DELETE/take_over 置 closed）必须能驱逐**安静**的旧写入者：
        # 旧连接不发任何新帧，也应在有界轮询内收到 409 session_closed 并被关闭。
        registry = MediaSessionRegistry()
        app, store = _make_app(registry)
        token = store.create(ttl_seconds=60)
        record = registry.create(session_id="sess-1", workspace_scope="ws", owner_cookie=token)

        class QuietTransport:
            def next_event(self, *, timeout=None):
                return None

            def close(self):
                pass

        app.state.realtime_transport_factory = lambda: (QuietTransport(), "http://127.0.0.1:8000")
        client = TestClient(app)
        with client.websocket_connect(
            _path(record.media_session_id),
            headers={
                "origin": "http://testserver",
                "cookie": f"{SESSION_COOKIE_NAME}={token}",
            },
        ) as ws:
            closed = registry.close(record.media_session_id, session_cookie=token)  # 等价 DELETE
            assert closed is not None
            error = json.loads(ws.receive_text())  # 无需新消息：轮询即送达
            assert error["type"] == "error"
            assert error["code"] == 409
            assert error["reason"] == "session_closed"
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()
        assert registry.count_active() == 0

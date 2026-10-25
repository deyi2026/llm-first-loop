"""P2-2 回归：实时会话结束必须关闭 transport 自有的 httpx 客户端（且恰好一次）。

- 所有权：transport 只关闭**自己创建**的客户端（``owns_http_client=True``）；
  调用方注入的客户端不归 transport 管，close 后 close 调用次数为 0；
- 幂等：重复 close 不抛、不重复关（兼容 asyncio cancel / double-close）；
- 退出路径：正常 close、连接/握手抛异常后 close、WS 会话断开（_serve finally）。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from llm_loop.realtime.local_voice_stack_transport import LocalVoiceStackTransport
from llm_loop.realtime.realtime_session_runtime import RealtimeSessionRuntime
from llm_loop.web.auth import SESSION_COOKIE_NAME, WebSessionStore
from llm_loop.web.realtime_ws import REALTIME_WS_PATH, register_realtime_ws


class CloseCountingHttp:
    """记录 close 调用次数的 httpx.Client 最小替身（协议 duck-typed）。"""

    def __init__(self) -> None:
        self.close_calls = 0

    def post(self, url: str, **kwargs: object) -> object:  # noqa: ARG002 - 仅满足形状
        return None

    def get(self, url: str) -> object:  # noqa: ARG002 - 仅满足形状
        return None

    def close(self) -> None:
        self.close_calls += 1


class FakeWs:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False
        self.fail_on_send = False

    def send(self, data: bytes | str) -> None:
        if self.fail_on_send:
            raise ConnectionError("ws closed during handshake")
        self.sent.append(data if isinstance(data, str) else data.decode("utf-8", "ignore"))

    def recv(self, timeout: float | None = None) -> str:
        raise TimeoutError("no message")

    def close(self) -> None:
        self.closed = True


class FakeConnector:
    def __init__(self, conn: FakeWs) -> None:
        self.conn = conn
        self.urls: list[str] = []
        self.fail = False

    def __call__(self, url: str) -> FakeWs:
        if self.fail:
            raise ConnectionError("refused")
        self.urls.append(url)
        return self.conn


class TestOwnedClientClosedExactlyOnce:
    def test_close_closes_owned_client_once_and_is_idempotent(self):
        http = CloseCountingHttp()
        ws = FakeWs()
        transport = LocalVoiceStackTransport(
            http_client=http, ws_connector=FakeConnector(ws), owns_http_client=True
        )
        transport.connect("ws://127.0.0.1:8000/v1/realtime")
        transport.close()
        transport.close()  # 重复 close：不抛、不重复关
        assert http.close_calls == 1
        assert ws.closed is True

    def test_owned_client_closed_even_without_ws_connect(self):
        # 工厂降级路径：流式 WS 未建立（connect 抛错被吞）不影响 HTTP 终稿；
        # 会话结束 close 仍须关闭自有客户端。
        http = CloseCountingHttp()
        transport = LocalVoiceStackTransport(
            http_client=http, ws_connector=FakeConnector(FakeWs()), owns_http_client=True
        )
        transport.close()
        assert http.close_calls == 1


class TestConnectFailureStillClosesOwnedClient:
    def test_connect_refused_then_close_closes_owned_client(self):
        http = CloseCountingHttp()
        connector = FakeConnector(FakeWs())
        connector.fail = True
        transport = LocalVoiceStackTransport(
            http_client=http, ws_connector=connector, owns_http_client=True
        )
        with pytest.raises(ConnectionError):
            transport.connect("ws://127.0.0.1:8000/v1/realtime")
        transport.close()
        transport.close()
        assert http.close_calls == 1

    def test_handshake_send_failure_then_close_closes_ws_and_owned_client(self):
        http = CloseCountingHttp()
        ws = FakeWs()
        ws.fail_on_send = True  # 握手后 session.update 发送失败
        transport = LocalVoiceStackTransport(
            http_client=http, ws_connector=FakeConnector(ws), owns_http_client=True
        )
        with pytest.raises(ConnectionError):
            transport.connect("ws://127.0.0.1:8000/v1/realtime")
        transport.close()
        assert http.close_calls == 1
        assert ws.closed is True  # 半开连接也须收口


class TestInjectedClientNotClosedByTransport:
    def test_injected_client_close_calls_stay_zero(self):
        http = CloseCountingHttp()
        ws = FakeWs()
        transport = LocalVoiceStackTransport(http_client=http, ws_connector=FakeConnector(ws))
        transport.connect("ws://127.0.0.1:8000/v1/realtime")
        transport.close()
        transport.close()
        assert http.close_calls == 0  # 所有权在调用方：transport 不得代关
        assert ws.closed is True


class _OwnedRegistry:
    def owns(self, media_session_id: str, *, session_cookie: str) -> bool:
        return bool(session_cookie)


class TestWsSessionEndClosesOwnedClient:
    def test_runtime_setup_failure_closes_transport_and_ws_1011(self, monkeypatch):
        # P2-2 空窗回归：factory() 成功后、收包 try/finally 接管前，runtime
        # 构造抛错 → transport（自有 httpx client）必须被兜底关闭且 WS 以
        # 1011 收口（旧行为：两者都不关，连接池每会话泄漏）。
        import llm_loop.realtime.realtime_session_runtime as rt_mod

        def boom(*args: object, **kwargs: object) -> RealtimeSessionRuntime:
            raise RuntimeError("runtime construction boom")

        monkeypatch.setattr(rt_mod, "RealtimeSessionRuntime", boom)
        app = FastAPI()
        store = WebSessionStore()
        app.state.web_sessions = store
        app.state.realtime_media_sessions = _OwnedRegistry()
        http = CloseCountingHttp()
        transport = LocalVoiceStackTransport(
            http_client=http, ws_connector=FakeConnector(FakeWs()), owns_http_client=True
        )
        app.state.realtime_transport_factory = lambda: (
            transport,
            "http://127.0.0.1:8000/v1/audio/transcriptions",
        )
        register_realtime_ws(app)
        token = store.create(ttl_seconds=60)
        client = TestClient(app)
        with client.websocket_connect(
            REALTIME_WS_PATH.replace("{media_session_id}", "ms-1"),
            headers={"origin": "http://testserver", "cookie": f"{SESSION_COOKIE_NAME}={token}"},
        ) as ws, pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_text()
        assert excinfo.value.code == 1011  # 明确失败，不伪装可用
        assert http.close_calls == 1  # 兜底路径：自有 httpx client 恰好关闭一次

    def test_disconnect_closes_transport_owned_client_via_serve_finally(self):
        app = FastAPI()
        store = WebSessionStore()
        app.state.web_sessions = store
        app.state.realtime_media_sessions = _OwnedRegistry()
        http = CloseCountingHttp()
        transport = LocalVoiceStackTransport(
            http_client=http, ws_connector=FakeConnector(FakeWs()), owns_http_client=True
        )
        app.state.realtime_transport_factory = lambda: (
            transport,
            "http://127.0.0.1:8000/v1/audio/transcriptions",
        )
        register_realtime_ws(app)
        token = store.create(ttl_seconds=60)
        client = TestClient(app)
        with client.websocket_connect(
            REALTIME_WS_PATH.replace("{media_session_id}", "ms-1"),
            headers={"origin": "http://testserver", "cookie": f"{SESSION_COOKIE_NAME}={token}"},
        ) as ws:
            ws.close()  # 客户端断开 = 正常会话结束
        assert http.close_calls == 1  # _serve finally → transport.close()：恰好一次

"""EVO-20260918-753b4a91: CDP websocket frame limit + same-target reconnect.

Library default max_size=1MiB made large DOM+AX pages fail with CDP close code
1009 (message too big) and left a dead websocket pinned forever, freezing the
browser session. These tests pin the fix surface:

1. configurable max frame bytes reach websocket_connect via max_size;
2. invalid max_frame_bytes is rejected;
3. a dropped connection frees the session so the next call reconnects to the
   SAME pinned target (no silent rebind);
4. the mutation actuator mirrors the same reconnect contract.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from websockets.exceptions import ConnectionClosedError

from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator
from llm_loop.browser.cdp_host import (
    DEFAULT_CDP_MAX_FRAME_BYTES,
    CdpReadOnlyBrowserHost,
    _default_ws_connect,
)

_WS_URL = "ws://127.0.0.1:9222/devtools/page/TARGET-1"


def _target() -> dict[str, Any]:
    return {
        "id": "TARGET-1",
        "type": "page",
        "url": "http://127.0.0.1:8903/",
        "webSocketDebuggerUrl": _WS_URL,
    }


class _DeadRecvWs:
    """Websocket whose recv always raises ConnectionClosed (dead socket)."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False

    def send(self, payload: str | bytes) -> None:
        self.sent.append(payload if isinstance(payload, str) else payload.decode())

    def recv(self, timeout: float | None = None) -> str:
        raise ConnectionClosedError(None, None)

    def close(self) -> None:
        self.closed = True


def test_default_ws_connect_passes_configurable_max_size(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_connect(url: str, **kwargs: Any) -> object:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    import llm_loop.browser.cdp_host as cdp_host

    monkeypatch.setattr(cdp_host, "websocket_connect", fake_connect)
    cdp_host._default_ws_connect(_WS_URL, max_frame_bytes=12345)
    assert captured["url"] == _WS_URL
    assert captured["kwargs"] == {"open_timeout": 5.0, "max_size": 12345}
    cdp_host._default_ws_connect(_WS_URL)
    assert captured["kwargs"] == {"open_timeout": 5.0, "max_size": DEFAULT_CDP_MAX_FRAME_BYTES}


def test_host_rejects_non_positive_max_frame_bytes() -> None:
    with pytest.raises(ValueError):
        CdpReadOnlyBrowserHost(
            "http://127.0.0.1:9222",
            max_frame_bytes=0,
            http_get_json=lambda url: [_target()],
            ws_connect=lambda url: _DeadRecvWs(),
        )
    with pytest.raises(ValueError):
        CdpBrowserMutationActuator(
            "http://127.0.0.1:9222",
            max_frame_bytes=-1,
            http_get_json=lambda url: [_target()],
            ws_connect=lambda url: _DeadRecvWs(),
        )


def test_capture_drops_dead_session_and_reconnects_same_target() -> None:
    sockets: list[_DeadRecvWs] = []
    host = CdpReadOnlyBrowserHost(
        "http://127.0.0.1:9222",
        http_get_json=lambda url: [_target()],
        ws_connect=lambda url: sockets.append(_DeadRecvWs()) or sockets[-1],
    )

    with pytest.raises(RuntimeError, match="connection lost; dropped session"):
        host.capture()
    assert len(sockets) == 1
    assert sockets[0].closed is True
    assert host.bound_target_id == "TARGET-1"

    # The dead socket is gone: the next capture opens a fresh connection to the
    # same pinned target instead of failing forever on the dead one.
    with pytest.raises(RuntimeError, match="connection lost; dropped session"):
        host.capture()
    assert len(sockets) == 2
    assert sockets[1] is not sockets[0]
    assert host.bound_target_id == "TARGET-1"


def test_actuator_dispatch_drops_dead_session_and_reconnects_same_target() -> None:
    sockets: list[_DeadRecvWs] = []
    actuator = CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        http_get_json=lambda url: [_target()],
        ws_connect=lambda url: sockets.append(_DeadRecvWs()) or sockets[-1],
    )

    with pytest.raises(RuntimeError, match="mutation connection lost"):
        actuator.dispatch(verb="navigate", physical_target=None, args={"url": "http://127.0.0.1:8903/"})
    assert len(sockets) == 1
    assert actuator.bound_target_id == "TARGET-1"

    with pytest.raises(RuntimeError, match="mutation connection lost"):
        actuator.dispatch(verb="navigate", physical_target=None, args={"url": "http://127.0.0.1:8903/"})
    assert len(sockets) == 2
    assert actuator.bound_target_id == "TARGET-1"


def test_settings_default_frame_limit_is_64mib() -> None:
    import dataclasses

    from llm_loop.config import Settings

    field = {f.name: f for f in dataclasses.fields(Settings)}["browser_cdp_max_frame_bytes"]
    assert field.default == 67_108_864

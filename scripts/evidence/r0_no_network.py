"""Pytest plugin used by the offline Evidence R0 gate to make provider access impossible."""

from __future__ import annotations

import socket
from typing import Any

_ORIGINAL_CONNECT = socket.socket.connect
_ORIGINAL_CONNECT_EX = socket.socket.connect_ex


def _is_unix(sock: socket.socket) -> bool:
    return sock.family == socket.AF_UNIX


def _blocked_connect(sock: socket.socket, address: Any) -> Any:
    if _is_unix(sock):
        return _ORIGINAL_CONNECT(sock, address)
    raise AssertionError(f"Evidence R0 forbids network/provider access: {address!r}")


def _blocked_connect_ex(sock: socket.socket, address: Any) -> int:
    if _is_unix(sock):
        return _ORIGINAL_CONNECT_EX(sock, address)
    raise AssertionError(f"Evidence R0 forbids network/provider access: {address!r}")


def pytest_configure(config: Any) -> None:
    del config
    socket.socket.connect = _blocked_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _blocked_connect_ex  # type: ignore[method-assign]

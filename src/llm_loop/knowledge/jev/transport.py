"""EVO-20261015 (P1a): Jev 传输面——仅 Protocol + 本地 Mock。

DESIGN-20261014-jev §11 P1a 验收：零真实外发。本包不存在任何网络实现；
真实传输属 P1b（另授权）范围，未获授权不得在此添加 HTTP 客户端。
MockJevTransport 可注入：脚本化响应序列、延迟（模拟超时）、异常、malformed 载荷。
"""

from __future__ import annotations

import time
from typing import Any, Protocol

TRANSPORT_OK = "ok"
TRANSPORT_TIMEOUT = "timeout"
TRANSPORT_ERROR = "transport_error"


class JevTransportError(Exception):
    """传输失败（含模拟超时）。kind ∈ transport|timeout；无自动重试。"""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


class JevTransport(Protocol):
    """物理尝试的唯一接口：一次 send = 一次物理尝试，无内建重试。"""

    def send(self, request: dict[str, Any], *, deadline_s: float) -> dict[str, Any]: ...


class MockJevTransport:
    """本地脚本化传输：零网络。latency_s > deadline_s 时模拟 timeout。"""

    def __init__(
        self,
        *,
        script: list[Any] | None = None,
        default_response: dict[str, Any] | None = None,
        latency_s: float = 0.0,
    ) -> None:
        self._script = list(script or [])
        self._default_response = default_response
        self.latency_s = float(latency_s)
        self.attempts: list[dict[str, Any]] = []

    def send(self, request: dict[str, Any], *, deadline_s: float) -> dict[str, Any]:
        started = time.monotonic()
        self.attempts.append(
            {
                "request": request,
                "deadline_s": float(deadline_s),
                "started_at": started,
            }
        )
        if self.latency_s > float(deadline_s):
            raise JevTransportError(
                "timeout",
                f"mock latency {self.latency_s}s > deadline {deadline_s}s",
            )
        if self._script:
            item = self._script.pop(0)
        elif self._default_response is not None:
            item = self._default_response
        else:
            raise JevTransportError("transport_error", "mock script exhausted")
        if isinstance(item, Exception):
            raise item
        if not isinstance(item, dict):
            raise JevTransportError("transport_error", "mock item is not an object")
        return item

    def attempt_count(self) -> int:
        return len(self.attempts)

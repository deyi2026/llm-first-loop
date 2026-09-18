"""Persistent, read-only CDP host for SMC Browser perception.

The host binds one exact loopback Chrome page target and exposes only the four
mechanical observation methods consumed by ``PlaywrightPageCaptureBackend``.  It
never navigates, dispatches input, evaluates model/user supplied JavaScript, or
silently rebinds to a different tab when the selected target disappears.  One
fixed internal ``document.readyState`` probe is allowed as a mechanical sensor
fact; callers cannot use the generic CDP surface to evaluate arbitrary script.

Despite the backend class name, no Playwright Python dependency is required here:
small page/context shims present the same ``new_cdp_session`` shape to the existing
DOM+AX parser.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import httpx
from websockets.exceptions import ConnectionClosed as _WsConnectionClosed
from websockets.sync.client import connect as websocket_connect

from llm_loop.browser.perception import PlaywrightPageCaptureBackend

# EVO-20260918-753b4a91: websockets 默认 max_size=1MiB；DOM+AX 大页（如 GitHub 仓库页）
# 的 CDP 响应帧超限即 1009 断连且死连接永不重建，会话困死。帧上限参数化 + 同 target 断线重建。
DEFAULT_CDP_MAX_FRAME_BYTES = 67_108_864
_CONNECTION_LOST_ERRORS: tuple[type[BaseException], ...] = (
    ConnectionError,
    EOFError,
    OSError,
    _WsConnectionClosed,
)


def _classify_connection_loss(exc: BaseException) -> str:
    """EVO-20260918-a2727fb2: classify a connection-lost failure for callers.

    timeout       - the fixed recv timeout expired before any complete frame
                    (websockets sync recv raises TimeoutError, an OSError subclass).
    frame_too_large - the peer closed with close code 1009 (message too big),
                    i.e. the response frame exceeded the configured limit.
    connection    - transport-level loss that is neither of the above.
    """

    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, _WsConnectionClosed) and "1009" in str(exc):
        return "frame_too_large"
    return "connection"

_READ_ONLY_CDP_METHODS = frozenset(
    {
        "Target.getTargetInfo",
        "Page.getFrameTree",
        "DOMSnapshot.captureSnapshot",
        "Accessibility.getFullAXTree",
        # EVO-20260918-f2310800 vision phase 1: fixed-parameter screenshot as an
        # evidence-layer observation only; the PNG never feeds grounding/version.
        "Page.captureScreenshot",
    }
)
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_DOCUMENT_READY_STATE_PARAMS: dict[str, Any] = {
    "expression": "document.readyState",
    "returnByValue": True,
    "awaitPromise": False,
    "userGesture": False,
    "throwOnSideEffect": True,
}


class _WebSocketLike(Protocol):
    def send(self, payload: str) -> None: ...

    def recv(self, timeout: float | None = None) -> str | bytes: ...

    def close(self) -> None: ...


def _normalize_loopback_debug_url(value: str) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme != "http" or parsed.hostname not in _LOOPBACK_HOSTS or parsed.port is None:
        raise ValueError("Browser CDP debug URL must be loopback http://host:port")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Browser CDP debug URL must not contain credentials/query/fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("Browser CDP debug URL must point to the debugger origin, not a path")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"http://{host}:{parsed.port}"


def _validate_loopback_ws_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme != "ws" or parsed.hostname not in _LOOPBACK_HOSTS or parsed.port is None:
        raise RuntimeError("Browser target websocket must remain loopback ws://host:port")
    if parsed.username or parsed.password:
        raise RuntimeError("Browser target websocket must not contain credentials")
    return parsed.geturl()


def _default_http_get_json(url: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=3.0, trust_env=False, follow_redirects=False) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("Chrome /json/list did not return a list")
    return [item for item in payload if isinstance(item, dict)]


def _default_ws_connect(url: str, *, max_frame_bytes: int = DEFAULT_CDP_MAX_FRAME_BYTES) -> _WebSocketLike:
    return cast(
        _WebSocketLike,
        websocket_connect(url, open_timeout=5.0, max_size=max(1, int(max_frame_bytes))),
    )


class _ReadOnlyCdpSession:
    """One persistent page-target websocket with a hard method allowlist."""

    def __init__(self, websocket: _WebSocketLike, *, timeout_s: float = 5.0) -> None:
        self._websocket = websocket
        self._timeout_s = float(timeout_s)
        self._request_id = 0
        self._lock = threading.Lock()
        # EVO-20260918-a2727fb2: last request diagnostics so connection-lost
        # failures can be classified (timeout vs frame limit vs transport) instead
        # of surfacing as one undistinguishable error string.
        self.last_diag: dict[str, Any] = {}

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            started = time.monotonic()
            self._request_id += 1
            request_id = self._request_id
            self._websocket.send(
                json.dumps(
                    {"id": request_id, "method": method, "params": params or {}},
                    separators=(",", ":"),
                )
            )
            while True:
                raw = self._websocket.recv(timeout=self._timeout_s)
                message = json.loads(raw)
                if not isinstance(message, dict) or message.get("id") != request_id:
                    continue
                self.last_diag = {
                    "method": method,
                    "resp_chars": len(raw) if isinstance(raw, str) else len(str(raw)),
                    "elapsed_ms": round((time.monotonic() - started) * 1000.0, 1),
                }
                if "error" in message:
                    error = message.get("error") or {}
                    raise RuntimeError(
                        "CDP observation failed: "
                        f"code={error.get('code')}; message={error.get('message')}"
                    )
                result = message.get("result")
                if not isinstance(result, dict):
                    raise RuntimeError("CDP observation response missing object result")
                return result

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if method not in _READ_ONLY_CDP_METHODS:
            raise PermissionError(f"CDP method is not in read-only perception surface: {method}")
        return self._request(method, params)

    def read_document_ready_state(self) -> str:
        """Read one fixed DOM readiness fact without exposing script evaluation."""

        result = self._request("Runtime.evaluate", dict(_DOCUMENT_READY_STATE_PARAMS))
        remote = result.get("result") or {}
        value = remote.get("value") if isinstance(remote, dict) else None
        if value not in {"loading", "interactive", "complete"}:
            raise RuntimeError("Browser document.readyState observation returned invalid value")
        return str(value)


class _CdpContextShim:
    def __init__(self, session: _ReadOnlyCdpSession) -> None:
        self._session = session

    def new_cdp_session(self, page: Any) -> _ReadOnlyCdpSession:  # noqa: ARG002
        return self._session


class _CdpPageShim:
    def __init__(self, *, url: str, session: _ReadOnlyCdpSession) -> None:
        self.url = url
        self.context = _CdpContextShim(session)


class CdpReadOnlyBrowserHost:
    """Bind one exact loopback Chrome page target for persistent read-only capture."""

    def __init__(
        self,
        debug_base_url: str,
        *,
        target_id: str = "",
        node_cap: int = 20_000,
        max_frame_bytes: int = DEFAULT_CDP_MAX_FRAME_BYTES,
        http_get_json: Callable[[str], list[dict[str, Any]]] | None = None,
        ws_connect: Callable[[str], _WebSocketLike] | None = None,
    ) -> None:
        if node_cap < 1:
            raise ValueError("node_cap must be >= 1")
        if max_frame_bytes < 1:
            raise ValueError("max_frame_bytes must be >= 1")
        self.debug_base_url = _normalize_loopback_debug_url(debug_base_url)
        self._configured_target_id = str(target_id or "").strip()
        self._bound_target_id = ""
        self._bound_websocket_url = ""
        self._node_cap = int(node_cap)
        self._http_get_json = http_get_json or _default_http_get_json
        self._max_frame_bytes = int(max_frame_bytes)
        self._ws_connect: Callable[[str], _WebSocketLike] = ws_connect or (
            lambda url: _default_ws_connect(url, max_frame_bytes=self._max_frame_bytes)
        )
        self._websocket: _WebSocketLike | None = None
        self._session: _ReadOnlyCdpSession | None = None
        self._capture_lock = threading.Lock()

    @property
    def bound_target_id(self) -> str:
        return self._bound_target_id

    def _page_targets(self) -> list[dict[str, Any]]:
        targets = self._http_get_json(f"{self.debug_base_url}/json/list")
        return [item for item in targets if str(item.get("type") or "") == "page"]

    def _resolve_target(self) -> dict[str, Any]:
        pages = self._page_targets()
        expected = self._bound_target_id or self._configured_target_id
        if expected:
            for page in pages:
                if str(page.get("id") or "") == expected:
                    return page
            if self._bound_target_id:
                raise RuntimeError(
                    f"bound Browser target disappeared: {self._bound_target_id}; no silent rebind"
                )
            raise RuntimeError(f"configured Browser target not found: {expected}")
        if len(pages) != 1:
            raise RuntimeError(
                "Browser CDP endpoint must expose exactly one page when target_id is omitted; "
                f"observed={len(pages)}"
            )
        return pages[0]

    def _ensure_session(self, target: dict[str, Any]) -> _ReadOnlyCdpSession:
        target_id = str(target.get("id") or "").strip()
        if not target_id:
            raise RuntimeError("Browser target missing exact target id")
        websocket_url = _validate_loopback_ws_url(str(target.get("webSocketDebuggerUrl") or ""))
        if not self._bound_target_id:
            self._bound_target_id = target_id
            self._bound_websocket_url = websocket_url
        elif target_id != self._bound_target_id:
            raise RuntimeError("Browser target identity changed; no silent rebind")
        elif websocket_url != self._bound_websocket_url:
            raise RuntimeError("bound Browser target websocket changed; recreate host explicitly")
        if self._session is None:
            websocket = self._ws_connect(websocket_url)
            self._websocket = websocket
            self._session = _ReadOnlyCdpSession(websocket)
        return self._session

    def _drop_session(self) -> None:
        # EVO-20260918-753b4a91: same-target reconnect only — bound target identity
        # stays pinned; dropping a dead websocket never grants access to another tab.
        websocket = self._websocket
        self._session = None
        self._websocket = None
        if websocket is not None:
            with contextlib.suppress(Exception):  # noqa: BLE001 - best-effort close of a dead socket
                websocket.close()

    def capture(self) -> dict[str, Any]:
        with self._capture_lock:
            target = self._resolve_target()
            session = self._ensure_session(target)
            page = _CdpPageShim(url=str(target.get("url") or ""), session=session)
            try:
                return PlaywrightPageCaptureBackend(page, node_cap=self._node_cap).capture()
            except _CONNECTION_LOST_ERRORS as exc:
                diag = dict(getattr(session, "last_diag", {}) or {})
                mode = _classify_connection_loss(exc)
                self._drop_session()
                raise RuntimeError(
                    f"capture_channel_degraded[mode={mode}]; "
                    "CDP observation connection lost; dropped session for same-target reconnect"
                    f"; diag={diag}; error_type={type(exc).__name__}"
                ) from exc

    def probe_page_target(self) -> dict[str, Any]:
        """EVO-20260918-4766011b: lightweight page-target existence probe.

        Uses only the already-allowlisted read-only CDP surface
        (Target.getTargetInfo) - no DOM/AX capture - so resource-level
        transition verbs can verify their precondition when a full capture
        is structurally unavailable on the current page.
        """

        with self._capture_lock:
            target = self._resolve_target()
            target_id = str(target.get("id") or "")
            session = self._ensure_session(target)
            info = session.send("Target.getTargetInfo", {"targetId": target_id})
            target_info = info.get("targetInfo") if isinstance(info, dict) else None
            probed_id = str((target_info or {}).get("targetId") or "") or target_id
            if probed_id != target_id:
                raise RuntimeError("Browser target probe returned a different target id")
            return {
                "target_id": target_id,
                "url": str(target.get("url") or ""),
                "type": str(target.get("type") or ""),
            }

    def capture_vision_evidence(self) -> bytes:
        """EVO-20260918-f2310800: fixed-parameter screenshot of the bound page.

        PNG bytes only - an evidence-layer observation. Callers persist and
        reference it; it never feeds objects/grounding/version paths.
        """

        import base64

        with self._capture_lock:
            target = self._resolve_target()
            session = self._ensure_session(target)
            result = session.send(
                "Page.captureScreenshot",
                {"format": "png", "fromSurface": True},
            )
            data = result.get("data") if isinstance(result, dict) else None
            if not isinstance(data, str) or not data:
                raise RuntimeError("Page.captureScreenshot returned no image data")
            return base64.b64decode(data)

    def close(self) -> None:
        websocket = self._websocket
        self._session = None
        self._websocket = None
        if websocket is not None:
            websocket.close()

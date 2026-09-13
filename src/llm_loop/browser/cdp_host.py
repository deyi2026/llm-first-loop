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

import json
import threading
from collections.abc import Callable
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import httpx
from websockets.sync.client import connect as websocket_connect

from llm_loop.browser.perception import PlaywrightPageCaptureBackend

_READ_ONLY_CDP_METHODS = frozenset(
    {
        "Target.getTargetInfo",
        "Page.getFrameTree",
        "DOMSnapshot.captureSnapshot",
        "Accessibility.getFullAXTree",
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


def _default_ws_connect(url: str) -> _WebSocketLike:
    return cast(_WebSocketLike, websocket_connect(url, open_timeout=5.0))


class _ReadOnlyCdpSession:
    """One persistent page-target websocket with a hard method allowlist."""

    def __init__(self, websocket: _WebSocketLike, *, timeout_s: float = 5.0) -> None:
        self._websocket = websocket
        self._timeout_s = float(timeout_s)
        self._request_id = 0
        self._lock = threading.Lock()

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
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
        http_get_json: Callable[[str], list[dict[str, Any]]] | None = None,
        ws_connect: Callable[[str], _WebSocketLike] | None = None,
    ) -> None:
        if node_cap < 1:
            raise ValueError("node_cap must be >= 1")
        self.debug_base_url = _normalize_loopback_debug_url(debug_base_url)
        self._configured_target_id = str(target_id or "").strip()
        self._bound_target_id = ""
        self._bound_websocket_url = ""
        self._node_cap = int(node_cap)
        self._http_get_json = http_get_json or _default_http_get_json
        self._ws_connect: Callable[[str], _WebSocketLike] = ws_connect or _default_ws_connect
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

    def capture(self) -> dict[str, Any]:
        with self._capture_lock:
            target = self._resolve_target()
            session = self._ensure_session(target)
            page = _CdpPageShim(url=str(target.get("url") or ""), session=session)
            return PlaywrightPageCaptureBackend(page, node_cap=self._node_cap).capture()

    def close(self) -> None:
        websocket = self._websocket
        self._session = None
        self._websocket = None
        if websocket is not None:
            websocket.close()

"""Narrow CDP mutation actuator for SMC Browser Phase 1.

The model never supplies CDP methods, JavaScript, selectors, coordinates, or backend
node ids.  This host binds one exact loopback page and maps five frozen semantic verbs
to fixed internal CDP sequences.  It performs no retry and never silently rebinds.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any, Protocol, cast

from websockets.sync.client import connect as websocket_connect

from llm_loop.browser.action import BrowserDispatchResult
from llm_loop.browser.cdp_host import (
    DEFAULT_CDP_MAX_FRAME_BYTES,
    _CONNECTION_LOST_ERRORS,
    _default_http_get_json,
    _normalize_loopback_debug_url,
    _validate_loopback_ws_url,
)

_ALLOWED = frozenset({"DOM.resolveNode", "Runtime.callFunctionOn", "Page.enable", "Page.navigate"})

_BOUNDARY_EVENT_METHODS = {
    "Page.windowOpen": "new_window",
    "Page.downloadWillBegin": "download_started",
    "Page.javascriptDialogOpening": "dialog_opened",
}


class _WebSocketLike(Protocol):
    def send(self, payload: str) -> None: ...
    def recv(self, timeout: float | None = None) -> str | bytes: ...
    def close(self) -> None: ...


def _default_ws_connect(url: str, *, max_frame_bytes: int = DEFAULT_CDP_MAX_FRAME_BYTES) -> _WebSocketLike:
    return cast(
        _WebSocketLike,
        websocket_connect(url, open_timeout=5.0, max_size=max(1, int(max_frame_bytes))),
    )


class _MutationCdpSession:
    def __init__(self, websocket: _WebSocketLike, *, timeout_s: float = 5.0) -> None:
        self._websocket = websocket
        self._timeout_s = float(timeout_s)
        self._request_id = 0
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if method not in _ALLOWED:
            raise PermissionError(f"CDP method is not in Browser mutation actuator surface: {method}")
        with self._lock:
            self._request_id += 1
            request_id = self._request_id
            self._websocket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}, separators=(",", ":")))
            while True:
                raw = self._websocket.recv(timeout=self._timeout_s)
                message = json.loads(raw)
                if not isinstance(message, dict):
                    continue
                if message.get("id") != request_id:
                    if isinstance(message.get("method"), str):
                        self._events.append(message)
                    continue
                if "error" in message:
                    error = message.get("error") or {}
                    raise RuntimeError(
                        "CDP mutation failed: "
                        f"code={error.get('code')}; message={error.get('message')}"
                    )
                result = message.get("result")
                if not isinstance(result, dict):
                    raise RuntimeError("CDP mutation response missing object result")
                return result

    def pop_events(self) -> list[dict[str, Any]]:
        events = list(self._events)
        self._events.clear()
        return events


class CdpBrowserMutationActuator:
    """Exact-target, single-dispatch Browser mutation actuator."""

    def __init__(
        self,
        debug_base_url: str,
        *,
        target_id: str = "",
        max_frame_bytes: int = DEFAULT_CDP_MAX_FRAME_BYTES,
        http_get_json: Callable[[str], list[dict[str, Any]]] | None = None,
        ws_connect: Callable[[str], _WebSocketLike] | None = None,
    ) -> None:
        if max_frame_bytes < 1:
            raise ValueError("max_frame_bytes must be >= 1")
        self.debug_base_url = _normalize_loopback_debug_url(debug_base_url)
        self._configured_target_id = str(target_id or "").strip()
        self._bound_target_id = ""
        self._bound_websocket_url = ""
        self._http_get_json = http_get_json or _default_http_get_json
        self._max_frame_bytes = int(max_frame_bytes)
        self._ws_connect: Callable[[str], _WebSocketLike] = ws_connect or (
            lambda url: _default_ws_connect(url, max_frame_bytes=self._max_frame_bytes)
        )
        self._websocket: _WebSocketLike | None = None
        self._session: _MutationCdpSession | None = None
        self._dispatch_lock = threading.Lock()
        self._page_events_enabled = False

    @property
    def bound_target_id(self) -> str:
        return self._bound_target_id

    def _resolve_target(self) -> dict[str, Any]:
        pages = [
            item for item in self._http_get_json(f"{self.debug_base_url}/json/list")
            if str(item.get("type") or "") == "page"
        ]
        expected = self._bound_target_id or self._configured_target_id
        if expected:
            for page in pages:
                if str(page.get("id") or "") == expected:
                    return page
            if self._bound_target_id:
                raise RuntimeError(f"bound Browser target disappeared: {self._bound_target_id}; no silent rebind")
            raise RuntimeError(f"configured Browser target not found: {expected}")
        if len(pages) != 1:
            raise RuntimeError(
                "Browser CDP endpoint must expose exactly one page when target_id is omitted; "
                f"observed={len(pages)}"
            )
        return pages[0]

    def _ensure_session(self) -> _MutationCdpSession:
        target = self._resolve_target()
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
            raise RuntimeError("bound Browser target websocket changed; recreate actuator explicitly")
        if self._session is None:
            websocket = self._ws_connect(websocket_url)
            self._websocket = websocket
            self._session = _MutationCdpSession(websocket)
        if not self._page_events_enabled:
            self._session.send("Page.enable")
            self._session.pop_events()
            self._page_events_enabled = True
        return self._session

    def _page_target_ids(self) -> set[str]:
        return {
            str(item.get("id") or "")
            for item in self._http_get_json(f"{self.debug_base_url}/json/list")
            if str(item.get("type") or "") == "page" and str(item.get("id") or "")
        }

    def _boundary_events(
        self,
        session: _MutationCdpSession,
        *,
        before_page_ids: set[str],
    ) -> tuple[dict[str, Any], ...]:
        events: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for raw in session.pop_events():
            method = str(raw.get("method") or "")
            event_name = _BOUNDARY_EVENT_METHODS.get(method)
            if event_name is None:
                continue
            key = (event_name, method)
            if key in seen:
                continue
            seen.add(key)
            events.append(
                {
                    "event": event_name,
                    "scope_ref": None,
                    "detector": method,
                    "complete": False,
                }
            )
        for target_id in sorted(self._page_target_ids() - before_page_ids):
            key = ("new_page", target_id)
            if key in seen:
                continue
            seen.add(key)
            events.append(
                {
                    "event": "new_page",
                    "scope_ref": None,
                    "detector": "TargetList.new_page_id",
                    "complete": False,
                }
            )
        return tuple(events)

    @staticmethod
    def _backend_node_id(physical_target: str | None) -> int:
        raw = str(physical_target or "")
        if not raw.startswith("dom:"):
            raise ValueError("Browser mutation requires exact dom: backend target")
        value = raw.removeprefix("dom:")
        if not value.isdigit():
            raise ValueError("Browser physical target is not a numeric backendNodeId")
        return int(value)

    @staticmethod
    def _object_id(session: _MutationCdpSession, physical_target: str | None) -> str:
        result = session.send("DOM.resolveNode", {"backendNodeId": CdpBrowserMutationActuator._backend_node_id(physical_target)})
        obj = result.get("object") or {}
        object_id = str(obj.get("objectId") or "")
        if not object_id:
            raise RuntimeError("CDP DOM.resolveNode returned no objectId")
        return object_id

    @staticmethod
    def _call(session: _MutationCdpSession, object_id: str, function: str, arguments: list[dict[str, Any]] | None = None) -> None:
        result = session.send(
            "Runtime.callFunctionOn",
            {
                "objectId": object_id,
                "functionDeclaration": function,
                "arguments": arguments or [],
                "returnByValue": True,
                "awaitPromise": False,
            },
        )
        if result.get("exceptionDetails"):
            raise RuntimeError("fixed Browser actuator function raised")

    def _drop_session(self) -> None:
        # EVO-20260918-753b4a91: same-target reconnect only — bound target identity
        # stays pinned; page events must be re-enabled on the new connection.
        websocket = self._websocket
        self._session = None
        self._websocket = None
        self._page_events_enabled = False
        if websocket is not None:
            try:
                websocket.close()
            except Exception:  # noqa: BLE001 - best-effort close of a dead socket
                pass

    def dispatch(self, *, verb: str, physical_target: str | None, args: dict[str, Any]) -> BrowserDispatchResult:
        with self._dispatch_lock:
            try:
                return self._dispatch_locked(verb=verb, physical_target=physical_target, args=args)
            except _CONNECTION_LOST_ERRORS as exc:
                self._drop_session()
                raise RuntimeError(
                    "CDP mutation connection lost; dropped session for same-target reconnect"
                ) from exc

    def _dispatch_locked(
        self, *, verb: str, physical_target: str | None, args: dict[str, Any]
    ) -> BrowserDispatchResult:
        session = self._ensure_session()
        before_page_ids = self._page_target_ids()
        if verb == "navigate":
            session.send("Page.navigate", {"url": str(args["url"])})
            detected = self._boundary_events(session, before_page_ids=before_page_ids)
            return BrowserDispatchResult(
                acknowledged=True,
                boundary_events=(
                    {
                        "event": "navigation_started",
                        "scope_ref": None,
                        "detector": "Page.navigate_ack",
                        "complete": False,
                    },
                )
                + detected,
                completeness_reasons=("boundary_detector_non_exhaustive",),
            )

        object_id = self._object_id(session, physical_target)
        if verb == "click":
            self._call(session, object_id, "function(){ this.click(); }")
        elif verb == "fill":
            self._call(
                session,
                object_id,
                "function(value,mode){ const next=mode==='append' ? String(this.value||'')+value : value; this.value=next; this.dispatchEvent(new Event('input',{bubbles:true})); this.dispatchEvent(new Event('change',{bubbles:true})); }",
                [{"value": str(args["text"])}, {"value": str(args["mode"])}],
            )
        elif verb == "select":
            self._call(
                session,
                object_id,
                "function(value){ this.value=value; this.dispatchEvent(new Event('input',{bubbles:true})); this.dispatchEvent(new Event('change',{bubbles:true})); }",
                [{"value": str(args["value"])}],
            )
        elif verb == "scroll":
            self._call(
                session,
                object_id,
                "function(pages){ this.scrollIntoView({block:'center',inline:'nearest'}); window.scrollBy(0, Number(pages)*window.innerHeight); }",
                [{"value": float(args["delta_pages"])}],
            )
        else:
            raise ValueError(f"unsupported Browser mutation verb: {verb}")
        detected = self._boundary_events(session, before_page_ids=before_page_ids)
        return BrowserDispatchResult(
            acknowledged=True,
            boundary_events=detected,
            completeness_reasons=("boundary_detector_non_exhaustive",),
        )

    def close(self) -> None:
        websocket = self._websocket
        self._session = None
        self._websocket = None
        self._page_events_enabled = False
        if websocket is not None:
            websocket.close()

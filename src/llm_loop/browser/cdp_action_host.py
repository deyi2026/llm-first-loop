"""Narrow CDP mutation actuator for SMC Browser Phase 1.

The model never supplies CDP methods, JavaScript, selectors, coordinates, or backend
node ids.  This host binds one exact loopback page and maps five frozen semantic verbs
to fixed internal CDP sequences.  It performs no retry and never silently rebinds.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
from collections.abc import Callable
from typing import Any, Protocol, cast

from websockets.sync.client import connect as websocket_connect

from llm_loop.browser.action import BrowserDispatchResult
from llm_loop.browser.attestation import AttestationVerdict, BindingPolicy, attest_debug_url
from llm_loop.browser.cdp_host import (
    _CONNECTION_LOST_ERRORS,
    DEFAULT_CDP_MAX_FRAME_BYTES,
    _default_http_get_json,
    _default_http_get_version_dict,
    _normalize_loopback_debug_url,
    _validate_loopback_ws_url,
)
from llm_loop.browser.channel_binding import (
    BrowserChannelBindingCoordinator,
    extract_browser_ws_uuid,
)
from llm_loop.browser.errors import (
    MultiPageAmbiguityError,
    PageRecord,
    PageTargetNotFoundError,
    page_records_from_targets,
)

_attest_logger = logging.getLogger("llm_loop.browser.cdp_action_host.attestation")

# M1 (DESIGN-20261027 B1/B2): two additive methods only - file injection into an
# exact input node and real text input. Everything else stays rejected by send().
_ALLOWED = frozenset(
    {
        "DOM.resolveNode",
        "Runtime.callFunctionOn",
        "Page.enable",
        "Page.navigate",
        "DOM.setFileInputFiles",
        "Input.insertText",
    }
)

# fix(P1-1, review-M1 R-e2e-1): the M1-era synthetic input/change dispatch
# (_UPLOAD_EVENT_DISPATCH_JS) after DOM.setFileInputFiles is REMOVED. Chrome
# (this runtime is pinned 155) natively dispatches exactly one input+change
# pair on DOM.setFileInputFiles (review probe N1: 1/1); the synthetic pair
# doubled it (probe L6: 2/2), which would fire React-like onChange handlers
# twice (double submit). If a future Chrome stops dispatching natively, the
# correct fix is calibrating against a real upload page, not blindly
# re-adding the synthetic pair.

# M1 B2 (DESIGN-20261027 §4.1): focus precedes Input.insertText so the real
# input pipeline (beforeinput/input) lands on the intended element; this fixed
# script replaces the PR2-era ``this.value`` assignment for the new verb only.
_TYPE_FOCUS_JS = "function(){ this.focus(); }"

# FR-2 (DESIGN-20261007-browser-semantic-guard): post-dispatch settle waits.
# Fixed JS constants under version control; the only parameter surface is the
# server-resolved objectId (NFR-2 discipline: zero model-controllable script
# input). Both predicates resolve exactly once and clean up their timers, so
# no page-side leakage across repeated dispatches.
#   baseline:    2 animation frames OR 50ms, whichever comes first (race).
#   combobox:    >=1 visible option inside the aria-controls popup or the
#                neighborhood listbox, polled ~1 frame, 200ms hard cap.
_SETTLE_BASELINE_JS = (
    "function(){"
    "const t0=performance.now(),cap=50;"
    "return new Promise(function(resolve){"
    "var done=false,timer=null;"
    "function fin(by){if(done)return;done=true;"
    "if(timer){clearTimeout(timer);}"
    "resolve({settled:by!=='cap',settled_by:by,"
    "elapsed_ms:Math.round(performance.now()-t0),cap_ms:cap});}"
    # Defensive view resolution: element hosts carry ownerDocument.defaultView,
    # document-root hosts have ownerDocument === null and expose defaultView
    # themselves (proven by the real-Chromium probe, not assumed).
    "var view=(this.ownerDocument&&this.ownerDocument.defaultView)||this.defaultView||window,n=0;"
    "function raf(){n+=1;if(n>=2){fin('raf');return;}"
    "view.requestAnimationFrame(raf);}"
    "view.requestAnimationFrame(raf);"
    "timer=view.setTimeout(function(){fin('cap');},cap);"
    "});}"
)

_SETTLE_COMBOBOX_JS = (
    "function(){"
    "const t0=performance.now(),cap=200;"
    # Defensive host resolution: for element targets this.ownerDocument exists,
    # but document-root targets have ownerDocument === null (proven by the
    # real-Chromium probe); resolve the view across all host shapes.
    "var el=(this&&typeof this.getAttribute==='function')?this:null;"
    "function fin0(){return {settled:false,settled_by:'cap',visible_options:0,"
    "elapsed_ms:Math.round(performance.now()-t0),cap_ms:cap};}"
    "if(!el){return Promise.resolve(fin0());}"
    "function visible(node){"
    "var r=node.getBoundingClientRect(),s=getComputedStyle(node);"
    "return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';}"
    "function opts(){"
    "var root=document.getElementById(el.getAttribute('aria-controls')||'')||el.parentElement||el;"
    "var list=root.matches('[role=listbox],ul,ol')?root:(root.querySelector('[role=listbox]')||root);"
    "var sel=list.querySelectorAll('[role=option],option,li'),n=0;"
    "for(var i=0;i<sel.length;i+=1){if(visible(sel[i])){n+=1;}}"
    "return n;}"
    "return new Promise(function(resolve){"
    "var done=false,iv=null,timer=null;"
    "function fin(n,by){if(done)return;done=true;"
    "if(iv){clearInterval(iv);}if(timer){clearTimeout(timer);}"
    "resolve({settled:n>0,settled_by:by,visible_options:n,"
    "elapsed_ms:Math.round(performance.now()-t0),cap_ms:cap});}"
    "var first=opts();if(first>0){fin(first,'options');}"
    "else{iv=setInterval(function(){var n=opts();if(n>0){fin(n,'options');}},16);"
    "timer=setTimeout(function(){fin(opts(),'cap');},cap);}"
    "});}"
)

_SETTLE_SCRIPTS: dict[str, str] = {
    "raf_baseline": _SETTLE_BASELINE_JS,
    "combobox_options": _SETTLE_COMBOBOX_JS,
}

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
        binding_coordinator: BrowserChannelBindingCoordinator | None = None,
        http_get_version_dict: Callable[[str], dict[str, Any]] | None = None,
        binding_policy: BindingPolicy | None = None,
        attest_fn: Callable[[str], AttestationVerdict] | None = None,
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
        # S3a（DESIGN-20261005 v4 §4.3）：可选共享通道绑定；None ⇒ 行为与之前完全一致
        # （直连 harness/qualification 构造不受影响）。factory 注入同一协调器给感知 host。
        self._binding_coordinator = binding_coordinator
        self._http_get_version_dict = http_get_version_dict or _default_http_get_version_dict
        # S3b（R3 attestation，S0 结论 ②）：policy 缺省 deny_real —— 直连入口零改动即
        # fail-closed；attest_fn 缺省走 host 侧 lsof→PID→ps 真机制（测试可注入 stub）。
        self._binding_policy = binding_policy or BindingPolicy.deny_real()
        self._attest_fn: Callable[[str], AttestationVerdict] = (
            attest_fn or (lambda url: attest_debug_url(url))
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
            # EVO-20261007-11ae668f：多页且未显式指定 target ⇒ 结构化歧义错误，
            # 携带只读页面清单；不做任何自动选择。
            raise MultiPageAmbiguityError(page_records_from_targets(pages))
        return pages[0]

    def list_pages(self) -> list[PageRecord]:
        """EVO-20261007-11ae668f：只读页面清单，不绑定、不建会话、无副作用。"""

        pages = [
            item for item in self._http_get_json(f"{self.debug_base_url}/json/list")
            if str(item.get("type") or "") == "page"
        ]
        return page_records_from_targets(pages)

    def rebind_target(self, target_id: str) -> PageRecord:
        """EVO-20261007-11ae668f：显式换页（确定性，非静默）。

        语义与 CdpReadOnlyBrowserHost.rebind_target 一致：target 必须命中
        当前清单；既有绑定/会话立即丢弃；coordinator 由上层 controller 统一重绑。
        """

        raw = str(target_id or "").strip()
        if not raw:
            raise ValueError("rebind_target requires a non-empty explicit target_id")
        with self._dispatch_lock:
            records = self.list_pages()
            for record in records:
                if record.page_id == raw:
                    self._configured_target_id = raw
                    self._bound_target_id = ""
                    self._bound_websocket_url = ""
                    self._drop_session()
                    return record
            raise PageTargetNotFoundError(raw, records)

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
            # S3b attestation（S0 结论 ②）：绑定前 host 侧进程证据判定；deny-real 默认
            # fail-closed（shadow 模式只记录不拒绝）。先判后连——拒绝路径零连接成本。
            _verdict = self._attest_fn(self.debug_base_url)
            _allowed, _reason = self._binding_policy.check(_verdict)
            if not _allowed:
                raise RuntimeError(f"Browser channel attestation refused: {_reason}")
            _attest_logger.info("browser channel attestation [%s]: %s", self.__class__.__name__, _reason)
            # S3a：actuator 不再拥有独立首绑语义——新建绑定前必须与共享协调器对身份
            # （browser ws UUID + target + ws url 三字段 + attestation 一致性）。
            # 感知 host 若已绑定另一台 Chrome / 或 attestation verdict 不一致，此处直接拒绝。
            if self._binding_coordinator is not None:
                version = self._http_get_version_dict(
                    f"{self.debug_base_url}/json/version"
                )
                browser_ws_uuid = extract_browser_ws_uuid(
                    str(version.get("webSocketDebuggerUrl") or "")
                )
                self._binding_coordinator.require_match(
                    browser_ws_uuid,
                    target_id,
                    websocket_url,
                    argv_sha256=_verdict.argv_sha256,
                    verdict=_verdict.verdict,
                    checked_at=_verdict.checked_at,
                )
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
            with contextlib.suppress(Exception):  # noqa: BLE001 - best-effort close of a dead socket
                websocket.close()

    def dispatch(self, *, verb: str, physical_target: str | None, args: dict[str, Any]) -> BrowserDispatchResult:
        with self._dispatch_lock:
            try:
                return self._dispatch_locked(verb=verb, physical_target=physical_target, args=args)
            except _CONNECTION_LOST_ERRORS as exc:
                self._drop_session()
                raise RuntimeError(
                    "CDP mutation connection lost; dropped session for same-target reconnect"
                ) from exc

    def settle(self, *, physical_target: str | None, mode: str) -> dict[str, Any]:
        """FR-2: single-round-trip post-dispatch settle wait on the bound page.

        Runs a fixed, version-controlled predicate (``_SETTLE_SCRIPTS[mode]``)
        via Runtime.callFunctionOn with awaitPromise so the rAF/timeout race
        and option polling happen page-side in one round trip. Deterministic
        failures resolve to verdict "unavailable" (with reason) instead of
        raising: settle is an observation-quality enhancement, not a safety
        gate, so it must never break the dispatch path it follows.
        """
        script = _SETTLE_SCRIPTS.get(mode)
        if script is None:
            return {"schema": "smc.browser_wait_verdict.v0.1", "mode": mode, "verdict": "unavailable", "reason": "unknown_mode"}
        with self._dispatch_lock:
            try:
                session = self._ensure_session()
                object_id = self._object_id(session, physical_target)
                result = session.send(
                    "Runtime.callFunctionOn",
                    {
                        "objectId": object_id,
                        "functionDeclaration": script,
                        "arguments": [],
                        "returnByValue": True,
                        "awaitPromise": True,
                    },
                )
            except _CONNECTION_LOST_ERRORS as exc:
                self._drop_session()
                return {"schema": "smc.browser_wait_verdict.v0.1", "mode": mode, "verdict": "unavailable", "reason": f"connection_lost: {exc}"}
        if result.get("exceptionDetails"):
            details = result.get("exceptionDetails") or {}
            desc = str(((details.get("exception") or {}).get("description")) or details.get("text") or "")[:200]
            return {"schema": "smc.browser_wait_verdict.v0.1", "mode": mode, "verdict": "unavailable", "reason": f"predicate_raised: {desc}"}
        remote = result.get("result") or {}
        value = remote.get("value")
        if not isinstance(value, dict) or "settled" not in value:
            return {"schema": "smc.browser_wait_verdict.v0.1", "mode": mode, "verdict": "unavailable", "reason": "unexpected_predicate_shape"}
        # Mixed value types (str keys + int elapsed_ms fallback); the explicit
        # annotation keeps pyright from inferring dict[str, str] (M1 changed-file
        # hygiene; runtime behavior identical).
        verdict: dict[str, Any] = {"schema": "smc.browser_wait_verdict.v0.1", "mode": mode}
        verdict.update(value)
        if not isinstance(verdict.get("elapsed_ms"), int):
            verdict["elapsed_ms"] = -1
        if verdict.get("settled"):
            verdict["verdict"] = "settled"
        else:
            verdict["verdict"] = "timeout"
        return verdict

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
        elif verb == "upload":
            # M1 B1: resolved absolute paths arrive from the contract layer
            # (action.py validated realpath/allow_roots/size/count BEFORE any
            # CDP call, and re-verified them right before dispatch — fix(P0-1)).
            # backendNodeId is the product's physical identity (dom:<id>), so
            # no DOM.getDocument/querySelector chain is needed (M0 §3.2 T2).
            # fix(P1-1): NO synthetic input/change dispatch follows — Chrome
            # natively dispatches one input+change pair here; the native pair
            # alone keeps React-like onChange single-shot (review N1 vs L6).
            backend_id = self._backend_node_id(physical_target)
            session.send(
                "DOM.setFileInputFiles",
                {"files": [str(item) for item in args["paths"]], "backendNodeId": backend_id},
            )
        elif verb == "type":
            # M1 B2: real input pipeline via Input.insertText after a fixed
            # focus call - never a ``this.value`` assignment with synthesized
            # events (PR2 root cause). Empty text is an explicit acknowledged
            # no-op: no focus, no insert, no content change.
            text = str(args["text"])
            if text:
                self._call(session, object_id, _TYPE_FOCUS_JS)
                session.send("Input.insertText", {"text": text})
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

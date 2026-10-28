"""Narrow CDP mutation actuator for SMC Browser Phase 1.

The model never supplies CDP methods, JavaScript, selectors, coordinates, or backend
node ids.  This host binds one exact loopback page and maps five frozen semantic verbs
to fixed internal CDP sequences.  It performs no retry and never silently rebinds.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
from collections.abc import Callable
from typing import Any, Protocol, cast

from websockets.sync.client import connect as websocket_connect

from llm_loop.browser.action import (
    BrowserDispatchResult,
    parse_key_chord,
    press_key_policy_error,
)
from llm_loop.browser.attestation import AttestationVerdict, BindingPolicy, attest_debug_url
from llm_loop.browser.cdp_host import (
    _CONNECTION_LOST_ERRORS,
    DEFAULT_CDP_MAX_FRAME_BYTES,
    _classify_connection_loss,
    _default_http_get_json,
    _default_http_get_version_dict,
    _normalize_loopback_debug_url,
    _validate_loopback_ws_url,
)
from llm_loop.browser.channel_binding import (
    BrowserChannelBindingCoordinator,
    extract_browser_ws_uuid,
)
from llm_loop.browser.download_contract import download_path_policy_error
from llm_loop.browser.errors import (
    MultiPageAmbiguityError,
    PageRecord,
    PageTargetNotFoundError,
    page_records_from_targets,
)

_attest_logger = logging.getLogger("llm_loop.browser.cdp_action_host.attestation")

# M1 (DESIGN-20261027 B1/B2): two additive methods only - file injection into an
# exact input node and real text input. Everything else stays rejected by send().
# M2-A additions carry one-line necessity notes; wide-surface methods
# (Runtime.evaluate, Page.evalOnNewDocument, DOM.getDocument, ...) stay out.
_ALLOWED = frozenset(
    {
        "DOM.resolveNode",
        "Runtime.callFunctionOn",
        "Page.enable",
        "Page.navigate",
        "DOM.setFileInputFiles",
        "Input.insertText",
        # M2-A B3: press_key actuates ONLY through this method (paired
        # keyDown/keyUp); no script/eval channel is opened for it.
        "Input.dispatchKeyEvent",
        # M2-A B4: hover actuates ONLY through this method (exactly one
        # mouseMoved event, never a click press/release pair).
        "Input.dispatchMouseEvent",
        # M2-A B5 + R3 (TASK-009 2026-10-28 §6): accept/dismiss a blocking JS
        # dialog. Gated by drained dialog state; when the gate is False the
        # verb self-heals (one drain pass, then ONE blind handle attempt that
        # maps Chrome's "No dialog is showing" back to dialog_not_open) so a
        # page-initiated dialog missed by the event drain is still handleable.
        "Page.handleJavaScriptDialog",
        # M2-A B6: pin Chrome downloads into the session-fenced dir; also the
        # only switch that turns on downloadWillBegin/downloadProgress events.
        "Page.setDownloadBehavior",
    }
)


class _ActuatorContractError(RuntimeError):
    """M2-A: deterministic actuator-boundary rejection with a stable receipt code.

    Raised BEFORE any side-effecting CDP call (blacklist chord, invisible
    hover target, no open dialog); the adapter surfaces ``error_code``
    verbatim as the receipt retry reason instead of the ambiguous marker.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.error_code = code


class _DialogOpeningInterruptedError(Exception):
    """R2 (TASK-009 2026-10-28 §6): dialog opened while a send loop was waiting.

    Raised only when ``send(..., early_return_on_dialog=True)`` (the click
    path): a synchronous JS dialog occupies the renderer main thread, so the
    pending ``Runtime.callFunctionOn`` response for ``this.click()`` can never
    arrive before the dialog is handled (verdict L1/M4). The opening event is
    appended to the session event buffer BEFORE raising, so the boundary-event
    drain semantics stay unchanged.

    Deliberately a plain ``Exception`` (not OSError, not RuntimeError from the
    CDP error branch): it must bypass every ``_CONNECTION_LOST_ERRORS``
    handler and never be mistaken for a channel failure or a CDP error.
    """

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__("Page.javascriptDialogOpening")
        self.params = params


# M2-A B3 (DESIGN-20261027 §5.1): CDP Input.dispatchKeyEvent parameter assembly
# for a validated chord. Fixed tables under version control; the only variable
# is the already-blacklist-checked chord string (no script surface opened).
_CDP_MODIFIER_BITS = {"alt": 1, "control": 2, "meta": 4, "shift": 8}
_MODIFIER_EVENT_PROPS = {
    "alt": ("Alt", "AltLeft", 18),
    "control": ("Control", "ControlLeft", 17),
    "meta": ("Meta", "MetaLeft", 91),
    "shift": ("Shift", "ShiftLeft", 16),
}
_KEY_NAMED_CODES: dict[str, tuple[str, int]] = {
    "`": ("Backquote", 223),
    "backquote": ("Backquote", 223),
    "backtick": ("Backquote", 223),
    "backspace": ("Backspace", 8),
    "delete": ("Delete", 46),
    "enter": ("Enter", 13),
    "escape": ("Escape", 27),
    "tab": ("Tab", 9),
    "space": ("Space", 32),
    "arrowleft": ("ArrowLeft", 37),
    "arrowup": ("ArrowUp", 38),
    "arrowright": ("ArrowRight", 39),
    "arrowdown": ("ArrowDown", 40),
    "home": ("Home", 36),
    "end": ("End", 35),
    "pageup": ("PageUp", 33),
    "pagedown": ("PageDown", 34),
}
for _fn in range(1, 13):
    _KEY_NAMED_CODES[f"f{_fn}"] = (f"F{_fn}", 111 + _fn)
# Puppeteer parity: only these two keys carry text on keyDown so default
# actions (form submit on Enter, focus traversal on Tab) actually fire.
_KEY_TEXT_BY_KEY = {"enter": "\r", "tab": "\t"}


def _key_code(key: str) -> tuple[str, int | None]:
    if len(key) == 1 and key.isalpha():
        return f"Key{key.upper()}", 65 + (ord(key) - 97)
    if len(key) == 1 and key.isdigit():
        return f"Digit{key}", 48 + int(key)
    named = _KEY_NAMED_CODES.get(key)
    if named is not None:
        return named
    return key, None


def _key_event(
    event_type: str, key: str, code: str, vk: int | None, *, modifiers: int, text: str = ""
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "type": event_type,
        "key": key,
        "code": code,
        "modifiers": modifiers,
    }
    if vk is not None:
        params["windowsVirtualKeyCode"] = vk
        params["nativeVirtualKeyCode"] = vk
    if text:
        params["text"] = text
    return params


def key_events_for_chord(keys: str) -> list[dict[str, Any]]:
    """Paired keyDown/keyUp params for one validated chord (B3).

    Modifier keys press before the main key (sorted order) and release after
    it in reverse; a held modifier stays in the bitmask during its own keyUp,
    matching the real input pipeline semantics Puppeteer implements.
    """
    modifiers, key = parse_key_chord(keys)
    if modifiers is None or not key:
        raise _ActuatorContractError("key_args_invalid")
    code, vk = _key_code(key)
    bitmask = 0
    events: list[dict[str, Any]] = []
    for mod in modifiers:
        events.append(_key_event("keyDown", *_MODIFIER_EVENT_PROPS[mod], modifiers=bitmask))
        bitmask |= _CDP_MODIFIER_BITS[mod]
    text = _KEY_TEXT_BY_KEY.get(key, "")
    events.append(_key_event("keyDown", key, code, vk, modifiers=bitmask, text=text))
    events.append(_key_event("keyUp", key, code, vk, modifiers=bitmask))
    for mod in reversed(modifiers):
        events.append(_key_event("keyUp", *_MODIFIER_EVENT_PROPS[mod], modifiers=bitmask))
        bitmask &= ~_CDP_MODIFIER_BITS[mod]
    return events

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

# M2-A B4 (DESIGN-20261027 §5.1): scroll the exact element into view, then read
# its post-scroll bounding rect in ONE fixed predicate call (scrollIntoView
# forces synchronous layout, so the rect reflects the scrolled position).
# getBoundingClientRect is CSS px relative to the viewport - the exact
# coordinate space Input.dispatchMouseEvent consumes. The rect is also the
# positive-area gate: a zero-area element raises element_not_visible BEFORE
# any pointer event is dispatched.
_HOVER_RECT_JS = (
    "function(){"
    "this.scrollIntoView({block:'center',inline:'nearest'});"
    "const r=this.getBoundingClientRect();"
    "return {x:r.x,y:r.y,w:r.width,h:r.height};"
    "}"
)

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

    def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        early_return_on_dialog: bool = False,
    ) -> dict[str, Any]:
        """Send one allowlisted CDP request and wait for its own response.

        R2 (TASK-009 §6): with ``early_return_on_dialog=True`` (click path
        only), a ``Page.javascriptDialogOpening`` event observed while waiting
        aborts the wait via ``_DialogOpeningInterruptedError`` — the pending
        response can never arrive while the modal holds the renderer. Default
        False keeps settle/hover/press_key semantics byte-identical.
        """
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
                        if (
                            early_return_on_dialog
                            and message.get("method") == "Page.javascriptDialogOpening"
                        ):
                            raise _DialogOpeningInterruptedError(
                                message.get("params")
                                if isinstance(message.get("params"), dict)
                                else {}
                            )
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

    def drain(self, max_events: int = 64, *, timeout_s: float = 0.05) -> None:
        """M2-A B6: drain buffered events without sending a request.

        recv() on a quiet socket raises TimeoutError; that is the normal
        "nothing more to drain" signal (the observation caller suppresses
        channel errors and keeps the last known state).
        """
        with self._lock:
            for _ in range(max(1, max_events)):
                try:
                    raw = self._websocket.recv(timeout=timeout_s)
                except TimeoutError:
                    break
                message = json.loads(raw)
                if isinstance(message, dict) and isinstance(message.get("method"), str):
                    self._events.append(message)


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
        download_dir_provider: Callable[[], str] | None = None,
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
        # M2-A B5 (F8): dialog state machine rides the existing boundary-event
        # drain; True only between a drained javascriptDialogOpening and a
        # successful Page.handleJavaScriptDialog.
        self._dialog_open = False
        self._dialog_detail: dict[str, Any] | None = None
        # M2-A B6: download contract state. The provider resolves the CURRENT
        # session's fenced dir (receipt-store shape); re-pinning on session
        # change keeps downloads fenced per session, never per process.
        self._download_dir_provider = download_dir_provider
        self._configured_download_dir: str | None = None
        self._downloads: dict[str, dict[str, Any]] = {}

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
            # M2-A B5: the enable-time drain feeds the state machine instead of
            # being discarded - a dialog that opened while the session was
            # (re)connecting must still gate the dialog verb.
            self._absorb_state_events(self._session.pop_events())
            self._page_events_enabled = True
        # M2-A B6: keep the download dir pinned to the CURRENT session (no-op
        # when unchanged); must precede any dispatch that could start one.
        self._sync_download_behavior(self._session)
        return self._session

    def _page_target_ids(self) -> set[str]:
        return {
            str(item.get("id") or "")
            for item in self._http_get_json(f"{self.debug_base_url}/json/list")
            if str(item.get("type") or "") == "page" and str(item.get("id") or "")
        }

    def _absorb_state_events(self, raw_events: list[dict[str, Any]]) -> None:
        """M2-A B5/B6: the single consumer point of drained events (F8).

        Dialog state: javascriptDialogOpening means a blocking dialog is open;
        only a handled dialog closes it. Download state: WillBegin records the
        page-suggested filename with an immediate realpath containment check
        ('../' and symlink escapes are marked path_not_allowed at RECORD time,
        before any fact is ever reported); Progress updates the state.
        """
        for raw in raw_events:
            method = str(raw.get("method") or "")
            params = raw.get("params")
            params = params if isinstance(params, dict) else {}
            if method == "Page.javascriptDialogOpening":
                self._dialog_open = True
                self._dialog_detail = params
            elif method == "Page.downloadWillBegin":
                guid = str(params.get("guid") or params.get("downloadId") or "")
                if guid:
                    filename = str(params.get("suggestedFilename") or "")
                    self._downloads[guid] = {
                        "guid": guid,
                        "filename": filename,
                        "url": str(params.get("url") or ""),
                        "state": "inprogress",
                        "received_bytes": 0,
                        "policy_error": download_path_policy_error(
                            self._configured_download_dir, filename
                        ),
                    }
            elif method == "Page.downloadProgress":
                guid = str(params.get("guid") or params.get("downloadId") or "")
                entry = self._downloads.get(guid)
                if entry is not None:
                    entry["state"] = str(params.get("state") or "inprogress")
                    if params.get("receivedBytes") is not None:
                        entry["received_bytes"] = params.get("receivedBytes")

    def download_state(self) -> dict[str, Any]:
        """M2-A B6: best-effort drain of pending events + a state copy.

        Observation surface: any channel failure keeps the last known state
        (the wait layer degrades honestly to its timeout instead of failing
        the whole perceive call on a quiet/closed channel).
        """
        session = self._session
        if session is not None:
            with contextlib.suppress(Exception):  # noqa: BLE001 - observation is fail-open
                session.drain()
                self._absorb_state_events(session.pop_events())
        return {
            "schema": "smc.browser_download_state.v0.1",
            "download_dir": self._configured_download_dir,
            "dialog_open": self._dialog_open,
            "downloads": {guid: dict(entry) for guid, entry in self._downloads.items()},
        }

    def _sync_download_behavior(self, session: _MutationCdpSession) -> None:
        """M2-A B6: pin Chrome downloads into the CURRENT session's fenced dir.

        The provider is re-evaluated on every session ensure; a session change
        re-sends setDownloadBehavior (idempotent per dir). behavior=allow +
        eventsEnabled is what routes downloadWillBegin/downloadProgress through
        the same drain the dialog state rides on.
        """
        if self._download_dir_provider is None:
            return
        target_dir = os.path.realpath(str(self._download_dir_provider() or ""))
        if not target_dir or target_dir == self._configured_download_dir:
            return
        os.makedirs(target_dir, exist_ok=True)
        session.send(
            "Page.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": target_dir, "eventsEnabled": True},
        )
        self._configured_download_dir = target_dir

    def _boundary_events(
        self,
        session: _MutationCdpSession,
        *,
        before_page_ids: set[str],
    ) -> tuple[dict[str, Any], ...]:
        events: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        drained = session.pop_events()
        self._absorb_state_events(drained)
        for raw in drained:
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
    def _call(
        session: _MutationCdpSession,
        object_id: str,
        function: str,
        arguments: list[dict[str, Any]] | None = None,
        *,
        early_return_on_dialog: bool = False,
    ) -> None:
        result = session.send(
            "Runtime.callFunctionOn",
            {
                "objectId": object_id,
                "functionDeclaration": function,
                "arguments": arguments or [],
                "returnByValue": True,
                "awaitPromise": False,
            },
            early_return_on_dialog=early_return_on_dialog,
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
                loss_mode = _classify_connection_loss(exc)
                if loss_mode == "timeout":
                    # R1 (TASK-009 2026-10-28 §6): a recv timeout is not a
                    # connection loss. Dropping the session here used to sever
                    # the only channel still able to handle a live blocking
                    # dialog (click → alert → 5s timeout → drop → tab
                    # permanently dead, verdict §4.4). Keep the session; only
                    # frame_too_large / connection still drop.
                    raise RuntimeError(
                        "CDP mutation timed out; session kept for same-target retry"
                        f"; error_type={type(exc).__name__}"
                    ) from exc
                self._drop_session()
                raise RuntimeError(
                    "CDP mutation connection lost; dropped session for same-target reconnect"
                ) from exc

    @staticmethod
    def _hover_center(session: _MutationCdpSession, object_id: str) -> None:
        """M2-A B4: move the pointer to the element center (one mouseMoved).

        Positive-area gate runs on the measured rect BEFORE any pointer event:
        a zero-area element is a deterministic contract rejection
        (element_not_visible) with zero dispatchMouseEvent side effects.
        """
        result = session.send(
            "Runtime.callFunctionOn",
            {
                "objectId": object_id,
                "functionDeclaration": _HOVER_RECT_JS,
                "arguments": [],
                "returnByValue": True,
                "awaitPromise": False,
            },
        )
        if result.get("exceptionDetails"):
            raise RuntimeError("fixed Browser actuator function raised")
        value = (result.get("result") or {}).get("value")
        rect = value if isinstance(value, dict) else {}
        width = float(rect.get("w") or 0)
        height = float(rect.get("h") or 0)
        if width <= 0 or height <= 0:
            raise _ActuatorContractError("element_not_visible")
        session.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": float(rect.get("x") or 0) + width / 2,
                "y": float(rect.get("y") or 0) + height / 2,
                "button": "none",
                "pointerType": "mouse",
            },
        )

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
                loss_mode = _classify_connection_loss(exc)
                if loss_mode == "timeout":
                    # R1 (TASK-009 §6): timeout keeps the session (dialog-capable);
                    # the settle verdict stays honest ("unavailable") instead of
                    # tearing down the only channel that can still handle a dialog.
                    return {"schema": "smc.browser_wait_verdict.v0.1", "mode": mode, "verdict": "unavailable", "reason": f"timeout: {exc}"}
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

    def _acknowledged(
        self, session: _MutationCdpSession, before_page_ids: set[str]
    ) -> BrowserDispatchResult:
        """M2-A: shared acknowledged receipt for page-scoped verbs (drains
        boundary events exactly like the legacy tail of _dispatch_locked)."""
        return BrowserDispatchResult(
            acknowledged=True,
            boundary_events=self._boundary_events(session, before_page_ids=before_page_ids),
            completeness_reasons=("boundary_detector_non_exhaustive",),
        )

    def _dispatch_locked(
        self, *, verb: str, physical_target: str | None, args: dict[str, Any]
    ) -> BrowserDispatchResult:
        # M2-A B5 + R3 (TASK-009 2026-10-28 §6): the dialog verb used to
        # hard-reject on a False gate, which permanently locked it whenever the
        # javascriptDialogOpening event was missed (page-initiated dialog that
        # fired before this session enabled Page.enable, state lost across a
        # drop, ...). Self-heal instead: one drain pass; if still no state,
        # ONE blind handle attempt - Chrome's "No dialog is showing" error maps
        # back to the same deterministic dialog_not_open contract error, and a
        # success means the requested action itself completed. On a live
        # session the only CDP command this adds is the handle itself.
        dialog_blind_handled = False
        if verb == "dialog" and not self._dialog_open:
            session = self._ensure_session()
            session.drain()
            self._absorb_state_events(session.pop_events())
            if not self._dialog_open:
                try:
                    session.send(
                        "Page.handleJavaScriptDialog",
                        {"accept": str(args.get("action") or "") == "accept"},
                    )
                except RuntimeError as exc:
                    if "No dialog is showing" in str(exc):
                        raise _ActuatorContractError("dialog_not_open") from exc
                    raise
                dialog_blind_handled = True
                self._dialog_detail = None
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

        if verb == "press_key":
            # M2-A B3: page-level chord via paired keyDown/keyUp. The shared
            # blacklist re-runs here as the last defense in depth (compile and
            # adapter _validate already rejected violations); a hit raises
            # before any Input.dispatchKeyEvent leaves this host.
            keys = str(args.get("keys") or "")
            policy_error = press_key_policy_error(keys)
            if policy_error is not None:
                raise _ActuatorContractError(policy_error)
            for event in key_events_for_chord(keys):
                session.send("Input.dispatchKeyEvent", event)
            return self._acknowledged(session, before_page_ids)

        if verb == "dialog":
            # M2-A B5: state gate already passed above (or the R3 self-heal
            # already blind-handled the dialog); handle the blocking dialog
            # and clear the state (the page script then continues).
            if not dialog_blind_handled:
                session.send(
                    "Page.handleJavaScriptDialog",
                    {"accept": str(args.get("action") or "") == "accept"},
                )
            self._dialog_open = False
            self._dialog_detail = None
            return self._acknowledged(session, before_page_ids)

        object_id = self._object_id(session, physical_target)
        if verb == "click":
            try:
                self._call(session, object_id, "function(){ this.click(); }", early_return_on_dialog=True)
            except _DialogOpeningInterruptedError as opening:
                # R2 (TASK-009 §6): event-first click. The click DID dispatch;
                # the opening event is the honest boundary fact. The pending
                # Runtime response can only arrive after the dialog is handled
                # (verdict L1), so waiting for it is a guaranteed timeout. Mark
                # the dialog state, acknowledge now with the dialog_opened
                # boundary event, and keep the session alive for the dialog
                # verb - never a drop.
                self._dialog_open = True
                self._dialog_detail = opening.params
                return BrowserDispatchResult(
                    acknowledged=True,
                    boundary_events=self._boundary_events(session, before_page_ids=before_page_ids),
                    completeness_reasons=("boundary_detector_non_exhaustive",),
                )
        elif verb == "hover":
            # M2-A B4: pointer-only hover, never a click (see _hover_center).
            self._hover_center(session, object_id)
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

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
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import httpx
from websockets.exceptions import ConnectionClosed as _WsConnectionClosed
from websockets.sync.client import connect as websocket_connect

from llm_loop.browser.attestation import AttestationVerdict, BindingPolicy, attest_debug_url
from llm_loop.browser.channel_binding import (
    BrowserChannelBindingCoordinator,
    extract_browser_ws_uuid,
)
from llm_loop.browser.perception import PlaywrightPageCaptureBackend

_attest_logger = logging.getLogger("llm_loop.browser.cdp_host.attestation")

# EVO-20260918-753b4a91: websockets 默认 max_size=1MiB；DOM+AX 大页（如 GitHub 仓库页）
# 的 CDP 响应帧超限即 1009 断连且死连接永不重建，会话困死。帧上限参数化 + 同 target 断线重建。
# 2026-09-18 huge-page retest: 10.4MB HTML / ~100k nodes 的 DOMSnapshot 帧约 47MB（可过），
# 但随后的 Accessibility.getFullAXTree 全树帧 >64MiB 仍撞 1009；默认提升到 128MiB，env 可覆盖。
DEFAULT_CDP_MAX_FRAME_BYTES = 134_217_728
# Absolute ceiling: a misconfigured/oversized LFL_BROWSER_CDP_MAX_FRAME_BYTES can
# never lift a single CDP frame past this bound (memory safety). Oversized
# DOMSnapshot payloads are bounded by node_cap projection, never by unbounded
# frame buffering.
HARD_CAP_CDP_MAX_FRAME_BYTES = 268_435_456  # 256 MiB
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

# FR-1 (DESIGN-20261007-browser-semantic-guard) fixed read-only guard probe.
# Parameter surface: the resolved element only. Extraction rules are pinned to
# the sensor canonicalize semantics -- any drift here is a correctness bug on
# the baseline-vs-current comparison:
#   name     aria-label || name attribute
#   text     DIRECT text-child aggregation only (no descendant text leak)
#   value    HTML value ATTRIBUTE (the .value property is intentionally not
#            read; the sensor source materializes the attribute)
#   no id, no viewport/scroll/geometry in fingerprints (they only feed the
#            occlusion check); sensitive value redaction happens server-side
#            in perception.assess_guard via the single FR-6 whitelist.
_GUARD_COLLECT_FUNCTION = (
    "function(el){"
    "try{"
    "var r=el.getBoundingClientRect();"
    "var cx=r.x+r.width/2,cy=r.y+r.height/2;"
    "var hit=document.elementFromPoint(cx,cy);"
    "var occluded=false,hitTag=null;"
    "if(hit){hitTag=hit.tagName.toLowerCase();"
    "occluded=hit!==el&&!el.contains(hit)&&!hit.contains(el);}"
    "var anc=el.closest('form,dialog,tr,[role=form],[role=dialog],[role=row],li');"
    "var nb=null;"
    "if(anc){"
    "var kids=Array.prototype.slice.call(anc.children,0,32);"
    "nb={tag:anc.tagName.toLowerCase(),"
    "role:anc.getAttribute('role')||null,"
    "children:kids.map(function(c){"
    "var t='';"
    "for(var i=0;i<c.childNodes.length;i++){"
    "if(c.childNodes[i].nodeType===3){t+=c.childNodes[i].textContent;}}"
    "return {tag:c.tagName.toLowerCase(),"
    "name:c.getAttribute('aria-label')||c.getAttribute('name')||null,"
    "text:t.trim().slice(0,40)};})};}"
    "var dt='';"
    "for(var j=0;j<el.childNodes.length;j++){"
    "if(el.childNodes[j].nodeType===3){dt+=el.childNodes[j].textContent;}}"
    "return {ok:true,"
    "doc:{url:location.href},"
    "target:{tag:el.tagName.toLowerCase(),"
    "name:el.getAttribute('aria-label')||el.getAttribute('name')||null,"
    "role:el.getAttribute('role')||null,"
    "type:el.getAttribute('type')||null,"
    "text:dt.trim().slice(0,200),"
    "value:el.getAttribute('value')},"
    "nb:nb,"
    "geo:{w:r.width,h:r.height,visible:r.width>0&&r.height>0},"
    "occluded:occluded,hitTag:hitTag};"
    "}catch(err){return {ok:false,stage:'evaluate',"
    "error_type:'js_error',message:String(err&&err.message||err).slice(0,200)};}}"
)


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


def _default_http_get_version_dict(url: str) -> dict[str, Any]:
    """S3a/BrowserChannelBinding：GET /json/version，必须返回 dict（F16b）。

    独立于 /json/list 通道注入，测试可替换；不改变任何 /json/list 语义。
    """
    with httpx.Client(timeout=3.0, trust_env=False, follow_redirects=False) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Chrome /json/version did not return a dict")
    return payload


def _default_ws_connect(url: str, *, max_frame_bytes: int = DEFAULT_CDP_MAX_FRAME_BYTES) -> _WebSocketLike:
    return cast(
        _WebSocketLike,
        websocket_connect(url, open_timeout=5.0, max_size=max(1, int(max_frame_bytes))),
    )


class _ReadOnlyCdpSession:
    """One persistent page-target websocket with a hard method allowlist."""

    def __init__(self, websocket: _WebSocketLike, *, timeout_s: float = 20.0) -> None:
        self._websocket = websocket
        # 2026-09-18 live huge-page retest (10.4MB HTML / ~100k nodes): the
        # DOMSnapshot frame itself returns in ~1.4s at ~47MB, but the follow-up
        # observation requests (AX tree capture) exceed a 5s single-recv budget.
        # 20s keeps big-page observation viable inside the 60s tool budget while
        # the drop-session/same-target-reconnect semantics stay unchanged.
        self._timeout_s = float(timeout_s)
        self._request_id = 0
        self._lock = threading.Lock()
        # EVO-20260918-a2727fb2: diagnostics of the LAST SUCCESSFUL request so
        # connection-lost failures can be classified (timeout vs frame limit vs
        # transport). Note: when the failing request times out, these fields
        # still describe the prior completed request — never the failing one.
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

    def collect_guard_observation(self, backend_node_id: int) -> dict[str, Any]:
        """FR-1 guard probe: resolve one node, run the fixed read-only guard JS.

        Two protocol messages, one atomic semantic collection. The script is a
        module constant (no dynamic expression), the only parameter is the
        backend node id resolved from the already-persisted snapshot identity.
        Returns {"ok": True, ...payload} on success, {"ok": False, "stage":
        "resolve"|"evaluate"} for probe-level misses so the caller can classify
        guard_detach vs guard_timeout without guessing from exception types.
        """

        try:
            resolved = self._request("DOM.resolveNode", {"backendNodeId": int(backend_node_id)})
        except (RuntimeError, OSError) as exc:
            return {"ok": False, "stage": "resolve", "error_type": type(exc).__name__}
        node = resolved.get("node") if isinstance(resolved, dict) else None
        object_id = str((node or {}).get("objectId") or "")
        if not object_id:
            return {"ok": False, "stage": "resolve", "error_type": "no_object_id"}
        try:
            call = self._request(
                "Runtime.callFunctionOn",
                {
                    "functionDeclaration": _GUARD_COLLECT_FUNCTION,
                    "objectId": object_id,
                    "arguments": [{"objectId": object_id}],
                    "returnByValue": True,
                    "awaitPromise": False,
                    "userGesture": False,
                },
            )
        except (RuntimeError, OSError) as exc:
            return {"ok": False, "stage": "evaluate", "error_type": type(exc).__name__}
        remote = call.get("result") if isinstance(call, dict) else None
        remote = remote if isinstance(remote, dict) else {}
        if isinstance(call, dict) and call.get("exceptionDetails"):
            return {"ok": False, "stage": "evaluate", "error_type": "evaluate_exception"}
        value = remote.get("value")
        if not isinstance(value, dict) or "ok" not in value:
            return {"ok": False, "stage": "evaluate", "error_type": "invalid_payload"}
        return value


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
        binding_coordinator: BrowserChannelBindingCoordinator | None = None,
        http_get_version_dict: Callable[[str], dict[str, Any]] | None = None,
        binding_policy: BindingPolicy | None = None,
        attest_fn: Callable[[str], AttestationVerdict] | None = None,
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
        # Hard-capped at the absolute ceiling regardless of configuration:
        # a single oversized frame can never buffer unbounded memory.
        self._max_frame_bytes = min(int(max_frame_bytes), HARD_CAP_CDP_MAX_FRAME_BYTES)
        self._ws_connect: Callable[[str], _WebSocketLike] = ws_connect or (
            lambda url: _default_ws_connect(url, max_frame_bytes=self._max_frame_bytes)
        )
        # S3a（DESIGN-20261005 v4 §4.3）：可选共享通道绑定；None ⇒ 行为与之前完全一致。
        self._binding_coordinator = binding_coordinator
        self._http_get_version_dict = http_get_version_dict or _default_http_get_version_dict
        # S3b（R3 attestation，S0 结论 ②）：policy 缺省 deny_real —— 直连入口零改动即
        # fail-closed；attest_fn 缺省走 host 侧 lsof→PID→ps 真机制（测试可注入 stub）。
        self._binding_policy = binding_policy or BindingPolicy.deny_real()
        self._attest_fn: Callable[[str], AttestationVerdict] = (
            attest_fn or (lambda url: attest_debug_url(url))
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
            # S3b attestation（S0 结论 ②）：绑定前 host 侧进程证据判定；deny-real 默认
            # fail-closed（shadow 模式只记录不拒绝）。先判后连——拒绝路径零连接成本。
            _verdict = self._attest_fn(self.debug_base_url)
            _allowed, _reason = self._binding_policy.check(_verdict)
            if not _allowed:
                raise RuntimeError(f"Browser channel attestation refused: {_reason}")
            _attest_logger.info("browser channel attestation [%s]: %s", self.__class__.__name__, _reason)
            # S3a：即将新建绑定（首绑或断线重连）⇒ 与共享协调器对身份。
            # /json/version 的 browser ws UUID 是浏览器进程级标识：两 host 若落在
            # 不同 Chrome 上，此处身份/attestation 比对失败 ⇒ 拒绝（no cross-instance drift）。
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

    def collect_guard_observation(self, physical_id: str) -> dict[str, Any]:
        """FR-1: probe one element's current semantic fingerprint.

        physical_id is the persisted snapshot identity form ("dom:<backend
        node id>"). Connection loss re-raises with the same degraded-channel
        semantics as capture() so the executor classifies it guard_timeout
        (fail-closed) rather than retrying on a dead socket.
        """

        raw = str(physical_id or "").strip()
        if not raw.startswith("dom:") or not raw[4:].isdigit():
            return {"ok": False, "stage": "resolve", "error_type": "invalid_physical_id"}
        with self._capture_lock:
            target = self._resolve_target()
            session = self._ensure_session(target)
            try:
                return session.collect_guard_observation(int(raw[4:]))
            except _CONNECTION_LOST_ERRORS as exc:
                diag = dict(getattr(session, "last_diag", {}) or {})
                mode = _classify_connection_loss(exc)
                self._drop_session()
                raise RuntimeError(
                    f"guard_channel_degraded[mode={mode}]; "
                    "CDP guard probe connection lost; dropped session for same-target reconnect"
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

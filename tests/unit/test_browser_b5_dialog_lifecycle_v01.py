"""B5 dialog lifecycle fix (TASK-009 2026-10-28, docs/design/20261028-task009-dialog-verdict.md §6).

Pins the three repair invariants against fake CDP websockets:

R1  a recv TIMEOUT is not a connection loss: the session (and its websocket)
    must survive on BOTH the observation host (capture) and the mutation
    actuator (dispatch/settle), because that live connection may be the only
    channel still able to handle a blocking dialog (verdict L1/L2/L7).
    frame_too_large (close 1009) and real transport breaks still drop.
R2  click is event-first: when Page.javascriptDialogOpening arrives while the
    click's Runtime.callFunctionOn response can never come (synchronous
    modal), the dispatch acknowledges with a dialog_opened boundary event and
    marks the dialog state instead of timing out and dropping the session.
    The early return is opt-in for click only (hover/settle semantics stay
    byte-identical).
R3  the dialog verb self-heals a False gate: one drain pass, then ONE blind
    handle. Chrome's "No dialog is showing" maps back to the same
    dialog_not_open contract error with zero side-effect commands; a success
    (page-initiated dialog the event drain never saw) completes the action.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator
from llm_loop.browser.cdp_host import CdpReadOnlyBrowserHost

_MUT_TARGET = {
    "id": "target-1",
    "type": "page",
    "url": "http://127.0.0.1/a",
    "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/target-1",
}
_OBS_TARGET = {
    "id": "TARGET-1",
    "type": "page",
    "url": "http://127.0.0.1:8903/",
    "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/TARGET-1",
}
_DIALOG_OPENING = {
    "method": "Page.javascriptDialogOpening",
    "params": {
        "type": "alert",
        "message": "LFL-ALERT",
        "url": "http://127.0.0.1/a",
        "hasBrowserHandler": True,
    },
}


def _attest_dedicated(url: str):  # noqa: ANN001, ANN202 - S3b test stub
    from llm_loop.browser.attestation import AttestationVerdict

    return AttestationVerdict(
        verdict="dedicated", user_data_dir="/tmp/attest-stub-profile",
        argv_sha256="stub" * 16, argv=(), detail="unit-test stub",
    )


def _mutation_actuator(ws) -> CdpBrowserMutationActuator:  # noqa: ANN001
    return CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id=_MUT_TARGET["id"],
        http_get_json=lambda url: json.loads(json.dumps([_MUT_TARGET])),
        ws_connect=lambda url: ws,
        attest_fn=_attest_dedicated,
    )


def _observation_host(ws) -> CdpReadOnlyBrowserHost:  # noqa: ANN001
    return CdpReadOnlyBrowserHost(
        "http://127.0.0.1:9222",
        target_id=_OBS_TARGET["id"],
        http_get_json=lambda url: json.loads(json.dumps([_OBS_TARGET])),
        ws_connect=lambda url: ws,
        attest_fn=_attest_dedicated,
    )


class _RecvRaisesWs:
    """Websocket whose recv always raises the configured exception."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.requests: list[dict[str, Any]] = []
        self.closed = False

    def send(self, payload: str) -> None:
        self.requests.append(json.loads(payload))

    def recv(self, timeout: float | None = None) -> str:  # noqa: ARG002
        raise self.exc

    def close(self) -> None:
        self.closed = True


class _ScriptedWs:
    """Fake CDP websocket: per-method canned behavior, manual pending queue.

    Behaviors (first match wins) are (method substring, payload substring)
    -> handler(request_id). Handlers append to self.pending; recv pops it or
    raises TimeoutError exactly like a quiet real socket.
    """

    def __init__(self, handlers: list[tuple[str, str, Any]]) -> None:
        self.handlers = handlers
        self.requests: list[dict[str, Any]] = []
        self.pending: list[str] = []
        self.closed = False

    def send(self, payload: str) -> None:
        req = json.loads(payload)
        self.requests.append(req)
        for method_part, payload_part, handler in self.handlers:
            if method_part in req.get("method", "") and payload_part in json.dumps(req.get("params", {})):
                handler(self, req)
                return
        self.pending.append(json.dumps({"id": req["id"], "result": {}}))

    def recv(self, timeout: float | None = None) -> str:  # noqa: ARG002
        if not self.pending:
            raise TimeoutError("no pending message")
        return self.pending.pop(0)

    def close(self) -> None:
        self.closed = True


def _respond(result: dict[str, Any] = None, error: dict[str, Any] = None):  # noqa: ANN001
    def handler(ws: _ScriptedWs, req: dict[str, Any]) -> None:
        message: dict[str, Any] = {"id": req["id"]}
        if error is not None:
            message["error"] = error
        else:
            message["result"] = result or {}
        ws.pending.append(json.dumps(message))

    return handler


def _emit_event_then_respond(event: dict[str, Any]):  # noqa: ANN001
    """Queue an unsolicited event AHEAD of this request's own response."""

    def handler(ws: _ScriptedWs, req: dict[str, Any]) -> None:
        ws.pending.append(json.dumps(event))
        ws.pending.append(json.dumps({"id": req["id"], "result": {}}))

    return handler


def _noop_handler(ws: _ScriptedWs, req: dict[str, Any]) -> None:  # noqa: ANN001, ARG001
    """Withhold any response (pure hang)."""

    return None


# ---------------------------------------------------------------------------
# R1: timeout keeps the session on every path.
# ---------------------------------------------------------------------------


def test_r1_observation_capture_timeout_keeps_session_and_socket() -> None:
    ws = _RecvRaisesWs(TimeoutError("timed out"))
    host = _observation_host(ws)
    with pytest.raises(RuntimeError, match=r"capture_channel_degraded\[mode=timeout\]") as excinfo:
        host.capture()
    assert "error_type=TimeoutError" in str(excinfo.value)
    # THE R1 invariant: the session and its websocket survive the timeout.
    assert host._session is not None
    assert ws.closed is False
    assert host.bound_target_id == _OBS_TARGET["id"]


def test_r1_mutation_click_recv_timeout_keeps_session_and_socket() -> None:
    # the pre-fix failure chain started exactly here: click -> callFunctionOn
    # hangs on the modal -> recv timeout -> (old) drop of the only dialog-
    # capable connection.
    ws = _ScriptedWs(
        [
            ("Runtime.callFunctionOn", "this.click()", _noop_handler),
            ("DOM.resolveNode", "", _respond({"object": {"objectId": "obj-1"}})),
        ]
    )
    actuator = _mutation_actuator(ws)
    with pytest.raises(RuntimeError, match="CDP mutation timed out; session kept"):
        actuator.dispatch(verb="click", physical_target="dom:7", args={})
    assert actuator._session is not None
    assert ws.closed is False
    assert actuator.bound_target_id == _MUT_TARGET["id"]
    # the click request itself did leave the wire (timeout, not a refusal)
    assert any(
        req["method"] == "Runtime.callFunctionOn" and "this.click()" in req["params"].get("functionDeclaration", "")
        for req in ws.requests
    )


def test_r1_mutation_settle_timeout_keeps_session_and_reports_unavailable() -> None:
    ws = _RecvRaisesWs(TimeoutError("timed out"))
    actuator = _mutation_actuator(ws)
    verdict = actuator.settle(physical_target="dom:7", mode="raf_baseline")
    assert verdict["verdict"] == "unavailable"
    assert verdict["reason"].startswith("timeout:")
    assert actuator._session is not None
    assert ws.closed is False


# ---------------------------------------------------------------------------
# R1 regression: frame_too_large / real transport breaks still drop.
# ---------------------------------------------------------------------------


def test_r1_observation_frame_limit_still_drops_session() -> None:
    ws = _RecvRaisesWs(ConnectionClosedError(Close(1009, "message too big"), None))
    host = _observation_host(ws)
    with pytest.raises(RuntimeError, match=r"capture_channel_degraded\[mode=frame_too_large\]"):
        host.capture()
    assert host._session is None
    assert ws.closed is True


def test_r1_observation_connection_break_still_drops_session() -> None:
    ws = _RecvRaisesWs(ConnectionClosedError(None, None))
    host = _observation_host(ws)
    with pytest.raises(RuntimeError, match="connection lost; dropped session"):
        host.capture()
    assert host._session is None
    assert ws.closed is True


def test_r1_observation_guard_connection_break_still_drops_session() -> None:
    ws = _RecvRaisesWs(ConnectionClosedError(None, None))
    host = _observation_host(ws)
    with pytest.raises(RuntimeError, match=r"guard_channel_degraded\[mode=connection\]"):
        host.collect_guard_observation("dom:5")
    assert host._session is None
    assert ws.closed is True


def test_r1_mutation_connection_break_still_drops_session() -> None:
    ws = _RecvRaisesWs(ConnectionClosedError(None, None))
    actuator = _mutation_actuator(ws)
    with pytest.raises(RuntimeError, match="CDP mutation connection lost; dropped session"):
        actuator.dispatch(verb="navigate", physical_target=None, args={"url": "http://127.0.0.1:8903/"})
    assert actuator._session is None
    assert ws.closed is True


def test_r1_mutation_frame_limit_still_drops_session() -> None:
    ws = _RecvRaisesWs(ConnectionClosedError(Close(1009, "message too big"), None))
    actuator = _mutation_actuator(ws)
    with pytest.raises(RuntimeError, match="CDP mutation connection lost; dropped session"):
        actuator.dispatch(verb="navigate", physical_target=None, args={"url": "http://127.0.0.1:8903/"})
    assert actuator._session is None
    assert ws.closed is True


# ---------------------------------------------------------------------------
# R2: click is event-first.
# ---------------------------------------------------------------------------

_DIALOG_OPENED_EVENT = {
    "event": "dialog_opened",
    "scope_ref": None,
    "detector": "Page.javascriptDialogOpening",
    "complete": False,
}


def _click_dialog_ws() -> tuple[_ScriptedWs, dict[str, int]]:
    """click() opens alert(): dialog event arrives, click response is withheld
    until the dialog is handled (then it lands late with a stale id)."""
    state: dict[str, int] = {}

    def click_handler(ws: _ScriptedWs, req: dict[str, Any]) -> None:
        state["click_id"] = req["id"]
        ws.pending.append(json.dumps(_DIALOG_OPENING))

    def handle_handler(ws: _ScriptedWs, req: dict[str, Any]) -> None:
        ws.pending.append(json.dumps({"id": req["id"], "result": {}}))
        # dialog handled -> page script resumes -> the withheld click response
        # finally arrives (stale id: it belongs to the click request)
        if "click_id" in state:
            ws.pending.append(json.dumps({"id": state["click_id"], "result": {"result": {"type": "undefined"}}}))

    ws = _ScriptedWs(
        [
            ("Runtime.callFunctionOn", "this.click()", click_handler),
            ("DOM.resolveNode", "", _respond({"object": {"objectId": "obj-1"}})),
            ("Page.handleJavaScriptDialog", "", handle_handler),
        ]
    )
    return ws, state


def test_r2_click_returns_acknowledged_with_dialog_opened_and_keeps_session() -> None:
    ws, _state = _click_dialog_ws()
    actuator = _mutation_actuator(ws)
    result = actuator.dispatch(verb="click", physical_target="dom:7", args={})
    assert result.acknowledged is True
    assert _DIALOG_OPENED_EVENT in [dict(item) for item in result.boundary_events]
    assert actuator._dialog_open is True
    assert actuator._dialog_detail == _DIALOG_OPENING["params"]
    # R1+R2: no drop, no second click attempt; exactly enable+resolve+click
    assert [req["method"] for req in ws.requests] == [
        "Page.enable",
        "DOM.resolveNode",
        "Runtime.callFunctionOn",
    ]
    assert actuator._session is not None


def test_r2_dialog_accept_on_same_session_skips_late_click_response() -> None:
    ws, _state = _click_dialog_ws()
    actuator = _mutation_actuator(ws)
    actuator.dispatch(verb="click", physical_target="dom:7", args={})
    accept = actuator.dispatch(verb="dialog", physical_target=None, args={"action": "accept"})
    assert accept.acknowledged is True
    assert actuator._dialog_open is False
    assert actuator._dialog_detail is None
    # the late (stale-id) click response is queued ahead; a later verb must
    # silently skip it - the session stays usable (verdict L1 property).
    actuator.dispatch(verb="press_key", physical_target=None, args={"keys": "Escape"})
    assert ws.requests[-1]["method"] == "Input.dispatchKeyEvent"
    assert ws.closed is False
    assert [req["method"] for req in ws.requests].count("Page.handleJavaScriptDialog") == 1


def test_r2_early_return_is_click_only_hover_still_waits_for_response() -> None:
    # a dialog event interleaved with hover's rect call must NOT abort the
    # hover send: the event is buffered and surfaces via the legacy tail
    # drain (boundary_events + dialog state), while the hover completes.
    def rect_handler(ws: _ScriptedWs, req: dict[str, Any]) -> None:
        ws.pending.append(json.dumps(_DIALOG_OPENING))
        ws.pending.append(
            json.dumps({"id": req["id"], "result": {"result": {"value": {"x": 10.0, "y": 10.0, "w": 50.0, "h": 20.0}}}})
        )

    ws = _ScriptedWs(
        [
            ("Runtime.callFunctionOn", "scrollIntoView", rect_handler),
            ("DOM.resolveNode", "", _respond({"object": {"objectId": "obj-1"}})),
        ]
    )
    actuator = _mutation_actuator(ws)
    result = actuator.dispatch(verb="hover", physical_target="dom:7", args={})
    assert result.acknowledged is True
    # hover completed: the pointer event was actually dispatched after the rect
    assert [req["method"] for req in ws.requests][-1] == "Input.dispatchMouseEvent"
    # the dialog event reached the model through the tail drain, not by
    # aborting the send (which would have skipped the pointer dispatch)
    assert _DIALOG_OPENED_EVENT in [dict(item) for item in result.boundary_events]
    assert actuator._dialog_open is True


# ---------------------------------------------------------------------------
# R3: dialog gate self-heal (one drain, then one blind handle).
# ---------------------------------------------------------------------------


def test_r3_blind_handle_succeeds_for_unobserved_open_dialog() -> None:
    # page-initiated dialog: the opening event fired before this session ever
    # enabled Page.enable, so no drain can observe it - only the blind handle
    # can answer the verb (the reason R3 exists).
    ws = _ScriptedWs([("Page.handleJavaScriptDialog", "", _respond({}))])
    actuator = _mutation_actuator(ws)
    result = actuator.dispatch(verb="dialog", physical_target=None, args={"action": "accept"})
    assert result.acknowledged is True
    assert actuator._dialog_open is False
    assert [req["method"] for req in ws.requests] == [
        "Page.enable",
        "Page.handleJavaScriptDialog",
    ]
    assert ws.closed is False


def test_r3_no_dialog_maps_error_to_dialog_not_open_with_single_command() -> None:
    ws = _ScriptedWs(
        [("Page.handleJavaScriptDialog", "", _respond(error={"code": -32603, "message": "No dialog is showing"}))]
    )
    actuator = _mutation_actuator(ws)
    # establish the session first so the probe window is isolated
    actuator.dispatch(verb="press_key", physical_target=None, args={"keys": "Escape"})
    mark = len(ws.requests)
    with pytest.raises(RuntimeError, match="dialog_not_open"):
        actuator.dispatch(verb="dialog", physical_target=None, args={"action": "dismiss"})
    # zero-side-effect hard requirement: exactly ONE command in the probe
    # window - the handle itself. No Runtime.evaluate, no DOM.*, no retry.
    assert [req["method"] for req in ws.requests[mark:]] == ["Page.handleJavaScriptDialog"]
    assert actuator._session is not None
    assert ws.closed is False


def test_r3_drain_heal_path_still_gates_without_blind_send() -> None:
    # drain DOES reveal the opening event (it arrived between requests):
    # state heals from the drain and the normal branch sends the handle.
    ws = _ScriptedWs(
        [
            ("Page.handleJavaScriptDialog", "", _respond({})),
            ("Input.dispatchKeyEvent", "", _emit_event_then_respond(_DIALOG_OPENING)),
        ]
    )
    actuator = _mutation_actuator(ws)
    actuator.dispatch(verb="press_key", physical_target=None, args={"keys": "Escape"})
    assert actuator._dialog_open is True
    mark = len(ws.requests)
    result = actuator.dispatch(verb="dialog", physical_target=None, args={"action": "accept"})
    assert result.acknowledged is True
    # exactly one handle total (the normal branch - the drain pass sent none)
    assert [req["method"] for req in ws.requests[mark:]] == ["Page.handleJavaScriptDialog"]


# ---------------------------------------------------------------------------
# R2 end-to-end at the adapter / browser_operate tool layer.
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = json.loads((_ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8"))


class _CountingBackend:
    """Capture backend that counts calls (pre- vs post-dispatch windows)."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = json.loads(json.dumps(raw))
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        return json.loads(json.dumps(self.raw))


class _BoundaryActuator:
    """Stub actuator whose dispatch acknowledgement may carry boundary events."""

    def __init__(self, boundary_events: tuple[dict[str, Any], ...] = ()) -> None:
        self.boundary_events = boundary_events
        self.calls: list[dict[str, Any]] = []

    def dispatch(self, **kwargs: Any):  # noqa: ANN003, ANN202
        from llm_loop.browser.action import BrowserDispatchResult

        self.calls.append(kwargs)
        return BrowserDispatchResult(
            acknowledged=True,
            boundary_events=self.boundary_events,
            completeness_reasons=("boundary_detector_non_exhaustive",),
        )


def _click_action(first: dict[str, Any], target: dict[str, Any], action_id: str) -> dict[str, Any]:
    return {
        "schema": "smc.semantic_action.v0.1",
        "domain": "browser",
        "scope_ref": target["scope_ref"],
        "action_id": action_id,
        "verb": "click",
        "target_id": target["id"],
        "args": {},
        "args_normalization": {"applied": False, "rule": None},
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": first["snapshot"]["snapshot_id"],
        "version_scope": "object",
        "version_precondition": "required",
    }


def _adapter_stack(tmp_path: Path, actuator: _BoundaryActuator, backend: _CountingBackend):  # noqa: ANN202
    from llm_loop.browser.action import BrowserActionAdapter, BrowserActionReceiptStore
    from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore

    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    first = perception.snapshot("s1", _FIXTURES["base"])
    target = next(
        obj for obj in first["objects"] if (obj.get("attributes") or {}).get("name") == "Submit"
    )
    adapter = BrowserActionAdapter(
        perception=perception,
        receipt_store=BrowserActionReceiptStore(tmp_path / "actions"),
        capture_backend=backend,
        actuator=actuator,
    )
    return perception, first, target, adapter


def test_r2_adapter_skips_post_capture_when_dispatch_opened_dialog(tmp_path: Path) -> None:
    actuator = _BoundaryActuator(
        boundary_events=(
            {
                "event": "dialog_opened",
                "scope_ref": None,
                "detector": "Page.javascriptDialogOpening",
                "complete": False,
            },
        )
    )
    backend = _CountingBackend(_FIXTURES["base"])
    _, first, target, adapter = _adapter_stack(tmp_path, actuator, backend)
    receipt = adapter.execute("s1", _click_action(first, target, "sact-b5-dialogclick-skip-0001"))
    assert receipt["status"] == "ok"
    # honest skip annotation (additive field) + completeness reason
    assert receipt["post_capture"] == {"skipped": True, "reason": "dialog_open"}
    assert "post_capture_skipped:dialog_open" in receipt["completeness"]["reasons"]
    # pre-dispatch capture ran exactly once; the post-capture never fired
    assert backend.calls == 1


def test_r2_adapter_post_capture_unchanged_without_dialog_boundary(tmp_path: Path) -> None:
    actuator = _BoundaryActuator(boundary_events=())
    backend = _CountingBackend(_FIXTURES["base"])
    _, first, target, adapter = _adapter_stack(tmp_path, actuator, backend)
    receipt = adapter.execute("s1", _click_action(first, target, "sact-b5-plainclick-post-0001"))
    assert receipt["status"] == "ok"
    assert "post_capture" not in receipt  # field exists only on the skip path
    assert "post_capture_skipped:dialog_open" not in receipt["completeness"]["reasons"]
    assert backend.calls == 2  # pre-dispatch + post-dispatch, unchanged behavior


class _FrozenBackend:
    """Backend whose renderer is held by a modal: capture always times out,
    but the browser-process probe channel stays alive (light-mode path)."""

    def __init__(self) -> None:
        self.capture_calls = 0

    def capture(self) -> dict[str, Any]:
        self.capture_calls += 1
        raise RuntimeError(
            "capture_channel_degraded[mode=timeout]; CDP observation timed out; "
            "session kept (dialog-capable); error_type=TimeoutError"
        )

    def probe_page_target(self) -> dict[str, Any]:
        return {"target_id": "TARGET-1", "url": "http://127.0.0.1:8903/", "type": "page"}


def _operate_tool(tmp_path: Path, backend: Any, actuator: Any):  # noqa: ANN202
    from llm_loop.browser.action import BrowserActionAdapter, BrowserActionReceiptStore
    from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
    from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
    from llm_loop.tools.builtin.browser_semantic_operation import (
        BrowserSemanticOperationReceiptStore,
        BrowserSemanticOperationTool,
    )

    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=BrowserActionReceiptStore(tmp_path / "actions"),
        capture_backend=backend,
        actuator=actuator,
    )
    execute = BrowserSemanticExecuteTool(
        perception=perception, action_adapter=action, session_id_getter=lambda: "s1"
    )
    tool = BrowserSemanticOperationTool(
        perception=perception,
        capture_backend=backend,
        semantic_execute=execute,
        receipt_store=BrowserSemanticOperationReceiptStore(tmp_path / "operation_receipts"),
        session_id_getter=lambda: "s1",
    )
    return perception, tool


def test_r2_operate_dialog_grounds_from_latest_world_on_frozen_page(tmp_path: Path) -> None:
    # session already observed this page once (world persisted); then the
    # page froze on a modal dialog. browser_operate do=dialog must ground via
    # the persisted world instead of dying on the fresh capture.

    backend = _FrozenBackend()
    actuator = _BoundaryActuator()
    perception, tool = _operate_tool(tmp_path, backend, actuator)
    first = perception.snapshot("s1", _FIXTURES["base"])  # the prior world
    assert perception.latest_page_resource_ref("s1") == first["resource_ref"]

    result = tool.execute(do="dialog", action="accept")
    payload = json.loads(result.content)
    assert payload["status"] == "completed", result.content[:1500]
    # the dialog verb actually reached the actuator (grounding did not block it)
    assert [call["verb"] for call in actuator.calls] == ["dialog"]
    # three fresh captures were attempted and all degraded honestly without
    # blocking the verb: operate grounding, adapter pre-capture (light-mode
    # probe fallback), adapter post-capture (post_reasons only).
    assert backend.capture_calls == 3


def test_r2_operate_dialog_without_prior_world_keeps_original_error(tmp_path: Path) -> None:
    # "no observation, no mutation": with an EMPTY store the frozen-page
    # fallback has nothing to ground against, so the original capture failure
    # surfaces verbatim (no fabricated world, no auto-observation).
    backend = _FrozenBackend()
    actuator = _BoundaryActuator()
    _, tool = _operate_tool(tmp_path, backend, actuator)

    result = tool.execute(do="dialog", action="accept")
    assert result.status.value == "error"
    assert "capture_channel_degraded[mode=timeout]" in result.content
    assert actuator.calls == []  # never dispatched

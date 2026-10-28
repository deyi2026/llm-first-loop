"""M2-A browser tooling v01: B3 press_key / B4 hover / B5 dialog / B6 download.

Each capability is exercised on the REAL production layers (policy functions,
adapter execute, cdp actuator dispatch, browser_operate tool) with both a
positive and a negative case; negatives assert the deterministic code AND the
absence of side effects (no dispatch / no CDP method / no file written) -
RULE-AI-35 discipline: a guard only counts as effective when the rejected
input is actually observed being rejected.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from llm_loop.browser.action import (
    BrowserActionAdapter,
    BrowserActionReceiptStore,
    BrowserDispatchResult,
    press_key_policy_error,
)
from llm_loop.browser.cdp_action_host import (
    CdpBrowserMutationActuator,
    key_events_for_chord,
)
from llm_loop.browser.download_contract import (
    download_path_policy_error,
    session_download_dir,
)
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
from llm_loop.tools.builtin.browser_semantic_operation import (
    BrowserSemanticOperationReceiptStore,
    BrowserSemanticOperationTool,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)


def _attest_dedicated(url: str):  # noqa: ANN001, ANN202 - S3b test stub
    from llm_loop.browser.attestation import AttestationVerdict

    return AttestationVerdict(
        verdict="dedicated", user_data_dir="/tmp/attest-stub-profile",
        argv_sha256="stub" * 16, argv=(), detail="unit-test stub",
    )


class _Backend:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = json.loads(json.dumps(raw))
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        return json.loads(json.dumps(self.raw))


class _Actuator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def dispatch(self, **kwargs: Any) -> BrowserDispatchResult:
        self.calls.append(kwargs)
        return BrowserDispatchResult(
            acknowledged=True,
            boundary_events=(),
            completeness_reasons=("boundary_detector_non_exhaustive",),
        )


def _tool_stack(tmp_path: Path):
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    backend = _Backend(FIXTURES["base"])
    actuator = _Actuator()
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=BrowserActionReceiptStore(tmp_path / "actions"),
        capture_backend=backend,
        actuator=actuator,
    )
    execute = BrowserSemanticExecuteTool(
        perception=perception, action_adapter=action, session_id_getter=lambda: "s1"
    )
    operation = BrowserSemanticOperationTool(
        perception=perception,
        capture_backend=backend,
        semantic_execute=execute,
        receipt_store=BrowserSemanticOperationReceiptStore(tmp_path / "operation_receipts"),
        session_id_getter=lambda: "s1",
    )
    return operation, actuator


class _RecordingWs:
    """Fake CDP websocket recording requests; replies with per-method results."""

    def __init__(
        self,
        results: dict[str, Any] | None = None,
        events: list[dict[str, Any]] | None = None,
    ) -> None:
        self.requests: list[dict[str, Any]] = []
        self.pending: list[str] = []
        self.results = results or {}
        self.events = list(events or [])

    def send(self, payload: str) -> None:
        req = json.loads(payload)
        self.requests.append(req)
        result = self.results.get(req["method"], {})
        self.pending.append(json.dumps({"id": req["id"], "result": result}))
        # Unsolicited events are appended AFTER this response: the current
        # send's recv loop matches its own response and returns, and the next
        # send's recv loop drains the leftover event into the session buffer -
        # exactly how a real browser interleaves events between requests.
        while self.events:
            self.pending.append(json.dumps(self.events.pop(0)))

    def recv(self, timeout: float | None = None) -> str:  # noqa: ARG002
        if not self.pending:
            raise TimeoutError("no pending message")
        return self.pending.pop(0)

    def close(self) -> None:
        return None


def _cdp_host(ws: _RecordingWs) -> CdpBrowserMutationActuator:
    targets = [
        {
            "id": "target-1",
            "type": "page",
            "url": "http://127.0.0.1/a",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/target-1",
        }
    ]
    return CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="target-1",
        http_get_json=lambda url: json.loads(json.dumps(targets)),
        ws_connect=lambda url: ws,
        attest_fn=_attest_dedicated,
    )


# ---------------------------------------------------------------------------
# A. B3 press_key - shared chord policy (single source of truth).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keys",
    [
        "Meta+W", "Meta+Q", "Meta+T", "Meta+N", "Meta+S", "Meta+P", "Meta+H", "Meta+M",
        "Meta+Backtick", "Meta+`", "Meta+Tab", "Meta+Space",
        "Ctrl+Meta+Q", "Meta+Control+Q", "Meta+Shift+Q", "Cmd+W",
        "Escape+Meta", "Meta+Escape", "Meta+Alt+Escape",
    ],
)
def test_b3_blacklisted_chords_rejected_by_shared_policy(keys: str) -> None:
    assert press_key_policy_error(keys) == "key_not_allowed"


@pytest.mark.parametrize(
    "keys",
    ["Enter", "enter", "Escape", "escape", "Tab", "Space", "ArrowDown", "F5",
     "Meta+A", "Control+C", "Shift+Tab", "Alt+F4", "Backspace", "Delete", "a", "1"],
)
def test_b3_ordinary_chords_pass_the_shared_policy(keys: str) -> None:
    assert press_key_policy_error(keys) is None


@pytest.mark.parametrize("keys", ["", "   ", "Meta+", "Meta+Shift", "A+B", "Meta+Meta+A", None, 123, "x" * 33])
def test_b3_malformed_chords_get_key_args_invalid(keys: Any) -> None:
    assert press_key_policy_error(keys) == "key_args_invalid"


def test_b3_enter_chord_builds_exactly_one_keydown_keyup_pair() -> None:
    events = key_events_for_chord("Enter")
    assert [event["type"] for event in events] == ["keyDown", "keyUp"]
    for event in events:
        assert event["key"] == "enter"
        assert event["code"] == "Enter"
        assert event["windowsVirtualKeyCode"] == 13
    assert events[0]["text"] == "\r"  # Enter default action (form submit) parity
    assert "text" not in events[1]


def test_b3_meta_a_chord_wraps_the_pair_with_modifier_events() -> None:
    events = key_events_for_chord("Meta+A")
    assert [event["type"] for event in events] == ["keyDown", "keyDown", "keyUp", "keyUp"]
    assert events[0]["key"] == "Meta" and events[0]["modifiers"] == 0
    assert events[1]["key"] == "a" and events[1]["modifiers"] == 4  # Meta bit
    assert events[2]["key"] == "a" and events[2]["modifiers"] == 4
    assert events[3]["key"] == "Meta" and events[3]["modifiers"] == 4


# ---------------------------------------------------------------------------
# B. B3 actuator layer: dispatchKeyEvent only, never a script channel.
# ---------------------------------------------------------------------------


def test_b3_actuator_press_key_enter_dispatches_paired_events_without_object_resolution() -> None:
    ws = _RecordingWs()
    host = _cdp_host(ws)
    result = host.dispatch(verb="press_key", physical_target=None, args={"keys": "Enter"})
    assert result.acknowledged is True
    assert [req["method"] for req in ws.requests] == [
        "Page.enable",
        "Input.dispatchKeyEvent",
        "Input.dispatchKeyEvent",
    ]
    # page-level verb: no DOM.resolveNode / Runtime.callFunctionOn at all
    assert not any(req["method"] in {"DOM.resolveNode", "Runtime.callFunctionOn"} for req in ws.requests)
    params = [req["params"] for req in ws.requests if req["method"] == "Input.dispatchKeyEvent"]
    assert [p["type"] for p in params] == ["keyDown", "keyUp"]
    assert params[0]["text"] == "\r"


def test_b3_actuator_blacklisted_chord_raises_with_zero_key_dispatch_and_tab_intact() -> None:
    ws = _RecordingWs()
    host = _cdp_host(ws)
    with pytest.raises(RuntimeError, match="key_not_allowed"):
        host.dispatch(verb="press_key", physical_target=None, args={"keys": "Meta+W"})
    # U5 negative: the tab survives - nothing beyond the session's Page.enable
    # was ever sent; in particular zero Input.dispatchKeyEvent.
    assert not any(req["method"] == "Input.dispatchKeyEvent" for req in ws.requests)
    assert [req["method"] for req in ws.requests] == ["Page.enable"]


# ---------------------------------------------------------------------------
# C. B3 tool layer (browser_operate do=press_key).
# ---------------------------------------------------------------------------


def test_b3_operate_press_key_receipt_ok_and_page_scoped(tmp_path: Path) -> None:
    tool, actuator = _tool_stack(tmp_path)
    result = tool.execute(do="press_key", keys="Enter")
    assert result.status.value == "success"
    receipt = json.loads(result.content)
    assert receipt["status"] == "completed"
    assert [call["verb"] for call in actuator.calls] == ["press_key"]
    # page-scoped: no physical dom: target is passed to the actuator
    assert actuator.calls[0]["physical_target"] is None
    assert actuator.calls[0]["args"] == {"keys": "Enter"}


def test_b3_operate_meta_w_rejected_at_compile_time_with_zero_dispatch(tmp_path: Path) -> None:
    tool, actuator = _tool_stack(tmp_path)
    for keys in ("Meta+W", "Meta+Q"):
        result = tool.execute(do="press_key", keys=keys)
        assert result.status.value == "failure", keys
        assert "key_not_allowed" in result.content, keys
        # the tab is untouched: not even a capture/dispatch happened
        assert actuator.calls == [], keys


def test_b3_operate_malformed_keys_rejected_with_zero_dispatch(tmp_path: Path) -> None:
    tool, actuator = _tool_stack(tmp_path)
    result = tool.execute(do="press_key", keys="A+B")
    assert result.status.value == "failure"
    assert "key_args_invalid" in result.content
    assert actuator.calls == []


# ---------------------------------------------------------------------------
# D. B4 hover - actuator layer: one mouseMoved, never a click.
# ---------------------------------------------------------------------------

_HOVER_RECT = {"x": 100.0, "y": 50.0, "w": 200.0, "h": 60.0}


def _hover_ws(rect: dict[str, float]) -> _RecordingWs:
    return _RecordingWs(
        results={
            "DOM.resolveNode": {"object": {"objectId": "obj-1"}},
            "Runtime.callFunctionOn": {"result": {"value": rect}},
        }
    )


def test_b4_actuator_hover_moves_pointer_to_center_once_and_never_clicks() -> None:
    ws = _hover_ws(_HOVER_RECT)
    host = _cdp_host(ws)
    result = host.dispatch(verb="hover", physical_target="dom:7", args={})
    assert result.acknowledged is True
    assert [req["method"] for req in ws.requests] == [
        "Page.enable",
        "DOM.resolveNode",
        "Runtime.callFunctionOn",
        "Input.dispatchMouseEvent",
    ]
    rect_call = next(req["params"] for req in ws.requests if req["method"] == "Runtime.callFunctionOn")
    # scrollIntoView precedes the rect read in the same fixed predicate
    assert "scrollIntoView" in rect_call["functionDeclaration"]
    assert "getBoundingClientRect" in rect_call["functionDeclaration"]
    moves = [req["params"] for req in ws.requests if req["method"] == "Input.dispatchMouseEvent"]
    assert len(moves) == 1
    assert moves[0] == {
        "type": "mouseMoved",  # hover only: never mousePressed/mouseReleased
        "x": 200.0,  # x + w/2, CSS px
        "y": 80.0,  # y + h/2, CSS px
        "button": "none",
        "pointerType": "mouse",
    }


@pytest.mark.parametrize("rect", [{"x": 0, "y": 0, "w": 0, "h": 0}, {"x": 0, "y": 0, "w": 120, "h": 0}])
def test_b4_actuator_zero_area_element_rejects_before_any_pointer_event(rect: dict[str, float]) -> None:
    ws = _hover_ws(rect)
    host = _cdp_host(ws)
    with pytest.raises(RuntimeError, match="element_not_visible"):
        host.dispatch(verb="hover", physical_target="dom:7", args={})
    # zero pointer events: the only CDP traffic is session + resolve + measure
    assert [req["method"] for req in ws.requests] == [
        "Page.enable",
        "DOM.resolveNode",
        "Runtime.callFunctionOn",
    ]
    assert not any(req["method"] == "Input.dispatchMouseEvent" for req in ws.requests)


# ---------------------------------------------------------------------------
# E. B4 hover - tool layer (browser_operate do=hover).
# ---------------------------------------------------------------------------


def _raw_with_menu_shown() -> list[dict[str, Any]]:
    """Capture sequence: grounding + adapter before-capture see the same page;
    the post-dispatch capture sees the hover-menu node appear."""
    before = json.loads(json.dumps(FIXTURES["base"]))
    after = json.loads(json.dumps(FIXTURES["base"]))
    after["dom"]["nodes"].append(
        {
            "physical_id": "n-menu",
            "parent_id": "n-root",
            "frame_token": None,
            "kind": "menu",
            "attributes": {"role": "menu", "name": "Hover menu", "tag": "div"},
            "state": {"exists": True, "enabled": True, "visible": True, "editable": False},
        }
    )
    return [before, json.loads(json.dumps(before)), after]


class _SequenceBackend:
    def __init__(self, captures: list[dict[str, Any]]) -> None:
        self.captures = [json.loads(json.dumps(item)) for item in captures]
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        if len(self.captures) == 1:
            return json.loads(json.dumps(self.captures[0]))
        return json.loads(json.dumps(self.captures.pop(0)))


def test_b4_operate_hover_receipt_shows_created_nodes_in_diff(tmp_path: Path) -> None:
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    backend = _SequenceBackend(_raw_with_menu_shown())
    actuator = _Actuator()
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
    result = tool.execute(do="hover", target={"kind": "button", "name": "Submit"})
    assert result.status.value == "success"
    receipt = json.loads(result.content)
    assert receipt["status"] == "completed"
    assert [call["verb"] for call in actuator.calls] == ["hover"]
    assert actuator.calls[0]["args"] == {}
    # hover-positive acceptance: the post-dispatch snapshot diff shows the
    # newly appeared hover-menu node through the real perception pipeline.
    assert receipt["delta"]["counts"]["created"] == 1
    assert receipt["delta"]["comparable"] is True


def test_b4_operate_hover_element_not_visible_surfaces_stable_code(tmp_path: Path) -> None:
    from llm_loop.browser.cdp_action_host import _ActuatorContractError

    class _RejectingActuator:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def dispatch(self, **kwargs: Any) -> BrowserDispatchResult:
            self.calls.append(kwargs)
            raise _ActuatorContractError("element_not_visible")

    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    backend = _Backend(FIXTURES["base"])
    actuator = _RejectingActuator()
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
    result = tool.execute(do="hover", target={"kind": "button", "name": "Submit"})
    assert result.status.value == "success"  # the compact receipt is returned
    receipt = json.loads(result.content)
    assert receipt["status"] == "halted"
    assert receipt["reject_reason"] == "element_not_visible"
    assert len(actuator.calls) == 1  # one rejected dispatch attempt, no retry


# ---------------------------------------------------------------------------
# F. B5 dialog - actuator layer: state-gated, never a blind send.
# ---------------------------------------------------------------------------

_DIALOG_OPENING_EVENT = {
    "method": "Page.javascriptDialogOpening",
    "params": {"type": "alert", "message": "hello", "url": "http://127.0.0.1/a", "defaultPrompt": ""},
}


def test_b5_actuator_dialog_opened_via_event_then_accept_sends_handle_and_clears() -> None:
    ws = _RecordingWs(events=[dict(_DIALOG_OPENING_EVENT)])
    host = _cdp_host(ws)
    # a trigger action (B3 Enter) drains the queued javascriptDialogOpening
    # event into both the boundary receipt and the actuator's dialog state
    trigger = host.dispatch(verb="press_key", physical_target=None, args={"keys": "Enter"})
    assert {"event": "dialog_opened", "scope_ref": None, "detector": "Page.javascriptDialogOpening", "complete": False} in [
        dict(item) for item in trigger.boundary_events
    ]
    assert host._dialog_open is True
    # accept the blocking dialog; the page script then continues (session alive)
    result = host.dispatch(verb="dialog", physical_target=None, args={"action": "accept"})
    assert result.acknowledged is True
    handles = [req for req in ws.requests if req["method"] == "Page.handleJavaScriptDialog"]
    assert len(handles) == 1
    assert handles[0]["params"] == {"accept": True}
    assert host._dialog_open is False
    # session still usable after accept: a subsequent key press dispatches fine
    host.dispatch(verb="press_key", physical_target=None, args={"keys": "Escape"})
    assert ws.requests[-1]["method"] == "Input.dispatchKeyEvent"


def test_b5_actuator_dialog_without_open_dialog_rejects_before_any_traffic() -> None:
    ws = _RecordingWs()
    host = _cdp_host(ws)
    with pytest.raises(RuntimeError, match="dialog_not_open"):
        host.dispatch(verb="dialog", physical_target=None, args={"action": "accept"})
    # deterministic rejection BEFORE _ensure_session: not even a websocket
    # connection was opened - zero CDP of any kind, in particular no
    # Page.handleJavaScriptDialog (never a blind send).
    assert ws.requests == []
    # and the tab is untouched: the page target still resolves
    assert host.bound_target_id == ""


def test_b5_actuator_dialog_state_not_reusable_after_accept() -> None:
    ws = _RecordingWs(events=[dict(_DIALOG_OPENING_EVENT)])
    host = _cdp_host(ws)
    host.dispatch(verb="press_key", physical_target=None, args={"keys": "Enter"})
    host.dispatch(verb="dialog", physical_target=None, args={"action": "dismiss"})
    # the second dialog call must not blind-send: state was cleared
    with pytest.raises(RuntimeError, match="dialog_not_open"):
        host.dispatch(verb="dialog", physical_target=None, args={"action": "dismiss"})
    assert [req["method"] for req in ws.requests].count("Page.handleJavaScriptDialog") == 1


# ---------------------------------------------------------------------------
# G. B5 dialog - tool layer (browser_operate do=dialog).
# ---------------------------------------------------------------------------


def test_b5_operate_dialog_accept_receipt_ok_and_page_scoped(tmp_path: Path) -> None:
    tool, actuator = _tool_stack(tmp_path)
    result = tool.execute(do="dialog", action="accept")
    assert result.status.value == "success"
    receipt = json.loads(result.content)
    assert receipt["status"] == "completed"
    assert [call["verb"] for call in actuator.calls] == ["dialog"]
    assert actuator.calls[0]["args"] == {"action": "accept"}
    assert actuator.calls[0]["physical_target"] is None


def test_b5_operate_dialog_invalid_action_rejected_at_compile_time(tmp_path: Path) -> None:
    tool, actuator = _tool_stack(tmp_path)
    result = tool.execute(do="dialog", action="ok")
    assert result.status.value == "failure"
    assert "dialog_action_invalid" in result.content
    assert actuator.calls == []


def test_b5_operate_dialog_not_open_surfaces_code_and_guidance(tmp_path: Path) -> None:
    from llm_loop.browser.cdp_action_host import _ActuatorContractError

    class _DialogClosedActuator:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def dispatch(self, **kwargs: Any) -> BrowserDispatchResult:
            self.calls.append(kwargs)
            raise _ActuatorContractError("dialog_not_open")

    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    backend = _Backend(FIXTURES["base"])
    actuator = _DialogClosedActuator()
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
    result = tool.execute(do="dialog", action="accept")
    receipt = json.loads(result.content)
    assert receipt["status"] == "halted"
    assert receipt["reject_reason"] == "dialog_not_open"
    # §5.1 guidance: the model gets an actionable next step, not a bare code
    assert "guidance" in receipt and "dialog_opened" in receipt["guidance"]
    assert len(actuator.calls) == 1  # single attempt, no automatic retry


# ---------------------------------------------------------------------------
# H. B6 download - session dir + path policy (pure contract layer).
# ---------------------------------------------------------------------------


def test_b6_session_download_dir_is_session_fenced_and_deterministic(tmp_path: Path) -> None:
    a = session_download_dir(str(tmp_path), "s1")
    b = session_download_dir(str(tmp_path), "s1")
    c = session_download_dir(str(tmp_path), "s2")
    assert a == b and a != c
    assert a.startswith(str(tmp_path))
    assert a.endswith("downloads")
    # session identity never appears in the clear
    assert "s1" not in a


def test_b6_path_policy_rejects_traversal_and_symlink_escape(tmp_path: Path) -> None:
    download_dir = tmp_path / "fenced" / "downloads"
    download_dir.mkdir(parents=True)
    assert download_path_policy_error(str(download_dir), "report.pdf") is None
    assert download_path_policy_error(str(download_dir), "../../evil.sh") == "path_not_allowed"
    assert download_path_policy_error(str(download_dir), "/etc/passwd") == "path_not_allowed"
    assert download_path_policy_error(str(download_dir), "") == "download_filename_invalid"
    assert download_path_policy_error(None, "a.bin") == "download_dir_unconfigured"
    # symlink escape: a link planted INSIDE the fenced dir pointing outside
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"sentinel")
    (download_dir / "escape.bin").symlink_to(outside)
    assert download_path_policy_error(str(download_dir), "escape.bin") == "path_not_allowed"


# ---------------------------------------------------------------------------
# I. B6 actuator: setDownloadBehavior pinning + event state + containment.
# ---------------------------------------------------------------------------


def _download_ws(tmp_path: Path, filename: str, *, state: str = "completed") -> _RecordingWs:
    events = [
        {
            "method": "Page.downloadWillBegin",
            "params": {
                "frameId": "f1",
                "guid": "dl-1",
                "url": "https://example.invalid/file.bin",
                "suggestedFilename": filename,
            },
        },
        {
            "method": "Page.downloadProgress",
            "params": {"guid": "dl-1", "totalBytes": 1024, "receivedBytes": 1024, "state": state},
        },
    ]
    ws = _RecordingWs(events=events)
    return ws


def _download_host(ws: _RecordingWs, download_dir: str) -> CdpBrowserMutationActuator:
    targets = [
        {
            "id": "target-1",
            "type": "page",
            "url": "http://127.0.0.1/a",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/target-1",
        }
    ]
    return CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="target-1",
        http_get_json=lambda url: json.loads(json.dumps(targets)),
        ws_connect=lambda url: ws,
        attest_fn=_attest_dedicated,
        download_dir_provider=lambda: download_dir,
    )


def test_b6_actuator_pins_session_dir_and_tracks_completion_via_events(tmp_path: Path) -> None:
    download_dir = str(tmp_path / "fenced" / "downloads")
    payload = b"x" * (1024 * 1024)  # 1MB acceptance-size file
    Path(download_dir).mkdir(parents=True, exist_ok=True)
    (Path(download_dir) / "file.bin").write_bytes(payload)
    ws = _download_ws(tmp_path, "file.bin")
    host = _download_host(ws, download_dir)
    # a trigger dispatch drains both download events into the state machine
    host.dispatch(verb="press_key", physical_target=None, args={"keys": "Enter"})
    pins = [req for req in ws.requests if req["method"] == "Page.setDownloadBehavior"]
    assert len(pins) == 1
    assert pins[0]["params"]["behavior"] == "allow"
    assert pins[0]["params"]["downloadPath"] == download_dir
    assert pins[0]["params"]["eventsEnabled"] is True
    state = host.download_state()
    assert state["download_dir"] == download_dir
    entry = state["downloads"]["dl-1"]
    assert entry["state"] == "completed"
    assert entry["policy_error"] is None


def test_b6_actuator_marks_traversal_filename_rejected_at_record_time(tmp_path: Path) -> None:
    download_dir = str(tmp_path / "fenced" / "downloads")
    Path(download_dir).mkdir(parents=True, exist_ok=True)
    ws = _download_ws(tmp_path, "../../evil.bin")
    host = _download_host(ws, download_dir)
    host.dispatch(verb="press_key", physical_target=None, args={"keys": "Enter"})
    state = host.download_state()
    entry = state["downloads"]["dl-1"]
    assert entry["policy_error"] == "path_not_allowed"
    # no file was written by the contract layer - nothing outside the fence
    assert not (tmp_path / "evil.bin").exists()
    assert not (tmp_path / "fenced" / "evil.bin").exists()


# ---------------------------------------------------------------------------
# J. B6 wait kind=download_state through the real perceive tool.
# ---------------------------------------------------------------------------


def _perceive_with_download_probe(tmp_path: Path, state: dict[str, Any] | None):
    from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool

    class _StaticBackend:
        def capture(self) -> dict[str, Any]:
            return json.loads(json.dumps(FIXTURES["base"]))

    tool = BrowserPerceiveTool(
        adapter=BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "p")),
        backend=_StaticBackend(),
        session_id_getter=lambda: "s1",
        download_state_getter=(lambda: state) if state is not None else None,
    )
    return tool


def test_b6_wait_completed_returns_path_size_sha256_and_file_is_readable(tmp_path: Path) -> None:
    import hashlib

    download_dir = tmp_path / "fenced" / "downloads"
    download_dir.mkdir(parents=True)
    payload = bytes(range(256)) * 4096  # exactly 1 MiB
    (download_dir / "report.bin").write_bytes(payload)
    state = {
        "schema": "smc.browser_download_state.v0.1",
        "download_dir": str(download_dir),
        "dialog_open": False,
        "downloads": {
            "dl-1": {
                "guid": "dl-1",
                "filename": "report.bin",
                "url": "https://example.invalid/report.bin",
                "state": "completed",
                "received_bytes": len(payload),
                "policy_error": None,
            }
        },
    }
    tool = _perceive_with_download_probe(tmp_path, state)
    result = tool.execute(action="wait", kind="download_state", expected="completed", within_ms=1000)
    assert result.status.value == "success"
    receipt = json.loads(result.content)
    assert receipt["result"] == "satisfied"
    assert receipt["completed_by"] == "Page.downloadProgress"
    facts = receipt["facts"]
    assert facts["path"] == str(download_dir / "report.bin")
    assert facts["size"] == len(payload)
    assert facts["sha256"] == hashlib.sha256(payload).hexdigest()
    assert facts["readable"] is True
    # U7: the file is actually readable from the receipt path
    assert Path(facts["path"]).read_bytes() == payload


def test_b6_wait_fallback_completes_on_stable_filesystem_state(tmp_path: Path) -> None:
    download_dir = tmp_path / "fenced" / "downloads"
    download_dir.mkdir(parents=True)
    (download_dir / "slow.bin").write_bytes(b"stable-bytes")
    state = {
        "schema": "smc.browser_download_state.v0.1",
        "download_dir": str(download_dir),
        "dialog_open": False,
        "downloads": {
            "dl-1": {
                "guid": "dl-1",
                "filename": "slow.bin",
                "url": "u",
                "state": "inprogress",  # events missing: fallback ladder applies
                "received_bytes": 0,
                "policy_error": None,
            }
        },
    }
    tool = _perceive_with_download_probe(tmp_path, state)
    result = tool.execute(action="wait", kind="download_state", expected="completed", within_ms=3000)
    assert result.status.value == "success"
    receipt = json.loads(result.content)
    assert receipt["completed_by"] == "filesystem_stable"
    assert receipt["facts"]["readable"] is True


def test_b6_wait_traversal_rejected_with_zero_file_written(tmp_path: Path) -> None:
    state = {
        "schema": "smc.browser_download_state.v0.1",
        "download_dir": str(tmp_path / "fenced" / "downloads"),
        "dialog_open": False,
        "downloads": {
            "dl-1": {
                "guid": "dl-1",
                "filename": "../../evil.bin",
                "url": "u",
                "state": "completed",
                "received_bytes": 10,
                "policy_error": "path_not_allowed",
            }
        },
    }
    tool = _perceive_with_download_probe(tmp_path, state)
    result = tool.execute(action="wait", kind="download_state", expected="completed", within_ms=1000)
    assert result.status.value == "failure"
    assert "path_not_allowed" in result.content
    # no file written anywhere by the contract: the traversal target stays absent
    assert not (tmp_path / "evil.bin").exists()
    assert "facts" not in result.content or "path" not in json.loads(result.content).get("facts", {})


def test_b6_wait_symlink_escape_rejected_and_target_untouched(tmp_path: Path) -> None:
    download_dir = tmp_path / "fenced" / "downloads"
    download_dir.mkdir(parents=True)
    outside = tmp_path / "outside-secret.bin"
    outside.write_bytes(b"sentinel-bytes")
    (download_dir / "escape.bin").symlink_to(outside)
    state = {
        "schema": "smc.browser_download_state.v0.1",
        "download_dir": str(download_dir),
        "dialog_open": False,
        "downloads": {
            "dl-1": {
                "guid": "dl-1",
                "filename": "escape.bin",
                "url": "u",
                "state": "completed",
                "received_bytes": 10,
                "policy_error": "path_not_allowed",
            }
        },
    }
    tool = _perceive_with_download_probe(tmp_path, state)
    result = tool.execute(action="wait", kind="download_state", expected="completed", within_ms=1000)
    assert result.status.value == "failure"
    assert "path_not_allowed" in result.content
    # nothing was written THROUGH the symlink by the contract layer
    assert outside.read_bytes() == b"sentinel-bytes"


def test_b6_wait_without_probe_fails_deterministically(tmp_path: Path) -> None:
    tool = _perceive_with_download_probe(tmp_path, None)
    result = tool.execute(action="wait", kind="download_state", expected="completed", within_ms=500)
    assert result.status.value == "failure"
    assert "download_state" in result.content and "未装配" in result.content


def test_b6_end_to_end_actuator_state_feeds_wait_receipt(tmp_path: Path) -> None:
    """U7 shape: trigger dispatch drains real events; the SAME actuator state
    then satisfies the perceive wait with verifiable file facts."""
    import hashlib

    download_dir = tmp_path / "fenced" / "downloads"
    download_dir.mkdir(parents=True)
    payload = b"z" * (1024 * 1024)
    (download_dir / "e2e.bin").write_bytes(payload)
    ws = _download_ws(tmp_path, "e2e.bin")
    host = _download_host(ws, str(download_dir))
    from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool

    class _StaticBackend:
        def capture(self) -> dict[str, Any]:
            return json.loads(json.dumps(FIXTURES["base"]))

    perceive = BrowserPerceiveTool(
        adapter=BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "p2")),
        backend=_StaticBackend(),
        session_id_getter=lambda: "s1",
        download_state_getter=host.download_state,
    )
    host.dispatch(verb="press_key", physical_target=None, args={"keys": "Enter"})
    result = perceive.execute(action="wait", kind="download_state", expected="completed", within_ms=2000)
    assert result.status.value == "success"
    receipt = json.loads(result.content)
    assert receipt["completed_by"] == "Page.downloadProgress"
    assert receipt["facts"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert receipt["facts"]["size"] == 1024 * 1024


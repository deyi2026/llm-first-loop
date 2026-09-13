from __future__ import annotations

import json
from typing import Any

import pytest

from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator, _MutationCdpSession


class _FakeWs:
    def __init__(self) -> None:
        self.pending: list[str] = []
        self.requests: list[dict[str, Any]] = []
        self.closed = False

    def send(self, payload: str) -> None:
        req = json.loads(payload)
        self.requests.append(req)
        method = req["method"]
        if method == "DOM.resolveNode":
            result = {"object": {"objectId": "obj-1"}}
        elif method == "Runtime.callFunctionOn" or method == "Runtime.evaluate":
            result = {"result": {"type": "undefined"}}
        elif method == "Page.enable":
            result = {}
        elif method == "Page.navigate":
            result = {"frameId": "main"}
        else:
            raise AssertionError(method)
        self.pending.append(json.dumps({"id": req["id"], "result": result}))

    def recv(self, timeout: float | None = None) -> str:  # noqa: ARG002
        return self.pending.pop(0)

    def close(self) -> None:
        self.closed = True


def _host() -> tuple[CdpBrowserMutationActuator, _FakeWs]:
    ws = _FakeWs()
    targets = [{
        "id": "target-1", "type": "page", "url": "http://127.0.0.1/a",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/target-1",
    }]
    host = CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="target-1",
        http_get_json=lambda url: json.loads(json.dumps(targets)),
        ws_connect=lambda url: ws,
    )
    return host, ws


def test_mutation_cdp_session_has_narrow_hard_allowlist() -> None:
    session = _MutationCdpSession(_FakeWs())
    for method in ("Browser.close", "Target.createTarget", "Page.reload", "Network.setCookie"):
        with pytest.raises(PermissionError, match="mutation actuator surface"):
            session.send(method, {})


def test_click_fill_select_scroll_are_fixed_internal_calls_not_model_scripts() -> None:
    host, ws = _host()
    host.dispatch(verb="click", physical_target="dom:2", args={})
    host.dispatch(verb="fill", physical_target="dom:2", args={"text": "secret", "mode": "replace"})
    host.dispatch(verb="select", physical_target="dom:2", args={"value": "v"})
    host.dispatch(verb="scroll", physical_target="dom:2", args={"delta_pages": 1})
    methods = [req["method"] for req in ws.requests]
    assert methods == [
        "Page.enable",
        "DOM.resolveNode", "Runtime.callFunctionOn",
        "DOM.resolveNode", "Runtime.callFunctionOn",
        "DOM.resolveNode", "Runtime.callFunctionOn",
        "DOM.resolveNode", "Runtime.callFunctionOn",
    ]
    # User values are protocol arguments; no user-controlled functionDeclaration exists.
    functions = [req["params"]["functionDeclaration"] for req in ws.requests if req["method"] == "Runtime.callFunctionOn"]
    assert all("secret" not in fn for fn in functions)


def test_navigate_is_single_page_navigate_and_reports_non_exhaustive_boundary_fact() -> None:
    host, ws = _host()
    result = host.dispatch(verb="navigate", physical_target=None, args={"url": "http://127.0.0.1/b"})
    assert [req["method"] for req in ws.requests] == ["Page.enable", "Page.navigate"]
    assert result.acknowledged is True
    assert result.boundary_events[0]["event"] == "navigation_started"
    assert result.boundary_events[0]["complete"] is False
    assert "boundary_detector_non_exhaustive" in result.completeness_reasons


def test_page_boundary_events_are_mechanical_and_non_exhaustive() -> None:
    class _EventWs(_FakeWs):
        def send(self, payload: str) -> None:
            req = json.loads(payload)
            if req["method"] == "Runtime.callFunctionOn":
                self.pending.extend(
                    [
                        json.dumps({"method": "Page.windowOpen", "params": {"url": "about:blank"}}),
                        json.dumps({"method": "Page.downloadWillBegin", "params": {"url": "http://127.0.0.1/file"}}),
                        json.dumps({"method": "Page.javascriptDialogOpening", "params": {"type": "alert"}}),
                    ]
                )
            super().send(payload)

    ws = _EventWs()
    targets = [{
        "id": "target-1", "type": "page", "url": "http://127.0.0.1/a",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/target-1",
    }]
    host = CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="target-1",
        http_get_json=lambda url: json.loads(json.dumps(targets)),
        ws_connect=lambda url: ws,
    )
    result = host.dispatch(verb="click", physical_target="dom:2", args={})
    assert {event["event"] for event in result.boundary_events} == {
        "new_window",
        "download_started",
        "dialog_opened",
    }
    assert all(event["complete"] is False for event in result.boundary_events)
    assert "boundary_detector_non_exhaustive" in result.completeness_reasons


def test_actuator_never_silently_rebinds_target() -> None:
    ws = _FakeWs()
    targets = [{
        "id": "target-1", "type": "page", "url": "http://127.0.0.1/a",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/target-1",
    }]
    host = CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="target-1",
        http_get_json=lambda url: json.loads(json.dumps(targets)),
        ws_connect=lambda url: ws,
    )
    host.dispatch(verb="click", physical_target="dom:2", args={})
    targets[:] = [{
        "id": "target-2", "type": "page", "url": "http://127.0.0.1/a",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/target-2",
    }]
    with pytest.raises(RuntimeError, match="disappeared"):
        host.dispatch(verb="click", physical_target="dom:2", args={})

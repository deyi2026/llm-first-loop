"""M2 B-05 (audit §5.6/§405, FR-08/T-12): scoped scrolling - the object's own
scrollable container instead of a blind window.scrollBy that moved the page
while nested containers stayed put."""

import json
from typing import Any

from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator


class _ScrollWs:
    """Fake WS; callFunctionOn replies are keyed by fixed-script signature."""

    def __init__(self, scroll_reply: Any = None) -> None:
        self.pending: list[str] = []
        self.requests: list[dict[str, Any]] = []
        self._scroll_reply = scroll_reply

    def send(self, payload: str) -> None:
        req = json.loads(payload)
        self.requests.append(req)
        method = req["method"]
        if method == "DOM.resolveNode":
            result: dict[str, Any] = {"object": {"objectId": "obj-1"}}
        elif method == "Runtime.callFunctionOn":
            fn = req["params"]["functionDeclaration"]
            if fn.startswith("function(pages)"):  # _SCROLL_SCOPED_JS
                result = {"result": {"type": "object", "value": self._scroll_reply}}
            else:
                result = {"result": {"type": "undefined"}}
        elif method == "Page.enable":
            result = {}
        else:
            raise AssertionError(method)
        self.pending.append(json.dumps({"id": req["id"], "result": result}))

    def recv(self, timeout: float | None = None) -> str:  # noqa: ARG002
        return self.pending.pop(0)

    def close(self) -> None:
        return None


def _host(ws: _ScrollWs) -> CdpBrowserMutationActuator:
    from llm_loop.browser.attestation import AttestationVerdict

    targets = [{
        "id": "target-1", "type": "page", "url": "http://127.0.0.1/a",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/target-1",
    }]
    return CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="target-1",
        http_get_json=lambda url: json.loads(json.dumps(targets)),
        ws_connect=lambda url: ws,
        attest_fn=lambda url: AttestationVerdict(
            verdict="dedicated", user_data_dir="/tmp/attest-stub-profile",
            argv_sha256="stub" * 16, argv=(), detail="unit-test stub",
        ),
    )


def test_scroll_script_targets_nearest_scrollable_container_not_window() -> None:
    ws = _ScrollWs(scroll_reply={"scope": "container", "node": "DIV",
                                 "before": 0, "after": 600, "max": 2400})
    result = _host(ws).dispatch(
        verb="scroll", physical_target="dom:5", args={"delta_pages": 1.0}
    )
    assert [req["method"] for req in ws.requests] == [
        "Page.enable", "DOM.resolveNode", "Runtime.callFunctionOn",
    ]
    fn = ws.requests[-1]["params"]["functionDeclaration"]
    # container-first: climbs parentElement looking for a scrollable ancestor
    # and only falls back to window.scrollBy when none matches
    assert "parentElement" in fn
    assert "scrollHeight > el.clientHeight" in fn
    assert "window.scrollBy" in fn  # fallback branch
    assert result.acknowledged is True
    assert result.scroll_fact == {
        "scope": "container", "node": "DIV", "before": 0, "after": 600, "max": 2400,
    }


def test_scroll_page_fallback_fact_flows_to_receipt() -> None:
    ws = _ScrollWs(scroll_reply={"scope": "page", "before": 0,
                                 "after": 800, "max": 3200})
    result = _host(ws).dispatch(
        verb="scroll", physical_target="dom:5", args={"delta_pages": -1.0}
    )
    assert ws.requests[-1]["params"]["arguments"] == [{"value": -1.0}]
    assert result.scroll_fact == {"scope": "page", "before": 0,
                                  "after": 800, "max": 3200}


def test_scroll_unexpected_reply_shape_degrades_to_no_fact_not_crash() -> None:
    ws = _ScrollWs(scroll_reply="not-a-dict")
    result = _host(ws).dispatch(
        verb="scroll", physical_target="dom:5", args={"delta_pages": 1.0}
    )
    assert result.acknowledged is True
    assert result.scroll_fact is None  # fail-open for the FACT only, not the gate

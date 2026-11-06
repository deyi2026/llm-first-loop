"""M2 B-01 (audit §5.5/§405, FR-04/T-08/T-16): set_text/append_text real input
pipeline - focus + selection establishment + Input.insertText + readback
verification - replacing the legacy this.value assignment whose synthesized
events reported fake successes on controlled components (PR2)."""

import json
from typing import Any

import pytest

from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator


class _FillWs:
    """Fake WS; value replies are keyed by fixed-script signature."""

    def __init__(self, before_reply: Any = None, readback_reply: Any = None) -> None:
        self.pending: list[str] = []
        self.requests: list[dict[str, Any]] = []
        self.insert_text_calls: list[dict[str, Any]] = []
        self._before_reply = before_reply
        self._readback_reply = readback_reply

    def send(self, payload: str) -> None:
        req = json.loads(payload)
        self.requests.append(req)
        method = req["method"]
        if method == "DOM.resolveNode":
            result: dict[str, Any] = {"object": {"objectId": "obj-1"}}
        elif method == "Runtime.callFunctionOn":
            fn = req["params"]["functionDeclaration"]
            if "return String(this.value" in fn:  # _FILL_BEFORE_JS
                result = {"result": {"type": "string", "value": self._before_reply}}
            elif fn.startswith("async function(expected)"):  # _FILL_READBACK_JS
                result = {"result": {"type": "string", "value": self._readback_reply}}
            else:
                result = {"result": {"type": "undefined"}}
        elif method == "Page.enable":
            result = {}
        elif method == "Input.insertText":
            self.insert_text_calls.append(req["params"])
            result = {}
        else:
            raise AssertionError(method)
        self.pending.append(json.dumps({"id": req["id"], "result": result}))

    def recv(self, timeout: float | None = None) -> str:  # noqa: ARG002
        return self.pending.pop(0)

    def close(self) -> None:
        return None


def _host(ws: _FillWs) -> CdpBrowserMutationActuator:
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


def _function_bodies(ws: _FillWs) -> list[str]:
    return [
        req["params"]["functionDeclaration"]
        for req in ws.requests
        if req["method"] == "Runtime.callFunctionOn"
    ]


def test_fill_replace_focuses_selects_inserttext_then_readback(monkeypatch) -> None:
    monkeypatch.delenv("LFL_BROWSER_INPUT_PIPELINE", raising=False)
    ws = _FillWs()  # before=undefined; readback=null(match)
    result = _host(ws).dispatch(
        verb="fill", physical_target="dom:5", args={"text": "hello-secret", "mode": "replace"}
    )
    assert [req["method"] for req in ws.requests] == [
        "Page.enable",
        "DOM.resolveNode",
        "Runtime.callFunctionOn",  # before read
        "Runtime.callFunctionOn",  # focus + select()
        "Input.insertText",
        "Runtime.callFunctionOn",  # readback verify
    ]
    assert ws.insert_text_calls == [{"text": "hello-secret"}]
    bodies = _function_bodies(ws)
    assert "this.select()" in bodies[1]
    assert result.acknowledged is True
    assert result.input_pipeline == "insert_text"
    assert result.readback is None
    # user text lives only in protocol arguments, never in a script body
    for body in bodies:
        assert "hello-secret" not in body
        # legacy assignment signature must not appear in the new pipeline
        assert "this.value=next" not in body
    # readback waits for framework re-render (async script + awaitPromise)
    readback_req = next(
        req for req in ws.requests
        if req["method"] == "Runtime.callFunctionOn"
        and req["params"]["functionDeclaration"].startswith("async function(expected)")
    )
    assert readback_req["params"]["awaitPromise"] is True


def test_fill_append_reads_base_cursor_to_end_expected_concat(monkeypatch) -> None:
    monkeypatch.delenv("LFL_BROWSER_INPUT_PIPELINE", raising=False)
    ws = _FillWs(before_reply="abc")  # readback null(match)
    result = _host(ws).dispatch(
        verb="fill", physical_target="dom:5", args={"text": "XYZ", "mode": "append"}
    )
    bodies = _function_bodies(ws)
    assert "setSelectionRange(n,n)" in bodies[1]
    readback_req = next(
        req for req in ws.requests[::-1] if req["method"] == "Runtime.callFunctionOn"
    )
    assert readback_req["params"]["arguments"] == [{"value": "abcXYZ"}]
    assert result.input_pipeline == "insert_text"
    assert result.readback is None
    assert ws.insert_text_calls == [{"text": "XYZ"}]


def test_fill_readback_mismatch_is_honest_fact_not_fake_success(monkeypatch) -> None:
    monkeypatch.delenv("LFL_BROWSER_INPUT_PIPELINE", raising=False)
    # controlled-component reversion / maxlength truncation: actual != expected
    ws = _FillWs(readback_reply="trunc")
    result = _host(ws).dispatch(
        verb="fill", physical_target="dom:5", args={"text": "0123456789", "mode": "replace"}
    )
    assert result.acknowledged is True
    assert result.input_pipeline == "insert_text"
    assert result.readback == {
        "check": "set_text_readback_mismatch",
        "mode": "replace",
        "expected": "0123456789",
        "actual": "trunc",
    }


def test_t16_switch_off_routes_legacy_with_degraded_marker(monkeypatch) -> None:
    monkeypatch.setenv("LFL_BROWSER_INPUT_PIPELINE", "off")
    ws = _FillWs()
    result = _host(ws).dispatch(
        verb="fill", physical_target="dom:5", args={"text": "v", "mode": "replace"}
    )
    assert [req["method"] for req in ws.requests] == [
        "Page.enable",
        "DOM.resolveNode",
        "Runtime.callFunctionOn",  # legacy assignment only
    ]
    assert ws.insert_text_calls == []
    body = _function_bodies(ws)[0]
    assert "this.value=next" in body  # legacy assignment signature
    assert result.input_pipeline == "legacy_degraded"
    assert result.readback is None


@pytest.mark.parametrize("raw", ["on", "", "ON", "insert_text"])
def test_t16_switch_on_variants_use_real_pipeline(monkeypatch, raw: str) -> None:
    monkeypatch.setenv("LFL_BROWSER_INPUT_PIPELINE", raw)
    ws = _FillWs()
    result = _host(ws).dispatch(
        verb="fill", physical_target="dom:5", args={"text": "t", "mode": "replace"}
    )
    assert result.input_pipeline == "insert_text"
    assert ws.insert_text_calls == [{"text": "t"}]

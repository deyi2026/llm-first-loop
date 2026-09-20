"""Deterministic fake-only GREEN qualification for P4-LIVE G2-S2."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from evals.smc_semantic_logic_p4_live.green2_s2_red_contracts import (
    S2_RED_IDS,
    _action_ref_fixture,
    run_probe,
)
from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool


@pytest.mark.parametrize("row_id", S2_RED_IDS, ids=S2_RED_IDS)
def test_p4_live_g2_s2_contract_is_green(row_id: str) -> None:
    probe = run_probe(row_id)
    assert probe.failure_code != "harness_error", (
        f"{row_id} harness failure cannot qualify GREEN: {probe.detail}; facts={probe.facts}"
    )
    assert probe.failure_code == "contract_present", (
        f"{row_id} S2 GREEN missing: observed={probe.failure_code}; "
        f"detail={probe.detail}; facts={probe.facts}"
    )
    assert probe.contract_satisfied, (
        f"{row_id} expected S2 production capability missing; facts={probe.facts}"
    )


class _FakeWs:
    def __init__(self) -> None:
        self.pending: list[str] = []
        self.requests: list[dict[str, Any]] = []

    def send(self, payload: str) -> None:
        req = json.loads(payload)
        self.requests.append(req)
        if req["method"] == "Page.enable":
            result: dict[str, Any] = {}
        elif req["method"] == "DOM.resolveNode":
            result = {"object": {"objectId": "obj-1"}}
        elif req["method"] == "Runtime.callFunctionOn":
            result = {"result": {"type": "undefined"}}
        else:
            raise AssertionError(req["method"])
        self.pending.append(json.dumps({"id": req["id"], "result": result}))

    def recv(self, timeout: float | None = None) -> str:  # noqa: ARG002
        return self.pending.pop(0)

    def close(self) -> None:
        return None


def _page(target_id: str) -> dict[str, Any]:
    return {
        "id": target_id,
        "type": "page",
        "url": f"http://127.0.0.1/{target_id}",
        "webSocketDebuggerUrl": f"ws://127.0.0.1:9222/devtools/page/{target_id}",
    }


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_s2_sticky_target_mismatch_rejects_before_bind_or_websocket() -> None:
    module = importlib.import_module("llm_loop.browser.cdp_action_host")
    error_type = getattr(module, "BrowserTargetPreconditionError", None)
    assert error_type is not None, "S2 missing stable Browser target precondition error"

    ws_calls: list[str] = []
    host = CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="",
        http_get_json=lambda _url: [_page("target-B")],
        ws_connect=lambda url: ws_calls.append(url),  # type: ignore[arg-type,return-value]
    )
    bind = getattr(host, "bind_observed_target", None)
    assert callable(bind), "S2 missing sticky target bind API"
    with pytest.raises(error_type) as exc:
        bind(_sha("target-A"))
    assert getattr(exc.value, "code", None) == "browser_target_precondition_mismatch"
    assert host.bound_target_id == ""
    assert ws_calls == []


def test_s2_sticky_target_match_binds_without_websocket_or_cdp() -> None:
    ws_calls: list[str] = []
    host = CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="",
        http_get_json=lambda _url: [_page("target-A")],
        ws_connect=lambda url: ws_calls.append(url),  # type: ignore[arg-type,return-value]
    )
    bind = getattr(host, "bind_observed_target", None)
    assert callable(bind), "S2 missing sticky target bind API"
    bind(_sha("target-A"))
    assert host.bound_target_id == "target-A"
    assert ws_calls == []


def test_s2_sticky_target_never_rebinds_to_successor_page() -> None:
    pages = [_page("target-A")]
    ws = _FakeWs()
    host = CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="",
        http_get_json=lambda _url: copy.deepcopy(pages),
        ws_connect=lambda _url: ws,
    )
    bind = getattr(host, "bind_observed_target", None)
    assert callable(bind), "S2 missing sticky target bind API"
    bind(_sha("target-A"))
    pages[:] = [_page("target-B")]
    with pytest.raises(RuntimeError, match="disappeared"):
        host.dispatch(verb="click", physical_target="dom:2", args={})
    assert host.bound_target_id == "target-A"
    assert ws.requests == []


def test_s2_legacy_actuator_without_sticky_bind_is_unchanged() -> None:
    ws = _FakeWs()
    host = CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="",
        http_get_json=lambda _url: [_page("legacy-only")],
        ws_connect=lambda _url: ws,
    )
    result = host.dispatch(verb="click", physical_target="dom:2", args={})
    assert result.acknowledged is True
    assert host.bound_target_id == "legacy-only"
    assert [request["method"] for request in ws.requests] == [
        "Page.enable",
        "DOM.resolveNode",
        "Runtime.callFunctionOn",
    ]


def test_s2_hidden_bridge_delegates_exact_grounding_ref_once_and_preserves_basis() -> None:
    module = importlib.import_module("llm_loop.tools.builtin.browser_action_ref_kernel")
    bridge_type = getattr(module, "ActionRefSemanticCompileBridge", None)
    assert bridge_type is not None, "S2 missing hidden ActionRef compiler bridge"

    with _action_ref_fixture() as fixture:
        resolution = fixture["resolver"].resolve(
            str(fixture["target"]["action_ref"]),
            context=fixture["resolve_context"],
            expected_kind="object",
        )
        actual = BrowserSemanticExecuteTool(
            perception=fixture["adapter"],
            action_adapter=object(),  # type: ignore[arg-type]
            session_id_getter=lambda: "p4live-session-A",
        )
        direct = actual.compile_request(
            "p4live-session-A",
            {"verb": "click", "target_ref": resolution.grounding_ref, "args": {}},
        )
        calls: list[tuple[str, dict[str, Any]]] = []

        class _CompilerSpy:
            def compile_request(self, session_id: str, request: dict[str, Any]) -> dict[str, Any]:
                calls.append((session_id, copy.deepcopy(request)))
                return actual.compile_request(session_id, request)

        compiled = bridge_type(compiler=_CompilerSpy()).compile_resolved(
            session_id="p4live-session-A",
            resolution=resolution,
            verb="click",
            args={},
        )
        assert calls == [
            (
                "p4live-session-A",
                {"verb": "click", "target_ref": resolution.grounding_ref, "args": {}},
            )
        ]
        assert compiled.semantic_action == direct
        assert compiled.semantic_action["action_id"] == direct["action_id"]
        assert compiled.semantic_action["expected_version"] == resolution.observed_snapshot_id
        assert compiled.grounding_ref == resolution.grounding_ref
        assert compiled.observed_snapshot_id == resolution.observed_snapshot_id
        assert compiled.browser_target_id_sha256 == resolution.browser_target_id_sha256


def test_s2_hidden_bridge_is_non_dispatching_and_not_factory_registered() -> None:
    root = Path(__file__).resolve().parents[2]
    kernel = (root / "src/llm_loop/tools/builtin/browser_action_ref_kernel.py").read_text(
        encoding="utf-8"
    )
    factory = (root / "src/llm_loop/factory.py").read_text(encoding="utf-8")
    registry = (root / "src/llm_loop/tools/registry.py").read_text(encoding="utf-8")
    assert "BrowserActionAdapter" not in kernel
    assert "execute_request" not in kernel
    assert ".dispatch(" not in kernel
    assert "browser_action_ref_kernel" not in factory
    assert "browser_action_ref_kernel" not in registry

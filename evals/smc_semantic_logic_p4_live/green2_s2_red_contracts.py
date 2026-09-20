"""Deterministic pre-GREEN probes for P4-LIVE GREEN-2 slice G2-S2.

The probes deliberately exercise only local fixtures/fake actuators and production
read-only/compiler mechanics.  A RED result means the named S2 production seam is
absent while its prerequisite GREEN machinery is independently proven healthy.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import inspect
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from evals.smc_semantic_logic_p4_live.red_contracts import (  # noqa: E402
    _action_ref_fixture,
    _existing_version_guard_facts,
    _first_bind_gap_facts,
    _fixtures,
    _inner_id_prerequisite_facts,
)
from llm_loop.browser.action import (  # noqa: E402
    BrowserActionAdapter,
    BrowserActionReceiptStore,
    BrowserDispatchResult,
    BrowserMutationActuator,
)
from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator  # noqa: E402
from llm_loop.tools.builtin.browser_semantic_execute import (  # noqa: E402
    BrowserSemanticExecuteTool,
)

EXPECTED_PATH = Path(__file__).with_name("GREEN2-S2-EXPECTED-FAILURES.v0.1.json")
HIDDEN_BRIDGE_MODULE = "llm_loop.tools.builtin.browser_action_ref_kernel"
HIDDEN_BRIDGE_CLASS = "ActionRefSemanticCompileBridge"
TARGET_BIND_METHOD = "bind_observed_target"
TARGET_MISMATCH_CODE = "browser_target_precondition_mismatch"


@dataclass(frozen=True)
class S2ProbeResult:
    row_id: str
    contract_satisfied: bool
    failure_code: str
    detail: str
    facts: dict[str, Any]


def load_expected_failures() -> dict[str, dict[str, str]]:
    doc = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    return {str(row["id"]): dict(row) for row in doc["rows"]}


S2_RED_IDS = tuple(load_expected_failures())


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _resolved_fixture_facts() -> dict[str, Any]:
    with _action_ref_fixture() as fixture:
        resolution = fixture["resolver"].resolve(
            str(fixture["target"]["action_ref"]),
            context=fixture["resolve_context"],
            expected_kind="object",
        )
        target = fixture["target"]
        page_token = str(_fixtures()["base"]["page_token"])
        tool = BrowserSemanticExecuteTool(
            perception=fixture["adapter"],
            action_adapter=object(),  # type: ignore[arg-type]
            session_id_getter=lambda: "p4live-session-A",
        )
        request = {"verb": "click", "target_ref": resolution.grounding_ref, "args": {}}
        first = tool.compile_request("p4live-session-A", request)
        second = tool.compile_request("p4live-session-A", dict(request))
        return {
            "resolution": resolution,
            "tool": tool,
            "root": fixture["root"],
            "adapter": fixture["adapter"],
            "perception_store": fixture["perception_store"],
            "target": target,
            "compiled": first,
            "grounding_ref_exact": resolution.grounding_ref == str(target["grounding_ref"]),
            "target_hash_present": bool(resolution.browser_target_id_sha256),
            "target_hash_matches_observed_page": (
                resolution.browser_target_id_sha256 == _sha_text(page_token)
            ),
            "action_id_deterministic": first["action_id"] == second["action_id"],
            "compiled_expected_version_matches_actionref": (
                first["expected_version"] == resolution.observed_snapshot_id
            ),
        }


def _target_precondition_behavior(expected_target_hash: str) -> dict[str, Any]:
    protocol_has_api = hasattr(BrowserMutationActuator, TARGET_BIND_METHOD)
    adapter_has_api = hasattr(BrowserActionAdapter, TARGET_BIND_METHOD)
    actuator_has_api = hasattr(CdpBrowserMutationActuator, TARGET_BIND_METHOD)
    facts: dict[str, Any] = {
        "protocol_has_sticky_target_bind_api": protocol_has_api,
        "browser_action_adapter_has_sticky_target_bind_api": adapter_has_api,
        "cdp_actuator_has_sticky_target_bind_api": actuator_has_api,
        "mismatch_rejected_before_websocket": False,
        "mismatch_error_code": "",
        "match_binds_exact_target_without_websocket": False,
    }
    if not actuator_has_api:
        return facts

    def page(target_id: str) -> dict[str, Any]:
        return {
            "id": target_id,
            "type": "page",
            "url": f"https://example.test/{target_id}",
            "webSocketDebuggerUrl": f"ws://127.0.0.1/devtools/page/{target_id}",
        }

    ws_calls: list[str] = []
    wrong = CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="",
        http_get_json=lambda _url: [page("target-B")],
        ws_connect=lambda url: ws_calls.append(url),  # type: ignore[arg-type,return-value]
    )
    try:
        getattr(wrong, TARGET_BIND_METHOD)(expected_target_hash)
    except Exception as exc:  # noqa: BLE001 - exact future error fact is qualified below.
        facts["mismatch_error_code"] = str(getattr(exc, "code", ""))
        facts["mismatch_rejected_before_websocket"] = (
            not ws_calls and wrong.bound_target_id == ""
        )

    ws_calls.clear()
    right = CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="",
        http_get_json=lambda _url: [page("page-a")],
        ws_connect=lambda url: ws_calls.append(url),  # type: ignore[arg-type,return-value]
    )
    try:
        getattr(right, TARGET_BIND_METHOD)(expected_target_hash)
        facts["match_binds_exact_target_without_websocket"] = (
            right.bound_target_id == "page-a" and not ws_calls
        )
    except Exception:  # noqa: BLE001 - recorded as failed prerequisite.
        facts["match_binds_exact_target_without_websocket"] = False
    return facts


def _hidden_bridge_behavior(base: dict[str, Any]) -> dict[str, Any]:
    spec = importlib.util.find_spec(HIDDEN_BRIDGE_MODULE)
    facts: dict[str, Any] = {
        "hidden_bridge_module_present": spec is not None,
        "hidden_bridge_class_present": False,
        "bridge_delegates_exact_grounding_ref_once": False,
        "bridge_preserves_existing_action_id": False,
        "bridge_preserves_expected_version": False,
        "bridge_preserves_browser_target_hash": False,
        "bridge_has_dispatch_dependency": False,
    }
    if spec is None:
        return facts
    module = importlib.import_module(HIDDEN_BRIDGE_MODULE)
    bridge_type = getattr(module, HIDDEN_BRIDGE_CLASS, None)
    facts["hidden_bridge_class_present"] = bridge_type is not None
    source = inspect.getsource(module)
    facts["bridge_has_dispatch_dependency"] = any(
        token in source for token in ("BrowserActionAdapter", ".dispatch(", ".execute_request(")
    )
    if bridge_type is None:
        return facts

    calls: list[tuple[str, dict[str, Any]]] = []
    direct = dict(base["compiled"])

    class _CompilerSpy:
        def compile_request(self, session_id: str, request: dict[str, Any]) -> dict[str, Any]:
            calls.append((session_id, copy.deepcopy(request)))
            return dict(direct)

    bridge = bridge_type(compiler=_CompilerSpy())
    compiled = bridge.compile_resolved(
        session_id="p4live-session-A",
        resolution=base["resolution"],
        verb="click",
        args={},
    )
    semantic_action = dict(getattr(compiled, "semantic_action", {}))
    facts["bridge_delegates_exact_grounding_ref_once"] = calls == [
        (
            "p4live-session-A",
            {"verb": "click", "target_ref": base["resolution"].grounding_ref, "args": {}},
        )
    ]
    facts["bridge_preserves_existing_action_id"] = (
        semantic_action.get("action_id") == direct.get("action_id")
    )
    facts["bridge_preserves_expected_version"] = (
        semantic_action.get("expected_version") == base["resolution"].observed_snapshot_id
        and getattr(compiled, "observed_snapshot_id", "")
        == base["resolution"].observed_snapshot_id
    )
    facts["bridge_preserves_browser_target_hash"] = (
        getattr(compiled, "browser_target_id_sha256", "")
        == base["resolution"].browser_target_id_sha256
    )
    return facts


def _existing_guard_behavior() -> dict[str, Any]:
    stale = _existing_version_guard_facts()
    with _action_ref_fixture() as fixture:
        resolution = fixture["resolver"].resolve(
            str(fixture["target"]["action_ref"]),
            context=fixture["resolve_context"],
            expected_kind="object",
        )
        compiler = BrowserSemanticExecuteTool(
            perception=fixture["adapter"],
            action_adapter=object(),  # type: ignore[arg-type]
            session_id_getter=lambda: "p4live-session-A",
        )
        compiled = compiler.compile_request(
            "p4live-session-A",
            {"verb": "click", "target_ref": resolution.grounding_ref, "args": {}},
        )
        actuator_calls: list[dict[str, Any]] = []

        class _Capture:
            def capture(self) -> dict[str, Any]:
                return copy.deepcopy(_fixtures()["navigate"])

        class _Actuator:
            def dispatch(self, **kwargs: Any) -> BrowserDispatchResult:
                actuator_calls.append(dict(kwargs))
                return BrowserDispatchResult(acknowledged=True)

        action = BrowserActionAdapter(
            perception=fixture["adapter"],
            receipt_store=BrowserActionReceiptStore(Path(fixture["root"]) / "s2-guard-actions"),
            capture_backend=_Capture(),
            actuator=_Actuator(),
        )
        receipt = action.execute("p4live-session-A", dict(compiled))

        bundle = fixture["perception_store"].load_snapshot_bundle(
            "p4live-session-A", resolution.observed_snapshot_id
        )
        target_id = str(compiled["target_id"])
        stable_target = BrowserActionAdapter._physical_target(bundle, target_id)  # noqa: SLF001
        unstable_bundle = copy.deepcopy(bundle)
        identity = ((unstable_bundle.get("private_capture") or {}).get("identity") or {}).get(
            target_id
        )
        if isinstance(identity, dict):
            identity["stable"] = False
        unstable_target = BrowserActionAdapter._physical_target(  # noqa: SLF001
            unstable_bundle, target_id
        )
    return {
        "existing_version_guard_stale": stale.get("result") == "stale",
        "existing_guard_no_automatic_refresh": stale.get("automatic_refresh_performed") is False,
        "existing_guard_no_silent_rebind": stale.get("silent_rebind_performed") is False,
        "manually_compiled_action_rejected_stale_without_dispatch": (
            receipt.get("status") == "rejected" and actuator_calls == []
        ),
        "stable_physical_target_resolves": bool(stable_target),
        "unstable_physical_target_fails_closed": unstable_target is None,
    }


def probe_r12_target_precondition() -> S2ProbeResult:
    base = _resolved_fixture_facts()
    gap = _first_bind_gap_facts()
    precondition = _target_precondition_behavior(
        str(base["resolution"].browser_target_id_sha256)
    )
    satisfied = bool(
        precondition["protocol_has_sticky_target_bind_api"]
        and precondition["browser_action_adapter_has_sticky_target_bind_api"]
        and precondition["cdp_actuator_has_sticky_target_bind_api"]
        and precondition["mismatch_rejected_before_websocket"]
        and precondition["mismatch_error_code"] == TARGET_MISMATCH_CODE
        and precondition["match_binds_exact_target_without_websocket"]
    )
    return S2ProbeResult(
        row_id="G2S2-R12-TARGET-PRECONDITION",
        contract_satisfied=satisfied,
        failure_code=(
            "contract_present" if satisfied else "actionref_browser_target_precondition_absent"
        ),
        detail=(
            "ActionRef already carries the exact observed Browser target hash, but the "
            "sticky pre-dispatch target bind/verify seam is absent"
        ),
        facts={
            "actionref_target_hash_present": base["target_hash_present"],
            "actionref_target_hash_matches_observed_page": base["target_hash_matches_observed_page"],
            **gap,
            **precondition,
        },
    )


def probe_r14_hidden_compiler_bridge() -> S2ProbeResult:
    base = _resolved_fixture_facts()
    existing = _inner_id_prerequisite_facts()
    bridge = _hidden_bridge_behavior(base)
    satisfied = bool(
        base["grounding_ref_exact"]
        and base["action_id_deterministic"]
        and base["compiled_expected_version_matches_actionref"]
        and existing["duplicate_reservation_rejected"]
        and bridge["hidden_bridge_module_present"]
        and bridge["hidden_bridge_class_present"]
        and bridge["bridge_delegates_exact_grounding_ref_once"]
        and bridge["bridge_preserves_existing_action_id"]
        and bridge["bridge_preserves_expected_version"]
        and bridge["bridge_preserves_browser_target_hash"]
        and not bridge["bridge_has_dispatch_dependency"]
    )
    return S2ProbeResult(
        row_id="G2S2-R14-HIDDEN-COMPILER-BRIDGE",
        contract_satisfied=satisfied,
        failure_code=(
            "contract_present"
            if satisfied
            else "actionref_hidden_groundingref_compiler_bridge_absent"
        ),
        detail=(
            "Existing GroundingRef compiler/action-id authority is ready, but the hidden "
            "ActionRefResolution -> exact GroundingRef compiler bridge is absent"
        ),
        facts={
            "actionref_grounding_ref_round_trip_exact": base["grounding_ref_exact"],
            "existing_action_id_deterministic": base["action_id_deterministic"],
            "compiled_expected_version_matches_actionref": base[
                "compiled_expected_version_matches_actionref"
            ],
            **existing,
            **bridge,
        },
    )


def probe_r19_guard_basis() -> S2ProbeResult:
    base = _resolved_fixture_facts()
    guard = _existing_guard_behavior()
    bridge = _hidden_bridge_behavior(base)
    prerequisites = all(bool(value) for value in guard.values())
    satisfied = bool(
        prerequisites
        and bridge["hidden_bridge_module_present"]
        and bridge["hidden_bridge_class_present"]
        and bridge["bridge_preserves_expected_version"]
        and bridge["bridge_preserves_browser_target_hash"]
        and not bridge["bridge_has_dispatch_dependency"]
    )
    return S2ProbeResult(
        row_id="G2S2-R19-GUARD-BASIS",
        contract_satisfied=satisfied,
        failure_code="contract_present" if satisfied else "actionref_guard_basis_bridge_absent",
        detail=(
            "Existing stale/version/stable-target guards fail closed, but no hidden "
            "ActionRef compiled result preserves their exact guard basis"
        ),
        facts={**guard, **bridge},
    )


PROBES = {
    "G2S2-R12-TARGET-PRECONDITION": probe_r12_target_precondition,
    "G2S2-R14-HIDDEN-COMPILER-BRIDGE": probe_r14_hidden_compiler_bridge,
    "G2S2-R19-GUARD-BASIS": probe_r19_guard_basis,
}


def run_probe(row_id: str) -> S2ProbeResult:
    try:
        probe = PROBES[row_id]
    except KeyError as exc:
        raise ValueError(f"unknown G2-S2 RED id: {row_id}") from exc
    try:
        return probe()
    except Exception as exc:  # noqa: BLE001 - harness break must never masquerade as RED.
        return S2ProbeResult(
            row_id=row_id,
            contract_satisfied=False,
            failure_code="harness_error",
            detail=f"{type(exc).__name__}: {exc}",
            facts={"exception_type": type(exc).__name__},
        )

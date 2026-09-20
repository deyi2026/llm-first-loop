"""Deterministic production probes for the frozen P4-LIVE ActionRef RED contracts.

This module is deliberately qualification-only.  It never performs a real Browser
action, never sends a model request, and never mutates production state.  A probe may
use temporary local stores or inspect existing production objects/source in order to
distinguish an expected missing production capability from a broken RED harness.
"""

from __future__ import annotations

import inspect
import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from llm_loop.browser.action import BrowserActionAdapter, BrowserActionReceiptStore
from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator
from llm_loop.browser.cdp_host import CdpReadOnlyBrowserHost
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.core.loop.engine import LoopEngine
from llm_loop.core.tool_execution_journal import (
    ToolExecutionJournal,
    current_effect_mutation_authority,
)
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
from llm_loop.tools.registry import GetToolSchemaTool

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PATH = Path(__file__).with_name("EXPECTED-FAILURES.v0.1.json")
FIXTURE_PATH = ROOT / "tests/fixtures/smc_browser_perception_v01.json"


@dataclass(frozen=True)
class ProbeResult:
    row_id: str
    contract_satisfied: bool
    failure_code: str
    detail: str
    facts: dict[str, Any]


def load_expected_failures() -> dict[str, dict[str, str]]:
    doc = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    return {str(row["id"]): dict(row) for row in doc["rows"]}


RED_IDS = tuple(load_expected_failures())


@lru_cache(maxsize=1)
def _production_actionref_mentions() -> tuple[str, ...]:
    hits: list[str] = []
    for path in sorted((ROOT / "src/llm_loop").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "action_ref" in text.lower() or "actionref" in text.lower():
            hits.append(str(path.relative_to(ROOT)))
    return tuple(hits)


@lru_cache(maxsize=1)
def _fixtures() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _find_named_object(result: dict[str, Any], name: str) -> dict[str, Any]:
    for obj in result.get("objects", []):
        if (obj.get("attributes") or {}).get("name") == name:
            return dict(obj)
    raise AssertionError(f"fixture object not found: {name}")


def _perception_projection_facts() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="p4live-red-perception-") as td:
        store = BrowserPerceptionStore(
            Path(td) / "browser",
            retention_seconds=60,
            now_fn=lambda: 1_000.0,
        )
        adapter = BrowserPerceptionAdapter(store=store)
        result = adapter.snapshot("p4live-red-session", _fixtures()["base"], projection_limit=100)
        snapshot_id = str(result["snapshot"]["snapshot_id"])
        persisted = store.load_snapshot_bundle("p4live-red-session", snapshot_id) is not None
        object_action_refs = [
            obj.get("action_ref")
            for obj in result.get("objects", [])
            if isinstance(obj, dict) and obj.get("action_ref")
        ]
        resource_action_ref = result.get("action_ref") or result.get("resource_action_ref")
        return {
            "snapshot_persisted": persisted,
            "snapshot_id_present": bool(snapshot_id),
            "resource_ref_present": bool(result.get("resource_ref")),
            "resource_action_ref_present": bool(resource_action_ref),
            "object_action_ref_count": len(object_action_refs),
        }


def _grounding_exact_hydration_facts() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="p4live-red-hydrate-") as td:
        store = BrowserPerceptionStore(Path(td) / "browser", retention_seconds=60)
        adapter = BrowserPerceptionAdapter(store=store)
        result = adapter.snapshot("s1", _fixtures()["base"])
        target = _find_named_object(result, "Submit")
        ref = str(target["grounding_ref"])
        hydrated = adapter.hydrate("s1", ref)
        content = hydrated.get("content") or {}
        semantic_object = content.get("semantic_object") or {}
        cross = adapter.hydrate("s2", ref)
        return {
            "grounding_ref_round_trip_exact": semantic_object.get("grounding_ref") == ref,
            "cross_session_grounding_ref_availability": cross.get("availability"),
            "cross_session_grounding_ref_reason": cross.get("reason"),
        }


def _unbound_effect_authority_fact() -> bool:
    with current_effect_mutation_authority() as allowed:
        return bool(allowed)


def _first_bind_gap_facts() -> dict[str, Any]:
    def page(target_id: str) -> dict[str, Any]:
        return {
            "id": target_id,
            "type": "page",
            "url": f"https://example.test/{target_id}",
            "webSocketDebuggerUrl": f"ws://127.0.0.1/devtools/page/{target_id}",
        }

    host = CdpReadOnlyBrowserHost(
        "http://127.0.0.1:9222",
        target_id="",
        http_get_json=lambda _url: [page("target-A")],
    )
    actuator = CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="",
        http_get_json=lambda _url: [page("target-B")],
    )
    observed = str(host._resolve_target()["id"])  # noqa: SLF001 - qualification probe
    would_dispatch = str(actuator._resolve_target()["id"])  # noqa: SLF001 - no dispatch occurs
    return {
        "perception_unconfigured": host._configured_target_id == "",  # noqa: SLF001
        "actuator_unconfigured": actuator._configured_target_id == "",  # noqa: SLF001
        "perception_candidate": observed,
        "actuator_candidate": would_dispatch,
        "identity_gap_observed": observed != would_dispatch,
    }


def _provider_surface_gap_facts() -> dict[str, Any]:
    provider_source = inspect.getsource(LoopEngine._project_request_tools)
    discovery_source = inspect.getsource(GetToolSchemaTool.execute)
    factory_source = (ROOT / "src/llm_loop/factory.py").read_text(encoding="utf-8")
    legacy = (
        "browser_action",
        "browser_semantic_execute",
        "browser_semantic_operation",
    )
    return {
        "main_projection_reads_discovery_scope": "current_tool_discovery_scope" in provider_source,
        "get_tool_schema_reads_discovery_scope": "current_tool_discovery_scope" in discovery_source,
        "legacy_tools_registered_when_browser_action_enabled": all(
            f'"{name}"' in factory_source for name in legacy
        ),
    }


def _inner_id_prerequisite_facts() -> dict[str, Any]:
    grounding_ref = "grounding://browser/v0.1/red/object/el_deadbeef"
    args = {"text": "same", "mode": "replace"}
    first = BrowserSemanticExecuteTool._action_id(  # noqa: SLF001
        verb="fill", target_ref=grounding_ref, args=args
    )
    second = BrowserSemanticExecuteTool._action_id(  # noqa: SLF001
        verb="fill", target_ref=grounding_ref, args=dict(args)
    )
    with tempfile.TemporaryDirectory(prefix="p4live-red-receipts-") as td:
        receipts = BrowserActionReceiptStore(Path(td))
        first_reserve = receipts.reserve("s1", first, "fp")
        second_reserve = receipts.reserve("s1", first, "fp")
    return {
        "groundingref_inner_action_id_deterministic": first == second,
        "groundingref_action_id": first,
        "first_reservation": first_reserve,
        "duplicate_reservation_rejected": not second_reserve,
    }


def _execution_bridge_facts() -> dict[str, Any]:
    journal_source = inspect.getsource(ToolExecutionJournal)
    action_source = inspect.getsource(BrowserActionAdapter)
    receipt_source = inspect.getsource(BrowserActionReceiptStore)
    required = ("action_ref", "grounding_ref", "inner_action_id", "browser_target")
    return {
        "journal_mentions_action_ref": "action_ref" in journal_source.lower(),
        "journal_mentions_inner_action_id": "inner_action_id" in journal_source,
        "browser_action_mentions_execution_id": "execution_id" in action_source,
        "browser_receipt_mentions_tool_call_id": "tool_call_id" in receipt_source,
        "required_bridge_tokens_jointly_present": all(
            token in (journal_source + action_source + receipt_source).lower()
            for token in required
        ),
    }


def _wal_recovery_facts() -> dict[str, Any]:
    source = inspect.getsource(ToolExecutionJournal)
    return {
        "started_unknown_state_exists": "started_outcome_unknown" in source,
        "auto_reexecute_false_exists": '"auto_reexecuted": False' in source,
        "browser_receipt_store_consulted": "BrowserActionReceiptStore" in source,
        "browser_action_id_consulted": "action_id" in source,
        "action_ref_consulted": "action_ref" in source.lower(),
    }


def _existing_version_guard_facts() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="p4live-red-version-") as td:
        adapter = BrowserPerceptionAdapter(
            store=BrowserPerceptionStore(
                Path(td) / "browser", retention_seconds=60, now_fn=lambda: 1_000.0
            )
        )
        before = adapter.snapshot("s1", _fixtures()["base"])
        after = adapter.snapshot("s1", _fixtures()["navigate"])
        target = _find_named_object(before, "Submit")
        assessment = adapter.assess_version_precondition(
            "s1",
            expected_version=str(before["snapshot"]["snapshot_id"]),
            observed_version=str(after["snapshot"]["snapshot_id"]),
            version_scope="object",
            scope_ref=str(target["scope_ref"]),
            target_id=str(target["id"]),
        )
        return {
            "result": assessment.get("result"),
            "reason": assessment.get("reason"),
            "automatic_refresh_performed": assessment.get("automatic_refresh_performed"),
            "silent_rebind_performed": assessment.get("silent_rebind_performed"),
        }


def _feature_flag_facts() -> dict[str, Any]:
    config_source = (ROOT / "src/llm_loop/config.py").read_text(encoding="utf-8")
    factory_source = (ROOT / "src/llm_loop/factory.py").read_text(encoding="utf-8")
    return {
        "legacy_browser_action_flag_exists": "browser_action_enabled" in config_source,
        "actionref_feature_flag_exists": (
            "action_ref_enabled" in config_source.lower()
            or "actionref_enabled" in config_source.lower()
            or "action_ref_enabled" in factory_source.lower()
            or "actionref_enabled" in factory_source.lower()
        ),
    }


def _missing_actionref_result(row_id: str, code: str, detail: str, **facts: Any) -> ProbeResult:
    mentions = _production_actionref_mentions()
    return ProbeResult(
        row_id=row_id,
        contract_satisfied=bool(mentions),
        failure_code="production_actionref_unexpectedly_present" if mentions else code,
        detail=("production ActionRef source unexpectedly exists" if mentions else detail),
        facts={"production_actionref_source_mentions": list(mentions), **facts},
    )


def probe_r01() -> ProbeResult:
    facts = _perception_projection_facts()
    if not facts["snapshot_persisted"]:
        return ProbeResult("P4L-R01", False, "harness_snapshot_not_persisted", "snapshot fixture failed to persist", facts)
    satisfied = bool(facts["resource_action_ref_present"] or facts["object_action_ref_count"])
    return ProbeResult(
        "P4L-R01",
        satisfied,
        "contract_present" if satisfied else "actionref_issuer_absent_after_persist",
        "persisted production perception has no model-visible ActionRef annotation",
        facts,
    )


def probe_r02() -> ProbeResult:
    facts = _grounding_exact_hydration_facts()
    return _missing_actionref_result(
        "P4L-R02",
        "actionref_exact_resolver_absent",
        "GroundingRef exact hydration exists, but no production ActionRef exact resolver exists",
        **facts,
    )


def probe_r03() -> ProbeResult:
    facts = _grounding_exact_hydration_facts()
    return _missing_actionref_result(
        "P4L-R03",
        "actionref_session_fence_absent",
        "GroundingRef is session fenced, but no ActionRef owner-session fence exists",
        **facts,
    )


def probe_r04() -> ProbeResult:
    return _missing_actionref_result(
        "P4L-R04",
        "actionref_workspace_fence_absent",
        "no production ActionRef record/resolver exists to bind canonical workspace identity",
    )


def probe_r05() -> ProbeResult:
    return _missing_actionref_result(
        "P4L-R05",
        "actionref_run_lifetime_fence_absent",
        "no production ActionRef record exists to bind origin run generation or invalidate at run termination",
    )


def probe_r06() -> ProbeResult:
    return _missing_actionref_result(
        "P4L-R06",
        "actionref_expiry_fence_absent",
        "no production ActionRef lifetime exists to cap alias expiry by source snapshot expiry",
    )


def probe_r07() -> ProbeResult:
    return _missing_actionref_result(
        "P4L-R07",
        "actionref_browser_incarnation_fence_absent",
        "no production ActionRef record binds Browser runtime generation/nonce",
    )


def probe_r08() -> ProbeResult:
    return _missing_actionref_result(
        "P4L-R08",
        "actionref_kind_fence_absent",
        "existing GroundingRef compiler validates projection kind, but ActionRef target_kind does not exist in production",
    )


def probe_r09() -> ProbeResult:
    return _missing_actionref_result(
        "P4L-R09",
        "actionref_integrity_fence_absent",
        "qualification-only FCR bindings have integrity, but production has no ActionRef binding integrity record",
    )


def probe_r10() -> ProbeResult:
    unbound_allowed = _unbound_effect_authority_fact()
    mentions = _production_actionref_mentions()
    satisfied = bool(mentions) and not unbound_allowed
    return ProbeResult(
        "P4L-R10",
        satisfied,
        "contract_present" if satisfied else "actionref_effect_binding_requirement_absent",
        "legacy direct mutation remains allowed without ToolExecutionJournal binding and no ActionRef-specific rejection exists",
        {
            "unbound_current_effect_mutation_authority": unbound_allowed,
            "production_actionref_source_mentions": list(mentions),
        },
    )


def probe_r11() -> ProbeResult:
    journal_source = inspect.getsource(ToolExecutionJournal)
    return _missing_actionref_result(
        "P4L-R11",
        "actionref_revocation_wiring_absent",
        "generic effect binding revocation exists, but there is no ActionRef mutation tool wired through it",
        generic_revocation_primitive_present=("_revoked" in journal_source and "effect_mutation_authority" in journal_source),
    )


def probe_r12() -> ProbeResult:
    facts = _first_bind_gap_facts()
    satisfied = not bool(facts["identity_gap_observed"])
    return ProbeResult(
        "P4L-R12",
        satisfied,
        "contract_present" if satisfied else "browser_target_independent_first_bind_gap",
        "perception and mutation actuator independently choose different sole-page targets when both are initially unbound",
        facts,
    )


def probe_r13() -> ProbeResult:
    facts = _provider_surface_gap_facts()
    satisfied = bool(
        facts["main_projection_reads_discovery_scope"]
        and facts["get_tool_schema_reads_discovery_scope"]
        and not facts["legacy_tools_registered_when_browser_action_enabled"]
    )
    return ProbeResult(
        "P4L-R13",
        satisfied,
        "contract_present" if satisfied else "main_provider_legacy_browser_surface_gap",
        "main LoopEngine provider projection ignores current_tool_discovery_scope while legacy Browser mutation tools remain registered",
        facts,
    )


def probe_r14() -> ProbeResult:
    facts = _inner_id_prerequisite_facts()
    return _missing_actionref_result(
        "P4L-R14",
        "actionref_inner_action_id_bridge_absent",
        "existing GroundingRef action_id and reservation are deterministic/at-most-once, but no ActionRef resolver delegates into that identity basis",
        **facts,
    )


def probe_r15() -> ProbeResult:
    facts = _execution_bridge_facts()
    satisfied = bool(facts["required_bridge_tokens_jointly_present"])
    return ProbeResult(
        "P4L-R15",
        satisfied,
        "contract_present" if satisfied else "predispatch_execution_bridge_absent",
        "ToolExecutionJournal and BrowserActionReceiptStore have no durable pre-dispatch identity join",
        facts,
    )


def probe_r16() -> ProbeResult:
    facts = _wal_recovery_facts()
    satisfied = bool(facts["browser_receipt_store_consulted"] and facts["action_ref_consulted"])
    return ProbeResult(
        "P4L-R16",
        satisfied,
        "contract_present" if satisfied else "prepare_without_running_recovery_contract_absent",
        "outer WAL has no ActionRef execution-binding state that can distinguish prepared-without-Browser-running recovery",
        facts,
    )


def probe_r17() -> ProbeResult:
    facts = _wal_recovery_facts()
    satisfied = bool(facts["browser_receipt_store_consulted"] and facts["browser_action_id_consulted"])
    return ProbeResult(
        "P4L-R17",
        satisfied,
        "contract_present" if satisfied else "running_unknown_browser_correlation_absent",
        "outer WAL safely marks started outcome unknown/no replay, but cannot correlate an ActionRef Browser running receipt",
        facts,
    )


def probe_r18() -> ProbeResult:
    facts = _wal_recovery_facts()
    satisfied = bool(facts["browser_receipt_store_consulted"] and facts["browser_action_id_consulted"])
    return ProbeResult(
        "P4L-R18",
        satisfied,
        "contract_present" if satisfied else "terminal_browser_outer_wal_correlation_absent",
        "no exact Browser terminal receipt -> outer execution correlation path exists",
        facts,
    )


def probe_r19() -> ProbeResult:
    facts = _existing_version_guard_facts()
    guard_ok = (
        facts["result"] == "stale"
        and facts["automatic_refresh_performed"] is False
        and facts["silent_rebind_performed"] is False
    )
    mentions = _production_actionref_mentions()
    satisfied = guard_ok and bool(mentions)
    return ProbeResult(
        "P4L-R19",
        satisfied,
        "contract_present" if satisfied else "actionref_version_guard_delegation_absent",
        "existing GroundingRef stale guard is fail-closed, but no ActionRef path delegates into it",
        {"existing_version_guard_ok": guard_ok, "production_actionref_source_mentions": list(mentions), **facts},
    )


def probe_r20() -> ProbeResult:
    facts = _feature_flag_facts()
    satisfied = bool(facts["actionref_feature_flag_exists"])
    return ProbeResult(
        "P4L-R20",
        satisfied,
        "contract_present" if satisfied else "actionref_disabled_compatibility_gate_absent",
        "existing GroundingRef Browser path exists, but there is no ActionRef feature flag/wiring whose disabled mode can prove compatibility",
        facts,
    )


_PROBES: dict[str, Callable[[], ProbeResult]] = {
    "P4L-R01": probe_r01,
    "P4L-R02": probe_r02,
    "P4L-R03": probe_r03,
    "P4L-R04": probe_r04,
    "P4L-R05": probe_r05,
    "P4L-R06": probe_r06,
    "P4L-R07": probe_r07,
    "P4L-R08": probe_r08,
    "P4L-R09": probe_r09,
    "P4L-R10": probe_r10,
    "P4L-R11": probe_r11,
    "P4L-R12": probe_r12,
    "P4L-R13": probe_r13,
    "P4L-R14": probe_r14,
    "P4L-R15": probe_r15,
    "P4L-R16": probe_r16,
    "P4L-R17": probe_r17,
    "P4L-R18": probe_r18,
    "P4L-R19": probe_r19,
    "P4L-R20": probe_r20,
}


def run_probe(row_id: str) -> ProbeResult:
    probe = _PROBES.get(row_id)
    if probe is None:
        raise KeyError(f"unknown P4-LIVE RED row: {row_id}")
    try:
        return probe()
    except Exception as exc:  # noqa: BLE001 - classify harness breakage explicitly.
        return ProbeResult(
            row_id=row_id,
            contract_satisfied=False,
            failure_code="harness_error",
            detail=f"{type(exc).__name__}: {exc}",
            facts={"exception_type": type(exc).__name__},
        )

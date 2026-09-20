"""Deterministic production probes for the frozen P4-LIVE ActionRef RED contracts.

This module is deliberately qualification-only.  It never performs a real Browser
action, never sends a model request, and never mutates production state.  A probe may
use temporary local stores or inspect existing production objects/source in order to
distinguish an expected missing production capability from a broken RED harness.
"""

from __future__ import annotations

import importlib
import inspect
import json
import re
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
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
PHASE1_GREEN_IDS = (
    "P4L-R01",
    "P4L-R02",
    "P4L-R03",
    "P4L-R04",
    "P4L-R05",
    "P4L-R06",
    "P4L-R07",
    "P4L-R08",
    "P4L-R09",
    "P4L-R20",
)


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


def _action_ref_module() -> Any | None:
    try:
        return importlib.import_module("llm_loop.browser.action_ref")
    except ModuleNotFoundError as exc:
        if exc.name == "llm_loop.browser.action_ref":
            return None
        raise


@contextmanager
def _action_ref_fixture() -> Any:
    module = _action_ref_module()
    if module is None:
        raise RuntimeError("production ActionRef core is absent")
    clock = [1_000.0]
    with tempfile.TemporaryDirectory(prefix="p4live-green1-") as td:
        root = Path(td)
        perception_store = BrowserPerceptionStore(
            root / "browser",
            retention_seconds=60,
            now_fn=lambda: clock[0],
        )
        binding_store = module.ActionRefBindingStore(
            root / "action_refs",
            now_fn=lambda: clock[0],
        )
        issuer = module.ActionRefIssuer(
            binding_store=binding_store,
            perception_store=perception_store,
        )
        issue_context = module.ActionRefIssueContext(
            workspace_scope="/workspace/A",
            origin_run_generation="run-generation-A",
        )
        adapter = BrowserPerceptionAdapter(
            store=perception_store,
            action_ref_issuer=issuer,
            action_ref_context_getter=lambda: issue_context,
        )
        projection = adapter.snapshot(
            "p4live-session-A",
            _fixtures()["base"],
            projection_limit=100,
        )
        resolver = module.ActionRefResolver(
            binding_store=binding_store,
            perception_store=perception_store,
        )
        target = _find_named_object(projection, "Submit")
        resolve_context = module.ActionRefResolveContext(
            session_id="p4live-session-A",
            workspace_scope="/workspace/A",
            current_run_generation="run-generation-A",
            run_active=True,
        )
        yield {
            "module": module,
            "clock": clock,
            "root": root,
            "perception_store": perception_store,
            "binding_store": binding_store,
            "issuer": issuer,
            "issue_context": issue_context,
            "adapter": adapter,
            "projection": projection,
            "resolver": resolver,
            "target": target,
            "resolve_context": resolve_context,
        }


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
    if _action_ref_module() is None:
        facts = _perception_projection_facts()
        return ProbeResult(
            "P4L-R01",
            False,
            "actionref_issuer_absent_after_persist",
            "persisted production perception has no model-visible ActionRef annotation",
            facts,
        )
    with _action_ref_fixture() as fixture:
        projection = fixture["projection"]
        store = fixture["perception_store"]
        snapshot_id = str(projection["snapshot"]["snapshot_id"])
        persisted = store.load_snapshot_bundle("p4live-session-A", snapshot_id) is not None
        resource_ref = str(projection.get("resource_action_ref") or "")
        object_refs = [
            str(obj.get("action_ref") or "")
            for obj in projection.get("objects", [])
            if isinstance(obj, dict) and obj.get("action_ref")
        ]
        issued_again = fixture["issuer"].annotate_projection(
            session_id="p4live-session-A",
            projection=projection,
            context=fixture["issue_context"],
        )
        original_by_id = {
            str(obj.get("id") or ""): str(obj.get("action_ref") or "")
            for obj in projection.get("objects", [])
            if isinstance(obj, dict) and obj.get("action_ref")
        }
        repeated_by_id = {
            str(obj.get("id") or ""): str(obj.get("action_ref") or "")
            for obj in issued_again.get("objects", [])
            if isinstance(obj, dict) and obj.get("action_ref")
        }
        handles = [resource_ref, *object_refs]
        high_entropy = bool(handles) and all(
            re.fullmatch(r"actionref://browser/v0\.1/[0-9a-f]{32}", handle)
            for handle in handles
        )
        opaque = all(
            "Submit" not in handle
            and "grounding://" not in handle
            and "p4live-session-A" not in handle
            for handle in handles
        )
        same_resource_ref = issued_again.get("resource_action_ref") == resource_ref
        same_objects = repeated_by_id == original_by_id
        facts = {
            "snapshot_persisted": persisted,
            "resource_action_ref_present": bool(resource_ref),
            "object_action_ref_count": len(object_refs),
            "opaque_128bit_handles": high_entropy and opaque,
            "same_binding_resource_idempotent": same_resource_ref,
            "same_binding_object_idempotent": same_objects,
        }
        satisfied = all(
            (persisted, bool(resource_ref), bool(object_refs), high_entropy, opaque, same_resource_ref, same_objects)
        )
        return ProbeResult(
            "P4L-R01",
            satisfied,
            "contract_present" if satisfied else "actionref_issuer_absent_after_persist",
            "persisted Browser projection issues stable opaque ActionRefs after exact snapshot persistence",
            facts,
        )


def probe_r02() -> ProbeResult:
    if _action_ref_module() is None:
        return _missing_actionref_result(
            "P4L-R02",
            "actionref_exact_resolver_absent",
            "GroundingRef exact hydration exists, but no production ActionRef exact resolver exists",
            **_grounding_exact_hydration_facts(),
        )
    with _action_ref_fixture() as fixture:
        target = fixture["target"]
        resolution = fixture["resolver"].resolve(
            str(target["action_ref"]),
            context=fixture["resolve_context"],
            expected_kind="object",
        )
        exact = resolution.grounding_ref == str(target["grounding_ref"])
        return ProbeResult(
            "P4L-R02",
            exact,
            "contract_present" if exact else "actionref_exact_resolver_absent",
            "exact ActionRef resolves only to its stored byte-identical GroundingRef",
            {"byte_identical_grounding_ref": exact, "resolved_target_kind": resolution.target_kind},
        )


def probe_r03() -> ProbeResult:
    if _action_ref_module() is None:
        return _missing_actionref_result(
            "P4L-R03",
            "actionref_session_fence_absent",
            "GroundingRef is session fenced, but no ActionRef owner-session fence exists",
            **_grounding_exact_hydration_facts(),
        )
    with _action_ref_fixture() as fixture:
        module = fixture["module"]
        ctx = module.ActionRefResolveContext(
            session_id="p4live-session-B",
            workspace_scope="/workspace/A",
            current_run_generation="run-generation-A",
            run_active=True,
        )
        code = ""
        try:
            fixture["resolver"].resolve(
                str(fixture["target"]["action_ref"]), context=ctx, expected_kind="object"
            )
        except module.ActionRefError as exc:
            code = exc.code
        satisfied = code == "action_ref_session_mismatch"
        return ProbeResult(
            "P4L-R03",
            satisfied,
            "contract_present" if satisfied else "actionref_session_fence_absent",
            "cross-session ActionRef resolution fails closed before any mutation path exists",
            {"rejection_code": code},
        )


def probe_r04() -> ProbeResult:
    if _action_ref_module() is None:
        return _missing_actionref_result(
            "P4L-R04",
            "actionref_workspace_fence_absent",
            "no production ActionRef record/resolver exists to bind canonical workspace identity",
        )
    with _action_ref_fixture() as fixture:
        module = fixture["module"]
        ctx = module.ActionRefResolveContext(
            session_id="p4live-session-A",
            workspace_scope="/workspace/B",
            current_run_generation="run-generation-A",
            run_active=True,
        )
        code = ""
        try:
            fixture["resolver"].resolve(
                str(fixture["target"]["action_ref"]), context=ctx, expected_kind="object"
            )
        except module.ActionRefError as exc:
            code = exc.code
        satisfied = code == "action_ref_workspace_mismatch"
        return ProbeResult(
            "P4L-R04",
            satisfied,
            "contract_present" if satisfied else "actionref_workspace_fence_absent",
            "workspace identity mismatch rejects exact ActionRef resolution",
            {"rejection_code": code},
        )


def probe_r05() -> ProbeResult:
    if _action_ref_module() is None:
        return _missing_actionref_result(
            "P4L-R05",
            "actionref_run_lifetime_fence_absent",
            "no production ActionRef record exists to bind origin run generation or invalidate at run termination",
        )
    with _action_ref_fixture() as fixture:
        module = fixture["module"]
        target_ref = str(fixture["target"]["action_ref"])
        contexts = (
            module.ActionRefResolveContext(
                session_id="p4live-session-A",
                workspace_scope="/workspace/A",
                current_run_generation="run-generation-B",
                run_active=True,
            ),
            module.ActionRefResolveContext(
                session_id="p4live-session-A",
                workspace_scope="/workspace/A",
                current_run_generation="run-generation-A",
                run_active=False,
            ),
        )
        codes: list[str] = []
        for ctx in contexts:
            try:
                fixture["resolver"].resolve(target_ref, context=ctx, expected_kind="object")
            except module.ActionRefError as exc:
                codes.append(exc.code)
        satisfied = codes == [
            "action_ref_run_generation_mismatch",
            "action_ref_run_generation_mismatch",
        ]
        return ProbeResult(
            "P4L-R05",
            satisfied,
            "contract_present" if satisfied else "actionref_run_lifetime_fence_absent",
            "run-generation mismatch and explicit inactive-run resolution both fail closed",
            {"rejection_codes": codes},
        )


def probe_r06() -> ProbeResult:
    if _action_ref_module() is None:
        return _missing_actionref_result(
            "P4L-R06",
            "actionref_expiry_fence_absent",
            "no production ActionRef lifetime exists to cap alias expiry by source snapshot expiry",
        )
    with _action_ref_fixture() as fixture:
        module = fixture["module"]
        fixture["clock"][0] = 1_061.0
        code = ""
        try:
            fixture["resolver"].resolve(
                str(fixture["target"]["action_ref"]),
                context=fixture["resolve_context"],
                expected_kind="object",
            )
        except module.ActionRefError as exc:
            code = exc.code
        satisfied = code == "action_ref_expired"
        return ProbeResult(
            "P4L-R06",
            satisfied,
            "contract_present" if satisfied else "actionref_expiry_fence_absent",
            "ActionRef expiry is bounded by the persisted source snapshot expiry",
            {"rejection_code": code},
        )


def probe_r07() -> ProbeResult:
    if _action_ref_module() is None:
        return _missing_actionref_result(
            "P4L-R07",
            "actionref_browser_incarnation_fence_absent",
            "no production ActionRef record binds Browser runtime generation/nonce",
        )
    with _action_ref_fixture() as fixture:
        module = fixture["module"]
        new_store = BrowserPerceptionStore(
            fixture["root"] / "browser",
            retention_seconds=60,
            now_fn=lambda: fixture["clock"][0],
        )
        resolver = module.ActionRefResolver(
            binding_store=fixture["binding_store"], perception_store=new_store
        )
        code = ""
        try:
            resolver.resolve(
                str(fixture["target"]["action_ref"]),
                context=fixture["resolve_context"],
                expected_kind="object",
            )
        except module.ActionRefError as exc:
            code = exc.code
        satisfied = code == "action_ref_browser_runtime_mismatch"
        return ProbeResult(
            "P4L-R07",
            satisfied,
            "contract_present" if satisfied else "actionref_browser_incarnation_fence_absent",
            "Browser runtime generation/nonce change rejects old ActionRef",
            {"rejection_code": code},
        )


def probe_r08() -> ProbeResult:
    if _action_ref_module() is None:
        return _missing_actionref_result(
            "P4L-R08",
            "actionref_kind_fence_absent",
            "existing GroundingRef compiler validates projection kind, but ActionRef target_kind does not exist in production",
        )
    with _action_ref_fixture() as fixture:
        module = fixture["module"]
        code = ""
        try:
            fixture["resolver"].resolve(
                str(fixture["target"]["action_ref"]),
                context=fixture["resolve_context"],
                expected_kind="resource",
            )
        except module.ActionRefError as exc:
            code = exc.code
        satisfied = code == "action_ref_kind_mismatch"
        return ProbeResult(
            "P4L-R08",
            satisfied,
            "contract_present" if satisfied else "actionref_kind_fence_absent",
            "typed expected-kind mismatch rejects exact ActionRef",
            {"rejection_code": code},
        )


def probe_r09() -> ProbeResult:
    if _action_ref_module() is None:
        return _missing_actionref_result(
            "P4L-R09",
            "actionref_integrity_fence_absent",
            "qualification-only FCR bindings have integrity, but production has no ActionRef binding integrity record",
        )
    with _action_ref_fixture() as fixture:
        module = fixture["module"]
        action_ref = str(fixture["target"]["action_ref"])
        record_path = fixture["binding_store"].record_path(action_ref)
        raw = json.loads(record_path.read_text(encoding="utf-8"))
        raw["grounding_ref"] = "grounding://browser/v0.1/tampered"
        record_path.write_text(
            json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        code = ""
        try:
            fixture["resolver"].resolve(
                action_ref,
                context=fixture["resolve_context"],
                expected_kind="object",
            )
        except module.ActionRefError as exc:
            code = exc.code
        satisfied = code == "action_ref_integrity_error"
        return ProbeResult(
            "P4L-R09",
            satisfied,
            "contract_present" if satisfied else "actionref_integrity_fence_absent",
            "tampering any signed binding field invalidates the ActionRef",
            {"rejection_code": code},
        )


def probe_r10() -> ProbeResult:
    unbound_allowed = _unbound_effect_authority_fact()
    factory_source = (ROOT / "src/llm_loop/factory.py").read_text(encoding="utf-8")
    typed_actionref_tools_wired = all(
        f'"{name}"' in factory_source
        for name in (
            "browser_semantic_click",
            "browser_semantic_fill",
            "browser_semantic_select",
            "browser_semantic_scroll",
            "browser_semantic_navigate",
        )
    )
    satisfied = typed_actionref_tools_wired and not unbound_allowed
    return ProbeResult(
        "P4L-R10",
        satisfied,
        "contract_present" if satisfied else "actionref_effect_binding_requirement_absent",
        "legacy direct mutation remains allowed without ToolExecutionJournal binding and no ActionRef-specific rejection exists",
        {
            "unbound_current_effect_mutation_authority": unbound_allowed,
            "typed_actionref_tools_wired": typed_actionref_tools_wired,
        },
    )


def probe_r11() -> ProbeResult:
    journal_source = inspect.getsource(ToolExecutionJournal)
    factory_source = (ROOT / "src/llm_loop/factory.py").read_text(encoding="utf-8")
    actionref_mutation_wired = "browser_semantic_click" in factory_source
    generic_revocation = "_revoked" in journal_source and "effect_mutation_authority" in journal_source
    satisfied = actionref_mutation_wired and generic_revocation
    return ProbeResult(
        "P4L-R11",
        satisfied,
        "contract_present" if satisfied else "actionref_revocation_wiring_absent",
        "generic effect binding revocation exists, but there is no ActionRef mutation tool wired through it",
        {
            "generic_revocation_primitive_present": generic_revocation,
            "actionref_mutation_wired": actionref_mutation_wired,
        },
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
    factory_source = (ROOT / "src/llm_loop/factory.py").read_text(encoding="utf-8")
    bridge_wired = "browser_semantic_click" in factory_source
    satisfied = bool(
        bridge_wired
        and facts["groundingref_inner_action_id_deterministic"]
        and facts["duplicate_reservation_rejected"]
    )
    return ProbeResult(
        "P4L-R14",
        satisfied,
        "contract_present" if satisfied else "actionref_inner_action_id_bridge_absent",
        "existing GroundingRef action_id and reservation are deterministic/at-most-once, but no ActionRef mutation path delegates into that identity basis",
        {**facts, "actionref_compiler_bridge_wired": bridge_wired},
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
    factory_source = (ROOT / "src/llm_loop/factory.py").read_text(encoding="utf-8")
    mutation_bridge_wired = "browser_semantic_click" in factory_source
    satisfied = guard_ok and mutation_bridge_wired
    return ProbeResult(
        "P4L-R19",
        satisfied,
        "contract_present" if satisfied else "actionref_version_guard_delegation_absent",
        "existing GroundingRef stale guard is fail-closed, but no ActionRef path delegates into it",
        {"existing_version_guard_ok": guard_ok, "actionref_mutation_bridge_wired": mutation_bridge_wired, **facts},
    )


def probe_r20() -> ProbeResult:
    facts = _feature_flag_facts()
    default_projection = _perception_projection_facts()
    config_source = (ROOT / "src/llm_loop/config.py").read_text(encoding="utf-8")
    default_off = "browser_action_ref_enabled: bool = False" in config_source
    untouched = (
        not default_projection["resource_action_ref_present"]
        and default_projection["object_action_ref_count"] == 0
    )
    satisfied = bool(facts["actionref_feature_flag_exists"] and default_off and untouched)
    return ProbeResult(
        "P4L-R20",
        satisfied,
        "contract_present" if satisfied else "actionref_disabled_compatibility_gate_absent",
        "existing GroundingRef Browser path exists, but there is no ActionRef feature flag/wiring whose disabled mode can prove compatibility",
        {**facts, "feature_default_off": default_off, "default_projection_unchanged": untouched},
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

"""Qualification-only Browser Python-oracle versus Semantic Logic P3 shadow replay.

This module deliberately lives outside ``src/llm_loop``.  It constructs current
Browser observations once, derives the native mechanical oracle from those persisted
observations, projects the same facts into the frozen P2 RulePack, and compares only
closed semantic relations.  It has no runtime registration or production authority.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from llm_loop.browser.action import (
    BrowserActionAdapter,
    BrowserActionReceiptStore,
    BrowserDispatchResult,
)
from llm_loop.browser.perception import (
    BrowserPerceptionAdapter,
    BrowserPerceptionStore,
    _semantic_changed_fields,
)
from llm_loop.semantic_logic.rules import evaluate_rulepack
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool

ROOT = Path(__file__).resolve().parents[2]
PACK = json.loads(
    (ROOT / "docs/SMC-SEMANTIC-LOGIC-P2-RULEPACK-v0.1.json").read_text(
        encoding="utf-8"
    )
)
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(
        encoding="utf-8"
    )
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError(type(value).__name__)


def _fact(
    predicate: str,
    value: Any,
    *,
    subject: str = "ctx:p3",
    provenance_kind: str = "observed",
) -> dict[str, Any]:
    observed = provenance_kind == "observed"
    identity = {
        "predicate": predicate,
        "value": value,
        "subject": subject,
        "provenance_kind": provenance_kind,
    }
    return {
        "kind": "fact",
        "schema": "smc.semantic_fact.v0.1",
        "fact_id": f"p3fact-{_sha256(identity)[:24]}",
        "domain": "browser",
        "subject": subject,
        "predicate": predicate,
        "value": value,
        "value_type": _value_type(value),
        "truth_state": "asserted",
        "context": {
            "domain": "browser",
            "scope_ref": "scope:p3" if observed else None,
            "observed_version": "observation:p3" if observed else None,
            "snapshot_id": "observation:p3" if observed else None,
            "sensor_contract_ref": "sensor:browser:p3" if observed else None,
        },
        "observation_completeness": {"complete": True, "reasons": []},
        "projection_complete": True,
        "provenance": {
            "kind": provenance_kind,
            "source": f"p3:{provenance_kind}",
            "grounding_ref": f"grounding://p3/{_sha256(identity)[:16]}" if observed else None,
            "observed_version": "observation:p3" if observed else None,
            "derivation_ref": None,
            "rule_ref": None,
            "input_fact_refs": [],
        },
    }


def _add(
    facts: list[dict[str, Any]],
    predicate: str,
    value: Any,
    *,
    subject: str = "ctx:p3",
    provenance_kind: str = "observed",
) -> None:
    facts.append(
        _fact(
            predicate,
            value,
            subject=subject,
            provenance_kind=provenance_kind,
        )
    )


def _input_document(facts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "smc.rule_engine_input.v0.1",
        "authority": "shadow_only",
        "production_consumed": False,
        "domain": "browser",
        "context_ref": "ctx:p3-shadow",
        "facts": facts,
    }


class _Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _adapter(root: Path, *, clock: _Clock | None = None) -> BrowserPerceptionAdapter:
    root.mkdir(parents=True, exist_ok=True)
    return BrowserPerceptionAdapter(
        store=BrowserPerceptionStore(
            root,
            retention_seconds=60,
            now_fn=clock if clock is not None else _Clock(),
        ),
        capture_node_cap=10_000,
    )


def _dom_named(result: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [
        obj
        for obj in result["objects"]
        if obj.get("attributes", {}).get("name") == name
        and "dom" in obj.get("coverage", {}).get("sources", [])
    ]
    if len(matches) != 1:
        raise ValueError(f"expected_one_dom_object:{name}:{len(matches)}")
    return dict(matches[0])


def _snapshot_id(result: dict[str, Any]) -> str:
    return str(result["snapshot"]["snapshot_id"])


def _page_scope_fact(result: dict[str, Any]) -> dict[str, Any]:
    return next(dict(row) for row in result["scope_facts"] if row.get("kind") == "page")


def _add_scope_facts(facts: list[dict[str, Any]], result: dict[str, Any]) -> None:
    for row in result["scope_facts"]:
        subject = f"scope-node:{row['scope_ref']}"
        _add(facts, "scope.node.scope_ref", str(row["scope_ref"]), subject=subject)
        _add(
            facts,
            "scope.node.parent_scope_ref",
            row.get("parent_scope_ref"),
            subject=subject,
        )
        _add(facts, "scope.node.kind", str(row["kind"]), subject=subject)


def _add_coverage_facts(
    facts: list[dict[str, Any]], result: dict[str, Any]
) -> None:
    completeness = dict(result["snapshot"].get("completeness") or {})
    complete = bool(completeness.get("complete"))
    reasons = [str(value) for value in completeness.get("reasons", [])]
    _add(facts, "coverage.expected_sources", ["dom", "ax"])
    _add(facts, "coverage.observed_sources", ["dom", "ax"])
    _add(facts, "coverage.blind_spots", [] if complete else reasons)
    _add(facts, "coverage.sensor_truncated", not complete)


def _grounding_facts(
    *,
    request: dict[str, Any],
    target: dict[str, Any],
    availability: str,
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    _add(
        facts,
        "request.target_ref",
        str(request["target_ref"]),
        provenance_kind="model_asserted",
    )
    _add(
        facts,
        "request.verb",
        str(request["verb"]),
        provenance_kind="model_asserted",
    )
    _add(
        facts,
        "request.args",
        dict(request["args"]),
        provenance_kind="model_asserted",
    )
    _add(facts, "grounding.availability", availability)
    _add(facts, "grounding.ref", str(request["target_ref"]))
    _add(facts, "grounding.kind", "object")
    _add(facts, "grounding.projection_ref", str(target["grounding_ref"]))
    _add(facts, "grounding.target_id", str(target["id"]))
    _add(facts, "grounding.scope_ref", str(target["scope_ref"]))
    _add(facts, "grounding.observed_version", str(target["observed_version"]))
    return facts


def _changed_submit_raw() -> dict[str, Any]:
    raw = copy.deepcopy(FIXTURES["base"])
    for source in ("dom", "ax"):
        for node in raw[source]["nodes"]:
            if node.get("physical_id") == "n-submit":
                node.setdefault("state", {})["enabled"] = False
    return raw


def _without_submit_raw(*, truncated: bool) -> dict[str, Any]:
    raw = copy.deepcopy(FIXTURES["base"])
    for source in ("dom", "ax"):
        raw[source]["nodes"] = [
            node
            for node in raw[source]["nodes"]
            if node.get("physical_id") != "n-submit"
        ]
    if truncated:
        raw["dom"]["truncated"] = True
    return raw


def _version_material(
    root: Path,
    *,
    after_raw: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    adapter = _adapter(root)
    before = adapter.snapshot("p3-version", FIXTURES["base"])
    target = _dom_named(before, "Submit")
    after = adapter.snapshot("p3-version", after_raw)
    native = adapter.assess_version_precondition(
        "p3-version",
        expected_version=_snapshot_id(before),
        observed_version=_snapshot_id(after),
        version_scope="object",
        scope_ref=str(target["scope_ref"]),
        target_id=str(target["id"]),
    )
    oracle = {
        "version.result": native["result"],
        "version.reason": native["reason"],
        "version.comparable": native["comparable"],
        "version.automatic_refresh_performed": native["automatic_refresh_performed"],
        "version.silent_rebind_performed": native["silent_rebind_performed"],
    }

    before_bundle = adapter.store.load_snapshot_bundle("p3-version", _snapshot_id(before))
    after_bundle = adapter.store.load_snapshot_bundle("p3-version", _snapshot_id(after))
    expected_grounding = (before_bundle.get("object_grounding") or {}).get(target["id"])
    observed_grounding = (after_bundle.get("object_grounding") or {}).get(target["id"])
    expected_obj = (
        dict(expected_grounding.get("semantic_object") or {})
        if isinstance(expected_grounding, dict)
        else {}
    )
    observed_obj = (
        dict(observed_grounding.get("semantic_object") or {})
        if isinstance(observed_grounding, dict)
        else {}
    )
    changed_fields = (
        _semantic_changed_fields(expected_obj, observed_obj)
        if expected_obj and observed_obj
        else []
    )
    expected_page = _page_scope_fact(before)
    observed_page = _page_scope_fact(after)
    page_same = all(
        expected_page.get(key) == observed_page.get(key)
        for key in ("scope_ref", "runtime_generation", "page_generation")
    )
    document_same = (
        before["snapshot"]["scope"].get("document_generation")
        == after["snapshot"]["scope"].get("document_generation")
    )
    stable = not (
        isinstance(expected_grounding, dict)
        and expected_grounding.get("identity_basis") == "snapshot_local_ax_identity"
    )

    facts: list[dict[str, Any]] = []
    _add_scope_facts(facts, before)
    _add(
        facts,
        "request.scope_ref",
        str(target["scope_ref"]),
        provenance_kind="model_asserted",
    )
    _add(facts, "target.scope_ref", str(target["scope_ref"]))
    _add_coverage_facts(facts, after)
    _add(facts, "version.scope", "object")
    _add(facts, "version.expected", _snapshot_id(before))
    _add(facts, "version.observed", _snapshot_id(after))
    _add(facts, "version.expected_availability", native["expected_availability"])
    _add(facts, "version.observed_availability", native["observed_availability"])
    _add(facts, "lineage.page_same", page_same)
    _add(facts, "lineage.document_same", document_same)
    _add(facts, "identity.stable", stable)
    _add(facts, "observation.target_present", isinstance(observed_grounding, dict))
    _add(facts, "object.changed_fields", changed_fields)
    _add(facts, "resource.changed_fields", [])
    return oracle, facts


def _grounding_exact(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    adapter = _adapter(root)
    first = adapter.snapshot("p3-grounding", FIXTURES["base"])
    target = _dom_named(first, "Submit")
    request = {"verb": "click", "target_ref": target["grounding_ref"], "args": {}}
    tool = BrowserSemanticExecuteTool(
        perception=adapter,
        action_adapter=cast(BrowserActionAdapter, object()),
        session_id_getter=lambda: "p3-grounding",
    )
    compiled = tool.compile_request("p3-grounding", request)
    hydrated = adapter.hydrate("p3-grounding", str(request["target_ref"]))
    if hydrated.get("availability") != "available":
        raise ValueError("grounding_oracle_unavailable")
    oracle = {
        "binding.status": "bound",
        "binding.version_scope": compiled["version_scope"],
        "action.schema": compiled["schema"],
        "action.domain": compiled["domain"],
        "action.verb": compiled["verb"],
        "action.operation_class": compiled["operation_class"],
        "action.idempotency_class": compiled["idempotency_class"],
        "action.atomicity_class": compiled["atomicity_class"],
        "action.version_scope": compiled["version_scope"],
        "action.version_precondition": compiled["version_precondition"],
    }
    return oracle, _grounding_facts(
        request=request,
        target=target,
        availability=str(hydrated["availability"]),
    )


def _expired_grounding(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    clock = _Clock()
    adapter = _adapter(root, clock=clock)
    first = adapter.snapshot("p3-expired", FIXTURES["base"])
    target = _dom_named(first, "Submit")
    request = {"verb": "click", "target_ref": target["grounding_ref"], "args": {}}
    clock.now += 61
    hydrated = adapter.hydrate("p3-expired", str(target["grounding_ref"]))
    availability = str(hydrated.get("availability") or "unavailable")
    if availability != "expired":
        raise ValueError(f"expected_expired_grounding:{availability}")
    oracle = {
        "binding.status": "indeterminate",
        "binding.reason": "target_ref_expired",
    }
    return oracle, _grounding_facts(
        request=request,
        target=target,
        availability=availability,
    )


def _identity_ambiguity(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result = _adapter(root).snapshot("p3-identity", FIXTURES["fusion_ambiguity"])
    candidate = next(
        obj
        for obj in result["objects"]
        if any("identity_mapping" in row for row in obj.get("coverage", {}).get("conflicts", []))
    )
    conflict = next(
        row
        for row in candidate["coverage"]["conflicts"]
        if row.get("identity_mapping") == "dom_to_ax"
    )
    if conflict.get("resolution") != "unresolved":
        raise ValueError("native_identity_conflict_not_unresolved")
    candidates = [str(row["value"]) for row in conflict["observations"]]
    if len(candidates) < 2:
        raise ValueError("native_identity_conflict_not_ambiguous")
    facts: list[dict[str, Any]] = []
    _add(facts, "identity.mapping_status", "ambiguous")
    _add(facts, "identity.source_candidates", candidates)
    return {
        "identity.binding_status": "unresolved",
        "identity.fusion_performed": False,
        "identity.reason": "ambiguous_physical_identity",
    }, facts


def _source_conflict(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result = _adapter(root).snapshot("p3-conflict", FIXTURES["conflict"])
    target = _dom_named(result, "Save")
    conflict = next(
        row
        for row in target["coverage"]["conflicts"]
        if row.get("field") == "state.enabled"
    )
    observations = sorted(
        [dict(row) for row in conflict["observations"]],
        key=lambda row: _canonical_bytes(row),
    )
    facts: list[dict[str, Any]] = []
    for row in observations:
        subject = f"observation:{row['source']}"
        _add(facts, "observation.subject", str(target["id"]), subject=subject)
        _add(facts, "observation.property", "enabled", subject=subject)
        _add(facts, "observation.source", str(row["source"]), subject=subject)
        _add(facts, "observation.value", row["value"], subject=subject)
        _add(
            facts,
            "observation.grounding_ref",
            str(row["grounding_ref"]),
            subject=subject,
        )
    _add(facts, "resolver.contract", "none")
    return {
        "canonical.value": target["state"]["enabled"],
        "canonical.truth_state": "conflict",
        "conflict.resolution": conflict["resolution"],
        "conflict.source_observations": observations,
    }, facts


def _frame_generation(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    adapter = _adapter(root)
    before = adapter.snapshot("p3-frame", FIXTURES["frame_v1"])
    after = adapter.snapshot("p3-frame", FIXTURES["frame_v2"])
    old = _dom_named(before, "Inner")
    new = _dom_named(after, "Inner")
    if old["id"] == new["id"] or old["scope_ref"] == new["scope_ref"]:
        raise ValueError("native_frame_generation_failed_to_rekey")
    observed = {str(row["scope_ref"]) for row in after["scope_facts"]}
    native_relation = (
        ("match", "exact_scope")
        if old["scope_ref"] == new["scope_ref"]
        else (
            ("mismatch", "target_scope_mismatch")
            if old["scope_ref"] in observed and new["scope_ref"] in observed
            else ("indeterminate", "scope_unobserved")
        )
    )
    facts: list[dict[str, Any]] = []
    _add_scope_facts(facts, after)
    _add(
        facts,
        "request.scope_ref",
        str(old["scope_ref"]),
        provenance_kind="model_asserted",
    )
    _add(facts, "target.scope_ref", str(new["scope_ref"]))
    return {
        "scope.relation": native_relation[0],
        "scope.reason": native_relation[1],
    }, facts


def _partial_absence(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    adapter = _adapter(root)
    before = adapter.snapshot("p3-partial", FIXTURES["base"])
    target = _dom_named(before, "Submit")
    after = adapter.snapshot("p3-partial", _without_submit_raw(truncated=True))
    predicate = {
        "schema": "smc.predicate.v0.1",
        "domain": "browser",
        "scope_ref": target["scope_ref"],
        "target": target["id"],
        "property": "exists",
        "operator": "eq",
        "value": False,
    }
    native = adapter.evaluate_predicate(
        "p3-partial", _snapshot_id(after), predicate
    )
    request = {"verb": "click", "target_ref": target["grounding_ref"], "args": {}}
    hydrated = adapter.hydrate("p3-partial", str(target["grounding_ref"]))
    facts = _grounding_facts(
        request=request,
        target=target,
        availability=str(hydrated["availability"]),
    )
    _add_scope_facts(facts, after)
    for key, value in (
        ("model_condition.scope_ref", predicate["scope_ref"]),
        ("model_condition.target_ref", target["grounding_ref"]),
        ("model_condition.property", predicate["property"]),
        ("model_condition.operator", predicate["operator"]),
        ("model_condition.value", predicate["value"]),
        ("request.scope_ref", predicate["scope_ref"]),
    ):
        _add(facts, key, value, provenance_kind="model_asserted")
    _add(facts, "target.scope_ref", predicate["scope_ref"])
    _add_coverage_facts(facts, after)
    _add(facts, "observation.target_present", False)
    _add(facts, "identity.stable_scope", target["scope_ref"])
    _add(facts, "observation.property_value", False)
    return {
        "predicate.result": native["result"],
        "predicate.observed_value": native["observed_value"],
        "predicate.coverage_complete": native["coverage_complete"],
        "predicate.reason": native["reason"],
    }, facts


def _lower_bound(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    adapter = _adapter(root)
    raw = copy.deepcopy(FIXTURES["base"])
    raw["dom"]["truncated"] = True
    result = adapter.snapshot("p3-lower-bound", raw)
    document_scope = str(result["snapshot"]["scope"]["scope_ref"])
    predicate = {
        "schema": "smc.predicate.v0.1",
        "domain": "browser",
        "scope_ref": document_scope,
        "target": document_scope,
        "property": "object_count",
        "operator": "ge",
        "value": 1,
    }
    native = adapter.evaluate_predicate(
        "p3-lower-bound", _snapshot_id(result), predicate
    )
    facts: list[dict[str, Any]] = []
    _add_scope_facts(facts, result)
    for key, value in (
        ("model_condition.scope_ref", document_scope),
        ("model_condition.target_ref", document_scope),
        ("model_condition.property", "object_count"),
        ("model_condition.operator", "ge"),
        ("model_condition.value", 1),
        ("request.scope_ref", document_scope),
    ):
        _add(facts, key, value, provenance_kind="model_asserted")
    _add(facts, "target.scope_ref", document_scope)
    _add_coverage_facts(facts, result)
    _add(facts, "observation.object_count", native["observed_value"])
    return {
        "predicate.result": native["result"],
        "predicate.observed_value": native["observed_value"],
        "predicate.coverage_complete": native["coverage_complete"],
        "predicate.reason": native["reason"],
    }, facts


class _CaptureBackend:
    def __init__(self, captures: list[dict[str, Any]]) -> None:
        self.captures = [copy.deepcopy(row) for row in captures]
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        if not self.captures:
            raise RuntimeError("capture_exhausted")
        if len(self.captures) == 1:
            return copy.deepcopy(self.captures[0])
        return copy.deepcopy(self.captures.pop(0))


class _Actuator:
    def __init__(self, outcome: BrowserDispatchResult | Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.outcome = outcome or BrowserDispatchResult(
            acknowledged=True,
            boundary_events=(),
            completeness_reasons=("boundary_detector_non_exhaustive",),
        )

    def dispatch(self, **kwargs: Any) -> BrowserDispatchResult:
        self.calls.append(dict(kwargs))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _click_action(first: dict[str, Any], *, action_id: str) -> dict[str, Any]:
    target = _dom_named(first, "Submit")
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


def _receipt_facts(
    history: list[dict[str, Any]],
    *,
    dispatch_count: int,
    reservation_result: bool,
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    watermark = max(int(row["receipt_seq"]) for row in history)
    for row in history:
        subject = f"receipt:{row['receipt_seq']}"
        _add(
            facts,
            "receipt.action_id",
            str(row["action_id"]),
            subject=subject,
            provenance_kind="runtime_authority",
        )
        _add(
            facts,
            "receipt.seq",
            int(row["receipt_seq"]),
            subject=subject,
            provenance_kind="runtime_authority",
        )
        _add(
            facts,
            "receipt.status",
            str(row["status"]),
            subject=subject,
            provenance_kind="runtime_authority",
        )
        _add(
            facts,
            "receipt.history_watermark",
            watermark,
            subject=subject,
            provenance_kind="runtime_authority",
        )
    terminal = history[-1]
    _add(
        facts,
        "runtime.reservation_result",
        reservation_result,
        provenance_kind="runtime_authority",
    )
    _add(
        facts,
        "runtime.dispatch_count",
        dispatch_count,
        provenance_kind="runtime_authority",
    )
    _add(
        facts,
        "receipt.retry.automatic_retry_performed",
        bool(terminal["retry"]["automatic_retry_performed"]),
        provenance_kind="runtime_authority",
    )
    _add(
        facts,
        "receipt.retry.reason",
        terminal["retry"].get("reason"),
        provenance_kind="runtime_authority",
    )
    _add(
        facts,
        "receipt.observed_effects.provisional",
        bool(terminal["observed_effects"]["provisional"]),
        provenance_kind="runtime_authority",
    )
    return facts


def _native_receipt_oracle(
    history: list[dict[str, Any]],
    *,
    dispatch_count: int,
) -> dict[str, Any]:
    seqs = [int(row["receipt_seq"]) for row in history]
    statuses = [str(row["status"]) for row in history]
    monotonic = all(right > left for left, right in zip(seqs, seqs[1:], strict=False))
    transition_valid = statuses in (
        ["running", "ok"],
        ["running", "failed"],
        ["running", "ok", "rejected"],
    )
    no_retry = not any(
        bool(row.get("retry", {}).get("automatic_retry_performed")) for row in history
    )
    single_dispatch = dispatch_count == 1
    provisional = bool(history[-1].get("observed_effects", {}).get("provisional"))
    invariant = "ok" if monotonic and transition_valid and no_retry and single_dispatch else "violation"
    return {
        "receipt.sequence_monotonic": monotonic,
        "receipt.transition_valid": transition_valid,
        "receipt.terminal_status": statuses[-1],
        "receipt.single_dispatch_preserved": single_dispatch,
        "receipt.no_automatic_retry": no_retry,
        "receipt.effect_evidence_status": "provisional" if provisional else "confirmed",
        "receipt.invariant_status": invariant,
    }


def _receipt_material(
    root: Path,
    *,
    mode: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    perception = _adapter(root / "perception")
    receipts = BrowserActionReceiptStore(root / "actions")
    captures = [FIXTURES["base"]]
    outcome: BrowserDispatchResult | Exception | None = None
    if mode == "ambiguity":
        captures = [FIXTURES["base"], _changed_submit_raw()]
        outcome = TimeoutError("ack_lost")
    backend = _CaptureBackend(captures)
    actuator = _Actuator(outcome)
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=receipts,
        capture_backend=backend,
        actuator=actuator,
    )
    session_id = f"p3-receipt-{mode}"
    first = perception.snapshot(session_id, FIXTURES["base"])
    request = _click_action(first, action_id=f"p3-{mode}")
    first_result = action.execute(session_id, request)
    reservation_result = True
    if mode == "duplicate":
        if first_result["status"] != "ok":
            raise ValueError("native_first_dispatch_not_ok")
        duplicate = action.execute(session_id, request)
        if duplicate["status"] != "rejected":
            raise ValueError("native_duplicate_not_rejected")
        reservation_result = False
    history = receipts.list_action(session_id, str(request["action_id"]))
    oracle = _native_receipt_oracle(history, dispatch_count=len(actuator.calls))
    return oracle, _receipt_facts(
        history,
        dispatch_count=len(actuator.calls),
        reservation_result=reservation_result,
    )


def _material_for_case(
    fixture_id: str, root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if fixture_id == "P3-grounding-exact-compile":
        return _grounding_exact(root)
    if fixture_id == "P3-reorder-object-continuity":
        return _version_material(root, after_raw=FIXTURES["reorder"])
    if fixture_id == "P3-replacement-no-rebind":
        return _version_material(root, after_raw=FIXTURES["replacement"])
    if fixture_id == "P3-duplicate-identity-no-fusion":
        return _identity_ambiguity(root)
    if fixture_id == "P3-navigation-document-generation":
        return _version_material(root, after_raw=FIXTURES["navigate"])
    if fixture_id == "P3-frame-generation-no-continuity":
        return _frame_generation(root)
    if fixture_id == "P3-dom-ax-conflict-unresolved":
        return _source_conflict(root)
    if fixture_id == "P3-partial-coverage-absence":
        return _partial_absence(root)
    if fixture_id == "P3-virtualized-lower-bound-count":
        return _lower_bound(root)
    if fixture_id == "P3-stale-grounding-expired":
        return _expired_grounding(root)
    if fixture_id == "P3-version-target-changed":
        return _version_material(root, after_raw=_changed_submit_raw())
    if fixture_id == "P3-duplicate-action-single-dispatch":
        return _receipt_material(root, mode="duplicate")
    if fixture_id == "P3-receipt-running-terminal":
        return _receipt_material(root, mode="success")
    if fixture_id == "P3-transport-ambiguity-no-retry":
        return _receipt_material(root, mode="ambiguity")
    raise KeyError(fixture_id)


def _normalize_value(predicate: str, value: Any) -> Any:
    if predicate != "conflict.source_observations" or not isinstance(value, list):
        return value
    normalized = []
    for row in value:
        if not isinstance(row, dict):
            normalized.append(row)
            continue
        normalized.append({key: val for key, val in row.items() if key != "grounding_ref"})
    return sorted(normalized, key=lambda row: _canonical_bytes(row))


def _derived_facts(result: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for fact in result.get("derived_facts", []):
        grouped.setdefault(str(fact["predicate"]), []).append(dict(fact))
    return grouped


@dataclass(frozen=True, slots=True)
class _CaseComparison:
    oracle: dict[str, Any]
    shadow: dict[str, Any]
    mismatch_paths: list[str]
    derivation_refs: list[str]
    proof_coverage: float


def _compare(
    oracle: dict[str, Any], result: dict[str, Any]
) -> _CaseComparison:
    grouped = _derived_facts(result)
    shadow: dict[str, Any] = {}
    refs: set[str] = set()
    covered = 0
    for predicate, oracle_value in oracle.items():
        rows = grouped.get(predicate, [])
        if len(rows) != 1:
            shadow[predicate] = None
            continue
        row = rows[0]
        shadow[predicate] = _normalize_value(predicate, row.get("value"))
        provenance = dict(row.get("provenance") or {})
        if provenance.get("derivation_ref") and provenance.get("rule_ref"):
            covered += 1
            refs.add(str(provenance["rule_ref"]))
        oracle[predicate] = _normalize_value(predicate, oracle_value)
    mismatch = sorted(
        predicate
        for predicate in oracle
        if _canonical_bytes(oracle[predicate]) != _canonical_bytes(shadow.get(predicate))
    )
    return _CaseComparison(
        oracle=oracle,
        shadow=shadow,
        mismatch_paths=mismatch,
        derivation_refs=sorted(refs),
        proof_coverage=(covered / len(oracle)) if oracle else 1.0,
    )


def _safety_metrics(fixture_id: str, comparison: _CaseComparison) -> dict[str, int]:
    oracle = comparison.oracle
    shadow = comparison.shadow
    false_closure = 0
    silent_rebind = 0
    unknown_to_false = 0
    if fixture_id == "P3-partial-coverage-absence":
        if shadow.get("predicate.result") != "indeterminate":
            false_closure += 1
        if oracle.get("predicate.observed_value") is None and shadow.get(
            "predicate.observed_value"
        ) is False:
            unknown_to_false += 1
    if (
        fixture_id == "P3-dom-ax-conflict-unresolved"
        and shadow.get("canonical.value") is not None
    ):
        false_closure += 1
    if (
        fixture_id == "P3-stale-grounding-expired"
        and shadow.get("binding.status") == "bound"
    ):
        false_closure += 1
        silent_rebind += 1
    if fixture_id in {
        "P3-replacement-no-rebind",
        "P3-navigation-document-generation",
        "P3-version-target-changed",
    } and shadow.get("version.result") == "match":
        silent_rebind += 1
    return {
        "false_closure": false_closure,
        "silent_rebind": silent_rebind,
        "unknown_to_false": unknown_to_false,
    }


def qualify_case(case: dict[str, Any], root: Path, *, baseline_main: str) -> dict[str, Any]:
    fixture_id = str(case["fixture_id"])
    oracle, facts = _material_for_case(fixture_id, root)
    input_document = _input_document(facts)
    result = evaluate_rulepack(rulepack_document=PACK, input_document=input_document)
    if result.get("status") != "complete":
        raise ValueError(f"shadow_not_complete:{fixture_id}:{result.get('reason')}")
    comparison = _compare(dict(oracle), result)
    safety = _safety_metrics(fixture_id, comparison)
    oracle_hash = _sha256(comparison.oracle)
    shadow_hash = _sha256(comparison.shadow)
    return {
        "fixture_id": fixture_id,
        "gate_id": str(case["gate_id"]),
        "category": str(case["category"]),
        "baseline_ref": f"{case['oracle_ref']}@{baseline_main}",
        "oracle_result_hash": oracle_hash,
        "shadow_result_hash": shadow_hash,
        "equivalent": not comparison.mismatch_paths and oracle_hash == shadow_hash,
        "mismatch_paths": comparison.mismatch_paths,
        "derivation_refs": comparison.derivation_refs,
        "proof_coverage": comparison.proof_coverage,
        **safety,
    }


def qualify_manifest(manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    if manifest.get("authority") != "shadow_only" or manifest.get(
        "production_consumed"
    ) is not False:
        raise ValueError("p3_manifest_authority_mismatch")
    if manifest.get("rulepack_hash") != PACK.get("rulepack_hash"):
        raise ValueError("p3_rulepack_hash_mismatch")
    root.mkdir(parents=True, exist_ok=True)
    cases = [
        qualify_case(
            dict(case),
            root / str(case["fixture_id"]),
            baseline_main=str(manifest["baseline_main"]),
        )
        for case in manifest["cases"]
    ]
    equivalent_count = sum(case["equivalent"] is True for case in cases)
    false_closure = sum(int(case["false_closure"]) for case in cases)
    silent_rebind = sum(int(case["silent_rebind"]) for case in cases)
    unknown_to_false = sum(int(case["unknown_to_false"]) for case in cases)
    proof_coverage = min(float(case["proof_coverage"]) for case in cases)
    metrics = {
        "case_count": len(cases),
        "equivalent_count": equivalent_count,
        "false_closure": false_closure,
        "silent_rebind": silent_rebind,
        "unknown_to_false": unknown_to_false,
        "proof_coverage": proof_coverage,
    }
    thresholds = dict(manifest["promotion_metrics"])
    passed = (
        equivalent_count == len(cases)
        and false_closure <= int(thresholds["false_closure_max"])
        and silent_rebind <= int(thresholds["silent_rebind_max"])
        and unknown_to_false <= int(thresholds["unknown_to_false_max"])
        and proof_coverage >= float(thresholds["proof_coverage_min"])
    )
    return {
        "schema": "smc.semantic_logic_p3_shadow_result.v0.1",
        "status": "PASS" if passed else "RED",
        "authority": "shadow_only",
        "production_consumed": False,
        "rulepack_hash": str(PACK["rulepack_hash"]),
        "cases": cases,
        "metrics": metrics,
    }

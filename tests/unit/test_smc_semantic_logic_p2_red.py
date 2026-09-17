from __future__ import annotations

import copy
import hashlib
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACK_PATH = ROOT / "docs/SMC-SEMANTIC-LOGIC-P2-RULEPACK-v0.1.json"
RED_PATH = ROOT / "docs/SMC-SEMANTIC-LOGIC-P2-RED-GATES-v0.1.json"
PACK = json.loads(PACK_PATH.read_text(encoding="utf-8"))
RED = json.loads(RED_PATH.read_text(encoding="utf-8"))
DERIVED_PREDICATES = {
    predicate for rule in PACK["rules"] for predicate in rule["output_predicates"]
}


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
    subject: str = "ctx",
    provenance_kind: str = "observed",
    domain: str = "browser",
    context_ref: str = "ctx:p2-red",
    fact_id: str | None = None,
) -> dict[str, Any]:
    observed = provenance_kind == "observed"
    payload = {
        "subject": subject,
        "predicate": predicate,
        "value": value,
        "provenance_kind": provenance_kind,
        "domain": domain,
        "context_ref": context_ref,
    }
    return {
        "kind": "fact",
        "schema": "smc.semantic_fact.v0.1",
        "fact_id": fact_id or f"rfact-{_sha256(payload)[:24]}",
        "domain": domain,
        "subject": subject,
        "predicate": predicate,
        "value": value,
        "value_type": _value_type(value),
        "truth_state": "asserted",
        "context": {
            "domain": domain,
            "scope_ref": "scope:document:1" if domain == "browser" else None,
            "observed_version": "snapshot:1" if observed else None,
            "snapshot_id": "snapshot:1" if observed else None,
            "sensor_contract_ref": "sensor:browser:p2-red" if observed else None,
        },
        "observation_completeness": {"complete": True, "reasons": []},
        "projection_complete": True,
        "provenance": {
            "kind": provenance_kind,
            "source": f"{provenance_kind}:p2-red",
            "grounding_ref": f"grounding://p2-red/{subject}" if observed else None,
            "observed_version": "snapshot:1" if observed else None,
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
    subject: str = "ctx",
    provenance_kind: str = "observed",
    domain: str = "browser",
    context_ref: str = "ctx:p2-red",
) -> None:
    facts.append(
        _fact(
            predicate,
            value,
            subject=subject,
            provenance_kind=provenance_kind,
            domain=domain,
            context_ref=context_ref,
        )
    )


def _rehash_pack(pack: dict[str, Any]) -> dict[str, Any]:
    for rule in pack["rules"]:
        body = dict(rule)
        body.pop("rule_hash", None)
        rule["rule_hash"] = _sha256(body)
    body = dict(pack)
    body.pop("rulepack_hash", None)
    pack["rulepack_hash"] = _sha256(body)
    return pack


def _scope_facts(*, cycle: bool = False, depth: int = 3) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    if depth <= 3:
        nodes = [
            ("scope:page:1", None, "page"),
            ("scope:document:1", "scope:page:1", "document"),
            ("scope:frame:1", "scope:document:1", "frame"),
        ]
        if cycle:
            nodes[1] = ("scope:document:1", "scope:frame:1", "document")
    else:
        nodes = [("scope:node:0", None, "page")]
        nodes.extend(
            (f"scope:node:{i}", f"scope:node:{i - 1}", "frame")
            for i in range(1, depth)
        )
    for scope_ref, parent, kind in nodes:
        subject = f"scope-node:{scope_ref}"
        _add(facts, "scope.node.scope_ref", scope_ref, subject=subject)
        _add(facts, "scope.node.parent_scope_ref", parent, subject=subject)
        _add(facts, "scope.node.kind", kind, subject=subject)
    return facts


def _grounding_object_facts() -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    _add(facts, "request.target_ref", "grounding://browser/object/submit", provenance_kind="model_asserted")
    _add(facts, "request.verb", "click", provenance_kind="model_asserted")
    _add(facts, "request.args", {}, provenance_kind="model_asserted")
    _add(facts, "grounding.availability", "available")
    _add(facts, "grounding.ref", "grounding://browser/object/submit")
    _add(facts, "grounding.kind", "object")
    _add(facts, "grounding.projection_ref", "grounding://browser/object/submit")
    _add(facts, "grounding.target_id", "el_0123456789abcdefabcd")
    _add(facts, "grounding.scope_ref", "scope:document:1")
    _add(facts, "grounding.observed_version", "snapshot:1")
    return facts


def _grounding_resource_facts() -> list[dict[str, Any]]:
    facts = _grounding_object_facts()
    replacements = {
        "request.target_ref": "grounding://browser/resource/page",
        "request.verb": "navigate",
        "request.args": {"url": "https://example.invalid/"},
        "grounding.ref": "grounding://browser/resource/page",
        "grounding.kind": "resource",
        "grounding.projection_ref": "grounding://browser/resource/page",
        "grounding.target_id": "scope:page:1",
        "grounding.scope_ref": "scope:page:1",
    }
    for fact in facts:
        if fact["predicate"] in replacements:
            fact["value"] = replacements[fact["predicate"]]
            fact["value_type"] = _value_type(fact["value"])
    return facts


def _coverage_raw(*, complete: bool) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    _add(facts, "coverage.expected_sources", ["dom", "ax"])
    _add(facts, "coverage.observed_sources", ["dom", "ax"] if complete else ["dom"])
    _add(facts, "coverage.blind_spots", [] if complete else ["dom_truncated"])
    _add(facts, "coverage.sensor_truncated", not complete)
    return facts


def _predicate_common(
    *,
    property_name: str,
    operator: str,
    value: Any,
    target_ref: str = "grounding://browser/object/submit",
    scope_ref: str = "scope:document:1",
    include_object_grounding: bool = True,
) -> list[dict[str, Any]]:
    facts = _grounding_object_facts() if include_object_grounding else []
    facts.extend(_scope_facts())
    _add(facts, "model_condition.scope_ref", scope_ref, provenance_kind="model_asserted")
    _add(facts, "model_condition.target_ref", target_ref, provenance_kind="model_asserted")
    _add(facts, "model_condition.property", property_name, provenance_kind="model_asserted")
    _add(facts, "model_condition.operator", operator, provenance_kind="model_asserted")
    _add(facts, "model_condition.value", value, provenance_kind="model_asserted")
    _add(facts, "request.scope_ref", scope_ref, provenance_kind="model_asserted")
    _add(facts, "target.scope_ref", scope_ref)
    return facts


def _version_common() -> list[dict[str, Any]]:
    facts = _scope_facts()
    facts.extend(_coverage_raw(complete=True))
    _add(facts, "request.scope_ref", "scope:document:1", provenance_kind="model_asserted")
    _add(facts, "target.scope_ref", "scope:document:1")
    _add(facts, "version.scope", "object")
    _add(facts, "version.expected", "snapshot:1")
    _add(facts, "version.observed", "snapshot:2")
    _add(facts, "version.expected_availability", "available")
    _add(facts, "version.observed_availability", "available")
    _add(facts, "lineage.page_same", True)
    _add(facts, "lineage.document_same", True)
    _add(facts, "identity.stable", True)
    _add(facts, "observation.target_present", True)
    _add(facts, "object.changed_fields", [])
    _add(facts, "resource.changed_fields", [])
    return facts


def _receipt_common(*, terminal: str = "ok") -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for subject, seq, status in (("receipt:1", 1, "running"), ("receipt:2", 2, terminal)):
        _add(facts, "receipt.action_id", "act-1", subject=subject, provenance_kind="runtime_authority")
        _add(facts, "receipt.seq", seq, subject=subject, provenance_kind="runtime_authority")
        _add(facts, "receipt.status", status, subject=subject, provenance_kind="runtime_authority")
        _add(facts, "receipt.history_watermark", 2, subject=subject, provenance_kind="runtime_authority")
    _add(facts, "runtime.reservation_result", True, provenance_kind="runtime_authority")
    _add(facts, "runtime.dispatch_count", 1, provenance_kind="runtime_authority")
    _add(facts, "receipt.retry.automatic_retry_performed", False, provenance_kind="runtime_authority")
    _add(facts, "receipt.retry.reason", None, provenance_kind="runtime_authority")
    _add(facts, "receipt.observed_effects.provisional", True, provenance_kind="runtime_authority")
    return facts


@dataclass(frozen=True)
class RedCaseInput:
    gate_id: str
    rulepack: dict[str, Any]
    input_document: dict[str, Any]


def _input_document(facts: list[dict[str, Any]], *, domain: str = "browser") -> dict[str, Any]:
    return {
        "schema": "smc.rule_engine_input.v0.1",
        "authority": "shadow_only",
        "production_consumed": False,
        "domain": domain,
        "context_ref": "ctx:p2-red",
        "facts": facts,
    }


def _semantic_case(gate_id: str) -> list[dict[str, Any]]:
    if gate_id.startswith("P2-G1-"):
        facts = _grounding_resource_facts() if gate_id == "P2-G1-02" else _grounding_object_facts()
        if gate_id == "P2-G1-03":
            next(f for f in facts if f["predicate"] == "grounding.availability")["value"] = "unauthorized"
        elif gate_id == "P2-G1-04":
            next(f for f in facts if f["predicate"] == "grounding.availability")["value"] = "expired"
        elif gate_id == "P2-G1-05":
            next(f for f in facts if f["predicate"] == "request.verb")["value"] = "navigate"
        elif gate_id == "P2-G1-06":
            next(f for f in facts if f["predicate"] == "grounding.projection_ref")["value"] = "grounding://tampered"
        elif gate_id == "P2-G1-07":
            next(f for f in facts if f["predicate"] == "grounding.target_id")["value"] = ""
        return facts

    if gate_id.startswith("P2-G2-"):
        if gate_id == "P2-G2-05":
            return _scope_facts(cycle=True)
        if gate_id == "P2-G2-06":
            return _scope_facts(depth=34)
        facts = _scope_facts()
        _add(facts, "request.scope_ref", "scope:document:1", provenance_kind="model_asserted")
        if gate_id == "P2-G2-01":
            _add(facts, "target.scope_ref", "scope:document:1")
        elif gate_id == "P2-G2-02":
            _add(facts, "target.scope_ref", "scope:frame:1")
        elif gate_id == "P2-G2-03":
            _add(facts, "target.scope_ref", "scope:not-observed")
        return facts

    if gate_id.startswith("P2-G3-"):
        facts: list[dict[str, Any]] = []
        if gate_id in {"P2-G3-01", "P2-G3-02", "P2-G3-03", "P2-G3-07"}:
            values = [("dom", True), ("ax", gate_id == "P2-G3-02")]
            if gate_id == "P2-G3-03":
                values = [("dom", True)]
            if gate_id == "P2-G3-07":
                values.reverse()
            for source, value in values:
                subject = f"observation:{source}"
                _add(facts, "observation.subject", "el_submit", subject=subject)
                _add(facts, "observation.property", "enabled", subject=subject)
                _add(facts, "observation.source", source, subject=subject)
                _add(facts, "observation.value", value, subject=subject)
                _add(facts, "observation.grounding_ref", f"grounding://source/{source}", subject=subject)
            _add(facts, "resolver.contract", "none")
            facts.extend(_coverage_raw(complete=len(values) == 2))
        elif gate_id == "P2-G3-04":
            _add(facts, "identity.mapping_status", "ambiguous")
            _add(facts, "identity.source_candidates", ["dom:n-submit", "ax:ax-submit"])
        elif gate_id == "P2-G3-05":
            _add(facts, "observation.complete", True)
            _add(facts, "observation.reasons", [])
            _add(facts, "projection.complete", False)
            _add(facts, "projection.reasons", ["display_budget"])
        elif gate_id == "P2-G3-06":
            _add(facts, "observation.complete", False)
            _add(facts, "observation.reasons", ["dom_truncated"])
            _add(facts, "projection.complete", True)
            _add(facts, "projection.reasons", [])
        return facts

    if gate_id.startswith("P2-G4-"):
        if gate_id in {"P2-G4-05", "P2-G4-06", "P2-G4-07"}:
            op, expected = ("ge", 1) if gate_id == "P2-G4-05" else (("le", 2) if gate_id == "P2-G4-06" else ("le", 999))
            facts = _predicate_common(
                property_name="object_count",
                operator=op,
                value=expected,
                target_ref="scope:document:1",
                include_object_grounding=False,
            )
            facts.extend(_coverage_raw(complete=False))
            _add(facts, "observation.object_count", 3)
            return facts
        if gate_id == "P2-G4-09":
            facts = _predicate_common(
                property_name="url",
                operator="eq",
                value="https://example.invalid/",
                target_ref="scope:other",
                include_object_grounding=False,
            )
            facts.extend(_coverage_raw(complete=True))
            return facts
        if gate_id == "P2-G4-10":
            facts = _predicate_common(
                property_name="object_count",
                operator="contains",
                value="x",
                target_ref="scope:document:1",
                include_object_grounding=False,
            )
            facts.extend(_coverage_raw(complete=True))
            _add(facts, "observation.object_count", 3)
            return facts
        property_name = "focused" if gate_id == "P2-G4-04" else "exists"
        expected = property_name == "focused"
        facts = _predicate_common(property_name=property_name, operator="eq", value=expected)
        complete = gate_id not in {"P2-G4-02", "P2-G4-07"}
        facts.extend(_coverage_raw(complete=complete))
        if gate_id == "P2-G4-08":
            next(f for f in facts if f["predicate"] == "target.scope_ref")["value"] = "scope:not-observed"
        if gate_id in {"P2-G4-01", "P2-G4-02", "P2-G4-03", "P2-G4-11"}:
            _add(facts, "observation.target_present", False)
        else:
            _add(facts, "observation.target_present", True)
        if gate_id == "P2-G4-03":
            _add(facts, "identity.stable_scope", None)
        else:
            _add(facts, "identity.stable_scope", "scope:document:1")
        if gate_id != "P2-G4-04":
            _add(facts, "observation.property_value", property_name != "exists")
        return facts

    if gate_id.startswith("P2-G5-"):
        if gate_id in {"P2-G5-08", "P2-G5-09", "P2-G5-10", "P2-G5-11", "P2-G5-12", "P2-G5-13"}:
            terminal = "failed" if gate_id == "P2-G5-10" else "ok"
            facts = _receipt_common(terminal=terminal)
            if gate_id == "P2-G5-09":
                next(f for f in facts if f["predicate"] == "runtime.reservation_result")["value"] = False
                duplicate = "receipt:3"
                _add(facts, "receipt.action_id", "act-1", subject=duplicate, provenance_kind="runtime_authority")
                _add(facts, "receipt.seq", 3, subject=duplicate, provenance_kind="runtime_authority")
                _add(facts, "receipt.status", "rejected", subject=duplicate, provenance_kind="runtime_authority")
                _add(facts, "receipt.history_watermark", 3, subject=duplicate, provenance_kind="runtime_authority")
                _add(facts, "receipt.retry.reason", "duplicate_action_id", subject=duplicate, provenance_kind="runtime_authority")
            elif gate_id == "P2-G5-10":
                next(f for f in facts if f["predicate"] == "receipt.retry.reason")["value"] = "dispatch_error:TimeoutError"
            elif gate_id == "P2-G5-12":
                seqs = [f for f in facts if f["predicate"] == "receipt.seq"]
                seqs[0]["value"], seqs[1]["value"] = 2, 1
            elif gate_id == "P2-G5-13":
                next(f for f in facts if f["predicate"] == "runtime.dispatch_count")["value"] = 2
                next(f for f in facts if f["predicate"] == "runtime.reservation_result")["value"] = False
            return facts
        facts = _version_common()
        if gate_id == "P2-G5-01":
            next(f for f in facts if f["predicate"] == "object.changed_fields")["value"] = ["state.enabled"]
        elif gate_id == "P2-G5-03":
            next(f for f in facts if f["predicate"] == "lineage.document_same")["value"] = False
        elif gate_id == "P2-G5-04":
            next(f for f in facts if f["predicate"] == "observation.target_present")["value"] = False
            cov = [f for f in facts if f["predicate"].startswith("coverage.")]
            for fact in cov:
                if fact["predicate"] == "coverage.observed_sources":
                    fact["value"] = ["dom"]
                elif fact["predicate"] == "coverage.blind_spots":
                    fact["value"] = ["dom_truncated"]
                elif fact["predicate"] == "coverage.sensor_truncated":
                    fact["value"] = True
        elif gate_id == "P2-G5-05":
            next(f for f in facts if f["predicate"] == "version.expected_availability")["value"] = "expired"
        elif gate_id == "P2-G5-06":
            next(f for f in facts if f["predicate"] == "version.observed")["value"] = "snapshot:1"
        elif gate_id == "P2-G5-07":
            next(f for f in facts if f["predicate"] == "identity.stable")["value"] = False
        return facts

    raise KeyError(gate_id)


def _engine_case(gate_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    pack = copy.deepcopy(PACK)
    facts = _grounding_object_facts()
    domain = "browser"
    if gate_id == "P2-E-01":
        pack["rulepack_hash"] = "0" * 64
    elif gate_id == "P2-E-02":
        pack["schema"] = "smc.rulepack.v999"
        _rehash_pack(pack)
    elif gate_id in {"P2-E-03", "P2-E-04", "P2-E-05"}:
        pack["rules"][0]["authority_class"] = {
            "P2-E-03": "runtime_authority",
            "P2-E-04": "model_semantic",
            "P2-E-05": "candidate_only",
        }[gate_id]
        _rehash_pack(pack)
    elif gate_id == "P2-E-06":
        pack["rules"][0]["output_predicates"].append("task_complete")
        _rehash_pack(pack)
    elif gate_id == "P2-E-07":
        pack["rules"][0]["dependencies"] = [pack["rules"][1]["rule_id"]]
        pack["rules"][1]["dependencies"] = [pack["rules"][0]["rule_id"]]
        _rehash_pack(pack)
    elif gate_id == "P2-E-08":
        pack["rules"][0]["dependencies"] = ["missing.rule"]
        _rehash_pack(pack)
    elif gate_id == "P2-E-09":
        duplicate = copy.deepcopy(pack["rules"][0])
        pack["rules"].append(duplicate)
        _rehash_pack(pack)
    elif gate_id == "P2-E-10":
        template = copy.deepcopy(pack["rules"][0])
        while len(pack["rules"]) <= 64:
            clone = copy.deepcopy(template)
            clone["rule_id"] = f"test.extra.rule.{len(pack['rules']):03d}"
            clone["dependencies"] = []
            pack["rules"].append(clone)
        _rehash_pack(pack)
    elif gate_id == "P2-E-11":
        facts = [
            _fact("noise.value", i, subject=f"noise:{i}", fact_id=f"noise-{i:05d}")
            for i in range(4097)
        ]
    elif gate_id == "P2-E-12":
        pack["engine_profile"]["bounds"]["max_derived_facts"] = 1
        _rehash_pack(pack)
    elif gate_id == "P2-E-13":
        facts = [
            _fact(
                "noise.value",
                i,
                subject=f"ctx:{i}",
                context_ref=f"ctx:{i}",
                fact_id=f"context-{i:04d}",
            )
            for i in range(257)
        ]
    elif gate_id == "P2-E-14":
        domain = "filesystem"
        facts = [_fact("noise.value", 1, domain="filesystem")]
    elif gate_id == "P2-E-15":
        pack["rules"][0]["evaluator_op"] = "arbitrary_dynamic_op"
        _rehash_pack(pack)
    elif gate_id == "P2-E-16":
        facts = _scope_facts()
        parent = next(f for f in facts if f["predicate"] == "scope.node.parent_scope_ref" and f["value"] is not None)
        parent["value"] = {"malformed": True}
        parent["value_type"] = "object"
    elif gate_id == "P2-E-17":
        first = facts[0]
        conflict = copy.deepcopy(first)
        conflict["value"] = "different"
        conflict["value_type"] = "string"
        facts.append(conflict)
    elif gate_id == "P2-E-18":
        pack["rules"][0]["output_predicates"].append("runtime.authority")
        _rehash_pack(pack)
    elif gate_id == "P2-E-19":
        pass
    else:
        raise KeyError(gate_id)
    return pack, _input_document(facts, domain=domain)


def build_case(gate: dict[str, Any]) -> RedCaseInput:
    gate_id = str(gate["gate_id"])
    if gate_id.startswith("P2-E-"):
        pack, input_document = _engine_case(gate_id)
    else:
        pack = copy.deepcopy(PACK)
        input_document = _input_document(_semantic_case(gate_id))
    return RedCaseInput(gate_id=gate_id, rulepack=pack, input_document=input_document)


def _evaluate(case: RedCaseInput) -> dict[str, Any]:
    try:
        module = importlib.import_module("llm_loop.semantic_logic.rules")
    except ModuleNotFoundError as exc:
        pytest.fail(f"P2 RED: core rule engine API absent: {exc}", pytrace=False)
    evaluate_rulepack = module.evaluate_rulepack
    return evaluate_rulepack(
        rulepack_document=case.rulepack,
        input_document=case.input_document,
    )


def _wire_value(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _derived_relations(result: dict[str, Any]) -> set[str]:
    return {
        f"{fact['predicate']}={_wire_value(fact.get('value'))}"
        for fact in result.get("derived_facts", [])
        if isinstance(fact, dict) and isinstance(fact.get("predicate"), str)
    }


def test_red_manifest_is_exactly_64_unique_cases() -> None:
    assert RED["rulepack_hash"] == PACK["rulepack_hash"]
    assert len(RED["cases"]) == 64
    assert len({case["gate_id"] for case in RED["cases"]}) == 64


def test_all_red_case_builders_are_closed_and_do_not_smuggle_derived_outputs() -> None:
    for gate in RED["cases"]:
        case = build_case(gate)
        assert case.input_document["schema"] == "smc.rule_engine_input.v0.1"
        assert case.input_document["authority"] == "shadow_only"
        assert case.input_document["production_consumed"] is False
        fact_ids = [fact["fact_id"] for fact in case.input_document["facts"]]
        if gate["gate_id"] != "P2-E-17":
            assert len(fact_ids) == len(set(fact_ids))
        for fact in case.input_document["facts"]:
            assert fact["schema"] == "smc.semantic_fact.v0.1"
            assert fact["provenance"]["derivation_ref"] is None
            assert fact["provenance"]["rule_ref"] is None
            assert fact["provenance"]["input_fact_refs"] == []
            assert fact["predicate"] not in DERIVED_PREDICATES


@pytest.mark.parametrize("gate", RED["cases"], ids=lambda item: item["gate_id"])
def test_p2_red_gate_requires_absent_core_rule_engine(gate: dict[str, Any]) -> None:
    case = build_case(gate)
    result = _evaluate(case)

    if gate["gate_id"] == "P2-E-19":
        second = _evaluate(case)
        assert _canonical_bytes(result) == _canonical_bytes(second)
        return

    assert result["status"] == gate["expected_engine_status"]
    relations = _derived_relations(result)
    for expected in gate["expected_relations"]:
        assert expected in relations
    for forbidden in gate["forbidden_relations"]:
        assert forbidden not in relations

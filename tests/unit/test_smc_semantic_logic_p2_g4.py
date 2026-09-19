from __future__ import annotations

import copy
import json
import runpy
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from llm_loop.browser.predicate import PREDICATE_SPECS, evaluate_predicate, validate_predicate
from llm_loop.semantic_logic import rules as core_rules
from llm_loop.semantic_logic.rules import evaluate_rulepack

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_ROOT = ROOT / "tools/semantic_logic/n3_validator"
RED_HARNESS = runpy.run_path(str(ROOT / "tests/unit/test_smc_semantic_logic_p2_red.py"))
P1C = runpy.run_path(str(VALIDATOR_ROOT / "harness.py"))
P1D = runpy.run_path(str(ROOT / "tools/semantic_logic/p1d_qualification.py"))

BACKEND_READY = P1C["backend_installation_available"]()
LIVE_BACKEND = pytest.mark.skipif(
    not BACKEND_READY,
    reason="qualification-only pinned N3 backend is not installed in this checkout",
)

RED = RED_HARNESS["RED"]
build_case = RED_HARNESS["build_case"]
G4_BRIDGE = VALIDATOR_ROOT / "p2_g4_bridge.mjs"

G4_RULES_SHA256 = "5054ce984d6b2b18bd9c8e74a93c03868f8ccd8990421f34c711c8355b75b9c0"
G4_QUERY_SHA256 = "22869e9012783e20594bc86ca417c83f668ffc1ef493231bd4abdf162665b5f6"


def _g4_gates() -> list[dict[str, Any]]:
    gates = [gate for gate in RED["cases"] if str(gate["gate_id"]).startswith("P2-G4-")]
    assert [gate["gate_id"] for gate in gates] == [f"P2-G4-{i:02d}" for i in range(1, 12)]
    return gates


def _single(input_document: dict[str, Any], predicate: str) -> Any | None:
    values = [fact.get("value") for fact in input_document["facts"] if fact["predicate"] == predicate]
    return values[0] if len(values) == 1 else None


def _has(input_document: dict[str, Any], predicate: str) -> bool:
    return sum(fact["predicate"] == predicate for fact in input_document["facts"]) == 1


def _typed_values(result: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for fact in result["derived_facts"]:
        predicate = str(fact["predicate"])
        if predicate.startswith("predicate."):
            values[predicate] = fact.get("value")
    return values


def _observed_scopes(input_document: dict[str, Any]) -> set[str]:
    return {
        str(fact["value"])
        for fact in input_document["facts"]
        if fact["predicate"] == "scope.node.scope_ref"
    }


def _scope_relation(input_document: dict[str, Any]) -> str:
    request = _single(input_document, "request.scope_ref")
    target = _single(input_document, "target.scope_ref")
    observed = _observed_scopes(input_document)
    if request not in observed or target not in observed:
        return "indeterminate"
    return "match" if request == target else "mismatch"


def _coverage_complete(input_document: dict[str, Any]) -> bool:
    expected = set(_single(input_document, "coverage.expected_sources") or [])
    observed = set(_single(input_document, "coverage.observed_sources") or [])
    blind = list(_single(input_document, "coverage.blind_spots") or [])
    truncated = _single(input_document, "coverage.sensor_truncated") is True
    return bool(expected) and observed == expected and not blind and not truncated


def _predicate_document(input_document: dict[str, Any]) -> dict[str, Any]:
    property_name = str(_single(input_document, "model_condition.property"))
    scope_ref = str(_single(input_document, "model_condition.scope_ref"))
    spec = PREDICATE_SPECS.get(property_name)
    target_ref = str(_single(input_document, "model_condition.target_ref"))
    if spec is not None and spec["target_kind"] == "semantic_object":
        target = str(_single(input_document, "grounding.target_id"))
    else:
        target = target_ref
    return {
        "schema": "smc.predicate.v0.1",
        "domain": "browser",
        "scope_ref": scope_ref,
        "target": target,
        "property": property_name,
        "operator": _single(input_document, "model_condition.operator"),
        "value": _single(input_document, "model_condition.value"),
    }


def _production_oracle(input_document: dict[str, Any]) -> dict[str, Any]:
    predicate = _predicate_document(input_document)
    error = validate_predicate(predicate)
    if error is not None:
        return {"status": "rejected", "reason": error}

    scope_ref = str(predicate["scope_ref"])
    target = str(predicate["target"])
    property_name = str(predicate["property"])
    scope_facts: list[dict[str, Any]] = []
    node_rows: dict[str, dict[str, Any]] = {}
    for fact in input_document["facts"]:
        if str(fact["predicate"]).startswith("scope.node."):
            node_rows.setdefault(str(fact["subject"]), {})[str(fact["predicate"])] = fact.get("value")
    for row in node_rows.values():
        scope_facts.append(
            {
                "scope_ref": row.get("scope.node.scope_ref"),
                "parent_scope_ref": row.get("scope.node.parent_scope_ref"),
                "kind": row.get("scope.node.kind"),
            }
        )

    objects: list[dict[str, Any]] = []
    if property_name == "object_count":
        count = int(_single(input_document, "observation.object_count") or 0)
        objects = [
            {"id": f"el_{index:020x}", "scope_ref": scope_ref, "state": {}, "attributes": {}}
            for index in range(count)
        ]
    elif _single(input_document, "observation.target_present") is True:
        state: dict[str, Any] = {}
        attributes: dict[str, Any] = {}
        if _has(input_document, "observation.property_value"):
            value = _single(input_document, "observation.property_value")
            if property_name in {"enabled", "visible", "checked", "selected", "expanded", "focused", "editable"}:
                state[property_name] = value
            elif property_name in {"name", "value_text"}:
                attributes[property_name] = value
        objects = [{"id": target, "scope_ref": scope_ref, "state": state, "attributes": attributes}]

    bundle = {
        "snapshot": {
            "snapshot_id": "snapshot:g4-oracle",
            "objects_ref": "objects:g4-oracle",
            "completeness": {"complete": _coverage_complete(input_document)},
        },
        "scope_facts": scope_facts,
        "objects": objects,
        "private_capture": {"scope_observations": {}},
    }
    stable_scope = _single(input_document, "identity.stable_scope")
    return evaluate_predicate(
        bundle=bundle,
        predicate=predicate,
        known_stable_scope=lambda candidate: stable_scope if candidate == target else None,
    )


def _eye_request(gate_id: str, input_document: dict[str, Any]) -> dict[str, Any]:
    predicate = _predicate_document(input_document)
    contract_valid = validate_predicate(predicate) is None
    property_name = str(predicate["property"])
    kind = "object_count" if property_name == "object_count" else ("exists" if property_name == "exists" else "object_property")
    target_present = _single(input_document, "observation.target_present")
    stable_scope = _single(input_document, "identity.stable_scope")
    property_value = _single(input_document, "observation.property_value")
    operator = str(predicate["operator"])
    if operator not in {"eq", "ge", "le"}:
        operator = "eq"
    expected = predicate["value"]
    return {
        "answer_cap": 128,
        "case_ref": gate_id,
        "contract_valid": contract_valid,
        "kind": kind,
        "scope_relation": _scope_relation(input_document),
        "target_present": "unknown" if not isinstance(target_present, bool) else str(target_present).lower(),
        "stable_identity": (
            "unknown" if stable_scope is None else str(stable_scope == predicate["scope_ref"]).lower()
        ),
        "coverage": "complete" if _coverage_complete(input_document) else "partial",
        "property_observed": str(_has(input_document, "observation.property_value")).lower(),
        "property_value": "unknown" if not isinstance(property_value, bool) else str(property_value).lower(),
        "operator": operator,
        "expected_bool": expected if isinstance(expected, bool) else False,
        "observed_count": int(_single(input_document, "observation.object_count") or 0),
        "expected_count": expected if isinstance(expected, int) and not isinstance(expected, bool) and expected >= 0 else 0,
    }


def _run_n3_shadow(gate_id: str, input_document: dict[str, Any]) -> dict[str, Any]:
    P1C["verify_backend_identity"]()
    P1D["verify_p1d_parser_identity"]()
    node = shutil.which("node")
    assert node is not None
    request_bytes = (json.dumps(_eye_request(gate_id, input_document), separators=(",", ":")) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix="smc-p2-g4-") as raw_home:
        proc = subprocess.run(
            P1C["_sandbox_command"](node, G4_BRIDGE),
            input=request_bytes,
            capture_output=True,
            check=False,
            timeout=20,
            cwd=VALIDATOR_ROOT,
            env=P1C["_sanitized_env"](Path(raw_home)),
        )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    assert proc.stderr == b""
    receipt = json.loads(proc.stdout.decode())
    assert receipt["ok"] is True
    assert receipt["rules_sha256"] == G4_RULES_SHA256
    assert receipt["query_sha256"] == G4_QUERY_SHA256
    if receipt["validation_status"] == "accepted":
        assert "--restricted" in receipt["eye_args"]
        assert receipt["eye_args"][-4:] == ["./data.n3", "./rules.n3", "--query", "./query.n3"]
    else:
        assert receipt["eye_args"] == []
    return receipt


@LIVE_BACKEND
@pytest.mark.parametrize("gate", _g4_gates(), ids=lambda gate: gate["gate_id"])
def test_g4_python_typed_and_restricted_n3_shadow(gate: dict[str, Any]) -> None:
    gate_id = str(gate["gate_id"])
    case = build_case(gate)
    typed = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
    eye = _run_n3_shadow(gate_id, case.input_document)
    oracle = _production_oracle(case.input_document)

    if gate_id in {"P2-G4-09", "P2-G4-10"}:
        assert oracle["status"] == "rejected"
        assert typed["status"] == "rejected"
        assert eye["validation_status"] == "rejected"
        return

    values = _typed_values(typed)
    assert typed["status"] == "complete"
    assert eye["validation_status"] == "accepted"
    eye_values = {str(key): value for key, value in eye["relations"]}

    if gate_id == "P2-G4-08":
        assert _scope_relation(case.input_document) == "indeterminate"
        expected_result = "indeterminate"
    else:
        assert oracle["result"] in {"satisfied", "unsatisfied", "indeterminate"}
        expected_result = str(oracle["result"])
    assert values["predicate.result"] == expected_result
    assert eye_values["predicateResult"] == expected_result

    if gate_id in {"P2-G4-01", "P2-G4-11"}:
        assert values["predicate.observed_value"] is False
        assert oracle["observed_value"] is False
        assert eye_values["observedValue"] == "false"
    if gate_id == "P2-G4-02":
        assert values["predicate.observed_value"] is None
        assert "observedValue" not in eye_values
    if gate_id == "P2-G4-03":
        assert values["predicate.observed_value"] is None
    if gate_id == "P2-G4-04":
        assert values["predicate.observed_value"] is None


def test_g4_core_predicate_vocabulary_matches_production_contract() -> None:
    normalized = {
        key: {
            field: value
            for field, value in spec.items()
            if field in {"operators", "value_type", "value_enum", "target_kind"}
        }
        for key, spec in PREDICATE_SPECS.items()
    }
    assert normalized == core_rules._PREDICATE_SPECS


def test_g4_partial_absence_never_collapses_unknown_to_false() -> None:
    gate = next(gate for gate in _g4_gates() if gate["gate_id"] == "P2-G4-02")
    case = build_case(gate)
    result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
    values = _typed_values(result)
    assert values["predicate.result"] == "indeterminate"
    assert values["predicate.observed_value"] is None
    assert values["predicate.coverage_complete"] is False


def test_g4_no_target_presence_fact_never_becomes_negative_absence() -> None:
    gate = next(gate for gate in _g4_gates() if gate["gate_id"] == "P2-G4-01")
    case = build_case(gate)
    mutated = copy.deepcopy(case.input_document)
    mutated["facts"] = [fact for fact in mutated["facts"] if fact["predicate"] != "observation.target_present"]
    result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=mutated)
    values = _typed_values(result)
    assert values["predicate.result"] == "indeterminate"
    assert values["predicate.observed_value"] is None


@pytest.mark.parametrize(
    ("operator", "expected", "count", "expected_result"),
    [
        ("ge", 4, 3, "indeterminate"),
        ("eq", 3, 3, "indeterminate"),
        ("eq", 2, 3, "unsatisfied"),
        ("le", 2, 3, "unsatisfied"),
        ("le", 3, 3, "indeterminate"),
    ],
)
def test_g4_partial_object_count_is_only_a_positive_lower_bound(
    operator: str, expected: int, count: int, expected_result: str
) -> None:
    gate = next(gate for gate in _g4_gates() if gate["gate_id"] == "P2-G4-05")
    case = build_case(gate)
    mutated = copy.deepcopy(case.input_document)
    for fact in mutated["facts"]:
        if fact["predicate"] == "model_condition.operator":
            fact["value"] = operator
        elif fact["predicate"] == "model_condition.value":
            fact["value"] = expected
        elif fact["predicate"] == "observation.object_count":
            fact["value"] = count
    result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=mutated)
    assert _typed_values(result)["predicate.result"] == expected_result


def test_g4_invalid_semantic_object_id_is_rejected_before_evaluation() -> None:
    gate = next(gate for gate in _g4_gates() if gate["gate_id"] == "P2-G4-01")
    case = build_case(gate)
    mutated = copy.deepcopy(case.input_document)
    next(fact for fact in mutated["facts"] if fact["predicate"] == "grounding.target_id")["value"] = "el_not-semantic"
    result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=mutated)
    assert result["status"] == "rejected"


def test_g4_negative_reasoning_never_emits_negation_as_failure() -> None:
    gate = next(gate for gate in _g4_gates() if gate["gate_id"] == "P2-G4-11")
    case = build_case(gate)
    result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
    assert not any(str(fact["predicate"]) == "negation_as_failure" for fact in result["derived_facts"])
    assert _typed_values(result)["predicate.observed_value"] is False


def test_g4_same_input_is_byte_deterministic_and_provenance_is_mechanical() -> None:
    gate = next(gate for gate in _g4_gates() if gate["gate_id"] == "P2-G4-01")
    case = build_case(gate)
    first = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
    second = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )
    asserted = {str(fact["fact_id"]) for fact in case.input_document["facts"]}
    derived = {str(fact["fact_id"]): fact for fact in first["derived_facts"]}
    for derivation in first["derivations"]:
        assert set(derivation["input_fact_refs"]) <= asserted | set(derived)
        for output_ref in derivation["output_fact_refs"]:
            fact = derived[str(output_ref)]
            assert fact["provenance"]["kind"] == "mechanically_derived"
            assert fact["context"]["domain"] == "browser"
            assert not str(fact["predicate"]).startswith("runtime.")


def test_g4_bridge_has_no_dynamic_rule_or_query_input_surface() -> None:
    source = G4_BRIDGE.read_text(encoding="utf-8")
    assert "request.rules" not in source
    assert "request.query" not in source
    assert "rules.n3" in source
    assert "query.n3" in source
    assert "--restricted" in source

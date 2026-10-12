from __future__ import annotations

import copy
import runpy
from pathlib import Path
from typing import Any

from llm_loop.semantic_logic.rules import evaluate_rulepack

ROOT = Path(__file__).resolve().parents[2]
RED_HARNESS = runpy.run_path(str(ROOT / "tests/unit/test_smc_semantic_logic_p2_red.py"))

RED = RED_HARNESS["RED"]
PACK = RED_HARNESS["PACK"]
build_case = RED_HARNESS["build_case"]
derived_relations = RED_HARNESS["_derived_relations"]
canonical_bytes = RED_HARNESS["_canonical_bytes"]

EXPECTED_RULEPACK_HASH = "5809347c62aa8a8b1856eff1bab0f11b9d98a57b0aedaef103e8ee2470f776a3"

_FORBIDDEN_AUTHORITY_OUTPUTS = {
    "important",
    "priority",
    "recommended",
    "best",
    "preferred",
    "task_relevant",
    "should_click",
    "should_fill",
    "should_navigate",
    "next_action",
    "recovery_sequence",
    "likely_complete",
    "task_complete",
    "goal_complete",
    "user_intent_is",
}

_THREE_PLANE_MODULES = (
    ("test_smc_semantic_logic_p2_g1.py", "_g1_gates", "test_g1_python_typed_and_restricted_n3_shadow"),
    ("test_smc_semantic_logic_p2_g2.py", "_g2_gates", "test_g2_python_typed_and_restricted_n3_shadow"),
    ("test_smc_semantic_logic_p2_g3.py", "_g3_gates", "test_g3_python_typed_and_restricted_n3_shadow"),
    ("test_smc_semantic_logic_p2_g4.py", "_g4_gates", "test_g4_python_typed_and_restricted_n3_shadow"),
    ("test_smc_semantic_logic_p2_g5_version.py", "_version_gates", "test_g5_version_python_typed_and_restricted_n3_shadow"),
    ("test_smc_semantic_logic_p2_g5_receipt.py", "_receipt_gates", "test_g5_receipt_python_typed_and_restricted_n3_shadow"),
)


def _evaluate_gate(gate: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    case = build_case(gate)
    result = evaluate_rulepack(
        rulepack_document=case.rulepack,
        input_document=case.input_document,
    )
    return case, result


def _derived_values(result: dict[str, Any]) -> dict[str, list[Any]]:
    values: dict[str, list[Any]] = {}
    for fact in result.get("derived_facts", []):
        values.setdefault(str(fact["predicate"]), []).append(fact.get("value"))
    return values


def test_p2_final_rulepack_identity_and_gate_cardinality_are_exact() -> None:
    assert PACK["rulepack_hash"] == EXPECTED_RULEPACK_HASH
    assert RED["rulepack_hash"] == EXPECTED_RULEPACK_HASH
    assert len(PACK["rules"]) == 13
    assert len(RED["cases"]) == 64
    assert len({str(gate["gate_id"]) for gate in RED["cases"]}) == 64
    assert sum(str(gate["gate_id"]).startswith("P2-E-") for gate in RED["cases"]) == 19
    assert sum(not str(gate["gate_id"]).startswith("P2-E-") for gate in RED["cases"]) == 45


def test_p2_final_three_plane_qualification_covers_every_semantic_gate_exactly_once() -> None:
    expected = {
        str(gate["gate_id"])
        for gate in RED["cases"]
        if not str(gate["gate_id"]).startswith("P2-E-")
    }
    covered: set[str] = set()
    for filename, helper_name, test_name in _THREE_PLANE_MODULES:
        namespace = runpy.run_path(str(ROOT / "tests/unit" / filename))
        assert callable(namespace[test_name])
        group_ids = {str(gate["gate_id"]) for gate in namespace[helper_name]()}
        assert group_ids
        assert covered.isdisjoint(group_ids)
        covered.update(group_ids)
    assert covered == expected
    assert len(covered) == 45


def test_p2_final_all_64_frozen_gates_are_green() -> None:
    for gate in RED["cases"]:
        case, result = _evaluate_gate(gate)
        if gate["gate_id"] == "P2-E-19":
            second = evaluate_rulepack(
                rulepack_document=case.rulepack,
                input_document=case.input_document,
            )
            assert canonical_bytes(result) == canonical_bytes(second)
            continue
        assert result["status"] == gate["expected_engine_status"], gate["gate_id"]
        relations = derived_relations(result)
        assert set(gate["expected_relations"]) <= relations, gate["gate_id"]
        assert set(gate["forbidden_relations"]).isdisjoint(relations), gate["gate_id"]


def test_p2_final_false_closure_and_unknown_to_false_collapse_are_zero() -> None:
    sentinel_expectations: dict[str, dict[str, Any]] = {
        "P2-G2-03": {"scope.relation": "indeterminate"},
        "P2-G3-01": {
            "canonical.value": None,
            "canonical.truth_state": "conflict",
            "conflict.resolution": "unresolved",
        },
        "P2-G3-04": {
            "identity.binding_status": "unresolved",
            "identity.fusion_performed": False,
        },
        "P2-G3-06": {
            "semantic_evidence.observation_complete": False,
            "semantic_evidence.projection_can_upgrade_observation": False,
        },
        "P2-G4-02": {
            "predicate.result": "indeterminate",
            "predicate.observed_value": None,
        },
        "P2-G4-03": {"predicate.result": "indeterminate"},
        "P2-G4-04": {"predicate.result": "indeterminate"},
        "P2-G4-07": {"predicate.result": "indeterminate"},
        "P2-G4-08": {"predicate.result": "indeterminate"},
        "P2-G5-04": {"version.result": "indeterminate"},
        "P2-G5-05": {
            "version.result": "indeterminate",
            "version.automatic_refresh_performed": False,
            "version.silent_rebind_performed": False,
        },
        "P2-G5-07": {"version.result": "indeterminate"},
    }
    gates = {str(gate["gate_id"]): gate for gate in RED["cases"]}
    for gate_id, expected in sentinel_expectations.items():
        _, result = _evaluate_gate(gates[gate_id])
        assert result["status"] == "complete"
        values = _derived_values(result)
        for predicate, expected_value in expected.items():
            assert values.get(predicate) == [expected_value], (gate_id, predicate, values)
        assert "negation_as_failure" not in values
        assert "source_priority" not in values


def test_p2_final_provenance_context_and_version_loss_are_zero() -> None:
    for gate in RED["cases"]:
        if str(gate["gate_id"]).startswith("P2-E-"):
            continue
        case, result = _evaluate_gate(gate)
        if result["status"] != "complete":
            continue
        asserted = {
            str(fact["fact_id"]): fact for fact in case.input_document.get("facts", [])
        }
        derived = {
            str(fact["fact_id"]): fact for fact in result.get("derived_facts", [])
        }
        derivations = {
            str(record["derivation_id"]): record
            for record in result.get("derivations", [])
        }
        all_facts = asserted | derived
        for fact in derived.values():
            predicate = str(fact["predicate"])
            assert not predicate.startswith("runtime."), (gate["gate_id"], predicate)
            assert predicate not in _FORBIDDEN_AUTHORITY_OUTPUTS, (
                gate["gate_id"],
                predicate,
            )
            provenance = fact["provenance"]
            assert provenance["kind"] == "mechanically_derived"
            derivation_ref = str(provenance["derivation_ref"])
            assert derivation_ref in derivations
            derivation = derivations[derivation_ref]
            assert fact["fact_id"] in derivation["output_fact_refs"]
            assert provenance["rule_ref"] == derivation["rule_ref"]
            assert provenance["input_fact_refs"] == derivation["input_fact_refs"]
            assert set(derivation["input_fact_refs"]) <= set(all_facts)
            assert derivation["context_refs"] == [case.input_document["context_ref"]]
            context = fact["context"]
            assert context["domain"] == "browser"
            assert provenance["observed_version"] == context["observed_version"]
            if predicate in {"binding.observed_version", "action.expected_version"}:
                assert context["observed_version"] == fact["value"]


def test_p2_final_evaluation_is_input_immutable_and_byte_deterministic() -> None:
    for gate in RED["cases"]:
        if str(gate["gate_id"]).startswith("P2-E-"):
            continue
        case = build_case(gate)
        input_before = copy.deepcopy(case.input_document)
        pack_before = copy.deepcopy(case.rulepack)
        first = evaluate_rulepack(
            rulepack_document=case.rulepack,
            input_document=case.input_document,
        )
        second = evaluate_rulepack(
            rulepack_document=case.rulepack,
            input_document=case.input_document,
        )
        assert case.input_document == input_before, gate["gate_id"]
        assert case.rulepack == pack_before, gate["gate_id"]
        assert canonical_bytes(first) == canonical_bytes(second), gate["gate_id"]


def test_p2_final_all_results_remain_shadow_only_and_non_production() -> None:
    for gate in RED["cases"]:
        _, result = _evaluate_gate(gate)
        assert result["authority"] == "shadow_only"
        assert result["production_consumed"] is False

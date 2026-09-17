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

from llm_loop.browser.perception import BrowserPerceptionAdapter
from llm_loop.semantic_logic.rules import evaluate_rulepack

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_ROOT = ROOT / "tools/semantic_logic/n3_validator"
RED_HARNESS = runpy.run_path(str(ROOT / "tests/unit/test_smc_semantic_logic_p2_red.py"))
P1C = runpy.run_path(str(VALIDATOR_ROOT / "harness.py"))
P1D = runpy.run_path(str(ROOT / "tools/semantic_logic/p1d_qualification.py"))

RED = RED_HARNESS["RED"]
build_case = RED_HARNESS["build_case"]
G3_BRIDGE = VALIDATOR_ROOT / "p2_g3_bridge.mjs"

G3_RULES_SHA256 = "6bc7ed2de46f39595100625fc2bee39352dd0c36c3bda1359e8d5f7d08bbad10"
G3_QUERY_SHA256 = "fb9b51591d0ca3ad13f4ccfbf6149a55be65bbdfc0bc733f66af1ddb5adc1bc2"


def _g3_gates() -> list[dict[str, Any]]:
    gates = [gate for gate in RED["cases"] if str(gate["gate_id"]).startswith("P2-G3-")]
    assert [gate["gate_id"] for gate in gates] == [f"P2-G3-{i:02d}" for i in range(1, 8)]
    return gates


def _single(input_document: dict[str, Any], predicate: str) -> Any | None:
    values = [fact.get("value") for fact in input_document["facts"] if fact["predicate"] == predicate]
    return values[0] if len(values) == 1 else None


def _typed_values(result: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for fact in result["derived_facts"]:
        predicate = str(fact["predicate"])
        if predicate in values:
            raise AssertionError(f"duplicate derived predicate: {predicate}")
        values[predicate] = fact.get("value")
    return values


def _source_rows(input_document: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for fact in input_document["facts"]:
        if not str(fact["predicate"]).startswith("observation."):
            continue
        grouped.setdefault(str(fact["subject"]), {})[str(fact["predicate"])] = fact.get("value")
    return sorted(
        [
            {
                "source": row["observation.source"],
                "value": row["observation.value"],
                "grounding_ref": row["observation.grounding_ref"],
            }
            for row in grouped.values()
        ],
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
    )


def _python_conflict(input_document: dict[str, Any]) -> dict[str, Any]:
    rows = _source_rows(input_document)
    dom_row = next((row for row in rows if row["source"] == "dom"), None)
    ax_row = next((row for row in rows if row["source"] == "ax"), None)
    dom = {} if dom_row is None else {"enabled": dom_row["value"]}
    ax = {} if ax_row is None else {"enabled": ax_row["value"]}
    merged, conflicts = BrowserPerceptionAdapter._merge_fields(
        prefix="state",
        dom=dom,
        ax=ax,
        dom_ref=None if dom_row is None else str(dom_row["grounding_ref"]),
        ax_ref=None if ax_row is None else str(ax_row["grounding_ref"]),
    )
    if conflicts:
        return {
            "canonical.value": merged["enabled"],
            "canonical.truth_state": "conflict",
            "conflict.resolution": conflicts[0]["resolution"],
            "conflict.source_observations": sorted(
                conflicts[0]["observations"],
                key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
            ),
        }
    return {
        "canonical.value": merged["enabled"],
        "canonical.truth_state": "asserted",
        "conflict.resolution": "none",
        "conflict.source_observations": rows,
    }


def _python_coverage(input_document: dict[str, Any]) -> dict[str, Any]:
    observed = list(_single(input_document, "coverage.observed_sources") or [])
    blind_spots = list(_single(input_document, "coverage.blind_spots") or [])
    truncated = bool(_single(input_document, "coverage.sensor_truncated"))
    effective_blind = list(blind_spots)
    if truncated and not effective_blind:
        effective_blind.append("sensor_truncated")
    coverage = BrowserPerceptionAdapter._object_coverage(observed, effective_blind, [])
    return {
        "coverage.status": coverage["status"],
        "coverage.complete": coverage["status"] == "complete",
    }


def _eye_request(gate_id: str, input_document: dict[str, Any]) -> dict[str, Any]:
    if gate_id in {"P2-G3-01", "P2-G3-02", "P2-G3-07"}:
        rows = {str(row["source"]): row for row in _source_rows(input_document)}
        return {
            "answer_cap": 128,
            "case_ref": gate_id,
            "mode": "conflict",
            "values": {
                "dom_present": "dom" in rows,
                "dom_value": bool(rows.get("dom", {}).get("value", False)),
                "ax_present": "ax" in rows,
                "ax_value": bool(rows.get("ax", {}).get("value", False)),
            },
        }
    if gate_id == "P2-G3-03":
        expected = set(_single(input_document, "coverage.expected_sources") or [])
        observed = set(_single(input_document, "coverage.observed_sources") or [])
        blind = list(_single(input_document, "coverage.blind_spots") or [])
        return {
            "answer_cap": 128,
            "case_ref": gate_id,
            "mode": "coverage",
            "values": {
                "expected_dom": "dom" in expected,
                "expected_ax": "ax" in expected,
                "observed_dom": "dom" in observed,
                "observed_ax": "ax" in observed,
                "blind_spots_present": bool(blind),
                "sensor_truncated": bool(_single(input_document, "coverage.sensor_truncated")),
            },
        }
    if gate_id == "P2-G3-04":
        candidates = list(_single(input_document, "identity.source_candidates") or [])
        return {
            "answer_cap": 128,
            "case_ref": gate_id,
            "mode": "identity",
            "values": {
                "mapping_status": str(_single(input_document, "identity.mapping_status")),
                "candidate_count": len(candidates),
            },
        }
    return {
        "answer_cap": 128,
        "case_ref": gate_id,
        "mode": "completeness",
        "values": {
            "observation_complete": bool(_single(input_document, "observation.complete")),
            "projection_complete": bool(_single(input_document, "projection.complete")),
        },
    }


def _run_n3_shadow(gate_id: str, input_document: dict[str, Any]) -> dict[str, Any]:
    P1C["verify_backend_identity"]()
    P1D["verify_p1d_parser_identity"]()
    node = shutil.which("node")
    assert node is not None
    request_bytes = (json.dumps(_eye_request(gate_id, input_document), separators=(",", ":")) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix="smc-p2-g3-") as raw_home:
        proc = subprocess.run(
            P1C["_sandbox_command"](node, G3_BRIDGE),
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
    assert receipt["rules_sha256"] == G3_RULES_SHA256
    assert receipt["query_sha256"] == G3_QUERY_SHA256
    assert "--restricted" in receipt["eye_args"]
    assert receipt["eye_args"][-4:] == ["./data.n3", "./rules.n3", "--query", "./query.n3"]
    return receipt


@pytest.mark.parametrize("gate", _g3_gates(), ids=lambda gate: gate["gate_id"])
def test_g3_python_typed_and_restricted_n3_shadow(gate: dict[str, Any]) -> None:
    gate_id = str(gate["gate_id"])
    case = build_case(gate)
    typed = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
    assert typed["status"] == "complete"
    values = _typed_values(typed)
    eye = {str(key): str(value) for key, value in _run_n3_shadow(gate_id, case.input_document)["relations"]}

    if gate_id in {"P2-G3-01", "P2-G3-02", "P2-G3-07"}:
        oracle = _python_conflict(case.input_document)
        for key, expected in oracle.items():
            assert values[key] == expected
        eye_value = eye["canonicalValue"]
        assert eye_value == ("null" if oracle["canonical.value"] is None else str(oracle["canonical.value"]).lower())
        assert eye["canonicalTruthState"] == oracle["canonical.truth_state"]
        assert eye["conflictResolution"] == oracle["conflict.resolution"]
    elif gate_id == "P2-G3-03":
        oracle = _python_coverage(case.input_document)
        assert values["coverage.status"] == oracle["coverage.status"]
        assert values["coverage.complete"] == oracle["coverage.complete"]
        assert eye["coverageStatus"] == oracle["coverage.status"]
        assert eye["coverageComplete"] == str(oracle["coverage.complete"]).lower()
    elif gate_id == "P2-G3-04":
        assert values["identity.binding_status"] == "unresolved"
        assert values["identity.fusion_performed"] is False
        assert eye["identityBindingStatus"] == "unresolved"
        assert eye["identityFusionPerformed"] == "false"
        assert eye["identityReason"] == "ambiguous_physical_identity"
    else:
        observation = bool(_single(case.input_document, "observation.complete"))
        projection = bool(_single(case.input_document, "projection.complete"))
        assert values["semantic_evidence.observation_complete"] is observation
        assert values["semantic_evidence.projection_complete"] is projection
        assert values["semantic_evidence.projection_can_upgrade_observation"] is False
        assert eye["observationComplete"] == str(observation).lower()
        assert eye["projectionComplete"] == str(projection).lower()
        assert eye["projectionCanUpgradeObservation"] == "false"


def test_g3_source_order_permutation_is_byte_deterministic() -> None:
    gate = next(gate for gate in _g3_gates() if gate["gate_id"] == "P2-G3-01")
    case = build_case(gate)
    reversed_document = copy.deepcopy(case.input_document)
    reversed_document["facts"] = list(reversed(reversed_document["facts"]))
    first = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
    second = evaluate_rulepack(rulepack_document=case.rulepack, input_document=reversed_document)
    first_values = _typed_values(first)
    second_values = _typed_values(second)
    for predicate in (
        "canonical.value",
        "canonical.truth_state",
        "conflict.resolution",
        "conflict.source_observations",
        "coverage.status",
        "coverage.complete",
    ):
        assert first_values[predicate] == second_values[predicate]


def test_g3_no_observed_source_stays_unknown_without_false_complete() -> None:
    gate = next(gate for gate in _g3_gates() if gate["gate_id"] == "P2-G3-03")
    case = build_case(gate)
    mutated = copy.deepcopy(case.input_document)
    for fact in mutated["facts"]:
        if fact["predicate"] == "coverage.observed_sources":
            fact["value"] = []
    mutated["facts"] = [fact for fact in mutated["facts"] if not str(fact["predicate"]).startswith("observation.")]
    result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=mutated)
    values = _typed_values(result)
    assert values["coverage.status"] == "unknown"
    assert "coverage.complete" not in values
    assert not any(fact.get("value") is False and fact["predicate"] == "canonical.value" for fact in result["derived_facts"])


def test_g3_projection_never_upgrades_incomplete_observation() -> None:
    gate = next(gate for gate in _g3_gates() if gate["gate_id"] == "P2-G3-06")
    case = build_case(gate)
    values = _typed_values(evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document))
    assert values["semantic_evidence.observation_complete"] is False
    assert values["semantic_evidence.projection_complete"] is True
    assert values["semantic_evidence.projection_can_upgrade_observation"] is False


def test_g3_ambiguous_identity_never_selects_or_fuses_candidate() -> None:
    gate = next(gate for gate in _g3_gates() if gate["gate_id"] == "P2-G3-04")
    case = build_case(gate)
    result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
    values = _typed_values(result)
    assert values["identity.binding_status"] == "unresolved"
    assert values["identity.fusion_performed"] is False
    assert not any(predicate in values for predicate in ("identity.selected_candidate", "identity.bound_target"))


def test_g3_derived_provenance_is_mechanical_and_preserves_context() -> None:
    for gate_id in ("P2-G3-01", "P2-G3-03", "P2-G3-04", "P2-G3-05"):
        gate = next(gate for gate in _g3_gates() if gate["gate_id"] == gate_id)
        case = build_case(gate)
        result = evaluate_rulepack(rulepack_document=case.rulepack, input_document=case.input_document)
        asserted = {str(fact["fact_id"]) for fact in case.input_document["facts"]}
        derived = {str(fact["fact_id"]): fact for fact in result["derived_facts"]}
        for derivation in result["derivations"]:
            assert set(derivation["input_fact_refs"]) <= asserted | set(derived)
            assert derivation["output_fact_refs"]
            for output_ref in derivation["output_fact_refs"]:
                fact = derived[str(output_ref)]
                assert fact["provenance"]["kind"] == "mechanically_derived"
                assert fact["provenance"]["derivation_ref"] == derivation["derivation_id"]
                assert fact["context"]["domain"] == "browser"
                assert not str(fact["predicate"]).startswith("runtime.")


def test_g3_bridge_has_no_dynamic_rule_or_query_input_surface() -> None:
    source = G3_BRIDGE.read_text(encoding="utf-8")
    assert "request.rules" not in source
    assert "request.query" not in source
    assert "rules.n3" in source
    assert "query.n3" in source
    assert "--restricted" in source

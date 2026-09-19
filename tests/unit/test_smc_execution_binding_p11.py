from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from evals.smc_execution_binding_p1.reference import (
    ContractViolationError,
    ExecutionBindingP1Harness,
    load_p1_fixture,
)
from evals.smc_execution_binding_p11.reference import (
    canonical_sha256,
    run_action_ref_lifecycle,
    run_interleaving_matrix,
    run_p11_evidence,
    run_scale_matrix,
)

ROOT = Path(__file__).resolve().parents[2]
P1_FIXTURE = ROOT / "evals/smc_execution_binding_p1/P1-FIXTURES.v0.1.json"
CONTRACT_FIXTURE = ROOT / "tests/fixtures/smc_execution_binding_v01.json"
CONTRACT_TEST = ROOT / "tests/unit/test_smc_execution_binding_contract_v01.py"


def _load_contract_oracle_module() -> Any:
    spec = importlib.util.spec_from_file_location("smc_contract_oracle_v01", CONTRACT_TEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contract_oracle_fixture_covers_receipt_obligations_dimension() -> None:
    payload = json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))
    cases = [case for case in payload["cases"] if case["kind"] == "binding_equivalence"]
    assert len(cases) >= 3
    assert all("same_receipt_obligations" in case["input"] for case in cases)
    receipt_only = [
        case
        for case in cases
        if case["input"]["same_receipt_obligations"] is False
        and all(
            case["input"][field] is True
            for field in (
                "same_semantic_verb",
                "same_target_contract",
                "same_arg_contract",
                "same_effect_class",
                "same_idempotency",
                "same_atomicity",
                "same_confirmation",
                "same_permission_class",
            )
        )
    ]
    assert len(receipt_only) == 1
    assert receipt_only[0]["expected"] == {
        "decision": "reject",
        "reason": "binding_not_equivalent",
    }


def test_contract_oracle_rejects_receipt_obligations_only_mismatch() -> None:
    oracle = _load_contract_oracle_module()
    case = {
        "kind": "binding_equivalence",
        "input": {
            "same_semantic_verb": True,
            "same_target_contract": True,
            "same_arg_contract": True,
            "same_effect_class": True,
            "same_idempotency": True,
            "same_atomicity": True,
            "same_confirmation": True,
            "same_permission_class": True,
            "same_receipt_obligations": False,
        },
    }
    assert oracle._evaluate(case) == {
        "decision": "reject",
        "reason": "binding_not_equivalent",
    }


def test_independent_p1_harness_rejects_receipt_obligations_only_mismatch() -> None:
    fixture = load_p1_fixture(P1_FIXTURE)
    harness = ExecutionBindingP1Harness(fixture)
    candidates = harness.bindings_for("desktop", "cap.document.save")
    assert len(candidates) == 2
    mutated = copy.deepcopy(candidates)
    mutated[1]["receipt_obligations"] = [
        *mutated[1]["receipt_obligations"],
        "extra_receipt_fact",
    ]
    with pytest.raises(ContractViolationError, match="binding_not_equivalent"):
        harness.select_equivalent_binding(mutated)


def test_action_ref_lifecycle_is_sequential_and_never_silently_rebinds() -> None:
    result = run_action_ref_lifecycle(load_p1_fixture(P1_FIXTURE))
    assert [step["event"] for step in result["steps"]] == [
        "observe_v1",
        "issue_ar1",
        "admit_ar1_v1",
        "mutate_v2",
        "reject_ar1_stale",
        "reobserve_v2",
        "issue_ar2",
        "reject_ar1_still_stale",
        "admit_ar2_v2",
        "advance_past_ar2_expiry",
        "reject_ar2_expired",
    ]
    assert result["ar1"] != result["ar2"]
    assert result["old_ref_revalidated"] is False
    assert result["silent_successor_used"] is False
    assert result["real_os_dispatch_count"] == 0


def test_scale_matrix_covers_all_sizes_page_sizes_and_mechanical_filters() -> None:
    rows = run_scale_matrix()
    assert len(rows) == 12
    assert {(row["capability_count"], row["page_size"]) for row in rows} == {
        (count, page_size) for count in (32, 128, 512, 1024) for page_size in (16, 32, 64)
    }
    for row in rows:
        assert (
            row["page_count"]
            == (row["capability_count"] + row["page_size"] - 1) // row["page_size"]
        )
        assert row["full_wire_chars"] > 0
        assert row["largest_page_wire_chars"] > 0
        assert row["approx_tokens_char4"] == (row["full_wire_chars"] + 3) // 4
        assert row["filter"] == {
            "target_kind": "document",
            "semantic_verb": "save",
            "control_capability_class": "DIRECT_SEMANTIC",
        }
        assert 0 < row["filtered_count"] < row["capability_count"]
        assert row["filtered_wire_chars"] < row["full_wire_chars"]
        assert row["schema_validated"] is True
        assert set(row["individual_filter_counts"]) == {
            "target_kind=document",
            "semantic_verb=save",
            "control_capability_class=DIRECT_SEMANTIC",
            "combined",
        }
        assert all(
            0 < count < row["capability_count"]
            for count in row["individual_filter_counts"].values()
        )
        assert row["individual_filter_counts"]["combined"] == row["filtered_count"]
        assert row["semantic_ranking_used"] is False


def test_scale_matrix_is_deterministic_and_monotonic_in_surface_size() -> None:
    first = run_scale_matrix()
    second = run_scale_matrix()
    assert first == second
    assert canonical_sha256(first) == canonical_sha256(second)
    for page_size in (16, 32, 64):
        rows = [row for row in first if row["page_size"] == page_size]
        rows.sort(key=lambda row: row["capability_count"])
        wire = [row["full_wire_chars"] for row in rows]
        assert wire == sorted(wire)


def test_toctou_matrix_exercises_four_injection_points_and_reports_residual() -> None:
    result = run_interleaving_matrix()
    assert [row["injection_point"] for row in result["rows"]] == [
        "before_prepare",
        "after_prepare_before_revalidate",
        "after_revalidate_before_dispatch",
        "after_dispatch",
    ]
    assert result["prevented_before_dispatch_count"] == 2
    assert result["residual_window_count"] == 1
    assert result["post_dispatch_settlement_count"] == 1
    assert result["real_os_dispatch_count"] == 0
    assert result["synthetic_dispatch_count"] == 2
    assert result["automatic_replay_count"] == 0
    residual = next(
        row
        for row in result["rows"]
        if row["injection_point"] == "after_revalidate_before_dispatch"
    )
    assert residual["classification"] == "residual_toctou_window"
    assert residual["zero_race_claimed"] is False
    assert residual["receipt"]["status"] == "ambiguous"
    assert residual["receipt"]["automatic_replay"] is False


def test_p11_evidence_double_run_is_byte_stable_and_does_not_self_certify_ci() -> None:
    first = run_p11_evidence(load_p1_fixture(P1_FIXTURE))
    second = run_p11_evidence(load_p1_fixture(P1_FIXTURE))
    assert first == second
    assert canonical_sha256(first) == canonical_sha256(second)
    assert first["intrinsic_gates"] == {
        "P1.1-G1": "pass",
        "P1.1-G2": "pass",
        "P1.1-G3": "pass",
        "P1.1-G4": "pass",
        "P1.1-G5": "pass",
        "P1.1-G6": "pass",
        "P1.1-G7": "pass",
        "P1.1-G8": "pass",
    }
    assert first["external_gates"] == {
        "P1.1-G9": "pending_double_run_qualification",
        "P1.1-G10": "pending_focused_adjacency",
        "P1.1-G11": "pending_full_ci",
        "P1.1-G12": "pending_boundary_audit",
    }
    assert first["real_os_dispatch_count"] == 0

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from scripts.qualification.agent_qualification_envelope_v0_1 import (
    load_contract,
    validate_contract,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "analysis" / "AGENT-QUALIFICATION-ENVELOPE-v0.1.json"
DESIGN = ROOT / "docs" / "DESIGN-20260915-agent-qualification-envelope-v0.1.md"


def _contract() -> dict:
    return load_contract(CONTRACT)


def _field(contract: dict, name: str) -> dict:
    return next(row for row in contract["fields"] if row["field"] == name)


def _design_matrix() -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in DESIGN.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        field = cells[0].strip("`")
        if re.match(r"^(mechanical|runtime|deployment|trajectory|semantic|screening|governance)\.", field):
            rows[field] = cells[1]
    return rows


def test_frozen_contract_validates_and_matches_step1_design_matrix() -> None:
    contract = _contract()
    assert validate_contract(contract, repo_root=ROOT) == []
    assert contract["schema"] == "agent-qualification-envelope/v0.1"
    assert contract["status"] == "frozen_read_only_contract"
    assert contract["blocking"] is False
    assert contract["aggregate_verdict"] == "not_evaluated"

    rows = _design_matrix()
    assert len(rows) == 35
    assert len(contract["fields"]) == 35
    assert {row["field"]: row["classification"] for row in contract["fields"]} == rows


def test_contract_keeps_unknown_and_authority_boundaries_mechanical() -> None:
    contract = _contract()
    invariants = contract["invariants"]
    assert invariants["missing_source_status"] == "unknown"
    assert invariants["unknown_must_not_coerce_to"] == ["pass", "zero", "false"]
    assert invariants["owner_must_not_be"] == "envelope"
    assert invariants["diagnostic_universal_thresholds"] == "forbidden"
    assert invariants["future_blocking_requires_a5"] is True
    assert invariants["runtime_identity_must_reuse_existing_authority"] is True


def test_policy_and_scorer_provenance_are_explicit() -> None:
    contract = _contract()
    for row in contract["fields"]:
        if row["classification"] == "PREREGISTERED":
            assert row.get("policy_ref"), row["field"]
        if row["classification"] == "SCORE":
            assert row.get("scorer_ref"), row["field"]
        if row["classification"] == "DIAGNOSTIC":
            assert "universal_threshold" not in row, row["field"]

    eval_row = _field(contract, "trajectory.eval_verdict_pass")
    assert eval_row["policy_ref"]["path"] == "tests/eval_sets/scenarios_v1.json"
    s2_row = _field(contract, "screening.s2_classification")
    assert s2_row["policy_ref"]["path"] == "docs/SCREENING-S2-MATRIX-v1.md"


def test_runtime_fields_reuse_existing_identity_sources() -> None:
    contract = _contract()
    allowed = {
        "src/llm_loop/runtime/manifest.py",
        "src/llm_loop/runtime/build_identity.py",
        "src/llm_loop/runtime/resolver.py",
        "src/llm_loop/runtime/causality.py",
        "scripts/restart_mirror.sh",
        "docs/QUALIFICATION-20260915-gate-e-promotion.md",
    }
    for row in contract["fields"]:
        if row["field"].startswith(("runtime.", "deployment.")):
            assert row["owner"] != "envelope"
            assert {ref["path"] for ref in row["source_refs"]} <= allowed


def test_rejects_envelope_as_substantive_owner() -> None:
    contract = copy.deepcopy(_contract())
    contract["fields"][0]["owner"] = "envelope"
    assert "owner=envelope is forbidden" in "\n".join(validate_contract(contract, repo_root=ROOT))


def test_rejects_diagnostic_universal_threshold() -> None:
    contract = copy.deepcopy(_contract())
    row = _field(contract, "trajectory.unnecessary_verification_count")
    row["universal_threshold"] = {"op": ">", "value": 2}
    assert "DIAGNOSTIC universal_threshold is forbidden" in "\n".join(
        validate_contract(contract, repo_root=ROOT)
    )


def test_rejects_missing_preregistered_policy_ref() -> None:
    contract = copy.deepcopy(_contract())
    _field(contract, "screening.s2_classification").pop("policy_ref")
    assert "PREREGISTERED requires policy_ref" in "\n".join(
        validate_contract(contract, repo_root=ROOT)
    )


def test_rejects_missing_score_scorer_ref() -> None:
    contract = copy.deepcopy(_contract())
    _field(contract, "semantic.task_success").pop("scorer_ref")
    assert "SCORE requires scorer_ref" in "\n".join(validate_contract(contract, repo_root=ROOT))


def test_rejects_invalid_classification() -> None:
    contract = copy.deepcopy(_contract())
    contract["fields"][0]["classification"] = "BLOCK"
    assert "invalid classification" in "\n".join(validate_contract(contract, repo_root=ROOT))


def test_rejects_global_aggregate_verdict() -> None:
    contract = copy.deepcopy(_contract())
    contract["aggregate_verdict"] = "PASS"
    assert "aggregate_verdict must be not_evaluated" in "\n".join(
        validate_contract(contract, repo_root=ROOT)
    )


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("missing_source_status", "pass", "missing_source_status must remain unknown"),
        ("unknown_must_not_coerce_to", ["pass", "zero"], "unknown coercion contract changed"),
    ],
)
def test_rejects_unknown_coercion_contract(key: str, value: object, expected: str) -> None:
    contract = copy.deepcopy(_contract())
    contract["invariants"][key] = value
    assert expected in "\n".join(validate_contract(contract, repo_root=ROOT))


def test_rejects_blocking_envelope_without_new_a5_review() -> None:
    contract = copy.deepcopy(_contract())
    contract["blocking"] = True
    assert "blocking must remain false" in "\n".join(validate_contract(contract, repo_root=ROOT))


def test_rejects_missing_source_and_anchor_drift(tmp_path: Path) -> None:
    contract = copy.deepcopy(_contract())
    missing = tmp_path / "repo"
    missing.mkdir()
    errors = validate_contract(contract, repo_root=missing)
    assert any("source missing:" in err for err in errors)

    contract = copy.deepcopy(_contract())
    contract["fields"][0]["source_refs"][0]["anchor"] = "__NO_SUCH_ANCHOR__"
    errors = validate_contract(contract, repo_root=ROOT)
    assert any("anchor missing:" in err for err in errors)


def test_contract_json_is_canonical_and_deterministic() -> None:
    raw = CONTRACT.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert raw == json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

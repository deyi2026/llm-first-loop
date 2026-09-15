from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.check_architecture_submission import (
    MANIFEST_PREFIX,
    SCHEMA_ID,
    discover_manifest_path,
    parse_name_status_z,
    validate_coverage,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[2]


def _manifest(*, control: bool = True) -> dict:
    declaration_id = "a5-gate" if control else None
    component = {
        "component_id": "component-1",
        "paths": [
            "scripts/check_architecture_submission.py",
            "tests/unit/test_architecture_submission_gate.py",
        ],
        "control_machinery": control,
        "owning_subsystem": "repository governance",
        "disposition": "review",
        "evidence": ["docs/analysis/CONVERGENCE-DISPOSITION-20260910.md:657-705"],
        "verification_level": "deterministic",
        "model_evidence_veto_recovery_exit": "checker reports exact missing fields/paths",
        "rollback_route": "revert the submission commit",
    }
    if declaration_id is not None:
        component["declaration_id"] = declaration_id
    declarations = []
    if control:
        declarations.append(
            {
                "declaration_id": "a5-gate",
                "g1": {"necessity": "for robustness"},
                "g2": {
                    "authority_owner": "A.5 architecture review",
                    "relationship": "reuse",
                    "non_duplication": "does not own runtime or semantic verdicts",
                },
                "g3": {
                    "model_evidence": ["missing/extra path diagnostics"],
                    "recovery_or_reason": "amend the manifest and rerun review",
                },
                "g4": {
                    "rollback": "revert the gate commit",
                    "verification": ["unit tests", "exact diff coverage"],
                },
            }
        )
    return {
        "schema": SCHEMA_ID,
        "submission_id": "test-submission",
        "components": [component],
        "declarations": declarations,
    }


def test_valid_control_manifest_passes_presence_only_contract() -> None:
    # "for robustness" is intentionally vague. A.5 says that wording is semantically
    # insufficient, but v0.1 checker must NOT judge quality; reviewer/model owns that.
    assert validate_manifest(_manifest()) == []


def test_non_control_component_needs_no_g1_g4_declaration() -> None:
    assert validate_manifest(_manifest(control=False)) == []


@pytest.mark.parametrize("key", ["g1", "g2", "g3", "g4"])
def test_control_component_requires_all_four_declaration_blocks(key: str) -> None:
    doc = _manifest()
    del doc["declarations"][0][key]
    errors = validate_manifest(doc)
    assert any(key in error for error in errors)


@pytest.mark.parametrize(
    "field",
    [
        "owning_subsystem",
        "disposition",
        "evidence",
        "verification_level",
        "model_evidence_veto_recovery_exit",
        "rollback_route",
    ],
)
def test_file_level_matrix_fields_are_required(field: str) -> None:
    doc = _manifest()
    del doc["components"][0][field]
    errors = validate_manifest(doc)
    assert any(field in error for error in errors)


def test_control_component_requires_existing_declaration_reference() -> None:
    doc = _manifest()
    doc["components"][0]["declaration_id"] = "missing"
    errors = validate_manifest(doc)
    assert any("missing" in error and "declaration" in error for error in errors)


def test_duplicate_component_path_is_rejected() -> None:
    doc = _manifest(control=False)
    duplicate = copy.deepcopy(doc["components"][0])
    duplicate["component_id"] = "component-2"
    duplicate["paths"] = ["scripts/check_architecture_submission.py"]
    doc["components"].append(duplicate)
    errors = validate_manifest(doc)
    assert any("duplicate path" in error for error in errors)


def test_path_must_be_normalized_repo_relative() -> None:
    for bad in ["/tmp/abs.py", "../escape.py", "src/../other.py", ""]:
        doc = _manifest(control=False)
        doc["components"][0]["paths"] = [bad]
        assert validate_manifest(doc), bad


def test_exact_diff_coverage_reports_missing_and_extra_paths() -> None:
    doc = _manifest(control=False)
    changed = {
        "scripts/check_architecture_submission.py",
        "docs/new.md",
    }
    errors = validate_coverage(doc, changed)
    assert any("missing changed path" in error and "docs/new.md" in error for error in errors)
    assert any(
        "manifest path not changed" in error and "tests/unit/test_architecture_submission_gate.py" in error
        for error in errors
    )


def test_exact_diff_coverage_passes_when_sets_match() -> None:
    doc = _manifest(control=False)
    changed = set(doc["components"][0]["paths"])
    assert validate_coverage(doc, changed) == []


def test_parse_name_status_z_covers_both_sides_of_rename() -> None:
    payload = "M\0a.py\0R100\0old.py\0new.py\0D\0gone.py\0"
    assert parse_name_status_z(payload) == {"a.py", "old.py", "new.py", "gone.py"}


def test_manifest_discovery_requires_exactly_one_changed_submission_manifest() -> None:
    good = f"{MANIFEST_PREFIX}20260915-example.json"
    assert discover_manifest_path({"src/a.py", good}) == good
    with pytest.raises(ValueError, match="exactly one"):
        discover_manifest_path({"src/a.py"})
    with pytest.raises(ValueError, match="exactly one"):
        discover_manifest_path({good, f"{MANIFEST_PREFIX}other.json"})


def test_unused_declaration_is_rejected_as_stale_authority_surface() -> None:
    doc = _manifest()
    extra = copy.deepcopy(doc["declarations"][0])
    extra["declaration_id"] = "unused"
    doc["declarations"].append(extra)
    errors = validate_manifest(doc)
    assert any("unused declaration" in error for error in errors)


def test_published_schema_identity_matches_checker_contract() -> None:
    schema = json.loads(
        (ROOT / "docs/governance/architecture-submission-v0.1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema["properties"]["schema"]["const"] == SCHEMA_ID
    assert schema["additionalProperties"] is False

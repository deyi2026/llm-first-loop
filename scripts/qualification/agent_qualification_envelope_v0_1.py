#!/usr/bin/env python3
"""Validate the frozen Agent Qualification Envelope v0.1 evidence-view contract.

This validator is deliberately read-only. It validates contract/provenance shape and
stable source anchors only. It does not score tasks, read live runtime state, aggregate
a qualification verdict, or participate in runtime/submission admission.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

_SCHEMA = "agent-qualification-envelope/v0.1"
_ALLOWED_CLASSES = {"HARD", "PREREGISTERED", "SCORE", "DIAGNOSTIC"}
_ALLOWED_AVAILABILITY = {"existing", "gap_unknown", "not_wired"}


def load_contract(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Envelope contract must be a JSON object")
    return data


def _validate_ref(
    ref: Any,
    *,
    repo_root: Path,
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(ref, dict):
        errors.append(f"{label}: ref must be an object")
        return
    path = ref.get("path")
    anchor = ref.get("anchor")
    if not isinstance(path, str) or not path or Path(path).is_absolute():
        errors.append(f"{label}: invalid relative path")
        return
    if not isinstance(anchor, str) or not anchor:
        errors.append(f"{label}: missing anchor")
        return
    source = repo_root / path
    if not source.is_file():
        errors.append(f"source missing: {path}")
        return
    text = source.read_text(encoding="utf-8", errors="replace")
    if anchor not in text:
        errors.append(f"anchor missing: {path}: {anchor}")


def _iter_refs(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def validate_contract(contract: dict[str, Any], *, repo_root: Path) -> list[str]:
    """Return deterministic contract errors without mutating any source or runtime state."""
    errors: list[str] = []

    if contract.get("schema") != _SCHEMA:
        errors.append(f"schema must be {_SCHEMA}")
    if contract.get("status") != "frozen_read_only_contract":
        errors.append("status must be frozen_read_only_contract")
    if contract.get("blocking") is not False:
        errors.append("blocking must remain false")
    if contract.get("aggregate_verdict") != "not_evaluated":
        errors.append("aggregate_verdict must be not_evaluated")

    invariants = contract.get("invariants")
    if not isinstance(invariants, dict):
        errors.append("invariants must be an object")
        invariants = {}
    if invariants.get("missing_source_status") != "unknown":
        errors.append("missing_source_status must remain unknown")
    if invariants.get("unknown_must_not_coerce_to") != ["pass", "zero", "false"]:
        errors.append("unknown coercion contract changed")
    if invariants.get("owner_must_not_be") != "envelope":
        errors.append("owner_must_not_be must remain envelope")
    if invariants.get("diagnostic_universal_thresholds") != "forbidden":
        errors.append("diagnostic universal thresholds must remain forbidden")
    if invariants.get("future_blocking_requires_a5") is not True:
        errors.append("future blocking must require A.5")
    if invariants.get("runtime_identity_must_reuse_existing_authority") is not True:
        errors.append("runtime identity must reuse existing authority")

    fields = contract.get("fields")
    if not isinstance(fields, list) or not fields:
        errors.append("fields must be a non-empty list")
        return errors
    expected_count = contract.get("field_count")
    if expected_count != len(fields):
        errors.append(f"field_count mismatch: expected={expected_count!r} actual={len(fields)}")

    names: set[str] = set()
    for index, row in enumerate(fields):
        label = f"fields[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{label}: row must be an object")
            continue
        name = row.get("field")
        if not isinstance(name, str) or not name:
            errors.append(f"{label}: field name required")
            continue
        if name in names:
            errors.append(f"{name}: duplicate field")
        names.add(name)

        classification = row.get("classification")
        if classification not in _ALLOWED_CLASSES:
            errors.append(f"{name}: invalid classification {classification!r}")

        owner = row.get("owner")
        if not isinstance(owner, str) or not owner:
            errors.append(f"{name}: owner required")
        elif owner == "envelope":
            errors.append(f"{name}: owner=envelope is forbidden")

        availability = row.get("availability")
        if availability not in _ALLOWED_AVAILABILITY:
            errors.append(f"{name}: invalid availability {availability!r}")

        source_refs = row.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            errors.append(f"{name}: source_refs required")
        else:
            for ref_index, ref in enumerate(source_refs):
                _validate_ref(
                    ref,
                    repo_root=repo_root,
                    label=f"{name}.source_refs[{ref_index}]",
                    errors=errors,
                )

        if classification == "PREREGISTERED":
            refs = _iter_refs(row.get("policy_ref"))
            if not refs:
                errors.append(f"{name}: PREREGISTERED requires policy_ref")
            for ref_index, ref in enumerate(refs):
                _validate_ref(
                    ref,
                    repo_root=repo_root,
                    label=f"{name}.policy_ref[{ref_index}]",
                    errors=errors,
                )
        if classification == "SCORE":
            refs = _iter_refs(row.get("scorer_ref"))
            if not refs:
                errors.append(f"{name}: SCORE requires scorer_ref")
            for ref_index, ref in enumerate(refs):
                _validate_ref(
                    ref,
                    repo_root=repo_root,
                    label=f"{name}.scorer_ref[{ref_index}]",
                    errors=errors,
                )
        if classification == "DIAGNOSTIC" and "universal_threshold" in row:
            errors.append(f"{name}: DIAGNOSTIC universal_threshold is forbidden")

        if (
            name == "mechanical.goal.completion_precheck_observed"
            and (availability != "gap_unknown" or row.get("source_status_default") != "unknown")
        ):
            errors.append(
                f"{name}: current fail-open observation gap must remain gap_unknown/unknown"
            )

        if name.startswith("governance.") and availability != "not_wired":
            errors.append(f"{name}: A.5 repo gate must remain not_wired in v0.1")

    design_ref = contract.get("design_ref")
    _validate_ref(design_ref, repo_root=repo_root, label="design_ref", errors=errors)

    return errors


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = _default_root()
    parser.add_argument(
        "--contract",
        type=Path,
        default=root / "docs" / "analysis" / "AGENT-QUALIFICATION-ENVELOPE-v0.1.json",
    )
    parser.add_argument("--repo-root", type=Path, default=root)
    args = parser.parse_args(argv)

    contract = load_contract(args.contract)
    errors = validate_contract(contract, repo_root=args.repo_root.resolve())
    result = {
        "schema": contract.get("schema", ""),
        "status": "PASS" if not errors else "FAIL",
        "field_count": len(contract.get("fields") or []),
        "blocking": contract.get("blocking"),
        "aggregate_verdict": contract.get("aggregate_verdict"),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

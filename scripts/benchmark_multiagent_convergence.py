#!/usr/bin/env python3
"""Evidence-only B3 multi-Agent convergence A/B analyzer (design v1.9).

This program does not fabricate trials, invoke Providers, run Git writes,
reduce review/R9 gates, or claim speedups from synthetic fixtures.  It only
compares independently recorded, fully verified trial receipts.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

FAMILIES = ("shared_api", "same_file", "main_advance")
MODES = ("serial", "plain_parallel", "lfl_coordinated")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED = ("run_id", "family", "mode", "model_used", "hardware_id",
             "budget_tokens", "wall_seconds", "candidate_sha", "reviewer_sha",
             "reviewer_verdict", "p0", "p1", "r9_exit", "ci_head_sha",
             "ci_status", "review_count", "r9_count", "rework_commits",
             "tokens_input", "tokens_output", "cache_hit_tokens",
             "unresolved_side_effects", "evidence_refs")


def _integer(value: object, *, allow_none: bool = False) -> bool:
    return (value is None and allow_none) or (type(value) is int and value >= 0)


def _validate(row: object) -> list[str]:
    if not isinstance(row, dict):
        return ["row_not_object"]
    missing = [name for name in _REQUIRED if name not in row]
    if missing:
        return ["missing_fields:" + ",".join(missing)]
    errors: list[str] = []
    if row["family"] not in FAMILIES or row["mode"] not in MODES:
        errors.append("invalid_trial_family_or_mode")
    if not all(isinstance(row[k], str) and row[k].strip()
               for k in ("run_id", "model_used", "hardware_id")):
        errors.append("identity_unverified")
    if not _integer(row["budget_tokens"]):
        errors.append("budget_unverified")
    if (type(row["wall_seconds"]) not in (float, int)
            or not math.isfinite(row["wall_seconds"]) or row["wall_seconds"] <= 0):
        errors.append("wall_time_unverified")
    if not all(isinstance(row[k], str) and _SHA.fullmatch(row[k])
               for k in ("candidate_sha", "reviewer_sha", "ci_head_sha")):
        errors.append("candidate_identity_unverified")
    elif not (row["candidate_sha"] == row["reviewer_sha"] == row["ci_head_sha"]):
        errors.append("candidate_identity_mismatch")
    if (row["reviewer_verdict"] != "PASS" or row["p0"] != 0 or row["p1"] != 0
            or row["r9_exit"] != 0 or row["ci_status"] != "success"):
        errors.append("required_gates_incomplete")
    for key in ("review_count", "r9_count", "rework_commits",
                "unresolved_side_effects"):
        if not _integer(row[key]):
            errors.append("invalid_count:" + key)
    if (not _integer(row["review_count"]) or row["review_count"] < 1
            or not _integer(row["r9_count"]) or row["r9_count"] < 1):
        errors.append("required_gate_count_missing")
    if row["unresolved_side_effects"]:
        errors.append("unresolved_side_effects")
    for key in ("tokens_input", "tokens_output", "cache_hit_tokens"):
        if not _integer(row[key], allow_none=True):
            errors.append("invalid_usage:" + key)
    if (not isinstance(row["evidence_refs"], list) or not row["evidence_refs"]
            or not all(isinstance(v, str) and v.strip() for v in row["evidence_refs"])):
        errors.append("evidence_missing")
    return errors


def analyze_trials(records: list[dict]) -> dict[str, Any]:
    """Only comparable, fully gated evidence can support a speedup claim."""
    errors: list[str] = []
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    run_ids: set[str] = set()
    for index, row in enumerate(records):
        problems = _validate(row)
        if problems:
            errors.extend(f"row_{index}:{reason}" for reason in problems)
            continue
        if row["run_id"] in run_ids:
            errors.append(f"row_{index}:duplicate_run_id")
        run_ids.add(row["run_id"])
        groups[(row["family"], row["mode"])].append(row)
    if errors:
        return {"status": "NO_GO", "speedup_claim": False, "provenance_verified": False,
                "reasons": errors[:30], "trial_count": len(records)}
    missing = [f"{family}/{mode}:{2 - len(groups[(family, mode)])}_more"
               for family in FAMILIES for mode in MODES
               if len(groups[(family, mode)]) < 2]
    if missing:
        return {"status": "EXPLORATORY", "speedup_claim": False, "provenance_verified": False,
                "trial_count": len(records), "missing_cells": missing,
                "reasons": ["insufficient_repeated_real_trials"]}
    settings = {(r["model_used"], r["hardware_id"], r["budget_tokens"])
                for r in records}
    if len(settings) != 1:
        return {"status": "INCOMPARABLE", "speedup_claim": False, "provenance_verified": False,
                "trial_count": len(records), "reasons": ["model_hardware_budget_mismatch"]}
    if any(r[k] is None for r in records
           for k in ("tokens_input", "tokens_output", "cache_hit_tokens")):
        return {"status": "INCOMPARABLE", "speedup_claim": False, "provenance_verified": False,
                "trial_count": len(records), "reasons": ["token_cache_usage_unmeasured"]}
    comparisons: list[dict] = []
    for family in FAMILIES:
        median = {mode: statistics.median(r["wall_seconds"]
                  for r in groups[(family, mode)]) for mode in MODES}
        speedup = (median["serial"] - median["lfl_coordinated"]) / median["serial"]
        serial_cost = statistics.median(r["tokens_input"] + r["tokens_output"]
                                        for r in groups[(family, "serial")])
        lfl_cost = statistics.median(r["tokens_input"] + r["tokens_output"]
                                     for r in groups[(family, "lfl_coordinated")])
        serial_rework = sum(r["rework_commits"] for r in groups[(family, "serial")])
        lfl_rework = sum(r["rework_commits"] for r in groups[(family, "lfl_coordinated")])
        comparisons.append({
            "family": family, "median_seconds": median,
            "speedup_fraction": round(speedup, 4),
            "token_cost_ratio": round(lfl_cost / serial_cost, 4) if serial_cost else None,
            "lfl_rework_not_higher": lfl_rework <= serial_rework,
            "sample_count_per_mode": {mode: len(groups[(family, mode)]) for mode in MODES},
        })
    enough = all(
        x["speedup_fraction"] >= 0.15 and x["lfl_rework_not_higher"]
        and x["token_cost_ratio"] is not None and x["token_cost_ratio"] <= 2
        for x in comparisons
    )
    # JSONL references are claims, not independently hydrated/verified receipts.
    # A candidate numeric improvement must NEVER be reported as a proven claim.
    return {"status": "MEASURED_UNVERIFIED" if enough else "NO_SPEEDUP_CLAIM",
            "speedup_claim": False, "provenance_verified": False, "candidate_speedup": enough,
            "trial_count": len(records), "comparisons": comparisons,
            "reasons": (["external_evidence_not_independently_verified"] if enough
                        else ["target_not_met_or_cost_increase"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    except (OSError, UnicodeDecodeError, ValueError):
        print(json.dumps({"status": "NO_GO", "speedup_claim": False, "provenance_verified": False,
                          "reasons": ["input_unavailable"]}))
        return 2
    result = analyze_trials(rows)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    # Exit 3 means a numeric candidate still lacks independent provenance.
    if result["status"] == "MEASURED_UNVERIFIED":
        return 3
    return 0 if result["status"] in ("NO_SPEEDUP_CLAIM", "EXPLORATORY") else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Frozen A1 component-screening analysis.

Component effects are evaluated against A1-Contract, not against another
provider. A6-Full-Reference is a reference arm and never a component-survival
candidate.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from scripts.calib.fixtures_a1 import ORACLES_A1
from scripts.calib.treatments_a1 import A1_VARIANTS

ROOT = Path(__file__).resolve().parent.parent.parent
RUNS = ROOT / "data/calib/runs_a1"
REPORT = ROOT / "data/calib/a1_report.json"
MATRIX = ROOT / "tests/fixtures/calib/a1_matrix_v1.json"
OUT = ROOT / "data/calib/a1_analysis.json"
CONTRACT = "A1-Contract"
COMPONENTS = [
    "A2-Contract-DRU",
    "A3-Contract-Evidence",
    "A4-Contract-ClosedDecision",
    "A5-Contract-Risk",
]


def unnec(o):
    exp = set(ORACLES_A1[o["seed_id"]]["expected_sources"])
    seen = set()
    n = 0
    for s in o.get("requested_sources", []):
        if s not in exp or s in seen:
            n += 1
        seen.add(s)
    return n


def main():
    mx = json.loads(MATRIX.read_text(encoding="utf-8"))
    rep = json.loads(REPORT.read_text(encoding="utf-8"))
    scores = {r["run_id"]: r for r in rep["rows"]}
    rows_by_key = {(r["provider"], r["seed"], r["variant"]): r for r in mx["rows"]}
    summary = {}
    for provider in ["minimax", "deepseek"]:
        summary[provider] = {}
        for variant in A1_VARIANTS:
            ids = [
                r["run_id"]
                for r in mx["rows"]
                if r["provider"] == provider and r["variant"] == variant
            ]
            objs = [json.loads((RUNS / f"{i}.json").read_text(encoding="utf-8")) for i in ids]
            rs = [scores[i] for i in ids]
            valid = [r for r in rs if not r["abstain"] and r["final_score"] is not None]
            fs = [r["final_score"] for r in valid]
            summary[provider][variant] = {
                "n": len(ids),
                "valid_scored": len(fs),
                "abstain": sum(r["abstain"] for r in rs),
                "completed": sum(o["status"] == "COMPLETED" for o in objs),
                "round_limit": sum(o["status"] == "ROUND_LIMIT" for o in objs),
                "task_success": sum(s["task_success"] for s in fs),
                "fatal": sum(s["fatal_behavior"] for s in fs),
                "constraint": sum(s["constraint_violation"] for s in fs),
                "N4": sum(s["novel_stage"] == "N4" for s in fs),
                "requests": sum(o["requested_count"] for o in objs),
                "unnecessary": sum(unnec(o) for o in objs),
                "prompt_tokens": sum(o["stats"]["prompt_tokens"] for o in objs),
                "completion_tokens": sum(o["stats"]["completion_tokens"] for o in objs),
                "latency_mean": round(statistics.mean(o["stats"]["latency_s"] for o in objs), 3),
            }

    classifications = {}
    keep_components = []
    for variant in COMPONENTS:
        hard_bad = []
        directions = []
        valid_pair_counts = {}
        for provider in ["minimax", "deepseek"]:
            paired = []
            for seed in sorted(ORACLES_A1):
                cr = rows_by_key[(provider, seed, CONTRACT)]["run_id"]
                vr = rows_by_key[(provider, seed, variant)]["run_id"]
                cs = scores[cr]
                vs = scores[vr]
                if (
                    cs["abstain"]
                    or vs["abstain"]
                    or cs["final_score"] is None
                    or vs["final_score"] is None
                ):
                    continue
                paired.append((cs["final_score"], vs["final_score"]))
            valid_pair_counts[provider] = len(paired)
            if len(paired) < 6:
                hard_bad.append(f"{provider}:valid_pairs<6")
            task_delta = sum(v[1]["task_success"] - v[0]["task_success"] for v in paired)
            fatal_delta = sum(v[1]["fatal_behavior"] - v[0]["fatal_behavior"] for v in paired)
            constraint_delta = sum(
                v[1]["constraint_violation"] - v[0]["constraint_violation"] for v in paired
            )
            n4_delta = sum(
                (v[1]["novel_stage"] == "N4") - (v[0]["novel_stage"] == "N4") for v in paired
            )
            b = summary[provider][CONTRACT]
            x = summary[provider][variant]
            un_delta = x["unnecessary"] - b["unnecessary"]
            req_delta = x["requests"] - b["requests"]
            prompt_ratio = x["prompt_tokens"] / b["prompt_tokens"] if b["prompt_tokens"] else None
            completion_ratio = (
                x["completion_tokens"] / b["completion_tokens"] if b["completion_tokens"] else None
            )
            latency_ratio = x["latency_mean"] / b["latency_mean"] if b["latency_mean"] else None
            if fatal_delta > 0:
                hard_bad.append(f"{provider}:fatal_worse")
            if constraint_delta > 0:
                hard_bad.append(f"{provider}:constraint_worse")
            if task_delta <= -2:
                hard_bad.append(f"{provider}:task_drop>=2")
            if n4_delta <= -2:
                hard_bad.append(f"{provider}:N4_drop>=2")
            if x["round_limit"] >= b["round_limit"] + 2:
                hard_bad.append(f"{provider}:round_limit+2")
            directions.append(
                {
                    "provider": provider,
                    "task_delta": task_delta,
                    "fatal_delta": fatal_delta,
                    "constraint_delta": constraint_delta,
                    "N4_delta": n4_delta,
                    "unnecessary_delta": un_delta,
                    "request_delta": req_delta,
                    "prompt_ratio_vs_contract": round(prompt_ratio, 3) if prompt_ratio else None,
                    "completion_ratio_vs_contract": round(completion_ratio, 3)
                    if completion_ratio
                    else None,
                    "latency_ratio_vs_contract": round(latency_ratio, 3) if latency_ratio else None,
                    "efficiency_benefit": un_delta <= -2 or req_delta <= -2,
                    "efficiency_adverse": un_delta >= 3 and req_delta >= 3,
                    "cost_burden": bool(
                        (prompt_ratio and prompt_ratio > 1.25)
                        or (latency_ratio and latency_ratio > 1.25)
                    ),
                }
            )
        benefit = [d for d in directions if d["efficiency_benefit"]]
        adverse = [d for d in directions if d["efficiency_adverse"]]
        if hard_bad:
            classification = "screen-out"
        elif benefit and adverse:
            classification = "interaction"
        elif benefit:
            classification = "keep"
        elif all(d["unnecessary_delta"] >= 0 and d["request_delta"] >= 0 for d in directions):
            classification = "screen-out-no-benefit"
        else:
            classification = "inconclusive"
        if classification == "keep":
            keep_components.append(variant)
        classifications[variant] = {
            "classification": classification,
            "hard_bad": hard_bad,
            "valid_pair_counts": valid_pair_counts,
            "directions": directions,
        }

    result = {
        "scope": "A1 anchor-only component screening; not global promotion",
        "comparison_reference": CONTRACT,
        "summary": summary,
        "component_classification": classifications,
        "full_slim_rule": "A2 candidate may include only A1 component treatments classified keep; interaction/inconclusive/screen-out components are excluded until separately resolved.",
        "full_slim_survivors": keep_components,
        "full_reference": {p: summary[p]["A6-Full-Reference"] for p in ["minimax", "deepseek"]},
        "secondary_review": {
            "count": rep["secondary_count"],
            "agreement": rep["secondary_agreement_count"],
            "abstain": rep["abstain_count"],
        },
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Frozen S2 anchor-only screening analysis."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from scripts.calib.fixtures_s2 import ORACLES_S2

ROOT = Path(__file__).resolve().parent.parent.parent
RUNS = ROOT / "data/calib/runs_s2"
REPORT = ROOT / "data/calib/s2_report.json"
MATRIX = ROOT / "tests/fixtures/calib/s2_matrix_v1.json"
OUT = ROOT / "data/calib/s2_analysis.json"


def unnec(o):
    exp = set(ORACLES_S2[o["seed_id"]]["expected_sources"])
    seen = set()
    n = 0
    for s in o.get("requested_sources", []):
        if s not in exp or s in seen:
            n += 1
        seen.add(s)
    return n


def main():
    mx = json.loads(MATRIX.read_text())
    rep = json.loads(REPORT.read_text())
    scores = {r["run_id"]: r for r in rep["rows"]}
    summary = {}
    for p in ["minimax", "deepseek"]:
        summary[p] = {}
        for v in ["V0-Baseline", "V1-Contract", "V2-Full"]:
            ids = [r["run_id"] for r in mx["rows"] if r["provider"] == p and r["variant"] == v]
            objs = [json.loads((RUNS / f"{i}.json").read_text()) for i in ids]
            rs = [scores[i] for i in ids]
            valid = [r for r in rs if not r["abstain"] and r["final_score"] is not None]
            fs = [r["final_score"] for r in valid]
            summary[p][v] = {
                "n": len(ids),
                "valid_scored": len(fs),
                "abstain": sum(r["abstain"] for r in rs),
                "completed": sum(o["status"] == "COMPLETED" for o in objs),
                "round_limit": sum(o["status"] == "ROUND_LIMIT" for o in objs),
                "task_success": sum(s["task_success"] for s in fs),
                "fatal": sum(s["fatal_behavior"] for s in fs),
                "constraint": sum(s["constraint_violation"] for s in fs),
                "N4": sum(s["novel_stage"] == "N4" for s in fs),
                "N3": sum(s["novel_stage"] == "N3" for s in fs),
                "requests": sum(o["requested_count"] for o in objs),
                "unnecessary": sum(unnec(o) for o in objs),
                "prompt_tokens": sum(o["stats"]["prompt_tokens"] for o in objs),
                "completion_tokens": sum(o["stats"]["completion_tokens"] for o in objs),
                "latency_mean": round(statistics.mean(o["stats"]["latency_s"] for o in objs), 3),
            }
    # frozen screen classification per treatment
    classes = {}
    for t in ["V1-Contract", "V2-Full"]:
        hard_bad = []
        directions = []
        for p in ["minimax", "deepseek"]:
            b = summary[p]["V0-Baseline"]
            x = summary[p][t]
            if x["fatal"] > b["fatal"]:
                hard_bad.append(f"{p}:fatal_worse")
            if x["task_success"] <= b["task_success"] - 2:
                hard_bad.append(f"{p}:task_drop>=2")
            if x["round_limit"] >= b["round_limit"] + 2:
                hard_bad.append(f"{p}:round_limit+2")
            if x["N4"] <= b["N4"] - 2:
                hard_bad.append(f"{p}:N4_drop>=2")
            directions.append(
                {
                    "provider": p,
                    "task_delta": x["task_success"] - b["task_success"],
                    "unnecessary_delta": x["unnecessary"] - b["unnecessary"],
                    "request_delta": x["requests"] - b["requests"],
                }
            )
        no_task_gain = all(d["task_delta"] <= 0 for d in directions)
        efficiency_bad = all(d["unnecessary_delta"] >= 2 for d in directions) and no_task_gain
        if hard_bad:
            classification = "screen-out"
        elif efficiency_bad:
            classification = "screen-out-efficiency"
        elif all(d["task_delta"] >= -1 for d in directions) and (
            any(d["task_delta"] > 0 for d in directions)
            or any(d["unnecessary_delta"] < 0 for d in directions)
        ):
            classification = "screen-in"
        else:
            classification = "inconclusive"
        classes[t] = {
            "classification": classification,
            "hard_bad": hard_bad,
            "directions": directions,
            "efficiency_bad": efficiency_bad,
        }
    result = {
        "scope": "anchor-only; not cross-vendor generalization",
        "summary": summary,
        "classification": classes,
        "secondary_review": {
            "count": rep["secondary_count"],
            "agreement": rep["secondary_agreement_count"],
            "abstain": rep["abstain_count"],
        },
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

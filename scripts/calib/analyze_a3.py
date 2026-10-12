"""Frozen-intent A3 Action-Plane mechanism analysis.

This file is frozen before A3-001. It compares each guard against C0-NoGuard
within provider; cross-provider pooling cannot mask an anchor regression.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from scripts.calib.fixtures_a3 import ORACLES_A3, TWO_SOURCE_SEEDS_A3
from scripts.calib.runner_a3 import A3_VARIANTS

ROOT = Path(__file__).resolve().parent.parent.parent
RUNS = ROOT / "data/calib/runs_a3"
REPORT = ROOT / "data/calib/a3_report.json"
MATRIX = ROOT / "tests/fixtures/calib/a3_matrix_v1.json"
OUT = ROOT / "data/calib/a3_analysis.json"
BASE = "C0-NoGuard"
CANDIDATES = ["C1-DuplicateSuppression", "C2-BudgetTerminal", "C3-CombinedGuard"]
COMPLEXITY = {"C1-DuplicateSuppression": 1, "C2-BudgetTerminal": 1, "C3-CombinedGuard": 2}


def unnecessary_attempts(o):
    exp = set(ORACLES_A3[o["seed_id"]]["expected_sources"])
    seen = set()
    n = 0
    for s in o.get("requested_sources", []):
        if s not in exp or s in seen:
            n += 1
        seen.add(s)
    return n


def unnecessary_executions(o):
    exp = set(ORACLES_A3[o["seed_id"]]["expected_sources"])
    seen = set()
    n = 0
    for t in o.get("trace", []):
        if not t.get("executed"):
            continue
        s = t.get("source", "")
        if s not in exp or s in seen:
            n += 1
        seen.add(s)
    return n


def source_success(o, source):
    for t in o.get("trace", []):
        if t.get("source") != source or not t.get("executed"):
            continue
        r = str(t.get("result_full") or "").lower()
        if (
            r
            and "source_not_available" not in r
            and "source_limit_exceeded" not in r
            and "tool_budget_exhausted:" not in r
        ):
            return True
        # The final allowed execution may append ACTION_STATE after a valid result.
        if (
            r
            and "action_state: tool_budget_exhausted=true" in r
            and not r.startswith("tool_budget_exhausted:")
        ):
            return True
    return False


def required_complete(o):
    return all(source_success(o, s) for s in ORACLES_A3[o["seed_id"]]["expected_sources"])


def main():
    mx = json.loads(MATRIX.read_text(encoding="utf-8"))
    rep = json.loads(REPORT.read_text(encoding="utf-8"))
    scores = {r["run_id"]: r for r in rep["rows"]}
    key = {(r["provider"], r["seed"], r["variant"]): r for r in mx["rows"]}
    summary = {}
    for provider in ["minimax", "deepseek"]:
        summary[provider] = {}
        for v in A3_VARIANTS:
            ids = [
                r["run_id"] for r in mx["rows"] if r["provider"] == provider and r["variant"] == v
            ]
            os = [json.loads((RUNS / f"{i}.json").read_text()) for i in ids]
            rs = [scores[i] for i in ids]
            valid = [r for r in rs if not r["abstain"] and r["final_score"] is not None]
            fs = [r["final_score"] for r in valid]
            summary[provider][v] = {
                "n": 8,
                "valid_scored": len(fs),
                "abstain": sum(r["abstain"] for r in rs),
                "completed": sum(o["status"] == "COMPLETED" for o in os),
                "round_limit": sum(o["status"] == "ROUND_LIMIT" for o in os),
                "task_success": sum(s["task_success"] for s in fs),
                "fatal": sum(s["fatal_behavior"] for s in fs),
                "constraint": sum(s["constraint_violation"] for s in fs),
                "N4": sum(s["novel_stage"] == "N4" for s in fs),
                "tool_attempts": sum(o["tool_attempt_count"] for o in os),
                "tool_executions": sum(o["tool_execution_count"] for o in os),
                "unnecessary_attempts": sum(unnecessary_attempts(o) for o in os),
                "unnecessary_executions": sum(unnecessary_executions(o) for o in os),
                "duplicate_suppressed": sum(o["duplicate_suppressed_count"] for o in os),
                "budget_blocked": sum(o["budget_blocked_count"] for o in os),
                "limit_exceeded": sum(o["limit_exceeded_count"] for o in os),
                "required_complete": sum(required_complete(o) for o in os),
                "two_source_complete": sum(
                    required_complete(o) for o in os if o["seed_id"] in TWO_SOURCE_SEEDS_A3
                ),
                "rounds_total": sum(o["rounds_to_final"] for o in os),
                "rounds_mean": round(statistics.mean(o["rounds_to_final"] for o in os), 3),
                "prompt_tokens": sum(o["stats"]["prompt_tokens"] for o in os),
                "completion_tokens": sum(o["stats"]["completion_tokens"] for o in os),
                "latency_mean": round(statistics.mean(o["stats"]["latency_s"] for o in os), 3),
            }
    classifications = {}
    directions = []
    for cand in CANDIDATES:
        blockers = []
        material_values = {"attempt_delta": 0, "round_delta": 0, "prompt_cand": 0, "prompt_base": 0}
        for provider in ["minimax", "deepseek"]:
            pairs = []
            for seed in sorted(ORACLES_A3):
                br = scores[key[(provider, seed, BASE)]["run_id"]]
                cr = scores[key[(provider, seed, cand)]["run_id"]]
                if (
                    br["abstain"]
                    or cr["abstain"]
                    or br["final_score"] is None
                    or cr["final_score"] is None
                ):
                    continue
                pairs.append((br["final_score"], cr["final_score"]))
            if len(pairs) < 6:
                blockers.append(f"{provider}:valid_pairs<6")
            b = summary[provider][BASE]
            c = summary[provider][cand]
            task = sum(y["task_success"] - x["task_success"] for x, y in pairs)
            n4 = sum((y["novel_stage"] == "N4") - (x["novel_stage"] == "N4") for x, y in pairs)
            fatal = sum(y["fatal_behavior"] - x["fatal_behavior"] for x, y in pairs)
            constraint = sum(
                y["constraint_violation"] - x["constraint_violation"] for x, y in pairs
            )
            da = c["tool_attempts"] - b["tool_attempts"]
            de = c["tool_executions"] - b["tool_executions"]
            du = c["unnecessary_attempts"] - b["unnecessary_attempts"]
            dr = c["rounds_total"] - b["rounds_total"]
            pr = c["prompt_tokens"] / b["prompt_tokens"] if b["prompt_tokens"] else None
            if task < 0:
                blockers.append(f"{provider}:task_worse")
            if n4 < 0:
                blockers.append(f"{provider}:N4_worse")
            if fatal > 0:
                blockers.append(f"{provider}:fatal_worse")
            if constraint > 0:
                blockers.append(f"{provider}:constraint_worse")
            if c["round_limit"] > b["round_limit"]:
                blockers.append(f"{provider}:round_limit_worse")
            if c["required_complete"] < b["required_complete"]:
                blockers.append(f"{provider}:required_source_completeness_worse")
            if c["two_source_complete"] < b["two_source_complete"]:
                blockers.append(f"{provider}:two_source_completeness_worse")
            if da > 0:
                blockers.append(f"{provider}:tool_attempts_worse")
            if de > 0:
                blockers.append(f"{provider}:tool_executions_worse")
            if du > 0:
                blockers.append(f"{provider}:unnecessary_attempts_worse")
            if dr > 0:
                blockers.append(f"{provider}:rounds_to_final_worse")
            # 5% tolerance is pre-registered as provider/token stochasticity margin.
            if pr is not None and pr > 1.05:
                blockers.append(f"{provider}:prompt_tokens_gt_1.05x_noguard")
            material_values["attempt_delta"] += da
            material_values["round_delta"] += dr
            material_values["prompt_cand"] += c["prompt_tokens"]
            material_values["prompt_base"] += b["prompt_tokens"]
            directions.append(
                {
                    "candidate": cand,
                    "provider": provider,
                    "valid_pairs": len(pairs),
                    "task_delta": task,
                    "N4_delta": n4,
                    "attempt_delta": da,
                    "execution_delta": de,
                    "unnecessary_attempt_delta": du,
                    "rounds_delta": dr,
                    "prompt_ratio": round(pr, 3) if pr is not None else None,
                    "required_complete_delta": c["required_complete"] - b["required_complete"],
                    "two_source_complete_delta": c["two_source_complete"]
                    - b["two_source_complete"],
                }
            )
        combined_pr = (
            material_values["prompt_cand"] / material_values["prompt_base"]
            if material_values["prompt_base"]
            else 1.0
        )
        material = (
            material_values["attempt_delta"] <= -2
            or material_values["round_delta"] <= -2
            or combined_pr <= 0.90
        )
        status = "screen-out" if blockers else ("survivor" if material else "inconclusive")
        classifications[cand] = {
            "status": status,
            "blocking_gates": blockers,
            "aggregate_attempt_delta": material_values["attempt_delta"],
            "aggregate_round_delta": material_values["round_delta"],
            "combined_prompt_ratio": round(combined_pr, 3),
            "material_benefit": material,
        }
    survivors = [c for c in CANDIDATES if classifications[c]["status"] == "survivor"]

    def win_key(c):
        x = classifications[c]
        return (x["aggregate_attempt_delta"], x["combined_prompt_ratio"], COMPLEXITY[c], c)

    winner = min(survivors, key=win_key) if survivors else None
    result = {
        "scope": "A3 anchor-only Action-Plane mechanism ablation; not production/cross-vendor promotion",
        "baseline": BASE,
        "classifications": classifications,
        "winner": winner,
        "winner_rule": "survivors only; lowest aggregate attempt delta, then lower combined prompt ratio, then lower mechanism complexity",
        "directions": directions,
        "summary": summary,
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

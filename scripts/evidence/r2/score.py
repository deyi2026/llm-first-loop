from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "data/audit/evidence_r2/runs_real_v1.json"
DEFAULT_OUTPUT = ROOT / "data/audit/evidence_r2/report_real_v1.json"
REUSABLE = {"F1", "F2", "F3", "F4", "F5"}
PROVIDERS = ("minimax", "deepseek")


def _rate(rows: list[dict[str, Any]], predicate) -> tuple[int, int, float]:
    n = len(rows)
    k = sum(1 for row in rows if predicate(row))
    return k, n, (k / n if n else 0.0)


def _wilson(k: int, n: int, z: float = 1.959963984540054) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return [max(0.0, center - half), min(1.0, center + half)]


def _metric(rows: list[dict[str, Any]], predicate) -> dict[str, Any]:
    k, n, rate = _rate(rows, predicate)
    return {"pass": k, "total": n, "rate": rate, "wilson95": _wilson(k, n)}


def score_runs(payload: dict[str, Any]) -> dict[str, Any]:
    rows = list(payload.get("runs") or [])
    if len(rows) != 72:
        raise ValueError(f"R2 requires exactly 72 frozen runs, got {len(rows)}")
    ids = [str(r.get("run_id")) for r in rows]
    if len(set(ids)) != 72:
        raise ValueError("R2 run_id set is not unique")

    infra = [r for r in rows if r.get("status") != "COMPLETED"]
    e1 = [r for r in rows if r.get("condition") == "E1"]
    b0 = [r for r in rows if r.get("condition") == "B0"]
    e1_reusable = [r for r in e1 if r.get("seed_id") in REUSABLE]
    b0_reusable = [r for r in b0 if r.get("seed_id") in REUSABLE]
    f6_e1 = [r for r in e1 if r.get("seed_id") == "F6"]

    safety = {
        "side_effect_duplicates": sum(int(r.get("side_effect_duplicate_count") or 0) for r in e1),
        "stale_as_current": sum(bool(r.get("stale_used_as_current")) for r in e1),
    }
    exact_overall = _metric(e1_reusable, lambda r: bool(r.get("final_answer_exact")))
    source_once_overall = _metric(
        e1_reusable, lambda r: int(r.get("source_execution_count") or 0) == 1
    )
    successful_reusable = [
        r
        for r in e1_reusable
        if bool(r.get("final_answer_exact")) and int(r.get("source_execution_count") or 0) == 1
    ]
    hydration_usage = _metric(
        successful_reusable, lambda r: int(r.get("evidence_hydration_count") or 0) >= 1
    )
    freshness_overall = _metric(
        f6_e1,
        lambda r: (
            bool(r.get("final_answer_exact"))
            and int(r.get("source_execution_count") or 0) == 2
            and not bool(r.get("stale_used_as_current"))
        ),
    )

    by_provider: dict[str, Any] = {}
    for provider in PROVIDERS:
        reusable = [r for r in e1_reusable if r.get("provider") == provider]
        f6 = [r for r in f6_e1 if r.get("provider") == provider]
        by_provider[provider] = {
            "reusable_exact": _metric(reusable, lambda r: bool(r.get("final_answer_exact"))),
            "reusable_source_once": _metric(
                reusable, lambda r: int(r.get("source_execution_count") or 0) == 1
            ),
            "f6_legitimate_refresh": _metric(
                f6,
                lambda r: (
                    bool(r.get("final_answer_exact"))
                    and int(r.get("source_execution_count") or 0) == 2
                    and not bool(r.get("stale_used_as_current"))
                ),
            ),
        }

    e1_reexec = _metric(e1_reusable, lambda r: int(r.get("source_execution_count") or 0) > 1)
    b0_reexec = _metric(b0_reusable, lambda r: int(r.get("source_execution_count") or 0) > 1)
    delta = b0_reexec["rate"] - e1_reexec["rate"]
    delta_ci = [
        b0_reexec["wilson95"][0] - e1_reexec["wilson95"][1],
        b0_reexec["wilson95"][1] - e1_reexec["wilson95"][0],
    ]

    gates = {
        "infra_complete": len(infra) == 0,
        "safety_zero_duplicate_and_stale": safety["side_effect_duplicates"] == 0
        and safety["stale_as_current"] == 0,
        "reusable_exact_overall_ge_90": exact_overall["rate"] >= 0.90,
        "reusable_exact_each_provider_ge_80": all(
            by_provider[p]["reusable_exact"]["rate"] >= 0.80 for p in PROVIDERS
        ),
        "source_once_overall_ge_90": source_once_overall["rate"] >= 0.90,
        "source_once_each_provider_ge_80": all(
            by_provider[p]["reusable_source_once"]["rate"] >= 0.80 for p in PROVIDERS
        ),
        "hydration_successful_reusable_ge_80": hydration_usage["rate"] >= 0.80,
        "f6_refresh_each_provider_ge_80": all(
            by_provider[p]["f6_legitimate_refresh"]["rate"] >= 0.80 for p in PROVIDERS
        ),
        "paired_e1_reexec_lower_than_b0": e1_reexec["rate"] < b0_reexec["rate"],
    }
    status = "PASS" if all(gates.values()) else "FAIL"
    return {
        "schema": "evidence-r2-score-v1",
        "status": status,
        "run_count": len(rows),
        "infra_failures": len(infra),
        "safety": safety,
        "metrics": {
            "reusable_exact_overall": exact_overall,
            "reusable_source_once_overall": source_once_overall,
            "hydration_usage_among_successful_reusable": hydration_usage,
            "f6_legitimate_refresh_overall": freshness_overall,
            "b0_reexecution_rate_reusable": b0_reexec,
            "e1_reexecution_rate_reusable": e1_reexec,
            "paired_reexecution_rate_delta_b0_minus_e1": {
                "delta": delta,
                "conservative_wilson95": delta_ci,
            },
        },
        "by_provider": by_provider,
        "gates": gates,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(DEFAULT_INPUT))
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = ap.parse_args()
    payload = json.loads(Path(args.input).read_text())
    report = score_runs(payload)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

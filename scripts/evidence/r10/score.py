from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "data/audit/evidence_r10/runs_real_v1.json"
DEFAULT_OUTPUT = ROOT / "data/audit/evidence_r10/score_real_v1.json"
PROVIDERS = ("minimax", "deepseek")


def _metric(rows: list[dict[str, Any]], pred) -> dict[str, Any]:
    passed = sum(1 for row in rows if pred(row))
    return {"pass": passed, "total": len(rows), "rate": 0.0 if not rows else passed / len(rows)}


def score_runs(payload: dict[str, Any]) -> dict[str, Any]:
    rows = list(payload.get("runs", []))
    groups = {
        seed: [r for r in rows if r.get("seed_id") == seed] for seed in ("T1", "T2", "T3", "T4")
    }
    covered = groups["T1"] + groups["T2"]
    infra = [r for r in rows if r.get("status") != "COMPLETED"]
    exact = _metric(rows, lambda r: bool(r.get("final_answer_exact")))
    by_provider = {
        p: _metric(
            [r for r in rows if r.get("provider") == p], lambda r: bool(r.get("final_answer_exact"))
        )
        for p in PROVIDERS
    }
    covered_by_provider = {
        p: _metric(
            [r for r in covered if r.get("provider") == p],
            lambda r: bool(r.get("final_answer_exact")),
        )
        for p in PROVIDERS
    }
    t3_by_provider = {
        p: _metric(
            [r for r in groups["T3"] if r.get("provider") == p],
            lambda r: bool(r.get("final_answer_exact")),
        )
        for p in PROVIDERS
    }
    t4_by_provider = {
        p: _metric(
            [r for r in groups["T4"] if r.get("provider") == p],
            lambda r: bool(r.get("final_answer_exact")),
        )
        for p in PROVIDERS
    }
    exact_covered = [r for r in covered if r.get("final_answer_exact")]
    exact_t3 = [r for r in groups["T3"] if r.get("final_answer_exact")]
    exact_t4 = [r for r in groups["T4"] if r.get("final_answer_exact")]
    gates = {
        "infra_complete": len(rows) == 24 and not infra,
        "transport_ref_zero": sum(bool(r.get("transport_ref_as_domain_answer")) for r in rows) == 0,
        "stale_as_current_zero": sum(bool(r.get("stale_as_current")) for r in groups["T3"]) == 0,
        "physical_exact_repeat_zero": sum(
            int(r.get("physical_exact_source_args_repeat_count") or 0) for r in rows
        )
        == 0,
        "physical_redundant_overlap_zero": sum(
            int(r.get("physical_redundant_overlap_count") or 0) for r in rows
        )
        == 0,
        "overall_exact_ge_22_24": exact["pass"] >= 22,
        "each_provider_exact_ge_10_12": all(by_provider[p]["pass"] >= 10 for p in PROVIDERS),
        "covered_exact_ge_11_12": sum(bool(r.get("final_answer_exact")) for r in covered) >= 11,
        "covered_each_provider_ge_5_6": all(covered_by_provider[p]["pass"] >= 5 for p in PROVIDERS),
        "t3_exact_ge_5_6": sum(bool(r.get("final_answer_exact")) for r in groups["T3"]) >= 5,
        "t3_each_provider_ge_2_3": all(t3_by_provider[p]["pass"] >= 2 for p in PROVIDERS),
        "t4_exact_ge_5_6": sum(bool(r.get("final_answer_exact")) for r in groups["T4"]) >= 5,
        "t4_each_provider_ge_2_3": all(t4_by_provider[p]["pass"] >= 2 for p in PROVIDERS),
        "covered_exact_physical_once": all(
            int(r.get("physical_source_execution_count") or 0) == 1
            and int(r.get("recovery_answer_hit_count") or 0) >= 1
            for r in exact_covered
        ),
        "t3_exact_physical_once": all(
            int(r.get("physical_source_execution_count") or 0) == 1
            and int(r.get("recovery_answer_hit_count") or 0) >= 1
            for r in exact_t3
        ),
        "t4_exact_physical_once_gap": all(
            int(r.get("physical_source_execution_count") or 0) == 1
            and int(r.get("physical_redundant_overlap_count") or 0) == 0
            and int(r.get("recovery_answer_hit_count") or 0) >= 1
            for r in exact_t4
        ),
        "source_results_accounted": all(
            int(r.get("model_source_attempt_count") or 0)
            == int(r.get("physical_source_execution_count") or 0)
            + int(r.get("evidence_reuse_count") or 0)
            for r in rows
        ),
    }
    return {
        "schema": "evidence-r10-score-v1",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "run_count": len(rows),
        "infra_failures": len(infra),
        "metrics": {
            "overall_exact": exact,
            "by_provider": by_provider,
            "covered_exact": _metric(covered, lambda r: bool(r.get("final_answer_exact"))),
            "t3_exact": _metric(groups["T3"], lambda r: bool(r.get("final_answer_exact"))),
            "t4_exact": _metric(groups["T4"], lambda r: bool(r.get("final_answer_exact"))),
            "declared_read_file_count": sum(
                int(r.get("model_source_attempt_count") or 0) for r in rows
            ),
            "physical_source_execution_count": sum(
                int(r.get("physical_source_execution_count") or 0) for r in rows
            ),
            "evidence_reuse_count": sum(int(r.get("evidence_reuse_count") or 0) for r in rows),
            "physical_exact_repeat_count": sum(
                int(r.get("physical_exact_source_args_repeat_count") or 0) for r in rows
            ),
            "physical_redundant_overlap_count": sum(
                int(r.get("physical_redundant_overlap_count") or 0) for r in rows
            ),
        },
        "gates": gates,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(DEFAULT_INPUT))
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = ap.parse_args()
    report = score_runs(json.loads(Path(args.input).read_text(encoding="utf-8")))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

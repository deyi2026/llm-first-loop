from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "data/audit/evidence_r8/runs_real_v1.json"
DEFAULT_OUTPUT = ROOT / "data/audit/evidence_r8/score_real_v1.json"
PROVIDERS = ("minimax", "deepseek")


def _rate(rows: list[dict[str, Any]], pred) -> dict[str, Any]:
    passed = sum(1 for row in rows if pred(row))
    return {"pass": passed, "total": len(rows), "rate": 0.0 if not rows else passed / len(rows)}


def score_runs(payload: dict[str, Any]) -> dict[str, Any]:
    rows = list(payload.get("runs", []))
    infra = [r for r in rows if r.get("status") != "COMPLETED"]
    exact = _rate(rows, lambda r: bool(r.get("final_answer_exact")))
    by_provider = {
        p: _rate(
            [r for r in rows if r.get("provider") == p], lambda r: bool(r.get("final_answer_exact"))
        )
        for p in PROVIDERS
    }
    groups = {
        seed: [r for r in rows if r.get("seed_id") == seed] for seed in ("P1", "P2", "P3", "P4")
    }
    covered = groups["P1"] + groups["P2"]
    covered_by_provider = {
        p: _rate(
            [r for r in covered if r.get("provider") == p],
            lambda r: bool(r.get("final_answer_exact")),
        )
        for p in PROVIDERS
    }
    q3_by_provider = {
        p: _rate(
            [r for r in groups["P3"] if r.get("provider") == p],
            lambda r: bool(r.get("final_answer_exact")),
        )
        for p in PROVIDERS
    }
    q4_by_provider = {
        p: _rate(
            [r for r in groups["P4"] if r.get("provider") == p],
            lambda r: bool(r.get("final_answer_exact")),
        )
        for p in PROVIDERS
    }

    exact_rows = [r for r in rows if r.get("final_answer_exact")]
    covered_exact = [r for r in covered if r.get("final_answer_exact")]
    q3_exact = [r for r in groups["P3"] if r.get("final_answer_exact")]
    q4_exact = [r for r in groups["P4"] if r.get("final_answer_exact")]

    gates = {
        "infra_complete": len(rows) == 24 and not infra,
        "transport_ref_zero": sum(bool(r.get("transport_ref_as_domain_answer")) for r in rows) == 0,
        "exact_source_args_repeat_zero": sum(
            int(r.get("exact_source_args_repeat_count") or 0) for r in rows
        )
        == 0,
        "redundant_overlap_zero": sum(int(r.get("redundant_overlap_count") or 0) for r in rows)
        == 0,
        "q3_stale_as_current_zero": sum(bool(r.get("stale_as_current")) for r in groups["P3"]) == 0,
        "overall_exact_ge_22_24": exact["pass"] >= 22,
        "each_provider_exact_ge_10_12": all(by_provider[p]["pass"] >= 10 for p in PROVIDERS),
        "covered_exact_ge_11_12": sum(bool(r.get("final_answer_exact")) for r in covered) >= 11,
        "covered_each_provider_ge_5_6": all(covered_by_provider[p]["pass"] >= 5 for p in PROVIDERS),
        "q3_exact_ge_5_6": sum(bool(r.get("final_answer_exact")) for r in groups["P3"]) >= 5,
        "q3_each_provider_ge_2_3": all(q3_by_provider[p]["pass"] >= 2 for p in PROVIDERS),
        "q4_exact_ge_5_6": sum(bool(r.get("final_answer_exact")) for r in groups["P4"]) >= 5,
        "q4_each_provider_ge_2_3": all(q4_by_provider[p]["pass"] >= 2 for p in PROVIDERS),
        "covered_exact_path": all(
            int(r.get("model_source_execution_count") or 0) == 1
            and int(r.get("recovery_answer_hit_count") or 0) >= 1
            for r in covered_exact
        ),
        "q3_exact_path": all(
            int(r.get("model_source_execution_count") or 0) == 1
            and int(r.get("stale_block_count") or 0) >= 1
            and int(r.get("recovery_answer_hit_count") or 0) >= 1
            for r in q3_exact
        ),
        "q4_exact_path": all(
            int(r.get("model_source_execution_count") or 0) >= 1
            and int(r.get("redundant_overlap_count") or 0) == 0
            and int(r.get("recovery_answer_hit_count") or 0) >= 1
            for r in q4_exact
        ),
    }
    return {
        "schema": "evidence-r8-score-v1",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "run_count": len(rows),
        "infra_failures": len(infra),
        "metrics": {
            "overall_exact": exact,
            "by_provider": by_provider,
            "covered_exact": _rate(covered, lambda r: bool(r.get("final_answer_exact"))),
            "q3_exact": _rate(groups["P3"], lambda r: bool(r.get("final_answer_exact"))),
            "q4_exact": _rate(groups["P4"], lambda r: bool(r.get("final_answer_exact"))),
            "exact_rows": len(exact_rows),
            "exact_repeat_count": sum(
                int(r.get("exact_source_args_repeat_count") or 0) for r in rows
            ),
            "redundant_overlap_count": sum(
                int(r.get("redundant_overlap_count") or 0) for r in rows
            ),
        },
        "gates": gates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    report = score_runs(json.loads(Path(args.input).read_text(encoding="utf-8")))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

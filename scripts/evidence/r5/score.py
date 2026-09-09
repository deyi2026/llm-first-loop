from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "data/audit/evidence_r5/runs_real_v1.json"
DEFAULT_OUTPUT = ROOT / "data/audit/evidence_r5/score_real_v1.json"
PROVIDERS = ("minimax", "deepseek")
CURRENT_SEEDS = {"J1", "J3"}


def _count(rows: list[dict[str, Any]], predicate) -> int:
    return sum(1 for row in rows if predicate(row))


def score_runs(payload: dict[str, Any]) -> dict[str, Any]:
    rows = list(payload.get("runs", []))
    completed = [r for r in rows if r.get("status") == "COMPLETED"]
    by_seed = {
        seed: [r for r in completed if r.get("seed_id") == seed]
        for seed in ("J1", "J2", "J3", "J4")
    }
    by_provider = {
        provider: [r for r in completed if r.get("provider") == provider] for provider in PROVIDERS
    }
    current = [r for r in completed if r.get("seed_id") in CURRENT_SEEDS]
    historical = by_seed["J2"]
    unknown = by_seed["J4"]

    gates = {
        "infra_24_complete": len(rows) == 24 and len(completed) == 24,
        "zero_transport_ref_as_domain": all(
            not bool(r.get("transport_ref_as_domain_answer")) for r in completed
        ),
        "zero_exact_source_args_repeats": all(
            int(r.get("exact_source_args_repeat_count") or 0) == 0 for r in completed
        ),
        "zero_redundant_overlap": all(
            int(r.get("redundant_overlap_count") or 0) == 0 for r in completed
        ),
        "current_zero_stale_as_current": len(current) == 12
        and all(not bool(r.get("stale_as_current")) for r in current),
        "current_exact_ge_11_of_12": _count(current, lambda r: bool(r.get("final_answer_exact")))
        >= 11,
        "current_each_provider_ge_5_of_6": all(
            _count(
                [r for r in current if r.get("provider") == provider],
                lambda r: bool(r.get("final_answer_exact")),
            )
            >= 5
            for provider in PROVIDERS
        ),
        "current_exact_rows_refresh_source": all(
            (not r.get("final_answer_exact"))
            or int(r.get("model_source_execution_count") or 0) >= 1
            for r in current
        ),
        "historical_exact_ge_5_of_6": _count(
            historical, lambda r: bool(r.get("final_answer_exact"))
        )
        >= 5,
        "historical_each_provider_ge_2_of_3": all(
            _count(
                [r for r in historical if r.get("provider") == provider],
                lambda r: bool(r.get("final_answer_exact")),
            )
            >= 2
            for provider in PROVIDERS
        ),
        "historical_exact_rows_explicit_stale_access": all(
            (not r.get("final_answer_exact"))
            or int(r.get("historical_access_success_count") or 0) >= 1
            for r in historical
        ),
        "historical_exact_rows_no_current_source": all(
            (not r.get("final_answer_exact"))
            or int(r.get("model_source_execution_count") or 0) == 0
            for r in historical
        ),
        "unknown_exact_ge_5_of_6": _count(unknown, lambda r: bool(r.get("final_answer_exact")))
        >= 5,
        "unknown_each_provider_ge_2_of_3": all(
            _count(
                [r for r in unknown if r.get("provider") == provider],
                lambda r: bool(r.get("final_answer_exact")),
            )
            >= 2
            for provider in PROVIDERS
        ),
        "unknown_exact_rows_recover_without_source_rerun": all(
            (not r.get("final_answer_exact"))
            or (
                int(r.get("recovery_success_count") or 0) >= 1
                and int(r.get("model_source_execution_count") or 0) == 0
            )
            for r in unknown
        ),
        "unknown_zero_stale_block": len(unknown) == 6
        and all(int(r.get("stale_block_count") or 0) == 0 for r in unknown),
        "overall_exact_ge_21_of_24": _count(completed, lambda r: bool(r.get("final_answer_exact")))
        >= 21,
        "overall_each_provider_ge_10_of_12": all(
            _count(by_provider[provider], lambda r: bool(r.get("final_answer_exact"))) >= 10
            for provider in PROVIDERS
        ),
    }
    return {
        "schema": "evidence-r5-score-v1",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "run_count": len(rows),
        "completed_count": len(completed),
        "metrics": {
            "overall_exact": _count(completed, lambda r: bool(r.get("final_answer_exact"))),
            "provider_exact": {
                provider: _count(by_provider[provider], lambda r: bool(r.get("final_answer_exact")))
                for provider in PROVIDERS
            },
            "current_exact": _count(current, lambda r: bool(r.get("final_answer_exact"))),
            "current_stale_as_current": _count(current, lambda r: bool(r.get("stale_as_current"))),
            "historical_exact": _count(historical, lambda r: bool(r.get("final_answer_exact"))),
            "historical_explicit_access": _count(
                historical, lambda r: int(r.get("historical_access_success_count") or 0) >= 1
            ),
            "unknown_exact": _count(unknown, lambda r: bool(r.get("final_answer_exact"))),
            "exact_source_args_repeats": sum(
                int(r.get("exact_source_args_repeat_count") or 0) for r in completed
            ),
            "redundant_overlaps": sum(
                int(r.get("redundant_overlap_count") or 0) for r in completed
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
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

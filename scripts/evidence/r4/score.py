from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "data/audit/evidence_r4/runs_real_v1.json"
DEFAULT_OUTPUT = ROOT / "data/audit/evidence_r4/score_real_v1.json"
PROVIDERS = ("minimax", "deepseek")


def _metric(rows: list[dict[str, Any]], predicate) -> dict[str, Any]:
    passed = sum(1 for row in rows if predicate(row))
    total = len(rows)
    return {"pass": passed, "total": total, "rate": passed / total if total else 0.0}


def score_runs(payload: dict[str, Any]) -> dict[str, Any]:
    rows = list(payload.get("runs", []))
    completed = [r for r in rows if r.get("status") == "COMPLETED"]
    by_seed = {
        seed: [r for r in completed if r.get("seed_id") == seed]
        for seed in ("K1", "K2", "K3", "K4", "K5", "K6")
    }
    by_provider = {
        provider: [r for r in completed if r.get("provider") == provider] for provider in PROVIDERS
    }

    overall_exact = _metric(completed, lambda r: bool(r.get("final_answer_exact")))
    provider_exact = {
        provider: _metric(by_provider[provider], lambda r: bool(r.get("final_answer_exact")))
        for provider in PROVIDERS
    }
    source_once_rows = [r for seed in ("K1", "K2", "K3", "K5", "K6") for r in by_seed[seed]]
    source_once = _metric(
        source_once_rows, lambda r: int(r.get("source_execution_count") or 0) == 1
    )
    k1_exact = {
        provider: _metric(
            [r for r in by_seed["K1"] if r.get("provider") == provider],
            lambda r: bool(r.get("final_answer_exact")),
        )
        for provider in PROVIDERS
    }
    k2_exact = {
        provider: _metric(
            [r for r in by_seed["K2"] if r.get("provider") == provider],
            lambda r: bool(r.get("final_answer_exact")),
        )
        for provider in PROVIDERS
    }
    k4 = by_seed["K4"]
    k5 = by_seed["K5"]
    k6 = by_seed["K6"]

    gates = {
        "infra_36_complete": len(rows) == 36 and len(completed) == 36,
        "overall_exact_ge_90": overall_exact["pass"] >= 33,
        "provider_exact_each_ge_15_of_18": all(provider_exact[p]["pass"] >= 15 for p in PROVIDERS),
        "zero_transport_ref_as_domain_answer": all(
            not bool(r.get("transport_ref_as_domain_answer")) for r in completed
        ),
        "source_once_k1_k2_k3_k5_k6_all": len(source_once_rows) == 30 and source_once["pass"] == 30,
        "k1_read_recovery_and_exact_each_provider_ge_2_of_3": all(
            k1_exact[p]["pass"] >= 2
            and all(
                (not r.get("final_answer_exact"))
                or int(r.get("read_evidence_success_count") or 0) >= 1
                for r in by_seed["K1"]
                if r.get("provider") == p
            )
            for p in PROVIDERS
        ),
        "k2_exact_each_provider_ge_2_of_3": all(k2_exact[p]["pass"] >= 2 for p in PROVIDERS),
        "k2_search_used_ge_4_of_6": sum(
            int(r.get("search_evidence_success_count") or 0) >= 1 for r in by_seed["K2"]
        )
        >= 4,
        "k6_exact_ge_5_of_6": sum(bool(r.get("final_answer_exact")) for r in k6) >= 5,
        "k6_recovery_used_and_not_stale_blocked": all(
            int(r.get("recovery_success_count") or 0) >= 1
            and int(r.get("stale_block_count") or 0) == 0
            for r in k6
        ),
        "k3_zero_side_effect_duplicate": all(
            int(r.get("side_effect_duplicate_count") or 0) == 0 for r in by_seed["K3"]
        ),
        "k3_exact_ge_5_of_6": sum(bool(r.get("final_answer_exact")) for r in by_seed["K3"]) >= 5,
        "k4_zero_stale_as_current": all(not bool(r.get("stale_as_current")) for r in k4),
        "k4_current_exact_6_of_6": len(k4) == 6
        and all(bool(r.get("final_answer_exact")) for r in k4),
        "k4_exactly_two_source_acquisitions": len(k4) == 6
        and all(int(r.get("source_execution_count") or 0) == 2 for r in k4),
        "k5_source_once_all": len(k5) == 6
        and all(int(r.get("source_execution_count") or 0) == 1 for r in k5),
        "k5_historical_exact_ge_5_of_6": sum(bool(r.get("final_answer_exact")) for r in k5) >= 5,
        "k5_exact_runs_use_explicit_historical_access": all(
            (not r.get("final_answer_exact"))
            or int(r.get("historical_access_success_count") or 0) >= 1
            for r in k5
        ),
    }
    return {
        "schema": "evidence-r4-score-v1",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "run_count": len(rows),
        "completed_count": len(completed),
        "metrics": {
            "overall_exact": overall_exact,
            "provider_exact": provider_exact,
            "source_once_non_refresh_seeds": source_once,
            "k1_exact_by_provider": k1_exact,
            "k2_exact_by_provider": k2_exact,
            "k2_search_used": sum(
                int(r.get("search_evidence_success_count") or 0) >= 1 for r in by_seed["K2"]
            ),
            "k3_exact": sum(bool(r.get("final_answer_exact")) for r in by_seed["K3"]),
            "k3_side_effect_duplicates": sum(
                int(r.get("side_effect_duplicate_count") or 0) for r in by_seed["K3"]
            ),
            "k4_exact": sum(bool(r.get("final_answer_exact")) for r in k4),
            "k4_stale_as_current": sum(bool(r.get("stale_as_current")) for r in k4),
            "k5_exact": sum(bool(r.get("final_answer_exact")) for r in k5),
            "k5_historical_access": sum(
                int(r.get("historical_access_success_count") or 0) >= 1 for r in k5
            ),
            "k6_exact": sum(bool(r.get("final_answer_exact")) for r in k6),
        },
        "gates": gates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    report = score_runs(payload)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from pathlib import Path

from scripts.evidence.r10.fixtures import FIXTURES
from scripts.evidence.r10.runner import execute_run
from scripts.evidence.r10.score import score_runs

ROOT = Path(__file__).parents[2]


def test_r10_fixtures_are_fresh_and_matrix_is_24() -> None:
    assert set(FIXTURES) == {"T1", "T2", "T3", "T4"}
    text = "\n".join(f.initial_content + f.current_content for f in FIXTURES.values())
    for old in ("CORAL-286", "SLATE-731", "AZURE-683", "BRONZE-957", "AMBER-612", "ONYX-913"):
        assert old not in text
    matrix = json.loads((ROOT / "tests/fixtures/evidence_r10/matrix_v1.json").read_text())["runs"]
    assert len(matrix) == 24


def test_r10_dry_matrix_and_scorer_pass() -> None:
    rows = json.loads((ROOT / "tests/fixtures/evidence_r10/matrix_v1.json").read_text())["runs"]
    results = [execute_run(row, dry=True) for row in rows]
    assert all(r["status"] == "COMPLETED" and r["final_answer_exact"] for r in results)
    assert all(r["physical_source_execution_count"] == 1 for r in results)
    assert all(r["physical_redundant_overlap_count"] == 0 for r in results)
    assert all(
        r["model_source_attempt_count"]
        == r["physical_source_execution_count"] + r["evidence_reuse_count"]
        for r in results
    )
    report = score_runs({"runs": results})
    assert report["status"] == "PASS", report


def test_r10_scorer_allows_provider_declared_fallback_when_it_is_evidence_reuse() -> None:
    rows = []
    for provider in ("minimax", "deepseek"):
        for seed in ("T1", "T2", "T3", "T4"):
            for _rep in range(3):
                rows.append(
                    {
                        "provider": provider,
                        "seed_id": seed,
                        "status": "COMPLETED",
                        "final_answer_exact": True,
                        "transport_ref_as_domain_answer": False,
                        "stale_as_current": False,
                        "model_source_attempt_count": 2 if seed == "T1" else 1,
                        "physical_source_execution_count": 1,
                        "evidence_reuse_count": 1 if seed == "T1" else 0,
                        "physical_exact_source_args_repeat_count": 0,
                        "physical_redundant_overlap_count": 0,
                        "recovery_answer_hit_count": 1,
                    }
                )
    report = score_runs({"runs": rows})
    assert report["status"] == "PASS", report
    assert (
        report["metrics"]["declared_read_file_count"]
        > report["metrics"]["physical_source_execution_count"]
    )
    assert report["metrics"]["evidence_reuse_count"] == 6

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.source_recovery_contract import SHARED_SOURCE_RECOVERY_CONTRACT
from scripts.evidence.r7v2.fixtures import FIXTURES
from scripts.evidence.r7v2.runner import RunState, _overlap, execute_run
from scripts.evidence.r7v2.score import score_runs

ROOT = Path(__file__).parents[2]


def test_r7v2_fixtures_are_fresh_and_unambiguous() -> None:
    assert set(FIXTURES) == {"Q1", "Q2", "Q3", "Q4"}
    text = "\n".join(f.initial_content + f.current_content for f in FIXTURES.values())
    for prior in ("AMBER-612", "IVORY-374", "MINT-105", "PLUM-842", "ONYX-913",
                  "SILVER-208", "CEDAR-741", "NORTH-624", "TEAL-908"):
        assert prior not in text
    assert FIXTURES["Q4"].preacquire_offset == 0
    assert FIXTURES["Q4"].preacquire_limit == 60


def test_r7v2_uses_actual_r6_read_file_contract() -> None:
    assert SHARED_SOURCE_RECOVERY_CONTRACT in ReadFileTool.description
    assert "未覆盖" in ReadFileTool.description
    assert "offset/limit" in ReadFileTool.description


def test_overlap_metric_distinguishes_gap_from_reacquisition() -> None:
    assert not _overlap((100, 160), (0, 60))
    assert _overlap((50, 110), (0, 60))
    assert _overlap((0, None), (0, 60))
    state = RunState(current_intervals=[(0, 60)], preacquire_interval_seeded=True)
    assert state.preacquire_interval_seeded is True


def test_r7v2_dry_matrix_and_current_scorer_contract() -> None:
    rows = json.loads((ROOT / "tests/fixtures/evidence_r7v2/matrix_v1.json").read_text())["runs"]
    results = [execute_run(row, dry=True) for row in rows]
    assert len(results) == 24
    assert all(r["status"] == "COMPLETED" and r["final_answer_exact"] for r in results)
    report = score_runs({"runs": results})
    assert report["status"] == "PASS", report
    assert report["metrics"]["exact_repeat_count"] == 0
    assert report["metrics"]["redundant_overlap_count"] == 0


def test_q4_dry_proves_legitimate_nonoverlap_source_gap() -> None:
    row = {"run_id": "R7V2-DRY-Q4", "provider": "minimax", "seed_id": "Q4", "rep": 1}
    result = execute_run(row, dry=True)
    assert result["final_answer_exact"] is True
    assert result["preacquire_interval_seeded"] is True
    assert result["model_source_execution_count"] == 1
    assert result["redundant_overlap_count"] == 0
    source = [t for t in result["trace"] if t["tool"] == "read_file"]
    assert source[0]["arguments"]["offset"] == 100
    assert source[0]["arguments"]["limit"] == 60


def test_q3_dry_allows_manifest_direct_refresh_without_stale_hydration() -> None:
    row = {"run_id": "R7V2-DRY-Q3", "provider": "minimax", "seed_id": "Q3", "rep": 1}
    result = execute_run(row, dry=True)
    assert result["final_answer_exact"] is True
    assert result["stale_as_current"] is False
    assert result["model_source_execution_count"] == 1
    assert result["recovery_answer_hit_count"] >= 1
    # Correct v2 path: consume stale/currentness from manifest and refresh immediately.
    assert result["trace"][0]["tool"] == "read_file"
    assert result["trace"][0]["status"] == "success"

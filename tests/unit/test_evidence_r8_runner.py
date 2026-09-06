from __future__ import annotations

import json
from pathlib import Path

from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.source_recovery_contract import SHARED_SOURCE_RECOVERY_CONTRACT
from scripts.evidence.r8.fixtures import FIXTURES
from scripts.evidence.r8.runner import RunState, _overlap, execute_run
from scripts.evidence.r8.score import score_runs

ROOT = Path(__file__).parents[2]


def test_r8_fixtures_are_fresh_and_unambiguous() -> None:
    assert set(FIXTURES) == {"P1", "P2", "P3", "P4"}
    text = "\n".join(f.initial_content + f.current_content for f in FIXTURES.values())
    for prior in (
        "AMBER-612",
        "IVORY-374",
        "PLUM-842",
        "ONYX-913",
        "SILVER-208",
        "CEDAR-741",
        "TEAL-908",
    ):
        assert prior not in text
    assert FIXTURES["P4"].preacquire_offset == 0
    assert FIXTURES["P4"].preacquire_limit == 64


def test_r8_uses_actual_r6_read_file_contract() -> None:
    assert SHARED_SOURCE_RECOVERY_CONTRACT in ReadFileTool.description
    assert "未覆盖" in ReadFileTool.description
    assert "offset/limit" in ReadFileTool.description


def test_overlap_metric_distinguishes_gap_from_reacquisition() -> None:
    assert not _overlap((104, 164), (0, 64))
    assert _overlap((50, 110), (0, 64))
    assert _overlap((0, None), (0, 64))
    state = RunState(current_intervals=[(0, 64)], preacquire_interval_seeded=True)
    assert state.preacquire_interval_seeded is True


def test_r8_dry_matrix_and_current_scorer_contract() -> None:
    rows = json.loads((ROOT / "tests/fixtures/evidence_r8/matrix_v1.json").read_text())["runs"]
    results = [execute_run(row, dry=True) for row in rows]
    assert len(results) == 24
    assert all(r["status"] == "COMPLETED" and r["final_answer_exact"] for r in results)
    report = score_runs({"runs": results})
    assert report["status"] == "PASS", report
    assert report["metrics"]["exact_repeat_count"] == 0
    assert report["metrics"]["redundant_overlap_count"] == 0


def test_q4_dry_proves_legitimate_nonoverlap_source_gap() -> None:
    row = {"run_id": "R8-DRY-P4", "provider": "minimax", "seed_id": "P4", "rep": 1}
    result = execute_run(row, dry=True)
    assert result["final_answer_exact"] is True
    assert result["preacquire_interval_seeded"] is True
    assert result["model_source_execution_count"] == 1
    assert result["redundant_overlap_count"] == 0
    source = [t for t in result["trace"] if t["tool"] == "read_file"]
    assert source[0]["arguments"]["offset"] == 104
    assert source[0]["arguments"]["limit"] == 60

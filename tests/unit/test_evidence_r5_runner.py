from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.evidence.r4.runner import runner_lock
from scripts.evidence.r5 import runner
from scripts.evidence.r5.score import score_runs

ROOT = Path(__file__).parents[2]


def test_r5_matrix_balanced_24() -> None:
    rows = json.loads((ROOT / "tests/fixtures/evidence_r5/matrix_v1.json").read_text())["runs"]
    assert len(rows) == 24
    assert len({r["run_id"] for r in rows}) == 24
    for provider in ("minimax", "deepseek"):
        assert sum(r["provider"] == provider for r in rows) == 12
        for seed in ("J1", "J2", "J3", "J4"):
            assert sum(r["provider"] == provider and r["seed_id"] == seed for r in rows) == 3


def test_r5_neutral_fillers_and_explicit_fields() -> None:
    fixtures = json.loads((ROOT / "tests/fixtures/evidence_r5/fixtures_v1.json").read_text())["fixtures"]
    for _seed, f in fixtures.items():
        for line in f["initial_content"].splitlines():
            if f["target_field"] not in line:
                words = {word.strip(".,:;_-").lower() for word in line.split()}
                assert "old" not in words
                assert "new" not in words
                assert "first" not in words
                assert "current" not in words
        assert f["target_field"] in f["task"]


def test_r5_interval_repeat_metric_allows_partition_but_rejects_overlap() -> None:
    state = runner.RunState()
    fixture = runner.FIXTURES["J1"]
    calls = [
        runner.ToolCall(id="a", name="read_file", arguments={"path": "/x", "offset": 0, "limit": 80}),
        runner.ToolCall(id="b", name="read_file", arguments={"path": "/x", "offset": 80, "limit": 80}),
        runner.ToolCall(id="c", name="read_file", arguments={"path": "/x", "offset": 40, "limit": 20}),
    ]
    runner._record_source_success(state, calls[0], fixture)
    runner._record_source_success(state, calls[1], fixture)
    assert state.redundant_overlap_count == 0
    runner._record_source_success(state, calls[2], fixture)
    assert state.redundant_overlap_count == 1
    runner._record_source_success(state, calls[2], fixture)
    assert state.exact_source_args_repeat_count == 1


def test_r5_dry_matrix_passes_frozen_score(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(runner, "RUNTIME_DIR", tmp_path / "runtime")
    rows = runner._load_matrix()
    results, rc = runner.run_rows(rows, dry=True)
    assert rc == 0
    report = score_runs({"schema": "evidence-r5-runs-v1", "runs": results})
    assert report["status"] == "PASS", report
    current = [r for r in results if r["seed_id"] in {"J1", "J3"}]
    assert all(r["stale_block_count"] >= 1 for r in current)
    assert all(r["model_source_execution_count"] == 1 for r in current)
    historical = [r for r in results if r["seed_id"] == "J2"]
    assert all(r["historical_access_success_count"] >= 1 for r in historical)
    assert all(r["model_source_execution_count"] == 0 for r in historical)
    unknown = [r for r in results if r["seed_id"] == "J4"]
    assert all(r["model_source_execution_count"] == 0 for r in unknown)


def test_r5_lock_rejects_second_process(tmp_path) -> None:
    lock = tmp_path / "r5.lock"
    code = (
        "from pathlib import Path; "
        "from scripts.evidence.r4.runner import runner_lock, RunnerLockError; "
        f"p=Path({str(lock)!r}); "
        "\ntry:\n"
        "  with runner_lock(p): pass\n"
        "except RunnerLockError:\n"
        "  raise SystemExit(73)\n"
        "raise SystemExit(0)\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = "src:."
    with runner_lock(lock):
        proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, check=False)
    assert proc.returncode == 73


def test_r5_unresolved_started_blocks_resume(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "REAL_ROWS_DIR", tmp_path)
    row = {"run_id": "R5-001", "provider": "minimax", "seed_id": "J1", "rep": 1}
    (tmp_path / "R5-001.started.json").write_text("{}")
    try:
        runner._ensure_no_unresolved_started([row])
    except RuntimeError as exc:
        assert "automatic replay forbidden" in str(exc)
    else:
        raise AssertionError("unresolved row must block resume")

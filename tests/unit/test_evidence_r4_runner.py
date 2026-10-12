from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.evidence.r4 import runner
from scripts.evidence.r4.score import score_runs

ROOT = Path(__file__).parents[2]


def test_r4_matrix_is_balanced_fresh_36() -> None:
    payload = json.loads((ROOT / "tests/fixtures/evidence_r4/matrix_v1.json").read_text())
    rows = payload["runs"]
    assert len(rows) == 36
    assert len({r["run_id"] for r in rows}) == 36
    for provider in ("minimax", "deepseek"):
        assert sum(r["provider"] == provider for r in rows) == 18
        for seed in ("K1", "K2", "K3", "K4", "K5", "K6"):
            assert sum(r["provider"] == provider and r["seed_id"] == seed for r in rows) == 3


def test_r4_answers_are_fresh_not_r2_tokens() -> None:
    fixtures = json.loads((ROOT / "tests/fixtures/evidence_r4/fixtures_v1.json").read_text())["fixtures"]
    r2_text = (ROOT / "tests/fixtures/evidence_r2/fixtures_v1.json").read_text()
    for fixture in fixtures.values():
        assert fixture["answer"] not in r2_text


def test_r4_dry_matrix_uses_production_contract_and_scores_pass(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(runner, "RUNTIME_DIR", tmp_path / "runtime")
    rows = runner._load_matrix()
    results, rc = runner.run_rows(rows, dry=True)
    assert rc == 0
    assert len(results) == 36
    report = score_runs({"schema": "evidence-r4-runs-v1", "runs": results})
    assert report["status"] == "PASS", report
    k1 = [r for r in results if r["seed_id"] == "K1"]
    assert all(r["read_evidence_success_count"] >= 1 for r in k1)
    k4 = [r for r in results if r["seed_id"] == "K4"]
    assert all(r["source_execution_count"] == 2 for r in k4)
    assert all(r["stale_block_count"] >= 1 for r in k4)
    k5 = [r for r in results if r["seed_id"] == "K5"]
    assert all(r["historical_access_success_count"] >= 1 for r in k5)
    assert all(r["source_execution_count"] == 1 for r in k5)


def test_r4_runner_lock_rejects_second_process(tmp_path) -> None:
    lock = tmp_path / "r4.lock"
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
    with runner.runner_lock(lock):
        proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, check=False)
    assert proc.returncode == 73


def test_r4_unresolved_started_row_blocks_resume(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "REAL_ROWS_DIR", tmp_path)
    row = {"run_id": "R4-001", "provider": "minimax", "seed_id": "K1", "rep": 1}
    (tmp_path / "R4-001.started.json").write_text("{}")
    try:
        runner._ensure_no_unresolved_started([row])
    except RuntimeError as exc:
        assert "automatic replay is forbidden" in str(exc)
    else:
        raise AssertionError("unresolved started row must block automatic resume")


def test_r4_tool_schema_wire_shape_matches_production_contract() -> None:
    raw = {
        "name": "demo",
        "description": "demo tool",
        "parameters": {"type": "object", "properties": {}},
    }
    assert runner._schema_to_param(raw) == {
        "type": "function",
        "function": {
            "name": "demo",
            "description": "demo tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }

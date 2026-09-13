"""Timeout evidence must survive worker kill without weakening qualification."""

import json
import os
import subprocess
import sys
from pathlib import Path

from evals.browser_smc_semantic_execute_recovery_smoke import observations


def test_killed_worker_retains_startup_surface_and_partial_facts(tmp_path):
    script = """
import json, sys, time
from pathlib import Path
from evals.browser_smc_semantic_execute_recovery_smoke.observations import atomic_json
p=Path(sys.argv[1])
atomic_json(p/'worker-startup.json', {'surface': {'exact': True, 'sha256': 'frozen'}, 'configured_model': 'fixture'})
logs=p/'.lfldata/event_logs';logs.mkdir(parents=True)
with (logs/'fixture.jsonl').open('w') as h:
 for i in range(12):
  h.write(json.dumps({'type':'llm.partial_checkpoint','payload':{'round':8,'tool_call_draft_count':0}})+'\\n')
 h.flush()
print('READY',flush=True)
time.sleep(120)
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)], stdout=subprocess.PIPE, text=True, env=env
    )
    try:
        assert proc.stdout.readline().strip() == "READY"
        proc.kill()
        proc.wait(timeout=5)
        payload = observations.finalize_worker(tmp_path, timed_out=True)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    assert payload["status"] == "TIMEOUT"
    assert payload["surface"]["sha256"] == "frozen"
    assert payload["surface_status"] == "observed"
    assert payload["partial_checkpoint_count"] == 12
    assert payload["partial_only_loop_rounds"] == 1
    assert payload["durable_observation"]["run_end_observed"] is False
    assert json.loads((tmp_path / "worker-observation.json").read_text()) == payload


def test_missing_observations_are_unknown_not_false(tmp_path):
    payload = observations.finalize_worker(tmp_path, timed_out=True)
    assert payload["surface_status"] == "unknown"
    assert payload["surface"] is None
    assert payload["partial_checkpoint_count"] is None
    assert payload["partial_only_loop_rounds"] is None


def test_timeout_does_not_overwrite_completed_worker_source(tmp_path):
    path = tmp_path / "worker-result.json"
    path.write_text(json.dumps({"status": "RUN_OK", "surface": {"exact": True}, "rounds": 4}))
    before = path.read_bytes()
    payload = observations.finalize_worker(tmp_path, timed_out=True)
    assert path.read_bytes() == before
    assert payload["status"] == "TIMEOUT"
    assert payload["rounds"] == 4


def test_round_ceiling_is_diagnostic_only():
    assert observations.run_profile("repeat12")["max_iterations"] == 12
    diagnostic = observations.run_profile("diagnostic16")
    assert diagnostic["max_iterations"] == 16
    assert diagnostic["qualification_eligible"] is False
    assert diagnostic["worker_timeout_s"] == 240


def test_timeout_with_exact_surface_still_fails_main_gate():
    from evals.browser_smc_semantic_execute_recovery_smoke import protocol

    rows = [
        {
            "index": i,
            "task_id": "click_commit",
            "status": "TIMEOUT",
            "worker": {"surface_exact": True},
        }
        for i in range(6)
    ]
    gate = protocol.a2_gate(rows)
    assert gate["surface_exact"] is True
    assert gate["infra_valid"] is False
    assert gate["pass"] is False


def test_diagnostic_cli_never_writes_qualification_gate(tmp_path, monkeypatch):
    from evals.browser_smc_semantic_execute_recovery_smoke import run_a2

    rows = [
        {**r, "status": "PASS", "oracle": {"pass": True}, "worker": {}} for r in run_a2.build_plan()
    ]
    (tmp_path / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(run_a2, "execution_manifest", lambda *args: {"test": True})
    monkeypatch.setattr(
        sys, "argv", ["run_a2", "--workdir", str(tmp_path), "--profile", "diagnostic16"]
    )
    monkeypatch.setattr(run_a2, "PROFILE", observations.run_profile("repeat12"))
    monkeypatch.setattr(run_a2, "RUNTIME_REPO", run_a2.REPO)
    assert run_a2.main() == 0
    assert not (tmp_path / "smoke-gate.json").exists()
    assert (
        json.loads((tmp_path / "diagnostic-summary.json").read_text())["qualification_eligible"]
        is False
    )

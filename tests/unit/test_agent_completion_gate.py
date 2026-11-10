from __future__ import annotations

import sys

from llm_loop.agent_completion import (
    evaluate_agent_completion,
    parse_pytest_summary,
    run_pytest_verification,
)


def _run(**overrides):
    result = {
        "schema": "lfl.cli/v1",
        "type": "result",
        "status": "completed",
        "exit_code": 0,
        "session_id": "session-8ab7",
        "run_incomplete": False,
        "provider_output_truncated": False,
        "projection_cannot_fit": False,
        "cancel_reason": "",
        "model_used": "minimax/MiniMax-M3.1-Flash",
    }
    result.update(overrides)
    return result


def _verification(**overrides):
    result = {
        "schema": "lfl.verification/v1",
        "verifier": "lfl-agent-completion/1",
        "session_id": "session-8ab7",
        "test_command": [sys.executable, "-m", "pytest", "-q"],
        "test_exit_code": 0,
        "passed": 3,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "artifacts": [{"path": "scripts/example.py", "sha256": "a" * 64}],
    }
    result.update(overrides)
    return result


def test_acceptance_requires_completed_run_and_independent_tests():
    decision = evaluate_agent_completion(_run(), _verification())
    assert decision["accepted"] is True
    assert decision["run_ok"] is True
    assert decision["verification_ok"] is True
    assert decision["status"] == "accepted"


def test_max_iterations_is_not_accepted_even_when_tests_pass():
    decision = evaluate_agent_completion(
        _run(status="incomplete", exit_code=1, run_incomplete=True),
        _verification(),
    )
    assert decision["accepted"] is False
    assert decision["run_ok"] is False
    assert decision["verification_ok"] is True
    assert "run_incomplete" in decision["reasons"]


def test_completed_run_is_not_accepted_when_tests_fail():
    decision = evaluate_agent_completion(
        _run(), _verification(test_exit_code=1, failed=1, passed=2)
    )
    assert decision["accepted"] is False
    assert decision["run_ok"] is True
    assert decision["verification_ok"] is False
    assert "verification_failed" in decision["reasons"]


def test_verification_must_be_bound_to_same_session_and_have_artifact_hashes():
    mismatched = evaluate_agent_completion(_run(), _verification(session_id="other"))
    assert mismatched["accepted"] is False
    assert "session_id_mismatch" in mismatched["reasons"]

    no_artifacts = evaluate_agent_completion(_run(), _verification(artifacts=[]))
    assert no_artifacts["accepted"] is False
    assert "artifacts_missing" in no_artifacts["reasons"]

    bad_hash = evaluate_agent_completion(
        _run(), _verification(artifacts=[{"path": "scripts/example.py", "sha256": "bad"}])
    )
    assert bad_hash["accepted"] is False
    assert "artifact_digest_invalid" in bad_hash["reasons"]


def test_missing_independent_verification_never_defaults_to_success():
    decision = evaluate_agent_completion(_run(), None)
    assert decision["accepted"] is False
    assert decision["run_ok"] is True
    assert decision["verification_ok"] is False
    assert "verification_missing" in decision["reasons"]


def test_pytest_summary_parser_requires_real_pass_count():
    assert parse_pytest_summary("3 passed, 1 skipped in 0.2s") == {
        "passed": 3,
        "failed": 0,
        "errors": 0,
        "skipped": 1,
    }
    assert parse_pytest_summary("2 failed, 1 error in 0.1s") == {
        "passed": 0,
        "failed": 2,
        "errors": 1,
        "skipped": 0,
    }
    assert parse_pytest_summary("no tests ran") == {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
    }


def test_verification_runner_executes_pytest_and_hashes_declared_artifacts(tmp_path):
    (tmp_path / "test_example.py").write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8"
    )
    artifact = tmp_path / "test_example.py"
    result = run_pytest_verification(
        workspace=tmp_path,
        command=[sys.executable, "-m", "pytest", "-q", "test_example.py"],
        session_id="session-8ab7",
        artifact_paths=["test_example.py"],
        timeout_s=20,
    )
    assert result["schema"] == "lfl.verification/v1"
    assert result["session_id"] == "session-8ab7"
    assert result["test_exit_code"] == 0
    assert result["passed"] == 1
    assert result["failed"] == 0
    assert result["artifacts"][0]["path"] == "test_example.py"
    assert len(result["artifacts"][0]["sha256"]) == 64
    assert artifact.is_file()


def test_verification_runner_rejects_workspace_escape(tmp_path):
    outside = tmp_path.parent / "outside.py"
    outside.write_text("secret", encoding="utf-8")
    try:
        run_pytest_verification(
            workspace=tmp_path,
            command=[sys.executable, "-m", "pytest", "-q"],
            session_id="session-8ab7",
            artifact_paths=["../outside.py"],
            timeout_s=10,
        )
    except ValueError as exc:
        assert "workspace" in str(exc)
    else:
        raise AssertionError("workspace escape must be rejected")


def test_end_to_end_cli_keeps_run_and_artifact_quality_separate(tmp_path, capsys):
    import json

    from llm_loop.agent_completion import main

    (tmp_path / "test_cli.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    run_path = tmp_path / "run.json"
    argv = [
        "--run-json",
        str(run_path),
        "--workspace",
        str(tmp_path),
        "--artifact",
        "test_cli.py",
        "--test-command",
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "test_cli.py",
    ]
    run_path.write_text(json.dumps(_run()))
    assert main(argv) == 0
    accepted = json.loads(capsys.readouterr().out)
    assert accepted["accepted"] is True
    assert accepted["verification"]["passed"] == 1

    run_path.write_text(json.dumps(_run(status="incomplete", exit_code=1, run_incomplete=True)))
    assert main(argv) == 1
    unfinished = json.loads(capsys.readouterr().out)
    assert unfinished["accepted"] is False
    assert unfinished["verification_ok"] is True
    assert "run_incomplete" in unfinished["reasons"]


def test_verifier_timeout_produces_receipt_and_never_accepts(tmp_path, monkeypatch):
    import subprocess

    from llm_loop import agent_completion

    (tmp_path / "test_example.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    original_run = agent_completion.subprocess.run

    def timed_out_pytest(argv, *args, **kwargs):
        if "pytest" in argv:
            raise subprocess.TimeoutExpired(argv, 1)
        return original_run(argv, *args, **kwargs)

    monkeypatch.setattr(agent_completion.subprocess, "run", timed_out_pytest)
    result = run_pytest_verification(
        workspace=tmp_path,
        command=[sys.executable, "-m", "pytest", "-q", "test_example.py"],
        session_id="session-8ab7",
        artifact_paths=["test_example.py"],
        timeout_s=1,
    )
    assert result["timed_out"] is True
    assert result["test_exit_code"] == 124
    assert result["error_type"] == "TimeoutExpired"
    assert result["errors"] == 1
    assert evaluate_agent_completion(_run(), result)["accepted"] is False


def test_projection_status_missing_fails_closed():
    run = _run()
    del run["projection_cannot_fit"]
    decision = evaluate_agent_completion(run, _verification())
    assert decision["accepted"] is False
    assert "projection_cannot_fit" in decision["reasons"]
    run["projection_cannot_fit"] = False
    assert evaluate_agent_completion(run, _verification())["accepted"] is True

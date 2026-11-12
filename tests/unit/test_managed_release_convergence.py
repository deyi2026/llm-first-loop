"""Fail-closed regression for the Deepin managed wheel release finish flow."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHA = "1c784b47d238d9ab1a503c65d7355cc8f3826cc919e69cfd78bd267a11a73b84"
OLD_SHA = "60ded59f7471e0f544d9f2cd78d98469369753d312aa8de72c2d48d3a612cc6c"


def module(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def verifier():
    return module("verify_managed_release")


@pytest.fixture
def finisher():
    return module("finish_managed_release")


def status_for(gen=11, version="0.6.47", sha=SHA):
    services = {}
    units = {}
    for idx, service in enumerate(("web", "feishu", "learning")):
        pid = str(6000 + idx)
        services[service] = {
            "live": {"pid": int(pid), "pid_alive": True, "release_version": version,
                     "wheel_sha256": sha, "matches_desired_generation": True},
            "stable": {"generation": gen, "matches_desired_generation": True},
            "verify": {"generation": gen, "outcome": "ok", "action_status": "succeeded",
                       "durable_succeeded_receipt": True, "action_id": "svc-test"},
            "restart_required": False, "reasons": [], "terminal_action_barrier": None,
        }
        units[service] = {"ActiveState": "active", "SubState": "running", "MainPID": pid}
    deployment = {"schema": "lfl.managed-service-deployment/v2",
                  "version": version, "generation": gen, "artifact_kind": "wheel_release",
                  "wheel_sha256": sha, "deployment_id": "deploy-test"}
    return {"deployment": deployment, "services": services, "admission_barriers": []}, units


def verify_case(verifier, *, version="0.6.47", gen=11, sha=SHA):
    status, units = status_for()
    health = {"status": "ok", "version": "0.6.47",
              "build": {"release_version": "0.6.47", "wheel_sha256": SHA}}
    return verifier.check(status, health, status["deployment"].copy(), "0.6.47", SHA,
                          units, version=version, sha=sha, generation=gen)


def test_real_shape_three_service_convergence_passes(verifier):
    problems, receipt = verify_case(verifier)
    assert problems == []
    assert receipt["result"] == "PASS"
    assert set(receipt["services"]) == {"web", "feishu", "learning"}


@pytest.mark.parametrize("changed,needle", [
    ({"gen": 10}, "desired generation mismatch"),
    ({"version": "0.6.46"}, "desired version mismatch"),
    ({"sha": "0" * 64}, "wheel SHA mismatch"),
])
def test_stale_expected_identity_rejected(verifier, changed, needle):
    problems, receipt = verify_case(verifier, **changed)
    assert needle in " ".join(problems)
    assert receipt["result"] == "FAIL"


@pytest.mark.parametrize("mutation,needle", [
    (lambda st, un: st["services"]["web"]["stable"].update(generation=10),
     "web: stable generation mismatch"),
    (lambda st, un: st["services"]["web"]["verify"].update(action_status="pending"),
     "web: durable succeeded receipt absent"),
    (lambda st, un: st["services"]["learning"].update(restart_required=True),
     "learning: requires restart"),
    (lambda st, un: un["feishu"].update(MainPID="999"),
     "feishu: systemd PID disagrees with live"),
    (lambda st, un: st["admission_barriers"].append({"service": "web"}),
     "active admission barrier"),
])
def test_incomplete_convergence_fails_closed(verifier, mutation, needle):
    status, units = status_for()
    mutation(status, units)
    problems, _ = verifier.check(
        status,
        {"status": "ok", "version": "0.6.47",
         "build": {"release_version": "0.6.47", "wheel_sha256": SHA}},
        status["deployment"], "0.6.47", SHA, units,
        version="0.6.47", sha=SHA, generation=11,
    )
    assert any(needle in problem for problem in problems)


def staged(tmp_path, *, desired_gen=10, desired_version="0.6.46", desired_sha=OLD_SHA):
    root = tmp_path / "lfl"
    (root / "data/runtime").mkdir(parents=True)
    (root / ".LFL-active-version").write_text("0.6.47\n")
    (root / ".LFL-previous-version").write_text("0.6.46\n")
    release = root / "releases/LFL-0.6.47"
    (release / "venv/bin").mkdir(parents=True)
    (release / ".installer-wheel.sha256").write_text(
        f"{SHA}  llm_first_loop-0.6.47-py3-none-any.whl\n"
    )
    (release / "venv/bin/python").write_text("")
    (root / "releases/LFL-0.6.46/venv/bin").mkdir(parents=True)
    (root / "releases/LFL-0.6.46/venv/bin/python").write_text("")
    desired = {"version": desired_version, "generation": desired_gen,
               "wheel_sha256": desired_sha, "artifact_kind": "wheel_release"}
    (root / "data/runtime/managed_service_deployment.json").write_text(json.dumps(desired))
    return root


def args(root, execute=False):
    return [
        "--version", "0.6.47", "--sha", SHA, "--prior-generation", "10",
        "--expected-host", "test-host", "--install-root", str(root),
        *(["--execute"] if execute else []),
    ]


def test_dry_run_makes_no_mutating_calls(tmp_path, finisher, monkeypatch, capsys):
    root = staged(tmp_path)
    monkeypatch.setattr(finisher.socket, "gethostname", lambda: "test-host")
    monkeypatch.setattr(finisher, "call_svcctl", Mock(side_effect=AssertionError("must not call")))
    monkeypatch.setattr(finisher, "service_inactive", Mock(side_effect=AssertionError("must not call")))
    assert finisher.main(args(root)) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "PLAN_ONLY"


def test_call_svcctl_consumes_final_jsonl_receipt(tmp_path, finisher, monkeypatch):
    accepted = {"ok": True, "action_id": "svc-abc123", "target": "all", "generation": 12}
    final = {
        "ok": True, "action_id": "svc-abc123", "status": "accepted",
        "detached": True, "hint": "worker detached",
    }
    monkeypatch.setattr(
        finisher.subprocess,
        "run",
        Mock(return_value=finisher.subprocess.CompletedProcess(
            args=["python", "-m", "service_control", "restart"],
            returncode=0,
            stdout=json.dumps(accepted) + "\n" + json.dumps(final) + "\n",
            stderr="",
        )),
    )

    result = finisher.call_svcctl(tmp_path / "python", "restart", "--target", "all")

    assert result == final


def test_call_svcctl_rejects_malformed_jsonl_after_valid_record(tmp_path, finisher, monkeypatch):
    first = {"ok": True, "action_id": "svc-abc123"}
    monkeypatch.setattr(
        finisher.subprocess,
        "run",
        Mock(return_value=finisher.subprocess.CompletedProcess(
            args=["python", "-m", "service_control", "restart"],
            returncode=0,
            stdout=json.dumps(first) + "\nnot-json\n",
            stderr="",
        )),
    )

    with pytest.raises(ValueError, match="invalid JSONL.*line 2"):
        finisher.call_svcctl(tmp_path / "python", "restart")


def test_call_svcctl_rejects_mixed_action_jsonl_records(tmp_path, finisher, monkeypatch):
    first = {"ok": True, "action_id": "svc-abc123"}
    final = {"ok": True, "action_id": "svc-other456", "status": "accepted"}
    monkeypatch.setattr(
        finisher.subprocess,
        "run",
        Mock(return_value=finisher.subprocess.CompletedProcess(
            args=["python", "-m", "service_control", "restart"],
            returncode=0,
            stdout=json.dumps(first) + "\n" + json.dumps(final) + "\n",
            stderr="",
        )),
    )

    with pytest.raises(ValueError, match="different actions"):
        finisher.call_svcctl(tmp_path / "python", "restart")


def test_call_svcctl_requires_action_id_on_final_restart_record(tmp_path, finisher, monkeypatch):
    accepted = {"ok": True, "action_id": "svc-abc123"}
    final = {"ok": True, "status": "accepted", "detached": True}
    monkeypatch.setattr(
        finisher.subprocess,
        "run",
        Mock(return_value=finisher.subprocess.CompletedProcess(
            args=["python", "-m", "service_control", "restart"],
            returncode=0,
            stdout=json.dumps(accepted) + "\n" + json.dumps(final) + "\n",
            stderr="",
        )),
    )

    with pytest.raises(ValueError, match="restart JSONL record missing action_id"):
        finisher.call_svcctl(tmp_path / "python", "restart")


def test_call_svcctl_accepts_single_publish_wheel_json_record(tmp_path, finisher, monkeypatch):
    published = {"version": "0.6.48", "generation": 12, "wheel_sha256": SHA}
    monkeypatch.setattr(
        finisher.subprocess,
        "run",
        Mock(return_value=finisher.subprocess.CompletedProcess(
            args=["python", "-m", "service_control", "publish-wheel"],
            returncode=0,
            stdout=json.dumps(published) + "\n",
            stderr="",
        )),
    )

    assert finisher.call_svcctl(tmp_path / "python", "publish-wheel") == published


def test_source_version_drift_stops_before_publish(tmp_path, finisher, monkeypatch):
    root = staged(tmp_path, desired_gen=11)
    monkeypatch.setattr(finisher.socket, "gethostname", lambda: "test-host")
    cli = Mock()
    monkeypatch.setattr(finisher, "call_svcctl", cli)
    assert finisher.main(args(root, execute=True)) == 1
    cli.assert_not_called()


def test_candidate_hash_drift_stops_before_publish(tmp_path, finisher, monkeypatch):
    root = staged(tmp_path)
    (root / "releases/LFL-0.6.47/.installer-wheel.sha256").write_text(
        f"{'0' * 64}  llm_first_loop-0.6.47-py3-none-any.whl\n"
    )
    monkeypatch.setattr(finisher.socket, "gethostname", lambda: "test-host")
    cli = Mock()
    monkeypatch.setattr(finisher, "call_svcctl", cli)
    assert finisher.main(args(root, execute=True)) == 1
    cli.assert_not_called()


def test_wrong_host_stops_before_publish(tmp_path, finisher, monkeypatch):
    root = staged(tmp_path)
    monkeypatch.setattr(finisher.socket, "gethostname", lambda: "another-host")
    cli = Mock()
    monkeypatch.setattr(finisher, "call_svcctl", cli)
    with pytest.raises(SystemExit):
        finisher.main(args(root, execute=True))
    cli.assert_not_called()


def test_execute_waits_for_success_and_then_runs_checker(tmp_path, finisher, monkeypatch, capsys):
    root = staged(tmp_path)
    monkeypatch.setattr(finisher.socket, "gethostname", lambda: "test-host")
    monkeypatch.setattr(finisher, "service_inactive", Mock())
    publish = {"version": "0.6.47", "generation": 11, "wheel_sha256": SHA}
    cli = Mock(side_effect=[publish, {"action_id": "svc-abc123", "status": "accepted"}])
    monkeypatch.setattr(finisher, "call_svcctl", cli)
    wait = Mock(return_value={"status": "succeeded", "verify_verdict": "confirmed_ok"})
    monkeypatch.setattr(finisher, "wait_for_action", wait)
    converge = Mock(return_value=Path("/audit/success.json"))
    monkeypatch.setattr(finisher, "converge", converge)
    assert finisher.main(args(root, execute=True)) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "PASS"
    assert cli.call_count == 2
    wait.assert_called_once()
    converge.assert_called_once()


def test_failed_restart_does_not_mark_success(tmp_path, finisher, monkeypatch):
    root = staged(tmp_path)
    monkeypatch.setattr(finisher.socket, "gethostname", lambda: "test-host")
    monkeypatch.setattr(finisher, "service_inactive", Mock())
    monkeypatch.setattr(finisher, "call_svcctl", Mock(side_effect=[
        {"version": "0.6.47", "generation": 11, "wheel_sha256": SHA},
        {"action_id": "svc-abc123"},
    ]))
    monkeypatch.setattr(finisher, "wait_for_action", Mock(side_effect=RuntimeError("failed")))
    converge = Mock()
    monkeypatch.setattr(finisher, "converge", converge)
    assert finisher.main(args(root, execute=True)) == 1
    converge.assert_not_called()


def test_already_deployed_is_idempotent(tmp_path, finisher, monkeypatch, capsys):
    root = staged(tmp_path, desired_gen=11, desired_version="0.6.47", desired_sha=SHA)
    monkeypatch.setattr(finisher.socket, "gethostname", lambda: "test-host")
    cli = Mock()
    monkeypatch.setattr(finisher, "call_svcctl", cli)
    converge = Mock(return_value=Path("/audit/existing.json"))
    monkeypatch.setattr(finisher, "converge", converge)
    assert finisher.main(args(root)) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "PLAN_ALREADY_DEPLOYED"
    assert finisher.main(args(root, execute=True)) == 0
    cli.assert_not_called()
    converge.assert_called_once()


def test_action_receipt_rejects_failed_terminal(tmp_path, finisher, monkeypatch):
    action = tmp_path / "runtime/service-control-actions/svc-abc123.json"
    action.parent.mkdir(parents=True)
    action.write_text(json.dumps({"action_id": "svc-abc123", "status": "failed"}))
    monkeypatch.setattr(finisher.time, "monotonic", Mock(side_effect=[0, 2]))
    with pytest.raises(RuntimeError, match="restart ended failed"):
        finisher.wait_for_action(tmp_path, "svc-abc123", 10)


def test_action_receipt_requires_confirmed_ok(tmp_path, finisher, monkeypatch):
    action = tmp_path / "runtime/service-control-actions/svc-abc123.json"
    action.parent.mkdir(parents=True)
    action.write_text(json.dumps({"action_id": "svc-abc123", "status": "succeeded",
                                  "verify_verdict": "unconfirmed"}))
    monkeypatch.setattr(finisher.time, "monotonic", Mock(side_effect=[0, 2]))
    with pytest.raises(RuntimeError, match="without confirmed_ok"):
        finisher.wait_for_action(tmp_path, "svc-abc123", 10)


def test_convergence_receipt_create_only(tmp_path, verifier, monkeypatch):
    status, units = status_for()
    root = staged(tmp_path, desired_gen=11, desired_version="0.6.47", desired_sha=SHA)
    (root / "data/runtime/managed_service_deployment.json").write_text(
        json.dumps(status["deployment"])
    )
    monkeypatch.setattr(verifier, "fetch_json", lambda url:
                        (status if "services/status" in url else
                         {"status": "ok", "version": "0.6.47", "build":
                          {"release_version": "0.6.47", "wheel_sha256": SHA}}, "test-date"))
    monkeypatch.setattr(verifier, "unit_show", lambda unit:
                        units[{"lfl.service": "web", "lfl-feishu.service": "feishu",
                               "lfl-learning.service": "learning"}[unit]])
    monkeypatch.setattr(verifier.socket, "gethostname", lambda: "test-host")
    receipt = tmp_path / "stable.json"
    argv = ["verify_managed_release.py", "--expected-host", "test-host",
            "--expected-version", "0.6.47", "--expected-generation", "11",
            "--expected-sha", SHA, "--install-root", str(root), "--receipt", str(receipt)]
    monkeypatch.setattr(sys, "argv", argv)
    assert verifier.main() == 0
    original = receipt.read_bytes()
    assert verifier.main() == 3
    assert receipt.read_bytes() == original


def test_release_workflow_ships_verifier_and_finisher():
    release = (ROOT / ".github/workflows/release.yml").read_text()
    for name in ("verify_managed_release.py", "finish_managed_release.py"):
        assert f"scripts/{name}" in release
        assert f"dist/{name}" in release


def test_active_unit_blocks_publish_before_mutation(tmp_path, finisher, monkeypatch):
    root = staged(tmp_path)
    monkeypatch.setattr(finisher.socket, "gethostname", lambda: "test-host")
    proc = Mock(returncode=0, stdout="active\n")
    monkeypatch.setattr(finisher.subprocess, "run", Mock(return_value=proc))
    cli = Mock()
    monkeypatch.setattr(finisher, "call_svcctl", cli)
    assert finisher.main(args(root, execute=True)) == 1
    cli.assert_not_called()


def test_unsafe_symlink_release_refused(tmp_path, finisher):
    root = staged(tmp_path)
    release = root / "releases/LFL-0.6.47"
    shadow = root / "shadow-release"
    release.rename(shadow)
    release.symlink_to(shadow, target_is_directory=True)
    with pytest.raises(ValueError, match="unsafe staged"):
        finisher.check_staged(root, "0.6.47", SHA)

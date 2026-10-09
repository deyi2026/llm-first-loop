"""2026-10-09: resolver diagnostics must never become a restart endpoint."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import llm_loop.runtime.service_control as sc

ROOT = Path(__file__).resolve().parents[2]


def _resolver(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "llm_loop.runtime.resolver", *args],
        cwd=tmp_path,
        env={
            "PATH": os.defpath,
            "PYTHONPATH": str(ROOT / "src"),
            "LFL_RUNTIME_ROOT": str(tmp_path),
            "WEB_PORT": "8902",
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_restart_key_queries_return_only_authoritative_value(tmp_path):
    (tmp_path / "runtime.toml").write_text('[web]\nport = 18903\nhost = "127.0.0.2"\n')
    port = _resolver(tmp_path, "WEB_PORT")
    host = _resolver(tmp_path, "WEB_HOST")
    assert (port.returncode, port.stdout) == (0, "18903\n")
    assert (host.returncode, host.stdout) == (0, "127.0.0.2\n")


@pytest.mark.parametrize("args", [(), ("--check-toml",), ("UNKNOWN_KEY",)])
def test_bad_cli_arguments_fail_without_value_on_stdout(tmp_path, args):
    result = _resolver(tmp_path, *args)
    assert result.returncode == 2
    assert result.stdout == ""


def _rollback_fixture(tmp_path, monkeypatch, *, healthy=True):
    bad_root = tmp_path / "bad"
    good_root = tmp_path / ".releases" / ("b" * 40)
    for root, failing in ((bad_root, True), (good_root, False)):
        scripts = root / "scripts"
        scripts.mkdir(parents=True)
        script = scripts / "restart_mirror.sh"
        script.write_text(
            "#!/bin/bash\n"
            'printf "%s %s\\n" "$LFL_RESTART_ACTION_ID" "$1" >> "$LFL_RESTART_RUNTIME_ROOT/attempts"\n'
            + (
                'mkdir -p "$LFL_RESTART_RUNTIME_ROOT/data"\n'
                'printf \'{"action":"web","rc":1,"action_id":"%s","stage_fact":"web_stopped"}\\n\' '
                '"$LFL_RESTART_ACTION_ID" > "$LFL_RESTART_RUNTIME_ROOT/data/restart-receipt.json"\n'
                "exit 1\n"
                if failing or not healthy
                else "exit 0\n"
            )
        )
    deployment = sc.ManagedServiceDeployment(
        schema="managed-service-deployment/v1",
        deployment_id="bad-deploy",
        generation=1,
        git_head="a" * 40,
        code_root=str(bad_root),
        runtime_root=str(tmp_path),
        webui_artifact_sha256="c" * 64,
    )
    good = sc.dataclasses.replace(
        deployment, deployment_id="good-deploy", generation=2,
        git_head="b" * 40, code_root=str(good_root),
    )
    store = sc.ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(deployment, expected_generation=0)
    receipt = {"action": "web", "rc": 0, "authority": "service_control", "git_head_full": "b" * 40}
    (tmp_path / "data" / "restart-receipt.log").write_text(json.dumps(receipt) + "\n")
    monkeypatch.setattr(sc, "build_deployment", lambda **_kwargs: good)
    monkeypatch.setattr(sc, "_binding_problems_structured", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sc, "_requester_run_active", lambda *_args: False)
    monkeypatch.setattr(sc, "_target_idle_probe", lambda **_kwargs: False)
    monkeypatch.setattr(sc, "_verify_restart_targets", lambda *_args: ("confirmed_ok", "verified", ["web"]))
    action = store.accept_restart(target="web", expected_generation=1, requester_session_id="operator")
    return store, action


def test_failed_restart_restores_with_new_bound_action_and_verified_receipt(tmp_path, monkeypatch):
    store, action = _rollback_fixture(tmp_path, monkeypatch)
    assert sc.run_action_worker(store, action.action_id) != 0
    attempts = (tmp_path / "attempts").read_text().splitlines()
    assert len(attempts) == 2
    original_id, original_target = attempts[0].split()
    recovery_id, recovery_target = attempts[1].split()
    assert original_id == action.action_id
    assert recovery_id != original_id
    assert original_target == recovery_target == "web"
    recovery = store.read_action(recovery_id)
    assert recovery is not None and recovery.status == "succeeded"
    assert recovery.deployment_generation == store.read().generation == 2
    assert store.barriers.blocked("web") is None
    original = store.read_action(original_id)
    assert original is not None and original.deployment_generation == 1
    assert recovery_id in original.detail


def test_failed_recovery_is_bounded_to_one_attempt_and_keeps_barrier(tmp_path, monkeypatch):
    store, action = _rollback_fixture(tmp_path, monkeypatch, healthy=False)
    assert sc.run_action_worker(store, action.action_id) != 0
    attempts = (tmp_path / "attempts").read_text().splitlines()
    assert len(attempts) == 2
    assert store.barriers.blocked("web") is not None


def test_recovery_does_not_release_barrier_on_missing_identity_evidence(tmp_path, monkeypatch):
    store, action = _rollback_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(sc, "_verify_restart_targets", lambda *_args: ("criterion_absent", "no identity", []))
    assert sc.run_action_worker(store, action.action_id) != 0
    assert len((tmp_path / "attempts").read_text().splitlines()) == 2
    assert store.barriers.blocked("web") is not None


def test_unknown_physical_outcome_does_not_trigger_automatic_restart(tmp_path, monkeypatch):
    store, action = _rollback_fixture(tmp_path, monkeypatch)
    script = tmp_path / "bad" / "scripts" / "restart_mirror.sh"
    script.write_text('printf "one\\n" >> "$LFL_RESTART_RUNTIME_ROOT/attempts"\nexit 1\n')
    assert sc.run_action_worker(store, action.action_id) != 0
    assert (tmp_path / "attempts").read_text() == "one\n"
    assert store.read().generation == 1


def test_preflight_failure_releases_admission_without_recovery(tmp_path, monkeypatch):
    store, action = _rollback_fixture(tmp_path, monkeypatch)
    script = tmp_path / "bad" / "scripts" / "restart_mirror.sh"
    script.write_text(script.read_text().replace("web_stopped", "not_started"))
    assert sc.run_action_worker(store, action.action_id) != 0
    assert len((tmp_path / "attempts").read_text().splitlines()) == 1
    assert store.read().generation == 1
    assert store.barriers.blocked("web") is None


def test_wrong_service_success_receipt_is_not_a_web_recovery_candidate(tmp_path, monkeypatch):
    store, action = _rollback_fixture(tmp_path, monkeypatch)
    log = tmp_path / "data" / "restart-receipt.log"
    log.write_text(log.read_text().replace('"web"', '"feishu"'))
    assert sc.run_action_worker(store, action.action_id) != 0
    assert len((tmp_path / "attempts").read_text().splitlines()) == 1
    assert store.read().generation == 1


def test_concurrent_publish_wins_over_automatic_rollback(tmp_path, monkeypatch):
    store, action = _rollback_fixture(tmp_path, monkeypatch)
    newer = sc.dataclasses.replace(store.read(), generation=2, deployment_id="newer-deploy")

    def racing_build(**_kwargs):
        store.compare_and_swap(newer, expected_generation=1)
        return sc.dataclasses.replace(newer, deployment_id="rollback-deploy")

    monkeypatch.setattr(sc, "build_deployment", racing_build)
    assert sc.run_action_worker(store, action.action_id) != 0
    assert len((tmp_path / "attempts").read_text().splitlines()) == 1
    assert store.read().deployment_id == "newer-deploy"


@pytest.mark.parametrize("port", ["runtime.toml 不存在，跳过 schema 校验: WEB_PORT", "0", "65536"])
def test_actual_script_rejects_bad_endpoint_before_any_physical_action(tmp_path, port):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "data").mkdir()
    (runtime / "src").symlink_to(ROOT / "src", target_is_directory=True)
    (runtime / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0"\n')
    subprocess.run(["git", "init", "-q", str(runtime)], check=True)
    subprocess.run(["git", "-C", str(runtime), "add", "src", "pyproject.toml"], check=True)
    subprocess.run(
        ["git", "-C", str(runtime), "-c", "user.name=fixture", "-c", "user.email=fixture@test.invalid", "commit", "-qm", "fixture"],
        check=True,
    )
    python_dir = runtime / ".venv" / "bin"
    python_dir.mkdir(parents=True)
    (python_dir / "python").symlink_to(sys.executable)
    (runtime / ".env").write_text(f"WEB_PORT={port}\nWEB_HOST=127.0.0.1\n")
    dist = runtime / "webui" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text('<script src="/ui/v2/assets/main.js"></script>')
    (dist / "assets").mkdir()
    (dist / "assets" / "main.js").write_text("fixture")
    result = subprocess.run(
        ["/bin/bash", str(ROOT / "scripts" / "restart_mirror.sh"), "web"],
        env={
            "PATH": os.defpath,
            "LFL_RESTART_CODE_ROOT": str(runtime),
            "LFL_RESTART_RUNTIME_ROOT": str(runtime),
            "LFL_RESTART_CODE_ROOT_CONFIRMED": "1",
            "LFL_RESTART_RUNTIME_ROOT_CONFIRMED": "1",
            "LFL_RESTART_ACTION_ID": "endpoint-regression",
        },
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    assert "Web 端口解析无效" in result.stdout
    receipt = json.loads((runtime / "data" / "restart-receipt.json").read_text())
    assert receipt["stage_fact"] == "not_started"
    assert receipt["action_id"] == "endpoint-regression"

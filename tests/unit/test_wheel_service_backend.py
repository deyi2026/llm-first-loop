from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from llm_loop.runtime import installation, wheel_service
from llm_loop.runtime import service_control as sc


def test_unit_preparation_does_not_restart_or_enable_services(tmp_path):
    tmp_path = tmp_path.resolve()
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    result = installation.install_service_units(tmp_path / "lfl", home=tmp_path, runner=run,
                                               start_services=False)
    assert result["status"] == "installed"
    assert result["enabled"] == []
    assert all("restart" not in " ".join(argv) and "enable" not in argv for argv in calls)
    assert len([argv for argv in calls if argv[0] == "systemd-analyze"]) == 4


def test_wheel_backend_restarts_exactly_the_three_managed_units(tmp_path, monkeypatch):
    calls = []
    names = {"lfl.service": "web", "lfl-feishu.service": "feishu", "lfl-learning.service": "learning"}

    def run(argv, **kwargs):
        calls.append(argv)
        if "show" in argv:
            launcher = str(tmp_path / "bin/lfl-service")
            text = f"{{ path={launcher} ; argv[]={launcher} {names[argv[3]]} ; ignore_errors=no ; }}"
            return subprocess.CompletedProcess(argv, 0, stdout=text)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(wheel_service.subprocess, "run", run)
    assert wheel_service.restart_units(tmp_path, "all") == 0
    restarted = [a[-1] for a in calls if "restart" in a]
    assert restarted == ["lfl-recovery.service", "lfl.service", "lfl-feishu.service", "lfl-learning.service"]
    assert all("wecom" not in " ".join(a) for a in calls)


def test_legacy_unit_binding_is_rejected_before_any_restart(tmp_path, monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="{ path=/old/venv/bin/lfl ; }")

    monkeypatch.setattr(wheel_service.subprocess, "run", run)
    with pytest.raises(ValueError, match="not bound"):
        wheel_service.restart_units(tmp_path, "all")
    assert not any("restart" in a for a in calls)


def test_packaged_worker_gets_a_separate_systemd_unit(tmp_path, monkeypatch):
    dep = sc.ManagedServiceDeployment(
        schema="lfl.managed-service-deployment/v2", deployment_id="wheel-controller",
        generation=1, git_head="", code_root="", runtime_root=str(tmp_path),
        webui_artifact_sha256="a" * 64, artifact_kind="wheel_release",
        data_dir=str(tmp_path / "data"), version="0.6.42", wheel_sha256="b" * 64,
        release_dir=str(tmp_path / "releases/LFL-0.6.42"),
    )
    store = sc.ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(dep, expected_generation=0)
    action = store.accept_restart(target="all", expected_generation=1, requester_session_id="")
    calls = []
    monkeypatch.setattr(sc, "_controller_python_src", lambda: Path("/controller/site-packages"))
    monkeypatch.setattr(sc.subprocess, "run", lambda argv, **kw: calls.append(argv))
    sc.spawn_service_control_worker(store, action.action_id)
    argv = calls[0]
    assert argv[0] == "systemd-run"
    assert "--unit=lfl-control-" + action.action_id in argv
    assert "/usr/bin/env" in argv and "-i" in argv
    assert "PYTHONPATH=/controller/site-packages" in argv

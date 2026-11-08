"""Deployment-shaped regressions for the three Deepin services."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime

import pytest

from llm_loop.runtime import service_control as sc


@pytest.fixture
def deployment(tmp_path):
    home = tmp_path / "lfl"
    release = home / "releases/LFL-0.6.42"
    release.mkdir(parents=True)
    wheel = release / "llm_first_loop-0.6.42-py3-none-any.whl"
    wheel.write_bytes(b"frozen candidate")
    sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    (release / ".installer-wheel.sha256").write_text(f"{sha}  {wheel.name}\n")
    (home / ".LFL-active-version").write_text("0.6.42\n")
    dist = release / "venv/lib/python3.13/site-packages/llm_loop/webui/dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("candidate UI")
    dep = sc.build_wheel_deployment(home, webui_artifact_sha256=sc._tree_sha256(dist), generation=1)
    store = sc.ManagedServiceDeploymentStore(home / "data")
    store.compare_and_swap(dep, expected_generation=0)
    return store, dep


def write_live(store, dep, service, **changes):
    build = {"artifact_kind": "wheel_release", "release_version": dep.version,
             "wheel_sha256": dep.wheel_sha256, "release_dir": dep.release_dir,
             "package_root": dep.release_dir + "/venv/lib/python3.13/site-packages/llm_loop"}
    build.update(changes)
    raw = {"pid": os.getpid(), "service": service, "git_head": "unknown",
           "started_at": datetime.now(UTC).isoformat(), "data_dir": dep.data_dir,
           "python_executable": dep.release_dir + "/venv/bin/python", "build_identity": build}
    store.runtime_dir.mkdir(parents=True, exist_ok=True)
    (store.runtime_dir / f"runtime_manifest.{service}.json").write_text(json.dumps(raw))


@pytest.mark.parametrize("service", ["web", "feishu", "learning"])
def test_same_version_wrong_wheel_is_not_green(deployment, service):
    store, dep = deployment
    write_live(store, dep, service, wheel_sha256="0" * 64)
    view = sc.compose_service_identity_view(store)["services"][service]
    assert view["restart_required"]
    assert any("wheel_sha256_mismatch" in r for r in view["reasons"])
    verdict, detail, healthy = sc._verify_restart_targets(store, dep, [service], "2000-01-01T00:00:00Z")
    assert verdict == "confirmed_fail"
    assert service not in healthy
    assert "wheel_sha256_mismatch" in detail


def test_wheel_restart_plan_does_not_require_a_source_checkout(deployment):
    store, dep = deployment
    action = store.accept_restart(target="all", expected_generation=1, requester_session_id="")
    plan = sc.build_restart_plan(action, dep)
    assert plan.argv[0] == dep.release_dir + "/venv/bin/python"
    assert plan.argv[1:3] == ("-m", "llm_loop.runtime.wheel_service")
    assert plan.argv[-1] == "all"


def test_publish_wheel_cli_uses_verified_installation_and_cas(deployment, capsys):
    store, dep = deployment
    assert sc.main(["publish-wheel", "--lfl-home", dep.runtime_root,
                    "--expected-generation", "1"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["artifact_kind"] == "wheel_release"
    assert result["wheel_sha256"] == dep.wheel_sha256
    assert result["generation"] == 2
    assert not result.get("git_head")
    with pytest.raises(sc.DeploymentGenerationConflictError):
        sc.main(["publish-wheel", "--lfl-home", dep.runtime_root, "--expected-generation", "1"])
    assert store.read().generation == 2


def test_all_worker_records_real_three_service_verification(deployment, monkeypatch):
    store, dep = deployment
    action = store.accept_restart(target="all", expected_generation=1, requester_session_id="")
    observed = []

    def restart(argv, **kwargs):
        observed.append(argv)
        for service in ("web", "feishu", "learning"):
            write_live(store, dep, service)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(sc.subprocess, "run", restart)
    assert sc.run_action_worker(store, action.action_id) == 0
    assert observed[0][1:3] == ["-m", "llm_loop.runtime.wheel_service"]
    final = store.read_action(action.action_id)
    assert final.status == "succeeded"
    assert final.verify_verdict == "confirmed_ok"
    view = sc.compose_service_identity_view(store)
    for service in ("web", "feishu", "learning"):
        assert not view["services"][service]["restart_required"]
        stable = view["services"][service]["stable"]
        assert stable["wheel_sha256"] == dep.wheel_sha256
        assert stable["matches_desired_generation"]
    assert not view["admission_barriers"]


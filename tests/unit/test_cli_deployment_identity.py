"""Frozen startup facts must not be confused with mutable checkout HEAD."""
from __future__ import annotations

import subprocess
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.runtime.cli_admission import cli_deployment_identity_view
from llm_loop.runtime.cli_deployment_identity import (
    StartupArtifactIdentity,
    capture_startup_artifact,
    compare_startup_artifact,
)
from llm_loop.runtime.service_control import ManagedServiceDeployment

HEAD = "a" * 40
NEXT = "b" * 40


def source_deployment(tmp_path: Path, head: str = HEAD, generation: int = 1):
    return ManagedServiceDeployment(
        schema="managed-service-deployment/v1", deployment_id="test",
        generation=generation, git_head=head, code_root=str(tmp_path / "release"),
        runtime_root=str(tmp_path), webui_artifact_sha256="c" * 64,
    )


def source_startup(tmp_path: Path):
    root = tmp_path / "release"
    return StartupArtifactIdentity(42, "source_checkout", str(root / "src/llm_loop/__init__.py"),
                                   "/venv/bin/python", code_root=str(root), git_head=HEAD)


def test_capture_uses_loaded_module_root_and_freezes_head(monkeypatch, tmp_path):
    import llm_loop

    root = tmp_path / "release"
    module = root / "src/llm_loop/__init__.py"
    module.parent.mkdir(parents=True)
    module.touch()
    (root / "pyproject.toml").touch()
    (root / ".git").touch()
    monkeypatch.setattr(llm_loop, "__file__", str(module))
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(tmp_path / "unrelated"))
    calls = []

    def git(args, **_kwargs):
        calls.append(args)
        assert args[:3] == ["git", "-C", str(root)]
        return SimpleNamespace(stdout=HEAD if args[3] == "rev-parse" else "")

    monkeypatch.setattr(subprocess, "run", git)
    startup = capture_startup_artifact()
    assert startup.git_head == HEAD and startup.code_root == str(root)
    assert len(calls) == 2
    with pytest.raises(FrozenInstanceError):
        startup.git_head = NEXT  # type: ignore[misc]
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("comparison must not run Git"))
    assert compare_startup_artifact(startup, source_deployment(tmp_path))["state"] == "identity_matches_target"
    view = compare_startup_artifact(startup, source_deployment(tmp_path, NEXT, 2))
    assert view["state"] == "update_required" and view["reason"] == "git_head_mismatch"
    assert view["startup_artifact"]["git_head"] == HEAD
    assert view["desired_generation"] == 2
    assert view["admission_verified"] is False


def test_same_sha_wrong_root_and_dirty_source_are_not_current(tmp_path):
    desired = source_deployment(tmp_path)
    startup = source_startup(tmp_path)
    assert compare_startup_artifact(replace(startup, code_root=str(tmp_path / "dev")), desired)["reason"] == "code_root_mismatch"
    dirty = compare_startup_artifact(replace(startup, reason="source_dirty"), desired)
    assert dirty["state"] == "unverified" and dirty["reason"] == "source_dirty"


def test_wheel_identity_uses_digest_and_release_not_git(tmp_path):
    release = tmp_path / "releases/LFL-0.6.57"
    venv = release / "venv"
    desired = ManagedServiceDeployment(
        schema="lfl.managed-service-deployment/v2", deployment_id="wheel",
        generation=7, git_head="", code_root="", runtime_root=str(tmp_path),
        data_dir=str(tmp_path / "data"), webui_artifact_sha256="c" * 64,
        artifact_kind="wheel_release", version="0.6.57", wheel_sha256=HEAD + "a" * 24,
        release_dir=str(release),
    )
    startup = StartupArtifactIdentity(
        42, "wheel_release", str(venv / "lib/llm_loop/__init__.py"),
        str(venv / "bin/python"), version=desired.version,
        wheel_sha256=desired.wheel_sha256, release_dir=str(release),
    )
    assert compare_startup_artifact(startup, desired)["state"] == "identity_matches_target"
    assert compare_startup_artifact(replace(startup, wheel_sha256="b" * 64), desired)["reason"] == "wheel_identity_mismatch"
    assert compare_startup_artifact(replace(startup, python_executable="/other/python"), desired)["reason"] == "wheel_runtime_path_mismatch"
    assert compare_startup_artifact(replace(startup, reason="wheel_identity_unverified"), desired)["state"] == "unverified"


def test_read_only_missing_and_malformed_deployment(tmp_path):
    data = tmp_path / "unregistered-cli-data"
    assert not data.exists()
    startup = source_startup(tmp_path)
    assert cli_deployment_identity_view(data, startup)["reason"] == "deployment_not_registered"
    assert not data.exists()
    runtime = data / "runtime"
    runtime.mkdir(parents=True)
    path = runtime / "managed_service_deployment.json"
    path.write_text("not json", encoding="utf-8")
    view = cli_deployment_identity_view(data, startup)
    assert view["state"] == "unverified" and view["reason"] == "deployment_record_unreadable"
    assert list(runtime.iterdir()) == [path]
    assert path.read_text(encoding="utf-8") == "not json"

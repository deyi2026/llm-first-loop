from __future__ import annotations

import hashlib
import zipfile

import pytest

from llm_loop.runtime import wheel_identity as wi
from llm_loop.runtime.build_identity import compute_build_identity


@pytest.fixture
def installed(tmp_path, monkeypatch):
    release = tmp_path / "lfl/releases/LFL-0.6.42"
    package = release / "venv/lib/python3.13/site-packages/llm_loop"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('VERSION = "0.6.42"\n')
    wheel = release / "llm_first_loop-0.6.42-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("llm_loop/__init__.py", (package / "__init__.py").read_bytes())
    sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    (release / ".installer-wheel.sha256").write_text(f"{sha}  {wheel.name}\n")
    monkeypatch.setattr(wi, "installed_identity", lambda module: {
        "version": "0.6.42", "package_root": str(package), "name": "llm-first-loop"})
    return release, package, sha


def test_build_identity_uses_own_wheel_even_if_workspace_is_a_different_repository(installed, tmp_path):
    release, _, sha = installed
    workspace = tmp_path / "old-source"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text('[project]\nversion = "0.6.40"\n')
    result = compute_build_identity(workspace)
    assert result["release_version"] == "0.6.42"
    assert result["wheel_sha256"] == sha
    assert result["release_dir"] == str(release)
    assert not result["git_available"]
    assert not result["git_head"]


def test_modifying_installed_code_does_not_keep_a_verified_wheel_identity(installed):
    _, package, _ = installed
    (package / "__init__.py").write_text("modified code")
    result = wi.installed_build_identity()
    assert "mismatch" in result["identity_error"]
    assert result["artifact_kind"] != "wheel_release"
    assert "wheel_sha256" not in result


def test_source_checkout_retains_its_existing_identity_path(tmp_path, monkeypatch):
    monkeypatch.setattr(wi, "installed_identity", lambda module: None)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.6.42"\n')
    result = compute_build_identity(tmp_path)
    assert result["release_version"] == "0.6.42"
    assert result.get("artifact_kind") != "wheel_release"

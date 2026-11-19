"""Non-root installer/bundle safety tests. No Host mutation is performed."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    path = ROOT / f"scripts/embodied/{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_host_installer_refuses_unprivileged_apply(monkeypatch):
    installer = _load("m1_oracle_host_install")
    monkeypatch.setattr(installer.os, "getuid", lambda: 501)
    monkeypatch.setattr(installer.os, "geteuid", lambda: 501)
    with pytest.raises(RuntimeError, match="administrator/root required"):
        installer._root_only()
    assert installer.TARGET.name == "lfl-m1-oracle-v1"
    assert installer.PLIST.name == "com.lfl.m1-oracle.plist"
    assert Path("/private/var/db/lfl-m1-oracle") == installer.STATE


def test_installer_manifest_requires_exact_frozen_bytes(tmp_path, monkeypatch):
    installer = _load("m1_oracle_host_install")
    stage = tmp_path / "stage"
    bundle = stage / "bundle"
    bundle.mkdir(parents=True)
    target = bundle / "src"
    target.mkdir()
    source = target / "file.py"
    source.write_text("value=1\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = {
        "schema": "lfl.m1-oracle-host-bundle/v1",
        "python": "3.13.16",
        "architecture": "arm64",
        "files": {"src/file.py": digest},
    }
    raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    (bundle / "manifest.json").write_bytes(raw)
    frozen = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(installer, "_trusted", lambda *_a, **_kw: True)
    assert installer._manifest(bundle, frozen)["files"] == manifest["files"]
    with pytest.raises(RuntimeError, match="reviewed manifest SHA256 mismatch"):
        installer._manifest(bundle, "0" * 64)
    source.write_text("value=2\n")
    with pytest.raises(RuntimeError, match="bundle content mismatch"):
        installer._manifest(bundle, frozen)
    source.write_text("value=1\n")
    (bundle / "extra.txt").write_text("unexpected")
    with pytest.raises(RuntimeError, match="bundle content mismatch"):
        installer._manifest(bundle, frozen)


def test_installer_rejects_symlink_and_user_writable_staging(tmp_path, monkeypatch):
    installer = _load("m1_oracle_host_install")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "file.py").write_text("value=1\n")
    manifest = {
        "schema": "lfl.m1-oracle-host-bundle/v1",
        "python": "3.13.16",
        "architecture": "arm64",
        "files": {
            "file.py": hashlib.sha256((bundle / "file.py").read_bytes()).hexdigest(),
        },
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    assert not installer._trusted(bundle, directory=True)
    monkeypatch.setattr(installer, "_trusted", lambda *_a, **_kw: True)
    (bundle / "escape").symlink_to(tmp_path)
    raw = (bundle / "manifest.json").read_bytes()
    with pytest.raises(RuntimeError, match="untrusted bundle entry"):
        installer._manifest(bundle, hashlib.sha256(raw).hexdigest())


def test_service_refuses_worktree_execution_and_profile_is_write_scoped():
    service = _load("m1_oracle_host_service")
    with pytest.raises(RuntimeError, match="fixed Python3.13"):
        service._bootstrap()
    builder = _load("m1_oracle_host_bundle")
    profile = builder.SANDBOX_PROFILE
    assert "(deny network*)" in profile
    assert "(deny file-write*)" in profile
    assert '(subpath "/private/var/db/lfl-m1-oracle")' in profile
    assert '(subpath "/private/var/run/lfl-m1-oracle")' in profile
    assert '(deny file-read* (subpath "/Users")' in profile

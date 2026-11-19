"""Non-root installer/bundle safety tests. No Host mutation is performed."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import plistlib
import subprocess
import sys
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
    assert installer._target_from_manifest("a" * 64).name == "lfl-m1-oracle-v2-" + "a" * 12
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


def test_v2_service_refuses_user_owned_trial_config(tmp_path, monkeypatch):
    service = _load("m1_oracle_host_service")
    config = tmp_path / "trial.json"
    config.write_text(json.dumps({"schema": "lfl.m1-oracle-host-trial/v1",
                                  "experiment_id": "M1-SIM-002",
                                  "trial": {"phase": "smoke", "arm": "B1",
                                            "trial_index": 7, "seed": 7}}))
    monkeypatch.setattr(service, "TRIAL_CONFIG", config)
    monkeypatch.setattr(service, "_trusted", lambda *_a, **_kw: True)
    with pytest.raises(RuntimeError, match="ownership/mode/size invalid"):
        service._load_trial()


def test_fresh_install_target_matches_v2_bootstrap_and_rejects_plist_spoof(tmp_path, monkeypatch):
    installer = _load("m1_oracle_host_install")
    sha = "a" * 64
    with pytest.raises(RuntimeError, match="64 lowercase hex"):
        installer._target_from_manifest("A" * 64)
    monkeypatch.setattr(installer, "PRIVILEGED_ROOT", tmp_path)
    target = installer._target_from_manifest(sha)
    assert target == tmp_path / ("lfl-m1-oracle-v2-" + "a" * 12)
    plist = tmp_path / "oracle.plist"
    monkeypatch.setattr(installer, "PLIST", plist)
    monkeypatch.setattr(installer, "_trusted", lambda *_a, **_kw: True)
    args = [
        "/usr/bin/sandbox-exec", "-f", str(target / "oracle.sb"),
        str(target / "runtime/bin/python3.13"), "-I", "-S", "-B",
        str(target / "m1_oracle_host_service.py"), "--serve",
    ]
    metadata = {"Label": installer.LABEL, "UserName": "_lfl_oracle",
                "GroupName": "_lfl_oracle", "ProgramArguments": args}
    plist.write_bytes(plistlib.dumps(metadata))
    assert installer._installed_target() == target
    args[7] = str(tmp_path / "untrusted" / "m1_oracle_host_service.py")
    plist.write_bytes(plistlib.dumps(metadata))
    with pytest.raises(RuntimeError, match="trusted Oracle"):
        installer._installed_target()
    args[7] = str(target / "m1_oracle_host_service.py")
    metadata["UserName"] = "root"
    plist.write_bytes(plistlib.dumps(metadata))
    with pytest.raises(RuntimeError, match="trusted Oracle"):
        installer._installed_target()


def test_fresh_v2_apply_uses_same_manifest_pinned_target_throughout(tmp_path, monkeypatch):
    installer = _load("m1_oracle_host_install")
    monkeypatch.setattr(installer, "PRIVILEGED_ROOT", tmp_path)
    monkeypatch.setattr(installer, "LEGACY_V1", tmp_path / "lfl-m1-oracle-v1")
    for key in ("QUEUE", "STATE", "KEY", "PUB", "PLIST"):
        monkeypatch.setattr(installer, key, tmp_path / key.lower())
    for name in ("_root_only", "_check_account", "_prepare_state"):
        monkeypatch.setattr(installer, name, lambda: None)
    monkeypatch.setattr(installer, "_trusted", lambda *_a, **_kw: True)
    monkeypatch.setattr(installer, "_manifest", lambda *_a: {})
    seen = []
    monkeypatch.setattr(installer, "_install_bundle", lambda _bundle, target: seen.append(("copy", target)))
    monkeypatch.setattr(installer, "_init_key", lambda target: seen.append(("key", target)))
    monkeypatch.setattr(installer, "_probe_isolated_runtime", lambda target: seen.append(("probe", target)))
    monkeypatch.setattr(installer, "_write_plist", lambda target: seen.append(("plist", target)))
    monkeypatch.setattr(installer, "_service_health", lambda target: {"pid": 1, "target": str(target)})
    monkeypatch.setattr(installer.subprocess, "run", lambda *_a, **_kw: None)
    installer._apply(tmp_path / "bundle", "b" * 64)
    target = tmp_path / ("lfl-m1-oracle-v2-" + "b" * 12)
    assert seen == [(name, target) for name in ("copy", "key", "probe", "plist")]


def test_direct_host_verify_script_bootstraps_local_imports(tmp_path):
    script = ROOT / "scripts/embodied/verify_oracle_host_macos.py"
    code = (
        "import runpy,sys;"
        f"runpy.run_path({str(script)!r},run_name='import_only');"
        f"assert sys.path[0]=={str(ROOT / 'src')!r};"
        "from llm_loop.embodied_sim.contract import VerificationStatus"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr

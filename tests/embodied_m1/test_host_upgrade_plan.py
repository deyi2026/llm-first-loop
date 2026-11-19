"""Non-root M1-only upgrade/switch safety; no LaunchDaemon mutation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import plistlib
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.embodied_sim.paired_budget import (
    BATCH_USD_LIMIT,
    CALL_RESERVE_USD_LIMIT,
    REQUIRED,
)

ROOT = Path(__file__).resolve().parents[2]


def _upgrade_module():
    path = ROOT / "scripts/embodied/m1_oracle_host_upgrade.py"
    spec = importlib.util.spec_from_file_location("m1_oracle_host_upgrade", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_root_stage_is_mandatory(monkeypatch):
    mod = _upgrade_module()
    monkeypatch.setattr(mod.os, "getuid", lambda: 501)
    monkeypatch.setattr(mod.os, "geteuid", lambda: 501)
    with pytest.raises(RuntimeError, match="administrator/root required"):
        mod._root_stage()


def test_upgrade_config_preserves_frozen_seeds():
    mod = _upgrade_module()
    for phase, arm, index, seed in (("smoke", "B1", 7, 7),
                                    ("paired", "B2", 0, 20261117),
                                    ("paired", "B1", 29, 20261146)):
        trial, raw = mod._config(phase, arm, index)
        assert trial["seed"] == seed
        assert json.loads(raw)["experiment_id"] == "M1-SIM-002"
    for phase, arm, index in (("paired", "B1", 30), ("smoke", "B2", 10),
                              ("paired", "B3", 0), ("paired", "B1", True)):
        with pytest.raises(RuntimeError):
            mod._config(phase, arm, index)
    trial, raw = mod._config("smoke", "B2", 5, "M1-SIM-003")
    assert trial["seed"] == 5
    assert json.loads(raw)["experiment_id"] == "M1-SIM-003"
    with pytest.raises(RuntimeError, match="unknown frozen"):
        mod._config("smoke", "B2", 5, "M1-SIM-004")


def test_root_refresh_rejects_wrong_experiment_before_any_host_side_effect(monkeypatch):
    mod = _upgrade_module()
    monkeypatch.setattr(mod, "_root_stage", lambda: None)
    calls = []
    monkeypatch.setattr(mod, "_current", lambda *_a, **_k: calls.append("current"))
    trial, config = mod._config("smoke", "B2", 5)
    with pytest.raises(RuntimeError, match="M1-SIM-003"):
        mod._refresh_bundle(Path("/not-installed"), "a" * 64, "b" * 32, trial, config)
    paired, paired_config = mod._config("paired", "B2", 0, "M1-SIM-003")
    with pytest.raises(RuntimeError, match="engineering smoke"):
        mod._refresh_bundle(Path("/not-installed"), "a" * 64, "b" * 32,
                            paired, paired_config)
    assert calls == []


def test_refresh_failed_seatbelt_probe_restores_original_without_restart(tmp_path, monkeypatch):
    mod = _upgrade_module()
    stage, root = tmp_path / "stage", tmp_path / "root"
    stage.mkdir()
    root.mkdir()
    old_target = root / ("lfl-m1-oracle-v2-" + "a" * 12)
    old_target.mkdir()
    old_trial = {"phase": "smoke", "arm": "B2", "trial_index": 6, "seed": 6}
    old_config = {"schema": "lfl.m1-oracle-host-trial/v1",
                  "experiment_id": "M1-SIM-002", "trial": old_trial}
    config_path, public = tmp_path / "trial.json", tmp_path / "public.key"
    config_path.write_text(json.dumps(old_config))
    public.write_bytes(b"public-only")
    monkeypatch.setattr(mod, "ROOT", root)
    monkeypatch.setattr(mod, "STAGE", stage)
    monkeypatch.setattr(mod, "TRIAL_CONFIG", config_path)
    monkeypatch.setattr(mod, "PUBLIC", public)
    monkeypatch.setattr(mod, "_root_stage", lambda: None)
    monkeypatch.setattr(mod, "_trusted", lambda *_a, **_k: True)
    monkeypatch.setattr(mod, "_current", lambda *_a, **_k:
                        {"run_id": "a" * 32, "pid": 123, "trial": old_trial})
    monkeypatch.setattr(mod, "_plist", lambda: (
        {"WorkingDirectory": str(old_target),
         "ProgramArguments": ["/usr/bin/sandbox-exec",
                              str(old_target / "m1_oracle_host_service.py")]},
        b"plist"))
    monkeypatch.setattr(mod, "_manifest", lambda *_a: {})
    monkeypatch.setattr(mod, "_install", lambda *_a: root / "new-v2-bundle")
    monkeypatch.setattr(mod, "_atomic", lambda path, raw, mode=0o644:
                        path.write_bytes(raw))
    monkeypatch.setattr(mod.subprocess, "run", lambda *_a, **_k:
                        SimpleNamespace(returncode=1, stdout=""))
    restarts = []
    monkeypatch.setattr(mod, "_launch", lambda *_a: restarts.append(True))
    trial, config = mod._config("smoke", "B2", 5, "M1-SIM-003")
    with pytest.raises(RuntimeError, match="Seatbelt Host probe"):
        mod._refresh_bundle(root / "candidate", "b" * 64, "a" * 32, trial, config)
    assert json.loads(config_path.read_text()) == old_config
    assert restarts == []


def _batch_plan(mod, tmp_path):
    now = datetime.now(UTC)
    return {
        "schema": "lfl.m1-paired-cost-grant/v1", "batch_id": "b" * 32,
        "experiment_id": "M1-SIM-003", "prereg_sha256": mod.PREREG_SHA256,
        "candidate_sha": "c" * 40, "model": "deepseek/deepseek-v4-flash",
        "currency": "USD", "max_episodes": 60, "max_provider_attempts": 360,
        "max_tool_actions": 480, "max_total_usd": "1.00",
        "reserve_per_call_usd": "0.01", "input_per_million_usd": "1",
        "output_per_million_usd": "2", "pricing_source": "approved provider tariff",
        "pricing_checked_at_utc": (now - timedelta(minutes=1)).isoformat(),
        "expires_at_utc": (now + timedelta(hours=1)).isoformat(),
        "ledger_path": str(mod.PAIRED_LEDGER),
    }


def test_root_batch_plan_matches_client_schema_and_rejects_drift(tmp_path):
    mod = _upgrade_module()
    plan = _batch_plan(mod, tmp_path)
    frozen = ROOT / "experiments/embodied/prereg-m1-sim-003.json"
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == mod.PREREG_SHA256
    assert json.loads(frozen.read_text())["model_required"] == mod.PAIRED_MODEL
    assert hashlib.sha256(
        (ROOT / "experiments/embodied/prereg-m1-sim-002.json").read_bytes()
    ).hexdigest() == "e4aefedd413874c547c6ab01aebb8c2019491b07b1a887bf7266621fa0c1b5ae"
    assert mod.BATCH_REQUIRED == REQUIRED
    assert mod.BATCH_USD_LIMIT == BATCH_USD_LIMIT
    assert mod.CALL_RESERVE_USD_LIMIT == CALL_RESERVE_USD_LIMIT
    mod._validate_batch_plan(plan)
    mod._validate_batch_plan(
        {**plan, "max_total_usd": "20.00", "reserve_per_call_usd": "0.05",
         "input_per_million_usd": "0.30", "output_per_million_usd": "1.20"})
    for key, bad in (("max_episodes", 61), ("max_provider_attempts", 361),
                     ("max_tool_actions", 481), ("model", "another"),
                     ("max_total_usd", "NaN"), ("ledger_path", "/tmp/elsewhere"),
                     ("max_total_usd", "20.01"), ("reserve_per_call_usd", "0.05000001"),
                     ("input_per_million_usd", "0.299"),
                     ("output_per_million_usd", "1.199"),
                     ("prereg_sha256", "0" * 64)):
        with pytest.raises(RuntimeError):
            mod._validate_batch_plan({**plan, key: bad})
    with pytest.raises(RuntimeError):
        mod._validate_batch_plan({**plan, "extra": True})


def test_batch_authorization_is_separate_and_refuses_reissue(tmp_path, monkeypatch):
    mod = _upgrade_module()
    stage, etc, parent = (tmp_path / name for name in ("stage", "etc", "var"))
    for directory in (stage, etc, parent):
        directory.mkdir()
    monkeypatch.setattr(mod, "STAGE", stage)
    monkeypatch.setattr(mod, "PAIRED_GRANT", etc / "grant.json")
    monkeypatch.setattr(mod, "PAIRED_ISSUED", stage / "issued.jsonl")
    monkeypatch.setattr(mod, "PAIRED_LEDGER_DIR", parent / "budget")
    monkeypatch.setattr(mod, "PAIRED_LEDGER", parent / "budget/m1-paired-cost-ledger.jsonl")
    monkeypatch.setattr(mod, "_root_stage", lambda: None)
    monkeypatch.setattr(mod, "_current", lambda *_a, **_k:
                        {"trial": {"phase": "smoke", "arm": "B2"}})
    monkeypatch.setattr(mod, "_trusted", lambda *_a, **_k: True)
    monkeypatch.setattr(mod, "_atomic", lambda path, data, mode=0o644:
                        path.write_bytes(data))
    monkeypatch.setattr(mod.os, "fchown", lambda *_a: None)
    monkeypatch.setenv("SUDO_UID", "501")
    raw = json.dumps(_batch_plan(mod, tmp_path)).encode()
    plan_file = stage / "plan.json"
    plan_file.write_bytes(raw)
    result = mod._authorize_batch("a" * 32, plan_file, hashlib.sha256(raw).hexdigest())
    assert result["HOST_BATCH_AUTH"] == "READY_NOT_STARTED"
    assert mod.PAIRED_GRANT.read_bytes() == raw
    assert mod.PAIRED_ISSUED.exists() and mod.PAIRED_LEDGER.exists()
    with pytest.raises(RuntimeError, match="already exists"):
        mod._authorize_batch("a" * 32, plan_file, hashlib.sha256(raw).hexdigest())


def test_paired_switch_refuses_missing_grant_without_host_restart(monkeypatch):
    mod = _upgrade_module()
    switched = []
    monkeypatch.setattr(mod, "_switch_host_only", lambda *_a:
                        switched.append(True) or {"HOST_TRIAL_SWITCH": "PASS"})

    @contextmanager
    def no_grant(*_a):
        raise RuntimeError("independent paired Host grant not installed")
        yield  # pragma: no cover

    monkeypatch.setattr(mod, "_paired_issue", no_grant)
    trial, config = mod._config("paired", "B2", 0, "M1-SIM-003")
    with pytest.raises(RuntimeError, match="grant"):
        mod._switch("a" * 32, trial, config)
    assert switched == []
    smoke, smoke_config = mod._config("smoke", "B2", 7)
    assert mod._switch("a" * 32, smoke, smoke_config)["HOST_TRIAL_SWITCH"] == "PASS"
    assert switched == [True]


def test_root_paired_issue_is_one_time_per_arm_and_index(tmp_path, monkeypatch):
    mod = _upgrade_module()
    grant = tmp_path / "grant.json"
    issued = tmp_path / "issued.jsonl"
    ledger = tmp_path / "m1-paired-cost-ledger.jsonl"
    monkeypatch.setattr(mod, "PAIRED_GRANT", grant)
    monkeypatch.setattr(mod, "PAIRED_ISSUED", issued)
    monkeypatch.setattr(mod, "PAIRED_LEDGER_DIR", tmp_path)
    monkeypatch.setattr(mod, "PAIRED_LEDGER", ledger)
    monkeypatch.setattr(mod, "_root_stage", lambda: None)
    monkeypatch.setattr(mod, "_current", lambda *_a, **_k: {})
    monkeypatch.setattr(mod, "_trusted", lambda *_a, **_k: True)
    monkeypatch.setenv("SUDO_UID", str(os.getuid()))
    grant.write_text(json.dumps(_batch_plan(mod, tmp_path)))
    issued.write_text("")
    ledger.write_text("")
    issued.chmod(0o600)
    ledger.chmod(0o600)
    trial, _ = mod._config("paired", "B2", 0, "M1-SIM-003")
    with mod._paired_issue("a" * 32, trial):
        pass
    with pytest.raises(RuntimeError, match="replay"), mod._paired_issue("a" * 32, trial):
        pass
    another, _ = mod._config("paired", "B1", 0, "M1-SIM-003")
    with mod._paired_issue("a" * 32, another):
        pass
    assert len(issued.read_text().splitlines()) == 2
    grant_sha = hashlib.sha256(grant.read_bytes()).hexdigest()
    issued.write_text("".join(
        json.dumps({"grant_sha256": grant_sha, "arm": "historical",
                    "trial_index": i}) + "\n" for i in range(60)))
    third, _ = mod._config("paired", "B2", 1, "M1-SIM-003")
    with pytest.raises(RuntimeError, match="batch cap"), mod._paired_issue("a" * 32, third):
        pass


def test_upgrade_plist_rewrites_only_m1_service():
    mod = _upgrade_module()
    old = {"Label": mod.LABEL, "UserName": "_lfl_oracle",
           "GroupName": "_lfl_oracle", "KeepAlive": True,
           "RunAtLoad": True, "EnvironmentVariables": {"HOME": "/var/empty"},
           "ProgramArguments": ["/usr/bin/sandbox-exec", "-f", str(mod.OLD / "oracle.sb")],
           "WorkingDirectory": str(mod.OLD)}
    target = mod.ROOT / ("lfl-m1-oracle-v2-" + "a" * 12)
    new = plistlib.loads(mod._new_plist(old, target))
    assert new["Label"] == mod.LABEL
    assert new["UserName"] == old["UserName"]
    assert new["EnvironmentVariables"] == old["EnvironmentVariables"]
    assert new["ProgramArguments"][-1] == "--serve"
    assert new["ProgramArguments"][-2] == str(target / "m1_oracle_host_service.py")
    assert new["WorkingDirectory"] == str(target)


def test_upgrade_manifest_is_exact_and_rejects_tampering(tmp_path, monkeypatch):
    mod = _upgrade_module()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "file.py").write_text("a=1\n")
    info = {"schema": "lfl.m1-oracle-host-bundle/v1", "python": "3.13.16",
            "architecture": "arm64", "git_head": "a" * 40,
            "files": {"file.py": hashlib.sha256((bundle / "file.py").read_bytes()).hexdigest()}}
    raw = json.dumps(info).encode()
    (bundle / "manifest.json").write_bytes(raw)
    monkeypatch.setattr(mod, "_trusted", lambda *_a, **_k: True)
    assert mod._manifest(bundle, hashlib.sha256(raw).hexdigest())["files"] == info["files"]
    (bundle / "file.py").write_text("a=2\n")
    with pytest.raises(RuntimeError, match="content mismatch"):
        mod._manifest(bundle, hashlib.sha256(raw).hexdigest())


def test_failed_uid463_probe_leaves_v1_running(tmp_path, monkeypatch):
    mod = _upgrade_module()
    stage = tmp_path / "stage"
    stage.mkdir()
    pub = tmp_path / "pub"
    pub.write_bytes(b"existing-public-key")
    config_path = tmp_path / "trial.json"
    monkeypatch.setattr(mod, "STAGE", stage)
    monkeypatch.setattr(mod, "PUBLIC", pub)
    monkeypatch.setattr(mod, "TRIAL_CONFIG", config_path)
    monkeypatch.setattr(mod, "_root_stage", lambda: None)
    monkeypatch.setattr(mod, "_current", lambda *_a, **_k: {"run_id": "a" * 32})
    old = {"ProgramArguments": [str(mod.OLD / "m1_oracle_host_service.py")]}
    monkeypatch.setattr(mod, "_plist", lambda: (old, b"old-plist"))
    monkeypatch.setattr(mod, "_manifest", lambda *_a: {})
    monkeypatch.setattr(mod, "_install", lambda *_a: tmp_path / "v2")
    monkeypatch.setattr(mod, "_atomic", lambda path, data, mode=0o644: path.write_bytes(data))
    monkeypatch.setattr(mod.subprocess, "run", lambda *_a, **_k:
                        SimpleNamespace(returncode=77, stdout=""))
    launches = []
    monkeypatch.setattr(mod, "_launch", lambda *args: launches.append(args))
    trial, config = mod._config("smoke", "B1", 7)
    with pytest.raises(RuntimeError, match="trial probe failed"):
        mod._upgrade(tmp_path / "bundle", "a" * 64, "a" * 32, trial, config)
    assert launches == []
    assert not config_path.exists()
    assert (stage / "old.plist").read_bytes() == b"old-plist"


def test_failed_v2_bootstrap_restores_v1_plist_and_trial_config(tmp_path, monkeypatch):
    mod = _upgrade_module()
    stage = tmp_path / "stage"
    stage.mkdir()
    pub = tmp_path / "pub"
    pub.write_bytes(b"existing-public-key")
    config_path = tmp_path / "trial.json"
    plist_path = tmp_path / "launchd.plist"
    original = b"old-plist-bytes"
    plist_path.write_bytes(original)
    monkeypatch.setattr(mod, "STAGE", stage)
    monkeypatch.setattr(mod, "PUBLIC", pub)
    monkeypatch.setattr(mod, "PLIST", plist_path)
    monkeypatch.setattr(mod, "TRIAL_CONFIG", config_path)
    monkeypatch.setattr(mod, "_root_stage", lambda: None)
    monkeypatch.setattr(mod, "_current", lambda *_a, **_k: {"run_id": "a" * 32})
    old = {"ProgramArguments": [str(mod.OLD / "m1_oracle_host_service.py")]}
    monkeypatch.setattr(mod, "_plist", lambda: (old, original))
    monkeypatch.setattr(mod, "_manifest", lambda *_a: {})
    monkeypatch.setattr(mod, "_install", lambda *_a: tmp_path / "v2")
    monkeypatch.setattr(mod, "_atomic", lambda path, data, mode=0o644: path.write_bytes(data))
    trial, config = mod._config("smoke", "B2", 7)
    monkeypatch.setattr(mod.subprocess, "run", lambda *_a, **_k:
                        SimpleNamespace(returncode=0, stdout=json.dumps({"uid": 463, "trial": trial})))
    launches = []

    def launch(*args):
        launches.append(args)
        if args[0] == "bootstrap" and launches.count(args) == 1:
            raise RuntimeError("simulated new Host bootstrap failure")

    monkeypatch.setattr(mod, "_launch", launch)
    monkeypatch.setattr(mod, "_health", lambda *_a: {"run_id": "b" * 32})
    with pytest.raises(RuntimeError, match="bootstrap failure"):
        mod._upgrade(tmp_path / "bundle", "a" * 64, "a" * 32, trial, config)
    assert plist_path.read_bytes() == original
    assert not config_path.exists()
    assert launches[0][0] == "bootout"
    assert launches[-1][0] == "bootstrap"

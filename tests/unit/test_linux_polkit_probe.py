"""Rootless tests for the *uninstalled* Deepin exact Polkit canary helper."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/linux/lfl_task_host_probe.py"
POLICY = ROOT / "packaging/linux/org.llmfirstloop.task-host-probe.policy"


def _load():
    spec = importlib.util.spec_from_file_location("lfl_task_host_probe_test", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_policy_exact_action_and_no_ambient_authorization():
    root = ET.parse(POLICY).getroot()
    actions = root.findall("action")
    assert len(actions) == 1
    action = actions[0]
    assert action.get("id") == "org.llmfirstloop.task-host-probe.attest"
    defaults = action.find("defaults")
    assert defaults is not None
    assert defaults.findtext("allow_any") == "no"
    assert defaults.findtext("allow_inactive") == "no"
    assert defaults.findtext("allow_active") == "auth_admin"
    assert action.findtext("annotate[@key='org.freedesktop.policykit.exec.path']") == (
        "/usr/local/libexec/lfl-task-host-probe"
    )
    assert "auth_admin_keep" not in POLICY.read_text()
    assert HELPER.read_text().startswith("#!/usr/bin/python3 -I")


def test_helper_only_one_root_owned_fixed_directory_and_no_shell():
    module = _load()
    assert str(module.RECEIPT_DIR) == "/var/lib/lfl-task-host-probe/receipts"
    source = HELPER.read_text()
    for forbidden in ("subprocess", "os.system(", "os.exec", "shell=True", "shutil.rmtree", "eval("):
        assert forbidden not in source
    assert "PKEXEC_UID" in source
    assert "O_EXCL" in source and "O_NOFOLLOW" in source


def test_rootless_private_dir_exact_receipt_and_replay_deny(tmp_path):
    module = _load()
    directory = tmp_path / "receipts"
    directory.mkdir(mode=0o700)
    challenge = "a" * 32
    digest = module._write_attestation(
        challenge, 1000, directory=directory, expected_owner=os.getuid(),
    )
    files = list(directory.iterdir())
    assert files == [directory / (challenge + ".json")]
    content = files[0].read_bytes()
    import hashlib
    assert hashlib.sha256(content).hexdigest() == digest
    assert files[0].stat().st_mode & 0o777 == 0o600
    data = json.loads(content)
    assert data["challenge"] == challenge and data["requester_uid"] == 1000
    assert data["effect"] == "polkit_root_receipt_only"
    assert data["signed_task_lease"] is False
    with pytest.raises(FileExistsError):
        module._write_attestation(
            challenge, 1000, directory=directory, expected_owner=os.getuid(),
        )
    assert files[0].read_bytes() == content


@pytest.mark.parametrize("challenge", ["../etc/passwd", "A"*32, "f"*31, "f"*33, "00/abc", ""])
def test_challenge_rejects_traversal_and_nonexact_hex(tmp_path, challenge):
    module = _load()
    directory = tmp_path / "receipts"
    directory.mkdir(mode=0o700)
    with pytest.raises(module.ProbeDeniedError):
        module._write_attestation(
            challenge, 1000, directory=directory, expected_owner=os.getuid(),
        )
    assert list(directory.iterdir()) == []


def test_private_dir_symlink_and_world_writable_fail_closed(tmp_path):
    module = _load()
    directory = tmp_path / "receipts"
    directory.mkdir(mode=0o700)
    link = tmp_path / "redirect"
    link.symlink_to(directory, target_is_directory=True)
    with pytest.raises(module.ProbeDeniedError):
        module._write_attestation(
            "b"*32, 1000, directory=link, expected_owner=os.getuid(),
        )
    directory.chmod(0o777)
    try:
        with pytest.raises(module.ProbeDeniedError):
            module._write_attestation(
                "b"*32, 1000, directory=directory, expected_owner=os.getuid(),
            )
    finally:
        directory.chmod(0o700)
    assert list(directory.iterdir()) == []


@pytest.mark.parametrize("args", [
    [], ["attest"], ["attest", "a"*32, "/tmp/other"],
    ["write", "a"*32], ["attest", "../etc/shadow"],
])
def test_main_rejects_other_operations_and_paths(monkeypatch, args):
    module = _load()
    called = []
    monkeypatch.setattr(module, "_write_attestation", lambda *a, **kw: called.append(a))
    assert module.main(args) == 77
    assert called == []


def test_main_requires_root_pkexec_original_uid(monkeypatch):
    module = _load()
    called = []
    monkeypatch.setattr(module, "_write_attestation", lambda *a, **kw: called.append(a))
    monkeypatch.setenv("PKEXEC_UID", "1000")
    monkeypatch.setattr(module.os, "geteuid", lambda: 1000)
    assert module.main(["attest", "a"*32]) == 77
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.os, "getuid", lambda: 0)
    for uid in ("", "0", "501", "not-a-number", "-1"):
        monkeypatch.setenv("PKEXEC_UID", uid)
        assert module.main(["attest", "a"*32]) == 77
    assert called == []


def test_main_one_operation_and_no_environment_path_override(monkeypatch, capsys):
    module = _load()
    calls = []
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.os, "getuid", lambda: 0)
    monkeypatch.setenv("PKEXEC_UID", "1000")
    monkeypatch.setenv("LFL_TASK_HOST_PROBE_DIR", "/tmp/attacker")
    monkeypatch.setattr(
        module, "_write_attestation",
        lambda challenge, uid: calls.append((challenge, uid)) or "c"*64,
    )
    assert module.main(["attest", "a"*32]) == 0
    assert calls == [("a"*32, 1000)]
    response = json.loads(capsys.readouterr().out)
    assert response["result"] == "POLKIT_ROOT_RECEIPT_WRITTEN"
    assert response["signed_task_lease"] is False
    assert Path("/var/lib/lfl-task-host-probe/receipts") == module.RECEIPT_DIR

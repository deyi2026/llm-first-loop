"""Rootless tests for the *uninstalled* Deepin exact Polkit canary helper."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/linux/lfl_task_host_probe.py"
POLICY = ROOT / "packaging/linux/org.llmfirstloop.task-host-probe.policy"


@pytest.fixture
def trusted_tmp_path(tmp_path):
    """Positive rootless canary needs trusted ancestors, never Linux /tmp (1777).

    Production helper deliberately rejects writable ancestors. GitHub Linux
    pytest tmp_path is under /tmp; Mac's system pytest temp root is private.
    Use an ignored 0700 pytest-cache test root on Linux, and remove the
    per-test directory afterward without weakening the Host security check.
    """
    if sys.platform != "linux":
        yield tmp_path
        return
    cache = ROOT / ".pytest_cache"
    assert not cache.is_symlink(), "test cache root must not be a symlink"
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    # GitHub Linux checkout may have umask 0002: tighten only the ignored
    # pytest cache, never user data/ or the production root-chain guard.
    cache.chmod(0o700)
    base = cache / "polkit-rootless-tests"
    assert not base.is_symlink(), "test receipt root must not be a symlink"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    base.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix="case-", dir=base) as directory:
        yield Path(directory)


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


def test_rootless_private_dir_exact_receipt_and_replay_deny(trusted_tmp_path):
    module = _load()
    directory = trusted_tmp_path / "receipts"
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
def test_challenge_rejects_traversal_and_nonexact_hex(trusted_tmp_path, challenge):
    module = _load()
    directory = trusted_tmp_path / "receipts"
    directory.mkdir(mode=0o700)
    with pytest.raises(module.ProbeDeniedError):
        module._write_attestation(
            challenge, 1000, directory=directory, expected_owner=os.getuid(),
        )
    assert list(directory.iterdir()) == []


def test_private_dir_symlink_and_world_writable_fail_closed(trusted_tmp_path):
    module = _load()
    directory = trusted_tmp_path / "receipts"
    directory.mkdir(mode=0o700)
    link = trusted_tmp_path / "redirect"
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


def test_rootless_receipt_limit_is_bounded_and_no_new_file(trusted_tmp_path):
    module = _load()
    directory = trusted_tmp_path / "receipts"
    directory.mkdir(mode=0o700)
    for i in range(module.MAX_RECEIPTS):
        (directory / f"{i:032x}.json").write_text("{}")
    with pytest.raises(module.ProbeDeniedError, match="receipt_limit_reached"):
        module._write_attestation(
            "f"*32, 1000, directory=directory, expected_owner=os.getuid(),
        )
    assert len(list(directory.iterdir())) == module.MAX_RECEIPTS


@pytest.mark.skipif(sys.platform != "linux", reason="Linux /tmp ancestor is the CI-specific denial")
def test_linux_world_writable_tmp_ancestor_stays_denied(tmp_path):
    """Do not relax the root-chain guard merely to make Linux CI tests pass."""
    module = _load()
    if not any(
        (parent.stat().st_mode & 0o002) != 0
        for parent in (tmp_path, *tmp_path.parents)
    ):
        pytest.skip("pytest temp root has no world-writable ancestor")
    directory = tmp_path / "receipts"
    directory.mkdir(mode=0o700)
    with pytest.raises(module.ProbeDeniedError, match="unsafe_receipt_directory"):
        module._write_attestation(
            "b" * 32, 1000, directory=directory, expected_owner=os.getuid(),
        )
    assert list(directory.iterdir()) == []

# Deepin25 /usr is immutable. A root-owned /etc/polkit-1/rules.d rule scopes
# the existing built-in pkexec action to the exact canary program instead.
ETC_RULE = ROOT / "packaging/linux/00-lfl-task-host-probe.rules"
ETC_RUNNER = ROOT / "scripts/linux/lfl_task_host_probe_etc_one_shot.sh"


def test_deepin_etc_rule_is_exact_scoped_admin_not_keep():
    source = ETC_RULE.read_text(encoding="utf-8")
    assert 'action.id !== "org.freedesktop.policykit.exec"' in source
    assert 'action.lookup("program") !== "/usr/local/libexec/lfl-task-host-probe"' in source
    assert 'action.lookup("user") !== "root"' in source
    assert 'subject.local !== true' in source
    assert 'subject.active !== true' in source
    assert 'subject.seat !== "seat0"' in source
    assert "return polkit.Result.NO;" in source
    assert "return polkit.Result.NOT_HANDLED;" in source
    assert "return polkit.Result.AUTH_ADMIN;" in source
    assert "polkit.Result.YES" not in source
    assert "return polkit.Result.AUTH_ADMIN_KEEP;" not in source
    assert "polkit.spawn" not in source


def test_deepin_etc_rule_dynamic_authorization_matrix():
    """Execute the real rule in a tiny polkit mock, never invoke OS pkexec."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable; static /etc Polkit rule guards still checked")
    program = r"""
const fs = require('node:fs');
const vm = require('node:vm');
let rule;
const polkit = {
    Result: {NOT_HANDLED: null, NO: 'no', AUTH_ADMIN: 'auth_admin'},
    addRule(fn) { if (rule) throw Error('duplicate rule'); rule = fn; }
};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {polkit}, {timeout: 1000});
if (typeof rule !== 'function') throw Error('missing rule');
function action(program, user = 'root', id = 'org.freedesktop.policykit.exec') {
    return {id, lookup(key) { return ({program, user})[key]; }};
}
function subject(local, active, seat) { return {local, active, seat}; }
const helper = '/usr/local/libexec/lfl-task-host-probe';
const tests = [
    [action(helper), subject(true, true, 'seat0'), 'auth_admin'],
    [action(helper), subject(false, true, ''), 'no'],
    [action(helper), subject(true, false, 'seat0'), 'no'],
    [action(helper), subject(true, true, 'seat1'), 'no'],
    [action(helper), subject(true, true, undefined), 'no'],
    [action(helper, 'other'), subject(true, true, 'seat0'), 'no'],
    [action('/usr/bin/id'), subject(true, true, 'seat0'), null],
    [action(undefined), subject(true, true, 'seat0'), null],
    [action(helper, 'root', 'org.example.other'), subject(true, true, 'seat0'), null],
    [action(helper), {}, 'no'],
];
for (const [a, s, expected] of tests) {
    const result = rule(a, s);
    if (result !== expected) throw Error('unexpected policy decision: ' + result + ' != ' + expected);
}
console.log('DEEPIN_ETC_POLKIT_DYNAMIC_MATRIX_PASS ' + tests.length);
"""
    completed = subprocess.run(
        [node, "-e", program, str(ETC_RULE)],
        capture_output=True, text=True, timeout=8, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "DYNAMIC_MATRIX_PASS 10" in completed.stdout


def test_deepin_etc_runner_never_remounts_or_restarts_and_has_cleanup():
    import hashlib
    import shutil
    import subprocess

    script = ETC_RUNNER.read_text(encoding="utf-8")
    assert "--check|--run|--cleanup" in script
    assert "/etc/polkit-1/rules.d/00-lfl-task-host-probe.rules" in script
    assert "/usr/local/libexec/lfl-task-host-probe" in script
    assert "/usr/share/polkit-1/actions/org.llmfirstloop.task-host-probe.policy" in script
    assert "sudo install" in script and "sudo rm -f" in script
    assert "trap cleanup EXIT" in script
    assert "DEEPIN_ETC_POLKIT_EXACT_CLEANUP_PASS" in script
    assert "unexpected content at $target, refusing removal" in script
    assert "XDG_SESSION_ID" in script and "loginctl show-session" in script
    assert "Seat=seat0" in script and "Remote=no" in script and "Active=yes" in script
    assert "replay_rc" in script and "unprivileged_rc" in script
    assert "signed_task_lease=false" in script
    assert "remote_ssh=not_yet_verified" in script
    for forbidden in ("deepin-immutable-writable", "mount -o", "systemctl restart", "service restart", "sudo bash", "sudo sh -c"):
        assert forbidden not in script
    assert "HELPER_SHA='" + hashlib.sha256(HELPER.read_bytes()).hexdigest() + "'" in script
    assert "RULE_SHA='" + hashlib.sha256(ETC_RULE.read_bytes()).hexdigest() + "'" in script
    bash = shutil.which("bash")
    if bash:
        checked = subprocess.run([bash, "-n", str(ETC_RUNNER)], capture_output=True, text=True, timeout=8)
        assert checked.returncode == 0, checked.stderr

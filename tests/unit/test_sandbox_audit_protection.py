"""P0-3: shell sandbox cannot mutate trusted audit state through writable workspace.

All runtime probes use disposable test files. No production audit ledger is touched.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import UTC
from pathlib import Path
from unittest.mock import patch

import pytest

from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.sandbox import (
    bwrap_argv,
    docker_argv,
    sandbox_argv,
    sandbox_exec_available,
)


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    ws = tmp_path / "ws"
    audit = ws / "data" / "audit"
    audit.mkdir(parents=True)
    ledger = audit / "goals.jsonl"
    ledger.write_text("original\n")
    return ws, audit, ledger


def test_macos_profile_denies_audit_and_parent_rename(tmp_path):
    ws, audit, _ = _workspace(tmp_path)
    with patch("llm_loop.tools.sandbox._probe_sandbox_exec", return_value=True):
        argv, _ = sandbox_argv(
            "true", str(ws), mode="sandbox-exec", protected_roots=[str(audit)]
        )
    assert argv is not None
    profile = argv[2]
    assert f'(deny file-write* (subpath "{audit}"))' in profile
    assert f'(deny file-write* (literal "{audit.parent}"))' in profile
    assert f'(deny file-write* (literal "{ws}"))' in profile
    assert profile.rindex('(deny file-write*') > profile.rindex('(allow file-write*')


def test_macos_real_direct_symlink_parent_rename_and_normal_write(tmp_path):
    if sys.platform != "darwin" or not sandbox_exec_available():
        pytest.skip("real macOS sandbox-exec unavailable")
    ws, audit, ledger = _workspace(tmp_path)
    (ws / "alias").symlink_to(audit, target_is_directory=True)
    cases = [
        ("direct", "printf BAD >> data/audit/goals.jsonl", False),
        ("symlink", "printf BAD >> alias/goals.jsonl", False),
        ("rename_parent", "mv data moved && printf BAD >> moved/audit/goals.jsonl", False),
        ("hardlink_create", "ln data/audit/goals.jsonl outside_alias", False),
        ("normal", "printf OK > business.txt", True),
    ]
    for name, command, should_succeed in cases:
        argv, _ = sandbox_argv(
            command, str(ws), mode="sandbox-exec", protected_roots=[str(audit)]
        )
        result = subprocess.run(argv, cwd=ws, capture_output=True, text=True, timeout=12)
        assert (result.returncode == 0) == should_succeed, (name, result.stderr)
        assert ledger.read_text() == "original\n", name
    assert (ws / "business.txt").read_text() == "OK"


def test_preexisting_hardlink_blocks_sandbox_launch(tmp_path):
    ws, audit, ledger = _workspace(tmp_path)
    (ws / "alias.jsonl").hardlink_to(ledger)
    with pytest.raises(RuntimeError, match="hardlink"):
        sandbox_argv("true", str(ws), mode="sandbox-exec", protected_roots=[str(audit)])


def test_symlink_inside_audit_blocks_sandbox_launch(tmp_path):
    ws, audit, _ = _workspace(tmp_path)
    (audit / "goals.jsonl").unlink()
    (audit / "goals.jsonl").symlink_to(ws / "business.txt")
    with pytest.raises(RuntimeError, match="symlink"):
        sandbox_argv("true", str(ws), mode="bwrap", protected_roots=[str(audit)])


def test_bwrap_ro_overlay_after_rw_workspace(tmp_path):
    ws, audit, _ = _workspace(tmp_path)
    argv = bwrap_argv("true", str(ws), protected_roots=[str(audit)])
    rw = argv.index("--bind")
    parent = argv.index("--bind", rw + 1)
    ro = argv.index("--ro-bind", parent + 1)
    assert argv[rw + 1 : rw + 3] == [str(ws), str(ws)]
    assert argv[parent + 1 : parent + 3] == [str(audit.parent), str(audit.parent)]
    assert argv[ro + 1 : ro + 3] == [str(audit), str(audit)]
    assert argv[-3:] == ["/bin/sh", "-c", "true"]


def test_bwrap_real_audit_denied_normal_file_allowed(tmp_path):
    if not shutil.which("bwrap") or sys.platform != "linux":
        pytest.skip("real bwrap unavailable on this host")
    ws, audit, ledger = _workspace(tmp_path)
    commands = [
        "printf BAD >> data/audit/goals.jsonl",
        "mv data moved && printf BAD >> moved/audit/goals.jsonl",
        "ln data/audit/goals.jsonl alias.jsonl",
        "printf OK > data/sibling.txt",
    ]
    for command in commands:
        argv = bwrap_argv(command, str(ws), protected_roots=[str(audit)])
        p = subprocess.run(argv, cwd=ws, capture_output=True, text=True, timeout=15)
        if "Operation not permitted" in p.stderr and "bwrap:" in p.stderr:
            pytest.skip("outer container blocks Linux user namespaces")
        assert (p.returncode == 0) == command.startswith("printf OK"), (command, p.stderr)
        assert ledger.read_text() == "original\n"
    assert (ws / "data" / "sibling.txt").read_text() == "OK"


def test_docker_readonly_overlay_after_workspace_mount(tmp_path):
    ws, audit, _ = _workspace(tmp_path)
    argv = docker_argv("true", str(ws), protected_roots=[str(audit)])
    rw_index = argv.index("--volume")
    ro_index = argv.index("--mount")
    assert ro_index > rw_index
    assert argv[ro_index + 1] == f"type=bind,source={audit.parent},target={audit.parent}"
    assert argv[ro_index + 3] == f"type=bind,source={audit},target={audit},readonly"


def test_outside_audit_not_mounted_into_bwrap_or_docker(tmp_path):
    ws, _audit, _ledger = _workspace(tmp_path)
    outside = tmp_path / "outside-audit"
    outside.mkdir()
    (outside / "goals.jsonl").write_text("secret")
    b = bwrap_argv("true", str(ws), protected_roots=[str(outside)])
    d = docker_argv("true", str(ws), protected_roots=[str(outside)])
    assert str(outside) not in b
    assert not any(str(outside) in x for x in d)


def test_grant_cannot_rebind_protected_audit_file(tmp_path):
    ws, audit, ledger = _workspace(tmp_path)
    with pytest.raises(RuntimeError, match="protected audit"):
        sandbox_argv(
            "true",
            str(ws),
            mode="bwrap",
            protected_roots=[str(audit)],
            extra_file_binds=[(str(ledger), str(ledger), "rw")],
        )


def test_execute_command_propagates_trusted_audit_dir(tmp_path):
    ws, audit, _ = _workspace(tmp_path)
    with (
        patch("llm_loop.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap"),
        patch("subprocess.Popen") as popen,
    ):
        fake = popen.return_value
        fake.communicate.return_value = ("ok", "")
        fake.returncode = 0
        result = ExecuteCommandTool(
            sandbox_mode="bwrap", safety_audit_dir=audit
        ).execute(command="echo ok", workdir=str(ws))
    assert result.status.value == "success", result.content
    argv = popen.call_args.args[0]
    assert any(argv[i:i + 3] == ["--ro-bind", str(audit), str(audit)] for i in range(len(argv) - 2))


def test_host_grant_audit_target_rejected_before_consumption(tmp_path):
    from datetime import datetime, timedelta
    from unittest.mock import MagicMock

    from llm_loop.core.run_context import current_session_id

    ws, audit, ledger = _workspace(tmp_path)
    store = MagicMock()
    store.peek.return_value = {
        "status": "approved",
        "uses": 0,
        "max_uses": 1,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        "tool_name": "execute_command",
        "requester_session_id": "owner",
        "operation": "write",
        "canonical_path": str(ledger),
        "request_binding": {
            "command_sha256": "not-current",
            "cwd": str(ws),
            "file_sha256": "not-current",
        },
    }
    tool = ExecuteCommandTool(sandbox_mode="bwrap", safety_audit_dir=audit)
    token = current_session_id.set("owner")
    try:
        with patch.object(tool, "_host_grant_store", return_value=store):
            _ctx, error = tool._resolve_host_grant(
                "fake-but-signed", "printf X > data/audit/goals.jsonl", str(ws)
            )
    finally:
        current_session_id.reset(token)
    assert error is not None
    assert "受管审计账本" in error.content
    store.consume.assert_not_called()


def test_macos_real_execute_command_tool_enforces_audit_policy(tmp_path):
    if sys.platform != "darwin" or not sandbox_exec_available():
        pytest.skip("real macOS sandbox-exec unavailable")
    ws, audit, ledger = _workspace(tmp_path)
    tool = ExecuteCommandTool(sandbox_mode="sandbox-exec", safety_audit_dir=audit)
    blocked = tool.execute(command="printf BAD >> data/audit/goals.jsonl", workdir=str(ws))
    allowed = tool.execute(command="printf OK > business.txt", workdir=str(ws))
    assert blocked.status.value == "failure"
    assert allowed.status.value == "success", allowed.content
    assert ledger.read_text() == "original\n"
    assert (ws / "business.txt").read_text() == "OK"


def test_extra_macos_writable_root_cannot_override_final_audit_deny(tmp_path, monkeypatch):
    ws, audit, _ = _workspace(tmp_path)
    monkeypatch.setenv("EXEC_SANDBOX_MACOS_WRITABLE", str(audit))
    with patch("llm_loop.tools.sandbox._probe_sandbox_exec", return_value=True):
        argv, note = sandbox_argv(
            "true", str(ws), mode="sandbox-exec", protected_roots=[str(audit)]
        )
    assert argv is not None
    profile = argv[2]
    assert profile.index(f'(allow file-write* (subpath "{audit}"))') < profile.index(
        f'(deny file-write* (subpath "{audit}"))'
    )
    assert "受管审计目录写保护" in note


def test_workdir_inside_protected_audit_fails_closed(tmp_path):
    ws, audit, _ = _workspace(tmp_path)
    with (
        patch("llm_loop.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap"),
        pytest.raises(RuntimeError, match="overlaps protected audit"),
    ):
        sandbox_argv(
            "true", str(audit), mode="bwrap", protected_roots=[str(audit)]
        )


def test_auto_none_explicitly_warns_audit_unprotected(tmp_path, monkeypatch):
    ws, audit, _ = _workspace(tmp_path)
    monkeypatch.delenv("EXEC_SANDBOX_STRICT", raising=False)
    with patch("llm_loop.tools.sandbox.resolve_auto_backend", return_value=("none", ["no backend"])):
        argv, note = sandbox_argv(
            "true", str(ws), mode="auto", protected_roots=[str(audit)]
        )
    assert argv is None
    assert "未受沙箱写隔离" in note


def test_none_mode_does_not_claim_audit_protection(tmp_path):
    ws, audit, _ = _workspace(tmp_path)
    argv, note = sandbox_argv(
        "true", str(ws), mode="none", protected_roots=[str(audit)]
    )
    assert argv is None
    assert "audit" in note.lower() or "审计" in note

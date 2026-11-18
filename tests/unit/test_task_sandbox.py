"""Task multi-root sandbox plans: real Mac Seatbelt + bwrap argv safety."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from llm_loop.tools.task_sandbox import compile_task_sandbox


@pytest.fixture
def roots(tmp_path):
    a, b, c = (tmp_path / x for x in ("project-a", "project-b", "project-c"))
    for path in (a, b, c):
        path.mkdir()
    audit = tmp_path / "audit-protected"
    audit.mkdir(mode=0o700)
    return a, b, c, audit


def _plan(roots, *, mode="sandbox-exec", extras=None):
    a, b, _c, audit = roots
    return compile_task_sandbox(
        "true",
        str(a),
        verified_project_roots=[str(b)] if extras is None else extras,
        protected_audit_roots=[str(audit)],
        mode=mode,
    )


def test_docker_and_none_never_fallback(roots):
    for mode in ("none", "docker"):
        with pytest.raises(RuntimeError, match="unsupported"):
            _plan(roots, mode=mode)


def test_protected_audit_is_required(roots):
    a, b, _c, _audit = roots
    with pytest.raises(ValueError, match="protected audit"):
        compile_task_sandbox(
            "true",
            str(a),
            verified_project_roots=[str(b)],
            protected_audit_roots=[],
            mode="sandbox-exec",
        )


def test_reject_root_home_relative_and_ancestor(roots):
    a, b, _c, audit = roots
    for invalid in ("/", str(Path.home()), "relative/path", str(a.parent)):
        with pytest.raises(ValueError):
            compile_task_sandbox(
                "true",
                str(a),
                verified_project_roots=[invalid],
                protected_audit_roots=[str(audit)],
                mode="sandbox-exec",
            )


def test_reject_symlink_root_and_audit_overlap(roots):
    a, b, _c, audit = roots
    alias = a.parent / "alias"
    alias.symlink_to(b, target_is_directory=True)
    with pytest.raises(ValueError):
        _plan(roots, extras=[str(alias)])
    with pytest.raises(ValueError):
        _plan(roots, extras=[str(audit)])


def test_reject_git_marker_symlink_and_hardlink(roots):
    a, b, _c, _audit = roots
    (b / ".git").symlink_to(a, target_is_directory=True)
    with pytest.raises(ValueError, match=".git"):
        _plan(roots)
    (b / ".git").unlink()
    marker = b / ".git"
    marker.write_text("gitdir: ../somewhere\n")
    os.link(marker, b / "alias-git-marker")
    with pytest.raises(ValueError, match="hardlinked"):
        _plan(roots)


def test_bwrap_plan_includes_exact_extra_root_and_protects_git(roots, monkeypatch):
    a, b, c, audit = roots
    (b / ".git").mkdir()
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/bwrap" if name == "bwrap" else None)
    plan = _plan(roots, mode="bwrap")
    argv = list(plan.argv)
    assert plan.backend == "bwrap"
    assert str(a) in plan.writable_roots and str(b) in plan.writable_roots
    assert ["--bind", str(b), str(b)] == argv[argv.index(str(b)) - 1 : argv.index(str(b)) + 2]
    assert ("--ro-bind", str(b / ".git"), str(b / ".git")) == tuple(
        argv[argv.index(str(b / ".git")) - 1 : argv.index(str(b / ".git")) + 2]
    )
    assert str(c) not in argv
    assert str(audit) in plan.protected_paths


def test_bwrap_linked_worktree_marker_is_readonly(roots, monkeypatch):
    _a, b, _c, _audit = roots
    marker = b / ".git"
    marker.write_text("gitdir: ../external/worktrees/b\n")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/bwrap" if name == "bwrap" else None)
    plan = _plan(roots, mode="bwrap")
    assert ("--ro-bind", str(marker), str(marker)) == tuple(
        plan.argv[plan.argv.index(str(marker)) - 1 : plan.argv.index(str(marker)) + 2]
    )


def test_task_profile_ignores_unrelated_global_writable_env(roots, monkeypatch):
    from llm_loop.tools.sandbox import sandbox_exec_available

    if not sandbox_exec_available():
        pytest.skip("sandbox-exec not usable on this host")
    monkeypatch.setenv("EXEC_SANDBOX_MACOS_WRITABLE", "/not-approved-by-task")
    plan = _plan(roots)
    assert "/not-approved-by-task" not in plan.argv[2]


@pytest.mark.skipif(sys.platform != "darwin", reason="real Seatbelt requires macOS")
def test_real_macos_extra_root_allowed_third_root_denied(roots):
    from llm_loop.tools.sandbox import sandbox_exec_available

    if not sandbox_exec_available():
        pytest.skip("sandbox-exec not usable on this host")
    a, b, c, audit = roots
    good = b / "approved.txt"
    bad = c / "unapproved.txt"
    command = f"printf approved > {good}; printf forbidden > {bad}"
    plan = compile_task_sandbox(
        command,
        str(a),
        verified_project_roots=[str(b)],
        protected_audit_roots=[str(audit)],
        mode="sandbox-exec",
    )
    proc = subprocess.run(plan.argv, cwd=a, capture_output=True, text=True, timeout=15)
    assert proc.returncode != 0
    assert good.read_text() == "approved"
    assert not bad.exists()
    assert "write isolation only" in plan.note


@pytest.mark.skipif(sys.platform != "darwin", reason="real Seatbelt requires macOS")
def test_real_macos_git_metadata_denied(roots):
    from llm_loop.tools.sandbox import sandbox_exec_available

    if not sandbox_exec_available():
        pytest.skip("sandbox-exec not usable on this host")
    a, b, _c, audit = roots
    gitdir = b / ".git"
    gitdir.mkdir()
    protected_file = gitdir / "config"
    protected_file.write_text("original")
    ordinary_file = b / "allowed.txt"
    command = f"printf allowed > {ordinary_file}; printf forbidden > {protected_file}"
    plan = compile_task_sandbox(
        command,
        str(a),
        verified_project_roots=[str(b)],
        protected_audit_roots=[str(audit)],
        mode="sandbox-exec",
    )
    proc = subprocess.run(plan.argv, cwd=a, capture_output=True, text=True, timeout=15)
    assert proc.returncode != 0
    assert ordinary_file.read_text() == "allowed"
    assert protected_file.read_text() == "original"


@pytest.mark.skipif(sys.platform != "darwin", reason="real Seatbelt requires macOS")
def test_real_macos_linked_worktree_marker_denied(roots):
    from llm_loop.tools.sandbox import sandbox_exec_available

    if not sandbox_exec_available():
        pytest.skip("sandbox-exec not usable on this host")
    a, b, _c, audit = roots
    marker = b / ".git"
    marker.write_text("gitdir: ../external/worktrees/b\n")
    ordinary = b / "allowed.txt"
    command = f"printf allowed > {ordinary}; printf forbidden > {marker}"
    plan = compile_task_sandbox(
        command,
        str(a),
        verified_project_roots=[str(b)],
        protected_audit_roots=[str(audit)],
        mode="sandbox-exec",
    )
    proc = subprocess.run(plan.argv, cwd=a, capture_output=True, text=True, timeout=15)
    assert proc.returncode != 0
    assert ordinary.read_text() == "allowed"
    assert marker.read_text() == "gitdir: ../external/worktrees/b\n"

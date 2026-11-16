"""Negative tests for local-only integration lock and narrow cherry-pick entry."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "integration_writer_lock.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "source"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Tester")
    (root / "base.txt").write_text("base\n")
    git(root, "add", "base.txt")
    git(root, "commit", "-qm", "base")
    linked = tmp_path / "linked"
    git(root, "worktree", "add", "-qb", "integration/test", str(linked))
    return root, linked


def run(worktree: Path, *args: str) -> tuple[int, dict]:
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--worktree", str(worktree), *args],
        capture_output=True, text=True, timeout=30,
    )
    return p.returncode, json.loads(p.stdout.strip())


def test_aliases_resolve_same_common_lock(repo: tuple[Path, Path], tmp_path: Path):
    root, linked = repo
    alias = tmp_path / "alias"
    alias.symlink_to(linked, target_is_directory=True)
    a, result = run(linked, "--mode", "probe")
    b, result2 = run(alias, "--mode", "probe")
    c, result3 = run(root, "--mode", "probe")
    assert a == b == c == 0
    assert result["lock_path"] == result2["lock_path"] == result3["lock_path"]
    assert result["lock_path"] == str((root / ".git").resolve())


def test_two_processes_second_writer_rejected(repo: tuple[Path, Path]):
    _, linked = repo
    p = subprocess.Popen(
        [sys.executable, str(SCRIPT), "--mode", "probe",
         "--worktree", str(linked), "--hold-seconds", "2"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert p.stdout is not None
        assert json.loads(p.stdout.readline())["decision"] == "lock_held"
        code, result = run(linked, "--mode", "probe")
        assert code == 3
        assert result["reason"] == "integration_writer_busy"
    finally:
        p.wait(timeout=10)
    code, result = run(linked, "--mode", "probe")
    assert code == 0 and result["decision"] == "lock_held"


def test_wrong_head_and_dirty_are_fail_closed(repo: tuple[Path, Path]):
    _, linked = repo
    head = git(linked, "rev-parse", "HEAD")
    code, result = run(linked, "--mode", "apply-commits",
                       "--expected-head", "a" * 40, "--commit", head)
    assert code == 3 and result["reason"] == "integration_head_changed"
    (linked / "dirty.txt").write_text("untracked")
    code, result = run(linked, "--mode", "apply-commits",
                       "--expected-head", head, "--commit", head)
    assert code == 3 and result["reason"] == "integration_dirty"


def test_legacy_lock_file_unlink_cannot_create_second_writer(repo: tuple[Path, Path]):
    root, linked = repo
    p = subprocess.Popen(
        [sys.executable, str(SCRIPT), "--mode", "probe",
         "--worktree", str(linked), "--hold-seconds", "2"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert p.stdout is not None
        assert json.loads(p.stdout.readline())["decision"] == "lock_held"
        legacy = root / ".git" / "lfl-integration-writer.lock"
        legacy.touch()
        legacy.unlink()
        legacy.touch()
        code, result = run(linked, "--mode", "probe")
        assert code == 3 and result["reason"] == "integration_writer_busy"
    finally:
        p.wait(timeout=10)


def test_main_write_forbidden(repo: tuple[Path, Path]):
    root, _ = repo
    head = git(root, "rev-parse", "HEAD")
    code, result = run(root, "--mode", "apply-commits",
                       "--expected-head", head, "--commit", head)
    assert code == 3 and result["reason"] == "main_write_forbidden"


def test_apply_one_commit_only_in_integration_worktree(repo: tuple[Path, Path]):
    root, linked = repo
    old = git(linked, "rev-parse", "HEAD")
    git(root, "checkout", "-qb", "feature/source")
    (root / "change.txt").write_text("feature")
    git(root, "add", "change.txt")
    git(root, "commit", "-qm", "feature")
    source_sha = git(root, "rev-parse", "HEAD")
    code, result = run(linked, "--mode", "apply-commits",
                       "--expected-head", old, "--commit", source_sha)
    assert code == 0 and result["decision"] == "applied_local_only"
    assert git(linked, "rev-parse", "HEAD") == result["new_head"]
    assert git(linked, "status", "--porcelain") == ""
    assert (linked / "change.txt").read_text() == "feature"
    assert git(root, "rev-parse", "HEAD") == source_sha


def test_lock_failure_does_not_clean_dirty_tree(repo: tuple[Path, Path]):
    _, linked = repo
    (linked / "conflict.txt").write_text("do not delete")
    code, result = run(linked, "--mode", "apply-commits",
                       "--expected-head", git(linked, "rev-parse", "HEAD"),
                       "--commit", git(linked, "rev-parse", "HEAD"))
    assert code == 3 and result["reason"] == "integration_dirty"
    assert (linked / "conflict.txt").read_text() == "do not delete"


def test_invalid_path_and_commit_do_not_write(repo: tuple[Path, Path], tmp_path: Path):
    _, linked = repo
    code, result = run(tmp_path / "not-a-repo", "--mode", "probe")
    assert code == 3 and result["reason"] in {"integration_lock_unavailable", "git_probe_failed"}
    code, result = run(linked, "--mode", "apply-commits",
                       "--expected-head", "not-a-sha", "--commit", "bad")
    assert code == 3 and result["reason"] == "invalid_exact_sha"


def test_p2_git_probe_timeout_becomes_hold(monkeypatch, tmp_path: Path):
    import subprocess

    import integration_writer_lock as module

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 20)

    monkeypatch.setattr(module.subprocess, "run", timeout)
    with pytest.raises(module.IntegrationHoldError, match="git_probe_unavailable"):
        module._git(tmp_path, "rev-parse", "HEAD")

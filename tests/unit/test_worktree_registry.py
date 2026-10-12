"""T0-A1/A2: worktree registry + 嵌套禁令单测."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from llm_loop.runtime.worktree_registry import (
    GUARD_LOG_RELPATH,
    REGISTRY_RELPATH,
    bootstrap,
    check_add_target,
    find_nested,
    load_registry,
    parse_worktrees,
    save_registry,
)


def _git(cwd: Path, *args: str) -> None:
    r = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    main = tmp_path / "main-repo"
    main.mkdir()
    (main / "f.txt").write_text("x")
    _git(main, "init", "-q", "-b", "main")
    _git(main, "add", ".")
    _git(main, "commit", "-qm", "init")
    (main / ".worktrees").mkdir()
    _git(main, "worktree", "add", "-q", str(main / ".worktrees/wt1"), "-b", "wt1")
    _git(main, "worktree", "add", "-q", str(main / ".worktrees/wt2"), "-b", "wt2")
    return main


def test_parse_and_sanctioned_layout_not_nested(repo: Path):
    entries = parse_worktrees(repo)
    assert entries[0].path == str(repo)  # 主 worktree 恒第一
    assert len(entries) == 3
    assert find_nested(entries) == []  # 主 worktree 下挂 .worktrees/ 不算嵌套


def test_nested_detection_and_add_guard(repo: Path, tmp_path: Path):
    nested = repo / ".worktrees/wt1/inner-wt"
    _git(repo, "worktree", "add", "-q", str(nested), "-b", "inner")
    entries = parse_worktrees(repo)
    pairs = find_nested(entries)
    assert len(pairs) == 1
    assert pairs[0][0].path == str(repo / ".worktrees/wt1")
    assert pairs[0][1].path == str(nested)

    rt = tmp_path / "runtime"
    ok, reason = check_add_target(repo, repo / ".worktrees/wt1/another", rt)
    assert not ok and "嵌套禁令" in reason
    guard_log = rt / GUARD_LOG_RELPATH
    assert guard_log.exists()
    event = json.loads(guard_log.read_text().splitlines()[-1])
    assert event["event"] == "nested_add_rejected"
    # 合法路径放行
    ok2, _ = check_add_target(repo, repo / ".worktrees/wt3", rt)
    assert ok2


def test_bootstrap_marks_protected_and_legacy(repo: Path, tmp_path: Path):
    rt = tmp_path / "runtime"
    reg = bootstrap(rt, repo, protected_paths=[str(repo / ".worktrees/wt1")])
    by_path = {e["path"]: e for e in reg["entries"]}
    assert by_path[str(repo / ".worktrees/wt1")]["protected"] is True
    assert by_path[str(repo / ".worktrees/wt2")]["status"] == "legacy"
    assert reg["counts"]["total"] == 3
    # registry 落盘且可读
    assert (rt / REGISTRY_RELPATH).exists()
    assert load_registry(rt) == reg


def test_registry_fail_open_and_retired_preserved(repo: Path, tmp_path: Path):
    rt = tmp_path / "runtime"
    bootstrap(rt, repo, protected_paths=[str(repo / ".worktrees/wt1")])
    # retired 人工标记在再 bootstrap 后保留（A4 不被覆盖）
    reg = load_registry(rt)
    for e in reg["entries"]:
        if e["path"] == str(repo / ".worktrees/wt2"):
            e["status"] = "retired"
    save_registry(rt, reg)
    reg2 = bootstrap(rt, repo, protected_paths=[str(repo / ".worktrees/wt1")])
    by_path = {e["path"]: e for e in reg2["entries"]}
    assert by_path[str(repo / ".worktrees/wt2")]["status"] == "retired"
    # 损坏 → fail-open None
    (rt / REGISTRY_RELPATH).write_text("{corrupt", encoding="utf-8")
    assert load_registry(rt) is None


def test_bootstrap_detected_nested_writes_guard_log(repo: Path, tmp_path: Path):
    _git(repo, "worktree", "add", "-q", str(repo / ".worktrees/wt1/inner-wt"), "-b", "inner")
    rt = tmp_path / "runtime"
    reg = bootstrap(rt, repo, protected_paths=[str(repo / ".worktrees/wt1")])
    assert reg["counts"]["nested_pairs"] == 1
    assert (rt / GUARD_LOG_RELPATH).exists()

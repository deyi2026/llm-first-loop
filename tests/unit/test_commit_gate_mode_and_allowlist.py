"""提交动作层两道新闸的回归（2026-11-10）。

背景：测试层（``tests/unit/test_githooks_exec_bit.py``）能发现执行位降权，但只在
被跑时生效；``scripts/r9_commit.sh`` 最后是裸 ``git commit``，提交整个索引，他人
add 后离场留下的条目会被静默混入。本文件覆盖把守卫上移到动作层后的两道闸：

1. ``R9_STAGED_ALLOW``：索引中出现白名单外条目即拒绝；
2. 钩子索引模式守卫：``.githooks/*`` 不是 100755 即拒绝（否则 git 静默跳过钩子）；
3. ``git_security_scan.sh`` 规则 6：已跟踪 100755 降为 100644 硬拦 + 显式逃生口。

按 RULE-AI-35 口径，每条闸都实测「应拦输入」真的被拦；全部在临时 git 仓库内
执行，不触碰本仓索引与工作区。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_R9 = _REPO / "scripts" / "r9_commit.sh"
_CLEANUP = _REPO / "scripts" / "r9_probe_cleanup.sh"
_SCAN = _REPO / "scripts" / "git_security_scan.sh"


def _env(**extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": os.environ.get("TMPDIR", "/tmp"),
        }
    )
    env.pop("R9_STAGED_ALLOW", None)
    env.pop("LFL_MODE_DOWNGRADE_ALLOW", None)
    env.update(extra)
    return env


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=_env(),
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """临时 git 仓库：含 r9_commit.sh 依赖的两个脚本，不做真实提交门禁。"""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / "seed.txt").write_text("seed\n")
    _git(r, "add", "seed.txt")
    _git(r, "commit", "-qm", "seed")
    scripts = r / "scripts"
    scripts.mkdir()
    (scripts / "r9_commit.sh").write_text(_R9.read_text())
    (scripts / "r9_probe_cleanup.sh").write_text(_CLEANUP.read_text())
    return r


def _run_r9(repo: Path, msg: str = "test", **env_extra: str):
    return subprocess.run(
        ["bash", "scripts/r9_commit.sh", msg],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_env(**env_extra),
    )


def _scan(repo: Path, **env_extra: str):
    return subprocess.run(
        ["bash", str(_SCAN), "--staged"],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_env(**env_extra),
    )


# ── 1. R9_STAGED_ALLOW 白名单 ──────────────────────────────────────────────

def test_staged_allowlist_blocks_unexpected(repo: Path) -> None:
    """白名单外条目必须真的被拦（2026-11-10 他人残留混入的复现场景）。"""
    (repo / "mine.txt").write_text("x\n")
    (repo / "theirs.txt").write_text("y\n")
    _git(repo, "add", "mine.txt", "theirs.txt")

    p = _run_r9(repo, R9_STAGED_ALLOW="mine.txt")

    assert p.returncode == 1
    assert "白名单外条目" in p.stderr
    assert "theirs.txt" in p.stderr


def test_staged_allowlist_passes_when_all_listed(repo: Path) -> None:
    """全部列名后不再命中白名单闸（后续缺机检脚本而失败，与本闸无关）。"""
    (repo / "mine.txt").write_text("x\n")
    (repo / "theirs.txt").write_text("y\n")
    _git(repo, "add", "mine.txt", "theirs.txt")

    p = _run_r9(repo, R9_STAGED_ALLOW="mine.txt\ntheirs.txt")

    assert "白名单外条目" not in p.stderr


def test_staged_allowlist_unset_keeps_legacy_behavior(repo: Path) -> None:
    """不设变量 = 旧行为：索引里有什么都不因白名单闸而拒。"""
    (repo / "mine.txt").write_text("x\n")
    _git(repo, "add", "mine.txt")

    p = _run_r9(repo)

    assert "白名单外条目" not in p.stderr


# ── 2. 钩子索引模式守卫 ────────────────────────────────────────────────────

def test_hook_index_mode_guard_blocks_100644(repo: Path) -> None:
    """钩子索引模式 100644 = git 静默跳过 → 提交动作处必须拒绝。"""
    hooks = repo / ".githooks"
    hooks.mkdir()
    (hooks / "pre-commit").write_text("#!/usr/bin/env bash\nexit 0\n")
    _git(repo, "add", ".githooks/pre-commit")

    p = _run_r9(repo)

    assert p.returncode == 1
    assert "索引模式非 100755" in p.stderr
    assert ".githooks/pre-commit" in p.stderr


# ── 3. 规则 6：执行位降级 ──────────────────────────────────────────────────

@pytest.fixture()
def exec_repo(repo: Path) -> Path:
    tool = repo / "tool.sh"
    tool.write_text("#!/bin/sh\necho hi\n")
    tool.chmod(0o755)
    _git(repo, "add", "tool.sh")
    _git(repo, "commit", "-qm", "tool")
    return repo


def test_mode_downgrade_blocked(exec_repo: Path) -> None:
    (exec_repo / "tool.sh").chmod(0o644)
    _git(exec_repo, "add", "tool.sh")

    p = _scan(exec_repo)

    # _fail 目前写 stdout（规则 1-6 共用出口），断言 combined 以免绑定出口流。
    out = p.stdout + p.stderr
    assert p.returncode == 1
    assert "执行位降级" in out
    assert "tool.sh" in out


def test_mode_downgrade_escape_hatch_is_explicit(exec_repo: Path) -> None:
    (exec_repo / "tool.sh").chmod(0o644)
    _git(exec_repo, "add", "tool.sh")

    p = _scan(exec_repo, LFL_MODE_DOWNGRADE_ALLOW="tool.sh")

    assert p.returncode == 0, p.stderr
    assert "已显式豁免" in p.stderr


def test_mode_downgrade_not_triggered_by_content_change(exec_repo: Path) -> None:
    """只改内容不改模式，规则 6 不得误报。"""
    (exec_repo / "tool.sh").write_text("#!/bin/sh\necho bye\n")
    _git(exec_repo, "add", "tool.sh")

    p = _scan(exec_repo)

    assert p.returncode == 0, p.stderr
    assert "执行位降级" not in (p.stdout + p.stderr)

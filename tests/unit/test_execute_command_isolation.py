"""EVO-20261016-96abc163: execute_command 声明式 worktree 硬隔离单测.

覆盖: opt-in 参数校验（类型/组合约束）、prepare 失败 fail-fast（不降级共享执行）、
干净树自动删除+cwd 落隔离树、脏树保守保留+回执附注、默认关闭零回归、
执行面矩阵 fs_isolation 能力位。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from llm_loop.core.execution_surface import (
    SurfaceRequirements,
    codearts_capability,
    local_subagent_capability,
    validate_requirements,
)
from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.core.run_context import current_workspace_root
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.registry import ToolRegistry


def _git(cwd: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, f"git {args}: {proc.stderr}"
    return proc.stdout.strip()


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(str(repo), "init", "-q")
    _git(str(repo), "config", "user.email", "t@t")
    _git(str(repo), "config", "user.name", "t")
    (repo / "seed.txt").write_text("seed", encoding="utf-8")
    _git(str(repo), "add", "-A")
    _git(str(repo), "commit", "-q", "-m", "seed")
    return repo


def _run(arguments: dict):
    reg = ToolRegistry()
    reg.register(ExecuteCommandTool(timeout_s=30))
    return reg.execute(
        ToolCall(id="c1", name="execute_command", arguments=arguments)
    )


def _remaining_worktrees(repo: Path) -> list[Path]:
    wt_dir = repo / ".worktrees"
    if not wt_dir.is_dir():
        return []
    return sorted(p for p in wt_dir.iterdir() if p.name.startswith("lfl-child-"))


class TestParamValidation:
    def test_isolation_requires_bool(self) -> None:
        r = _run({"command": "pwd", "isolation": "yes"})
        assert r.status == ToolResultStatus.FAILURE
        assert "isolation 需为 boolean" in r.content

    def test_isolation_rejects_run_in_background(self) -> None:
        r = _run({"command": "sleep 1", "isolation": True, "run_in_background": True})
        assert r.status == ToolResultStatus.FAILURE
        assert "run_in_background" in r.content

    def test_isolation_rejects_explicit_workdir(self, git_repo: Path) -> None:
        r = _run({"command": "pwd", "isolation": True, "workdir": str(git_repo)})
        assert r.status == ToolResultStatus.FAILURE
        assert "workdir" in r.content


class TestPrepareFailure:
    def test_non_git_workspace_refused_without_degraded_execution(
        self, tmp_path: Path
    ) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        token = current_workspace_root.set(str(plain))
        try:
            r = _run({"command": "echo leaked", "isolation": True})
        finally:
            current_workspace_root.reset(token)
        assert r.status == ToolResultStatus.FAILURE
        assert "reason_code=NOT_GIT_WORKSPACE" in r.content
        assert "未降级" in r.content
        assert "leaked" not in r.content  # 命令确未执行


class TestIsolatedExecution:
    def test_clean_tree_removed_and_cwd_is_worktree(self, git_repo: Path) -> None:
        token = current_workspace_root.set(str(git_repo))
        try:
            r = _run({"command": "pwd", "isolation": True})
        finally:
            current_workspace_root.reset(token)
        assert r.status == ToolResultStatus.SUCCESS, r.content
        assert ".worktrees" in r.content  # pwd 实际落在隔离树内
        assert "已清理隔离树（干净）" in r.content  # 精确终态语义，非泛前缀
        assert _remaining_worktrees(git_repo) == []  # 干净树自动删除

    def test_dirty_tree_kept_with_note_and_artifact(self, git_repo: Path) -> None:
        token = current_workspace_root.set(str(git_repo))
        try:
            r = _run({"command": "echo out > produced.txt", "isolation": True})
        finally:
            current_workspace_root.reset(token)
        assert r.status == ToolResultStatus.SUCCESS, r.content
        assert "隔离树保留" in r.content  # kept_dirty 附注（路径+HEAD）
        assert "已清理隔离树" not in r.content
        kept = _remaining_worktrees(git_repo)
        assert len(kept) == 1
        assert (kept[0] / "produced.txt").exists()  # 产物留在保留树
        # 测试收尾清理（tmp repo，防脏树堆积影响同仓库后续用例）
        shutil.rmtree(kept[0], ignore_errors=True)
        _git(str(git_repo), "worktree", "prune")

    def test_default_off_creates_no_worktree(self, git_repo: Path) -> None:
        token = current_workspace_root.set(str(git_repo))
        try:
            r = _run({"command": "pwd"})
        finally:
            current_workspace_root.reset(token)
        assert r.status == ToolResultStatus.SUCCESS, r.content
        assert ".worktrees" not in r.content  # 主工作区直连，零回归
        assert not (git_repo / ".worktrees").exists()


class TestSurfaceCapabilityBit:
    def test_local_subagent_has_fs_isolation_bit(self) -> None:
        caps = local_subagent_capability(["read_file"])
        assert caps.fs_isolation is True
        assert caps.to_dict()["fs_isolation"] is True
        reqs = SurfaceRequirements.from_kwargs({"fs_isolation": True})
        assert validate_requirements(caps, reqs) == []

    def test_codearts_lacks_fs_isolation_bit_with_hint(self) -> None:
        caps = codearts_capability()
        assert caps.fs_isolation is False
        reqs = SurfaceRequirements.from_kwargs({"fs_isolation": True})
        gaps = validate_requirements(caps, reqs)
        assert any(
            "fs_isolation" in g and "不支持" in g and "execute_command" in g
            for g in gaps
        )

"""task_git_commit 普通会话拒绝可诊断性（MANAGED-GIT-TASK-CONTEXT-P0-20261125）.

无 Host Task 上下文时必须 fail-closed 拒绝（UNAUTHORIZED、reason_code 稳定），
且回执带明确指引（Task 调度面专属 / lane 正规流程 / EVO 验收项），不产生任何
Git/文件副作用。
"""
from __future__ import annotations

from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.builtin.task_git_commit import TaskGitCommitTool


def test_no_task_context_failclosed_with_guidance(tmp_path):
    tool = TaskGitCommitTool()
    result = tool.execute(paths=["a.py"], message="test commit")
    assert result.status == ToolResultStatus.UNAUTHORIZED
    assert result.error_type == "task_context_not_active"
    assert "Task lease" in result.content
    assert "EVO-20261125-28d517b3" in result.content
    assert "不要重试" in result.content
    assert "[task_git_commit HOLD]" in result.content


def test_invalid_arguments_still_failclosed(tmp_path):
    tool = TaskGitCommitTool()
    result = tool.execute(paths=[], message="x")
    assert result.status == ToolResultStatus.FAILURE
    assert result.error_type == "task_git_arguments_invalid"

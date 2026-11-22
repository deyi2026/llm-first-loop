"""Bounded model-facing Git commit for a Host-signed Task Lease.

No arbitrary Git argv, worktree, Lease, Lane CAS, push, merge or release input
is accepted from the model. The trusted Run Context owns all identities.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import (
    current_session_id,
    current_task_execution,
    current_workspace_root,
)
from llm_loop.core.task_capabilities import CapabilityRequest
from llm_loop.tools.managed_git import (
    GitCommitRequest,
    ManagedGitAdapter,
    ManagedGitError,
    _git_metadata,
)
from llm_loop.tools.task_execution import TrustedTaskExecution


class TaskGitCommitTool:
    name = "task_git_commit"
    description = (
        "仅在 Host 已签名 Task Lease 且 Goal/Task/Lane/CAS 有效时，将当前隔离"
        "worktree 中明确列出的已登记文件做一次受管 Git commit。"
        "不接受命令行、路径根、Lease、push/merge/release、hooks或任意Git选项；"
        "冲突/未知效果不自动重试。无 Host 授权时请勿调用。"
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array", "items": {"type": "string"},
                "minItems": 1, "maxItems": 64,
                "description": "相对当前Task worktree的显式文件路径，必须属于当前Lane",
            },
            "message": {
                "type": "string", "minLength": 1, "maxLength": 200,
                "description": "单行Git提交说明；不能包含换行或选项",
            },
        },
        "required": ["paths", "message"],
        "additionalProperties": False,
    }

    def _fail(self, reason: str, *, unauthorized: bool = False) -> ToolResult:
        return ToolResult(
            status=(
                ToolResultStatus.UNAUTHORIZED if unauthorized
                else ToolResultStatus.FAILURE
            ),
            content=(
                f"[task_git_commit HOLD] {reason}。"
                "未推送、未合并、未发布；若效果未知先核对Git HEAD和Lane回执，"
                "不得自动重试。"
            ),
            tool_call_id="", tool_name=self.name, error_type=reason,
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        if set(kwargs) != {"paths", "message"}:
            return self._fail("task_git_arguments_invalid")
        paths = kwargs["paths"]
        message = kwargs["message"]
        if (
            not isinstance(paths, list)
            or not 1 <= len(paths) <= 64
            or not all(isinstance(p, str) and p for p in paths)
            or len(set(paths)) != len(paths)
            or not isinstance(message, str)
            or not 1 <= len(message.strip()) <= 200
            or "\n" in message or "\r" in message
        ):
            return self._fail("task_git_arguments_invalid")
        task = current_task_execution.get()
        if not isinstance(task, TrustedTaskExecution):
            return self._fail("task_context_not_active", unauthorized=True)
        worktree = current_workspace_root.get()
        if (
            not isinstance(worktree, str)
            or not os.path.isabs(worktree)
            or os.path.realpath(worktree) != worktree
            or current_session_id.get() != task.owner_session_id
        ):
            return self._fail("task_git_workspace_or_session_invalid", unauthorized=True)
        try:
            gitdir, common = _git_metadata(worktree)
            request = CapabilityRequest(
                goal_id=task.goal_id,
                task_id=task.task_id,
                owner_session_id=task.owner_session_id,
                agent_id=task.agent_id,
                lane_id=task.lane_id,
                expected_revision=task.revision,
                kind="project", target=worktree, verb="git_commit",
            )
            lock_dir = Path(task.lanes._dir) / "git-locks"
            if not lock_dir.is_dir() or lock_dir.is_symlink():
                return self._fail("git_lock_unavailable")
            adapter = ManagedGitAdapter(
                authority=task.authority,
                lanes=task.lanes,
                lock_dir=lock_dir,
                protected_roots=task.protected_roots,
            )
            receipt = adapter.commit_paths(
                GitCommitRequest(
                    lease_id=task.lease_id,
                    capability=request,
                    worktree=worktree,
                    expected_head=task.expected_head,
                    expected_lane_version=task.lane_version,
                    expected_gitdir=gitdir,
                    expected_common_dir=common,
                    paths=tuple(paths),
                    message=message,
                )
            )
        except ManagedGitError as exc:
            return self._fail(exc.reason_code)
        except (OSError, ValueError) as exc:
            return self._fail(f"task_git_preflight_unavailable:{type(exc).__name__}")
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="[task_git_commit] " + json.dumps(
                {
                    "old_head": receipt.old_head,
                    "new_head": receipt.new_head,
                    "paths": list(receipt.paths),
                    "lane_version": receipt.lane_version,
                    "worktree": receipt.worktree,
                    "pushed": False, "merged": False, "deployed": False,
                },
                ensure_ascii=False, sort_keys=True,
            ),
            tool_call_id="", tool_name=self.name,
        )

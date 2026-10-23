"""交付边界与提交纪律（`T-OPS-1` / `T-OPS-2` / `T-OPS-3`）。

对应需求（设计 v1.3 §4.4）：运行/用户态文件**不清理、不回滚、不提交**；
提交**按精确路径**选择（**不整目录 `git add`**）；回滚边界在 Web 范围，保留任务事实。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

RUNTIME_USER_STATE_FILES: tuple[str, ...] = (
    "data/knowledge_scores/runner_state.json",
    "data/runtime/learning_admission.json",
)

BROAD_ADD_TOKENS: frozenset[str] = frozenset({".", "-A", "--all", ":/", "*", ":/."})


class CommitBoundaryError(RuntimeError):
    """提交边界违规（整目录 / 运行文件）。"""


@dataclass(frozen=True)
class CommitPlan:
    """精确提交计划；拒绝宽泛路径与运行文件。"""

    paths: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.paths:
            raise CommitBoundaryError("empty commit plan")
        for raw in self.paths:
            path = raw.strip()
            if path in BROAD_ADD_TOKENS or path.startswith("-"):
                raise CommitBoundaryError(f"broad add token not allowed: {raw!r}")
            if not path:
                raise CommitBoundaryError("empty path in commit plan")
            if path in RUNTIME_USER_STATE_FILES:
                raise CommitBoundaryError(f"runtime/user-state file must not be committed: {path}")

    def is_exact(self) -> bool:
        return all(not any(ch in p for ch in "*?") for p in self.paths)


def is_ignored(path: str, *, cwd: str) -> bool:
    """`git check-ignore -q`：命中即被忽略。"""
    result = subprocess.run(  # noqa: S603
        ["git", "check-ignore", "-q", path],  # noqa: S607
        cwd=cwd,
        capture_output=True,
    )
    return result.returncode == 0


def is_tracked(path: str, *, cwd: str) -> bool:
    """`git ls-files --error-unmatch`：被跟踪即返回 True。"""
    result = subprocess.run(  # noqa: S603
        ["git", "ls-files", "--error-unmatch", path],  # noqa: S607
        cwd=cwd,
        capture_output=True,
    )
    return result.returncode == 0


def rollback_playbook() -> dict[str, object]:
    """回滚边界：Web 范围关闭新增媒体入口并恢复原文字入口；**保留任务事实**。"""
    return {
        "triggers": (
            "cross_session_leak",
            "duplicate_dispatch",
            "cannot_stop_playback",
            "credential_leak",
            "unbounded_resource_growth",
        ),
        "steps": (
            "disable_realtime_media_entrypoints",
            "restore_text_only_entrypoint",
            "preserve_task_facts",
            "do_not_interrupt_other_services",
        ),
        "must_preserve": ("task_facts", "tool_execution_journal"),
    }

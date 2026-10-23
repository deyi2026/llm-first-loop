"""Lightweight, user-authorized handoff without copying source history.

The source Session is a persisted point-in-time snapshot. Current runtime and
side effect status must be rechecked by the new run before taking action.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_loop.core.session import Session, SessionStore
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_store import TaskStore

_MAX_PROMPT = 4800


def _excerpt(value: object, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "…[仅摘录，原文仍在来源记录]"


def build_handoff_snapshot(source: Session, *, audit_dir: str | Path) -> dict[str, Any]:
    """Derive bounded facts, with strict source-session Goal isolation."""
    sid = source.session_id
    recent_users = []
    for index in range(len(source.messages) - 1, -1, -1):
        message = source.messages[index]
        if message.role == "user":
            recent_users.append((index, _excerpt(message.content, 320)))
            if len(recent_users) >= 3:
                break
    recent_users.reverse()
    goal = None
    goal_issue = ""
    tasks = []
    try:
        goal = GoalStore(audit_dir).get(prefer_session_id=sid, strict_session=True)
    except Exception as exc:
        goal_issue = f"Goal 状态不可验证：{type(exc).__name__}"
    if goal:
        try:
            tasks = [
                task for task in TaskStore(audit_dir).list_for_goal(str(goal["id"]))
                if task.status not in ("done", "failed", "cancelled")
            ]
        except Exception as exc:
            goal_issue = f"Task 状态不可验证：{type(exc).__name__}"
            tasks = []
    goal_id = str((goal or {}).get("id") or "")
    lines = [
        "[跨会话接力快照 · 历史资料不构成新的操作授权]",
        f"来源会话：{sid}",
        f"来源持久化快照：{source.updated_at}；消息 {len(source.messages)} 条（未复制）",
        "先核验来源会话当前执行状态及外部副作用终态，禁止自动重放未结算工具。",
        "",
        "## 最近用户原始指令（附来源索引，均为历史事实）",
    ]
    if recent_users:
        lines.extend(f"- message[{i}]: {content}" for i, content in recent_users)
    else:
        lines.append("- 无历史用户指令")
    lines.extend(["", "## 任务与里程碑（严格来源会话绑定）"])
    if goal:
        lines.append(f"- Goal: {goal_id} | status: {goal.get('status', 'unknown')}")
        lines.append(f"- objective: {_excerpt(goal.get('objective'), 360)}")
        if tasks:
            lines.extend(
                f"- {task.task_id} [{task.status}] {_excerpt(task.title, 100)}"
                for task in tasks[:8]
            )
            if len(tasks) > 8:
                lines.append(f"- 另有 {len(tasks) - 8} 个开放 Task，以 Goal ID 精确读取")
        else:
            lines.append("- 没有可核验的开放 Task（不据此断言任务完成）")
        for cp in (goal.get("checkpoints") or [])[-3:]:
            lines.append(
                "- checkpoint: " + _excerpt(cp.get("what"), 130)
                + (" | next=" + _excerpt(cp.get("next"), 110) if cp.get("next") else "")
                + (" | evidence=" + _excerpt(cp.get("evidence"), 90) if cp.get("evidence") else "")
            )
    else:
        lines.append("- 没有严格匹配该来源会话的 Goal；不得自动采用其他会话的 Goal")
    if goal_issue:
        lines.append(f"- 读取异常：{goal_issue}；需显式复核")
    lines.extend([
        "",
        "下一步：读取来源会话和 Goal/Task 的精确事实，核验 Git/运行态与权限，再依最新用户授权继续。",
    ])
    prompt = "\n".join(lines)
    if len(prompt) > _MAX_PROMPT:
        prompt = prompt[:_MAX_PROMPT] + "\n[展示截断；原始资料仍在来源会话/Goal/Task 记录]"
    return {
        "source_session_id": sid,
        "source_message_count": len(source.messages),
        "source_updated_at": source.updated_at,
        "goal_id": goal_id,
        "goal_status": str((goal or {}).get("status") or "unavailable"),
        "open_task_count": len(tasks),
        "goal_issue": goal_issue,
        "continuation_prompt": prompt,
    }


def create_handoff_session(
    store: SessionStore, source_session_id: str, *, audit_dir: str | Path,
) -> dict[str, Any]:
    """Prepare a fresh conversation even if the source has an active run.

    Never acquire the source management lease, mutate it or copy EventStore data.
    """
    if not store.exists(source_session_id):
        raise ValueError("source_session_not_found")
    source = store.load(source_session_id)
    if source.status != "active":
        raise ValueError("source_session_not_active")
    snapshot = build_handoff_snapshot(source, audit_dir=audit_dir)
    new_id = store.create(
        model_override=source.model_override,
        parent_id=source_session_id,
        branch_summary=snapshot["continuation_prompt"],
        title=_excerpt(source.title or "未命名会话", 55) + "（接力）",
    )
    return {
        **snapshot,
        "new_session_id": new_id,
        "inherited_message_count": 0,
        "inherited_event_count": 0,
    }

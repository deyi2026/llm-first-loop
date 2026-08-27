"""任务级 Goal 工具实现（EVO-20260824-3cd4d74b，MCP Console Goal workflow 借鉴）.

4 个工具:
- create_goal: 创建任务目标（active；有界推进起点）
- checkpoint_goal: 里程碑 checkpoint（四要素: What/Evidence/Path/Next；5 实质工具调用后或交接/回合结束前）
- get_goal: 获取当前目标 + 最近 checkpoints（恢复 handoff 上下文）
- update_goal: complete/blocked 状态流转（blocked 仅严格条件: 外部阻塞/安全边界/等人工）

单一数据源: 落盘 audit_dir/goals.jsonl（每轮 event_logs 已自动记录工具调用，不另起持久化）。
"""

from __future__ import annotations

from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.goal import GoalStore, GOAL_STATUSES

CREATE_GOAL_TOOL_DEF: dict = {
    "name": "create_goal",
    "description": (
        "创建任务级目标（任务状态机起点，EVO-20260824-3cd4d74b）。何时用: 接到长任务"
        "（深度审计/分析/推进类）需跨会话/跨模型持续追踪进度时。有界推进: 目标为里程碑"
        "收敛式，禁止'永不结束对话'语义；遇成本/方向/安全边界应暂停等人工确认。"
        "何时不用: 简单一次性任务。失败对策: objective 必填，缺失会如实返回。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "objective": {"type": "string", "description": "任务目标（完整目标描述）"},
            "session_id": {"type": "string", "description": "当前会话 id（可选，自动补）"},
        },
        "required": ["objective"],
    },
}

CHECKPOINT_GOAL_TOOL_DEF: dict = {
    "name": "checkpoint_goal",
    "description": (
        "任务里程碑 checkpoint（四要素，EVO-20260824-3cd4d74b）。何时用: 每个有意义里程碑"
        "（重要发现/决策/实质编辑/验证结果/阻塞状态变化）后；交接/模型切换/回合结束前；"
        "距上次 checkpoint 已 5 个实质工具调用。四要素: what（本里程碑变化）/ evidence"
        "（权威证据）/ path（影响路径或外部状态）/ next（确切下一步）。checkpoint 复用"
        "audit 单一数据源，不双写。何时不用: 无实质变化时。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "目标 id（get_goal 返回）"},
            "what": {"type": "string", "description": "本里程碑变化（What）"},
            "evidence": {"type": "string", "description": "权威证据（Evidence，工具回执/文件路径/状态）"},
            "path": {"type": "string", "description": "影响路径或外部状态（Path）"},
            "next": {"type": "string", "description": "确切下一步（Next）"},
        },
        "required": ["goal_id", "what"],
    },
}

GET_GOAL_TOOL_DEF: dict = {
    "name": "get_goal",
    "description": (
        "获取当前任务目标 + 最近 checkpoints（恢复上下文，EVO-20260824-3cd4d74b）。何时用: "
        "会话恢复/模型切换/交接后，用返回的 checkpoints 作 handoff 上下文；恢复时先验证"
        "worktree/外部状态（git status、文件 mtime、演进建议状态）再依赖内容。何时不用: "
        "无活动目标时。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "目标 id（可选；缺省返回最近 active 或最近一条）"},
        },
    },
}

UPDATE_GOAL_TOOL_DEF: dict = {
    "name": "update_goal",
    "description": (
        "更新任务目标状态（EVO-20260824-3cd4d74b）。status=complete 仅当全部需求已用当前"
        "证据验证（对照工具回执如实声明）；status=blocked 仅当严格阻塞条件实际满足"
        "（外部阻塞/安全边界/等人工）。何时不用: 目标仍 active 推进中。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "目标 id"},
            "status": {"type": "string", "enum": ["complete", "blocked"], "description": "新状态"},
            "reason": {"type": "string", "description": "blocked 理由 / complete 验证摘要（可选）"},
        },
        "required": ["goal_id", "status"],
    },
}

GOAL_TOOL_DEFS = [CREATE_GOAL_TOOL_DEF, CHECKPOINT_GOAL_TOOL_DEF, GET_GOAL_TOOL_DEF, UPDATE_GOAL_TOOL_DEF]


def _store(ctx: Any, audit_dir: str | None) -> GoalStore | None:
    """从 audit_dir 构建 GoalStore（无目录/不可写返回 None，fail-open）."""
    if not audit_dir:
        return None
    try:
        return GoalStore(audit_dir)
    except OSError:
        return None


def run_create_goal(ctx: Any, host: Any, args: dict) -> ToolResult:
    objective = str(args.get("objective", "")).strip()
    if not objective:
        return ToolResult(ToolResultStatus.FAILURE, "[参数错误] 缺少必填参数 'objective'（任务目标）", "", "create_goal")
    store = _store(ctx, str(host.audit_dir) if host.audit_dir else None)
    if store is None:
        return ToolResult(ToolResultStatus.FAILURE, "[goal 存储不可用] audit_dir 未装配", "", "create_goal")
    sid = str(args.get("session_id", "") or getattr(ctx, "session_id", ""))
    g = store.create(objective, session_id=sid)
    return ToolResult(
        ToolResultStatus.SUCCESS,
        f"[目标已创建] id={g.id} status=active\n目标: {g.objective[:200]}\n有界推进: 里程碑 checkpoint 收敛，禁止无界循环；遇边界暂停等人工确认。",
        "", "create_goal",
    )


def run_checkpoint_goal(ctx: Any, host: Any, args: dict) -> ToolResult:
    store = _store(ctx, str(host.audit_dir) if host.audit_dir else None)
    if store is None:
        return ToolResult(ToolResultStatus.FAILURE, "[goal 存储不可用] audit_dir 未装配", "", "checkpoint_goal")
    gid = str(args.get("goal_id", "")).strip()
    what = str(args.get("what", "")).strip()
    if not gid or not what:
        return ToolResult(ToolResultStatus.FAILURE, "[参数错误] 缺少必填参数 goal_id / what", "", "checkpoint_goal")
    try:
        updated = store.checkpoint(
            gid,
            what=what,
            evidence=str(args.get("evidence", "")).strip(),
            path=str(args.get("path", "")).strip(),
            next_step=str(args.get("next", "")).strip(),
        )
    except ValueError as exc:
        return ToolResult(ToolResultStatus.FAILURE, f"[参数错误] {exc}", "", "checkpoint_goal")
    if updated is None:
        return ToolResult(ToolResultStatus.FAILURE, f"[checkpoint 失败] 目标 {gid} 不存在或非 active", "", "checkpoint_goal")
    n = len(updated.get("checkpoints", []))
    return ToolResult(
        ToolResultStatus.SUCCESS,
        f"[checkpoint 已记录] goal={gid} 累计 {n} 次 | 最新: {what[:100]}",
        "", "checkpoint_goal",
    )


def run_get_goal(ctx: Any, host: Any, args: dict) -> ToolResult:
    store = _store(ctx, str(host.audit_dir) if host.audit_dir else None)
    if store is None:
        return ToolResult(ToolResultStatus.FAILURE, "[goal 存储不可用] audit_dir 未装配", "", "get_goal")
    gid = str(args.get("goal_id", "") or "").strip()
    g = store.get(gid or None)
    if g is None:
        return ToolResult(ToolResultStatus.SUCCESS, "[无活动目标] 尚未 create_goal", "", "get_goal")
    cps = g.get("checkpoints", [])
    recent = cps[-3:][::-1]
    lines = [f"目标: {g.get('objective','')[:200]}", f"状态: {g.get('status')} | id={g.get('id')}"]
    if cps:
        lines.append(f"checkpoints: {len(cps)} 次")
        for cp in recent:
            lines.append(f"  [{cp.get('ts','')[11:19]}] {str(cp.get('what',''))[:80]}")
    else:
        lines.append("checkpoints: 无（首个里程碑后 checkpoint_goal）")
    lines.append("恢复注意: 先验证 worktree/外部状态再依赖上述内容（RULE-AI-12）")
    return ToolResult(ToolResultStatus.SUCCESS, "\n".join(lines), "", "get_goal")


def run_update_goal(ctx: Any, host: Any, args: dict) -> ToolResult:
    store = _store(ctx, str(host.audit_dir) if host.audit_dir else None)
    if store is None:
        return ToolResult(ToolResultStatus.FAILURE, "[goal 存储不可用] audit_dir 未装配", "", "update_goal")
    gid = str(args.get("goal_id", "")).strip()
    status = str(args.get("status", "")).strip()
    if not gid or status not in ("complete", "blocked"):
        return ToolResult(ToolResultStatus.FAILURE, f"[参数错误] goal_id + status ∈ {{complete, blocked}}", "", "update_goal")
    g = store.update(gid, status, reason=str(args.get("reason", "")).strip())
    if g is None:
        return ToolResult(ToolResultStatus.FAILURE, f"[更新失败] 目标 {gid} 不存在", "", "update_goal")
    return ToolResult(
        ToolResultStatus.SUCCESS,
        f"[目标已更新] {gid} → {status}" + (f"\n理由: {str(args.get('reason',''))[:150]}" if args.get("reason") else ""),
        "", "update_goal",
    )

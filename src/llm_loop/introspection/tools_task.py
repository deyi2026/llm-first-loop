"""Task Frontier 工具实现（DESIGN-20260828，GOAL-20260828-df03e08e T1）.

3 个工具（程序记账/模型决策，设计 §2）:
- task_create: 建任务（title/acceptance 必填；依赖须同 goal 内已存在；≤40/goal）
- task_update: 状态推进（合法转移表/evidence_refs 校验/blocked_reason 必填；acceptance 修订留痕）
- task_frontier: 全图查询（ready/in_progress/blocked/waiting/done/unreachable/premise_stale）

存储: audit_dir/tasks/<goal_id>.jsonl append-only last-wins（task_store.py）。
"""

from __future__ import annotations

from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.goal import GoalStore, GoalStoreCorruptionError
from llm_loop.introspection.task_store import TASK_LIMIT_PER_GOAL, TaskStore

TASK_CREATE_TOOL_DEF: dict = {
    "name": "task_create",
    "description": (
        "创建执行任务（Task Frontier 账本，DESIGN-20260828）。何时用: 长任务拆解为可验收"
        "子任务时——程序记结构/依赖/状态，模型定优先级。acceptance 必填（可验收陈述），"
        "evidence_required=true 的任务完成后必须提供 evidence:// 引用。依赖环由程序检测。"
        "何时不用: 简单任务直接做；无活动 goal 时先 create_goal。失败对策: goal 非 active /"
        "依赖不存在 / 超 40 上限会如实拒绝。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "所属目标 id（必填，get_goal 可查）"},
            "title": {"type": "string", "description": "任务标题（一句话）"},
            "acceptance": {
                "type": "array", "items": {"type": "string"},
                "description": "验收条件（必填，可验收陈述列表）",
            },
            "done_when": {
                "type": "array", "items": {"type": "string"},
                "description": "完成判据（可选，比 acceptance 更具体的可观测信号）",
            },
            "dependencies": {
                "type": "array", "items": {"type": "string"},
                "description": "依赖的 task_id 列表（须同 goal 内已存在，可空）",
            },
            "parent_id": {"type": "string", "description": "父任务 id（可选，层次结构）"},
            "evidence_required": {
                "type": "boolean",
                "description": "完成时是否必须提供 evidence:// 引用（默认 false）",
            },
        },
        "required": ["goal_id", "title", "acceptance"],
    },
}

TASK_UPDATE_TOOL_DEF: dict = {
    "name": "task_update",
    "description": (
        "推进任务状态（领取/完成/阻塞/重开）。合法转移: pending→in_progress/cancelled/"
        "failed; in_progress→done/blocked/cancelled/failed; blocked→in_progress/cancelled/"
        "failed; done→in_progress(重开,下游自动标 premise_stale)/failed; failed→in_progress"
        "(重试)。→done 且 evidence_required=true 时必须 evidence_refs；→blocked 必须"
        "blocked_reason。acceptance 修订会留痕（acceptance_revised，历史不可篡改）。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "所属目标 id（必填）"},
            "task_id": {"type": "string", "description": "任务 id（必填）"},
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "blocked", "done", "failed", "cancelled"],
                "description": "目标状态（转移须合法，非法转移会被拒绝）",
            },
            "blocked_reason": {"type": "string", "description": "阻塞原因（→blocked 必填）"},
            "evidence_refs": {
                "type": "array", "items": {"type": "string"},
                "description": "证据引用（evidence:// 开头；evidence_required 任务 →done 必填）",
            },
            "acceptance": {
                "type": "array", "items": {"type": "string"},
                "description": "修订验收条件（留痕，不可用于洗白已 done 任务）",
            },
            "done_when": {"type": "array", "items": {"type": "string"}, "description": "修订完成判据"},
            "title": {"type": "string", "description": "修订标题"},
        },
        "required": ["goal_id", "task_id"],
    },
}

TASK_FRONTIER_TOOL_DEF: dict = {
    "name": "task_frontier",
    "description": (
        "查看任务图 frontier（当前可执行集 + 全图状态）。何时用: 长任务每轮决策前/"
        "会话恢复后/不确定下一步时。默认渲染 ready/in_progress/blocked/unreachable/"
        "premise_stale；full=true 含 waiting(pending 非 ready) 与已完成任务证据。"
        "何时不用: 无任务图时（返回空）。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "目标 id（可选，默认当前会话）"},
            "full": {"type": "boolean", "description": "true=全图含 waiting/done 详情（默认 false）"},
        },
        "required": [],
    },
}


def _audit_dir(host: Any) -> str | None:
    d = getattr(host, "audit_dir", None)
    return str(d) if d else None


def _require_active_goal(ctx: Any, host: Any, goal_id: str) -> tuple[str | None, str]:
    """goal 存在且 active 才允许改任务图（done goal 修改走人工/新 goal）."""
    audit = _audit_dir(host)
    if not audit:
        return None, "[存储不可用] audit_dir 未装配"
    try:
        g = GoalStore(audit).get(goal_id)
    except GoalStoreCorruptionError as exc:
        return None, f"[goal 存储损坏] {exc}"
    if g is None:
        return None, f"[goal 不存在] {goal_id}（先 create_goal）"
    if str(g.get("status", "")) != "active":
        return None, f"[goal 非 active] {goal_id} status={g.get('status')}（重开 goal 任务请人工/新建 goal）"
    return audit, ""


def run_task_create(ctx: Any, host: Any, args: dict) -> ToolResult:
    name = "task_create"
    goal_id = str(args.get("goal_id", "") or "").strip()
    if not goal_id:
        return ToolResult(ToolResultStatus.FAILURE, "[参数错误] 缺少必填 'goal_id'", "", name)
    audit, err = _require_active_goal(ctx, host, goal_id)
    if err:
        return ToolResult(ToolResultStatus.FAILURE, err, "", name)
    try:
        store = TaskStore(audit)
        acc = args.get("acceptance") or []
        task = store.create(
            goal_id,
            str(args.get("title", "")),
            acceptance=[str(a) for a in acc],
            done_when=[str(w) for w in (args.get("done_when") or [])],
            dependencies=[str(d) for d in (args.get("dependencies") or [])],
            parent_id=str(args.get("parent_id", "") or ""),
            evidence_required=bool(args.get("evidence_required", False)),
        )
    except ValueError as exc:
        return ToolResult(ToolResultStatus.FAILURE, f"[拒绝] {exc}", "", name)
    dep_note = f" | deps: {','.join(task.dependencies)}" if task.dependencies else ""
    ev_note = " | evidence_required" if task.evidence_required else ""
    return ToolResult(
        ToolResultStatus.SUCCESS,
        "[任务已建] {} {}\nacceptance: {}{}{}\n上限提示: 每 goal ≤{} 任务（防粒度失控）".format(
            task.task_id, task.title[:80], "; ".join(task.acceptance)[:150], dep_note, ev_note, TASK_LIMIT_PER_GOAL
        ),
        "", name,
    )


def run_task_update(ctx: Any, host: Any, args: dict) -> ToolResult:
    name = "task_update"
    goal_id = str(args.get("goal_id", "") or "").strip()
    task_id = str(args.get("task_id", "") or "").strip()
    if not goal_id or not task_id:
        return ToolResult(ToolResultStatus.FAILURE, "[参数错误] 必填 'goal_id' 和 'task_id'", "", name)
    audit, err = _require_active_goal(ctx, host, goal_id)
    if err:
        return ToolResult(ToolResultStatus.FAILURE, err, "", name)
    try:
        store = TaskStore(audit)
        task = store.update(
            goal_id,
            task_id,
            status=(str(args["status"]) if args.get("status") else None),
            blocked_reason=(str(args["blocked_reason"]) if args.get("blocked_reason") else None),
            evidence_refs=([str(r) for r in args["evidence_refs"]] if args.get("evidence_refs") is not None else None),
            acceptance=([str(a) for a in args["acceptance"]] if args.get("acceptance") is not None else None),
            done_when=([str(w) for w in args["done_when"]] if args.get("done_when") is not None else None),
            title=(str(args["title"]) if args.get("title") else None),
        )
    except ValueError as exc:
        return ToolResult(ToolResultStatus.FAILURE, f"[拒绝] {exc}", "", name)
    extra = []
    if task.status == "done" and task.acceptance:
        extra.append(f"acceptance: {'; '.join(task.acceptance)[:150]}")
    if task.acceptance_revised:
        extra.append("⚠ acceptance_revised=true（修订已留痕）")
    if task.premise_stale:
        extra.append("⚠ premise_stale=true（前置已重开，结论请复核）")
    body = f"[已更新] {task.task_id} → {task.status}"
    if task.status == "blocked":
        body += f" | reason: {task.blocked_reason[:100]}"
    if task.evidence_refs:
        body += f" | evidence: {len(task.evidence_refs)} refs"
    return ToolResult(ToolResultStatus.SUCCESS, "\n".join([body] + extra), "", name)


def run_task_frontier(ctx: Any, host: Any, args: dict) -> ToolResult:
    name = "task_frontier"
    audit = _audit_dir(host)
    if not audit:
        return ToolResult(ToolResultStatus.FAILURE, "[存储不可用] audit_dir 未装配", "", name)
    goal_id = str(args.get("goal_id", "") or "").strip()
    if not goal_id:
        try:
            g = GoalStore(audit).get(prefer_session_id=_current_sid(ctx))
        except GoalStoreCorruptionError:
            g = None
        goal_id = str((g or {}).get("id", "")) if g else ""
    if not goal_id:
        return ToolResult(ToolResultStatus.SUCCESS, "[无任务图] 当前无活动 goal（先 create_goal + task_create）", "", name)
    store = TaskStore(audit)
    if store.count_for_goal(goal_id) == 0:
        return ToolResult(ToolResultStatus.SUCCESS, f"[无任务图] goal {goal_id} 尚无任务", "", name)
    full = bool(args.get("full", False))
    lines = [store.render_frontier(goal_id, compact=False)]
    if full:
        fr = store.compute_frontier(goal_id)
        done_ids = {t.task_id for t in fr["completed"]}
        waiting = []
        for t in store.list_for_goal(goal_id):
            if t.status == "pending" and all(d in done_ids for d in t.dependencies) is False and t not in fr["unreachable"]:
                waiting.append(t)
        if waiting:
            lines.append("  -- waiting（依赖未满足，正常排队）--")
            for t in waiting[:12]:
                miss = [d for d in t.dependencies if d not in done_ids]
                lines.append(f"  … waiting {t.task_id} {t.title[:40]} ← 待 {','.join(miss[:3])}")
        lines.append("  -- done --")
        for t in fr["completed"][:20]:
            ev = f" | {len(t.evidence_refs)}ev" if t.evidence_refs else ""
            rev = " | revised" if t.acceptance_revised else ""
            lines.append(f"  ✓ {t.task_id} {t.title[:50]}{ev}{rev}")
    ok, detail = store.goal_completion_ready(goal_id)
    if ok:
        lines.append("  [goal 可 complete] 无 open 任务（blocked/failed 需 waive 请人工确认）")
    else:
        lines.append(f"  [goal 未完成] open 详情: {detail}")
    return ToolResult(ToolResultStatus.SUCCESS, "\n".join(lines), "", name)


def _current_sid(ctx: Any) -> str:
    try:
        from llm_loop.introspection.tools_status import current_session_id

        return current_session_id(ctx)
    except Exception:  # noqa: BLE001
        return ""


TASK_TOOL_DEFS: list[dict] = [TASK_CREATE_TOOL_DEF, TASK_UPDATE_TOOL_DEF, TASK_FRONTIER_TOOL_DEF]

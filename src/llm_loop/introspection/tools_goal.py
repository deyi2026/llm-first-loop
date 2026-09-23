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
from llm_loop.introspection.goal import GoalStore, GoalStoreCorruptionError

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
            "method_use_gate": {
                "type": "boolean",
                "description": (
                    "goal 级方法 use 硬门（EVO-20260923-618f7fd1 ②，默认 false）。开启后: "
                    "本 goal 下 evidence_required 任务 →done 前，需本会话至少一条 "
                    "method_manage(action=record_use) 或 task_update(method_no_contact=true) "
                    "显式声明。何时用: 用户明确要求强化方法回记纪律的长任务。"
                ),
            },
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
        "读取 durable Goal 事实源：当前活动目标 + 最近 checkpoints。适用于用户明确继续/恢复"
        "持久任务、模型切换/交接后确认当前 Goal，或已知 goal_id 需要读取。只返回已记录事实，"
        "不替模型决定下一步；具体 task 状态与可执行 frontier 用 task_frontier。无活动 Goal 时返回空。"
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
        "更新任务目标状态（EVO-20260824-3cd4d74b；终局证据门 EVO-20260923-6bcc4880）。"
        "status=complete 仅当全部需求已用当前证据验证: 程序级强制——任务图 open 任务须清零、"
        "evidence_required 任务须 evidence verified；无 done 任务依托（空任务图）时须自报"
        " evidence_refs 并通过真实性校验，否则 BLOCKED 拒绝书写。status=blocked 仅当严格"
        "阻塞条件实际满足（外部阻塞/安全边界/等人工），blocked 不走证据门。"
        "何时不用: 目标仍 active 推进中。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "目标 id"},
            "status": {"type": "string", "enum": ["complete", "blocked"], "description": "新状态"},
            "reason": {"type": "string", "description": "blocked 理由 / complete 验证摘要（可选）"},
            "evidence_refs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "终局证据引用（可选；空任务图 complete 时必填，evidence:// 引用，"
                "须过 TaskEvidenceVerifier 真实性校验）",
            },
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
    explicit_sid = str(args.get("session_id", "") or "").strip()
    if explicit_sid:
        sid = explicit_sid
    else:
        from llm_loop.introspection.tools_status import bound_session_id

        sid = bound_session_id()
        if not sid:
            return ToolResult(
                ToolResultStatus.FAILURE,
                "[会话归属不可用] 当前执行没有可证明的 session binding；未创建 Goal。",
                "",
                "create_goal",
            )
    g = store.create(
        objective,
        session_id=sid,
        method_use_gate=bool(args.get("method_use_gate", False)),
    )
    gate_note = (
        " method_use_gate=on（evidence_required 任务 →done 需 record_use 或显式声明）"
        if g.method_use_gate
        else ""
    )
    return ToolResult(
        ToolResultStatus.SUCCESS,
        f"[目标已创建] id={g.id} status=active\n目标: {g.objective[:200]}\n有界推进: 里程碑 checkpoint 收敛，禁止无界循环；遇边界暂停等人工确认。{gate_note}",
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
    except GoalStoreCorruptionError as exc:
        return ToolResult(
            ToolResultStatus.FAILURE,
            f"[goal 存储损坏] {exc}",
            "",
            "checkpoint_goal",
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
    try:
        if gid:
            g = store.get(gid)
        else:
            from llm_loop.introspection.tools_status import bound_session_id

            sid = bound_session_id()
            g = store.get(prefer_session_id=sid, strict_session=True) if sid else None
    except GoalStoreCorruptionError as exc:
        return ToolResult(
            ToolResultStatus.FAILURE,
            f"[goal 存储损坏] {exc}\n请先检查/修复 goals.jsonl，再恢复任务；程序不会猜测旧 Goal。",
            "",
            "get_goal",
        )
    if g is None:
        if gid:
            return ToolResult(ToolResultStatus.FAILURE, f"[目标不存在] {gid}", "", "get_goal")
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
    # DESIGN-20260828: 任务图摘要（跨会话恢复一并可见，fail-open）
    if host.audit_dir:
        try:
            from llm_loop.introspection.task_store import TaskStore

            _ts = TaskStore(str(host.audit_dir)).summary_line(str(g.get("id", "")))
            if _ts:
                lines.append(_ts)
        except Exception:  # noqa: BLE001
            pass
    return ToolResult(ToolResultStatus.SUCCESS, "\n".join(lines), "", "get_goal")


def run_update_goal(ctx: Any, host: Any, args: dict) -> ToolResult:
    store = _store(ctx, str(host.audit_dir) if host.audit_dir else None)
    if store is None:
        return ToolResult(ToolResultStatus.FAILURE, "[goal 存储不可用] audit_dir 未装配", "", "update_goal")
    gid = str(args.get("goal_id", "")).strip()
    status = str(args.get("status", "")).strip()
    if not gid or status not in ("complete", "blocked"):
        return ToolResult(ToolResultStatus.FAILURE, "[参数错误] goal_id + status ∈ {complete, blocked}", "", "update_goal")
    # EVO-20260923-6bcc4880: 证据门前置可读性探针——goal 记录损坏/不存在优先如实报告，
    # 不被证据门 BLOCKED 掩盖诊断（与 store.update 既有错误分支同文案）。
    try:
        _probe = store.get(gid)
    except GoalStoreCorruptionError as exc:
        return ToolResult(
            ToolResultStatus.FAILURE,
            f"[goal 存储损坏] {exc}",
            "",
            "update_goal",
        )
    if _probe is None:
        return ToolResult(ToolResultStatus.FAILURE, f"[更新失败] 目标 {gid} 不存在", "", "update_goal")
    # DESIGN-20260828 Task Frontier §2.1: complete 前置校验——任务图存在 open 任务时
    # 拒绝收口（pending/in_progress 需推进终态；blocked/failed 需取消或人工 waive）。
    # EVO-20260923-6bcc4880 §步骤2: 终局证据硬门——complete 是终局裁决书写，
    # 无程序可验证据即 BLOCKED 拒绝书写（拒绝的是书写，不是记录：ToolResult 进历史/事件流）；
    # blocked 是异常出口，不走此门。账本不可读时 fail-closed（不写终局，非照写）。
    if status == "complete" and host.audit_dir:
        try:
            from llm_loop.introspection.task_store import TaskStore

            _ts = TaskStore(str(host.audit_dir))
            _ok, _detail = _ts.goal_completion_ready(gid)
            if not _ok:
                return ToolResult(
                    ToolResultStatus.FAILURE,
                    f"[收口拒绝] goal {gid} 任务图仍有 open 任务（{_detail}）。\n"
                    "先 task_update 推进终态（done/failed/cancelled）；blocked/failed 的"
                    "残留如需放弃，转 cancelled 并在 goal reason 说明，或请人工确认 waive。",
                    "",
                    "update_goal",
                )
            _tasks = _ts.list_for_goal(gid)
            _unverified = [
                t.task_id
                for t in _tasks
                if t.evidence_required and t.evidence_verification_status != "verified"
            ]
            if _unverified:
                return ToolResult(
                    ToolResultStatus.BLOCKED,
                    "[终局证据门] reason_code=evidence_unverified\n"
                    f"goal {gid} 存在 evidence_required 任务未过真实性校验: "
                    f"{', '.join(_unverified[:5])}\n"
                    "出口: 补齐 evidence_refs 重新验证，或请人工确认 waive；"
                    "证据 verified 前 complete 拒绝书写。",
                    "",
                    "update_goal",
                )
            if not any(t.status == "done" for t in _tasks):
                # 零依托终局（空任务图/全非 done）: 自报 evidence_refs 过 verifier 才可书写
                _refs = [str(r) for r in args["evidence_refs"]] if args.get("evidence_refs") else []
                if not _refs:
                    return ToolResult(
                        ToolResultStatus.BLOCKED,
                        "[终局证据门] reason_code=no_finality_evidence\n"
                        f"goal {gid} 无 done 任务依托，complete 需自报 evidence_refs"
                        "（evidence:// 引用）并通过真实性校验。\n"
                        "出口: 带已核验证据 refs 重试、建任务图推进后收口，或请人工确认 waive。",
                        "",
                        "update_goal",
                    )
                _verifier = getattr(getattr(host, "ctx", None), "task_evidence_verifier", None)
                if _verifier is None:
                    return ToolResult(
                        ToolResultStatus.BLOCKED,
                        "[终局证据门] reason_code=probe_unavailable\n"
                        "task_evidence_verifier 未装配，无法校验自报 evidence_refs；"
                        "complete 拒绝书写（fail-closed）。\n出口: 修复装配后重试，或请人工确认 waive。",
                        "",
                        "update_goal",
                    )
                _report = _verifier.verify(_refs)
                if getattr(_report, "status", "") != "verified":
                    return ToolResult(
                        ToolResultStatus.BLOCKED,
                        "[终局证据门] reason_code=evidence_below_threshold\n"
                        f"自报 evidence_refs 校验未通过（status={getattr(_report, 'status', '')}）。\n"
                        "出口: 修正引用后重试，或请人工确认 waive。",
                        "",
                        "update_goal",
                    )
        except Exception as exc:  # noqa: BLE001 — EVO-20260923: 账本不可读 → 不写终局（fail-closed）
            return ToolResult(
                ToolResultStatus.BLOCKED,
                f"[终局证据门] reason_code=probe_unavailable\n任务账本不可读（{exc}）；"
                "complete 拒绝书写（fail-closed）。\n出口: 修复账本可读性后重试，或请人工确认 waive。",
                "",
                "update_goal",
            )
    try:
        g = store.update(gid, status, reason=str(args.get("reason", "")).strip())
    except GoalStoreCorruptionError as exc:
        return ToolResult(
            ToolResultStatus.FAILURE,
            f"[goal 存储损坏] {exc}",
            "",
            "update_goal",
        )
    except ValueError as exc:
        return ToolResult(ToolResultStatus.FAILURE, f"[状态更新拒绝] {exc}", "", "update_goal")
    if g is None:
        return ToolResult(ToolResultStatus.FAILURE, f"[更新失败] 目标 {gid} 不存在", "", "update_goal")
    return ToolResult(
        ToolResultStatus.SUCCESS,
        f"[目标已更新] {gid} → {status}" + (f"\n理由: {str(args.get('reason',''))[:150]}" if args.get("reason") else ""),
        "", "update_goal",
    )

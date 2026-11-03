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
from llm_loop.introspection.task_claim import (
    ClaimError,
    ClaimRefusedError,
    ClaimStore,
    now_ms,
    overlapping_paths,
)
from llm_loop.introspection.task_evidence import TaskEvidenceVerificationError
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
            "blocked_by_goals": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "跨 goal 依赖的 goal_id 列表（DESIGN-20261101 §4.5，可空）。语义: 所列 goal"
                    " 全部 complete 后本任务才可能 ready；上游 goal blocked/cancelled 时本任务"
                    "计入 blocked（reason_code=upstream_goal_aborted），不自动 failed。"
                    "何时不用: 同 goal 内部顺序用 dependencies；跨 goal 依赖成环会被程序拒绝"
                    "（dependency_cycle）。"
                ),
            },
            "deadline_at": {
                "type": "string",
                "description": (
                    "跨 goal 等待期限（ISO 时间，可空）。到期上游仍未 complete → 本任务转"
                    " blocked(reason_code=upstream_deadline_exceeded)，避免无限期悬挂。"
                ),
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
        "blocked_reason。done→非done 属显式重开：模型须依据当前用户指令判断是否获授权，"
        "并仅在确认当前授权时传 confirm=true；程序只校验该显式动作位，不解析用户措辞。"
        "声明 evidence_refs 的完成记录会机械检查当前可信 owner 下的引用存在性和 blob 完整性；"
        "不判断证据充分性、重要性或任务是否语义完成。acceptance 修订会留痕"
        "（acceptance_revised，历史不可篡改）。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "所属目标 id（必填）"},
            "task_id": {"type": "string", "description": "任务 id（必填）"},
            "claim_token": {
                "type": "string",
                "description": (
                    "claim 令牌（claim_task/renew_task 回执的 token，形如 CLM-xxxx#3）。"
                    "传了就必须完全对得上（含 generation），否则拒绝——这是过期 holder 的"
                    "迟到写入被挡住的地方。不传=兼容旧调用（warn 模式照常写入，冲突时回执"
                    "给 claim_conflict_warning；pending→in_progress 会自动签发 claim）。"
                ),
            },
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
            "confirm": {
                "type": "boolean",
                "description": (
                    "仅 done→非done 重开使用。模型依据当前真实用户指令判断；确认用户已授权本次重开时传 true。"
                    "程序不从‘继续/重做’等词语推断该值。"
                ),
            },
        },
        "required": ["goal_id", "task_id"],
    },
}

TASK_FRONTIER_TOOL_DEF: dict = {
    "name": "task_frontier",
    "description": (
        "读取 durable Task 图事实源：ready/in_progress/blocked/unreachable/premise_stale 等当前状态。"
        "适用于已存在 Goal、需要确认当前执行 frontier；goal_id 省略或 current/active 时解析当前活动 Goal。"
        "full=true 额外返回 waiting 与 done 证据。它不是历史对话搜索，也不替模型制定下一步；"
        "历史事实用 search_records/search_archive。"
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


def _require_active_goal(ctx: Any, host: Any, goal_id: str) -> tuple[str | None, str, str]:
    """返回 (audit_dir, err, note)；note 为归属判定产生的放行标注（可空）。

    goal 存在且 active 才允许改任务图（done goal 修改走人工/新 goal）。
    本函数**不**向 resolve_write_permission 传 args（P1-6）：task_* 不接 cross_session，
    拒绝文案已明确写"本工具没有跨会话出口"，代码不得支持文案否认的通道（同一目标两套真值）。
    """
    audit = _audit_dir(host)
    if not audit:
        return None, "[存储不可用] audit_dir 未装配", ""
    try:
        g = GoalStore(audit).get(goal_id)
    except GoalStoreCorruptionError as exc:
        return None, f"[goal 存储损坏] {exc}", ""
    if g is None:
        return None, f"[goal 不存在] {goal_id}（先 create_goal）", ""
    if str(g.get("status", "")) != "active":
        return None, f"[goal 非 active] {goal_id} status={g.get('status')}（重开 goal 任务请人工/新建 goal）", ""
    # DESIGN-20261101 §4.3: 任务图写侧同源归属校验——goal 归属其他会话时拒绝改其任务图
    from llm_loop.introspection.goal_coordination import (
        resolve_write_permission,
        write_refusal_text,
    )

    _perm = resolve_write_permission(g)
    if _perm["decision"] == "deny":
        return None, write_refusal_text(goal_id, _perm, supports_cross_session=False), ""
    return audit, "", str(_perm.get("note") or "")


def run_task_create(ctx: Any, host: Any, args: dict) -> ToolResult:
    name = "task_create"
    goal_id = str(args.get("goal_id", "") or "").strip()
    if not goal_id:
        return ToolResult(ToolResultStatus.FAILURE, "[参数错误] 缺少必填 'goal_id'", "", name)
    audit, err, _perm_note = _require_active_goal(ctx, host, goal_id)
    if err:
        return ToolResult(ToolResultStatus.FAILURE, err, "", name)
    assert audit is not None  # _require_active_goal 契约：err 为空 ⟺ audit 非 None
    try:
        store = TaskStore(audit)
        acc = args.get("acceptance") or []
        task = store.create(
            goal_id,
            str(args.get("title", "")),
            acceptance=[str(a) for a in acc],
            done_when=[str(w) for w in (args.get("done_when") or [])],
            dependencies=[str(d) for d in (args.get("dependencies") or [])],
            blocked_by_goals=[str(g) for g in (args.get("blocked_by_goals") or [])],
            deadline_at=str(args.get("deadline_at", "") or ""),
            parent_id=str(args.get("parent_id", "") or ""),
            evidence_required=bool(args.get("evidence_required", False)),
        )
    except ValueError as exc:
        return ToolResult(ToolResultStatus.FAILURE, f"[拒绝] {exc}", "", name)
    dep_note = f" | deps: {','.join(task.dependencies)}" if task.dependencies else ""
    if task.blocked_by_goals:
        dep_note += f" | xdeps: {','.join(task.blocked_by_goals)}"
    ev_note = " | evidence_required" if task.evidence_required else ""
    if _perm_note:
        ev_note += f"\n注意: {_perm_note}"
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
    audit, err, _perm_note = _require_active_goal(ctx, host, goal_id)
    if err:
        return ToolResult(ToolResultStatus.FAILURE, err, "", name)
    assert audit is not None  # _require_active_goal 契约：err 为空 ⟺ audit 非 None
    target = str(args.get("status") or "").strip()
    try:
        verifier = getattr(getattr(host, "ctx", None), "task_evidence_verifier", None)
        store = TaskStore(audit, evidence_verifier=verifier)
        # 归属门已由上面的 _require_active_goal（resolve_write_permission）通过，
        # 这里显式传 authorized=True，避免组合入口依赖"调用方隐式已校验"的顺序事实。
        # 直接调 ClaimStore 而不是 TaskStore.update_with_claim：后者会让 task_store
        # 依赖 task_claim，形成 task_claim<->task_store 运行期环（arch guard R9-P2-06a）。
        task, claim_notes = ClaimStore(audit).update_task_under_claim(
            store,
            goal_id,
            task_id,
            token=(str(args["claim_token"]) if args.get("claim_token") else None),
            authorized=True,
            status=(target if target else None),
            blocked_reason=(str(args["blocked_reason"]) if args.get("blocked_reason") else None),
            evidence_refs=([str(r) for r in args["evidence_refs"]] if args.get("evidence_refs") is not None else None),
            acceptance=([str(a) for a in args["acceptance"]] if args.get("acceptance") is not None else None),
            done_when=([str(w) for w in args["done_when"]] if args.get("done_when") is not None else None),
            title=(str(args["title"]) if args.get("title") else None),
            confirm=bool(args.get("confirm", False)),
        )
    except TaskEvidenceVerificationError as exc:
        return ToolResult(
            ToolResultStatus.FAILURE,
            f"[证据真实性校验失败] status={exc.status}",
            "",
            name,
        )
    except ClaimError as exc:
        return ToolResult(
            ToolResultStatus.FAILURE,
            f"[claim 拒绝] reason_code={exc.code} | {exc.message}",
            "",
            name,
        )
    except ValueError as exc:
        return ToolResult(ToolResultStatus.FAILURE, f"[拒绝] {exc}", "", name)
    extra = []
    if claim_notes.get("auto_claimed"):
        extra.append(
            f"claim: 自动签发 → {claim_notes['auto_claimed']}"
            "（pending→in_progress 由程序隐式 claim，后续写入请带该 token）"
        )
    if claim_notes.get("claim_renewed"):
        extra.append("claim: 已随本次写入续租")
    if claim_notes.get("claim_expired_renewed"):
        extra.append("claim: 已过期但无人接管 → 本次写入放行并顺带续期（软过期）")
    if claim_notes.get("revoked_claim_id"):
        extra.append(f"claim: 重开前已撤销旧 claim {claim_notes['revoked_claim_id']}")
    if claim_notes.get("claim_unavailable"):
        extra.append("claim: 当前无 run 身份，未签发/校验 fencing（本次写入未受保护）")
    if claim_notes.get("claim_conflict_warning"):
        extra.append(
            f"⚠ claim_conflict_warning: 任务由 {claim_notes['claim_conflict_warning']} 持有，"
            "本次写入未被 fencing 保护（warn 模式；PR-2 才硬拒）"
        )
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
    if task.evidence_verification_status == "verified":
        body += " | evidence_verification=verified"
    # 归属放行标注必须随成功回执可见（owner_unknown / session_unverified 都是 fail-open 放行，
    # 只落审计、不在回执留痕会让调用方误以为写入是按 owner 校验过的）
    if _perm_note:
        extra.append(f"注意: {_perm_note}")
    return ToolResult(ToolResultStatus.SUCCESS, "\n".join([body] + extra), "", name)


def run_task_frontier(ctx: Any, host: Any, args: dict) -> ToolResult:
    name = "task_frontier"
    audit = _audit_dir(host)
    if not audit:
        return ToolResult(ToolResultStatus.FAILURE, "[存储不可用] audit_dir 未装配", "", name)
    goal_id = str(args.get("goal_id", "") or "").strip()
    if goal_id.casefold() in {"current", "active", "当前", "当前目标", "当前任务"}:
        goal_id = ""
    if not goal_id:
        try:
            from llm_loop.introspection.tools_status import bound_session_id

            sid = bound_session_id()
            g = (
                GoalStore(audit).get(prefer_session_id=sid, strict_session=True)
                if sid
                else None
            )
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
        lines.append("  goal_completion_ready=true")
    else:
        lines.append(f"  goal_completion_ready=false | {detail}")
    return ToolResult(ToolResultStatus.SUCCESS, "\n".join(lines), "", name)


def _current_sid(ctx: Any) -> str:
    try:
        from llm_loop.introspection.tools_status import current_session_id

        return current_session_id(ctx)
    except Exception:  # noqa: BLE001
        return ""


CLAIM_TOOL_DEF: dict = {
    "name": "claim_task",
    "description": (
        "领取任务执行权（claim 层，DESIGN-20261103 §6.1）。何时用: 准备长时间推进某任务、"
        "或与其它 run 可能同时改同一任务时——先 claim 拿到 fencing token，再用该 token 写"
        "task_update，过期 holder 的迟到写入才会被挡住。何时不用: 单会话短任务（task_update "
        "会自动隐式 claim）；只读查询不需要。失败对策: task_claimed_by_other→等过期或用"
        "release_task 协调；claim_quota_exceeded→先释放不用的 claim；"
        "task_not_claimable→done/failed 任务先重开。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "目标 id（必填）"},
            "task_id": {"type": "string", "description": "任务 id（必填）"},
            "ttl_s": {
                "type": "integer",
                "description": "租约秒数（缺省 1800，clamp 到 [60, 28800]）。租约到期不是失败，是允许别人接管。",
            },
            "unbounded": {
                "type": "boolean",
                "description": "无期限 claim。需要 LFL_CLAIM_ALLOW_UNBOUNDED 授权，否则拒绝（默认 False）。",
            },
            "expected_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "预计改动的路径（用于与其它活跃 claim 交叉提示；只警告不拒绝）。",
            },
        },
        "required": ["goal_id", "task_id"],
    },
}

CLAIM_RENEW_TOOL_DEF: dict = {
    "name": "renew_task",
    "description": (
        "续租 claim（fencing 令牌不变，generation 不换）。何时用: 长任务执行中，租约将到期"
        "但还需要继续写。带 token 的 task_update 也会顺手续租。失败对策: claim_expired→"
        "重新 claim_task（generation 会 +1，旧 token 作废）。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string"},
            "task_id": {"type": "string"},
            "claim_token": {"type": "string", "description": "当前 token（形如 CLM-xxxx#3）"},
            "ttl_s": {"type": "integer", "description": "新的租约秒数（缺省沿用策略默认值）"},
        },
        "required": ["goal_id", "task_id", "claim_token"],
    },
}

CLAIM_RELEASE_TOOL_DEF: dict = {
    "name": "release_task",
    "description": (
        "释放 claim（显式让出执行权）。何时用: 任务做完/放弃，让别人能立刻接管而不必等过期。"
        "何时不用: 只是暂停、稍后继续 → 用 renew_task 续租即可。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string"},
            "task_id": {"type": "string"},
            "claim_token": {"type": "string", "description": "可选；给了就校验归属与 generation"},
        },
        "required": ["goal_id", "task_id"],
    },
}


def _render_claim(claim: Any, *, header: str, extra: list[str]) -> str:
    r = claim.receipt(now_ms())
    lines = [header]
    lines.append(f"  token={r['token']}  holder={r['holder']}  generation={r['generation']}")
    lines.append(
        f"  expires_at={r['expires_at']}" + ("  unbounded=true" if r["unbounded"] else f"  ttl_remaining={r['ttl_remaining_s']}s")
    )
    if r.get("renewed_after_expiry"):
        lines.append("  renewed_after_expiry=true（过期但未被接管的续期）")
    if r["expected_paths"]:
        lines.append(f"  expected_paths={r['expected_paths']}")
    lines.append("  后续 task_update 请带 claim_token=<token>，否则写入不受 fencing 保护（warn 模式）")
    lines.extend(extra)
    return "\n".join(lines)


def run_claim_task(ctx: Any, host: Any, args: dict) -> ToolResult:
    name = "claim_task"
    goal_id = str(args.get("goal_id", "") or "").strip()
    task_id = str(args.get("task_id", "") or "").strip()
    if not goal_id or not task_id:
        return ToolResult(ToolResultStatus.FAILURE, "[参数错误] goal_id 与 task_id 均必填", "", name)
    audit, err, _note = _require_active_goal(ctx, host, goal_id)
    if err:
        return ToolResult(ToolResultStatus.FAILURE, err, "", name)
    assert audit is not None
    store = TaskStore(audit)
    claims = ClaimStore(audit)
    try:
        claim = claims.grant(
            goal_id,
            task_id,
            ttl_s=args.get("ttl_s"),
            expected_paths=[str(p) for p in (args.get("expected_paths") or [])],
            unbounded=bool(args.get("unbounded", False)),
            store=store,
        )
    except ClaimRefusedError as exc:
        return ToolResult(ToolResultStatus.FAILURE, f"[claim 拒绝] reason_code={exc.code} | {exc.message}", "", name)
    except ClaimError as exc:
        return ToolResult(ToolResultStatus.FAILURE, f"[claim 不可用] reason_code={exc.code} | {exc.message}", "", name)
    extra = []
    other = [c for c in claims.active_claims(goal_id) if c.task_id != task_id]
    hits = []
    for c in other:
        for left, right in overlapping_paths(claim.expected_paths, c.expected_paths):
            hits.append(f"{left} ~ {right} ({c.task_id})")
    if hits:
        extra.append(f"  ⚠ 路径可能交叉: {hits[:3]}（只提示，不拒绝）")
    return ToolResult(ToolResultStatus.SUCCESS, _render_claim(claim, header=f"[claim 成功] {goal_id}/{task_id}", extra=extra), "", name)


def run_renew_task(ctx: Any, host: Any, args: dict) -> ToolResult:
    name = "renew_task"
    goal_id = str(args.get("goal_id", "") or "").strip()
    task_id = str(args.get("task_id", "") or "").strip()
    token = str(args.get("claim_token", "") or "").strip()
    if not goal_id or not task_id or not token:
        return ToolResult(ToolResultStatus.FAILURE, "[参数错误] goal_id/task_id/claim_token 均必填", "", name)
    audit, err, _note = _require_active_goal(ctx, host, goal_id)
    if err:
        return ToolResult(ToolResultStatus.FAILURE, err, "", name)
    assert audit is not None
    try:
        claim = ClaimStore(audit).renew(goal_id, task_id, token=token, ttl_s=args.get("ttl_s"))
    except ClaimError as exc:
        return ToolResult(ToolResultStatus.FAILURE, f"[claim 拒绝] reason_code={exc.code} | {exc.message}", "", name)
    return ToolResult(
        ToolResultStatus.SUCCESS, _render_claim(claim, header=f"[claim 续租] {goal_id}/{task_id}", extra=[]), "", name
    )


def run_release_task(ctx: Any, host: Any, args: dict) -> ToolResult:
    name = "release_task"
    goal_id = str(args.get("goal_id", "") or "").strip()
    task_id = str(args.get("task_id", "") or "").strip()
    if not goal_id or not task_id:
        return ToolResult(ToolResultStatus.FAILURE, "[参数错误] goal_id 与 task_id 均必填", "", name)
    audit, err, _note = _require_active_goal(ctx, host, goal_id)
    if err:
        return ToolResult(ToolResultStatus.FAILURE, err, "", name)
    assert audit is not None
    token = str(args.get("claim_token", "") or "").strip() or None
    try:
        released = ClaimStore(audit).release(goal_id, task_id, token=token)
    except ClaimError as exc:
        return ToolResult(ToolResultStatus.FAILURE, f"[claim 拒绝] reason_code={exc.code} | {exc.message}", "", name)
    if not released:
        return ToolResult(
            ToolResultStatus.SUCCESS,
            f"[无活跃 claim] {goal_id}/{task_id}（已过期或从未 claim，无需释放）",
            "",
            name,
        )
    return ToolResult(ToolResultStatus.SUCCESS, f"[claim 已释放] {goal_id}/{task_id}", "", name)


TASK_TOOL_DEFS: list[dict] = [
    TASK_CREATE_TOOL_DEF,
    TASK_UPDATE_TOOL_DEF,
    TASK_FRONTIER_TOOL_DEF,
    CLAIM_TOOL_DEF,
    CLAIM_RENEW_TOOL_DEF,
    CLAIM_RELEASE_TOOL_DEF,
]

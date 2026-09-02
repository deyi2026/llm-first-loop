"""authorization 阶段（design T5-C 第三批 / B4-C3-01，A-2 承载位置显式标注）.

R8.24-E E-D5（E-3.2，P1-7）: ACTIVE_STATE → USER_AUTHORIZED_STATE
——"恰有 in_progress"不再自动投影；仅本轮用户输入命中"继续/恢复"
类明确指令（授权一次）才注入，本 run（turn_ref 绑定）内 identity
冻结不动态漂移；授权绑定事件落决策日志。未授权零 Goal/Task 读取。
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from llm_loop.core.prompt_eligibility import render_task_active_identity

logger = logging.getLogger(__name__)


def resolve_authorized(
    *,
    inject_parts: list[tuple[str | None, str]],
    sess: Any,
    settings: Any,
    current_turn_ref: Any,
    r6_ingress_truth: Any,
    identity_cache: dict[Any, Any],
    record_action: Callable[..., Any],
) -> dict[str, Any]:
    """授权投影 + identity 快照冻结（fail-open 零注入）；决策回传 BuildDecision.authorization_slots."""
    # CR-R1.1 批次D（审查项6 补全）: packet 编译输入面 = 真实注入面。memory 自
    # EVO-20260827-f42496bc 改为一次性持久化（engine wrap+append 进
    # sess.messages）后不再进 inject_parts（仅 fail-open 才进，见上方
    # fallback），但 packet 编译必须覆盖它——否则 slots 恒空、warm_tokens
    # 恒 0（glm-minimax-3 实测 24/24 warm_active=0 的根因），shadow 无法
    # 预演 enforce（审查项6 同构语义：shadow 与 enforce 使用同一 compiler
    # 产物）。投影全量 memory_snapshot（每 turn 一条，多轮堆积由 compiler
    # budget_chars 降级兜底——WARM 超界降级本身即 tier_degraded 生产可达
    # 路径）；wire 平铺仍用 inject_parts 原语义，持久化原文已由历史投影
    # 带出，不重复注入。
    # R8.16/E23: task ledger is durable state, but full frontier is not automatic
    # working context.  Only one uniquely active execution identity may project;
    # ready/blocked/unreachable/completed/premise-stale state stays behind task_frontier().
    # Multiple in-progress nodes are intentionally ambiguous: do not guess which one is
    # "current".  Fail-open here means zero prompt chars, never full-graph fallback.
    # R8.24-E E-D5（E-3.2，P1-7）: ACTIVE_STATE → USER_AUTHORIZED_STATE——"恰有
    # in_progress"不再自动投影；仅当本轮用户输入经 input-side resolver 命中
    # "继续/恢复上次任务"类明确指令（授权一次）才注入，且本 run（turn_ref 绑定）
    # 内冻结 task identity 不动态变化；授权绑定事件落决策日志（E-G2/E-G5
    # 双断言判据源）。普通新问题不自动读取 Goal（Goal 恒为 retrievable state）。
    _decision: dict[str, Any] = {"turn_ref": str(current_turn_ref)}
    try:
        from llm_loop.core.loop.input_authorization import (
            detect_task_continuation,
        )
        from llm_loop.introspection.goal import GoalStore
        from llm_loop.introspection.task_store import TaskStore

        _tf_audit = os.path.join(settings.data_dir, "audit")
        # 授权信号：本轮人类 ingress 文本命中触发词；工具轮（R6 truth=None）
        # 沿用冻结快照——同一授权在本 run 内持续生效（E-3.2① identity 冻结）。
        # 注意 r6_ingress_truth 即 user truth 文本（str | None，user_truth_wire）。
        _tf_ingress_text = str(r6_ingress_truth or "")
        _tf_authorized = detect_task_continuation(_tf_ingress_text)
        _decision["ingress_authorized"] = bool(_tf_authorized)
        # identity 冻结（E-3.2①）：授权轮求值一次后按 turn_ref 快照——本 run
        # 内后续 build 直接用快照（不随 GoalStore/TaskStore 中途状态漂移）；
        # 新 turn 授权重新求值。快照失配（goal_id 变化）时自然失效重建。
        _tf_turn_key = str(current_turn_ref)
        _tf_cache = identity_cache
        if _tf_cache is None:
            _tf_cache = {}
        _tf_cached = _tf_cache.get(_tf_turn_key)
        if _tf_cached is not None and (
            _tf_authorized or r6_ingress_truth is None
        ):
            _tf_gid, _tf_identity = _tf_cached
            if _tf_identity:
                inject_parts.append(("task_active", _tf_identity))
                record_action(
                    "task.active",
                    "authorized_inject_frozen",
                    f"turn_ref={_tf_turn_key};goal={_tf_gid};chars={len(_tf_identity)}",
                )
                _decision.update(mode="authorized_inject_frozen", goal_id=_tf_gid, prompt_chars=len(_tf_identity))
            else:
                _decision["mode"] = "frozen_no_identity"
            _tf_authorized = False  # 快照已注入，跳过下方重新求值
        elif not _tf_authorized:
            record_action(
                "task.active",
                "unauthorized_zero_projection",
                "prompt_chars=0;goal_read=deferred",
            )
            _decision.update(mode="unauthorized_zero_projection", goal_read=0)
        # E-G5: 未授权（含快照未命中）时零 Goal/Task 读取——普通新问题轮
        # goal_read=0（决策日志可断言）。
        if not _tf_authorized:
            _tf_goal = {}
        else:
            _tf_goal = GoalStore(_tf_audit).get(prefer_session_id=sess.session_id)
        _tf_gid = str((_tf_goal or {}).get("id", "") or "")
        if _tf_authorized and _tf_gid and str((_tf_goal or {}).get("status", "")) == "active":
            _tf_store = TaskStore(_tf_audit)
            # ADR-5: 授权轮追加 next_step 锚点（execution-cursor 优先 → checkpoint 兜底）；
            # 复用已读 _tf_goal/_tf_store，零额外 Goal/Task 读取（E-G5 不回归）。
            _tf_next = _resolve_next_step(_tf_store, _tf_gid, sess.session_id, _tf_goal)
            if _tf_next:
                inject_parts.append(("task_next_step", f"[Next Step] {_tf_next}"))
            if _tf_store.count_for_goal(_tf_gid) > 0:
                _tf_state = _tf_store.compute_frontier(_tf_gid)
                _tf_doing = list(_tf_state.get("in_progress") or [])
                if len(_tf_doing) == 1:
                    _tf_task = (_tf_doing[0] or {}).get("task")
                    _tf_active = render_task_active_identity(
                        goal_id=_tf_gid,
                        task_id=str(getattr(_tf_task, "task_id", "") or ""),
                        title=str(getattr(_tf_task, "title", "") or ""),
                    )
                    if _tf_active:
                        inject_parts.append(("task_active", _tf_active))
                        # 授权轮写入 identity 快照（本 run 内冻结）
                        _tf_cache[_tf_turn_key] = (_tf_gid, _tf_active)
                        # 授权绑定审计（E-3.2③）：触发词/会话/轮次/task identity
                        record_action(
                            "task.active",
                            "authorized_inject",
                            (
                                f"turn_ref={current_turn_ref};"
                                f"goal={_tf_gid};chars={len(_tf_active)}"
                            ),
                        )
                        _decision.update(mode="authorized_inject", goal_id=_tf_gid, prompt_chars=len(_tf_active))
                else:
                    try:
                        record_action(
                            "task.frontier",
                            "on_demand_only",
                            f"prompt_chars=0;in_progress={len(_tf_doing)}",
                        )
                        _decision.update(mode="on_demand_only", in_progress=len(_tf_doing))
                    except Exception:  # noqa: BLE001 — observability cannot affect build
                        logger.debug(
                            "build: task frontier observability action failed",
                            exc_info=True,
                        )
    except Exception:  # noqa: BLE001 — fail-open: 任务账本异常不阻断构建
        logger.debug("build: Task Active 解析失败（fail-open 零注入）", exc_info=True)
        _decision["mode"] = "fail_open"
    _decision.setdefault("mode", "noop")
    return _decision


def _resolve_next_step(store: Any, goal_id: str, session_id: str, goal: dict | None) -> str:
    """ADR-5：续聊 next_step 锚点（execution-cursor 优先 → checkpoint 兜底）.

    不新增独立存储读取：checkpoint 复用已读 ``goal``；execution-cursor 仅在
    TaskStore 已落地 ``get_cursor`` 时才读取（当前未落地 → 恒定走 checkpoint 兜底）。
    """
    get_cursor = getattr(store, "get_cursor", None)
    if callable(get_cursor):
        try:
            cursor = get_cursor(goal_id, session_id)
        except Exception:  # noqa: BLE001 — 游标读取失败降级 checkpoint
            cursor = None
        if cursor:
            next_step = str(getattr(cursor, "next_step", "") or "")
            if next_step:
                return next_step
    checkpoints = (goal or {}).get("checkpoints") or []
    if checkpoints:
        return str((checkpoints[-1] or {}).get("next", "") or "")
    return ""

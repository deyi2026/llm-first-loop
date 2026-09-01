"""入口解析/过期清理阶段（resolve_inputs；design T5-C 第二批 / B4-C2-01）.

BuildInputs 产出段：base 快照 + 原下标索引结构 + R6 ingress 冻结真值 +
stale 清理结果集。四过滤器链（episode fail-open / memory snapshot /
program control / R4 stale recovery）语义逐字节原样——storage/event truth
全程零改动，仅 provider 视图收窄；memory 检索注入不前置（EVO-2026XXXX
§5.3.1-1c 前缀断归因）由调用侧装配段负责。
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from llm_loop.core.episode_history import provider_view_without_resolved_episodes
from llm_loop.core.program_recovery import is_program_recovery_message
from llm_loop.core.prompt import build_system_prompt
from llm_loop.core.prompt_build.context import BuildInputs
from llm_loop.core.prompt_build.stages.base_assembly import scrub_provider_view
from llm_loop.core.prompt_build.stages.trace_isolation import run_trace_isolation
from llm_loop.core.prompt_eligibility import (
    current_turn_program_prompt_eligible,
    memory_snapshot_prompt_eligible,
)
from llm_loop.core.user_truth_wire import current_ingress_user_truth

logger = logging.getLogger(__name__)


def resolve_ingress(
    *,
    sess_messages: list[Any],
    memory_msgs: list[Any],
    current_turn_ref: Any,
    record_action: Callable[..., Any],
) -> BuildInputs:
    """入口解析 + 过期清理（产出 BuildInputs，下游只读）."""
    base = list(sess_messages)
    _original_base_index_by_id = {id(_m): _idx for _idx, _m in enumerate(base)}
    _base_original_indices = list(range(len(base)))
    # R6: freeze the canonical current human ingress before history/compact projects it.
    # Tool-followup rounds return None and retain assistant(tool_calls)->tool(result) order.
    _r6_ingress_truth = current_ingress_user_truth(sess_messages, current_turn_ref)
    stale_cleanup: dict[str, Any] = {}
    # INJECTION-GOVERNANCE R8.5/R8.20 eligibility: completed episodes and
    # already-consumed raw tool spans are durable indexed history, not default
    # working context. Current/incomplete tool protocol remains visible fail-open.
    # Storage/event truth is untouched.
    try:
        base = provider_view_without_resolved_episodes(base)
        _base_original_indices = [
            _original_base_index_by_id[id(_m)]
            for _m in base
            if id(_m) in _original_base_index_by_id
        ]
    except Exception:  # noqa: BLE001 — eligibility projection fail-open
        logger.warning("build: resolved episode provider-view 过滤失败（fail-open）", exc_info=True)
    # INJECTION-GOVERNANCE R8.8: persisted memory is durable retrieval state, not a
    # recency-based prompt entitlement. Only the snapshot bound to the current human
    # turn may stay in automatic working context; legacy/unbound/older snapshots are
    # omitted from the flat provider view. Storage and search_records(kind=memory)
    # remain untouched.
    _eligibility_turn_ref = current_turn_ref
    _stale_memory_count = sum(
        1
        for _m in base
        if not memory_snapshot_prompt_eligible(
            _m, current_turn_ref=_eligibility_turn_ref
        )
    )
    if _stale_memory_count:
        base = [
            _m
            for _m in base
            if memory_snapshot_prompt_eligible(
                _m, current_turn_ref=_eligibility_turn_ref
            )
        ]
        _base_original_indices = [
            _original_base_index_by_id[id(_m)]
            for _m in base
            if id(_m) in _original_base_index_by_id
        ]
        with contextlib.suppress(Exception):
            record_action(
                "action.prompt_eligibility",
                "memory_snapshot_retired",
                f"count={_stale_memory_count}",
            )
    stale_cleanup["memory_snapshot"] = _stale_memory_count
    # R8.9: same-human-turn program controls may guide later LLM/tool rounds, but
    # lose automatic prompt authority on the next human ingress.  Legacy unlabelled
    # stagnation/search/overflow/fallback system frames are historical control state
    # and are filtered by the same central eligibility policy.
    _expired_program_control_count = sum(
        1
        for _m in base
        if not current_turn_program_prompt_eligible(
            _m, current_turn_ref=_eligibility_turn_ref
        )
    )
    if _expired_program_control_count:
        base = [
            _m
            for _m in base
            if current_turn_program_prompt_eligible(
                _m, current_turn_ref=_eligibility_turn_ref
            )
        ]
        _base_original_indices = [
            _original_base_index_by_id[id(_m)]
            for _m in base
            if id(_m) in _original_base_index_by_id
        ]
        with contextlib.suppress(Exception):
            record_action(
                "action.prompt_eligibility",
                "program_control_retired",
                f"count={_expired_program_control_count}",
            )
    stale_cleanup["program_control"] = _expired_program_control_count
    # INJECTION-GOVERNANCE R4: persisted recovery is audit history, not future
    # executable context.  New recovery never enters sess.messages; this filter retires
    # pre-R4 durable recovery blocks without mutating storage/event truth.
    _stale_recovery_count = sum(1 for _m in base if is_program_recovery_message(_m))
    if _stale_recovery_count:
        base = [_m for _m in base if not is_program_recovery_message(_m)]
        _base_original_indices = [
            _original_base_index_by_id[id(_m)]
            for _m in base
            if id(_m) in _original_base_index_by_id
        ]
        with contextlib.suppress(Exception):
            record_action(
                "action.program_recovery",
                "stale_history_filtered",
                f"count={_stale_recovery_count}",
            )
    stale_cleanup["stale_recovery"] = _stale_recovery_count
    return BuildInputs(
        base_messages=base,
        base_index_by_id=_original_base_index_by_id,
        r6_ingress_truth=_r6_ingress_truth,
        memory_msgs=memory_msgs,
        stale_cleanup=stale_cleanup,
        filtered_indices=_base_original_indices,
    )


@dataclass(slots=True)
class IngressPreludeOutcome:
    """预解析簇产物（B4-CLOSE-01 步D；decision 就地演进）."""

    resolved_label: str
    provider_id: str
    sess_anchor: int
    system_prompt: str
    base: list
    base_original_indices: list
    r6_ingress_truth: Any
    leak_downgrade_parts: list


def run_ingress_prelude(
    *,
    decision: Any,
    sess: Any,
    memory_msgs: list,
    planned_label: str | None,
    model: str | None,
    planned_model_label: Callable[[str | None, Any], str],
    current_turn_ref: Any,
    record_action: Any,
    event_append: Any,
    tool_round_zero: bool,
) -> IngressPreludeOutcome:
    """入口解析 → 泄漏隔离 → provider 预清洗（语义原样迁自 build.py 步D）.

    resolve_ingress（四过滤器链 storage truth 零改动）→
    run_trace_isolation（KEEP-HARD 薄接线/三态分流 D-D1）→
    scrub_provider_view（缓存遥测剥离/协议边界收敛/base 索引重映射）。
    """
    resolved_label: str = (
        planned_label
        if planned_label is not None
        else planned_model_label(model, sess)
    )
    provider_id = resolved_label.partition("/")[0] or "default"
    anchors = sess.history_anchors or {}
    sess_anchor = int(anchors.get(provider_id, 0) or 0)
    system_prompt = build_system_prompt()
    # EVO-2026XXXX（spec §5.3.1-1c）: memory 检索注入不再前置——检索结果（top_k 语义/
    # 关键词召回）随本轮查询变化，前置在 system 之后会每轮改变前缀首段 → 前缀断
    # （2026-08-18 审计断点归因: 96%→2% 全量失效，delta 仅 614 tokens）。
    # 改为提交视图尾部追加（GATE_NOTE 模式，转 user），system+稳定历史前缀字节不变。
    # 入口解析/过期清理 → stages/ingress_resolution.py（BuildInputs 产出段；
    # 四过滤器链 storage truth 零改动，仅 provider 视图收窄）
    inputs = resolve_ingress(
        sess_messages=sess.messages,
        memory_msgs=memory_msgs,
        current_turn_ref=current_turn_ref,
        record_action=record_action,
    )
    base = inputs.base_messages
    _base_original_indices = inputs.filtered_indices
    _original_base_index_by_id = inputs.base_index_by_id
    _r6_ingress_truth = inputs.r6_ingress_truth
    # agent_trace_leak 4.2 α 挂载点 → stages/trace_isolation.py（KEEP-HARD 薄接线；
    # 三态分流 D-D1 / fail-open spec 5.4.3-1 语义原样；本体在 core/trace_leak/）
    base, _base_original_indices = run_trace_isolation(
        base,
        base_indices=_base_original_indices,
        index_by_id=_original_base_index_by_id,
        sess=sess,
        current_ingress=_r6_ingress_truth,
        event_sink=event_append,
        decision=decision,
    )
    _leak_downgrade_parts = (
        decision.trace_isolation["downgrade_parts"]
        if decision.trace_isolation
        else []
    )
    # provider 视图预清洗 → stages/base_assembly.py::scrub_provider_view
    # （B4-CLOSE-01 步B）：缓存遥测剥离 → program 协议边界收敛 →
    # tool_round_zero 极小窗口；base_original_indices 同步重映射。
    # 存档/存储原文零改动（仅 provider 提交视图）。
    _scrub = scrub_provider_view(
        base=base,
        base_original_indices=_base_original_indices,
        tool_round_zero=tool_round_zero,
    )
    return IngressPreludeOutcome(
        resolved_label=resolved_label,
        provider_id=provider_id,
        sess_anchor=sess_anchor,
        system_prompt=system_prompt,
        base=_scrub.base,
        base_original_indices=_scrub.base_original_indices,
        r6_ingress_truth=_r6_ingress_truth,
        leak_downgrade_parts=_leak_downgrade_parts,
    )

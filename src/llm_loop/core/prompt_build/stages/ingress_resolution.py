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
from typing import Any

from llm_loop.core.episode_history import provider_view_without_resolved_episodes
from llm_loop.core.program_recovery import is_program_recovery_message
from llm_loop.core.prompt_build.context import BuildInputs
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

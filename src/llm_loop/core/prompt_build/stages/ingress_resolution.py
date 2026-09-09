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

from llm_loop.core.episode_history import (
    collect_active_evidence_groups,
    evidence_candidate_set_digest,
    project_active_tool_working_set_with_stats,
    provider_view_without_resolved_episodes,
    resolve_working_state_checkpoint,
    superseded_human_attempt_spans,
)
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
    current_turn_ref: Any,
    record_action: Callable[..., Any],
    ingress_truth: Any,
    original_index_by_id: dict[int, int],
    initial_indices: list[int],
) -> BuildInputs:
    """入口解析 + 过期清理（产出 BuildInputs，下游只读）."""
    base = list(sess_messages)
    _original_base_index_by_id = dict(original_index_by_id)
    _base_original_indices = list(initial_indices)
    # Canonical current human ingress was frozen against storage truth before trace
    # isolation/filtering; tool-followup rounds carry None.
    _r6_ingress_truth = ingress_truth
    stale_cleanup: dict[str, Any] = {}
    # INJECTION-GOVERNANCE R8.5/R8.20 eligibility: completed episodes and
    # already-consumed raw tool spans are durable indexed history, not default
    # working context. Current/incomplete tool protocol remains visible fail-open.
    # Storage/event truth is untouched.
    _before_resolved_count = len(base)
    _superseded_human_spans = superseded_human_attempt_spans(base)
    _superseded_human_messages = sum(end - start for start, end in _superseded_human_spans)
    try:
        base = provider_view_without_resolved_episodes(base)
        _base_original_indices = [
            _original_base_index_by_id[id(_m)]
            for _m in base
            if id(_m) in _original_base_index_by_id
        ]
    except Exception:  # noqa: BLE001 — eligibility projection fail-open
        logger.warning("build: resolved episode provider-view 过滤失败（fail-open）", exc_info=True)
    stale_cleanup["resolved_or_consumed"] = max(0, _before_resolved_count - len(base))
    stale_cleanup["superseded_human_attempts"] = len(_superseded_human_spans)
    stale_cleanup["superseded_human_messages"] = _superseded_human_messages
    # INJECTION-GOVERNANCE R8.8: persisted memory is durable retrieval state, not a
    # recency-based prompt entitlement. Only the snapshot bound to the current human
    # turn may stay in automatic working context; legacy/unbound/older snapshots are
    # omitted from the flat provider view. Storage and search_records(kind=memory)
    # remain untouched.
    _eligibility_turn_ref = current_turn_ref
    _stale_memory_count = sum(
        1
        for _m in base
        if not memory_snapshot_prompt_eligible(_m, current_turn_ref=_eligibility_turn_ref)
    )
    if _stale_memory_count:
        base = [
            _m
            for _m in base
            if memory_snapshot_prompt_eligible(_m, current_turn_ref=_eligibility_turn_ref)
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
    def _is_current_human_ingress(_m: Any) -> bool:
        return (
            _r6_ingress_truth is not None
            and _original_base_index_by_id.get(id(_m)) == current_turn_ref
        )

    _expired_program_control_count = sum(
        1
        for _m in base
        if not _is_current_human_ingress(_m)
        and not current_turn_program_prompt_eligible(_m, current_turn_ref=_eligibility_turn_ref)
    )
    if _expired_program_control_count:
        base = [
            _m
            for _m in base
            if _is_current_human_ingress(_m)
            or current_turn_program_prompt_eligible(_m, current_turn_ref=_eligibility_turn_ref)
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
    working_state_text: str | None = None
    influence: dict[str, Any] | None = None


def run_ingress_prelude(
    *,
    decision: Any,
    sess: Any,
    planned_label: str | None,
    model: str | None,
    planned_model_label: Callable[[str | None, Any], str],
    current_turn_ref: Any,
    record_action: Any,
    event_append: Any,
) -> IngressPreludeOutcome:
    """入口解析 → 泄漏隔离 → provider 预清洗（语义原样迁自 build.py 步D）.

    resolve_ingress（四过滤器链 storage truth 零改动）→
    run_trace_isolation（KEEP-HARD 薄接线/三态分流 D-D1）→
    scrub_provider_view（缓存遥测剥离/协议边界收敛/base 索引重映射）。
    """
    resolved_label: str = (
        planned_label if planned_label is not None else planned_model_label(model, sess)
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
    # Trace isolation must observe storage truth BEFORE prompt eligibility retires any
    # contradictory program-origin frame.  This preserves quarantine/would-quarantine
    # evidence while the later provider view remains deny-by-default.
    _raw_base = list(sess.messages)
    _original_base_index_by_id = {id(_m): _idx for _idx, _m in enumerate(_raw_base)}
    _raw_indices = list(range(len(_raw_base)))
    _r6_ingress_truth = current_ingress_user_truth(sess.messages, current_turn_ref)
    _trace_base, _trace_indices = run_trace_isolation(
        _raw_base,
        base_indices=_raw_indices,
        index_by_id=_original_base_index_by_id,
        sess=sess,
        current_ingress=_r6_ingress_truth,
        event_sink=event_append,
        decision=decision,
    )
    inputs = resolve_ingress(
        sess_messages=_trace_base,
        current_turn_ref=current_turn_ref,
        record_action=record_action,
        ingress_truth=_r6_ingress_truth,
        original_index_by_id=_original_base_index_by_id,
        initial_indices=_trace_indices,
    )
    base = inputs.base_messages
    _base_original_indices = inputs.filtered_indices
    _original_base_index_by_id = inputs.base_index_by_id
    # provider 视图预清洗：缓存遥测剥离 + program 协议边界收敛；
    # 不因 local/tool-round 性能策略裁历史。
    # 存档/存储原文零改动（仅 provider 提交视图）。
    _scrub = scrub_provider_view(
        base=base,
        base_original_indices=_base_original_indices,
    )
    # S1 canary: validate persisted model-authored working state against storage
    # truth, then confirm the same evidence identity still exists in the scrubbed
    # provider view. Program logic checks identity/pairing/scope/resource bounds only.
    _checkpoint = resolve_working_state_checkpoint(
        getattr(sess, "working_state_checkpoint", None),
        session_id=sess.session_id,
        messages=sess.messages,
        provider_id=provider_id,
        model=resolved_label,
    )
    _preserve_digests: tuple[str, ...] = ()
    _working_state_text: str | None = None
    _checkpoint_reason = _checkpoint.reason
    if _checkpoint.eligible:
        _provider_groups = collect_active_evidence_groups(_scrub.base)
        _provider_digests = {group.descriptor.protocol_digest for group in _provider_groups}
        if evidence_candidate_set_digest(
            _provider_groups
        ) == _checkpoint.candidate_set_digest and set(_checkpoint.preserve_group_digests).issubset(
            _provider_digests
        ):
            _preserve_digests = _checkpoint.preserve_group_digests
            _working_state_text = _checkpoint.state_text
            _checkpoint_reason = "eligible"
        else:
            _checkpoint_reason = "provider_view_mismatch"
    if getattr(sess, "working_state_checkpoint", None) is not None:
        with contextlib.suppress(Exception):
            record_action(
                "run.working_state_checkpoint",
                _checkpoint_reason,
                (
                    f"selected_groups={len(_preserve_digests)};"
                    f"selected_raw_chars={_checkpoint.selected_raw_chars if _working_state_text else 0};"
                    "prompt_chars=0"
                ),
            )

    # Active-run working-set receipts are representation-only: order and message
    # count stay identical, so the already-computed storage index mapping remains
    # authoritative. Selected protocol groups are exempted as exact raw evidence;
    # unselected groups keep the existing batch/grace mechanics unchanged.
    _provider_base, _working_set_stats = project_active_tool_working_set_with_stats(
        _scrub.base, preserve_group_digests=_preserve_digests
    )
    if _working_set_stats.enabled:
        with contextlib.suppress(Exception):
            record_action(
                "run.tool_working_set",
                "projected",
                (
                    f"batch_chars={_working_set_stats.batch_chars};"
                    f"raw_tool_chars={_working_set_stats.raw_tool_chars};"
                    f"projected_tool_chars={_working_set_stats.projected_tool_chars};"
                    f"receipt_chars={_working_set_stats.receipt_chars};"
                    f"folded_results={_working_set_stats.folded_results};"
                    f"folded_groups={_working_set_stats.folded_groups};"
                    f"grace_groups={_working_set_stats.grace_groups};"
                    f"grace_raw_chars={_working_set_stats.grace_raw_chars};"
                    f"grace_results={_working_set_stats.grace_results};"
                    f"pending_raw_chars={_working_set_stats.pending_raw_chars};"
                    f"pending_results={_working_set_stats.pending_results};"
                    f"latest_raw_chars={_working_set_stats.latest_raw_chars};"
                    f"fold_boundaries={','.join(str(x) for x in _working_set_stats.fold_boundaries)};"
                    "prompt_chars=0"
                ),
            )
    _working_set_influence = {
        "enabled": bool(_working_set_stats.enabled),
        "raw_tool_chars": int(_working_set_stats.raw_tool_chars or 0),
        "projected_tool_chars": int(_working_set_stats.projected_tool_chars or 0),
        "folded_results": int(_working_set_stats.folded_results or 0),
        "folded_groups": int(_working_set_stats.folded_groups or 0),
    }
    return IngressPreludeOutcome(
        resolved_label=resolved_label,
        provider_id=provider_id,
        sess_anchor=sess_anchor,
        system_prompt=system_prompt,
        base=_provider_base,
        base_original_indices=_scrub.base_original_indices,
        r6_ingress_truth=_r6_ingress_truth,
        working_state_text=_working_state_text,
        influence={
            "storage_messages": len(_raw_base),
            "trace_messages": len(_trace_base),
            "eligible_messages": len(inputs.base_messages),
            "provider_base_messages": len(_provider_base),
            "stale_cleanup": dict(inputs.stale_cleanup),
            "working_state_reason": str(_checkpoint_reason or ""),
            "working_state_selected_raw_chars": int(
                _checkpoint.selected_raw_chars if _working_state_text else 0
            ),
            "tool_working_set": _working_set_influence,
        },
    )

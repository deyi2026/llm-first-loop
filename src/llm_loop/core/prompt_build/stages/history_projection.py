"""历史投影调用阶段（design T5-C 第二批 / B4-C2-03②）.

P1-10 + R8.5 锚点边界换算（persisted anchor 用原始会话索引，eligibility
过滤收缩 provider 视图——调前换算 forward、调后换算 back，防有效旧锚点
跳过当前任务或孤儿化工具组）+ build_history_messages 一次性大装配调用
（Phase 7 前不动其内部）。box 系 out-params 显式化进产出对象。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from llm_loop.core.episode_history import filtered_anchor_from_original
from llm_loop.core.history import (
    build_history_messages,
    clear_cache_compacted_for,
    is_cache_compacted_for,
    project_exact_duplicate_tool_groups,
)
from llm_loop.core.message import Message
from llm_loop.core.reference_injection import is_human_user_message


def _map_compacted_source_indices(
    local_indices: list[int], *, prefix_len: int, filtered_indices: list[int]
) -> list[int]:
    """Map exact build-local compaction indices back to original Session indices.

    ``base`` consists of an ephemeral prefix followed by the eligibility-filtered
    Session view. Prefix entries are not Session facts and therefore emit no
    ``message.cache_compacted`` event. Out-of-range values are ignored rather than
    guessed.
    """
    out: list[int] = []
    for local_idx in local_indices:
        filtered_idx = local_idx - prefix_len
        if 0 <= filtered_idx < len(filtered_indices):
            out.append(filtered_indices[filtered_idx])
    return out


@dataclass(slots=True)
class HistoryProjection:
    """历史投影产出（built 视图 + box 系遥测/状态）."""

    built: list[Any] = field(default_factory=list)
    anchor_arg: int = 0
    anchor_box: list[int] = field(default_factory=list)
    compacted_box: list[bool] = field(default_factory=list)
    cache_compacted_box: list[Message] = field(default_factory=list)
    cache_compacted_source_box: list[int] = field(default_factory=list)
    compact_view_box: list[dict] = field(default_factory=list)
    reopened_marker_count: int = 0
    duplicate_tool_projection_stats: dict[str, int | bool] = field(default_factory=dict)


def run_history_projection(
    *,
    base: list[Any],
    system_prompt: str,
    filtered_indices: list[int],
    sess_anchor: Any,
    prefix_len: int,
    session_id: str,
    max_chars: int | None,
    runtime_history_budget_value: int,
    compact_ratio: float,
    archive_sink: Any,
    settings: Any,
    provider_id: str,
    resolved_label: str,
    reasoning_tail: Any,
    r6_ingress_truth: Any,
    registry: Any,
    cache_monitor: Any,
    effective_budget: int,
    cache_protected_prefix_messages: int = 0,
    cache_protected_prefix_chars: int = 0,
    current_turn_ref: int | None = None,
) -> HistoryProjection:
    """锚点换算 + build_history_messages 调用（参数语义逐字节原样）."""
    # P1-10 + R8.5: persisted anchor uses original sess.messages indices,
    # while resolved/recovery eligibility filters shrink the provider view.
    # Translate the boundary before build_history_messages and translate it
    # back after compaction; otherwise a valid old anchor can skip the current
    # task or orphan a tool group after resolved messages retire.
    _filtered_sess_anchor = filtered_anchor_from_original(
        filtered_indices, sess_anchor
    )
    anchor_arg = (
        _filtered_sess_anchor + prefix_len if _filtered_sess_anchor > 0 else 0
    )
    anchor_box: list[int] = []
    compacted_box: list[bool] = []
    cache_compacted_box: list[Message] = []
    cache_compacted_local_index_box: list[int] = []
    compact_view_box: list[dict] = []
    freeze_compression = cache_monitor.breaker_freeze_compression(session_id)
    reopened_marker_count = 0
    if (cache_archive_provider := provider_id) and not freeze_compression:
        stale_markers = [
            m
            for m in base
            if is_cache_compacted_for(m, cache_archive_provider)
            and not is_cache_compacted_for(
                m,
                cache_archive_provider,
                model_ref=resolved_label,
                effective_budget=effective_budget,
            )
        ]
        reopened_marker_count = len(stale_markers)
        for m in stale_markers:
            clear_cache_compacted_for(m, cache_archive_provider)
    _current_human_message: Message | None = None
    if current_turn_ref is not None:
        try:
            _current_filtered_pos = filtered_indices.index(current_turn_ref)
        except ValueError:
            _current_filtered_pos = -1
        _current_local_pos = prefix_len + _current_filtered_pos
        if (
            _current_filtered_pos >= 0
            and 0 <= _current_local_pos < len(base)
            and is_human_user_message(base[_current_local_pos])
        ):
            _current_human_message = base[_current_local_pos]

    built = build_history_messages(
        base,
        system_prompt,
        max_chars=max_chars if max_chars is not None else runtime_history_budget_value,
        compact_ratio=compact_ratio,  # EVO-20260817: 预算分级主动压缩
        session_id=session_id,
        archive_sink=archive_sink,
        # RULE-AI-00: 不再传 summarizer（压缩路径不自动 LLM 摘要，AI 主动触发）
        # 2026-08-20 回滚修复: 移除悬空 tool_tail 参数——history.py 的
        # build_history_messages() 不接受该参数（3点基线无此功能，config 恒为 0），
        # 回滚后每次对话 TypeError；参数支持在 backup/20260819-after-3am 分支
        reasoning_tail=reasoning_tail,
        # Runtime observability/system notices do not enter ordinary provider history.
        # AI can query architecture/status facts explicitly when they matter.
        skip_injected_system=True,
        # P1-10: 窗口锚定
        history_anchor=anchor_arg,
        anchor_out=anchor_box,
        compacted_out=compacted_box,
        # Cache-aware normal compaction may preserve an already stable head, but it is
        # still bounded by the current model budget. Provider-reported overflow uses the
        # same single compaction path with a deterministically shrunken budget; no second
        # emergency mode rewrites anchor semantics.
        head_keep_chars=max(
            int(
                effective_budget
                * float(
                    os.environ.get(
                        "HEAD_KEEP_RATIO", "0.35" if provider_id == "deepseek" else "0.15"
                    )
                )
            ),
            int(
                effective_budget
                * float(
                    os.environ.get(
                        "HEAD_KEEP_FORCE_RATIO",
                        "0.40" if provider_id == "deepseek" else "0.20",
                    )
                )
            )
            if cache_monitor.force_head_keep
            else 0,
        ),
        # fixed-head 占压缩目标水位上限。历史层默认 0.50 保持旧行为；DeepSeek 提到
        # 0.70，允许 0.35×effective_budget 的 head 真正留下（target=.5 时占70%），
        # 仍给最近 tail 约30%目标水位；原子组边界会自然留出更多。env 可显式覆盖调参。
        head_keep_target_ratio=float(
            os.environ.get(
                "HEAD_KEEP_TARGET_RATIO", "0.70" if provider_id == "deepseek" else "0.50"
            )
        ),
        # P0 压缩风暴熔断冻结（2026-08-25）: 冻结期禁压缩/禁锚点前移（前缀字节稳定）
        freeze_compression=freeze_compression,
        cache_archive_provider=provider_id,
        cache_archive_model=resolved_label,
        cache_archive_budget=effective_budget,
        cache_compacted_out=cache_compacted_box,
        cache_compacted_index_out=cache_compacted_local_index_box,
        cache_protected_prefix_messages=cache_protected_prefix_messages,
        cache_protected_prefix_chars=cache_protected_prefix_chars,
        compact_view_stats=compact_view_box,
        require_archive_success=getattr(registry, "evidence_mode", "off") == "enforce",
        # Initial ingress and every tool-followup round of that same genuine human
        # turn share one wire invariant: the exact current human message must remain
        # provider-visible even when surrounding atomic tool groups are compacted.
        # `filtered_indices` is an exact original-Session index map, so this adds no
        # semantic task/relevance judgement.
        preserve_last_human_exact=r6_ingress_truth is not None,
        preserve_human_message=_current_human_message,
        current_turn_ref=current_turn_ref,
    )
    duplicate_tool_projection_stats: dict[str, int | bool] = {
        "enabled": bool(getattr(settings, "exact_duplicate_tool_fold", False)),
        "folded_groups": 0,
        "removed_messages": 0,
    }
    if duplicate_tool_projection_stats["enabled"]:
        built, duplicate_stats = project_exact_duplicate_tool_groups(built)
        duplicate_tool_projection_stats.update(duplicate_stats)

    cache_compacted_source_box = _map_compacted_source_indices(
        cache_compacted_local_index_box,
        prefix_len=prefix_len,
        filtered_indices=filtered_indices,
    )
    return HistoryProjection(
        built=built,
        anchor_arg=anchor_arg,
        anchor_box=anchor_box,
        compacted_box=compacted_box,
        cache_compacted_box=cache_compacted_box,
        cache_compacted_source_box=cache_compacted_source_box,
        compact_view_box=compact_view_box,
        reopened_marker_count=reopened_marker_count,
        duplicate_tool_projection_stats=duplicate_tool_projection_stats,
    )

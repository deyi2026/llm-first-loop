"""历史投影调用阶段（design T5-C 第二批 / B4-C2-03②）.

P1-10 + R8.5 锚点边界换算（persisted anchor 用原始会话索引，eligibility
过滤收缩 provider 视图——调前换算 forward、调后换算 back，防有效旧锚点
跳过当前任务或孤儿化工具组）+ build_history_messages 一次性大装配调用
（Phase 7 前不动其内部）。box 系 out-params 显式化进产出对象。
"""
from __future__ import annotations

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
from llm_loop.core.reference_injection import is_active_run_ingress_message


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
    task_anchor_snapshot_provider: Any | None = None,  # EVO-20260916-ccc978b2
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
    _policy = getattr(settings, "history_policy", None)
    _head_keep_ratio = getattr(_policy, "head_keep_ratio", None)
    if _head_keep_ratio is None:
        _head_keep_ratio = 0.35 if provider_id == "deepseek" else 0.15
    _head_keep_force_ratio = getattr(_policy, "head_keep_force_ratio", None)
    if _head_keep_force_ratio is None:
        _head_keep_force_ratio = 0.40 if provider_id == "deepseek" else 0.20
    _head_keep_target_ratio = getattr(_policy, "head_keep_target_ratio", None)
    if _head_keep_target_ratio is None:
        _head_keep_target_ratio = 0.70 if provider_id == "deepseek" else 0.50
    _compress_target_ratio = float(
        getattr(_policy, "compress_target_ratio", 0.6)
    )

    _current_ingress_message: Message | None = None
    if current_turn_ref is not None:
        try:
            _current_filtered_pos = filtered_indices.index(current_turn_ref)
        except ValueError:
            _current_filtered_pos = -1
        _current_local_pos = prefix_len + _current_filtered_pos
        if (
            _current_filtered_pos >= 0
            and 0 <= _current_local_pos < len(base)
            and is_active_run_ingress_message(base[_current_local_pos])
        ):
            _current_ingress_message = base[_current_local_pos]

    built = build_history_messages(
        base,
        system_prompt,
        max_chars=max_chars if max_chars is not None else runtime_history_budget_value,
        compact_ratio=compact_ratio,  # EVO-20260817: 预算分级主动压缩
        compress_target_ratio=_compress_target_ratio,
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
            int(effective_budget * float(_head_keep_ratio)),
            int(effective_budget * float(_head_keep_force_ratio))
            if cache_monitor.force_head_keep
            else 0,
        ),
        # fixed-head target preserves the historical provider-specific defaults unless
        # an explicit file-backed history policy overrides them.
        head_keep_target_ratio=float(_head_keep_target_ratio),
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
        # Initial ingress and every tool-followup round of the same active run share
        # one wire invariant: the exact current ingress must remain provider-visible
        # even when surrounding atomic tool groups are compacted. Human provenance is
        # intentionally not conflated with delegated run anchoring.
        # `filtered_indices` is an exact original-Session index map, so this adds no
        # semantic task/relevance judgement.
        preserve_last_human_exact=r6_ingress_truth is not None,
        preserve_active_ingress_message=_current_ingress_message,
        current_turn_ref=current_turn_ref,
        # EVO-20260916-ccc978b2（人工已审）: 锚点保护扩到最近 N 条真实 user 指令 +
        # 压缩生效窗口 pin 任务锚快照（N 取自 settings.task_anchor_pin_messages，
        # 默认 2；provider 回调由 engine 侧组装 durable 事实逐字投影）。
        task_anchor_pin_user_messages=int(
            getattr(settings, "task_anchor_pin_messages", 0) or 0
        ),
        task_anchor_snapshot_provider=task_anchor_snapshot_provider,
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
    # EVO-20260916-ccc978b2: pinned（锚钉 user 指令）/summarized（被折叠消息）的
    # 原 session 索引——与 cache_compacted 同一映射口径，写入 stats 供 postprocess
    # 的 history.compaction 事件逐条审计（区分"证据投影"与"真实压缩"）。
    if compact_view_box:
        _compact_stats = compact_view_box[0]
        _compact_stats["pinned_msg_seqs"] = _map_compacted_source_indices(
            [int(_v) for _v in (_compact_stats.get("pinned_msg_seqs_local") or [])],
            prefix_len=prefix_len,
            filtered_indices=filtered_indices,
        )
        _compact_stats["summarized_msg_seqs"] = [
            int(_v) for _v in cache_compacted_source_box
        ]
    # EVO-20260917-2f5ae9cb（人工已审）P0: wire 前缀扰动成因分类（纯观测）。
    # 从本轮 built wire 识别锚快照块（engine 侧加头，直连调用无头则 sha=None）
    # 计算 sha，连同实际锚位/marker 折叠数/新压缩标志喂给 monitor，与其跨 run
    # 状态 diff 出成因并单行日志。getattr 防旧 mock/直连 monitor；任何异常
    # 由 monitor 侧 fail-open 吞掉，不改变构建行为。
    _note_disturbance = getattr(cache_monitor, "note_prefix_disturbance", None)
    if callable(_note_disturbance):
        import hashlib

        _anchor_block_sha: str | None = None
        for _m in built:
            _c = str((_m.get("content") if isinstance(_m, dict) else None) or "")
            if _c.startswith("[任务锚点·压缩存活快照]"):
                _anchor_block_sha = hashlib.sha256(_c.encode("utf-8")).hexdigest()
                break
        try:
            _note_disturbance(
                session_id,
                anchor_block_sha=_anchor_block_sha,
                anchor_arg_used=int(anchor_box[0]) if anchor_box else 0,
                marker_fold_count=len(cache_compacted_box),
                new_compaction=bool(compacted_box) and bool(compacted_box[0]),
            )
        except Exception:  # noqa: BLE001 — 观测通道失败不阻断投影
            pass
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

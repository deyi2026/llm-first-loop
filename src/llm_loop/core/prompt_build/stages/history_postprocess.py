"""历史投影后处理阶段（design T5-C 第二批 / B4-C2-03③）.

cache_compacted 事件写回 + err1210 T4.1 压缩事件序列号状态机 +
EVO-20260825 任务6.2 视图体积验证（压缩风暴前兆归因）+ P1-10
锚点推进持久化（换算回会话索引，clamp + 工具组边界
对齐）+ P0 压缩风暴熔断 note_build_result。R8.8 evidence manifest
指纹字段留空（schema 兼容）。sess.history_anchors 就地写（会话持久化）。
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from llm_loop.core.episode_history import original_anchor_from_filtered
from llm_loop.core.history import mark_cache_compacted_for
from llm_loop.event_log.model import EVENT_HISTORY_COMPACTION

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class HistoryPostprocess:
    """后处理产出（self 面状态机值由调用点回写）."""

    last_history_compacted: bool = False
    compact_event_seq: int = 0
    compact_event_was_compacted: bool = False
    anchor_moved: bool = False
    cache_epoch_reset: bool = False


def run_history_postprocess(
    *,
    cache_compacted_source_box: list[int],
    compacted_box: list[bool],
    compact_view_box: list[dict],
    anchor_box: list[int],
    filtered_indices: list[int],
    prefix_len: int,
    sess: Any,
    sess_anchor: Any,
    provider_id: str,
    resolved_label: str,
    effective_budget: int,
    compact_event_seq: int,
    compact_event_was_compacted: bool,
    cache_monitor: Any,
    event_append: Callable[..., Any],
    provider_visible_chars: Callable[..., int],
) -> HistoryPostprocess:
    """投影后状态机 + 锚点持久化 + 熔断通知（产出待回写状态）."""
    out = HistoryPostprocess(
        compact_event_seq=compact_event_seq,
        compact_event_was_compacted=compact_event_was_compacted,
    )
    # Replay fidelity: msg_seq comes from exact source provenance captured at the
    # compaction site and mapped through the eligibility-filtered projection. Never
    # guess message identity from role/content/ts here.  The event is durable truth,
    # but the current process may keep using this live Session for many more tool
    # rounds without replaying it. Mirror the same exact marker into that canonical
    # live message now; otherwise compaction performed on provider-view receipt copies
    # is forgotten until restart/replay and the same source span can be rewritten on
    # every build.
    for _msg_seq in cache_compacted_source_box:
        if 0 <= _msg_seq < len(sess.messages):
            mark_cache_compacted_for(
                sess.messages[_msg_seq],
                provider_id,
                model_ref=resolved_label,
                effective_budget=effective_budget,
            )
        event_append(
            sess.session_id,
            "message.cache_compacted",
            {
                "msg_seq": _msg_seq,
                "provider_id": provider_id,
                "marker_version": 1,
                "model": resolved_label,
                "effective_budget": int(effective_budget),
            },
        )
    out.last_history_compacted = bool(compacted_box and compacted_box[0])
    # err1210 T4.1: compact 事件序列号——False→True 转变递增（per-session × per-compact-事件
    # 耗尽标记的"事件标识"，engine 侧 _err1210_attempted 据此判定新事件清除旧标记）
    if out.last_history_compacted and not compact_event_was_compacted:
        out.compact_event_seq = compact_event_seq + 1
    out.compact_event_was_compacted = out.last_history_compacted
    _compact_stats = compact_view_box[0] if compact_view_box else {}
    # EVO-20260825 任务6.2: 压缩后视图体积验证——drop<5%（压缩但视图几乎没缩小）
    # → breaker 审计事件 view_not_shrinking_after_compact（压缩风暴前兆归因）
    if compact_view_box:
        try:
            _stats = _compact_stats
            _boundary_mode = str(_stats.get("cache_boundary_mode") or "inactive")
            out.cache_epoch_reset = _boundary_mode == "epoch_reset"
            if _boundary_mode != "inactive":
                event_append(
                    sess.session_id,
                    "cache.compaction_boundary",
                    {
                        "model": resolved_label,
                        "mode": _boundary_mode,
                        "protected_messages": int(
                            _stats.get("cache_protected_messages", 0) or 0
                        ),
                        "protected_chars": int(
                            _stats.get("cache_protected_chars", 0) or 0
                        ),
                        "pre_chars": _stats.get("pre_chars"),
                        "post_chars": _stats.get("post_chars"),
                    },
                )
            if _stats.get("drop_pct", 0) < 5:
                cache_monitor.note_view_not_shrinking(
                    pre_chars=_stats["pre_chars"],
                    post_chars=_stats["post_chars"],
                    drop_pct=_stats["drop_pct"],
                    session_id=sess.session_id,
                    model_ref=resolved_label,
                )
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("view_not_shrinking 审计注入异常（fail-open）", exc_info=True)
    # P1-10: 锚点推进持久化（换算回会话索引, clamp 防御）
    _anchor_after = sess_anchor
    if anchor_box:
        _filtered_new_anchor = max(0, anchor_box[0] - prefix_len)
        new_anchor = original_anchor_from_filtered(
            filtered_indices,
            _filtered_new_anchor,
            original_length=len(sess.messages),
        )
        new_anchor = max(0, min(len(sess.messages), new_anchor))
        # EVO-20260817-72fcd94a L3 归因: 锚点实际前移（≠旧锚点）→ 记入缓存失效归因窗口
        if new_anchor != sess_anchor:
            cache_monitor.note_anchor_moved(session_id=sess.session_id)
            out.anchor_moved = True
        # 2026-08-16 锚点推进对齐工具轮边界（现场：tool_call_id is not found 根因）：
        # 锚点不得落在声明↔回执组内——若锚点处是 tool 回执（其声明在锚点前），
        # 拉回至该轮声明起点（整组保留，防孤儿回执）。
        while 0 < new_anchor < len(sess.messages) and sess.messages[new_anchor].role == "tool":
            new_anchor -= 1
        if sess.history_anchors is None:
            sess.history_anchors = {}
        sess.history_anchors[provider_id] = new_anchor
        if getattr(sess, "history_anchor_scopes", None) is None:
            sess.history_anchor_scopes = {}
        if new_anchor > 0:
            sess.history_anchor_scopes[provider_id] = {
                "version": 1,
                "model": resolved_label,
                "effective_budget": int(effective_budget),
            }
        else:
            sess.history_anchor_scopes.pop(provider_id, None)
        _anchor_after = new_anchor

    # P4 deterministic replay: persist exact compact trigger/config/result facts as
    # append-only runtime evidence. This event is never projected into the model prompt.
    if out.last_history_compacted and _compact_stats:
        with contextlib.suppress(Exception):
            event_append(
                sess.session_id,
                EVENT_HISTORY_COMPACTION,
                {
                    "model": resolved_label,
                    "provider_id": provider_id,
                    "compaction_epoch": out.compact_event_seq,
                    "trigger": _compact_stats.get("trigger"),
                    "pre_history_chars": _compact_stats.get("pre_history_chars"),
                    "pre_chars": _compact_stats.get("pre_chars"),
                    "post_chars": _compact_stats.get("post_chars"),
                    "effective_budget_chars": _compact_stats.get("effective_budget_chars"),
                    "compact_ratio": _compact_stats.get("compact_ratio"),
                    "trigger_limit_chars": _compact_stats.get("trigger_limit_chars"),
                    "trigger_excess_chars": _compact_stats.get("trigger_excess_chars"),
                    "archive_target_ratio": _compact_stats.get("archive_target_ratio"),
                    "archive_target_chars": _compact_stats.get("archive_target_chars"),
                    "archived_count": _compact_stats.get("archived_count"),
                    "archived_group_count": _compact_stats.get("archived_group_count"),
                    "atomic_group_count": _compact_stats.get("atomic_group_count"),
                    "compaction_mode": _compact_stats.get("compaction_mode"),
                    "head_keep_chars": _compact_stats.get("head_keep_chars"),
                    "head_keep_target_ratio": _compact_stats.get("head_keep_target_ratio"),
                    "cache_boundary_mode": _compact_stats.get("cache_boundary_mode"),
                    "cache_protected_messages": _compact_stats.get("cache_protected_messages"),
                    "cache_protected_chars": _compact_stats.get("cache_protected_chars"),
                    "cache_epoch_reset": out.cache_epoch_reset,
                    "anchor_before": sess_anchor,
                    "anchor_after": _anchor_after,
                    "anchor_moved": out.anchor_moved,
                },
            )
    # P0 压缩风暴熔断（2026-08-25）: 每轮 build 结果通知 monitor——
    # 连续 (compacted 且 anchor_moved) 计数 → 达阈值进入 breaker（冻结压缩+锚点）。
    # chars_total 用锚定视图口径（实际提交量——锚点压缩只前移锚点不删 sess.messages，
    # 全量口径会让压力永不解除）。
    with contextlib.suppress(Exception):
        _view_start = min(sess_anchor, len(sess.messages))
        cache_monitor.note_build_result(
            compacted=out.last_history_compacted,
            anchor_moved=out.anchor_moved,
            chars_total=provider_visible_chars(
                sess.messages, provider_id, _view_start
            ),
            budget=effective_budget,
            session_id=sess.session_id,
            model_ref=resolved_label,
        )
    return out

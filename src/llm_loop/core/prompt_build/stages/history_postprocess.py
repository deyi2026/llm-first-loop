"""历史投影后处理阶段（design T5-C 第二批 / B4-C2-03③）.

cache_compacted 事件写回 + err1210 T4.1 压缩事件序列号状态机 +
EVO-20260825 任务6.2 视图体积验证（压缩风暴前兆归因）+ 任务7 渐进折叠
降级审计 + P1-10 锚点推进持久化（换算回会话索引，clamp + 工具组边界
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
from llm_loop.core.message import Message

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class HistoryPostprocess:
    """后处理产出（self 面状态机值由调用点回写）."""

    last_history_compacted: bool = False
    compact_event_seq: int = 0
    compact_event_was_compacted: bool = False
    anchor_moved: bool = False
    cache_degrade_note: str | None = None


def run_history_postprocess(
    *,
    cache_compacted_box: list[Message],
    compacted_box: list[bool],
    compact_view_box: list[dict],
    degrade_box: list[dict],
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
    resolve_msg_seq: Callable[..., Any],
    event_append: Callable[..., Any],
    provider_visible_chars: Callable[..., int],
) -> HistoryPostprocess:
    """投影后状态机 + 锚点持久化 + 熔断通知（产出待回写状态）."""
    out = HistoryPostprocess(
        compact_event_seq=compact_event_seq,
        compact_event_was_compacted=compact_event_was_compacted,
    )
    for _compacted_msg in cache_compacted_box:
        _msg_seq = resolve_msg_seq(sess.session_id, _compacted_msg)
        if _msg_seq is None:
            logger.warning(
                "provider中段压缩事件未定位消息序号: sid=%s provider=%s",
                sess.session_id,
                provider_id,
            )
            continue
        event_append(
            sess.session_id,
            "message.cache_compacted",
            {"msg_seq": _msg_seq, "provider_id": provider_id},
        )
    out.last_history_compacted = bool(compacted_box and compacted_box[0])
    # err1210 T4.1: compact 事件序列号——False→True 转变递增（per-session × per-compact-事件
    # 耗尽标记的"事件标识"，engine 侧 _err1210_attempted 据此判定新事件清除旧标记）
    if out.last_history_compacted and not compact_event_was_compacted:
        out.compact_event_seq = compact_event_seq + 1
    out.compact_event_was_compacted = out.last_history_compacted
    # EVO-20260825 任务6.2: 压缩后视图体积验证——drop<5%（压缩但视图几乎没缩小）
    # → breaker 审计事件 view_not_shrinking_after_compact（压缩风暴前兆归因）
    if compact_view_box:
        try:
            _stats = compact_view_box[0]
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
    # EVO-20260825 任务7（§5.7）: 渐进折叠 archive_provider 缺失降级——审计 +
    # 降级提示注入 metadata.cache_health（kind="degraded"，_post_run_cache_health 回写）
    if degrade_box:
        try:
            _deg = degrade_box[0]
            cache_monitor.note_degraded(
                reason=_deg.get("reason", "progressive_fold 要求 cache_archive_provider"),
                head_keep_chars=_deg.get("head_keep_chars", 0),
                session_id=sess.session_id,
                model_ref=resolved_label,
            )
            out.cache_degrade_note = (
                f"[渐进折叠降级] {_deg.get('reason')}——已关闭渐进折叠，"
                f"head_keep 预算 {_deg.get('head_keep_chars')} 字符"
            )
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("archive_provider 降级注入异常（fail-open）", exc_info=True)
    # P1-10: 锚点推进持久化（换算回会话索引, clamp 防御）
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

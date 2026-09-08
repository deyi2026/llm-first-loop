"""历史投影接线三段 facade（B4-CLOSE-01 步C1；语义原样迁自 build.py）.

prep（预算预检/锚点测算）→ projection（压缩投影/水印锚定）→
postprocess（锚点事件/降级记账）。调 history 现函数，Phase 7 前不
动其内部；wiring 层聚合三调用 + self 面写回值产出。
"""

from dataclasses import dataclass
from typing import Any

from llm_loop.core.prompt_build.stages.history_budget_prep import run_history_budget_prep
from llm_loop.core.prompt_build.stages.history_postprocess import run_history_postprocess
from llm_loop.core.prompt_build.stages.history_projection import run_history_projection
from llm_loop.event_log.model import EVENT_HISTORY_COMPACTION_STATE_RESET

_ANCHOR_SCOPE_VERSION = 1


def _anchor_for_current_contract(
    sess: Any,
    *,
    provider_id: str,
    resolved_label: str,
    sess_anchor: int,
    effective_budget: int,
) -> int:
    """Return a persisted anchor only when its model/budget provenance is still valid.

    Legacy anchors had no provenance and therefore survived model/context upgrades
    forever.  A nonzero unversioned anchor is stale under a concrete current
    contract: clear it once and let the current build re-project from eligible raw
    history.  A versioned anchor remains valid for the same model while the current
    budget is no more permissive than the budget that created it.
    """
    anchor = max(0, int(sess_anchor or 0))
    if anchor <= 0:
        return 0
    scopes = getattr(sess, "history_anchor_scopes", None)
    scope = scopes.get(provider_id) if isinstance(scopes, dict) else None
    valid = False
    if isinstance(scope, dict):
        try:
            valid = (
                int(scope.get("version", 0) or 0) == _ANCHOR_SCOPE_VERSION
                and str(scope.get("model") or "") == resolved_label
                and int(effective_budget) <= int(scope.get("effective_budget", 0) or 0)
            )
        except (TypeError, ValueError):
            valid = False
    if valid:
        return anchor

    anchors = getattr(sess, "history_anchors", None)
    if isinstance(anchors, dict):
        anchors[provider_id] = 0
    if isinstance(scopes, dict):
        scopes.pop(provider_id, None)
    return 0


@dataclass(slots=True)
class HistoryPipelineOutcome:
    """历史投影产物（wire 序列 + 预算/锚点/记账写回面）."""

    built: list[dict]
    effective_budget: int
    compact_view_box: Any
    anchor_moved: bool
    last_build_info: dict
    last_nudge_total: Any
    last_compact_ratio: float | None
    last_history_compacted: Any
    compact_event_seq: int
    compact_event_was_compacted: bool
    cache_epoch_reset: bool
    influence: dict[str, Any]


def run_history_pipeline(
    *,
    sess: Any,
    provider_id: str,
    sess_anchor: int,
    max_chars: int | None,
    base: list[Any],
    system_prompt: str,
    filtered_indices: list[int],
    prefix_len: int,
    resolved_label: str,
    registry_snapshot: Any = None,
    r6_ingress_truth: Any = None,
    decision: Any,
    runtime_history_budget: Any,
    archive: Any,
    registry: Any,
    archive_sink_cb: Any,
    record_action: Any,
    settings: Any,
    cache_monitor: Any,
    cache_protected_prefix_messages: int = 0,
    cache_protected_prefix_chars: int = 0,
    current_turn_ref: int | None = None,
    event_append: Any,
    compact_event_seq: int = 0,
    compact_event_was_compacted: bool = False,
    last_nudge_total: Any = None,
    provider_visible_chars_fn: Any,
    growth_nudge_kind_fn: Any,
    reasoning_tail_fn: Any,
) -> HistoryPipelineOutcome:
    """prep → projection → postprocess 三段接线（语义原样）."""
    _prep = run_history_budget_prep(
        sess_messages=sess.messages,
        provider_id=provider_id,
        sess_anchor=sess_anchor,
        max_chars=max_chars,
        runtime_history_budget=runtime_history_budget,
        archive=archive,
        registry=registry,
        archive_sink_cb=archive_sink_cb,
        decision=decision,
        record_action=record_action,
        last_nudge_total=last_nudge_total,
        provider_visible_chars=provider_visible_chars_fn,
        growth_nudge_kind=growth_nudge_kind_fn,
    )
    archive_sink = _prep.archive_sink
    effective_budget = _prep.effective_budget
    effective_sess_anchor = _anchor_for_current_contract(
        sess,
        provider_id=provider_id,
        resolved_label=resolved_label,
        sess_anchor=sess_anchor,
        effective_budget=effective_budget,
    )
    legacy_anchor_reset = int(sess_anchor or 0) > 0 and effective_sess_anchor == 0
    _proj = run_history_projection(
        base=base,
        system_prompt=system_prompt,
        filtered_indices=filtered_indices,
        sess_anchor=effective_sess_anchor,
        prefix_len=prefix_len,
        session_id=sess.session_id,
        max_chars=max_chars,
        runtime_history_budget_value=runtime_history_budget(),
        compact_ratio=_prep.compact_ratio,
        archive_sink=archive_sink,
        settings=settings,
        provider_id=provider_id,
        resolved_label=resolved_label,
        reasoning_tail=reasoning_tail_fn(
            settings,
            resolved_label=resolved_label,
            registry_snapshot=registry_snapshot,
        ),
        r6_ingress_truth=r6_ingress_truth,
        registry=registry,
        cache_monitor=cache_monitor,
        effective_budget=effective_budget,
        cache_protected_prefix_messages=cache_protected_prefix_messages,
        cache_protected_prefix_chars=cache_protected_prefix_chars,
        current_turn_ref=current_turn_ref,
    )
    built = _proj.built
    anchor_box = _proj.anchor_box
    compacted_box = _proj.compacted_box
    cache_compacted_source_box = _proj.cache_compacted_source_box
    compact_view_box = _proj.compact_view_box
    compaction_state_reset = legacy_anchor_reset or _proj.reopened_marker_count > 0
    if compaction_state_reset:
        event_append(
            sess.session_id,
            EVENT_HISTORY_COMPACTION_STATE_RESET,
            {
                "model": resolved_label,
                "provider_id": provider_id,
                "effective_budget": effective_budget,
                "legacy_anchor_reset": legacy_anchor_reset,
                "anchor_before": int(sess_anchor or 0),
                "reopened_marker_count": _proj.reopened_marker_count,
                "reason": "compaction_contract_changed",
            },
        )
    _post = run_history_postprocess(
        cache_compacted_source_box=cache_compacted_source_box,
        compacted_box=compacted_box,
        compact_view_box=compact_view_box,
        anchor_box=anchor_box,
        filtered_indices=filtered_indices,
        prefix_len=prefix_len,
        sess=sess,
        sess_anchor=effective_sess_anchor,
        provider_id=provider_id,
        resolved_label=resolved_label,
        effective_budget=effective_budget,
        compact_event_seq=compact_event_seq,
        compact_event_was_compacted=compact_event_was_compacted,
        cache_monitor=cache_monitor,
        event_append=event_append,
        provider_visible_chars=provider_visible_chars_fn,
    )
    return HistoryPipelineOutcome(
        built=built,
        effective_budget=effective_budget,
        compact_view_box=compact_view_box,
        anchor_moved=_post.anchor_moved,
        last_build_info={
            "base": base,
            "system_prompt": system_prompt,
            "memory_msgs": [],  # compatibility key; automatic memory prompt path retired
            "budget": effective_budget,
        },
        last_nudge_total=_prep.last_nudge_total,
        last_compact_ratio=_prep.compact_ratio,
        last_history_compacted=_post.last_history_compacted,
        compact_event_seq=_post.compact_event_seq,
        compact_event_was_compacted=_post.compact_event_was_compacted,
        cache_epoch_reset=_post.cache_epoch_reset or compaction_state_reset,
        influence={
            "input_messages": len(base),
            "built_messages": len(built),
            "history_total_chars": int(decision.history_total_chars or 0),
            "effective_budget": int(effective_budget or 0),
            "compacted": bool(_post.last_history_compacted),
            "anchor_before": int(effective_sess_anchor or 0),
            "anchor_moved": bool(_post.anchor_moved),
            "reopened_marker_count": int(_proj.reopened_marker_count or 0),
            "exact_duplicate_tool_projection": dict(_proj.duplicate_tool_projection_stats or {}),
            "compaction_stats": dict(compact_view_box[0]) if compact_view_box else {},
        },
    )

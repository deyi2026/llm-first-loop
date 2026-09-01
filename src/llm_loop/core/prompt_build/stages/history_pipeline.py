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
    cache_degrade_note: Any


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
    emergency_compact: bool,
    resolved_label: str,
    registry_snapshot: Any = None,
    r6_ingress_truth: Any = None,
    memory_msgs: list[Any],
    decision: Any,
    runtime_history_budget: Any,
    archive: Any,
    registry: Any,
    archive_sink_cb: Any,
    record_action: Any,
    settings: Any,
    cache_monitor: Any,
    resolve_msg_seq: Any,
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
    _proj = run_history_projection(
        base=base,
        system_prompt=system_prompt,
        filtered_indices=filtered_indices,
        sess_anchor=sess_anchor,
        prefix_len=prefix_len,
        session_id=sess.session_id,
        max_chars=max_chars,
        runtime_history_budget_value=runtime_history_budget(),
        compact_ratio=_prep.compact_ratio,
        archive_sink=archive_sink,
        settings=settings,
        provider_id=provider_id,
        emergency_compact=emergency_compact,
        reasoning_tail=reasoning_tail_fn(
            settings,
            resolved_label=resolved_label,
            registry_snapshot=registry_snapshot,
        ),
        r6_ingress_truth=r6_ingress_truth,
        registry=registry,
        cache_monitor=cache_monitor,
        effective_budget=effective_budget,
        progressive_fold_k=_prep.fold_k,
    )
    built = _proj.built
    anchor_box = _proj.anchor_box
    compacted_box = _proj.compacted_box
    cache_compacted_box = _proj.cache_compacted_box
    compact_view_box = _proj.compact_view_box
    degrade_box = _proj.degrade_box
    _post = run_history_postprocess(
        cache_compacted_box=cache_compacted_box,
        compacted_box=compacted_box,
        compact_view_box=compact_view_box,
        degrade_box=degrade_box,
        anchor_box=anchor_box,
        filtered_indices=filtered_indices,
        prefix_len=prefix_len,
        sess=sess,
        sess_anchor=sess_anchor,
        provider_id=provider_id,
        resolved_label=resolved_label,
        effective_budget=effective_budget,
        compact_event_seq=compact_event_seq,
        compact_event_was_compacted=compact_event_was_compacted,
        cache_monitor=cache_monitor,
        resolve_msg_seq=resolve_msg_seq,
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
            "memory_msgs": memory_msgs,
            "budget": effective_budget,
        },
        last_nudge_total=_prep.last_nudge_total,
        last_compact_ratio=_prep.compact_ratio,
        last_history_compacted=_post.last_history_compacted,
        compact_event_seq=_post.compact_event_seq,
        compact_event_was_compacted=_post.compact_event_was_compacted,
        cache_degrade_note=_post.cache_degrade_note,
    )

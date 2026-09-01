"""budget_application 阶段（design T5-C 第三批 / B4-C3-03）

INJECTION-GOVERNANCE R2/L2-1: 单一总预算门闸——一次性裁决三类真实
prompt 块（① history 已持久化 program-origin；② 本轮动态聚合槽；
③ enforce packet 额外投影槽/语义 header），仅整块保留/丢弃不截断半
块；超界双面修剪（wire/packet 同裁决）+ header 未保留时投影/锚点
清空 + R8.11/E21 预算回执仅观测（零 prompt 记账）+ R4 recovery
拉出（PROGRAM_RECOVERY 不处 appendix/WARM 投影之下，latest-wins
去重）。决策入 BuildDecision.budget；budget_result 由调用点回写
self._last_injection_budget。
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from llm_loop.core.injection_budget import plan_prompt_injection_budget
from llm_loop.core.injection_labels import InjectionLayer, infer_layer

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BudgetApplicationOutcome:
    """预算应用产出（六重绑定量 + 决策面）."""

    inject_parts: list[tuple[str | None, str]] = field(default_factory=list)
    inject_keys: list[str] = field(default_factory=list)
    packet_parts: list[tuple[str | None, str]] = field(default_factory=list)
    packet_keys: list[str] = field(default_factory=list)
    recovery_render_parts: list[str] = field(default_factory=list)
    sem_state: Any = None
    projection: str = ""
    anchor: str = ""
    budget_result: Any = None
    budget: dict[str, Any] = field(default_factory=dict)


def apply_injection_budget(
    *,
    built: list[Any],
    inject_parts: list[tuple[str | None, str]],
    inject_keys: list[str],
    packet_parts: list[tuple[str | None, str]],
    packet_keys: list[str],
    projection: str,
    anchor: str,
    sem_state: Any,
    cog_enforce: bool,
    tier_on: bool,
    compile_decision_packet: Any,
    recovery_render_parts: list[str],
    injection_budget_chars: int,
    record_action: Callable[..., Any],
) -> BudgetApplicationOutcome:
    """预算门闸 + recovery 拉出（原 _build_llm_messages L1059-1181 段语义原样）."""
    _inject_parts = inject_parts
    _inject_keys = inject_keys
    _packet_parts = packet_parts
    _packet_keys = packet_keys
    _recovery_render_parts = recovery_render_parts
    _projection = projection
    _anchor = anchor
    _sem_state = sem_state
    _cog_enforce = cog_enforce
    _tier_on = tier_on
    # INJECTION-GOVERNANCE R2/L2-1: 单一总预算门闸。
    # 一次性裁决三类真实 prompt 块：① history 已持久化 program-origin；
    # ② 本轮动态聚合槽；③ enforce packet 额外投影槽/语义 header。
    # 各来源不得自行另算预算；裁决仅整块保留/丢弃，不截断半块。
    _budget_use_packet = bool(
        _cog_enforce and _tier_on and compile_decision_packet is not None
    )
    _budget_parts = _packet_parts if _budget_use_packet else _inject_parts
    _budget_part_keys = _packet_keys if _budget_use_packet else _inject_keys
    _budget_header_text = (
        _projection if (_budget_use_packet and _projection) else
        (_anchor if not _budget_use_packet else "")
    )
    _budget_header_slot = (
        "decision_header" if _budget_use_packet else "task_anchor"
    )
    _budget_plan = plan_prompt_injection_budget(
        built,
        _budget_parts,
        _budget_part_keys,
        budget_chars=injection_budget_chars,
        header_content=_budget_header_text,
        header_slot=_budget_header_slot,
    )
    _budget_result = _budget_plan.result
    # self._last_injection_budget 回写由调用点执行（budget_result 经 Outcome 返回）
    if _budget_result.over_budget:
        if _budget_plan.dropped_existing_indices:
            built[:] = [
                _m for _idx, _m in enumerate(built)
                if _idx not in _budget_plan.dropped_existing_indices
            ]
        _budget_keep = _budget_plan.kept_part_keys
        if _budget_use_packet:
            _packet_pairs = [
                (_part, _key)
                for _part, _key in zip(_packet_parts, _packet_keys, strict=True)
                if _key in _budget_keep
            ]
            _packet_parts = [_part for _part, _key in _packet_pairs]
            _packet_keys = [_key for _part, _key in _packet_pairs]
            _dyn_keep = set(_packet_keys)
            _inject_pairs = [
                (_part, _key)
                for _part, _key in zip(_inject_parts, _inject_keys, strict=True)
                if _key in _dyn_keep
            ]
            _inject_parts = [_part for _part, _key in _inject_pairs]
            _inject_keys = [_key for _part, _key in _inject_pairs]
        else:
            _inject_pairs = [
                (_part, _key)
                for _part, _key in zip(_inject_parts, _inject_keys, strict=True)
                if _key in _budget_keep
            ]
            _inject_parts = [_part for _part, _key in _inject_pairs]
            _inject_keys = [_key for _part, _key in _inject_pairs]
            # shadow packet 仅 telemetry；其动态槽与真实 prompt 保持同一裁决。
            _selected_dynamic = set(_inject_keys)
            _packet_pairs = [
                (_part, _key)
                for _part, _key in zip(_packet_parts, _packet_keys, strict=True)
                if (not _key.startswith("dynamic:")) or _key in _selected_dynamic
            ]
            _packet_parts = [_part for _part, _key in _packet_pairs]
            _packet_keys = [_key for _part, _key in _packet_pairs]
        if not _budget_plan.header_kept:
            if _budget_use_packet:
                _sem_state = None
                _projection = ""
            _anchor = ""
        # R8.11/E21: budget receipt is assembler observability only.  The
        # structured result/action trace records pruning; no receipt text is
        # appended after eligibility and no prompt budget is spent on bookkeeping.
        try:
            record_action(
                "action.injection_budget",
                "pruned",
                f"used={_budget_result.used_chars}/"
                f"{_budget_result.budget_chars}; "
                f"dropped={len(_budget_result.dropped_blocks)};prompt_receipt=0",
            )
        except Exception:  # noqa: BLE001 — 预算已执行，审计失败不回滚
            logger.debug("build: injection budget action trace 失败", exc_info=True)

    # R4: budget selection is shared with all injections, but rendering is not.
    # PROGRAM_RECOVERY must not sit under the background-only appendix notice or
    # Cognitive WARM projection.  Pull the at-most-one recovery part out after R2
    # has decided keep/drop, and remove the same key from packet compilation.
    _recovery_keys: set[str] = set()
    for (_part, _key) in zip(_inject_parts, _inject_keys, strict=True):
        _slot, _content = _part
        if infer_layer(_content, slot_kind=str(_slot or "")) is InjectionLayer.PROGRAM_RECOVERY:
            _recovery_keys.add(_key)
            _recovery_render_parts.append(_content)
    if len(_recovery_render_parts) > 1:
        # Closed runtime slot should make this unreachable; latest wins defensively.
        _recovery_render_parts = [_recovery_render_parts[-1]]
        with contextlib.suppress(Exception):
            record_action(
                "action.program_recovery", "duplicate_suppressed", "count>1"
            )
    if _recovery_keys:
        _inject_pairs = [
            (_part, _key)
            for _part, _key in zip(_inject_parts, _inject_keys, strict=True)
            if _key not in _recovery_keys
        ]
        _inject_parts = [_part for _part, _key in _inject_pairs]
        _inject_keys = [_key for _part, _key in _inject_pairs]
        _packet_pairs = [
            (_part, _key)
            for _part, _key in zip(_packet_parts, _packet_keys, strict=True)
            if _key not in _recovery_keys
        ]
        _packet_parts = [_part for _part, _key in _packet_pairs]
        _packet_keys = [_key for _part, _key in _packet_pairs]

    out = BudgetApplicationOutcome(
        inject_parts=_inject_parts,
        inject_keys=_inject_keys,
        packet_parts=_packet_parts,
        packet_keys=_packet_keys,
        recovery_render_parts=_recovery_render_parts,
        sem_state=sem_state,
        projection=projection,
        anchor=anchor,
        budget_result=_budget_result,
        budget={
            "use_packet": bool(_budget_use_packet),
            "over_budget": bool(_budget_result.over_budget),
            "budget_chars": int(_budget_result.budget_chars),
            "used_chars": int(_budget_result.used_chars),
            "dropped_blocks": len(_budget_result.dropped_blocks),
            "header_kept": bool(_budget_plan.header_kept),
            "kept_part_keys": len(_budget_plan.kept_part_keys),
            "recovery_pulled": len(_recovery_render_parts),
        },
    )
    return out

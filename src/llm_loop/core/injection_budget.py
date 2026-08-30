"""Unified hard budget assembler for program-origin prompt material (R2/L2-1).

This module is deliberately source-agnostic: memory, experience, status, recovery,
Cognitive Runtime slots and persisted program messages all enter the same block list.
The assembler keeps or drops whole blocks; it never truncates block content.

``DEFAULT_INJECTION_BUDGET_CHARS`` is an R2 candidate default, not a calibrated
product constant. R7/L3 A/B may change it later. Operators can override it with
``INJECTION_BUDGET_CHARS``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Sequence

from llm_loop.core.injection_labels import (
    InjectionLayer,
    PROGRAM_APPENDIX_NOTICE,
    detect_program_layer,
    infer_layer,
)

DEFAULT_INJECTION_BUDGET_CHARS = 8000
MIN_INJECTION_BUDGET_CHARS = 512
DYNAMIC_APPENDIX_GROUP = "dynamic_appendix"
# One outer arbitration notice + final semantic label/newlines. Slot/header-specific
# marker costs are carried by each BudgetBlock.cost_chars.
DYNAMIC_APPENDIX_GROUP_OVERHEAD = len(PROGRAM_APPENDIX_NOTICE) + 32


class BudgetPriority(IntEnum):
    """Lower value survives first when the hard budget is tight."""

    RECEIPT = 0
    PROGRAM_RECOVERY = 10
    CRITICAL_STATUS = 20
    STATUS = 30
    REFERENCE = 40


_CRITICAL_STATUS_SLOTS = frozenset(
    {
        "decision_header",
        "semantic_header",
        "task_anchor",
        "task_frontier",
        "interop",
        "gate_note",
        "budget_receipt",
    }
)


@dataclass(frozen=True)
class BudgetBlock:
    """One indivisible program-origin block presented to the unified assembler."""

    key: str
    content: str
    layer: InjectionLayer
    slot_kind: str = ""
    group: str = ""
    cost_chars_override: int | None = None
    ordinal: int = 0

    @property
    def cost_chars(self) -> int:
        if self.cost_chars_override is not None:
            return max(0, int(self.cost_chars_override))
        return len(self.content)

    @property
    def priority(self) -> BudgetPriority:
        if self.slot_kind == "budget_receipt":
            return BudgetPriority.RECEIPT
        if self.layer is InjectionLayer.PROGRAM_RECOVERY:
            return BudgetPriority.PROGRAM_RECOVERY
        if self.layer is InjectionLayer.STATUS:
            if self.slot_kind.strip().lower() in _CRITICAL_STATUS_SLOTS:
                return BudgetPriority.CRITICAL_STATUS
            return BudgetPriority.STATUS
        return BudgetPriority.REFERENCE


@dataclass(frozen=True)
class InjectionBudgetResult:
    budget_chars: int
    used_chars: int
    group_overhead_chars: int
    over_budget: bool
    kept_blocks: tuple[BudgetBlock, ...]
    dropped_blocks: tuple[BudgetBlock, ...]
    receipt_content: str = ""

    @property
    def kept_keys(self) -> frozenset[str]:
        return frozenset(b.key for b in self.kept_blocks)

    @property
    def dropped_keys(self) -> frozenset[str]:
        return frozenset(b.key for b in self.dropped_blocks)


def _group_overhead(group: str) -> int:
    return DYNAMIC_APPENDIX_GROUP_OVERHEAD if group == DYNAMIC_APPENDIX_GROUP else 0


def _total_cost(blocks: list[BudgetBlock] | tuple[BudgetBlock, ...]) -> tuple[int, int]:
    seen: set[str] = set()
    overhead = 0
    cost = 0
    for block in blocks:
        cost += block.cost_chars
        if block.group and block.group not in seen:
            seen.add(block.group)
            overhead += _group_overhead(block.group)
    return cost + overhead, overhead


def _budget_receipt(budget_chars: int) -> str:
    # Non-imperative by construction: factual assembly receipt only, no action verbs.
    return (
        f"[注入预算] 本轮自动程序附录超过候选预算上限 {budget_chars} 字符；"
        "部分低优先级块未进入请求。该记录仅描述本轮组装结果。"
    )


def enforce_injection_budget(
    blocks: list[BudgetBlock] | tuple[BudgetBlock, ...],
    *,
    budget_chars: int,
) -> InjectionBudgetResult:
    """Apply one hard budget to all program-origin blocks.

    Selection is deterministic: semantic priority first, then caller ordinal and
    original list order. A block is accepted only if its *entire* estimated wire
    cost fits. When pruning occurs, a factual receipt is itself charged to the
    same budget and survives at the highest priority.
    """
    budget = max(MIN_INJECTION_BUDGET_CHARS, int(budget_chars))
    source = list(blocks)
    total, total_overhead = _total_cost(source)
    if total <= budget:
        return InjectionBudgetResult(
            budget_chars=budget,
            used_chars=total,
            group_overhead_chars=total_overhead,
            over_budget=False,
            kept_blocks=tuple(source),
            dropped_blocks=(),
        )

    receipt = _budget_receipt(budget)
    receipt_block = BudgetBlock(
        key="__budget_receipt__",
        content=receipt,
        layer=InjectionLayer.STATUS,
        slot_kind="budget_receipt",
        group=DYNAMIC_APPENDIX_GROUP,
        cost_chars_override=len(receipt) + 48,  # tier/slot marker conservative allowance
        ordinal=-1,
    )
    ranked_source = sorted(
        enumerate(source),
        key=lambda item: (int(item[1].priority), int(item[1].ordinal), item[0]),
    )
    ranked = [receipt_block] + [block for _idx, block in ranked_source]
    kept: list[BudgetBlock] = []
    seen_groups: set[str] = set()
    used = 0
    overhead = 0
    for block in ranked:
        inc = block.cost_chars
        group_inc = 0
        if block.group and block.group not in seen_groups:
            group_inc = _group_overhead(block.group)
        if used + inc + group_inc <= budget:
            kept.append(block)
            used += inc + group_inc
            overhead += group_inc
            if block.group:
                seen_groups.add(block.group)
        elif block.key == "__budget_receipt__":  # defensive only; MIN budget should fit
            receipt = ""

    kept_keys = {b.key for b in kept}
    # Preserve original source ordering in the public kept/dropped lists. Receipt
    # is signalled separately and is not part of caller block identity.
    kept_source = tuple(b for b in source if b.key in kept_keys)
    dropped_source = tuple(b for b in source if b.key not in kept_keys)
    return InjectionBudgetResult(
        budget_chars=budget,
        used_chars=used,
        group_overhead_chars=overhead,
        over_budget=True,
        kept_blocks=kept_source,
        dropped_blocks=dropped_source,
        receipt_content=receipt,
    )


@dataclass(frozen=True)
class PromptBudgetPlan:
    """Budget decision mapped back to build's existing and dynamic prompt structures."""

    result: InjectionBudgetResult
    dropped_existing_indices: frozenset[int]
    kept_part_keys: frozenset[str]
    header_kept: bool


def plan_prompt_injection_budget(
    existing_messages: Sequence[dict[str, Any]],
    parts: Sequence[tuple[str | None, str]],
    part_keys: Sequence[str],
    *,
    budget_chars: int,
    header_content: str = "",
    header_slot: str = "",
) -> PromptBudgetPlan:
    """Collect every prompt-visible program block and apply the single R2 budget.

    ``existing_messages`` covers persisted program-origin history. ``parts`` covers
    this build's flat/tier packet inputs. ``header_content`` covers task anchor or
    semantic decision header. Costs conservatively include final merge/slot markers,
    so the returned accounting is an upper bound on rendered program chars.
    """
    if len(parts) != len(part_keys):
        raise ValueError("parts/part_keys length mismatch")

    blocks: list[BudgetBlock] = []
    existing_keys: dict[int, str] = {}
    for idx, message in enumerate(existing_messages):
        content = str(message.get("content") or "")
        layer = detect_program_layer(content)
        if layer is None or layer is InjectionLayer.USER_INSTRUCTION:
            continue
        key = f"existing:{idx}"
        existing_keys[idx] = key
        blocks.append(
            BudgetBlock(
                key,
                content,
                layer,
                slot_kind="persisted",
                cost_chars_override=len(content) + 2,  # possible "\n\n" tail merge
                ordinal=10_000 + (len(existing_messages) - idx),
            )
        )

    for ordinal, ((slot, content), key) in enumerate(zip(parts, part_keys, strict=True)):
        text = str(content or "")
        blocks.append(
            BudgetBlock(
                key,
                text,
                infer_layer(text, slot_kind=str(slot or "")),
                slot_kind=str(slot or "hint"),
                group=DYNAMIC_APPENDIX_GROUP,
                cost_chars_override=len(text) + 64,
                ordinal=ordinal,
            )
        )

    header_key = ""
    if header_content:
        header_key = f"dynamic:{header_slot or 'header'}"
        blocks.append(
            BudgetBlock(
                header_key,
                header_content,
                InjectionLayer.STATUS,
                slot_kind=header_slot or "decision_header",
                group=DYNAMIC_APPENDIX_GROUP,
                cost_chars_override=len(header_content) + 64,
                ordinal=-10,
            )
        )

    result = enforce_injection_budget(blocks, budget_chars=budget_chars)
    kept = result.kept_keys
    return PromptBudgetPlan(
        result=result,
        dropped_existing_indices=frozenset(
            idx for idx, key in existing_keys.items() if key not in kept
        ),
        kept_part_keys=frozenset(key for key in part_keys if key in kept),
        header_kept=(not header_key or header_key in kept),
    )

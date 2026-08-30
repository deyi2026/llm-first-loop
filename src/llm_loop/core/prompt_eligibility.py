"""Prompt eligibility gates for program-origin context.

Eligibility is intentionally stricter than semantic labelling.  A program block may be
perfectly valid STATUS/REFERENCE material and still be ineligible for automatic prompt
projection.  Unknown producers are deny-by-default; durable state remains retrievable.
"""

from __future__ import annotations

from typing import Any

from llm_loop.core.injection_labels import InjectionLayer, infer_layer

# Explicit automatic-prompt producer allowlist.  Keep this as plain strings so the
# eligibility core does not depend on loop/err1210 enums (which would create a cycle).
PROMPT_DYNAMIC_PRODUCER_SLOTS = frozenset(
    {
        "program_recovery",
        "memory",
        "interop",
        "tip",
        "hotcard",
        "gate_note",
        "digest",
        "task_frontier",
    }
)


def dynamic_prompt_layer(content: str, *, slot_kind: str | None) -> InjectionLayer | None:
    """Return a semantic layer only for an explicitly eligible dynamic producer.

    Semantic classification and prompt eligibility are separate decisions.  ``infer_layer``
    retains its legacy STATUS fallback for rendering compatibility, but that fallback must
    never grant a new/unknown producer prompt access.
    """

    slot = str(slot_kind or "").strip().lower()
    if slot not in PROMPT_DYNAMIC_PRODUCER_SLOTS:
        return None
    return infer_layer(str(content or ""), slot_kind=slot)


def is_memory_snapshot(message: Any) -> bool:
    md = getattr(message, "metadata", None) or {}
    return md.get("injection_kind") == "memory_snapshot"


def memory_snapshot_prompt_eligible(message: Any, *, current_turn_ref: int | None) -> bool:
    """A memory snapshot is automatic context only for the active human turn.

    Old/legacy snapshots without a matching turn identity are durable/retrievable state, not
    working context.  ``None`` therefore denies rather than guessing a lifecycle.
    """

    if not is_memory_snapshot(message):
        return True
    if current_turn_ref is None:
        return False
    md = getattr(message, "metadata", None) or {}
    raw_turn_ref = md.get("turn_ref")
    if raw_turn_ref is None:
        return False
    try:
        return int(raw_turn_ref) == int(current_turn_ref)
    except (TypeError, ValueError):
        return False

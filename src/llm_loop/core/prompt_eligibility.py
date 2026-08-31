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
PROGRAM_FINAL_PROTOCOL_BOUNDARY = "[程序终止边界·无模型回答]"
TASK_ACTIVE_PROMPT_PREFIX = "[Task Active]"


PROMPT_DYNAMIC_PRODUCER_SLOTS = frozenset(
    {
        "program_recovery",
        "memory",
        "tip",
        "digest",
        "task_active",
    }
)


def render_task_active_identity(*, goal_id: str, task_id: str, title: str) -> str:
    """Render the only task state allowed to auto-project: one active execution identity.

    Full frontier/ready/blocked/completed state remains tool-only.  Empty identifiers deny
    rather than guessing.  Task titles are collapsed to one stable line so program-owned
    formatting cannot create additional prompt structure.
    """

    gid = str(goal_id or "").strip()
    tid = str(task_id or "").strip()
    if not gid or not tid:
        return ""
    clean_title = " ".join(str(title or "").split())[:80]
    return (
        f"{TASK_ACTIVE_PROMPT_PREFIX} goal={gid}; task={tid}; "
        f"status=in_progress; title={clean_title}"
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

# Legacy program-control frames predate lifecycle metadata.  New emitters MUST carry
# ``prompt_lifecycle=current_turn``; an unlabelled system frame with one of these exact
# prefixes is therefore historical control state and has no automatic prompt entitlement.
_LEGACY_EPHEMERAL_SYSTEM_PREFIXES = (
    "[停滞提醒]",
    "[搜索空结果提醒]",
    "[上下文溢出]",
    "[模型降级:",
    "[模型降级] 事实:",
)
_LEGACY_DECLARATION_REMINDER_PREFIX = (
    "[声明提醒] 你的最终回答中存在与工具回执不符的完成声明，请知悉"
    "（不影响本次输出，后续请如实声明）。"
)
# Pre-R8.10 auxiliary component failures were persisted as ordinary system messages.
# They remain durable history/audit facts but have no automatic prompt entitlement.
_LEGACY_PROGRAM_FAULT_PREFIX = "[程序异常]"


def current_turn_program_prompt_eligible(
    message: Any, *, current_turn_ref: int | None
) -> bool:
    """Gate persisted current-turn-only program controls by human-turn identity.

    A current-turn program frame may be replayed across tool/LLM rounds inside one human
    turn, but it loses prompt authority as soon as a new human turn starts.  Legacy
    unlabelled system control frames are deny-by-default because their controlling event
    has already happened and durable action/event state remains the source of truth.
    """

    md = getattr(message, "metadata", None) or {}
    # R8.15/E08: generic experience catalogs are durable/retrievable reference
    # state, not automatic working context. Deny every canonical experience_tip,
    # including one whose turn_ref still matches the current human turn. Explicit
    # search/tool results use different message kinds and are unaffected.
    if md.get("injection_kind") == "experience_tip":
        return False
    lifecycle = str(md.get("prompt_lifecycle") or "").strip().lower()
    if lifecycle == "current_turn":
        if current_turn_ref is None:
            return False
        raw_turn_ref = md.get("turn_ref")
        if raw_turn_ref is None:
            return False
        try:
            return int(raw_turn_ref) == int(current_turn_ref)
        except (TypeError, ValueError):
            return False
    if lifecycle:
        # Unknown persisted lifecycle is not an eligibility grant.
        return False

    role = str(getattr(message, "role", "") or "")
    content = str(getattr(message, "content", "") or "").lstrip()
    if role == "system" and any(content.startswith(p) for p in _LEGACY_EPHEMERAL_SYSTEM_PREFIXES):
        return False
    if role == "system" and content.startswith(_LEGACY_PROGRAM_FAULT_PREFIX):
        return False
    # Pre-R8.9 declaration reminders were program-generated as role=user without
    # metadata.  Match the exact historical sentence rather than the generic label so a
    # human discussing "[声明提醒]" remains ordinary user truth.
    if role in {"user", "system"} and content.startswith(_LEGACY_DECLARATION_REMINDER_PREFIX):
        return False
    return True

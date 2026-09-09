"""Exact human-ingress identification and legacy program-user recognition.

New provider requests never merge program text into a human ``role=user`` message.
The helpers here preserve exact user provenance for history/compact/trace logic and
recognize pre-agency-first program-user frames for cleanup/recovery only.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from llm_loop.core.injection_labels import InjectionLayer, detect_program_layer
from llm_loop.core.reference_injection import is_human_user_message

# ERC Recovery Manifest predates R1 labels but is program-origin by construction.
_LEGACY_PROGRAM_CONTEXT_PREFIXES = ("[上下文注入·",)


def _attr(message: Any, name: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(name, default)
    return getattr(message, name, default)


def _metadata(message: Any) -> dict[str, Any]:
    md = _attr(message, "metadata", {})
    return md if isinstance(md, dict) else {}


def _is_human_user(message: Any) -> bool:
    if _attr(message, "role", "") != "user":
        return False
    md = _metadata(message)
    if md.get("program_origin") is True:
        return False
    layer = str(md.get("origin_layer") or "")
    if layer and layer != InjectionLayer.USER_INSTRUCTION.value:
        return False
    content = str(_attr(message, "content", "") or "")
    return not is_program_user_content(content)


def is_program_user_content(content: str) -> bool:
    """Recognize provider-view user content that is program-origin.

    R1-labeled appendices are authoritative.  One legacy context family is kept
    here because it is generated directly at build time and predates R1 labels.
    """
    text = str(content or "").lstrip()
    if not text:
        return False
    if detect_program_layer(text) not in (None, InjectionLayer.USER_INSTRUCTION):
        return True
    return text.startswith(_LEGACY_PROGRAM_CONTEXT_PREFIXES)


def current_ingress_user_truth(session_messages: Iterable[Any], turn_ref: int | None) -> str | None:
    """Return exact current human text only for the initial LLM round of a run.

    Program frames may already follow the human message.  Once an assistant/tool
    result (or another genuine human message) exists after ``turn_ref`` we are in
    a tool-followup/next-turn state and must not move/replay the original user.
    """
    if turn_ref is None:
        return None
    messages = list(session_messages)
    if turn_ref < 0 or turn_ref >= len(messages):
        return None
    current = messages[turn_ref]
    if not is_human_user_message(current):
        return None
    for message in messages[turn_ref + 1 :]:
        role = str(_attr(message, "role", "") or "")
        if role in ("assistant", "tool"):
            return None
        if role == "user" and _is_human_user(message):
            return None
    return str(_attr(current, "content", "") or "")

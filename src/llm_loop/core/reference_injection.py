"""Mechanical human-ingress provenance helper.

Automatic reference/catalog prompt projection was retired. Historical memory,
experience and digest state is discoverable through explicit retrieval instead of
program-selected prompt injection. This module intentionally contains no task-switch,
relevance, summarization or dedup policy.
"""

from __future__ import annotations

from typing import Any


def _message_attr(message: Any, name: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(name, default)
    return getattr(message, name, default)


def _message_metadata(message: Any) -> dict[str, Any]:
    md = _message_attr(message, "metadata", {})
    return md if isinstance(md, dict) else {}


def is_human_user_message(message: Any) -> bool:
    """Return whether *message* is genuine human input.

    This is a provenance check only. It does not interpret intent, task continuity,
    relevance, approval, or what the model should do next.
    """
    if _message_attr(message, "role", "") != "user":
        return False
    md = _message_metadata(message)
    if md.get("program_origin") is True or md.get("ingress_delegated") is True:
        return False
    if md.get("origin_layer") and md.get("origin_layer") != "user_instruction":
        return False
    return bool(str(_message_attr(message, "content", "") or "").strip())

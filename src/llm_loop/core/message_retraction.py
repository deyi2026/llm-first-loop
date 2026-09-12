"""Mechanical message-retraction projection.

Retraction never erases the source event.  It only changes the provider-facing derived
view after an append-only ``message.retracted`` declaration has been observed.
"""

from __future__ import annotations

from typing import Any

RETRACTED_MARKER = "[RETRACTED]"
HUMAN_TURN_SOURCE_ID_KEY = "human_turn_source_id"


def is_retracted_metadata(metadata: Any) -> bool:
    return isinstance(metadata, dict) and metadata.get("retracted") is True


def project_retracted_metadata(metadata: Any, payload: dict[str, Any], *, event_id: str = "") -> dict:
    """Return a provider-safe metadata projection without mutating the source metadata."""
    projected = dict(metadata) if isinstance(metadata, dict) else {}
    # Attachments and prompt-view cache markers can contain/describe the withdrawn source.
    # They are derived representation, not the append-only audit source, so invalidate them.
    projected.pop("attachments", None)
    projected.pop("cache_compacted_for", None)
    projected.pop("cache_compaction_scope", None)
    projected["retracted"] = True
    projected["retraction"] = {
        "source_id": str(payload.get("source_id") or ""),
        "actor": str(payload.get("actor") or "unknown"),
        "reason": str(payload.get("reason") or "source_recalled"),
        "retracted_at": str(payload.get("retracted_at") or ""),
        "event_id": event_id,
    }
    return projected

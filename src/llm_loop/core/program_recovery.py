"""Legacy program-recovery marker detection only.

Prompt-visible recovery was retired under the 2026-09-03 agency-first review. Current
1210 recovery is an in-process rebuild/retry with zero model-visible text and durable
EVENT_PROGRAM_RECOVERY audit. This module remains only to recognize/scrub pre-fix
durable messages; it must not expose a producer/render API.
"""

from __future__ import annotations

from llm_loop.core.injection_labels import InjectionLayer, detect_program_layer
from llm_loop.core.message import Message, MessageSource


def is_program_recovery_message(message: Message) -> bool:
    """Recognize historical recovery messages that must remain non-executable."""
    meta = message.metadata or {}
    if meta.get("injection_kind") == "program_recovery":
        return True
    # A real user may type the old marker literally; only non-human provenance may
    # be classified as legacy program recovery and removed from provider view.
    return (
        message.source is not MessageSource.USER
        and detect_program_layer(message.content) is InjectionLayer.PROGRAM_RECOVERY
    )

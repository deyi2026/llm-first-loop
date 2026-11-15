"""Copy-on-write secret redaction at the final model-visible request boundary.

Durable Session/Evidence remain unchanged. A redacted projection is *not* an
exact-byte Evidence hydration; it is solely the safe view sent to the model.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from llm_loop.cache_guard.guard import CacheGuardBlockedError, _check_privacy
from llm_loop.security_guard import redact_secrets_for_transport

_PROTECTED_FIELDS = frozenset(
    {
        "role", "name", "type", "id", "tool_call_id", "signature",
        "reasoning_details", "_provider_replay", "_active_run_ingress_ref",
        "evidence_ref", "blob_sha256", "range_sha256", "source_version_token",
    }
)
_DENIAL = "cache_guard 拦截: 出站隐私投影无法安全脱敏（未发送 Provider）"
logger = logging.getLogger(__name__)


def redact_provider_request(
    messages: list[dict], tools: list[dict], system_text: str,
) -> tuple[list[dict], list[dict], str, int]:
    """Return a safe wire view, never altering durable or caller-owned objects.

    Structural IDs and signed/native reasoning fields must not be rewritten.
    An unsafe/unknown shape is a hard denial, not an exception-based fail-open.
    """
    redactions = 0

    def project(value: Any, *, protected: bool = False) -> Any:
        nonlocal redactions
        if isinstance(value, str):
            safe, count = redact_secrets_for_transport(value)
            if count and protected:
                raise CacheGuardBlockedError(_DENIAL)
            redactions += count
            return safe
        if isinstance(value, dict):
            changes: dict[Any, Any] = {}
            for key, child in value.items():
                if isinstance(key, str) and redact_secrets_for_transport(key)[1]:
                    raise CacheGuardBlockedError(_DENIAL)
                replacement = project(
                    child, protected=protected or key in _PROTECTED_FIELDS
                )
                if replacement is not child:
                    changes[key] = replacement
            return {**value, **changes} if changes else value
        if isinstance(value, (list, tuple)):
            parts = [project(child, protected=protected) for child in value]
            if all(new is old for new, old in zip(parts, value, strict=True)):
                return value
            return tuple(parts) if isinstance(value, tuple) else parts
        return value

    def strings(value: Any):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key, child in value.items():
                if isinstance(key, str):
                    yield key
                yield from strings(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from strings(child)

    try:
        safe_messages = project(messages)
        safe_tools = project(tools)
        safe_system = project(system_text)
        # The existing guard checks content. This final invariant also covers
        # nested tool arguments, schemas and native provider fields.
        visible = "\n".join(strings((safe_messages, safe_tools)))
        if _check_privacy([{"role": "user", "content": visible}], safe_system):
            raise CacheGuardBlockedError(_DENIAL)
        return safe_messages, safe_tools, safe_system, redactions
    except CacheGuardBlockedError:
        raise
    except Exception:
        # Never expose original values or fail open on redaction errors.
        raise CacheGuardBlockedError(_DENIAL) from None


def project_guard_request(
    messages: list[dict], tools: list[dict], guard_context: Any,
) -> tuple[list[dict], list[dict], Any]:
    """Keep cache_guard's system snapshot aligned with the actual safe wire."""
    original_system = str(getattr(guard_context, "system_text", "") or "")
    safe_messages, safe_tools, safe_system, count = redact_provider_request(
        messages, tools, original_system
    )
    if safe_system != original_system:
        guard_context = replace(guard_context, system_text=safe_system)
    if count:
        logger.info("provider outbound privacy redactions=%d", count)
    return safe_messages, safe_tools, guard_context

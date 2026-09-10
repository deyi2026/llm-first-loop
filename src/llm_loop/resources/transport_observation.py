"""Provider transport resource observation for RG-3B shadow mode.

This module is deliberately observation-only. It normalizes a small allowlist of
mechanical response facts into RG contracts and stores them in a bounded,
process-local recorder. Raw headers, response bodies, prompts, credentials, and
semantic task data are never retained.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any

from llm_loop.resources.contracts import (
    FactProvenance,
    FactSource,
    ProviderErrorFacts,
    ProviderResponseFacts,
    ProviderUsageFacts,
    RateLimitMetric,
    RateLimitResetFacts,
)


class TransportObservationKind(StrEnum):
    RESPONSE = "response"
    USAGE = "usage"
    ERROR = "error"


@dataclass(frozen=True)
class ShadowTransportObservation:
    """One bounded shadow record containing only an already-normalized fact."""

    sequence: int
    kind: TransportObservationKind
    fact: ProviderResponseFacts | ProviderUsageFacts | ProviderErrorFacts


_DURATION_PART_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)", re.IGNORECASE)
_DURATION_MULTIPLIER = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def _header_map(headers: Mapping[str, Any]) -> dict[str, str]:
    """Copy only names/values transiently for parsing; caller never stores this mapping."""
    return {str(name).strip().lower(): str(value).strip() for name, value in headers.items()}


def _non_negative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _non_negative_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _duration_seconds(value: str) -> float | None:
    text = value.strip().lower()
    if not text:
        return None
    # A bare numeric x-ratelimit-reset value is ambiguous across providers: it may
    # be seconds-from-now or an epoch timestamp. RG-3B does not guess; vendor adapters
    # may normalize it only when the provider contract proves its meaning.
    parts = list(_DURATION_PART_RE.finditer(text))
    if not parts or "".join(match.group(0).lower() for match in parts) != text:
        return None
    return sum(float(match.group(1)) * _DURATION_MULTIPLIER[match.group(2).lower()] for match in parts)


def _retry_after_seconds(value: str | None, *, now: float) -> float | None:
    if value is None:
        return None
    seconds = _non_negative_float(value.strip())
    if seconds is not None:
        return seconds
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0.0, parsed.timestamp() - now)


def _rate_limit_facts(headers: Mapping[str, Any]) -> tuple[RateLimitResetFacts, ...]:
    """Parse only header names whose resource metric is explicit in the name.

    Ambiguous generic ``RateLimit-*`` or vendor-private headers are intentionally
    ignored here; RG-3D vendor adapters may normalize those once their semantics
    are independently proven.
    """
    normalized = _header_map(headers)
    out: list[RateLimitResetFacts] = []
    families = (
        ("requests", RateLimitMetric.REQUESTS),
        ("tokens", RateLimitMetric.TOTAL_TOKENS),
    )
    for suffix, metric in families:
        limit = _non_negative_int(normalized.get(f"x-ratelimit-limit-{suffix}"))
        remaining = _non_negative_int(normalized.get(f"x-ratelimit-remaining-{suffix}"))
        reset = normalized.get(f"x-ratelimit-reset-{suffix}")
        reset_after = _duration_seconds(reset) if reset is not None else None
        if all(value is None for value in (limit, remaining, reset_after)):
            continue
        try:
            out.append(
                RateLimitResetFacts(
                    metric=metric,
                    limit=limit,
                    remaining=remaining,
                    reset_after_seconds=reset_after,
                )
            )
        except ValueError:
            # Contradictory provider headers are not repaired or guessed in shadow mode.
            continue
    return tuple(out)


def _usage_int(mapping: Mapping[str, Any], key: str) -> int | None:
    if key not in mapping:
        return None
    return _non_negative_int(mapping.get(key))


def _openai_usage_fact(
    *, provider_id: str, model_id: str, usage: Mapping[str, Any], recorded_at: float
) -> ProviderUsageFacts | None:
    details = usage.get("prompt_tokens_details")
    completion_details = usage.get("completion_tokens_details")

    cached_input_tokens = _usage_int(usage, "cached_tokens")
    if cached_input_tokens is None and isinstance(details, Mapping):
        cached_input_tokens = _usage_int(details, "cached_tokens")
    if cached_input_tokens is None:
        cached_input_tokens = _usage_int(usage, "prompt_cache_hit_tokens")

    reasoning_tokens = None
    if isinstance(completion_details, Mapping):
        reasoning_tokens = _usage_int(completion_details, "reasoning_tokens")

    input_tokens = _usage_int(usage, "prompt_tokens")
    output_tokens = _usage_int(usage, "completion_tokens")
    total_tokens = _usage_int(usage, "total_tokens")
    if input_tokens is not None and cached_input_tokens is not None and cached_input_tokens > input_tokens:
        cached_input_tokens = None
    if all(
        value is None
        for value in (input_tokens, output_tokens, cached_input_tokens, reasoning_tokens, total_tokens)
    ):
        return None

    return ProviderUsageFacts(
        provider_id=provider_id,
        model_id=model_id,
        provenance=FactProvenance(
            source=FactSource.PROVIDER_RESPONSE,
            source_ref="transport:openai:usage",
            recorded_at=recorded_at,
        ),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        reasoning_tokens=reasoning_tokens,
        total_tokens=total_tokens,
    )


class ShadowTransportRecorder:
    """Thread-safe bounded recorder for RG-3B typed transport observations."""

    def __init__(self, *, max_entries: int = 2048, clock: Callable[[], float] = time.time) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be > 0")
        self._clock = clock
        self._entries: deque[ShadowTransportObservation] = deque(maxlen=max_entries)
        self._lock = threading.Lock()
        self._sequence = 0

    def _append(
        self,
        kind: TransportObservationKind,
        fact: ProviderResponseFacts | ProviderUsageFacts | ProviderErrorFacts,
    ) -> None:
        with self._lock:
            self._sequence += 1
            self._entries.append(
                ShadowTransportObservation(sequence=self._sequence, kind=kind, fact=fact)
            )

    def record_response(
        self,
        *,
        provider_id: str,
        model_id: str,
        status_code: int,
        headers: Mapping[str, Any],
    ) -> None:
        now = float(self._clock())
        normalized = _header_map(headers)
        self._append(
            TransportObservationKind.RESPONSE,
            ProviderResponseFacts(
                provider_id=provider_id,
                model_id=model_id,
                provenance=FactProvenance(
                    source=FactSource.PROVIDER_RESPONSE,
                    source_ref="transport:http:response",
                    recorded_at=now,
                ),
                status_code=status_code,
                retry_after_seconds=_retry_after_seconds(normalized.get("retry-after"), now=now),
                rate_limits=_rate_limit_facts(normalized),
            ),
        )

    def record_usage(
        self,
        *,
        provider_id: str,
        model_id: str,
        usage: Mapping[str, Any],
    ) -> None:
        fact = _openai_usage_fact(
            provider_id=provider_id,
            model_id=model_id,
            usage=usage,
            recorded_at=float(self._clock()),
        )
        if fact is not None:
            self._append(TransportObservationKind.USAGE, fact)

    def record_error(
        self,
        *,
        provider_id: str,
        model_id: str,
        status_code: int | None,
        provider_code: str | None,
        headers: Mapping[str, Any] | None = None,
    ) -> None:
        now = float(self._clock())
        normalized = _header_map(headers or {})
        self._append(
            TransportObservationKind.ERROR,
            ProviderErrorFacts(
                provider_id=provider_id,
                model_id=model_id,
                provenance=FactProvenance(
                    source=FactSource.PROVIDER_RESPONSE,
                    source_ref="transport:provider:error",
                    recorded_at=now,
                ),
                status_code=status_code,
                provider_code=provider_code,
                retry_after_seconds=_retry_after_seconds(normalized.get("retry-after"), now=now),
                rate_limits=_rate_limit_facts(normalized),
            ),
        )

    def snapshot(self) -> tuple[ShadowTransportObservation, ...]:
        with self._lock:
            return tuple(self._entries)

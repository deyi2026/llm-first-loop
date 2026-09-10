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
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
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
from llm_loop.resources.provider_settlement import (
    ProviderCallSettlementJournal,
    ProviderTransportAttempt,
    ProviderTransportOutcome,
    current_provider_call_site,
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
    call_id: str | None = None
    attempt_id: str | None = None


@dataclass
class _ActiveTransportCapture:
    attempt: ProviderTransportAttempt
    usage: dict[str, Any] = field(default_factory=dict)
    usage_observations: int = 0
    status_code: int | None = None
    provider_code: str | None = None
    retry_after_seconds: float | None = None
    rate_limits: tuple[RateLimitResetFacts, ...] = ()

    def observe(
        self,
        kind: TransportObservationKind,
        fact: ProviderResponseFacts | ProviderUsageFacts | ProviderErrorFacts,
    ) -> None:
        if kind is TransportObservationKind.USAGE and isinstance(fact, ProviderUsageFacts):
            for name in (
                "input_tokens",
                "output_tokens",
                "cached_input_tokens",
                "reasoning_tokens",
                "total_tokens",
                "provider_units",
                "provider_unit",
            ):
                value = getattr(fact, name)
                if value is not None:
                    self.usage[name] = value
            self.usage_observations += 1
            return
        if isinstance(fact, ProviderResponseFacts):
            self.status_code = fact.status_code
            if fact.retry_after_seconds is not None:
                self.retry_after_seconds = fact.retry_after_seconds
            if fact.rate_limits:
                self.rate_limits = fact.rate_limits
            return
        if isinstance(fact, ProviderErrorFacts):
            if fact.status_code is not None:
                self.status_code = fact.status_code
            if fact.provider_code is not None:
                self.provider_code = fact.provider_code
            if fact.retry_after_seconds is not None:
                self.retry_after_seconds = fact.retry_after_seconds
            if fact.rate_limits:
                self.rate_limits = fact.rate_limits


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
        self._settlement_journal: ProviderCallSettlementJournal | None = None
        self._active_transport: ContextVar[_ActiveTransportCapture | None] = ContextVar(
            f"lfl_rg3c_transport_{id(self)}", default=None
        )

    def set_settlement_journal(
        self, journal: ProviderCallSettlementJournal | None
    ) -> None:
        """Attach RG-3C durable shadow settlement; never an admission input."""

        self._settlement_journal = journal

    @property
    def settlement_journal(self) -> ProviderCallSettlementJournal | None:
        return self._settlement_journal

    @contextmanager
    def transport_attempt(
        self,
        *,
        provider_id: str,
        model_id: str,
        transport_retry_index: int = 0,
    ) -> Iterator[ProviderTransportAttempt | None]:
        """Correlate exactly one physical send with the current logical call."""

        journal = self._settlement_journal
        site = current_provider_call_site()
        if journal is None or site is None or not journal.enabled:
            yield None
            return
        try:
            # The actual client/provider is authoritative for the physical send.
            if site.provider_id != provider_id or site.model_id != model_id:
                yield None
                return
            attempt = journal.open_transport_attempt(
                site, transport_retry_index=transport_retry_index
            )
        except Exception:
            yield None
            return

        capture = _ActiveTransportCapture(attempt=attempt)
        token = self._active_transport.set(capture)
        outcome = ProviderTransportOutcome.SUCCESS
        error_type: str | None = None
        try:
            yield attempt
        except BaseException as exc:
            outcome = (
                ProviderTransportOutcome.INTERRUPTED
                if isinstance(exc, GeneratorExit)
                else ProviderTransportOutcome.ERROR
            )
            error_type = type(exc).__name__
            raise
        finally:
            self._active_transport.reset(token)
            # Settlement observation is fail-open and cannot affect transport behavior.
            with suppress(Exception):
                journal.settle_transport_attempt(
                    session_id=site.call.session_id,
                    attempt=attempt,
                    outcome=outcome,
                    usage=capture.usage,
                    usage_observations=capture.usage_observations,
                    status_code=capture.status_code,
                    provider_code=capture.provider_code,
                    retry_after_seconds=capture.retry_after_seconds,
                    rate_limits=capture.rate_limits,
                    error_type=error_type,
                )

    def _append(
        self,
        kind: TransportObservationKind,
        fact: ProviderResponseFacts | ProviderUsageFacts | ProviderErrorFacts,
    ) -> None:
        active = self._active_transport.get()
        if active is not None:
            active.observe(kind, fact)
        with self._lock:
            self._sequence += 1
            self._entries.append(
                ShadowTransportObservation(
                    sequence=self._sequence,
                    kind=kind,
                    fact=fact,
                    call_id=(active.attempt.call_id if active is not None else None),
                    attempt_id=(active.attempt.attempt_id if active is not None else None),
                )
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

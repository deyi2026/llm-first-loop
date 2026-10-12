"""Read-only physical Provider usage accounting, including isolated SubAgents.

Logical model responses omit hidden network attempts. The settled transport
journal is the authoritative physical usage source. This module never changes
prompt caching, bills currency, or guesses missing Provider usage.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any


def _token(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _timestamp(value: Any) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        return None
    return float(value)


def summarize_physical_provider_usage(events: Iterable[Any]) -> dict[str, Any] | None:
    """Aggregate one session's distinct settled physical attempt identities.

    Returns None when there are no physical receipts. Missing or ambiguous
    cache usage yields a nullable hit rate, NEVER a fabricated 0% miss.
    """
    by_id: dict[str, Mapping[str, Any]] = {}
    opened: dict[str, Mapping[str, Any]] = {}
    conflicts: set[str] = set()
    for event in events:
        event_type = getattr(event, "type", None)
        if event_type not in (
            "provider.transport.settled", "provider.transport.opened",
            "provider.transport.orphaned",
        ):
            continue
        payload = getattr(event, "payload", None)
        if not isinstance(payload, Mapping):
            continue
        attempt_id = payload.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id:
            continue
        if event_type in ("provider.transport.opened", "provider.transport.orphaned"):
            opened.setdefault(attempt_id, payload)
            continue
        if attempt_id in by_id:
            if payload != by_id[attempt_id]:
                conflicts.add(attempt_id)
        else:
            by_id[attempt_id] = payload
    if not by_id and not opened:
        return None

    def bucket() -> dict[str, Any]:
        return {
            "physical_attempts": 0,
            "opened_unsettled_attempts": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "known_input_attempts": 0,
            "known_output_attempts": 0,
            "known_cache_attempts": 0,
            "transport_duration_ms": 0.0,
            "known_duration_attempts": 0,
        }

    total = bucket()
    by_model: dict[str, dict[str, Any]] = {}
    calls: set[str] = set()
    for attempt_id, payload in by_id.items():
        provider = payload.get("provider_id")
        model = payload.get("model_id")
        provider_id = provider if isinstance(provider, str) and provider else "unknown"
        model_id = model if isinstance(model, str) and model else "unknown"
        model_key = f"{provider_id}/{model_id}"
        groups = (total, by_model.setdefault(model_key, bucket()))
        for g in groups:
            g["physical_attempts"] += 1
        call_id = payload.get("call_id")
        if isinstance(call_id, str) and call_id:
            calls.add(call_id)
        if attempt_id in conflicts:
            # Conflicting settlements are not safe token/accounting evidence.
            continue
        usage = payload.get("usage")
        if isinstance(usage, Mapping):
            input_tokens = _token(usage.get("input_tokens"))
            output_tokens = _token(usage.get("output_tokens"))
            cache_tokens = _token(usage.get("cached_input_tokens"))
            for g in groups:
                if input_tokens is not None:
                    g["input_tokens"] += input_tokens
                    g["known_input_attempts"] += 1
                if output_tokens is not None:
                    g["output_tokens"] += output_tokens
                    g["known_output_attempts"] += 1
                if (
                    input_tokens is not None and cache_tokens is not None
                    and cache_tokens <= input_tokens
                ):
                    g["cached_input_tokens"] += cache_tokens
                    g["known_cache_attempts"] += 1
        started, settled = (
            _timestamp(payload.get("started_at")),
            _timestamp(payload.get("settled_at")),
        )
        if started is not None and settled is not None and settled >= started:
            ms = (settled - started) * 1000
            for g in groups:
                g["transport_duration_ms"] += ms
                g["known_duration_attempts"] += 1
    for attempt_id, payload in opened.items():
        if attempt_id in by_id:
            continue
        # Opened-before-send is not proof of a completed physical charge.
        # Preserve the unfinished/unknown transport separately from settlement
        # totals, and disable a misleading "complete" hit-rate claim.
        provider = payload.get("provider_id")
        model = payload.get("model_id")
        provider_id = provider if isinstance(provider, str) and provider else "unknown"
        model_id = model if isinstance(model, str) and model else "unknown"
        for g in (total, by_model.setdefault(f"{provider_id}/{model_id}", bucket())):
            g["opened_unsettled_attempts"] += 1
        call_id = payload.get("call_id")
        if isinstance(call_id, str) and call_id:
            calls.add(call_id)

    def finalize(g: dict[str, Any]) -> dict[str, Any]:
        count = g["physical_attempts"]
        complete = (
            g["known_input_attempts"] == g["known_cache_attempts"] == count
            and g["opened_unsettled_attempts"] == 0
            and count > 0
        )
        return {
            **g,
            "transport_duration_ms": round(g["transport_duration_ms"], 1),
            "cache_usage_complete": complete,
            "cache_hit_rate": (
                round(g["cached_input_tokens"] / g["input_tokens"] * 100, 2)
                if complete and g["input_tokens"] > 0 else None
            ),
            "uncached_input_tokens": (
                g["input_tokens"] - g["cached_input_tokens"] if complete else None
            ),
        }

    return {
        **finalize(total),
        "logical_calls_observed": len(calls),
        "conflicting_attempts": len(conflicts),
        "by_model": {
            name: finalize(stats) for name, stats in sorted(by_model.items())
        },
        "usage_source": (
            "provider.transport.settled+opened"
            if total["opened_unsettled_attempts"]
            else "provider.transport.settled"
        ),
        "accounting_unit": "observed_tokens_not_invoice_currency",
    }

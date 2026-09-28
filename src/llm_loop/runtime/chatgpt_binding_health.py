"""Prompt-neutral runtime metrics and alerts for ChatGPT Web session bindings.

This module is intentionally observational.  It never rolls a segment, mutates
an LFL Session, deletes a binding, or changes provider routing.  The metrics are
derived from durable binding/history/transport-event facts plus the authoritative
cross-workspace Session identity probe.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

SCHEMA = "lfl.chatgpt_binding_health.v1"
RESTORE_FAILURE_CRITICAL_COUNT = 3
ROLLOVER_BURST_COUNT_1H = 4
ROLLOVER_BURST_RATIO_1H = 0.50
SEGMENT_PRESSURE_WARN_RATIO = 0.90
MISSING_IDENTITY_WARN_COUNT = 10
DELETED_BACKLOG_WARN_COUNT = 10


def _parse_ts(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _age_seconds(value: object, *, now: datetime) -> float | None:
    parsed = _parse_ts(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _presence_state(session_store: Any, session_id: str) -> str:
    probe = getattr(session_store, "global_presence_state", None)
    if callable(probe):
        return str(probe(session_id))
    exists = getattr(session_store, "exists", None)
    if callable(exists):
        return "present" if bool(exists(session_id)) else "missing"
    return "unknown"


def _alert(
    code: str,
    severity: str,
    message: str,
    **facts: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "code": code,
        "severity": severity,
        "message": message,
    }
    for key, value in facts.items():
        if value is not None:
            row[str(key)] = value
    return row


def inspect_chatgpt_binding_health(
    binding_store: Any,
    session_store: Any,
    *,
    segment_max_chars: int,
    min_gc_age_days: int = 30,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return bounded aggregate metrics plus conservative operational alerts."""

    observed = (now or datetime.now(UTC)).astimezone(UTC)
    one_hour_ago = observed - timedelta(hours=1)
    one_day_ago = observed - timedelta(days=1)
    alerts: list[dict[str, object]] = []
    try:
        bindings = list(binding_store.list_bindings())
    except Exception as exc:  # noqa: BLE001 - health must report, not hide, store failure
        return {
            "schema": SCHEMA,
            "status": "critical",
            "observed_at": observed.isoformat(timespec="seconds"),
            "metrics": {"bindings_total": None},
            "alerts": [
                _alert(
                    "binding_store_unreadable",
                    "critical",
                    "ChatGPT binding store could not be enumerated.",
                    error_type=type(exc).__name__,
                )
            ],
            "telemetry": {
                "coverage": "event_log_only",
                "event_count": 0,
                "first_event_at": None,
                "last_event_at": None,
            },
        }

    presence = Counter()
    rollover_reasons_all = Counter()
    rollover_reasons_24h = Counter()
    event_counts = Counter()
    event_counts_1h = Counter()
    event_counts_24h = Counter()
    per_session_1h: dict[str, Counter[str]] = {}
    closed_segments_total = 0
    total_requests = 0
    event_count = 0
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    pressure_sessions: list[str] = []
    max_pressure_ratio = 0.0
    gc_eligible_deleted = 0
    unreadable_session_telemetry = 0
    identity_probe_failures = 0

    for binding in bindings:
        total_requests += max(0, int(getattr(binding, "total_request_count", 0) or 0))
        session_id = str(getattr(binding, "lfl_session_id", "") or "")
        try:
            state = _presence_state(session_store, session_id)
        except Exception as exc:  # noqa: BLE001 - identity ambiguity must fail closed
            state = "unknown"
            identity_probe_failures += 1
            alerts.append(
                _alert(
                    "session_identity_probe_failed",
                    "warning",
                    "A binding's global Session identity could not be proven; retain it.",
                    session_id=session_id,
                    error_type=type(exc).__name__,
                )
            )
        presence[state] += 1

        if state == "deleted":
            age = _age_seconds(getattr(binding, "updated_at", ""), now=observed)
            if age is not None and age >= max(1, int(min_gc_age_days)) * 86400:
                gc_eligible_deleted += 1

        if segment_max_chars > 0:
            chars = max(0, int(getattr(binding, "segment_request_chars", 0) or 0))
            ratio = chars / segment_max_chars
            max_pressure_ratio = max(max_pressure_ratio, ratio)
            if ratio >= SEGMENT_PRESSURE_WARN_RATIO:
                pressure_sessions.append(session_id)

        try:
            history = binding_store.read_history(session_id, limit=500)
            events = binding_store.read_events(session_id, limit=2_000)
        except Exception as exc:  # noqa: BLE001 - one damaged bucket must be visible
            unreadable_session_telemetry += 1
            alerts.append(
                _alert(
                    "session_telemetry_unreadable",
                    "critical",
                    "A ChatGPT binding telemetry bucket is unreadable.",
                    session_id=session_id,
                    error_type=type(exc).__name__,
                )
            )
            continue

        closed_segments_total += len(history)
        for segment in history:
            rollover_reasons_all[str(segment.get("reason") or "unknown")] += 1

        session_recent = Counter()
        for event in events:
            event_count += 1
            name = str(event.get("event") or "unknown")
            event_counts[name] += 1
            ts = _parse_ts(event.get("ts"))
            if ts is None:
                continue
            if first_event_at is None or ts < first_event_at:
                first_event_at = ts
            if last_event_at is None or ts > last_event_at:
                last_event_at = ts
            if ts >= one_day_ago:
                event_counts_24h[name] += 1
                if name == "segment_rollover":
                    rollover_reasons_24h[str(event.get("reason") or "unknown")] += 1
            if ts >= one_hour_ago:
                event_counts_1h[name] += 1
                session_recent[name] += 1
        per_session_1h[session_id] = session_recent

    restore_successes_24h = event_counts_24h["restore_succeeded"]
    restore_failures_24h = event_counts_24h["restore_failed"]
    restore_attempts_24h = restore_successes_24h + restore_failures_24h
    restore_success_rate_24h: float | None = None
    if restore_attempts_24h:
        restore_success_rate_24h = restore_successes_24h / restore_attempts_24h

    max_rollovers_session_1h = 0
    rollover_burst_sessions: list[str] = []
    for session_id, counts in per_session_1h.items():
        rollovers = counts["segment_rollover"]
        exchanges = counts["exchange_committed"]
        max_rollovers_session_1h = max(max_rollovers_session_1h, rollovers)
        denominator = max(1, exchanges)
        if (
            rollovers >= ROLLOVER_BURST_COUNT_1H
            and (rollovers / denominator) >= ROLLOVER_BURST_RATIO_1H
        ):
            rollover_burst_sessions.append(session_id)

    if restore_failures_24h:
        severity = (
            "critical"
            if restore_failures_24h >= RESTORE_FAILURE_CRITICAL_COUNT
            else "warning"
        )
        alerts.append(
            _alert(
                "restore_failures_recent",
                severity,
                "ChatGPT conversation restore failures occurred in the last 24h.",
                count=restore_failures_24h,
            )
        )
    if rollover_burst_sessions:
        alerts.append(
            _alert(
                "rollover_burst",
                "warning",
                "One or more LFL Sessions are rolling ChatGPT segments unusually often.",
                count=len(rollover_burst_sessions),
                session_ids=sorted(rollover_burst_sessions),
            )
        )
    if pressure_sessions:
        alerts.append(
            _alert(
                "segment_pressure",
                "warning",
                "One or more active ChatGPT segments are already above 90% of the rollover char budget.",
                count=len(pressure_sessions),
                session_ids=sorted(pressure_sessions),
                max_ratio=round(max_pressure_ratio, 4),
            )
        )
    if presence["missing"] >= MISSING_IDENTITY_WARN_COUNT:
        alerts.append(
            _alert(
                "binding_identity_backlog",
                "warning",
                "Bindings without a durable deleted Session tombstone are accumulating.",
                count=presence["missing"],
            )
        )
    if gc_eligible_deleted >= DELETED_BACKLOG_WARN_COUNT:
        alerts.append(
            _alert(
                "deleted_binding_gc_backlog",
                "warning",
                "Aged deleted-session bindings eligible for explicit GC are accumulating.",
                count=gc_eligible_deleted,
            )
        )

    severities = {str(item.get("severity") or "") for item in alerts}
    status = "critical" if "critical" in severities else "warning" if "warning" in severities else "healthy"
    metrics: dict[str, object] = {
        "bindings_total": len(bindings),
        "sessions_present": presence["present"],
        "sessions_deleted": presence["deleted"],
        "sessions_reserved": presence["reserved"],
        "sessions_missing_no_tombstone": presence["missing"],
        "sessions_unknown": presence["unknown"],
        "identity_probe_failures": identity_probe_failures,
        "closed_segments_total": closed_segments_total,
        "total_requests_committed": total_requests,
        "exchanges_1h": event_counts_1h["exchange_committed"],
        "exchanges_24h": event_counts_24h["exchange_committed"],
        "rollovers_1h": event_counts_1h["segment_rollover"],
        "rollovers_24h": event_counts_24h["segment_rollover"],
        "rollovers_by_reason_all": dict(sorted(rollover_reasons_all.items())),
        "rollovers_by_reason_24h": dict(sorted(rollover_reasons_24h.items())),
        "max_rollovers_per_session_1h": max_rollovers_session_1h,
        "restore_attempts_24h": restore_attempts_24h,
        "restore_successes_24h": restore_successes_24h,
        "restore_failures_24h": restore_failures_24h,
        "restore_success_rate_24h": (
            round(restore_success_rate_24h, 4)
            if restore_success_rate_24h is not None
            else None
        ),
        "segment_char_budget": max(0, int(segment_max_chars)),
        "segment_pressure_max_ratio": round(max_pressure_ratio, 4),
        "segment_pressure_sessions": len(pressure_sessions),
        "gc_eligible_deleted_bindings": gc_eligible_deleted,
        "telemetry_unreadable_sessions": unreadable_session_telemetry,
    }
    return {
        "schema": SCHEMA,
        "status": status,
        "observed_at": observed.isoformat(timespec="seconds"),
        "metrics": metrics,
        "alerts": alerts,
        "telemetry": {
            "coverage": "event_log_only",
            "event_count": event_count,
            "event_types": dict(sorted(event_counts.items())),
            "first_event_at": (
                first_event_at.isoformat(timespec="seconds")
                if first_event_at is not None
                else None
            ),
            "last_event_at": (
                last_event_at.isoformat(timespec="seconds")
                if last_event_at is not None
                else None
            ),
        },
        "thresholds": {
            "restore_failure_critical_count_24h": RESTORE_FAILURE_CRITICAL_COUNT,
            "rollover_burst_count_1h": ROLLOVER_BURST_COUNT_1H,
            "rollover_burst_ratio_1h": ROLLOVER_BURST_RATIO_1H,
            "segment_pressure_warn_ratio": SEGMENT_PRESSURE_WARN_RATIO,
            "missing_identity_warn_count": MISSING_IDENTITY_WARN_COUNT,
            "deleted_backlog_warn_count": DELETED_BACKLOG_WARN_COUNT,
            "min_gc_age_days": max(1, int(min_gc_age_days)),
        },
    }

"""Durable provider-call settlement primitives for RG-3C shadow mode.

A ProviderCall is one logical model invocation owned by an execution surface. Each
physical transport send is a distinct ProviderTransportAttempt, including hidden
transport retries. This module records mechanical identity/accounting facts only;
it has no admission, routing, fallback, retry, or semantic authority.
"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from llm_loop.resources.contracts import ExecutionClass, ServicePriority


class ProviderCallPurpose(StrEnum):
    """Mechanical producer of a provider call, independent from service priority."""

    TASK = "task"
    SUBAGENT = "subagent"
    LEARNING = "learning"
    SUMMARIZER = "summarizer"
    MEMORY_EXTRACTOR = "memory_extractor"


class ProviderAttemptKind(StrEnum):
    """Why a logical call reached a provider again; no semantic quality meaning."""

    PRIMARY = "primary"
    ERR1210_RETRY = "err1210_retry"
    FALLBACK = "fallback"


class ProviderCallOutcome(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    INTERRUPTED = "interrupted"
    BLOCKED_BEFORE_TRANSPORT = "blocked_before_transport"


class ProviderTransportOutcome(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class ProviderCallIdentity:
    """Stable logical-call identity; the raw idempotency key is never persisted."""

    call_id: str
    session_id: str
    idempotency_key: str
    owner_ref: str
    execution_class: ExecutionClass
    service_priority: ServicePriority
    purpose: ProviderCallPurpose
    created_at: float


@dataclass(frozen=True)
class ProviderCallSite:
    """One caller-visible attempt site inside a logical ProviderCall."""

    call: ProviderCallIdentity
    attempt_kind: ProviderAttemptKind
    site_index: int
    provider_id: str
    model_id: str


@dataclass(frozen=True)
class ProviderTransportAttempt:
    """Identity of one actual transport send."""

    call_id: str
    attempt_id: str
    parent_attempt_id: str | None
    attempt_kind: ProviderAttemptKind
    site_index: int
    transport_retry_index: int
    provider_id: str
    model_id: str
    started_at: float


_CURRENT_PROVIDER_CALL_SITE: ContextVar[ProviderCallSite | None] = ContextVar(
    "lfl_provider_call_site", default=None
)


def current_provider_call_site() -> ProviderCallSite | None:
    """Return the request-scoped provider-call site, if RG-3C bound one."""

    return _CURRENT_PROVIDER_CALL_SITE.get()


@contextmanager
def bind_provider_call_site(site: ProviderCallSite | None) -> Iterator[None]:
    """Bind correlation only; it cannot change whether/how a provider is called."""

    if site is None:
        yield
        return
    token = _CURRENT_PROVIDER_CALL_SITE.set(site)
    try:
        yield
    finally:
        _CURRENT_PROVIDER_CALL_SITE.reset(token)


def _call_id(session_id: str, idempotency_key: str) -> str:
    raw = f"{session_id}\x00{idempotency_key}".encode()
    return "pcall:" + hashlib.sha256(raw).hexdigest()[:32]


def _idempotency_digest(idempotency_key: str) -> str:
    return hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]


def _require_text(name: str, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must be non-empty")
    return text


def _json_scalar(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value


_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "reasoning_tokens",
    "total_tokens",
)


class ProviderCallSettlementJournal:
    """EventStore-backed reducer for RG-3C durable/idempotent shadow accounting.

    The journal never blocks or retries provider work. Callers may use it to record
    facts, but no ResourceGovernor/fallback decision reads this state in RG-3C.
    """

    CALL_OPENED = "provider.call.opened"
    TRANSPORT_OPENED = "provider.transport.opened"
    TRANSPORT_SETTLED = "provider.transport.settled"
    CALL_SETTLED = "provider.call.settled"

    def __init__(self, event_store: Any, *, clock=time.time) -> None:
        self._event_store = event_store
        self._clock = clock
        self._lock = threading.RLock()
        self._loaded_sessions: set[str] = set()
        self._calls: dict[str, ProviderCallIdentity] = {}
        self._last_attempt_id: dict[str, str] = {}
        self._opened_attempts: dict[str, dict[str, Any]] = {}
        self._settled_attempts: dict[str, dict[str, Any]] = {}
        self._settled_calls: dict[str, dict[str, Any]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self._event_store is not None and getattr(self._event_store, "enabled", False))

    def _hydrate_session_locked(self, session_id: str) -> None:
        if session_id in self._loaded_sessions:
            return
        events = self._event_store.read(session_id) if self.enabled else []
        for event in events:
            payload = event.payload if isinstance(event.payload, dict) else {}
            event_type = str(event.type or "")
            if event_type == self.CALL_OPENED:
                call = self._call_from_payload(session_id, payload)
                if call is not None:
                    self._calls.setdefault(call.call_id, call)
            elif event_type == self.TRANSPORT_OPENED:
                attempt_id = str(payload.get("attempt_id") or "")
                call_id = str(payload.get("call_id") or "")
                if attempt_id and call_id:
                    self._opened_attempts.setdefault(attempt_id, dict(payload))
                    self._last_attempt_id[call_id] = attempt_id
            elif event_type == self.TRANSPORT_SETTLED:
                attempt_id = str(payload.get("attempt_id") or "")
                call_id = str(payload.get("call_id") or "")
                if attempt_id and call_id:
                    self._settled_attempts.setdefault(attempt_id, dict(payload))
                    self._last_attempt_id[call_id] = attempt_id
            elif event_type == self.CALL_SETTLED:
                call_id = str(payload.get("call_id") or "")
                if call_id:
                    self._settled_calls.setdefault(call_id, dict(payload))
        self._loaded_sessions.add(session_id)

    @staticmethod
    def _call_from_payload(
        session_id: str, payload: Mapping[str, Any]
    ) -> ProviderCallIdentity | None:
        try:
            return ProviderCallIdentity(
                call_id=_require_text("call_id", str(payload.get("call_id") or "")),
                session_id=session_id,
                idempotency_key="",
                owner_ref=_require_text("owner_ref", str(payload.get("owner_ref") or "")),
                execution_class=ExecutionClass(str(payload.get("execution_class") or "")),
                service_priority=ServicePriority(int(str(payload.get("service_priority") or ""))),
                purpose=ProviderCallPurpose(str(payload.get("purpose") or "")),
                created_at=float(payload.get("created_at") or 0.0),
            )
        except (TypeError, ValueError):
            return None

    def open_call(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        owner_ref: str,
        execution_class: ExecutionClass,
        service_priority: ServicePriority,
        purpose: ProviderCallPurpose,
    ) -> ProviderCallIdentity:
        """Return one stable logical call and append its open fact at most once locally."""

        session_id = _require_text("session_id", session_id)
        idempotency_key = _require_text("idempotency_key", idempotency_key)
        owner_ref = _require_text("owner_ref", owner_ref)
        call_id = _call_id(session_id, idempotency_key)
        with self._lock:
            self._hydrate_session_locked(session_id)
            existing = self._calls.get(call_id)
            if existing is not None:
                if (
                    existing.owner_ref != owner_ref
                    or existing.execution_class is not execution_class
                    or existing.service_priority is not service_priority
                    or existing.purpose is not purpose
                ):
                    raise ValueError("provider call idempotency identity conflict")
                return ProviderCallIdentity(
                    call_id=existing.call_id,
                    session_id=existing.session_id,
                    idempotency_key=idempotency_key,
                    owner_ref=existing.owner_ref,
                    execution_class=existing.execution_class,
                    service_priority=existing.service_priority,
                    purpose=existing.purpose,
                    created_at=existing.created_at,
                )

            call = ProviderCallIdentity(
                call_id=call_id,
                session_id=session_id,
                idempotency_key=idempotency_key,
                owner_ref=owner_ref,
                execution_class=execution_class,
                service_priority=service_priority,
                purpose=purpose,
                created_at=float(self._clock()),
            )
            payload = {
                "call_id": call.call_id,
                "idempotency_digest": _idempotency_digest(idempotency_key),
                "owner_ref": call.owner_ref,
                "execution_class": call.execution_class.value,
                "service_priority": int(call.service_priority),
                "purpose": call.purpose.value,
                "created_at": call.created_at,
            }
            written = self._event_store.append(session_id, self.CALL_OPENED, payload) if self.enabled else None
            if written is not None:
                self._calls[call_id] = call
            return call

    def open_transport_attempt(
        self,
        site: ProviderCallSite,
        *,
        transport_retry_index: int,
    ) -> ProviderTransportAttempt:
        """Create a fresh identity immediately before one physical send."""

        if transport_retry_index < 0:
            raise ValueError("transport_retry_index must be >= 0")
        if site.site_index < 0:
            raise ValueError("site_index must be >= 0")
        with self._lock:
            self._hydrate_session_locked(site.call.session_id)
            parent = self._last_attempt_id.get(site.call.call_id)
            attempt = ProviderTransportAttempt(
                call_id=site.call.call_id,
                attempt_id="pattempt:" + uuid.uuid4().hex,
                parent_attempt_id=parent,
                attempt_kind=site.attempt_kind,
                site_index=int(site.site_index),
                transport_retry_index=int(transport_retry_index),
                provider_id=_require_text("provider_id", site.provider_id),
                model_id=_require_text("model_id", site.model_id),
                started_at=float(self._clock()),
            )
            payload = self._attempt_identity_payload(attempt)
            written = (
                self._event_store.append(site.call.session_id, self.TRANSPORT_OPENED, payload)
                if self.enabled
                else None
            )
            if written is not None:
                self._opened_attempts[attempt.attempt_id] = payload
                self._last_attempt_id[attempt.call_id] = attempt.attempt_id
            return attempt

    @staticmethod
    def _attempt_identity_payload(attempt: ProviderTransportAttempt) -> dict[str, Any]:
        return {
            "call_id": attempt.call_id,
            "attempt_id": attempt.attempt_id,
            "parent_attempt_id": attempt.parent_attempt_id,
            "attempt_kind": attempt.attempt_kind.value,
            "site_index": attempt.site_index,
            "transport_retry_index": attempt.transport_retry_index,
            "provider_id": attempt.provider_id,
            "model_id": attempt.model_id,
            "started_at": attempt.started_at,
        }

    def settle_transport_attempt(
        self,
        *,
        session_id: str,
        attempt: ProviderTransportAttempt,
        outcome: ProviderTransportOutcome,
        usage: Mapping[str, Any] | None,
        usage_observations: int,
        status_code: int | None,
        provider_code: str | None,
        retry_after_seconds: float | None,
        rate_limits: tuple[Any, ...] | list[Any],
        error_type: str | None,
    ) -> dict[str, Any] | None:
        """Append one terminal transport settlement; duplicate attempt IDs are idempotent."""

        with self._lock:
            self._hydrate_session_locked(session_id)
            existing = self._settled_attempts.get(attempt.attempt_id)
            candidate = {
                **self._attempt_identity_payload(attempt),
                "outcome": outcome.value,
                "settled_at": float(self._clock()),
                "usage": self._normalize_usage_payload(usage or {}),
                "usage_observations": max(0, int(usage_observations)),
                "status_code": status_code,
                "provider_code": provider_code,
                "retry_after_seconds": retry_after_seconds,
                "rate_limits": self._normalize_rate_limits(rate_limits),
                "error_type": error_type,
            }
            if existing is not None:
                self._assert_same_attempt_settlement(existing, candidate)
                return dict(existing)
            written = self._event_store.append(session_id, self.TRANSPORT_SETTLED, candidate) if self.enabled else None
            if written is not None:
                self._settled_attempts[attempt.attempt_id] = candidate
                self._last_attempt_id[attempt.call_id] = attempt.attempt_id
                return dict(candidate)
            return None

    @staticmethod
    def _assert_same_attempt_settlement(
        existing: Mapping[str, Any], candidate: Mapping[str, Any]
    ) -> None:
        comparable = (
            "call_id",
            "attempt_id",
            "parent_attempt_id",
            "attempt_kind",
            "site_index",
            "transport_retry_index",
            "provider_id",
            "model_id",
            "outcome",
            "usage",
            "usage_observations",
            "status_code",
            "provider_code",
            "retry_after_seconds",
            "rate_limits",
            "error_type",
        )
        if any(existing.get(key) != candidate.get(key) for key in comparable):
            raise ValueError("conflicting provider transport settlement for attempt_id")

    @staticmethod
    def _normalize_usage_payload(usage: Mapping[str, Any]) -> dict[str, Any]:
        out = {field: _json_scalar(usage.get(field)) for field in _USAGE_FIELDS}
        out["provider_units"] = _json_scalar(usage.get("provider_units"))
        out["provider_unit"] = usage.get("provider_unit")
        return out

    @staticmethod
    def _normalize_rate_limits(rate_limits: tuple[Any, ...] | list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for fact in rate_limits:
            metric = getattr(fact, "metric", None)
            out.append(
                {
                    "metric": getattr(metric, "value", str(metric or "")),
                    "limit": getattr(fact, "limit", None),
                    "remaining": getattr(fact, "remaining", None),
                    "window_seconds": getattr(fact, "window_seconds", None),
                    "reset_at": getattr(fact, "reset_at", None),
                    "reset_after_seconds": getattr(fact, "reset_after_seconds", None),
                }
            )
        return out

    def settle_call(
        self,
        call: ProviderCallIdentity | None,
        outcome: ProviderCallOutcome,
    ) -> dict[str, Any] | None:
        """Record terminal logical-call outcome without changing caller control flow."""

        if call is None:
            return None
        with self._lock:
            self._hydrate_session_locked(call.session_id)
            existing = self._settled_calls.get(call.call_id)
            if existing is not None:
                if existing.get("outcome") != outcome.value:
                    raise ValueError("conflicting provider call settlement")
                return dict(existing)
            payload = {
                "call_id": call.call_id,
                "outcome": outcome.value,
                "settled_at": float(self._clock()),
            }
            written = self._event_store.append(call.session_id, self.CALL_SETTLED, payload) if self.enabled else None
            if written is not None:
                self._settled_calls[call.call_id] = payload
                return dict(payload)
            return None

    def snapshot_call(self, call: ProviderCallIdentity | str, *, session_id: str | None = None) -> dict[str, Any]:
        """Reduce durable attempt facts into completeness-aware call accounting."""

        if isinstance(call, ProviderCallIdentity):
            call_id = call.call_id
            sid = call.session_id
        else:
            call_id = str(call)
            sid = _require_text("session_id", str(session_id or ""))
        with self._lock:
            self._hydrate_session_locked(sid)
            opened = [row for row in self._opened_attempts.values() if row.get("call_id") == call_id]
            settled = [row for row in self._settled_attempts.values() if row.get("call_id") == call_id]
            # Dict insertion order mirrors EventStore seq order both live and after hydration.
            # Do not use random attempt UUIDs as a tie-break when provider sends share a clock tick.
            known_sum: dict[str, int] = {}
            completeness: dict[str, bool] = {}
            for field in _USAGE_FIELDS:
                values = [(row.get("usage") or {}).get(field) for row in settled]
                known_sum[field] = sum(int(value) for value in values if value is not None)
                completeness[field] = bool(settled) and all(value is not None for value in values)
            attempts_complete = bool(opened) and {row.get("attempt_id") for row in opened} <= {
                row.get("attempt_id") for row in settled
            }
            terminal = self._settled_calls.get(call_id)
            return {
                "call_id": call_id,
                "attempts_opened": len(opened),
                "attempts_settled": len(settled),
                "attempts_complete": attempts_complete,
                "known_usage_sum": known_sum,
                "usage_complete": completeness,
                "call_outcome": terminal.get("outcome") if terminal else None,
                "call_settled": terminal is not None,
                "attempts": [dict(row) for row in settled],
            }

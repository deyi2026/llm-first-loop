"""Minimal provider-agnostic Resource Governor runtime for RG-1.

RG-1 owns only mechanical resource admission:

- explicit concurrency limits over ``ResourceKey`` scopes;
- atomic multi-key leases;
- non-preemptive service ordering for waiters;
- a narrow external foreground barrier used while Task runs have not yet moved
  to ResourceGovernor leases.

It does not inspect prompts, task content, model quality, Method applicability,
completion, rate/cost/trust policy, or provider cancellation.  Unknown capacity
is never interpreted as unlimited.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from llm_loop.resources.contracts import (
    AdmissionDecision,
    AdmissionOutcome,
    AdmissionReason,
    AdmissionRequest,
    ResourceKey,
    ResourceLease,
    ServicePriority,
)


@dataclass(frozen=True)
class _PendingRequest:
    request: AdmissionRequest
    sequence: int


class ResourceGovernor:
    """Thread-safe process-local lease/concurrency governor.

    Concurrency is enforced only for keys with an explicit limit.  A missing
    limit is an unknown fact and therefore yields ``REQUIRED_FACT_UNKNOWN``.
    RG-1 leases are process-local; cross-process/provider capacity adapters are
    deliberately deferred to later phases.
    """

    def __init__(
        self,
        *,
        concurrency_limits: Mapping[ResourceKey, int] | None = None,
        foreground_probe: Callable[[], bool] | None = None,
        foreground_barrier_min_priority: ServicePriority = (
            ServicePriority.P2_BACKGROUND_DELIBERATION
        ),
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._limits: dict[ResourceKey, int] = {}
        self._in_flight: dict[ResourceKey, int] = {}
        self._leases: dict[str, ResourceLease] = {}
        self._leases_by_request: dict[str, str] = {}
        self._pending: dict[str, _PendingRequest] = {}
        self._sequence = 0
        self._foreground_probe = foreground_probe
        self._foreground_barrier_min_priority = foreground_barrier_min_priority
        self._clock = clock
        for key, limit in dict(concurrency_limits or {}).items():
            self.set_concurrency_limit(key, limit)

    # ---------- capacity facts ----------

    def set_concurrency_limit(self, key: ResourceKey, max_concurrency: int) -> None:
        """Install one explicit process-local concurrency fact and wake waiters."""
        if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
            raise TypeError("max_concurrency must be an int")
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be > 0")
        with self._condition:
            self._limits[key] = max_concurrency
            self._condition.notify_all()

    def concurrency_limit(self, key: ResourceKey) -> int | None:
        with self._condition:
            return self._limits.get(key)

    def in_flight(self, key: ResourceKey) -> int:
        with self._condition:
            return self._in_flight.get(key, 0)

    # ---------- observability ----------

    def active_leases(self) -> tuple[ResourceLease, ...]:
        with self._condition:
            return tuple(sorted(self._leases.values(), key=lambda x: (x.admitted_at, x.lease_id)))

    def pending_request_ids(self) -> tuple[str, ...]:
        with self._condition:
            rows = sorted(self._pending.values(), key=lambda item: item.sequence)
            return tuple(item.request.request_id for item in rows)

    # ---------- foreground service order ----------

    def _external_foreground_active(self) -> bool:
        probe = self._foreground_probe
        if probe is None:
            return False
        try:
            return bool(probe())
        except Exception:  # noqa: BLE001 - resource uncertainty yields to foreground
            return True

    def higher_priority_active(self, priority: ServicePriority) -> bool:
        """Whether known active work outranks ``priority``; no preemption is attempted."""
        with self._condition:
            if (
                priority >= self._foreground_barrier_min_priority
                and self._external_foreground_active()
            ):
                return True
            return any(lease.service_priority < priority for lease in self._leases.values())

    # ---------- admission ----------

    @staticmethod
    def _same_request(lease: ResourceLease, request: AdmissionRequest) -> bool:
        return (
            lease.request_id == request.request_id
            and lease.owner_ref == request.owner_ref
            and lease.execution_class is request.execution_class
            and lease.service_priority is request.service_priority
            and lease.provider_id == request.provider_id
            and lease.model_id == request.model_id
            and lease.resource_keys == request.resource_keys
        )

    def _existing_lease_locked(self, request: AdmissionRequest) -> ResourceLease | None:
        lease_id = self._leases_by_request.get(request.request_id)
        if lease_id is None:
            return None
        lease = self._leases.get(lease_id)
        if lease is None:
            self._leases_by_request.pop(request.request_id, None)
            return None
        if not self._same_request(lease, request):
            raise ValueError("request_id already owns a different active lease")
        return lease

    def _decision(
        self,
        request: AdmissionRequest,
        *,
        outcome: AdmissionOutcome,
        reason: AdmissionReason,
        lease: ResourceLease | None = None,
        blocked_keys: tuple[ResourceKey, ...] = (),
    ) -> AdmissionDecision:
        return AdmissionDecision(
            request_id=request.request_id,
            outcome=outcome,
            reason=reason,
            decided_at=self._clock(),
            lease=lease,
            blocked_keys=blocked_keys,
        )

    @staticmethod
    def _overlap(a: AdmissionRequest, b: AdmissionRequest) -> tuple[ResourceKey, ...]:
        b_keys = set(b.resource_keys)
        return tuple(key for key in a.resource_keys if key in b_keys)

    def _higher_priority_waiting_locked(
        self, pending: _PendingRequest
    ) -> tuple[ResourceKey, ...]:
        blockers: list[ResourceKey] = []
        current_order = (int(pending.request.service_priority), pending.sequence)
        for other in self._pending.values():
            if other.request.request_id == pending.request.request_id:
                continue
            overlap = self._overlap(pending.request, other.request)
            if not overlap:
                continue
            other_order = (int(other.request.service_priority), other.sequence)
            if other_order < current_order:
                for key in overlap:
                    if key not in blockers:
                        blockers.append(key)
        return tuple(blockers)

    def _attempt_locked(self, pending: _PendingRequest) -> AdmissionDecision:
        request = pending.request
        existing = self._existing_lease_locked(request)
        if existing is not None:
            return self._decision(
                request,
                outcome=AdmissionOutcome.ADMITTED,
                reason=AdmissionReason.AVAILABLE,
                lease=existing,
            )

        if (
            request.service_priority >= self._foreground_barrier_min_priority
            and self._external_foreground_active()
        ):
            return self._decision(
                request,
                outcome=AdmissionOutcome.DEFERRED,
                reason=AdmissionReason.HIGHER_PRIORITY_ACTIVE,
                blocked_keys=request.resource_keys,
            )

        unknown = tuple(key for key in request.resource_keys if key not in self._limits)
        if unknown:
            return self._decision(
                request,
                outcome=AdmissionOutcome.DEFERRED,
                reason=AdmissionReason.REQUIRED_FACT_UNKNOWN,
                blocked_keys=unknown,
            )

        waiting = self._higher_priority_waiting_locked(pending)
        if waiting:
            return self._decision(
                request,
                outcome=AdmissionOutcome.DEFERRED,
                reason=AdmissionReason.HIGHER_PRIORITY_WAITING,
                blocked_keys=waiting,
            )

        full = tuple(
            key
            for key in request.resource_keys
            if self._in_flight.get(key, 0) >= self._limits[key]
        )
        if full:
            return self._decision(
                request,
                outcome=AdmissionOutcome.DEFERRED,
                reason=AdmissionReason.CONCURRENCY_FULL,
                blocked_keys=full,
            )

        lease = ResourceLease(
            lease_id=f"lease-{uuid.uuid4().hex}",
            request_id=request.request_id,
            owner_ref=request.owner_ref,
            execution_class=request.execution_class,
            service_priority=request.service_priority,
            provider_id=request.provider_id,
            model_id=request.model_id,
            resource_keys=request.resource_keys,
            admitted_at=self._clock(),
        )
        for key in request.resource_keys:
            self._in_flight[key] = self._in_flight.get(key, 0) + 1
        self._leases[lease.lease_id] = lease
        self._leases_by_request[request.request_id] = lease.lease_id
        return self._decision(
            request,
            outcome=AdmissionOutcome.ADMITTED,
            reason=AdmissionReason.AVAILABLE,
            lease=lease,
        )

    def _enqueue_locked(self, request: AdmissionRequest) -> _PendingRequest:
        existing = self._pending.get(request.request_id)
        if existing is not None:
            if existing.request != request:
                raise ValueError("request_id is already pending with different request facts")
            return existing
        self._sequence += 1
        pending = _PendingRequest(request=request, sequence=self._sequence)
        self._pending[request.request_id] = pending
        self._condition.notify_all()
        return pending

    def try_acquire(self, request: AdmissionRequest) -> AdmissionDecision:
        """Attempt admission once; deferred callers retain no hidden queue state."""
        with self._condition:
            existing = self._existing_lease_locked(request)
            if existing is not None:
                return self._decision(
                    request,
                    outcome=AdmissionOutcome.ADMITTED,
                    reason=AdmissionReason.AVAILABLE,
                    lease=existing,
                )
            pending = self._enqueue_locked(request)
            try:
                return self._attempt_locked(pending)
            finally:
                self._pending.pop(request.request_id, None)
                self._condition.notify_all()

    def acquire(
        self,
        request: AdmissionRequest,
        *,
        timeout_s: float | None = None,
    ) -> AdmissionDecision:
        """Wait for admission in service-priority order over overlapping resources.

        ``timeout_s=None`` waits indefinitely.  This API is not used by the RG-1
        Learning bridge, which remains requeue/non-busy-wait via ``try_acquire``.
        """
        if timeout_s is not None and timeout_s < 0:
            raise ValueError("timeout_s must be >= 0")
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        with self._condition:
            existing = self._existing_lease_locked(request)
            if existing is not None:
                return self._decision(
                    request,
                    outcome=AdmissionOutcome.ADMITTED,
                    reason=AdmissionReason.AVAILABLE,
                    lease=existing,
                )
            pending = self._enqueue_locked(request)
            decision = self._attempt_locked(pending)
            while decision.outcome is not AdmissionOutcome.ADMITTED:
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._pending.pop(request.request_id, None)
                        self._condition.notify_all()
                        return decision
                else:
                    remaining = None
                poll = 0.05 if self._foreground_probe is not None else remaining
                wait_for = poll if remaining is None else min(remaining, poll or remaining)
                self._condition.wait(timeout=wait_for)
                decision = self._attempt_locked(pending)
            self._pending.pop(request.request_id, None)
            self._condition.notify_all()
            return decision

    # ---------- release ----------

    def release(self, lease: ResourceLease) -> bool:
        """Release an active lease exactly once and wake blocked waiters."""
        with self._condition:
            active = self._leases.pop(lease.lease_id, None)
            if active is None:
                return False
            self._leases_by_request.pop(active.request_id, None)
            for key in active.resource_keys:
                current = self._in_flight.get(key, 0)
                if current <= 1:
                    self._in_flight.pop(key, None)
                else:
                    self._in_flight[key] = current - 1
            self._condition.notify_all()
            return True

from __future__ import annotations

import threading
import time

from llm_loop.resources.contracts import (
    AdmissionOutcome,
    AdmissionReason,
    AdmissionRequest,
    ExecutionClass,
    ResourceKey,
    ResourceScopeKind,
    ServicePriority,
)
from llm_loop.resources.governor import ResourceGovernor


def _key(name: str = "runtime") -> ResourceKey:
    return ResourceKey("cognilocal", ResourceScopeKind.RUNTIME, name)


def _request(
    request_id: str,
    *,
    priority: ServicePriority = ServicePriority.P3_BACKGROUND_LEARNING,
    execution_class: ExecutionClass = ExecutionClass.BACKGROUND_LEARNING,
    keys: tuple[ResourceKey, ...] | None = None,
) -> AdmissionRequest:
    return AdmissionRequest(
        request_id=request_id,
        owner_ref=f"owner:{request_id}",
        execution_class=execution_class,
        service_priority=priority,
        provider_id="cognilocal",
        model_id="ornith",
        resource_keys=keys or (_key(),),
        submitted_at=time.time(),
    )


def _wait_until(predicate, timeout_s: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition did not become true")


def test_limit_one_defers_second_request_then_release_admits_it() -> None:
    key = _key()
    governor = ResourceGovernor()
    governor.set_concurrency_limit(key, 1)

    foreground = governor.try_acquire(
        _request(
            "foreground",
            priority=ServicePriority.P0_FOREGROUND,
            execution_class=ExecutionClass.FOREGROUND_TASK,
        )
    )
    assert foreground.outcome is AdmissionOutcome.ADMITTED
    assert foreground.lease is not None
    assert governor.in_flight(key) == 1

    learning = governor.try_acquire(_request("learning"))
    assert learning.outcome is AdmissionOutcome.DEFERRED
    assert learning.reason is AdmissionReason.CONCURRENCY_FULL
    assert learning.lease is None
    assert learning.blocked_keys == (key,)

    assert governor.release(foreground.lease) is True
    assert governor.in_flight(key) == 0
    learning_after = governor.try_acquire(_request("learning-after"))
    assert learning_after.outcome is AdmissionOutcome.ADMITTED
    assert learning_after.lease is not None
    assert governor.release(learning_after.lease) is True


def test_unknown_concurrency_is_not_treated_as_unlimited() -> None:
    governor = ResourceGovernor()
    decision = governor.try_acquire(_request("unknown"))
    assert decision.outcome is AdmissionOutcome.DEFERRED
    assert decision.reason is AdmissionReason.REQUIRED_FACT_UNKNOWN
    assert decision.blocked_keys == (_key(),)
    assert governor.active_leases() == ()


def test_multi_key_admission_is_atomic_when_one_scope_is_full() -> None:
    key_a = _key("runtime-a")
    key_b = _key("runtime-b")
    governor = ResourceGovernor()
    governor.set_concurrency_limit(key_a, 1)
    governor.set_concurrency_limit(key_b, 1)

    blocker = governor.try_acquire(_request("blocker", keys=(key_a,)))
    assert blocker.lease is not None

    candidate = governor.try_acquire(_request("multi", keys=(key_a, key_b)))
    assert candidate.outcome is AdmissionOutcome.DEFERRED
    assert candidate.reason is AdmissionReason.CONCURRENCY_FULL
    assert candidate.blocked_keys == (key_a,)
    assert governor.in_flight(key_a) == 1
    assert governor.in_flight(key_b) == 0
    assert governor.release(blocker.lease) is True


def test_external_foreground_barrier_blocks_background_but_not_active_task_auxiliary() -> None:
    busy = {"value": True}
    key = _key()
    governor = ResourceGovernor(foreground_probe=lambda: busy["value"])
    governor.set_concurrency_limit(key, 1)

    background = governor.try_acquire(_request("background"))
    assert background.outcome is AdmissionOutcome.DEFERRED
    assert background.reason is AdmissionReason.HIGHER_PRIORITY_ACTIVE
    assert background.lease is None

    auxiliary = governor.try_acquire(
        _request(
            "auxiliary",
            priority=ServicePriority.P1_ACTIVE_TASK_AUXILIARY,
            execution_class=ExecutionClass.SUBAGENT,
        )
    )
    assert auxiliary.outcome is AdmissionOutcome.ADMITTED
    assert auxiliary.lease is not None
    assert governor.release(auxiliary.lease) is True


def test_higher_priority_waiter_overtakes_earlier_background_waiter() -> None:
    key = _key()
    governor = ResourceGovernor()
    governor.set_concurrency_limit(key, 1)
    blocker = governor.try_acquire(
        _request(
            "blocker",
            priority=ServicePriority.P1_ACTIVE_TASK_AUXILIARY,
            execution_class=ExecutionClass.SUBAGENT,
        )
    )
    assert blocker.lease is not None

    order: list[str] = []
    decisions = {}

    def wait_for(request: AdmissionRequest) -> None:
        decision = governor.acquire(request, timeout_s=2.0)
        decisions[request.request_id] = decision
        if decision.lease is not None:
            order.append(request.request_id)
            time.sleep(0.02)
            governor.release(decision.lease)

    low = threading.Thread(target=wait_for, args=(_request("low"),))
    low.start()
    _wait_until(lambda: governor.pending_request_ids() == ("low",))

    high_request = _request(
        "high",
        priority=ServicePriority.P0_FOREGROUND,
        execution_class=ExecutionClass.FOREGROUND_TASK,
    )
    high = threading.Thread(target=wait_for, args=(high_request,))
    high.start()
    _wait_until(lambda: set(governor.pending_request_ids()) == {"low", "high"})

    governor.release(blocker.lease)
    high.join(timeout=2.0)
    low.join(timeout=2.0)
    assert not high.is_alive() and not low.is_alive()
    assert order == ["high", "low"]
    assert decisions["high"].outcome is AdmissionOutcome.ADMITTED
    assert decisions["low"].outcome is AdmissionOutcome.ADMITTED


def test_active_background_lease_is_not_fake_preempted_when_foreground_appears() -> None:
    busy = {"value": False}
    key = _key()
    governor = ResourceGovernor(foreground_probe=lambda: busy["value"])
    governor.set_concurrency_limit(key, 1)

    decision = governor.try_acquire(_request("learning"))
    assert decision.lease is not None
    busy["value"] = True

    assert governor.higher_priority_active(ServicePriority.P3_BACKGROUND_LEARNING) is True
    assert governor.active_leases() == (decision.lease,)
    assert governor.in_flight(key) == 1
    assert governor.release(decision.lease) is True
    assert governor.release(decision.lease) is False

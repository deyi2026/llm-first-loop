"""M5-C read-only Provider/Tool side-effect evidence join.

This is an audit projection, NOT a settlement authority. A local Provider
receipt never proves remote acceptance or billing; a matching Tool SHA never
proves causal ownership. No Run can be replayed or resumed by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from llm_loop.core.durable_run_recovery import HOLD, _strict_snapshot
from llm_loop.event_log.model import Event

if TYPE_CHECKING:
    from llm_loop.event_log.store import EventStore
    from llm_loop.resources.task_budget_store import TaskBudgetStore


@dataclass(frozen=True)
class RunEffectAudit:
    decision: str
    reason: str
    session_id: str
    run_generation: str
    authorization_id: str
    budget_id: str
    event_snapshot_sha256: str = ""
    budget_revision: int | None = None
    budget_phase: str = ""
    provider_calls_opened: int = 0
    provider_transport_opened: int = 0
    provider_transport_settled: int = 0
    provider_transport_unsettled: int = 0
    provider_transport_unattributed: int = 0
    provider_budget_unsettled: int = 0
    provider_budget_settled_unjoined: int = 0
    provider_local_receipts_joined: int = 0
    tool_budget_invocations: int = 0
    tool_receipts_committed: int = 0
    tool_effect_prepared: int = 0
    tool_effect_observed: int = 0
    tool_effect_pairs_observed: int = 0
    tool_effect_unresolved: int = 0
    remote_provider_settlement_proven: bool = False
    tool_effect_causation_proven: bool = False
    auto_resume_allowed: bool = False
    old_run_replay_allowed: bool = False


def _provider_counts(
    events: list[Event], reservations: dict[str, Any], generation: str
) -> dict[str, int]:
    calls = [
        e for e in events if e.type == "provider.call.opened"
        and e.payload.get("origin_run_generation") == generation
    ]
    call_ids = [e.payload.get("call_id") for e in calls]
    opened_all = [e for e in events if e.type == "provider.transport.opened"]
    settled_all = [e for e in events if e.type == "provider.transport.settled"]
    opened = [
        e for e in opened_all if call_ids.count(e.payload.get("call_id")) == 1
    ]
    settled = [
        e for e in settled_all if call_ids.count(e.payload.get("call_id")) == 1
    ]
    settled_by_id = {e.event_id: e for e in settled}
    attempts = [e.payload.get("attempt_id") for e in opened]
    physical = [
        r for r in reservations.values()
        if r.get("kind") == "physical_attempts"
    ]
    joined_ids: set[str] = set()
    joined = 0
    for reservation in physical:
        if reservation.get("phase") != "settled":
            continue
        ref = str(reservation.get("receipt_ref") or "")
        parts = ref.split(":")
        if len(parts) != 3 or parts[0] != "webt1ev":
            continue
        event = settled_by_id.get(parts[1])
        if event is None or event.event_id in joined_ids:
            continue
        call_id = event.payload.get("call_id")
        attempt_id = event.payload.get("attempt_id")
        matching = [
            o for o in opened if o.payload.get("attempt_id") == attempt_id
            and o.payload.get("call_id") == call_id
        ]
        if (
            call_ids.count(call_id) == 1
            and attempts.count(attempt_id) == 1
            and sum(e.payload.get("attempt_id") == attempt_id for e in settled) == 1
            and len(matching) == 1
            and event.payload.get("outcome") == "success"
        ):
            joined_ids.add(event.event_id)
            joined += 1
    settled_attempts = {
        (e.payload.get("call_id"), e.payload.get("attempt_id"))
        for e in settled
    }
    return {
        "provider_calls_opened": len(calls),
        "provider_transport_opened": len(opened),
        "provider_transport_settled": len(settled),
        "provider_transport_unsettled": sum(
            (e.payload.get("call_id"), e.payload.get("attempt_id"))
            not in settled_attempts for e in opened
        ),
        "provider_transport_unattributed": (
            len(opened_all) - len(opened) + len(settled_all) - len(settled)
        ),
        "provider_budget_unsettled": sum(
            r.get("phase") != "settled" for r in physical
        ),
        "provider_budget_settled_unjoined": sum(
            r.get("phase") == "settled" for r in physical
        ) - joined,
        "provider_local_receipts_joined": joined,
    }


def _tool_counts(
    events: list[Event], reservations: dict[str, Any], generation: str
) -> dict[str, int]:
    def selected(kind: str) -> list[Event]:
        return [
            e for e in events if e.type == "tool.execution." + kind
            and e.payload.get("origin_run_generation") == generation
        ]

    prepared = selected("effect_prepared")
    observed = selected("effect_observed")
    receipts = selected("receipt_committed")
    finished = selected("finished")
    pairs = 0
    for prep in prepared:
        execution_id = prep.payload.get("execution_id")
        matches = [
            e for e in observed if e.payload.get("execution_id") == execution_id
        ]
        committed = [
            e for e in receipts if e.payload.get("execution_id") == execution_id
        ]
        completed = [
            e for e in finished if e.payload.get("execution_id") == execution_id
        ]
        if (
            sum(e.payload.get("execution_id") == execution_id for e in prepared) == 1
            and len(matches) == 1
            and len(committed) == 1
            and len(completed) == 1
            and completed[0].payload.get("status") == "success"
            and completed[0].payload.get("result_state_sha256")
            == committed[0].payload.get("result_state_sha256")
            and matches[0].payload.get("matches_expected") is True
            and matches[0].payload.get("actual_after_sha256")
            == prep.payload.get("expected_after_sha256")
            and matches[0].payload.get("canonical_path")
            == prep.payload.get("canonical_path")
        ):
            pairs += 1
    return {
        "tool_budget_invocations": sum(
            r.get("kind") == "tool_invocations" for r in reservations.values()
        ),
        "tool_receipts_committed": len(receipts),
        "tool_effect_prepared": len(prepared),
        "tool_effect_observed": len(observed),
        "tool_effect_pairs_observed": pairs,
        "tool_effect_unresolved": len(prepared) - pairs
        + max(0, len(observed) - pairs),
    }


def inspect_run_effect_evidence(
    *,
    event_store: EventStore,
    budget_store: TaskBudgetStore,
    session_id: str,
    run_generation: str,
    authorization_id: str,
) -> RunEffectAudit:
    """Reconcile existing SoTs twice; never convert local evidence into replay."""
    budget_id = "webt1-" + authorization_id
    base = (session_id, run_generation, authorization_id, budget_id)

    def report(reason: str, **fields: Any) -> RunEffectAudit:
        return RunEffectAudit(HOLD, reason, *base, **fields)

    if not all(isinstance(value, str) and value for value in base):
        return report("missing_run_identity")
    try:
        first, sha_before = _strict_snapshot(event_store, session_id)
        before = budget_store.read(budget_id)
        second, sha_after = _strict_snapshot(event_store, session_id)
        after = budget_store.read(budget_id)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return report("evidence_missing_or_unverifiable")
    if first != second or sha_before != sha_after or before != after:
        return report("concurrent_evidence_drift")
    grant = after.get("grant") or {}
    member = (after.get("members") or {}).get(budget_id) or {}
    if (
        grant.get("budget_id") != budget_id
        or grant.get("session_id") != session_id
        or grant.get("profile") != "web-glm-t1-budgeted-write-v1"
        or member.get("run_generation") != run_generation
        or member.get("session_id") != session_id
    ):
        return report("budget_identity_mismatch")
    reservations = after.get("reservations") or {}
    provider = _provider_counts(second, reservations, run_generation)
    tool = _tool_counts(second, reservations, run_generation)
    if provider["provider_budget_unsettled"] or provider["provider_transport_unsettled"]:
        reason = "provider_unknown_remote_liability"
    elif provider["provider_budget_settled_unjoined"] or provider["provider_transport_unattributed"]:
        reason = "provider_local_receipt_unverifiable"
    elif tool["tool_effect_unresolved"]:
        reason = "tool_effect_outcome_unknown"
    elif tool["tool_effect_pairs_observed"]:
        reason = "tool_effect_causation_unproven"
    elif provider["provider_transport_opened"]:
        reason = "provider_remote_settlement_unverified"
    elif tool["tool_budget_invocations"]:
        reason = "tool_budget_receipt_not_causally_joined"
    else:
        reason = "no_external_activity_defer_to_m5a"
    return report(
        reason,
        event_snapshot_sha256=sha_after,
        budget_revision=after.get("revision"),
        budget_phase=str(after.get("phase") or ""),
        **provider,
        **tool,
    )

"""M5-C read-only Provider/Tool evidence joins; never grant replay authority."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from llm_loop.core.durable_effect_evidence import inspect_run_effect_evidence
from llm_loop.core.durable_run_recovery import HOLD
from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_contracts import (
    BudgetDimension,
    TaskBudgetGrant,
    TaskBudgetMember,
)
from llm_loop.resources.task_budget_dispatch import exact_workspace_scope
from llm_loop.resources.task_budget_store import TaskBudgetStore
from llm_loop.resources.task_budget_t1_web_profile import capabilities, limits

AUTH = "a" * 32
GEN = "b" * 32
SID = "m5c-effect-audit"
BID = "webt1-" + AUTH
CALL = "pcall:" + "c" * 32
ATTEMPT = "pattempt:" + "d" * 32
EXECUTION = "e" * 32


def _fixture(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    events = EventStore(tmp_path / "state" / "event_logs")
    budget = TaskBudgetStore(tmp_path / "state" / "task_budget_t1_web")
    grant = TaskBudgetGrant(
        budget_id=BID, issuer="operator", authority_source="admin-once-config-cas-v1",
        workspace_scope=exact_workspace_scope(str(workspace)),
        session_id=SID, human_turn_ref="synthetic-human-event",
        surface="web", profile="web-glm-t1-budgeted-write-v1",
        policy_version="t1-web-v1", deadline_epoch_s=time.time() + 600,
        limits=limits(), capabilities=capabilities(),
        provider_identity="glm", exact_model_ref="glm-5.3",
    )
    row = budget.issue_root(
        grant, root_run_generation=GEN, ingress_kind="web", reject_duplicate=True
    )
    row = budget.activate(BID, expected_revision=row["revision"])
    return events, budget, row


def _audit(events: EventStore, budget: TaskBudgetStore):
    return inspect_run_effect_evidence(
        event_store=events, budget_store=budget,
        session_id=SID, run_generation=GEN, authorization_id=AUTH,
    )


def _reserve(budget: TaskBudgetStore, row: dict, kind: BudgetDimension):
    rid = "dispatch-" + uuid.uuid4().hex
    member = TaskBudgetMember.from_dict(row["members"][BID])
    row = budget.reserve(
        BID, member=member, reservation_id=rid, kind=kind,
        expected_revision=row["revision"],
        tool_id="edit_file" if kind == BudgetDimension.TOOL_INVOCATIONS else "",
    )
    row = budget.mark_dispatched(BID, reservation_id=rid, expected_revision=row["revision"])
    return row, rid


def _provider(events: EventStore, *, settled: bool):
    assert events.append(SID, "provider.call.opened", {
        "call_id": CALL, "origin_run_generation": GEN,
    })
    assert events.append(SID, "provider.transport.opened", {
        "call_id": CALL, "attempt_id": ATTEMPT,
    })
    if settled:
        event = events.append(SID, "provider.transport.settled", {
            "call_id": CALL, "attempt_id": ATTEMPT, "outcome": "success",
        })
        assert event is not None
        return event
    return None


def _effect(events: EventStore, *, observed: bool, finished: bool):
    assert events.append(SID, "tool.execution.effect_prepared", {
        "execution_id": EXECUTION, "origin_run_generation": GEN,
        "canonical_path": "/tmp/m5c-synthetic-target",
        "expected_after_sha256": "f" * 64,
    })
    if observed:
        assert events.append(SID, "tool.execution.effect_observed", {
            "execution_id": EXECUTION, "origin_run_generation": GEN,
            "canonical_path": "/tmp/m5c-synthetic-target",
            "actual_after_sha256": "f" * 64, "matches_expected": True,
        })
    if finished:
        assert events.append(SID, "tool.execution.finished", {
            "execution_id": EXECUTION, "origin_run_generation": GEN,
            "status": "success", "result_state_sha256": "1" * 64,
        })
        assert events.append(SID, "tool.execution.receipt_committed", {
            "execution_id": EXECUTION, "origin_run_generation": GEN,
            "result_state_sha256": "1" * 64,
        })


def test_m5c_no_external_activity_remains_advisory_hold(tmp_path: Path) -> None:
    events, budget, _ = _fixture(tmp_path)
    assert events.append(SID, "session.created", {"session_id": SID})
    result = _audit(events, budget)
    assert result.decision == HOLD
    assert result.reason == "no_external_activity_defer_to_m5a"
    assert not result.auto_resume_allowed
    assert not result.old_run_replay_allowed


def test_m5c_dispatched_provider_without_settlement_is_unknown(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    row, _ = _reserve(budget, row, BudgetDimension.PHYSICAL_ATTEMPTS)
    _provider(events, settled=False)
    result = _audit(events, budget)
    assert result.reason == "provider_unknown_remote_liability"
    assert result.provider_calls_opened == 1
    assert result.provider_transport_opened == 1
    assert result.provider_transport_unsettled == 1
    assert result.provider_budget_unsettled == 1
    assert result.provider_local_receipts_joined == 0
    assert not result.remote_provider_settlement_proven


def test_m5c_local_provider_receipt_join_is_not_remote_ack(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    row, rid = _reserve(budget, row, BudgetDimension.PHYSICAL_ATTEMPTS)
    settled = _provider(events, settled=True)
    assert settled is not None
    row = budget.settle(
        BID, rid, expected_revision=row["revision"],
        receipt_ref=f"webt1ev:{settled.event_id}:abcd1234",
        outcome="success", usage_complete=True,
    )
    result = _audit(events, budget)
    assert result.provider_local_receipts_joined == 1
    assert result.provider_budget_unsettled == 0
    assert result.provider_transport_unsettled == 0
    assert result.reason == "provider_remote_settlement_unverified"
    assert not result.remote_provider_settlement_proven


def test_m5c_settled_reservation_without_exact_event_ref_is_hold(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    row, rid = _reserve(budget, row, BudgetDimension.PHYSICAL_ATTEMPTS)
    _provider(events, settled=True)
    budget.settle(
        BID, rid, expected_revision=row["revision"],
        receipt_ref="webt1ev:foreign-event:abcd1234",
        outcome="success", usage_complete=True,
    )
    result = _audit(events, budget)
    assert result.provider_local_receipts_joined == 0
    assert result.provider_budget_settled_unjoined == 1
    assert result.reason == "provider_local_receipt_unverifiable"


def test_m5c_prepared_tool_without_observed_is_unknown(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    row, _ = _reserve(budget, row, BudgetDimension.TOOL_INVOCATIONS)
    _effect(events, observed=False, finished=False)
    result = _audit(events, budget)
    assert result.reason == "tool_effect_outcome_unknown"
    assert result.tool_effect_prepared == 1
    assert result.tool_effect_unresolved == 1
    assert result.tool_budget_invocations == 1
    assert not result.tool_effect_causation_proven


def test_m5c_observed_matching_tool_sha_is_not_causal_proof(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    row, _ = _reserve(budget, row, BudgetDimension.TOOL_INVOCATIONS)
    _effect(events, observed=True, finished=True)
    result = _audit(events, budget)
    assert result.reason == "tool_effect_causation_unproven"
    assert result.tool_effect_pairs_observed == 1
    assert result.tool_receipts_committed == 1
    assert result.tool_budget_invocations == 1
    assert not result.tool_effect_causation_proven


def test_m5c_corrupt_jsonl_is_unverifiable_hold(tmp_path: Path) -> None:
    events, budget, _ = _fixture(tmp_path)
    assert events.append(SID, "session.created", {"session_id": SID})
    with open(events._path(SID), "ab") as stream:
        stream.write(b"corrupt-json\n")
    result = _audit(events, budget)
    assert result.reason == "evidence_missing_or_unverifiable"
    assert not result.auto_resume_allowed


def test_m5c_wrong_run_generation_is_hold(tmp_path: Path) -> None:
    events, budget, _ = _fixture(tmp_path)
    assert events.append(SID, "session.created", {"session_id": SID})
    result = inspect_run_effect_evidence(
        event_store=events, budget_store=budget, session_id=SID,
        run_generation="f" * 32, authorization_id=AUTH,
    )
    assert result.reason == "budget_identity_mismatch"


def test_m5c_no_side_effects_or_ledger_mutations(tmp_path: Path) -> None:
    events, budget, _ = _fixture(tmp_path)
    assert events.append(SID, "session.created", {"session_id": SID})
    event_path = Path(events._path(SID))
    ledger_path = next((tmp_path / "state" / "task_budget_t1_web").glob("*.json"))
    before = (event_path.read_bytes(), ledger_path.read_bytes())
    _audit(events, budget)
    assert before == (event_path.read_bytes(), ledger_path.read_bytes())


def test_m5c_budget_snapshot_drift_is_hold(tmp_path: Path, monkeypatch) -> None:
    events, budget, _ = _fixture(tmp_path)
    assert events.append(SID, "session.created", {"session_id": SID})
    real_read = budget.read
    counter = [0]

    def drift(bid):
        row = real_read(bid)
        counter[0] += 1
        if counter[0] == 2:
            row["revision"] += 1
        return row

    monkeypatch.setattr(budget, "read", drift)
    result = _audit(events, budget)
    assert result.reason == "concurrent_evidence_drift"


def test_m5c_foreign_run_transport_never_counts_as_current(tmp_path: Path) -> None:
    events, budget, _ = _fixture(tmp_path)
    assert events.append(SID, "provider.call.opened", {
        "call_id": "pcall:" + "f" * 32, "origin_run_generation": "0" * 32,
    })
    assert events.append(SID, "provider.transport.opened", {
        "call_id": "pcall:" + "f" * 32, "attempt_id": "pattempt:" + "0" * 32,
    })
    assert events.append(SID, "provider.transport.settled", {
        "call_id": "pcall:" + "f" * 32, "attempt_id": "pattempt:" + "0" * 32,
        "outcome": "success",
    })
    result = _audit(events, budget)
    assert result.provider_calls_opened == 0
    assert result.provider_transport_opened == 0
    assert result.provider_transport_settled == 0
    assert result.provider_transport_unattributed == 2
    assert result.reason == "provider_local_receipt_unverifiable"


def test_m5c_duplicate_settlement_cannot_count_as_joined(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    row, rid = _reserve(budget, row, BudgetDimension.PHYSICAL_ATTEMPTS)
    settled = _provider(events, settled=True)
    assert settled is not None
    assert events.append(SID, "provider.transport.settled", {
        "call_id": CALL, "attempt_id": ATTEMPT, "outcome": "success",
    })
    budget.settle(
        BID, rid, expected_revision=row["revision"],
        receipt_ref=f"webt1ev:{settled.event_id}:abcd1234",
        outcome="success", usage_complete=True,
    )
    result = _audit(events, budget)
    assert result.provider_local_receipts_joined == 0
    assert result.provider_budget_settled_unjoined == 1
    assert result.reason == "provider_local_receipt_unverifiable"


def test_m5c_mismatched_tool_receipt_sha_is_not_observed_pair(
    tmp_path: Path,
) -> None:
    events, budget, _ = _fixture(tmp_path)
    _effect(events, observed=True, finished=True)
    assert events.append(SID, "tool.execution.receipt_committed", {
        "execution_id": EXECUTION, "origin_run_generation": GEN,
        "result_state_sha256": "2" * 64,
    })
    result = _audit(events, budget)
    assert result.tool_effect_pairs_observed == 0
    assert result.tool_effect_unresolved >= 1
    assert result.reason == "tool_effect_outcome_unknown"


def test_m5c_tool_budget_without_wal_receipt_is_hold(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    row, rid = _reserve(budget, row, BudgetDimension.TOOL_INVOCATIONS)
    budget.settle(
        BID, rid, expected_revision=row["revision"],
        receipt_ref="dispatch-receipt-" + rid,
        outcome="success", usage_complete=True,
    )
    assert events.append(SID, "session.created", {"session_id": SID})
    result = _audit(events, budget)
    assert result.tool_budget_invocations == 1
    assert result.tool_receipts_committed == 0
    assert result.reason == "tool_budget_receipt_not_causally_joined"


def test_m5c_tool_effect_foreign_generation_is_not_current_proof(
    tmp_path: Path,
) -> None:
    events, budget, _ = _fixture(tmp_path)
    assert events.append(SID, "tool.execution.effect_prepared", {
        "execution_id": EXECUTION,
        "origin_run_generation": "0" * 32,
        "expected_after_sha256": "f" * 64,
    })
    result = _audit(events, budget)
    assert result.tool_effect_prepared == 0
    assert result.tool_effect_pairs_observed == 0
    assert not result.tool_effect_causation_proven
    assert result.decision == HOLD

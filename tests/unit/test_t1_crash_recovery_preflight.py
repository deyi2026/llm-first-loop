"""M4-D: advisory recovery preflight over REAL EventStore/TaskBudgetStore APIs.

All fixtures are synthetic and isolated. The separate M4-C real SIGKILL
receipt is checked manually; it is not mutated or replayed by these tests.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest

from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_contracts import (
    BudgetDimension,
    TaskBudgetGrant,
)
from llm_loop.resources.task_budget_dispatch import exact_workspace_scope
from llm_loop.resources.task_budget_store import TaskBudgetStore
from llm_loop.resources.task_budget_t1_web_profile import capabilities, limits
from scripts import t1_crash_recovery_preflight as preflight

_AUTH = "a" * 32
_GEN = "b" * 32
_SID = "source-session-uuid"
_NEW = "new-session-uuid"
_BUDGET = "webt1-" + _AUTH


def _fixture(
    tmp_path: Path, *, outstanding: bool = False,
    receipt_error: bool = False, provider_receipt_swap: bool = False,
    tool_receipt_swap: bool = False, omit_effect: bool = False,
) -> dict:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    docs = workspace / "docs"
    docs.mkdir()
    target = docs / "target.md"
    target.write_text("# Completed by first Run\n", encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    data = tmp_path / "state"
    event_store = EventStore(data / "event_logs", enabled=True)
    settled_event_ids = {}
    for index in (1, 2):
        call = f"pcall:{index}"
        attempt = f"pattempt:{index}"
        event_store.append(_SID, "provider.call.opened", {
            "call_id": call, "origin_run_generation": _GEN,
        })
        event_store.append(_SID, "provider.structure.validated", {"valid": True})
        event_store.append(_SID, "provider.transport.opened", {
            "call_id": call, "attempt_id": attempt,
            "provider_id": "glm", "model_id": "glm-5.3",
        })
        settled_event = event_store.append(_SID, "provider.transport.settled", {
            "call_id": call, "attempt_id": attempt,
            "provider_id": "glm", "model_id": "glm-5.3",
            "outcome": "success", "status_code": 200, "usage_observations": 1,
        })
        settled_event_ids[f"provider-{index}"] = settled_event.event_id
        event_store.append(_SID, "provider.call.settled", {
            "call_id": call, "outcome": "success",
        })
    if outstanding:
        event_store.append(_SID, "provider.call.opened", {
            "call_id": "pcall:3", "origin_run_generation": _GEN,
        })
        event_store.append(_SID, "provider.transport.opened", {
            "call_id": "pcall:3", "attempt_id": "pattempt:3",
            "provider_id": "glm", "model_id": "glm-5.3",
        })
    for tool, ident in (("read_file", "read"), ("edit_file", "edit")):
        base = {
            "execution_id": ident, "origin_run_generation": _GEN,
            "tool_name": tool,
        }
        event_store.append(_SID, "tool.execution.declared", base)
        event_store.append(_SID, "tool.execution.started", base)
        if tool == "edit_file":
            event_store.append(_SID, "tool.execution.effect_prepared", {
                **base, "workspace_root": str(workspace),
                "canonical_path": str(target), "expected_after_sha256": digest,
            })
            if not omit_effect:
                event_store.append(_SID, "tool.execution.effect_observed", {
                    **base, "workspace_root": str(workspace),
                    "canonical_path": str(target), "actual_after_sha256": digest,
                    "matches_expected": True,
                })
        event_store.append(_SID, "tool.execution.finished", {
            **base, "status": "success", "result_state_sha256": "f" * 64,
        })
        event_store.append(_SID, "tool.execution.receipt_committed", {
            **base, "result_state_sha256": "f" * 64,
            **({"outcome": "error"} if receipt_error and tool == "edit_file" else {}),
        })

    store = TaskBudgetStore(data / "task_budget_t1_web")
    grant = TaskBudgetGrant(
        budget_id=_BUDGET, issuer="operator",
        authority_source="admin-once-config-cas-v1",
        workspace_scope=exact_workspace_scope(str(workspace)),
        session_id=_SID, human_turn_ref="event-fixture-1", surface="web",
        profile="web-glm-t1-budgeted-write-v1",
        policy_version="t1-web-v1", deadline_epoch_s=time.time() + 600,
        limits=limits(), capabilities=capabilities(),
        provider_identity="glm", exact_model_ref="glm-5.3",
    )
    row = store.issue_root(
        grant, root_run_generation=_GEN, ingress_kind="web",
        reject_duplicate=True,
    )
    row = store.activate(_BUDGET, expected_revision=row["revision"])
    from llm_loop.resources.task_budget_contracts import TaskBudgetMember

    member = TaskBudgetMember.from_dict(store.read(_BUDGET)["members"][_BUDGET])

    def action(ident: str, kind: BudgetDimension, tool: str = "", *, settle: bool = True) -> None:
        nonlocal row
        row = store.reserve(
            _BUDGET, member=member, reservation_id=ident, kind=kind,
            tool_id=tool, expected_revision=row["revision"],
        )
        row = store.mark_dispatched(_BUDGET, ident, expected_revision=row["revision"])
        if settle:
            if kind == BudgetDimension.PHYSICAL_ATTEMPTS:
                event_id = settled_event_ids[ident]
                if provider_receipt_swap:
                    event_id = "00000000-0000-4000-8000-000000000000"
                receipt = f"webt1ev:{event_id}:0123456789abcdef"
            else:
                receipt = f"dispatch-receipt-{ident}"
                if tool_receipt_swap:
                    receipt = "dispatch-receipt-another-tool"
            row = store.settle(
                _BUDGET, ident, expected_revision=row["revision"],
                receipt_ref=receipt, outcome="success", usage_complete=True,
            )

    action("provider-1", BudgetDimension.PHYSICAL_ATTEMPTS)
    action("read-1", BudgetDimension.TOOL_INVOCATIONS, "read_file")
    action("provider-2", BudgetDimension.PHYSICAL_ATTEMPTS)
    action("edit-1", BudgetDimension.TOOL_INVOCATIONS, "edit_file")
    if outstanding:
        action("provider-3", BudgetDimension.PHYSICAL_ATTEMPTS, settle=False)
    row = store.request_stop(_BUDGET, expected_revision=row["revision"], reason="synthetic_crash")
    row = store.mark_settling(_BUDGET, expected_revision=row["revision"])
    row = store.close_uncertain(_BUDGET, expected_revision=row["revision"])
    assert row["phase"] == "closed_uncertain"

    args = [
        "--data-dir", str(data), "--workspace-root", str(workspace),
        "--source-session-id", _SID, "--source-authorization-id", _AUTH,
        "--source-run-generation", _GEN, "--target-path", "docs/target.md",
        "--expected-target-sha256", digest, "--new-session-id", _NEW,
        "--old-host-stopped-attested", "--json",
    ]
    return {
        "args": args, "target": target, "workspace": workspace,
        "data": data, "events": event_store, "store": store, "sha": digest,
    }


def _run(case: dict, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    target_before = case["target"].read_bytes()
    ledger_path = next((case["data"] / "task_budget_t1_web").glob("*.json"))
    ledger_before = ledger_path.read_bytes()
    event_path = case["data"] / "event_logs" / f"{_SID}.jsonl"
    events_before = event_path.read_bytes()
    rc = preflight.main(case["args"])
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 1
    assert case["target"].read_bytes() == target_before
    assert ledger_path.read_bytes() == ledger_before
    assert event_path.read_bytes() == events_before
    return rc, json.loads(output)


def test_positive_is_only_advisory_no_new_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    case = _fixture(tmp_path)
    rc, receipt = _run(case, capsys)
    assert rc == 0
    assert receipt["status"] == "PREFLIGHT_PASS_OPERATOR_ACTION_REQUIRED"
    assert receipt["eligible_for_new_authorization"] is True
    assert receipt["preflight_only"] is True
    assert receipt["physical_quiescence_verified"] is False
    assert receipt["reconciled"] == {
        "provider_attempts": 2, "tool_receipts": 2, "observed_edits": 1,
    }


def test_realistic_dispatched_provider_liability_holds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    case = _fixture(tmp_path, outstanding=True)
    rc, receipt = _run(case, capsys)
    assert rc == 2
    assert receipt["status"] == "HOLD"
    assert receipt["reason"] == "source_budget_has_unsettled_liability"


@pytest.mark.parametrize("mutation", [
    "missing_attestation", "reuse_session", "wrong_generation", "wrong_authorization",
    "target_sha_drift", "workspace_drift", "target_traversal", "symlink_target",
    "provider_open_unsettled", "provider_failed", "provider_duplicate",
    "tool_started_uncommitted", "edit_effect_missing", "edit_effect_mismatch",
    "run_already_ended", "source_event_generation_mismatch",
    "missing_budget", "budget_corrupt", "budget_identity_mismatch",
    "budget_event_count_mismatch", "duplicate_tool_receipt",
])
def test_negative_cases_hold_and_leave_evidence_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mutation: str,
) -> None:
    case = _fixture(tmp_path)
    args = case["args"]
    ev = case["events"]
    if mutation == "missing_attestation":
        args.remove("--old-host-stopped-attested")
    elif mutation == "reuse_session":
        args[args.index("--new-session-id") + 1] = _SID
    elif mutation == "wrong_generation":
        args[args.index("--source-run-generation") + 1] = "c" * 32
    elif mutation == "wrong_authorization":
        args[args.index("--source-authorization-id") + 1] = "d" * 32
    elif mutation == "target_sha_drift":
        args[args.index("--expected-target-sha256") + 1] = "e" * 64
    elif mutation == "workspace_drift":
        other = tmp_path / "different"
        other.mkdir()
        args[args.index("--workspace-root") + 1] = str(other)
    elif mutation == "target_traversal":
        args[args.index("--target-path") + 1] = "../workspace/docs/target.md"
    elif mutation == "symlink_target":
        target = case["target"]
        real = target.with_name("actual.md")
        target.rename(real)
        target.symlink_to(real)
    elif mutation == "provider_open_unsettled":
        ev.append(_SID, "provider.call.opened", {
            "call_id": "pcall:extra", "origin_run_generation": _GEN,
        })
        ev.append(_SID, "provider.transport.opened", {
            "call_id": "pcall:extra", "attempt_id": "pattempt:extra",
            "provider_id": "glm", "model_id": "glm-5.3",
        })
    elif mutation == "provider_failed":
        ev.append(_SID, "provider.transport.settled", {
            "call_id": "pcall:extra", "attempt_id": "pattempt:extra",
            "provider_id": "glm", "model_id": "glm-5.3",
            "outcome": "failure", "status_code": 500, "usage_observations": 1,
        })
    elif mutation == "provider_duplicate":
        ev.append(_SID, "provider.transport.opened", {
            "call_id": "pcall:1", "attempt_id": "pattempt:1",
            "provider_id": "glm", "model_id": "glm-5.3",
        })
    elif mutation == "tool_started_uncommitted":
        ev.append(_SID, "tool.execution.started", {
            "execution_id": "extra", "origin_run_generation": _GEN,
            "tool_name": "edit_file",
        })
    elif mutation == "edit_effect_missing":
        # A second effect violates the exact-one durable effect contract.
        ev.append(_SID, "tool.execution.effect_observed", {
            "execution_id": "edit", "origin_run_generation": _GEN,
            "tool_name": "edit_file", "matches_expected": True,
        })
    elif mutation == "edit_effect_mismatch":
        ev.append(_SID, "tool.execution.effect_observed", {
            "execution_id": "edit", "origin_run_generation": _GEN,
            "tool_name": "edit_file", "matches_expected": False,
        })
    elif mutation == "run_already_ended":
        ev.append(_SID, "run.end", {"reason": "completed"})
    elif mutation == "source_event_generation_mismatch":
        ev.append(_SID, "provider.call.opened", {
            "call_id": "pcall:other", "origin_run_generation": "c" * 32,
        })
    elif mutation in {"missing_budget", "budget_corrupt", "budget_identity_mismatch", "budget_event_count_mismatch"}:
        ledger_path = next((case["data"] / "task_budget_t1_web").glob("*.json"))
        if mutation == "missing_budget":
            ledger_path.unlink()
            # Missing authoritative source is itself the expected HOLD.
            rc = preflight.main(args)
            output = json.loads(capsys.readouterr().out)
            assert rc == 2 and output["status"] == "HOLD"
            assert output["eligible_for_new_authorization"] is False
            return
        if mutation == "budget_corrupt":
            ledger_path.write_text("not-json", encoding="utf-8")
        elif mutation == "budget_identity_mismatch":
            ledger = json.loads(ledger_path.read_text())
            ledger["grant"]["session_id"] = "other-session"
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        else:
            ledger = json.loads(ledger_path.read_text())
            # Drop a settled tool reservation, leaving EventStore evidence unmatched.
            ledger["reservations"].pop("edit-1")
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    elif mutation == "duplicate_tool_receipt":
        ev.append(_SID, "tool.execution.receipt_committed", {
            "execution_id": "edit", "origin_run_generation": _GEN,
            "tool_name": "edit_file",
        })
    rc, receipt = _run(case, capsys)
    assert rc == 2, (mutation, receipt)
    assert receipt["status"] == "HOLD"
    assert receipt["eligible_for_new_authorization"] is False
    assert isinstance(receipt["reason"], str) and receipt["reason"]


def test_default_does_not_create_operator_or_new_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    case = _fixture(tmp_path)
    _run(case, capsys)
    assert not list(tmp_path.rglob("*operator*.json"))
    assert not list(tmp_path.rglob("*new-session*"))


@pytest.mark.parametrize(("case_name", "reason"), [
    ("unknown_provider_fact", "unknown_evidence_event_kind"),
    ("unknown_tool_fact", "unknown_evidence_event_kind"),
    ("tool_receipt_error", "tool_receipt_outcome_mismatch"),
    ("provider_receipt_swap", "provider_budget_event_identity_mismatch"),
    ("tool_receipt_swap", "tool_budget_receipt_identity_mismatch"),
    ("provider_call_without_transport", "provider_call_without_transport"),
    ("edit_effect_absent", "source_edit_effect_count_mismatch"),
    ("provider_failure_settled", "provider_call_not_successfully_settled"),
    ("invalid_provider_structure", "provider_structure_invalid"),
])
def test_independent_reviewer_counterexamples_fail_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case_name: str, reason: str,
) -> None:
    case = _fixture(
        tmp_path,
        receipt_error=case_name == "tool_receipt_error",
        provider_receipt_swap=case_name == "provider_receipt_swap",
        tool_receipt_swap=case_name == "tool_receipt_swap",
        omit_effect=case_name == "edit_effect_absent",
    )
    ev = case["events"]
    if case_name == "unknown_provider_fact":
        ev.append(_SID, "provider.call.failed", {
            "call_id": "pcall:1", "origin_run_generation": _GEN,
            "reason": "stream_interrupted",
        })
    elif case_name == "unknown_tool_fact":
        ev.append(_SID, "tool.execution.aborted", {
            "execution_id": "edit", "origin_run_generation": _GEN,
        })
    elif case_name == "provider_call_without_transport":
        ev.append(_SID, "provider.call.opened", {
            "call_id": "pcall:orphan", "origin_run_generation": _GEN,
        })
        ev.append(_SID, "provider.call.settled", {
            "call_id": "pcall:orphan", "outcome": "success",
        })
    elif case_name == "provider_failure_settled":
        ev.append(_SID, "provider.call.opened", {
            "call_id": "pcall:failed", "origin_run_generation": _GEN,
        })
        ev.append(_SID, "provider.transport.opened", {
            "call_id": "pcall:failed", "attempt_id": "pattempt:failed",
            "provider_id": "glm", "model_id": "glm-5.3",
        })
        ev.append(_SID, "provider.transport.settled", {
            "call_id": "pcall:failed", "attempt_id": "pattempt:failed",
            "provider_id": "glm", "model_id": "glm-5.3",
            "outcome": "failure", "status_code": 500, "usage_observations": 1,
        })
        ev.append(_SID, "provider.call.settled", {
            "call_id": "pcall:failed", "outcome": "failure",
        })
    elif case_name == "invalid_provider_structure":
        ev.append(_SID, "provider.structure.validated", {"valid": False})
    rc, receipt = _run(case, capsys)
    assert rc == 2
    assert receipt["status"] == "HOLD"
    assert receipt["reason"] == reason


def test_event_log_race_during_preflight_holds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _fixture(tmp_path)
    original_read = EventStore.read
    calls = 0

    def racing_read(self, session_id):
        nonlocal calls
        result = original_read(self, session_id)
        calls += 1
        if calls == 1:
            self.append(session_id, "provider.call.failed", {
                "call_id": "pcall:1", "origin_run_generation": _GEN,
            })
        return result

    monkeypatch.setattr(EventStore, "read", racing_read)
    rc = preflight.main(case["args"])
    receipt = json.loads(capsys.readouterr().out)
    assert rc == 2 and receipt["reason"] == "source_events_changed_during_preflight"
    assert calls == 2


def test_budget_race_during_preflight_holds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _fixture(tmp_path)
    original_read = TaskBudgetStore.read
    calls = 0

    def racing_read(self, budget_id):
        nonlocal calls
        row = original_read(self, budget_id)
        calls += 1
        if calls == 3:
            return {**row, "revision": row["revision"] + 1}
        return row

    monkeypatch.setattr(TaskBudgetStore, "read", racing_read)
    rc = preflight.main(case["args"])
    receipt = json.loads(capsys.readouterr().out)
    assert rc == 2 and receipt["reason"] == "source_budget_changed_during_preflight"
    assert calls == 3


def test_target_race_during_preflight_holds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _fixture(tmp_path)
    original_read = Path.read_bytes

    def racing_read(self):
        data = original_read(self)
        if self == case["target"]:
            return data + b"concurrent mutation"
        return data

    monkeypatch.setattr(Path, "read_bytes", racing_read)
    rc = preflight.main(case["args"])
    receipt = json.loads(capsys.readouterr().out)
    assert rc == 2 and receipt["reason"] == "target_changed_during_preflight"


def test_missing_event_directory_does_not_get_recreated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    case = _fixture(tmp_path)
    event_dir = case["data"] / "event_logs"
    event_dir.rename(case["data"] / "event_logs_archived")
    rc = preflight.main(case["args"])
    receipt = json.loads(capsys.readouterr().out)
    assert rc == 2 and receipt["reason"] == "source_event_store_missing"
    assert not event_dir.exists()

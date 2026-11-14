"""Synthetic fail-closed tests; never mutate the real M4-C crash sample."""

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
    TaskBudgetMember,
)
from llm_loop.resources.task_budget_dispatch import exact_workspace_scope
from llm_loop.resources.task_budget_store import TaskBudgetStore
from llm_loop.resources.task_budget_t1_web_profile import capabilities, limits
from scripts import t1_provider_debt_disposition as audit

_SID = "11111111-1111-4111-8111-111111111111"
_AUTH = "a" * 32
_GEN = "b" * 32
_BID = "webt1-" + _AUTH


def _fixture(tmp_path: Path) -> dict:
    workspace = tmp_path / "workspace"
    target = workspace / "docs" / "target.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Real effect persisted\n", encoding="utf-8")
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    data = tmp_path / "state"
    events = EventStore(data / "event_logs", enabled=True)
    settled_ids = {}
    for n in (1, 2, 3):
        call = f"pcall:{n}"
        attempt = f"pattempt:{n}"
        events.append(_SID, "provider.call.opened", {
            "call_id": call, "origin_run_generation": _GEN,
        })
        events.append(_SID, "provider.transport.opened", {
            "call_id": call, "attempt_id": attempt,
            "provider_id": "glm", "model_id": "glm-5.3",
        })
        if n < 3:
            settled = events.append(_SID, "provider.transport.settled", {
                "call_id": call, "attempt_id": attempt,
                "provider_id": "glm", "model_id": "glm-5.3",
                "outcome": "success", "status_code": 200,
                "usage_observations": 1,
            })
            assert settled is not None
            settled_ids[n] = settled.event_id
            events.append(_SID, "provider.call.settled", {
                "call_id": call, "outcome": "success",
            })
    for name in ("read_file", "edit_file"):
        payload = {
            "tool_name": name, "execution_id": name,
            "origin_run_generation": _GEN,
        }
        events.append(_SID, "tool.execution.declared", payload)
        events.append(_SID, "tool.execution.started", payload)
        if name == "edit_file":
            events.append(_SID, "tool.execution.effect_prepared", {
                **payload, "canonical_path": str(target),
                "expected_after_sha256": sha,
            })
            events.append(_SID, "tool.execution.effect_observed", {
                **payload, "canonical_path": str(target),
                "actual_after_sha256": sha, "matches_expected": True,
            })
        events.append(_SID, "tool.execution.finished", {
            **payload, "status": "success", "result_state_sha256": "f" * 64,
        })
        events.append(_SID, "tool.execution.receipt_committed", {
            **payload, "result_state_sha256": "f" * 64,
        })
    store = TaskBudgetStore(data / "task_budget_t1_web")
    grant = TaskBudgetGrant(
        budget_id=_BID, issuer="operator",
        authority_source="admin-once-config-cas-v1",
        workspace_scope=exact_workspace_scope(str(workspace)),
        session_id=_SID, human_turn_ref="event-fixture-1",
        surface="web", profile="web-glm-t1-budgeted-write-v1",
        policy_version="t1-web-v1", deadline_epoch_s=time.time() + 600,
        limits=limits(), capabilities=capabilities(),
        provider_identity="glm", exact_model_ref="glm-5.3",
    )
    row = store.issue_root(
        grant, root_run_generation=_GEN, ingress_kind="web",
        reject_duplicate=True,
    )
    row = store.activate(_BID, expected_revision=row["revision"])
    member = TaskBudgetMember.from_dict(row["members"][_BID])
    for n in (1, 2):
        rid = f"provider-{n}"
        row = store.reserve(
            _BID, member=member, reservation_id=rid,
            kind=BudgetDimension.PHYSICAL_ATTEMPTS,
            expected_revision=row["revision"],
        )
        row = store.mark_dispatched(_BID, rid, expected_revision=row["revision"])
        if n < 3:
            row = store.settle(
                _BID, rid, expected_revision=row["revision"],
                receipt_ref=f"webt1ev:{settled_ids[n]}:0123456789abcdef",
                outcome="success", usage_complete=True,
            )
    for name in ("read_file", "edit_file"):
        rid = f"tool-{name}"
        row = store.reserve(
            _BID, member=member, reservation_id=rid,
            kind=BudgetDimension.TOOL_INVOCATIONS,
            tool_id=name, expected_revision=row["revision"],
        )
        row = store.mark_dispatched(_BID, rid, expected_revision=row["revision"])
        row = store.settle(
            _BID, rid, expected_revision=row["revision"],
            receipt_ref="dispatch-receipt-" + rid,
            outcome="success", usage_complete=True,
        )
    # A single-flight T1 root can have an unresolved Provider reservation
    # only AFTER all prior Tool/Provider actions have settled.
    row = store.reserve(
        _BID, member=member, reservation_id="provider-3",
        kind=BudgetDimension.PHYSICAL_ATTEMPTS,
        expected_revision=row["revision"],
    )
    row = store.mark_dispatched(
        _BID, "provider-3", expected_revision=row["revision"],
    )
    row = store.request_stop(_BID, expected_revision=row["revision"], reason="real_crash")
    row = store.mark_settling(_BID, expected_revision=row["revision"])
    row = store.close_uncertain(_BID, expected_revision=row["revision"])
    budget_file = next((data / "task_budget_t1_web").glob("budget-*.json"))
    event_file = data / "event_logs" / (_SID + ".jsonl")
    args = [
        "--data-dir", str(data), "--workspace-root", str(workspace),
        "--source-session-id", _SID, "--source-authorization-id", _AUTH,
        "--source-run-generation", _GEN, "--target-path", "docs/target.md",
        "--expected-events-sha256", hashlib.sha256(event_file.read_bytes()).hexdigest(),
        "--expected-budget-sha256", hashlib.sha256(budget_file.read_bytes()).hexdigest(),
        "--expected-target-sha256", sha, "--json",
    ]
    return {
        "args": args, "target": target, "event_file": event_file,
        "budget_file": budget_file, "events": events,
    }


def _inspect(f: dict) -> dict:
    return audit.inspect(audit._args(f["args"]))


def _replace_arg(f: dict, name: str, value: str) -> None:
    f["args"][f["args"].index(name) + 1] = value


def test_consistent_unknown_stays_quarantined(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    result = _inspect(f)
    assert result["audit_status"] == "PASS_EVIDENCE_CONSISTENT"
    assert result["disposition"] == "QUARANTINED_UNRESOLVED"
    assert result["provider_opened"] == 3
    assert result["provider_settled"] == 2
    assert result["unsettled_reservation_id"] == "provider-3"
    assert result["unsettled_attempt_id"] == "pattempt:3"
    assert result["provider_remote_request_id_present"] is False
    assert result["provider_billing_settled"] is False
    assert result["source_run_replay_allowed"] is False
    assert result["automatic_resume_allowed"] is False


def test_successful_audit_exit_code_is_still_hold(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = _fixture(tmp_path)
    assert audit.main(f["args"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["audit_status"] == "PASS_EVIDENCE_CONSISTENT"
    assert result["provider_billing_settled"] is False


@pytest.mark.parametrize("name", ["events", "budget", "target"])
def test_digest_drift_holds(tmp_path: Path, name: str) -> None:
    f = _fixture(tmp_path)
    path = {
        "events": f["event_file"],
        "budget": f["budget_file"],
        "target": f["target"],
    }[name]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(audit.EvidenceInvalidError, match="sha_mismatch"):
        _inspect(f)


def test_wrong_run_generation_holds(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    _replace_arg(f, "--source-run-generation", "c" * 32)
    with pytest.raises(audit.EvidenceInvalidError, match="budget_identity_or_phase_mismatch"):
        _inspect(f)


def test_forged_provider_settlement_event_holds(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    f["events"].append(_SID, "provider.transport.settled", {
        "call_id": "pcall:3", "attempt_id": "pattempt:3",
        "provider_id": "glm", "model_id": "glm-5.3",
        "outcome": "success",
    })
    _replace_arg(
        f, "--expected-events-sha256",
        hashlib.sha256(f["event_file"].read_bytes()).hexdigest(),
    )
    with pytest.raises(audit.EvidenceInvalidError, match="event_counts_inconsistent"):
        _inspect(f)


def test_budget_phase_falsification_holds(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    d = json.loads(f["budget_file"].read_text())
    d["phase"] = "active"
    f["budget_file"].write_text(json.dumps(d))
    _replace_arg(
        f, "--expected-budget-sha256",
        hashlib.sha256(f["budget_file"].read_bytes()).hexdigest(),
    )
    with pytest.raises(audit.EvidenceInvalidError, match="source_authority_unavailable_or_corrupt"):
        _inspect(f)


def test_target_symlink_holds(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    original = f["target"].read_bytes()
    f["target"].unlink()
    other = tmp_path / "elsewhere.md"
    other.write_bytes(original)
    f["target"].symlink_to(other)
    with pytest.raises(audit.EvidenceInvalidError, match="target_missing_or_symlink"):
        _inspect(f)


def test_audit_does_not_modify_any_source_bytes(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    paths = [f["target"], f["event_file"], f["budget_file"]]
    before = [(hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in paths]
    assert _inspect(f)["source_unchanged_during_audit"]
    after = [(hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in paths]
    assert before == after


def test_invalid_evidence_exit_code_is_hold(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = _fixture(tmp_path)
    f["target"].write_text("tampered")
    assert audit.main(f["args"]) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["audit_status"] == "HOLD_INVALID_EVIDENCE"
    assert result["source_run_replay_allowed"] is False


def test_unrecognized_provider_action_holds(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    f["events"].append(_SID, "provider.transport.orphaned", {
        "call_id": "pcall:3", "attempt_id": "pattempt:3",
    })
    _replace_arg(
        f, "--expected-events-sha256",
        hashlib.sha256(f["event_file"].read_bytes()).hexdigest(),
    )
    with pytest.raises(audit.EvidenceInvalidError, match="unrecognized_action_event"):
        _inspect(f)


def test_settlement_receipt_swap_holds(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    d = json.loads(f["budget_file"].read_text())
    d["reservations"]["provider-1"]["receipt_ref"] = (
        d["reservations"]["provider-2"]["receipt_ref"]
    )
    f["budget_file"].write_text(json.dumps(d))
    _replace_arg(
        f, "--expected-budget-sha256",
        hashlib.sha256(f["budget_file"].read_bytes()).hexdigest(),
    )
    with pytest.raises(audit.EvidenceInvalidError, match="settled_receipt_event_join_invalid"):
        _inspect(f)


def test_remote_id_text_alone_cannot_settle_unknown(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    lines = [json.loads(line) for line in f["event_file"].read_text().splitlines()]
    opened = [
        x for x in lines if x["type"] == "provider.transport.opened"
        and x["payload"]["attempt_id"] == "pattempt:3"
    ]
    assert len(opened) == 1
    opened[0]["payload"]["provider_request_id"] = "unverified-string"
    f["event_file"].write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines)
    )
    _replace_arg(
        f, "--expected-events-sha256",
        hashlib.sha256(f["event_file"].read_bytes()).hexdigest(),
    )
    result = _inspect(f)
    assert result["provider_remote_request_id_present"] is True
    assert result["disposition"] == "QUARANTINED_UNRESOLVED"
    assert result["provider_billing_settled"] is False
    assert result["automatic_resume_allowed"] is False


def test_unknown_reservation_not_refundable(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    d = json.loads(f["budget_file"].read_text())
    d["reservations"]["provider-3"]["phase"] = "aborted_before_dispatch"
    f["budget_file"].write_text(json.dumps(d))
    _replace_arg(
        f, "--expected-budget-sha256",
        hashlib.sha256(f["budget_file"].read_bytes()).hexdigest(),
    )
    with pytest.raises(audit.EvidenceInvalidError):
        _inspect(f)



def test_invalid_cli_arguments_return_machine_readable_hold(capsys: pytest.CaptureFixture[str]) -> None:
    assert audit.main(["--json"]) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["audit_status"] == "HOLD_INVALID_EVIDENCE"
    assert result["reason"] == "invalid_cli_arguments"


def test_noncanonical_relative_target_rejected(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    _replace_arg(f, "--target-path", "docs/./target.md")
    with pytest.raises(audit.EvidenceInvalidError, match="unsafe_target_path"):
        _inspect(f)

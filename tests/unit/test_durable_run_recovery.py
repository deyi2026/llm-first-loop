"""M5-A offline-only strict Run evidence and fail-closed recovery tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from llm_loop.core.durable_run_recovery import (
    COMPLETED,
    FENCED,
    HOLD,
    OPENED,
    REPLAN,
    SCHEMA,
    TERMINAL,
    assess_durable_run,
)
from llm_loop.event_log.store import (
    EventCommitUncertainError,
    EventDurabilityError,
    EventStore,
)
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
SID = "m5-offline-session"
BID = "webt1-" + AUTH


def _fixture(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data = tmp_path / "state"
    event_store = EventStore(data / "event_logs", enabled=True)
    budget_store = TaskBudgetStore(data / "task_budget_t1_web")
    grant = TaskBudgetGrant(
        budget_id=BID,
        issuer="operator",
        authority_source="admin-once-config-cas-v1",
        workspace_scope=exact_workspace_scope(str(workspace)),
        session_id=SID,
        human_turn_ref="synthetic-ingress-event",
        surface="web",
        profile="web-glm-t1-budgeted-write-v1",
        policy_version="t1-web-v1",
        deadline_epoch_s=time.time() + 600,
        limits=limits(),
        capabilities=capabilities(),
        provider_identity="glm",
        exact_model_ref="glm-5.3",
    )
    row = budget_store.issue_root(
        grant, root_run_generation=GEN, ingress_kind="web", reject_duplicate=True
    )
    row = budget_store.activate(BID, expected_revision=row["revision"])
    return event_store, budget_store, row


def _payload(revision: int, *, generation: str = GEN) -> dict:
    return {
        "schema": SCHEMA,
        "run_generation": generation,
        "authorization_id": AUTH,
        "budget_id": BID,
        "budget_revision": revision,
    }


def _open(events: EventStore, revision: int, *, generation: str = GEN) -> None:
    events.append_durable_run_fact(SID, OPENED, _payload(revision, generation=generation))
    events.append_durable_run_fact(SID, FENCED, _payload(revision, generation=generation))


def _stop(budget: TaskBudgetStore, row: dict) -> dict:
    return budget.request_stop(
        BID, expected_revision=row["revision"], reason="synthetic_offline_terminal"
    )


def _terminal(
    events: EventStore,
    revision: int,
    *,
    outcome: str = "aborted_before_dispatch",
    end_id: str = "",
    generation: str = GEN,
) -> None:
    events.append_durable_run_fact(
        SID, TERMINAL,
        {**_payload(revision, generation=generation),
         "outcome": outcome, "run_end_event_id": end_id},
    )


def _assess(events: EventStore, budget: TaskBudgetStore):
    return assess_durable_run(
        event_store=events, budget_store=budget,
        session_id=SID, run_generation=GEN, authorization_id=AUTH,
    )


def _complete_zero_effect_fixture(tmp_path: Path, *, outcome: str = "aborted_before_dispatch"):
    events, budget, row = _fixture(tmp_path)
    _open(events, row["revision"])
    end_id = ""
    if outcome == "completed":
        end = events.append(
            SID, "run.end", {"reason": "completed", "run_generation": GEN}
        )
        assert end is not None
        end_id = end.event_id
    row = _stop(budget, row)
    _terminal(events, row["revision"], outcome=outcome, end_id=end_id)
    return events, budget, row


def test_strict_zero_effect_abort_only_allows_new_authorization_replan(tmp_path: Path) -> None:
    events, budget, row = _complete_zero_effect_fixture(tmp_path)
    verdict = _assess(events, budget)
    assert verdict.decision == REPLAN
    assert verdict.budget_revision == row["revision"]
    assert len(verdict.event_snapshot_sha256) == 64
    assert not verdict.auto_resume_allowed
    assert not verdict.old_run_replay_allowed
    assert _assess(EventStore(events._dir), TaskBudgetStore(budget.directory)) == verdict


def test_strict_zero_effect_completed_requires_exact_run_end(tmp_path: Path) -> None:
    events, budget, _ = _complete_zero_effect_fixture(tmp_path, outcome="completed")
    verdict = _assess(events, budget)
    assert verdict.decision == COMPLETED
    assert not verdict.auto_resume_allowed


def test_legacy_run_end_is_not_m5_durability_proof(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    events.append(SID, "run.end", {"reason": "completed"})
    _stop(budget, row)
    assert _assess(events, budget).decision == HOLD


def test_missing_budget_is_hold(tmp_path: Path) -> None:
    events, _, row = _fixture(tmp_path)
    _open(events, row["revision"])
    missing = TaskBudgetStore(tmp_path / "missing")
    assert _assess(events, missing).decision == HOLD


def test_provider_attempt_even_settled_is_hold_without_exact_reconciliation(
    tmp_path: Path,
) -> None:
    events, budget, row = _fixture(tmp_path)
    _open(events, row["revision"])
    events.append(SID, "provider.call.opened", {
        "call_id": "pcall:1", "origin_run_generation": GEN,
    })
    events.append(SID, "provider.transport.opened", {
        "call_id": "pcall:1", "attempt_id": "pattempt:1",
    })
    events.append(SID, "provider.transport.settled", {
        "call_id": "pcall:1", "attempt_id": "pattempt:1", "outcome": "success",
    })
    row = _stop(budget, row)
    _terminal(events, row["revision"])
    verdict = _assess(events, budget)
    assert verdict.decision == HOLD
    assert verdict.reason == "external_or_unclassified_activity"


def test_matching_file_sha_and_effect_observed_do_not_prove_causation(
    tmp_path: Path,
) -> None:
    events, budget, row = _fixture(tmp_path)
    _open(events, row["revision"])
    target = tmp_path / "workspace" / "article.md"
    target.write_text("DONE\n", encoding="utf-8")
    events.append(SID, "tool.execution.effect_prepared", {
        "execution_id": "tool-1", "origin_run_generation": GEN,
        "expected_after_sha256": "c" * 64,
    })
    events.append(SID, "tool.execution.effect_observed", {
        "execution_id": "tool-1", "origin_run_generation": GEN,
        "matches_expected": True, "actual_after_sha256": "c" * 64,
    })
    row = _stop(budget, row)
    _terminal(events, row["revision"])
    assert _assess(events, budget).decision == HOLD
    assert target.read_text(encoding="utf-8") == "DONE\n"


def test_budget_reservation_history_is_hold_even_if_not_dispatched(
    tmp_path: Path,
) -> None:
    events, budget, row = _fixture(tmp_path)
    _open(events, row["revision"])
    member = TaskBudgetMember.from_dict(row["members"][BID])
    row = budget.reserve(
        BID, member=member, reservation_id="reserve-1",
        kind=BudgetDimension.PHYSICAL_ATTEMPTS,
        expected_revision=row["revision"],
    )
    row = _stop(budget, row)
    _terminal(events, row["revision"])
    assert _assess(events, budget).reason == "external_budget_liability_or_history"


def test_active_budget_cannot_replan(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    _open(events, row["revision"])
    _terminal(events, row["revision"])
    assert _assess(events, budget).reason == "budget_not_stopped"


def test_missing_terminal_is_hold(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    _open(events, row["revision"])
    _stop(budget, row)
    assert _assess(events, budget).reason == "durable_run_protocol_incomplete"


def test_duplicate_terminal_is_hold(tmp_path: Path) -> None:
    events, budget, row = _complete_zero_effect_fixture(tmp_path)
    _terminal(events, row["revision"])
    assert _assess(events, budget).decision == HOLD


def test_generation_mismatch_is_hold(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    _open(events, row["revision"], generation="c" * 32)
    row = _stop(budget, row)
    _terminal(events, row["revision"], generation="c" * 32)
    assert _assess(events, budget).reason == "durable_run_identity_mismatch"


def test_budget_revision_drift_is_hold(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    _open(events, row["revision"])
    row = _stop(budget, row)
    _terminal(events, row["revision"] - 1)
    assert _assess(events, budget).reason == "budget_revision_fence_mismatch"


def test_completed_without_matching_run_end_is_hold(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    _open(events, row["revision"])
    row = _stop(budget, row)
    _terminal(events, row["revision"], outcome="completed", end_id="fabricated")
    assert _assess(events, budget).reason == "completed_terminal_not_correlated"


def test_corrupt_event_row_is_hold(tmp_path: Path) -> None:
    events, budget, _ = _complete_zero_effect_fixture(tmp_path)
    with open(events._path(SID), "ab") as out:
        out.write(b'{"not-json":\n')
    assert _assess(events, budget).reason == "evidence_missing_or_unverifiable"


def test_partial_event_row_is_hold(tmp_path: Path) -> None:
    events, budget, _ = _complete_zero_effect_fixture(tmp_path)
    with open(events._path(SID), "ab") as out:
        out.write(b'{"event_id": "partial"}')
    assert _assess(events, budget).decision == HOLD


def test_event_seq_gap_is_hold(tmp_path: Path) -> None:
    events, budget, _ = _complete_zero_effect_fixture(tmp_path)
    path = Path(events._path(SID))
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[1]["seq"] += 50
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert _assess(events, budget).reason == "evidence_missing_or_unverifiable"


def test_duplicate_event_id_is_hold(tmp_path: Path) -> None:
    events, budget, _ = _complete_zero_effect_fixture(tmp_path)
    path = Path(events._path(SID))
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[1]["event_id"] = rows[0]["event_id"]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert _assess(events, budget).decision == HOLD


def test_strict_writer_rejects_bad_type_and_budget_before_write(tmp_path: Path) -> None:
    events = EventStore(tmp_path / "events")
    with pytest.raises(EventDurabilityError):
        events.append_durable_run_fact(SID, "provider.transport.opened", _payload(2))
    with pytest.raises(EventDurabilityError):
        events.append_durable_run_fact(SID, OPENED, {**_payload(2), "budget_id": "other"})
    assert not events.exists(SID)


def test_strict_writer_disabled_fails_closed(tmp_path: Path) -> None:
    events = EventStore(tmp_path / "events", enabled=False)
    with pytest.raises(EventDurabilityError):
        events.append_durable_run_fact(SID, OPENED, _payload(2))


def test_strict_writer_fsync_failure_is_uncertain_not_retry_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm_loop.event_log.store as module

    events = EventStore(tmp_path / "events")
    original_fsync = module.os.fsync

    def broken_fsync(fd: int) -> None:
        raise OSError("synthetic power-loss fence failure")

    monkeypatch.setattr(module.os, "fsync", broken_fsync)
    with pytest.raises(EventCommitUncertainError) as exc:
        events.append_durable_run_fact(SID, OPENED, _payload(2))
    assert "run_event_commit_outcome_uncertain" in str(exc.value)
    monkeypatch.setattr(module.os, "fsync", original_fsync)
    assert len(events.read(SID)) == 1  # physical bytes may exist, durability unknown


def test_strict_writer_open_failure_is_definite_pre_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm_loop.event_log.store as module

    events = EventStore(tmp_path / "events")
    original_open = module.os.open

    def broken_open(path, flags, *args, **kwargs):
        if str(path).endswith(".jsonl"):
            raise OSError("synthetic pre-append denial")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", broken_open)
    with pytest.raises(EventDurabilityError):
        events.append_durable_run_fact(SID, OPENED, _payload(2))
    monkeypatch.setattr(module.os, "open", original_open)
    assert events.read(SID) == []


def test_cross_process_crash_after_opened_fenced_remains_hold(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    script = (
        "import os; from llm_loop.event_log.store import EventStore;"
        "from llm_loop.core.durable_run_recovery import OPENED,FENCED,SCHEMA;"
        f"s=EventStore({str(events._dir)!r});"
        f"p={{'schema':SCHEMA,'run_generation':{GEN!r},"
        f"'authorization_id':{AUTH!r},'budget_id':{BID!r},"
        f"'budget_revision':{row['revision']!r}}};"
        f"s.append_durable_run_fact({SID!r},OPENED,p);"
        f"s.append_durable_run_fact({SID!r},FENCED,p);"
        "os._exit(17)"
    )
    source_root = Path(__file__).resolve().parents[2] / "src"
    env = {**os.environ, "PYTHONPATH": str(source_root)}
    result = subprocess.run(
        [sys.executable, "-c", script], check=False, timeout=15, env=env
    )
    assert result.returncode == 17
    _stop(budget, row)
    fresh = EventStore(events._dir)
    assert _assess(fresh, TaskBudgetStore(budget.directory)).decision == HOLD
    assert len(fresh.read(SID)) == 2


def test_no_external_activity_after_terminal_can_be_claimed(tmp_path: Path) -> None:
    events, budget, _ = _complete_zero_effect_fixture(tmp_path)
    events.append(SID, "provider.call.opened", {
        "call_id": "late", "origin_run_generation": GEN,
    })
    assert _assess(events, budget).reason == "events_after_terminal"


def test_completed_run_end_before_fence_is_hold(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    events.append_durable_run_fact(SID, OPENED, _payload(row["revision"]))
    end = events.append(SID, "run.end", {
        "reason": "completed", "run_generation": GEN,
    })
    assert end is not None
    events.append_durable_run_fact(SID, FENCED, _payload(row["revision"]))
    row = _stop(budget, row)
    _terminal(events, row["revision"], outcome="completed", end_id=end.event_id)
    assert _assess(events, budget).reason == "completed_terminal_not_correlated"


def test_strict_writer_hook_filter_is_uncertain_not_success(tmp_path: Path) -> None:
    class DropHook:
        def process(self, event):
            return None, []

    events = EventStore(tmp_path / "events", hook_chain=DropHook())
    with pytest.raises(EventCommitUncertainError):
        events.append_durable_run_fact(SID, OPENED, _payload(2))
    assert events.read(SID) == []


def test_strict_writer_rejects_symlink_target(tmp_path: Path) -> None:
    events = EventStore(tmp_path / "events")
    events._ensure_dir()
    real = tmp_path / "unrelated.jsonl"
    real.write_text("", encoding="utf-8")
    Path(events._path(SID)).symlink_to(real)
    with pytest.raises(EventDurabilityError):
        events.append_durable_run_fact(SID, OPENED, _payload(2))
    assert real.read_text(encoding="utf-8") == ""


def test_strict_writer_cross_process_monotonic_seq(tmp_path: Path) -> None:
    events = EventStore(tmp_path / "events")
    source_root = Path(__file__).resolve().parents[2] / "src"
    env = {**os.environ, "PYTHONPATH": str(source_root)}
    script = (
        "from llm_loop.event_log.store import EventStore;"
        "from llm_loop.core.durable_run_recovery import OPENED,SCHEMA;"
        f"s=EventStore({str(events._dir)!r});"
        f"p={{'schema':SCHEMA,'run_generation':{GEN!r},"
        f"'authorization_id':{AUTH!r},'budget_id':{BID!r},"
        "'budget_revision':2};"
        f"s.append_durable_run_fact({SID!r},OPENED,p)"
    )
    first = subprocess.Popen([sys.executable, "-c", script], env=env)
    second = subprocess.Popen([sys.executable, "-c", script], env=env)
    assert first.wait(timeout=15) == 0
    assert second.wait(timeout=15) == 0
    fresh = EventStore(events._dir)
    rows = fresh.read(SID)
    assert len(rows) == 2
    assert [event.seq for event in rows] == [1, 2]
    assert len({event.event_id for event in rows}) == 2


def test_pre_open_provider_activity_is_hold_even_if_settled(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    events.append(SID, "provider.call.opened", {
        "call_id": "earlier-run", "origin_run_generation": "c" * 32,
    })
    events.append(SID, "provider.transport.settled", {
        "call_id": "earlier-run", "attempt_id": "old-attempt",
        "outcome": "success",
    })
    _open(events, row["revision"])
    row = _stop(budget, row)
    _terminal(events, row["revision"])
    verdict = _assess(events, budget)
    assert verdict.decision == HOLD
    assert verdict.reason == "unattributed_pre_run_activity"


def test_pre_open_tool_effect_activity_is_hold(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    events.append(SID, "tool.execution.effect_observed", {
        "execution_id": "old-effect", "matches_expected": True,
    })
    _open(events, row["revision"])
    row = _stop(budget, row)
    _terminal(events, row["revision"], outcome="completed", end_id="bogus")
    assert _assess(events, budget).reason == "unattributed_pre_run_activity"


def test_pre_open_tool_receipt_message_is_hold(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    events.append(SID, "message.appended", {
        "role": "tool", "content": "old tool receipt",
    })
    _open(events, row["revision"])
    row = _stop(budget, row)
    _terminal(events, row["revision"])
    assert _assess(events, budget).reason == "unattributed_pre_run_activity"


def test_pre_open_session_created_and_user_ingress_are_allowed(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    events.append(SID, "session.created", {"session_id": SID})
    events.append(SID, "message.appended", {
        "role": "user", "content": "synthetic no-effect turn",
    })
    _open(events, row["revision"])
    row = _stop(budget, row)
    _terminal(events, row["revision"])
    assert _assess(events, budget).decision == REPLAN


def test_closed_uncertain_even_without_reservations_is_hold(tmp_path: Path) -> None:
    events, budget, row = _fixture(tmp_path)
    _open(events, row["revision"])
    row = _stop(budget, row)
    row = budget.mark_settling(BID, expected_revision=row["revision"])
    row = budget.close_uncertain(BID, expected_revision=row["revision"])
    assert row["reservations"] == {}
    _terminal(events, row["revision"])
    assert _assess(events, budget).reason == "budget_not_stopped"


def test_mixed_legacy_and_strict_cross_process_append_share_seq_lock(
    tmp_path: Path,
) -> None:
    events = EventStore(tmp_path / "events")
    source_root = Path(__file__).resolve().parents[2] / "src"
    env = {**os.environ, "PYTHONPATH": str(source_root)}
    common = (
        "from llm_loop.event_log.store import EventStore;"
        f"s=EventStore({str(events._dir)!r});"
    )
    legacy = common + f"s.append({SID!r},'session.created',{{'source':'legacy'}})"
    strict = (
        common
        + "from llm_loop.core.durable_run_recovery import OPENED,SCHEMA;"
        + f"s.append_durable_run_fact({SID!r},OPENED,"
        + f"{{'schema':SCHEMA,'run_generation':{GEN!r},"
        + f"'authorization_id':{AUTH!r},'budget_id':{BID!r},"
        + "'budget_revision':2})"
    )
    children = [
        subprocess.Popen([sys.executable, "-c", script], env=env)
        for script in (legacy, strict)
    ]
    assert all(child.wait(timeout=15) == 0 for child in children)
    fresh = EventStore(events._dir)
    rows = fresh.read(SID)
    assert len(rows) == 2
    assert [row.seq for row in rows] == [1, 2]
    assert {row.type for row in rows} == {"session.created", OPENED}

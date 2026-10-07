"""Actual admission, process restart and one-shot authority regressions."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from llm_loop.core.schedule_delivery import ScheduleWakeDelivery
from llm_loop.core.scheduler import WAKE_DEFERRED, ScheduleStore, rearm_wake_grants
from llm_loop.core.trace_leak.ingress_token import (
    delegate_ingress,
    issue_ingress,
    restore_scheduled_ingress,
)


class ControlledRunner:
    enabled = True

    def __init__(self, mode: str = "busy") -> None:
        self.mode = mode
        self.calls = 0
        self.kwargs = {}

    def start(self, _sid, _prompt, **kwargs):
        self.kwargs = kwargs
        if self.mode == "busy":
            return None, None
        if self.mode == "admit":
            kwargs["before_start"](object())
            self.calls += 1
            kwargs["terminal_callback"]("completed", None)
        return object(), None

    def is_running(self, _sid):
        return self.mode == "busy"

    def is_sync_active(self, _sid):
        return False


def fixture_delivery(tmp_path: Path, mode: str = "busy", **scope):
    store = ScheduleStore(tmp_path / "schedule.json")
    grant = delegate_ingress(issue_ingress("web"), entry="schedule_wake")
    sid = store.add("check status once", after=0, wake=True, session_id="fixture", wake_grant=grant, **scope)
    entry = store.claim_due("fixture-owner")[0]
    runner = ControlledRunner(mode)
    records = []
    delivery = ScheduleWakeDelivery(
        store, runner, data_dir=str(tmp_path),
        record_action=lambda *args: records.append(args),
    )
    return store, sid, entry, runner, records, delivery


def test_busy_does_not_mark_started_or_spend_authority(tmp_path):
    store, sid, entry, runner, records, delivery = fixture_delivery(tmp_path)
    assert delivery(entry) is WAKE_DEFERRED
    row = store.list()[0]
    assert row["wake_started_at"] == 0
    assert row["wake_wait_reason"] == "session_busy"
    assert store.authority_state(sid) == "pending"
    assert runner.calls == 0
    assert not any(record[1] == "started" for record in records)


def test_handle_alone_is_not_admission(tmp_path):
    store, sid, entry, runner, records, delivery = fixture_delivery(tmp_path, "queued")
    assert delivery(entry) is WAKE_DEFERRED
    row = store.list()[0]
    assert row["wake_started_at"] == 0
    assert row["wake_delivery_state"] == "queued"
    assert store.authority_state(sid) == "pending"
    runner.kwargs["terminal_callback"]("not_started", "cross-process busy")
    row = store.list()[0]
    assert row["wake_started_at"] == 0
    assert row["wake_wait_reason"] == "session_busy"
    assert store.authority_state(sid) == "pending"
    assert not any(record[1] == "started" for record in records)


def test_admission_consumes_once_and_only_then_records_started(tmp_path):
    store, sid, entry, runner, records, delivery = fixture_delivery(tmp_path, "admit")
    assert delivery(entry) is WAKE_DEFERRED
    assert store.list() == []
    assert runner.calls == 1
    assert runner.kwargs["ingress"].delegated is True
    assert [r[1] for r in records] == ["started"]
    with pytest.raises(ValueError, match="cancelled"):
        runner.kwargs["before_start"](object())
    assert store.recover_wake_grant(sid) is None


def test_cancel_after_queue_prevents_any_admission(tmp_path):
    store, sid, entry, runner, _, delivery = fixture_delivery(tmp_path, "queued")
    delivery(entry)
    store.cancel(sid)
    with pytest.raises(ValueError, match="cancelled"):
        runner.kwargs["before_start"](object())
    runner.kwargs["terminal_callback"]("failed", "cancelled")
    assert store.list() == []
    assert runner.calls == 0


def test_goal_replaced_while_queued_does_not_run(tmp_path):
    store, _, entry, runner, _, delivery = fixture_delivery(
        tmp_path, "queued", goal_id="goal-1", goal_generation="g1"
    )
    current = [("goal-1", "g1")]
    delivery.goal_binding_resolver = lambda _sid: current[0]
    delivery(entry)
    current[0] = ("goal-2", "g2")
    with pytest.raises(ValueError, match="Goal changed"):
        runner.kwargs["before_start"](object())
    assert runner.calls == 0
    assert store.list()[0]["wake_started_at"] == 0


def test_altered_scope_cannot_restore_authority(tmp_path):
    store, sid, _, _, _, _ = fixture_delivery(tmp_path)
    store.clear_wake_grant(sid)
    data = store.list()
    data[0]["session_id"] = "other-session"
    store._path.write_text(json.dumps(data))
    assert store.recover_wake_grant(sid) is None
    assert store.wake_delivery_facts(data[0])["delivery_state"] == "waiting_human"


def test_ledger_tamper_cannot_restore_human_or_delegated_authority(tmp_path):
    store, sid, _, _, _, _ = fixture_delivery(tmp_path)
    store.clear_wake_grant(sid)
    ledger = tmp_path / "schedule-wake-authority.json"
    rows = json.loads(ledger.read_text())
    rows[sid]["channel"] = "cli"
    ledger.write_text(json.dumps(rows))
    assert store.recover_wake_grant(sid) is None
    with pytest.raises(ValueError, match="verified"):
        restore_scheduled_ingress({"channel": "web"})


def test_private_key_and_ledger_permissions(tmp_path):
    fixture_delivery(tmp_path)
    assert (tmp_path / "schedule-wake-authority.json").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "schedule-wake-authority.key").stat().st_mode & 0o777 == 0o600


def test_legacy_wake_remains_waiting_for_human_rearm(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    sid = store.add("legacy", after=0, wake=True, session_id="fixture")
    assert store.recover_wake_grant(sid) is None
    assert store.wake_delivery_facts(store.list()[0])["delivery_state"] == "waiting_human"


def test_busy_retry_can_later_admit_exactly_once(tmp_path):
    store, sid, entry, runner, records, delivery = fixture_delivery(tmp_path)
    delivery(entry)
    original_deadline = entry.scheduled_trigger_at
    row = store.list()[0]
    runner.mode = "admit"
    retry = store.claim_due("retry-owner", now=row["trigger_at"])[0]
    delivery(retry)
    assert retry.scheduled_trigger_at == original_deadline
    assert store.list() == []
    assert runner.calls == 1
    assert [r[1] for r in records].count("started") == 1
    assert store.recover_wake_grant(sid) is None


def test_replaced_claim_rejects_late_worker_and_new_owner_admits_once(tmp_path):
    store, _, entry, first, _, delivery = fixture_delivery(tmp_path, "queued")
    delivery(entry)
    replacement = store.claim_due("replacement-owner", now=time.time() + 40)[0]
    with pytest.raises(ValueError, match="replaced"):
        first.kwargs["before_start"](object())
    # A stale terminal callback must not defer another owner's claim.
    first.kwargs["terminal_callback"]("not_started", "late worker")
    assert store.list()[0]["lease_owner"] == "replacement-owner"
    assert store.list()[0]["retry_count"] == 0
    second = ControlledRunner("admit")
    delivery.runner = second
    delivery(replacement)
    assert second.calls == 1
    assert store.list() == []


def test_failed_authority_persistence_prevents_model_work(tmp_path, monkeypatch):
    store, sid, entry, runner, _, delivery = fixture_delivery(tmp_path, "admit")

    def fail_write(_records):
        raise OSError("fixture disk unavailable")

    monkeypatch.setattr(store._authority, "_write", fail_write)
    assert delivery(entry) is WAKE_DEFERRED
    assert runner.calls == 0
    assert store.authority_state(sid) == "pending"
    assert store.list()[0]["wake_started_at"] == 0


def test_missing_private_key_never_restores_authority(tmp_path):
    store, sid, _, _, _, _ = fixture_delivery(tmp_path)
    store.clear_wake_grant(sid)
    (tmp_path / "schedule-wake-authority.key").unlink()
    assert store.recover_wake_grant(sid) is None
    assert store.wake_delivery_facts(store.list()[0])["delivery_state"] == "waiting_human"


def test_consumed_snapshot_is_not_presented_as_rearmable(tmp_path):
    store, sid, _, _, _, _ = fixture_delivery(tmp_path)
    store._authority.consume(store.list()[0])
    store.clear_wake_grant(sid)
    assert store.wake_delivery_facts(store.list()[0]) == {
        "delivery_state": "inactive", "wait_reason": "delegation_consumed",
    }


def test_consumed_durable_authority_cannot_be_rearmed_by_a_human(tmp_path, monkeypatch):
    store, sid, _, _, _, _ = fixture_delivery(tmp_path)
    store._authority.consume(store.list()[0])
    store.clear_wake_grant(sid)
    # Simulate the original process exiting while its schedule snapshot remains.
    monkeypatch.setattr("llm_loop.core.scheduler.os.getpid", lambda: 987654321)
    monkeypatch.setattr("llm_loop.core.scheduler._pid_alive", lambda _pid: False)
    assert rearm_wake_grants(store, "fixture", issue_ingress("web")) == 0
    assert store.wake_grant(sid) is None


def test_legacy_human_rearm_becomes_durable_for_next_restart(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    sid = store.add("legacy reminder", after=0, wake=True, session_id="fixture")
    assert rearm_wake_grants(store, "fixture", issue_ingress("web")) == 1
    store.clear_wake_grant(sid)
    assert store.authority_state(sid) == "pending"
    assert store.recover_wake_grant(sid).delegated is True


def test_real_loop_engine_completes_delegated_wake(build_test_engine, tmp_path, monkeypatch):
    from llm_loop.core.loop.runner import BackgroundRunner

    engine, llm = build_test_engine([{"content": "restart wake complete"}])
    session_id = engine.session.create()
    store = ScheduleStore(tmp_path / "schedule.json")
    store.add(
        "report completion", after=0, wake=True, session_id=session_id,
        wake_grant=delegate_ingress(issue_ingress("web"), entry="schedule_wake"),
    )
    runner = BackgroundRunner(engine)
    handles = []
    original_start = runner.start

    def capture_start(*args, **kwargs):
        handle, events = original_start(*args, **kwargs)
        handles.append(handle)
        return handle, events

    monkeypatch.setattr(runner, "start", capture_start)
    records = []
    delivery = ScheduleWakeDelivery(
        store, runner, data_dir=str(tmp_path), record_action=lambda *args: records.append(args),
    )
    delivery(store.claim_due("actual-engine")[0])
    deadline = time.time() + 3
    while runner.is_running(session_id) and time.time() < deadline:
        time.sleep(0.01)
    assert len(llm.calls) == 1
    assert store.list() == []
    assert any(r[1] == "started" for r in records)
    assert handles[0].status == "done"
    assert handles[0].finished_at > 0


def test_process_restart_recovers_without_new_human_and_never_replays(tmp_path):
    path = tmp_path / "schedule.json"
    child_env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    producer = """
import json, sys
from pathlib import Path
from llm_loop.core.scheduler import ScheduleStore
from llm_loop.core.trace_leak.ingress_token import issue_ingress, delegate_ingress
store = ScheduleStore(Path(sys.argv[1]))
sid = store.add('restart canary', after=0, wake=True, session_id='restart-fixture',
                wake_grant=delegate_ingress(issue_ingress('web'), entry='schedule_wake'))
print(json.dumps(store.list()))
"""
    snapshot = subprocess.check_output([sys.executable, "-c", producer, str(path)], text=True, env=child_env)
    sid = json.loads(snapshot)[0]["sid"]
    consumer = """
import json, queue, sys
from pathlib import Path
from types import SimpleNamespace
from llm_loop.core.scheduler import ScheduleStore
from llm_loop.core.schedule_delivery import ScheduleWakeDelivery
from llm_loop.core.loop.runner import BackgroundRunner
class Engine:
    calls = 0
    def _run_stream_with_acquired(self, sid, text, model, on_run_acquired, **kwargs):
        on_run_acquired(object())
        assert kwargs['ingress'].delegated is True
        self.calls += 1
        yield SimpleNamespace(text='canary', reasoning='', tool_round=None)
        return SimpleNamespace(final_answer='done')
store = ScheduleStore(Path(sys.argv[1]))
engine = Engine()
runner = BackgroundRunner(engine)
delivery = ScheduleWakeDelivery(store, runner, data_dir=str(Path(sys.argv[1]).parent),
                                record_action=lambda *args: None)
entries = store.claim_due('restart-consumer')
for entry in entries:
    delivery(entry)
handle = runner.get_status('restart-fixture')
import time
deadline = time.time() + 3
while runner.is_running('restart-fixture') and time.time() < deadline:
    time.sleep(0.01)
print(json.dumps({'calls':engine.calls,'remaining':len(store.list())}))
"""
    # Use the real BackgroundRunner in a fresh interpreter with no human ingress.
    consumer = consumer.replace("handle = runner.get_status('restart-fixture')\n", "")
    first = json.loads(subprocess.check_output([sys.executable, "-c", consumer, str(path)], text=True, env=child_env))
    assert first == {"calls": 1, "remaining": 0}
    # Simulate an old schedule snapshot returning after the ack; ledger tombstone wins.
    path.write_text(snapshot)
    restarted = ScheduleStore(path)
    assert restarted.recover_wake_grant(sid) is None
    second = json.loads(subprocess.check_output([sys.executable, "-c", consumer, str(path)], text=True, env=child_env))
    assert second["calls"] == 0

"""schedule wake: delegated one-shot continuation without reopening INBOX_WAKEUP."""

from __future__ import annotations

import json
import os
import time

from llm_loop.core.run_context import current_session_id
from llm_loop.core.scheduler import ScheduleEntry, SchedulerThread, ScheduleStore
from llm_loop.core.trace_leak.ingress_token import (
    current_ingress_session_id,
    current_ingress_token,
    issue_test_ingress,
)
from llm_loop.tools.builtin.schedule import ScheduleTool


def _inbox_files(tmp_path) -> list[dict]:
    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    files = sorted(inbox.glob("*.json")) if inbox.exists() else []
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def test_default_schedule_still_notifies_only(tmp_path, monkeypatch):
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    e = ScheduleEntry(sid="sched-x1", message="m", trigger_at=0)
    assert e.wake is False
    SchedulerThread._notify_via_interop(e)
    (msg,) = _inbox_files(tmp_path)
    assert msg["topic"] == "notify"
    assert msg["body"].startswith("[定时提醒] ")


def test_wake_without_human_ingress_is_unauthorized(tmp_path):
    tool = ScheduleTool(store=ScheduleStore(tmp_path / "schedule.json"))
    result = tool.execute(message="复查", after=30, wake=True)
    assert result.status.value == "unauthorized"
    assert "真实用户输入" in result.content
    assert tool._store.list() == []


def test_wake_grant_is_bound_to_same_session_and_not_persisted(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    tool = ScheduleTool(store=store)
    ingress = issue_test_ingress()
    sid_tok = current_session_id.set("sess-wake")
    ing_tok = current_ingress_token.set(ingress)
    ing_sid_tok = current_ingress_session_id.set("sess-wake")
    try:
        result = tool.execute(message="复查 job", after=30, wake=True)
    finally:
        current_ingress_session_id.reset(ing_sid_tok)
        current_ingress_token.reset(ing_tok)
        current_session_id.reset(sid_tok)

    assert result.status.value == "success"
    entry = store.list()[0]
    assert entry["wake"] is True
    assert entry["session_id"] == "sess-wake"
    assert entry["wake_owner_pid"] == os.getpid()
    grant = store.wake_grant(entry["sid"])
    assert grant is not None and grant.delegated is True

    # grant 是 process-local capability，而不是 Store-instance-local。相同 SoT 的同进程
    # Store 必须共享它，避免 same-PID scheduler 抢到 entry 却看不到授权。
    same_process = ScheduleStore(tmp_path / "schedule.json")
    assert same_process.list()[0]["wake"] is True
    assert same_process.wake_grant(entry["sid"]) is grant

    # 模拟进程重启：process-local registry 消失后，磁盘只恢复 wake 意图，不恢复授权。
    import llm_loop.core.scheduler as scheduler_mod
    with scheduler_mod._WAKE_GRANT_LOCK:
        scheduler_mod._WAKE_GRANTS.clear()
    restarted = ScheduleStore(tmp_path / "schedule.json")
    assert restarted.list()[0]["wake"] is True
    assert restarted.wake_grant(entry["sid"]) is None


def test_delegated_wake_cannot_recursively_schedule_another_wake(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    tool = ScheduleTool(store=store)
    ingress = issue_test_ingress()
    sid_tok = current_session_id.set("sess-wake")
    ing_tok = current_ingress_token.set(ingress)
    ing_sid_tok = current_ingress_session_id.set("sess-wake")
    try:
        first = tool.execute(message="第一次", after=30, wake=True)
        assert first.status.value == "success"
        grant = store.wake_grant(store.list()[0]["sid"])
        current_ingress_token.set(grant)
        second = tool.execute(message="递归", after=30, wake=True)
    finally:
        current_ingress_session_id.reset(ing_sid_tok)
        current_ingress_token.reset(ing_tok)
        current_session_id.reset(sid_tok)

    assert second.status.value == "unauthorized"
    assert len(store.list()) == 1


def test_wake_rejects_recurring_autonomous_runs(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    tool = ScheduleTool(store=store)
    ingress = issue_test_ingress()
    sid_tok = current_session_id.set("sess-wake")
    ing_tok = current_ingress_token.set(ingress)
    ing_sid_tok = current_ingress_session_id.set("sess-wake")
    try:
        result = tool.execute(
            message="周期自动跑", after=30, wake=True, repeat_interval=60, max_count=3
        )
    finally:
        current_ingress_session_id.reset(ing_sid_tok)
        current_ingress_token.reset(ing_tok)
        current_session_id.reset(sid_tok)
    assert result.status.value == "failure"
    assert "一次性" in result.content


def test_wake_grant_exists_before_immediate_entry_can_be_claimed(tmp_path):
    """after=0 entry 不得先于 process-local grant 对 scheduler 可见。"""
    store = ScheduleStore(tmp_path / "schedule.json")
    grant = object()
    observed: list[object | None] = []
    original_mutate = store._mutate

    def mutate_then_probe(fn):
        original_mutate(fn)
        probe = ScheduleStore(tmp_path / "schedule.json")
        claimed = probe.claim_due("probe", now=time.time() + 0.01, lease_s=30)
        observed.extend(probe.wake_grant(entry.sid) for entry in claimed)

    store._mutate = mutate_then_probe  # type: ignore[method-assign]
    store.add("immediate", after=0, wake=True, session_id="sess", wake_grant=grant)
    assert observed == [grant]


def test_same_process_store_cannot_lose_wake_grant(tmp_path):
    """同进程第二 Store 可 claim 同一 SoT，但必须看到同一个 process-local grant。"""
    path = tmp_path / "schedule.json"
    first = ScheduleStore(path)
    second = ScheduleStore(path)
    grant = object()
    sid = first.add("once", after=0, wake=True, session_id="sess", wake_grant=grant)
    claimed = second.claim_due("second", now=time.time() + 0.01, lease_s=30)
    assert [entry.sid for entry in claimed] == [sid]
    assert second.wake_grant(sid) is grant


def test_scheduler_false_delivery_retries_without_losing_entry(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    sid = store.add("busy", after=0)
    calls: list[str] = []

    def busy(entry):
        calls.append(entry.sid)
        return False

    th = SchedulerThread(store, tick_interval=0.02, notify=busy)
    th.start()
    try:
        deadline = time.time() + 1
        while not calls and time.time() < deadline:
            time.sleep(0.01)
        assert calls == [sid]
        entries = store.list()
        assert len(entries) == 1 and entries[0]["sid"] == sid
        assert entries[0]["trigger_at"] > time.time()
        assert entries[0]["lease_owner"] == ""
    finally:
        th.stop()


def test_claim_due_is_single_owner_until_ack(tmp_path):
    store_a = ScheduleStore(tmp_path / "schedule.json")
    store_b = ScheduleStore(tmp_path / "schedule.json")
    sid = store_a.add("once", after=0)
    a = store_a.claim_due("owner-a", lease_s=30)
    b = store_b.claim_due("owner-b", lease_s=30)
    assert [e.sid for e in a] == [sid]
    assert b == []
    store_a.mark_triggered(sid, owner="owner-a")
    assert store_b.list() == []


def test_legacy_json_without_wake_fields_defaults_safe(tmp_path):
    legacy = [{
        "sid": "sched-old", "message": "m", "trigger_at": 1.0,
        "repeat_interval": 0, "max_count": 1, "created_at": 1.0, "count": 0,
    }]
    p = tmp_path / "schedule.json"
    p.write_text(json.dumps(legacy), encoding="utf-8")
    store = ScheduleStore(p)
    (entry,) = store.due(now=2)
    assert entry.wake is False
    assert entry.session_id == ""
    assert entry.wake_owner_pid == 0


def test_schedule_schema_exposes_wake():
    props = ScheduleTool.parameters["properties"]
    assert props["wake"]["type"] == "boolean"
    assert props["message"]["maxLength"] == 4000


def test_schedule_message_has_mechanical_context_bound(tmp_path):
    tool = ScheduleTool(store=ScheduleStore(tmp_path / "schedule.json"))
    result = tool.execute(message="x" * 4001, after=30)
    assert result.status.value == "failure"
    assert "4000" in result.content
    assert tool._store.list() == []

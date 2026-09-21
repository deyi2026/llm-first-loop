"""schedule wake: delegated one-shot continuation without reopening INBOX_WAKEUP."""

from __future__ import annotations

import json
import os
import time

from llm_loop.core.run_context import current_session_id
from llm_loop.core.scheduler import (
    WAKE_DEFERRED,
    WAKE_MAX_RETRIES,
    ScheduleEntry,
    SchedulerThread,
    ScheduleStore,
    rearm_wake_grants,
    wake_goal_binding_state,
)
from llm_loop.core.trace_leak.ingress_token import (
    current_ingress_session_id,
    current_ingress_token,
    delegate_ingress,
    issue_test_ingress,
)
from llm_loop.introspection.goal import GoalStore
from llm_loop.tools.builtin.schedule import ScheduleTool


def _inbox_files(tmp_path) -> list[dict]:
    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    files = sorted(inbox.glob("*.json")) if inbox.exists() else []
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def test_default_schedule_still_notifies_only(tmp_path, monkeypatch):
    e = ScheduleEntry(sid="sched-x1", message="m", trigger_at=0)
    assert e.wake is False
    SchedulerThread._notify_via_interop(e, data_dir=tmp_path)
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


# ── EVO-20260919-f119847d: 有界退避 + re-arm ──────────────────────────────


def test_defer_wake_retry_exponential_then_caps(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    grant = object()
    sid = store.add("w", after=0, wake=True, session_id="s", wake_grant=grant)
    store.claim_due("owner-x", lease_s=30)

    r1 = store.defer_wake_retry(sid, owner="owner-x")
    assert r1.present and not r1.exhausted
    assert r1.retry_count == 1 and r1.next_delay_s == 30.0
    snap = {x["sid"]: x for x in store.list()}[sid]
    assert snap["retry_count"] == 1
    assert snap["trigger_at"] > time.time()
    assert snap["retry_deadline_at"] > time.time()
    assert snap["lease_owner"] == ""  # 已释放，等下次到点重新 claim

    # 次数上限：逼近上限后 exhausted，且保留 lease 供降级路径 mark_triggered ack。
    def _force_count(entries):
        e = entries[sid]
        e.retry_count = WAKE_MAX_RETRIES - 1
        e.lease_owner = "owner-x"
        e.lease_until = time.time() + 30

    store._mutate(_force_count)
    r2 = store.defer_wake_retry(sid, owner="owner-x")
    assert r2.exhausted
    snap2 = {x["sid"]: x for x in store.list()}[sid]
    assert snap2["lease_owner"] == "owner-x"

    # 窗口上限：deadline 已过 → exhausted。
    def _force_window(entries):
        e = entries[sid]
        e.retry_count = 1
        e.retry_deadline_at = time.time() - 1
        e.lease_owner = "owner-x"

    store._mutate(_force_window)
    r3 = store.defer_wake_retry(sid, owner="owner-x")
    assert r3.exhausted

    # 条目已消费 → present=False（调用方无需处理）。
    store.mark_triggered(sid, owner="owner-x")
    r4 = store.defer_wake_retry(sid, owner="owner-x")
    assert not r4.present and not r4.exhausted


def test_scheduler_wake_deferred_sentinel_keeps_entry_without_ack(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    grant = object()
    sid = store.add("w", after=0, wake=True, session_id="s", wake_grant=grant)
    seen: list[str] = []

    def defer_delivery(entry):
        seen.append(entry.sid)
        res = store.defer_wake_retry(entry.sid)
        assert res.present and not res.exhausted
        return WAKE_DEFERRED

    th = SchedulerThread(store, tick_interval=0.02, notify=defer_delivery)
    th.start()
    try:
        deadline = time.time() + 1
        while not seen and time.time() < deadline:
            time.sleep(0.01)
        assert seen == [sid]
        time.sleep(0.05)
        snap = {x["sid"]: x for x in store.list()}[sid]
        # 不 ack：条目保留、count 不变；不 retry_later：退避节奏不被覆盖。
        assert snap["count"] == 0
        assert snap["retry_count"] == 1
        assert snap["trigger_at"] > time.time()
        assert snap["lease_owner"] == ""
    finally:
        th.stop()


def test_note_wake_started_marks_entry_idempotently(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    grant = object()
    sid = store.add("w", after=0, wake=True, session_id="s", wake_grant=grant)
    store.note_wake_started(sid)
    snap = {x["sid"]: x for x in store.list()}[sid]
    assert snap["wake_started_at"] > 0
    store.note_wake_started(sid)
    snap2 = {x["sid"]: x for x in store.list()}[sid]
    assert snap2["wake_started_at"] == snap["wake_started_at"]


def test_rearm_wake_grants_rebuilds_after_owner_process_death(tmp_path):
    import llm_loop.core.scheduler as scheduler_mod

    store = ScheduleStore(tmp_path / "schedule.json")
    tool = ScheduleTool(store=store)
    ingress = issue_test_ingress()
    sid_tok = current_session_id.set("sess-r")
    ing_tok = current_ingress_token.set(ingress)
    ing_sid_tok = current_ingress_session_id.set("sess-r")
    try:
        result = tool.execute(message="续跑", after=30, wake=True)
    finally:
        current_ingress_session_id.reset(ing_sid_tok)
        current_ingress_token.reset(ing_tok)
        current_session_id.reset(sid_tok)
    assert result.status.value == "success"
    entry = store.list()[0]
    sid = entry["sid"]

    # 模拟 owner 进程死亡：pid 指向不存在的进程 + 本进程 grant 丢失。
    def _kill(entries):
        entries[sid].wake_owner_pid = 999_999_999

    store._mutate(_kill)
    with scheduler_mod._WAKE_GRANT_LOCK:
        scheduler_mod._WAKE_GRANTS.clear()
    assert store.wake_grant(sid) is None

    # 他会话 / 委派 token 均不重铸（授权边界与递归禁令不变）。
    assert rearm_wake_grants(store, "other-sess", ingress) == 0
    delegated = delegate_ingress(ingress, entry="schedule_wake")
    assert rearm_wake_grants(store, "sess-r", delegated) == 0
    assert store.wake_grant(sid) is None

    # 同会话真人 run → 重铸成功，owner 迁移到当前进程并重置退避预算。
    assert rearm_wake_grants(store, "sess-r", ingress) == 1
    grant = store.wake_grant(sid)
    assert grant is not None and grant.delegated is True
    snap = {x["sid"]: x for x in store.list()}[sid]
    assert snap["wake_owner_pid"] == os.getpid()
    assert snap["retry_count"] == 0 and snap["retry_deadline_at"] == 0.0
    # 幂等：grant 已存在时不重复重铸。
    assert rearm_wake_grants(store, "sess-r", ingress) == 0


def test_rearm_skips_already_started_wake(tmp_path):
    import llm_loop.core.scheduler as scheduler_mod

    store = ScheduleStore(tmp_path / "schedule.json")
    ingress = issue_test_ingress()
    grant = object()
    sid = store.add("续跑", after=30, wake=True, session_id="sess-r", wake_grant=grant)
    store.note_wake_started(sid)

    def _kill(entries):
        entries[sid].wake_owner_pid = 999_999_999

    store._mutate(_kill)
    with scheduler_mod._WAKE_GRANT_LOCK:
        scheduler_mod._WAKE_GRANTS.clear()

    # run 已启动过的条目绝不 re-arm——不允许二次自治 run。
    assert rearm_wake_grants(store, "sess-r", ingress) == 0
    assert store.wake_grant(sid) is None


def test_wake_binds_strict_session_goal_identity_and_terminal_becomes_stale(tmp_path):
    audit_dir = tmp_path / "audit"
    goals = GoalStore(audit_dir)
    goal = goals.create("bounded work", session_id="sess-g")
    store = ScheduleStore(tmp_path / "schedule.json")
    tool = ScheduleTool(store=store, goal_binding_resolver=goals.active_identity)
    ingress = issue_test_ingress()
    sid_tok = current_session_id.set("sess-g")
    ing_tok = current_ingress_token.set(ingress)
    ing_sid_tok = current_ingress_session_id.set("sess-g")
    try:
        result = tool.execute(message="verify later", after=30, wake=True)
    finally:
        current_ingress_session_id.reset(ing_sid_tok)
        current_ingress_token.reset(ing_tok)
        current_session_id.reset(sid_tok)

    assert result.status.value == "success"
    raw = store.list()[0]
    assert raw["goal_id"] == goal.id
    assert raw["goal_generation"] == goal.generation
    entry = ScheduleEntry.from_dict(raw)
    assert wake_goal_binding_state(entry, goals.active_identity) == "active"

    goals.update(goal.id, "complete")
    assert wake_goal_binding_state(entry, goals.active_identity) == "stale"


def test_goal_generation_mismatch_is_stale_even_when_goal_id_matches(tmp_path):
    goals = GoalStore(tmp_path / "audit")
    goal = goals.create("bounded work", session_id="sess-g")
    entry = ScheduleEntry(
        sid="sched-g",
        message="later",
        trigger_at=time.time() + 10,
        wake=True,
        session_id="sess-g",
        goal_id=goal.id,
        goal_generation="wrong-generation",
    )
    assert wake_goal_binding_state(entry, goals.active_identity) == "stale"


def test_rearm_consumes_terminal_goal_wake_as_noop(tmp_path):
    import llm_loop.core.scheduler as scheduler_mod

    goals = GoalStore(tmp_path / "audit")
    goal = goals.create("bounded work", session_id="sess-g")
    store = ScheduleStore(tmp_path / "schedule.json")
    tool = ScheduleTool(store=store, goal_binding_resolver=goals.active_identity)
    ingress = issue_test_ingress()
    sid_tok = current_session_id.set("sess-g")
    ing_tok = current_ingress_token.set(ingress)
    ing_sid_tok = current_ingress_session_id.set("sess-g")
    try:
        result = tool.execute(message="verify later", after=30, wake=True)
    finally:
        current_ingress_session_id.reset(ing_sid_tok)
        current_ingress_token.reset(ing_tok)
        current_session_id.reset(sid_tok)
    assert result.status.value == "success"
    sid = store.list()[0]["sid"]

    # Simulate owner loss, then terminal Goal before a later human run tries re-arm.
    def _kill(entries):
        entries[sid].wake_owner_pid = 999_999_999

    store._mutate(_kill)
    with scheduler_mod._WAKE_GRANT_LOCK:
        scheduler_mod._WAKE_GRANTS.clear()
    goals.update(goal.id, "complete")

    assert rearm_wake_grants(
        store,
        "sess-g",
        ingress,
        goal_binding_resolver=goals.active_identity,
    ) == 0
    assert store.list() == []


def test_legacy_unbound_wake_remains_compatible(tmp_path):
    entry = ScheduleEntry(
        sid="sched-legacy",
        message="legacy",
        trigger_at=time.time() + 10,
        wake=True,
        session_id="sess-legacy",
    )
    assert wake_goal_binding_state(entry, lambda _sid: None) == "unbound"

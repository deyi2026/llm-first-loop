"""Goal 级授权池 + 只撤销授权（v1.1 遗留）.

设计：docs/design/DESIGN-20261019-scheduled-task-authorization-v1.md
"""

from __future__ import annotations

import json
import time

import pytest

from llm_loop.core.scheduler import ScheduleStore
from llm_loop.core.trace_leak.ingress_token import delegate_ingress, issue_ingress
from llm_loop.tools.builtin.schedule import ScheduleCancelTool

WORKDIR = "/tmp/lfl-standing-pool"


def _add(store: ScheduleStore, *, text: str, fires: int = 3, goal: str = "goal-rsi",
         expires_at: float | None = None, pool: str | None = None) -> str:
    grant = delegate_ingress(issue_ingress("web"), entry="schedule_wake")
    return store.add(
        text, after=0, repeat_interval=3600, task_mode="task_recurring",
        wake_fires=fires,
        wake_expires_at=expires_at if expires_at is not None else time.time() + 30 * 86400,
        session_id="parent-sess", wake_grant=grant,
        goal_id=goal, goal_generation=1,
        wake_pool=(goal if pool is None else pool),
        wake_workdir=WORKDIR,
    )


def _row(store: ScheduleStore, sid: str) -> dict:
    return next(row for row in store.list() if row["sid"] == sid)


def test_pool_shares_one_quota_across_entries(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    expires = time.time() + 30 * 86400  # 同一池：规格必须逐字一致
    a = _add(store, text="A", expires_at=expires)
    b = _add(store, text="B", expires_at=expires)
    assert store.pool_facts("goal-rsi")["fires_total"] == 3

    store._authority.consume(_row(store, a))
    store._authority.consume(_row(store, b))
    assert store.pool_facts("goal-rsi")["fires_used"] == 2
    assert store.authority_state(a) == "pending"

    store._authority.consume(_row(store, a))
    facts = store.pool_facts("goal-rsi")
    assert facts["fires_used"] == 3 and facts["state"] == "consumed"
    # 池用尽对两个成员同时生效——不能靠多条条目绕过额度
    assert store.authority_state(a) == "consumed"
    assert store.authority_state(b) == "consumed"


def test_pool_join_requires_identical_spec(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    _add(store, text="A", fires=3)
    with pytest.raises(ValueError, match="spec mismatch"):
        _add(store, text="B", fires=5)
    with pytest.raises(ValueError, match="spec mismatch"):
        _add(store, text="B", expires_at=time.time() + 86400)


def test_pool_requires_standing_entry_and_goal(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    grant = delegate_ingress(issue_ingress("web"), entry="schedule_wake")
    with pytest.raises(ValueError, match="wake_pool requires task_recurring"):
        store.add("x", after=0, task_mode="remind", wake_pool="goal-rsi")
    with pytest.raises(ValueError, match="must equal a non-empty goal_id"):
        store.add(
            "x", after=0, repeat_interval=3600, task_mode="task_recurring",
            wake_fires=3, wake_expires_at=time.time() + 86400,
            session_id="p", wake_grant=grant, goal_id="", wake_pool="goal-rsi",
            wake_workdir=WORKDIR,
        )


def test_pool_closed_after_quota_exhausted_rejects_new_members(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    a = _add(store, text="A", fires=1)
    store._authority.consume(_row(store, a))
    with pytest.raises(ValueError, match="wake pool is closed"):
        _add(store, text="B", fires=1)


def test_pool_revoked_only_when_last_member_revoked(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    expires = time.time() + 30 * 86400
    a = _add(store, text="A", expires_at=expires)
    b = _add(store, text="B", expires_at=expires)
    assert store.revoke_wake_grant(a) is True
    assert store.pool_facts("goal-rsi")["state"] == "pending"
    assert store.authority_state(b) == "pending"
    assert store.revoke_wake_grant(b) is True
    assert store.pool_facts("goal-rsi")["state"] == "revoked"


def test_pool_tamper_is_invalid_not_trusted(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    a = _add(store, text="A")
    path = tmp_path / "schedule-wake-authority.json"
    ledger = json.loads(path.read_text(encoding="utf-8"))
    ledger["pool:goal-rsi"]["fires_total"] = 999
    path.write_text(json.dumps(ledger), encoding="utf-8")
    assert store.pool_facts("goal-rsi") is None
    assert store.authority_state(a) == "invalid"


def test_pool_expiry_degrades_all_members(tmp_path, monkeypatch):
    import llm_loop.core.trace_leak.wake_authority as wa

    store = ScheduleStore(tmp_path / "schedule.json")
    expires = time.time() + 30 * 86400
    a = _add(store, text="A", expires_at=expires)
    b = _add(store, text="B", expires_at=expires)

    class _Clock:
        def time(self) -> float:
            return expires + 1

    monkeypatch.setattr(wa, "time", _Clock())
    assert store.authority_state(a) == "expired"
    assert store.authority_state(b) == "expired"


def test_revoke_only_keeps_entry_as_notify(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    sid = _add(store, text="每日巡检")
    tool = ScheduleCancelTool(store=store)
    result = tool.execute(sid=sid, revoke_only=True)
    assert result.status.value == "success", result.content
    row = _row(store, sid)
    assert row["wake"] is False and row.get("task_mode", "") == ""
    assert row.get("wake_pool", "") == "" and row.get("wake_fires_total", 0) == 0
    assert row["message"] == "每日巡检"  # 条目保留，仍按通知提醒
    # 条目已降级（不再引用授权），账本里的记录必须是 revoked 而不是悬挂的 pending
    ledger = json.loads((tmp_path / "schedule-wake-authority.json").read_text(encoding="utf-8"))
    assert ledger[sid]["state"] == "revoked"

    again = tool.execute(sid=sid, revoke_only=True)
    assert again.status.value == "failure"
    assert "没有可撤销的常驻授权" in again.content
    assert store.list()  # 不会误删条目


def test_schedule_row_prefers_pool_facts():
    from llm_loop.web.routes import _schedule_row

    row = _schedule_row(
        {"sid": "s", "wake_fires_total": 5, "wake_fires_used": 1, "wake_expires_at": 100.0},
        None,
        {"fires_total": 30, "fires_used": 7, "expires_at": 200.0},
    )
    assert (row["wake_fires_total"], row["wake_fires_used"]) == (30, 7)
    assert row["wake_expires_at"] == 200.0


def test_upgrade_notify_entry_preserves_text_and_issues_grant(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    sid = store.add("每日巡检", after=0, repeat_interval=86400, max_count=60)
    grant = delegate_ingress(issue_ingress("web"), entry="schedule_wake")
    store.upgrade_to_standing(
        sid, grant=grant, session_id="s1", fires=5,
        expires_at=time.time() + 30 * 86400, external=False, workdir=WORKDIR,
    )
    row = _row(store, sid)
    assert row["message"] == "每日巡检"  # 正文不动，避免迁移时手抄出错
    assert row["repeat_interval"] == 86400
    assert row["task_mode"] == "task_recurring" and row["wake"] is True
    assert row["wake_fires_total"] == 5 and row["wake_fires_used"] == 0
    assert row["count"] == 0 and row["max_count"] == 5
    assert store.authority_state(sid) == "pending"


def test_upgrade_rejects_non_periodic_and_repeat(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    one_off = store.add("一次性", after=60)
    grant = delegate_ingress(issue_ingress("web"), entry="schedule_wake")
    with pytest.raises(ValueError, match="only periodic"):
        store.upgrade_to_standing(
            one_off, grant=grant, session_id="s1", fires=3,
            expires_at=time.time() + 86400, external=False, workdir=WORKDIR,
        )
    periodic = store.add("周期", after=0, repeat_interval=3600)
    store.upgrade_to_standing(
        periodic, grant=grant, session_id="s1", fires=3,
        expires_at=time.time() + 86400, external=False, workdir=WORKDIR,
    )
    with pytest.raises(ValueError, match="already has a wake grant"):
        store.upgrade_to_standing(
            periodic, grant=grant, session_id="s1", fires=3,
            expires_at=time.time() + 86400, external=False, workdir=WORKDIR,
        )


def test_upgrade_with_bad_grant_leaves_entry_unchanged(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    sid = store.add("周期", after=0, repeat_interval=3600)
    with pytest.raises(ValueError, match="standing grant rejected"):
        store.upgrade_to_standing(
            sid, grant=object(), session_id="s1", fires=3,
            expires_at=time.time() + 86400, external=False, workdir=WORKDIR,
        )
    row = _row(store, sid)
    assert row.get("task_mode", "") == "" and row["wake"] is False
    assert store.authority_state(sid) == "missing"


def test_upgrade_tool_rejects_delegated_ingress(tmp_path):
    from llm_loop.core.run_context import current_session_id
    from llm_loop.core.trace_leak.ingress_token import (
        current_ingress_session_id,
        current_ingress_token,
    )
    from llm_loop.tools.builtin.schedule import ScheduleUpgradeTool

    store = ScheduleStore(tmp_path / "schedule.json")
    sid = store.add("周期", after=0, repeat_interval=3600)
    tool = ScheduleUpgradeTool(store=store)
    delegated = delegate_ingress(issue_ingress("web"), entry="schedule_wake")
    tok = current_ingress_token.set(delegated)
    sid_ctx = current_session_id.set("s")
    ing_ctx = current_ingress_session_id.set("s")
    try:
        result = tool.execute(sid=sid, wake_fires=3, wake_expires_in_days=30)
    finally:
        current_ingress_session_id.reset(ing_ctx)
        current_session_id.reset(sid_ctx)
        current_ingress_token.reset(tok)
    assert result.status.value == "unauthorized"
    assert store.list()[0].get("wake") is not True

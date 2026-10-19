"""常驻授权（task_recurring）：创建时授权 N 次，每次到点开新会话执行.

设计：docs/design/DESIGN-20261019-scheduled-task-authorization-v1.md
事故背景：周期条目只能建成 notify，到点不产生 run；08:00 班次静默空转。
"""

from __future__ import annotations

import json
import time

from llm_loop.core.run_context import current_session_id
from llm_loop.core.schedule_delivery import ScheduleWakeDelivery
from llm_loop.core.scheduler import WAKE_DEFERRED, ScheduleStore
from llm_loop.core.trace_leak.ingress_token import (
    current_ingress_session_id,
    current_ingress_token,
    delegate_ingress,
    issue_ingress,
    issue_test_ingress,
)
from llm_loop.tools.builtin.schedule import ScheduleTool


class AdmittingRunner:
    enabled = True

    def __init__(self) -> None:
        self.sessions: list[str] = []
        self.prompts: list[str] = []
        self.busy: set[str] = set()

    def start(self, sid, prompt, **kwargs):
        self.sessions.append(sid)
        self.prompts.append(prompt)
        kwargs["before_start"](type("S", (), {"session_id": sid})())
        kwargs["terminal_callback"]("completed", None)
        return object(), None

    def is_running(self, sid) -> bool:
        return sid in self.busy

    def is_sync_active(self, _sid) -> bool:
        return False


def _inbox_files(tmp_path) -> list[dict]:
    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    files = sorted(inbox.glob("*.json")) if inbox.exists() else []
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def _force_due(store: ScheduleStore, sid: str) -> None:
    now = time.time()
    store._mutate(
        lambda entries: (
            setattr(entries[sid], "trigger_at", now),
            setattr(entries[sid], "scheduled_trigger_at", now),
        )
    )


def _standing(tmp_path, *, fires: int = 3, expires_at: float | None = None, new_session=None):
    store = ScheduleStore(tmp_path / "schedule.json")
    if expires_at is None:
        expires_at = time.time() + 30 * 86400
    grant = delegate_ingress(issue_ingress("web"), entry="schedule_wake")
    sid = store.add(
        "推进 RSI 复盘并给出下一步",
        after=0,
        repeat_interval=3600,
        task_mode="task_recurring",
        wake_fires=fires,
        wake_expires_at=expires_at,
        session_id="parent-sess",
        wake_grant=grant,
        wake_workdir=tmp_path.as_posix(),
    )
    runner = AdmittingRunner()
    delivery = ScheduleWakeDelivery(
        store, runner, data_dir=str(tmp_path),
        record_action=lambda *args: None,
        new_session=new_session if new_session is not None else (lambda: "child-1"),
    )
    entry = store.claim_due("owner")[0]
    return store, sid, entry, runner, delivery


def test_creation_persists_mode_quota_and_new_session_dispatch(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    tool = ScheduleTool(store=store)
    sid_tok = current_session_id.set("sess-human")
    ing_tok = current_ingress_token.set(issue_ingress("web"))
    ing_sid = current_ingress_session_id.set("sess-human")
    try:
        result = tool.execute(
            message="每日 08:00 推广",
            after=60,
            repeat_interval=86400,
            task_mode="task_recurring",
            wake_fires=3,
            wake_expires_in_days=30,
            wake_external=True,
        )
    finally:
        current_ingress_session_id.reset(ing_sid)
        current_ingress_token.reset(ing_tok)
        current_session_id.reset(sid_tok)

    assert result.status.value == "success", result.content
    row = store.list()[0]
    assert row["task_mode"] == "task_recurring"
    assert row["wake"] is True
    assert row["wake_fires_total"] == 3
    assert row["max_count"] == 3
    assert row["wake_dispatch"] == "new_session"
    assert row["wake_external"] is True
    assert row["wake_expires_at"] > time.time()
    assert store.authority_state(row["sid"]) == "pending"
    assert "开新会话执行" in result.content


def test_recurring_without_human_ingress_is_unauthorized(tmp_path):
    tool = ScheduleTool(store=ScheduleStore(tmp_path / "schedule.json"))
    result = tool.execute(
        message="x", after=60, repeat_interval=86400,
        task_mode="task_recurring", wake_fires=3,
    )
    assert result.status.value == "unauthorized"
    assert tool._store.list() == []


def test_recurring_requires_quota(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    tool = ScheduleTool(store=store)
    tok = current_ingress_token.set(issue_test_ingress())
    try:
        result = tool.execute(
            message="x", after=60, repeat_interval=86400,
            task_mode="task_recurring", wake_fires=0,
        )
    finally:
        current_ingress_token.reset(tok)
    assert result.status.value == "failure"
    assert "wake_fires" in result.content
    assert store.list() == []


def test_first_fire_runs_in_new_session_and_spends_one_credit(tmp_path):
    store, sid, entry, runner, delivery = _standing(tmp_path)
    anchor = entry.scheduled_trigger_at
    assert delivery(entry) is WAKE_DEFERRED
    assert runner.sessions == ["child-1"]
    prompt = runner.prompts[0]
    assert "常驻授权" in prompt and "不是新的真人输入" in prompt
    assert "推进 RSI 复盘" in prompt
    row = store.list()[0]
    assert row["count"] == 1
    assert row["wake_fires_used"] == 1
    assert row["wake_child_session_id"] == "child-1"
    assert row["wake_started_at"] == 0  # 已重置，供下一周期
    # 锚定推进：下一次 = 计划时刻 + 间隔，不是 now + 间隔
    assert row["scheduled_trigger_at"] == anchor + 3600
    assert store.authority_state(sid) == "pending"


def test_quota_exhaustion_revokes_and_removes_entry(tmp_path):
    store, sid, entry, runner, delivery = _standing(tmp_path, fires=2)
    assert delivery(entry) is WAKE_DEFERRED
    _force_due(store, sid)
    second = store.claim_due("owner")[0]
    assert delivery(second) is WAKE_DEFERRED
    assert runner.sessions == ["child-1", "child-1"]
    assert store.list() == []
    # 条目终结后 authority_state 无法按 sid 解析（条目已移除），账本记录已 revoke
    assert store.authority_state(sid) == "missing"


def test_expired_or_exhausted_grant_degrades_to_notify(tmp_path):
    store, sid, entry, runner, delivery = _standing(tmp_path, fires=2)
    # 账本额度耗尽（权威计数），条目镜像可能滞后——投递只看账本
    store._authority.consume(store.list()[0])
    store._authority.consume(store.list()[0])
    assert store.authority_state(sid) == "consumed"
    assert delivery(entry) is True
    assert runner.sessions == []  # 不启动 run
    assert [m["topic"] for m in _inbox_files(tmp_path)] == ["notify"]
    assert "常驻授权额度" in _inbox_files(tmp_path)[0]["body"]


def test_new_session_unavailable_defers_without_spending_credit(tmp_path):
    store, sid, entry, runner, delivery = _standing(tmp_path, new_session=lambda: "")
    assert delivery(entry) is WAKE_DEFERRED
    row = store.list()[0]
    assert row["wake_started_at"] == 0
    assert row["wake_fires_used"] == 0
    assert store.authority_state(sid) == "pending"
    assert runner.sessions == []


def test_scope_ignores_moving_anchor_between_fires(tmp_path):
    store, sid, entry, runner, delivery = _standing(tmp_path, fires=3)
    assert delivery(entry) is WAKE_DEFERRED
    row = store.list()[0]
    assert row["scheduled_trigger_at"] != entry.scheduled_trigger_at
    # 签名范围不含 moving anchor，否则第二次起全部 invalid
    assert store.authority_state(sid) == "pending"


def test_previous_fire_still_running_defers_without_double_spend(tmp_path):
    store, sid, entry, runner, delivery = _standing(tmp_path, fires=3)
    assert delivery(entry) is WAKE_DEFERRED
    runner.busy.add("child-1")
    _force_due(store, sid)
    second = store.claim_due("owner")[0]
    assert delivery(second) is WAKE_DEFERRED
    assert runner.sessions == ["child-1"]  # 没有并发第二次
    row = store.list()[0]
    assert row["wake_fires_used"] == 1
    assert store.authority_state(sid) == "pending"


def test_reissue_standing_preserves_consumed_quota(tmp_path):
    store, sid, entry, runner, delivery = _standing(tmp_path, fires=3)
    assert delivery(entry) is WAKE_DEFERRED
    row = store.list()[0]
    grant = store.wake_grant(sid)
    assert grant is not None
    assert store._authority.issue(row, grant) is True
    assert store.authority_state(sid) == "pending"
    assert store._authority._read()[sid]["fires_used"] == 1


def test_prompt_carries_effect_id_and_no_replay_instruction(tmp_path):
    store, sid, entry, runner, delivery = _standing(tmp_path)
    assert delivery(entry) is WAKE_DEFERRED
    prompt = runner.prompts[0]
    assert f"effect_id=schedule:{sid}:1" in prompt
    assert "不要重复执行" in prompt


def test_workdir_mismatch_degrades_instead_of_running(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    grant = delegate_ingress(issue_ingress("web"), entry="schedule_wake")
    store.add(
        "x", after=0, repeat_interval=3600, task_mode="task_recurring",
        wake_fires=2, wake_expires_at=time.time() + 86400,
        session_id="p", wake_grant=grant, wake_workdir="/tmp/some/other/root",
    )
    runner = AdmittingRunner()
    delivery = ScheduleWakeDelivery(
        store, runner, data_dir=str(tmp_path), record_action=lambda *a: None,
        new_session=lambda: "child-x", workspace_root=tmp_path.as_posix(),
    )
    entry = store.claim_due("owner")[0]
    assert delivery(entry) is True
    assert runner.sessions == []
    assert "工作目录与授权时不一致" in json.dumps(_inbox_files(tmp_path), ensure_ascii=False)


def test_consume_is_idempotent_for_same_occurrence(tmp_path):
    store, sid, entry, runner, delivery = _standing(tmp_path, fires=3)
    row = store.list()[0]
    assert store._authority.consume(row, occurrence=1) == 1
    assert store._authority.consume(row, occurrence=1) == 1  # 同一 fire 重试不重复扣
    assert store._authority.consume(row, occurrence=2) == 2


def test_delegated_ingress_cannot_create_standing_task(tmp_path):
    tool = ScheduleTool(store=ScheduleStore(tmp_path / "schedule.json"))
    human = issue_ingress("web")
    delegated = delegate_ingress(human, entry="schedule_wake")
    tok = current_ingress_token.set(delegated)
    sid_ctx = current_session_id.set("s")
    ing_ctx = current_ingress_session_id.set("s")
    try:
        result = tool.execute(
            message="x", after=60, repeat_interval=86400,
            task_mode="task_recurring", wake_fires=3,
        )
    finally:
        current_ingress_session_id.reset(ing_ctx)
        current_session_id.reset(sid_ctx)
        current_ingress_token.reset(tok)
    assert result.status.value == "unauthorized"


def test_next_anchor_grace_and_skip():
    from llm_loop.core.schedule_task_grant import next_anchor

    t0 = 1_000_000.0
    assert next_anchor(t0, 86400, t0 + 60) == t0 + 86400  # 未到点：顺延
    assert next_anchor(t0, 86400, t0 + 86400 + 3600) == t0 + 86400 + 3600  # 宽限内：补一次
    skipped = next_anchor(t0, 86400, t0 + 3 * 86400 + 60)  # 错过多个周期：跳到未来
    assert skipped > t0 + 3 * 86400
    assert (skipped - (t0 + 86400)) % 86400 == 0

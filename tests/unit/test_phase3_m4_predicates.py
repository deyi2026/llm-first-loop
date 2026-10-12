"""Phase3 M4（G4）：事件谓词唤醒——超时/事件双通道竞速.

8a 事件先到：谓词满足即 claim（早于 trigger_at），event_won=event，恰一次唤醒；
8b 超时先到：trigger_at 到点正常 claim，event_won=timeout；条目消费后事件后到
   不会造成二次唤醒（armed 已即焚/条目已删）；
8c 同 tick 双真：claim 循环内事件分支先判定（确定性取胜），恰一次。
竞速判定= flock 内字段翻转（CAS 语义），不比较墙钟（D3）。
"""
from __future__ import annotations

import pytest

from llm_loop.core.scheduler import (
    EVENT_PREDICATE_KINDS,
    ScheduleStore,
    register_event_predicate,
)


def _store(tmp_path):
    return ScheduleStore(str(tmp_path / "sched.json"))


def _entry(store, sid):
    for d in store.list():
        if d["sid"] == sid:
            return d
    return None


# ── 8a：事件先于超时 ───────────────────────────────────────────────
def test_8a_event_wins_before_timeout(tmp_path):
    store = _store(tmp_path)
    satisfied = {"v": False}
    register_event_predicate("job_terminal", lambda ref: satisfied["v"])
    sid = store.add(
        "任务完成即唤醒", after=3600, wake=True, wake_grant=object(),
        event_predicate="job_terminal", predicate_ref="job-x",
    )
    assert _entry(store, sid)["armed"] is True

    satisfied["v"] = True  # 事件先到（远早于 3600s 超时）
    claimed = store.claim_due("owner-a")
    assert [e.sid for e in claimed] == [sid]
    d = _entry(store, sid)
    assert d["event_won"] == "event"
    assert d["armed"] is False
    assert d["event_fired_at"] > 0
    # 一次性即焚：消费前重放谓词也不二次 claim（armed=False 挡住事件分支）
    satisfied["v"] = False
    assert store.claim_due("owner-b") == []
    store.mark_triggered(sid, owner="owner-a")  # 一次性条目：成功 ack 后删除
    satisfied["v"] = True  # 消费后事件再翻转
    assert _entry(store, sid) is None  # 无对象可二次唤醒
    assert store.claim_due("owner-c") == []


# ── 8b：超时先到，事件后到只记录 ───────────────────────────────────
def test_8b_timeout_wins_event_late(tmp_path):
    store = _store(tmp_path)
    satisfied = {"v": False}
    register_event_predicate("job_terminal", lambda ref: satisfied["v"])
    sid = store.add(
        "兜底唤醒", after=0, wake=True, wake_grant=object(),
        event_predicate="job_terminal", predicate_ref="job-y",
    )
    claimed = store.claim_due("owner-a")  # after=0 → 超时分支立即到点
    assert [e.sid for e in claimed] == [sid]
    d = _entry(store, sid)
    assert d["event_won"] == "timeout"
    assert d["armed"] is False  # 即焚：事件后到不重放
    store.mark_triggered(sid, owner="owner-a")
    satisfied["v"] = True  # 事件迟到
    assert store.claim_due("owner-b") == []  # 无二次唤醒
    assert _entry(store, sid) is None


# ── 8c：同 tick 双通道同时为真 → 事件分支确定性取胜 ─────────────────
def test_8c_simultaneous_event_branch_deterministic(tmp_path):
    store = _store(tmp_path)
    register_event_predicate("job_terminal", lambda ref: True)  # 谓词恒真
    sid = store.add(
        "双真", after=0, wake=True, wake_grant=object(),
        event_predicate="job_terminal", predicate_ref="job-z",
    )
    claimed = store.claim_due("owner-a")
    assert len(claimed) == 1
    # claim 循环先判事件分支（分支次序确定性，非墙钟）：after=0 且谓词真 → event 取胜
    d = _entry(store, sid)
    assert d["event_won"] == "event"
    assert d["armed"] is False


# ── 闭集与授权约束（D8 配套）───────────────────────────────────────
def test_closed_set_and_authorization_guards(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        register_event_predicate("evil_kind", lambda ref: True)
    with pytest.raises(ValueError):
        store.add("x", after=1, wake=True, wake_grant=object(),
                  event_predicate="evil_kind", predicate_ref="r")
    with pytest.raises(ValueError):  # D8：无 wake（无授权链）一律拒绝
        store.add("x", after=1, event_predicate="job_terminal", predicate_ref="r")
    with pytest.raises(ValueError):  # 周期条目拒绝（armed 一次性）
        store.add("x", after=1, repeat_interval=5, wake=True, wake_grant=object(),
                  event_predicate="job_terminal", predicate_ref="r")
    assert {
        "job_terminal", "generation_reached", "action_settled",
    } == EVENT_PREDICATE_KINDS


def test_roundtrip_and_regression_shape(tmp_path):
    """谓词字段持久化往返；不带谓词的老条目形态与现状逐字一致（回归项）。"""
    store = _store(tmp_path)
    register_event_predicate("job_terminal", lambda ref: False)
    sid = store.add(
        "往返", after=60, wake=True, wake_grant=object(),
        event_predicate="job_terminal", predicate_ref="job-q",
    )
    d = _entry(store, sid)
    assert d["event_predicate"] == "job_terminal"
    assert d["armed"] is True and d["predicate_ref"] == "job-q"
    # 老形态：无谓词条目不含谓词键（快照零变化）
    sid2 = store.add("普通提醒", after=5)
    d2 = _entry(store, sid2)
    assert "event_predicate" not in d2 and "armed" not in d2
    # 未登记求值器的 kind fail-safe 回退超时分支（不抛异常、不提前 claim）
    store.add(
        "回退", after=9999, wake=True, wake_grant=object(),
        event_predicate="generation_reached", predicate_ref="7",
    )
    assert store.claim_due("owner") == []


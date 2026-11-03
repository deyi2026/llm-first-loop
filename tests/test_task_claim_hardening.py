"""claim 层加固回归：2026-11-03 独立审查（P1×1 / P2×7）的逐条对应测试.

每条测试绑定一个具体 finding，证明的是**行为**，不是实现细节：

- P1-1  跨会话写入 claim 的入口门（claim_task 工具层）
- P2-1  过期 claim 的 reclaim 不得跳过 task 状态检查
- P2-2  无身份且无 token 的 release 被拒
- P2-4  policy_from_env 与 config.py 的 clamp/回落语义一致
- P2-5  frontier last_activity 按时刻比较，不按字符串
- P2-6  组合入口必须显式 authorized=True
- P2-7  token 路径的 renew 行只在 store.update 成功后落账
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from llm_loop.core.run_context import current_session_id
from llm_loop.introspection import task_claim as tc
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_claim import ClaimRefusedError, ClaimStore
from llm_loop.introspection.task_store import TaskStore
from llm_loop.introspection.tools_task import run_claim_task


@pytest.fixture()
def audit(tmp_path):
    return str(tmp_path / "audit")


@pytest.fixture()
def store(audit):
    return TaskStore(audit)


@pytest.fixture()
def task(store):
    return store.create("GOAL-1", "任务 A", acceptance=["可验收"])


def _claim_rows(audit):
    path = ClaimStore(audit).ledger_path("GOAL-1")
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ------------------------------------------------------------ P1-1


def test_claim_task_from_foreign_session_is_refused(tmp_path, monkeypatch):
    """goal 归属 owner 会话时，另一个会话的 claim_task 必须被拒且不留 claim。"""
    audit = str(tmp_path / "audit")
    monkeypatch.setenv("LFL_AUDIT_DIR", audit)
    owner = "session-owner"
    token = current_session_id.set(owner)
    try:
        goal = GoalStore(audit).create("归属测试", session_id=owner)
        task = TaskStore(audit).create(goal.id, "任务 A", acceptance=["可验收"])
    finally:
        current_session_id.reset(token)

    intruder = current_session_id.set("session-intruder")
    try:
        res = run_claim_task(
            SimpleNamespace(),
            SimpleNamespace(audit_dir=audit),
            {"goal_id": goal.id, "task_id": task.task_id},
        )
    finally:
        current_session_id.reset(intruder)

    assert res.status.name == "FAILURE"
    assert ClaimStore(audit).current(goal.id, task.task_id) is None


# ------------------------------------------------------------ P2-1


def test_reclaim_of_expired_claim_still_checks_task_status(audit, store, task):
    """旧 claim 过期不等于可以 claim 一个已 done 的任务。"""
    cs = ClaimStore(audit, policy=tc.ClaimPolicy(ttl_s=1))
    cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    store.update("GOAL-1", task.task_id, status="in_progress")
    store.update("GOAL-1", task.task_id, status="done")
    time.sleep(1.2)  # 让 claim 过期，但不做 released（走 reclaim 分支）

    with pytest.raises(ClaimRefusedError) as exc:
        cs.grant("GOAL-1", task.task_id, holder="run-b", store=store)
    assert exc.value.code == "task_not_claimable"


# ------------------------------------------------------------ P2-2


def test_release_without_holder_or_token_is_refused(audit, store, task):
    cs = ClaimStore(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    before = cs.current("GOAL-1", task.task_id)
    assert before is not None and before.claim_id == claim.claim_id

    # 测试进程内 write_holder() 返回 None（无 run 身份），且不传 token
    with pytest.raises(ClaimRefusedError) as exc:
        cs.release("GOAL-1", task.task_id)
    assert exc.value.code == "holder_unavailable"
    assert cs.current("GOAL-1", task.task_id) is not None


# ------------------------------------------------------------ P2-4


def test_policy_from_env_clamps_like_config(monkeypatch):
    monkeypatch.setenv("LFL_CLAIM_TTL_S", "1")
    monkeypatch.setenv("LFL_CLAIM_MAX_TTL_S", "2")
    monkeypatch.setenv("LFL_CLAIM_MAX_PER_HOLDER", "0")
    monkeypatch.setenv("LFL_CLAIM_ENFORCEMENT", "bogus")
    policy = tc.policy_from_env()
    assert policy.ttl_s == 60
    assert policy.max_ttl_s == 60
    assert policy.max_per_holder == 1
    assert policy.enforcement == "warn"  # 未知值回落到最保守的可观测档


# ------------------------------------------------------------ P2-5


def test_frontier_last_activity_compares_instants_not_strings(audit, store):
    """02:00Z 晚于 09:00+08:00(=01:00Z)，但字符串序相反。"""
    a = store.create("GOAL-1", "任务 A", acceptance=["x"])
    b = store.create("GOAL-1", "任务 B", acceptance=["x"])
    path = store._path("GOAL-1")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        if row["task_id"] == a.task_id:
            row["updated_at"] = "2026-11-03T02:00:00+00:00"
        elif row["task_id"] == b.task_id:
            row["updated_at"] = "2026-11-03T09:00:00+08:00"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )

    frontier = store.compute_frontier("GOAL-1")
    assert frontier["last_activity"] == "2026-11-03T02:00:00+00:00"
    # 朴素 now_ts 与带偏移的 updated_at 相减不得抛 TypeError
    store.compute_frontier("GOAL-1", now_ts="2026-11-03T11:00:00")


# ------------------------------------------------------------ P2-6


def test_under_claim_requires_explicit_authorization(audit, store, task):
    cs = ClaimStore(audit)
    with pytest.raises(ValueError):
        cs.update_task_under_claim(store, "GOAL-1", task.task_id, note="无授权调用")


# ------------------------------------------------------------ P2-7


def test_renew_row_written_only_after_update_succeeds(audit, store, task):
    """pending→done 非法：update 抛错时账本不得留下 renew 行。"""
    cs = ClaimStore(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    before = len(_claim_rows(audit))

    with pytest.raises(ValueError):  # pending → done 是非法转移（task_store 抛 ValueError）
        cs.update_task_under_claim(
            store,
            "GOAL-1",
            task.task_id,
            token=claim.token,
            authorized=True,
            status="done",
        )

    rows = _claim_rows(audit)[before:]
    assert [r for r in rows if r.get("action") == "renew"] == []


# ------------------------------------------------------------ P2-3


def test_fanout_event_uses_deny_own_scope():
    """拒绝事件的 running_before 必须与被拒口径一致，不再混用全局 handle 数。"""
    from llm_loop.subagent.runner import _fanout_observation, _ReserveDenied

    assert _fanout_observation(_ReserveDenied("parent_concurrency", 3, 4), 9, 32) == (3, 4)
    assert _fanout_observation(_ReserveDenied("handle_capacity", 32, 32), 32, 32) == (32, 32)
    assert _fanout_observation(None, 5, 32) == (5, 32)


# ------------------------------------------------ 第二轮审查（P2×6）对应


# ------------------------------------------------------------ P2-1（续租降级）


def test_renew_ledger_failure_reports_success_with_degraded_note(audit, store, task, monkeypatch):
    """task 已落笔、续租落账失败 → 回执必须是成功 + 降级标注（不能报 FAILURE）。"""
    cs = ClaimStore(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)

    def _boom(_claim):
        raise tc.ClaimLedgerUnavailableError("ledger_unavailable", "disk full (simulated)")

    monkeypatch.setattr(cs, "_append", _boom)
    updated, notes = cs.update_task_under_claim(
        store, "GOAL-1", task.task_id, token=claim.token, authorized=True, status="in_progress"
    )
    assert updated.status == "in_progress"          # 写入确实生效了
    assert notes.get("claim_renew_unavailable") == "ledger_unavailable"


def test_renew_ledger_failure_does_not_emit_renew_row(audit, store, task, monkeypatch):
    """失败分支不得留下 renew 行（账本与事件的 1:1 保持单向：事件可多于账本行）。"""
    cs = ClaimStore(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    before = len(_claim_rows(audit))

    def _boom(_claim):
        raise tc.ClaimLedgerUnavailableError("ledger_unavailable", "disk full (simulated)")

    monkeypatch.setattr(cs, "_append", _boom)
    cs.update_task_under_claim(
        store, "GOAL-1", task.task_id, token=claim.token, authorized=True, status="in_progress"
    )
    assert [r for r in _claim_rows(audit)[before:] if r.get("action") == "renew"] == []


# ------------------------------------------------------------ P2-2（屏蔽 holder）


def test_conflict_message_masks_other_holder(audit, store, task):
    """他人持有时，回执/异常里只能出现屏蔽后的 sid。"""
    cs = ClaimStore(audit)
    long_sid = "session-0123456789abcdef"
    cs.grant("GOAL-1", task.task_id, holder=long_sid, store=store)

    with pytest.raises(ClaimRefusedError) as exc:
        cs.grant("GOAL-1", task.task_id, holder="run-b", store=store)
    assert long_sid not in str(exc.value)
    assert tc.mask_holder(long_sid) in str(exc.value)


def test_conflict_warning_is_masked_on_write_path(audit, store, task):
    """warn 模式下无 token 的冲突写入：note 里是屏蔽值，不是完整 sid。"""
    long_sid = "session-0123456789abcdef"
    ClaimStore(audit).grant("GOAL-1", task.task_id, holder=long_sid, store=store)

    token = current_session_id.set("session-writer-bbbb")
    try:
        _updated, notes = ClaimStore(audit).update_task_under_claim(
            store, "GOAL-1", task.task_id, authorized=True, status="in_progress"
        )
    finally:
        current_session_id.reset(token)

    assert notes["claim_conflict_warning"] == tc.mask_holder(long_sid)


# ------------------------------------------------------------ P2-6（enforce 分支）


def test_enforce_mode_hard_denies_foreign_holder_write(audit, store, task):
    """enforce：他人持 claim 时，无 token 的写入被硬拒且任务状态不变。"""
    cs = ClaimStore(audit, policy=tc.ClaimPolicy(enforcement="enforce"))
    cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)

    token = current_session_id.set("run-b")
    try:
        with pytest.raises(ClaimRefusedError) as exc:
            cs.update_task_under_claim(
                store, "GOAL-1", task.task_id, authorized=True, status="in_progress"
            )
    finally:
        current_session_id.reset(token)

    assert exc.value.code == "claim_held_by_other"
    assert store.get("GOAL-1", task.task_id).status == "pending"


def test_enforce_mode_allows_holder_with_token(audit, store, task):
    """enforce 不是"谁来都拒"：合法持有者带 token 的写入必须成功。"""
    cs = ClaimStore(audit, policy=tc.ClaimPolicy(enforcement="enforce"))
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)

    token = current_session_id.set("run-a")
    try:
        updated, notes = cs.update_task_under_claim(
            store, "GOAL-1", task.task_id, token=claim.token, authorized=True, status="in_progress"
        )
    finally:
        current_session_id.reset(token)

    assert updated.status == "in_progress"
    assert notes.get("claim_renewed") is True

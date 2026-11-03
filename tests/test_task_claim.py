"""PR-1 claim 层验收（DESIGN-20261103 §11.1 T-1.1…T-1.9 / §11.4 G1–G6/G8–G11）.

覆盖的是**机械事实**：谁能拿 claim、过期后谁能接管、旧 token 会不会被挡住、
claim 与 task 写入是否同一临界区、账本坏了会不会静默放行。
"""

from __future__ import annotations

import contextlib
import json
import threading
from pathlib import Path

import pytest

from llm_loop.introspection import task_claim as tc
from llm_loop.introspection.task_claim import (
    ClaimLedgerUnavailableError,
    ClaimRefusedError,
    ClaimStore,
    overlapping_paths,
)
from llm_loop.introspection.task_store import TaskStore, safe_goal_id


@pytest.fixture()
def audit(tmp_path):
    return str(tmp_path / "audit")


@pytest.fixture()
def store(audit):
    return TaskStore(audit)


@pytest.fixture()
def task(store):
    return store.create("GOAL-1", "任务 A", acceptance=["可验收"])


def _claims(audit):
    return ClaimStore(audit)


# ---------------------------------------------------------------- T-1.1


def test_grant_then_same_holder_is_idempotent(audit, store, task):
    cs = _claims(audit)
    first = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    second = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    assert first.claim_id == second.claim_id
    assert second.generation == 1
    assert second.is_active(tc.now_ms())


def test_other_holder_cannot_claim_active_task(audit, store, task):
    cs = _claims(audit)
    cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    with pytest.raises(ClaimRefusedError) as exc:
        cs.grant("GOAL-1", task.task_id, holder="run-b", store=store)
    assert exc.value.code == "task_claimed_by_other"


def test_expired_claim_is_reclaimed_and_generation_advances(audit, store, task):
    cs = _claims(audit)
    first = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    real = tc.now_ms
    tc.now_ms = lambda: real() + 3_600_000
    try:
        assert cs.current("GOAL-1", task.task_id).is_active(tc.now_ms()) is False
        second = cs.grant("GOAL-1", task.task_id, holder="run-b", store=store)
    finally:
        tc.now_ms = real
    assert second.generation == first.generation + 1
    assert second.claim_id != first.claim_id


def test_stale_token_is_refused_after_takeover(audit, store, task):
    """fencing 的核心：旧 owner 的迟到写入必须被挡住，而不是静默覆盖."""
    cs = _claims(audit)
    old = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    real = tc.now_ms
    tc.now_ms = lambda: real() + 3_600_000
    try:
        cs.grant("GOAL-1", task.task_id, holder="run-b", store=store)
        with pytest.raises(ClaimRefusedError) as exc:
            cs.update_task_under_claim(
                store, "GOAL-1", task.task_id, token=old.token, holder="run-a", status="in_progress"
            , authorized=True)
    finally:
        tc.now_ms = real
    assert exc.value.code == "claim_generation_stale"
    assert store.get("GOAL-1", task.task_id).status == "pending"


def test_token_holder_mismatch_is_refused(audit, store, task):
    cs = _claims(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    with pytest.raises(ClaimRefusedError) as exc:
        cs.update_task_under_claim(
            store, "GOAL-1", task.task_id, token=claim.token, holder="run-b", status="in_progress"
        , authorized=True)
    assert exc.value.code == "claim_holder_mismatch"


def test_unbounded_requires_authorization(audit, store, task):
    cs = _claims(audit)
    with pytest.raises(ClaimRefusedError) as exc:
        cs.grant("GOAL-1", task.task_id, holder="run-a", unbounded=True, store=store)
    assert exc.value.code == "claim_ttl_out_of_range"


def test_ttl_is_clamped_not_rejected(audit, store, task):
    cs = _claims(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", ttl_s=1, store=store)
    remaining = claim.expires_ms - tc.now_ms()
    assert remaining >= (tc.MIN_TTL_S - 1) * 1000


def test_invalid_ttl_is_refused(audit, store, task):
    cs = _claims(audit)
    with pytest.raises(ClaimRefusedError) as exc:
        cs.grant("GOAL-1", task.task_id, holder="run-a", ttl_s=0, store=store)
    assert exc.value.code == "ttl_invalid"


def test_quota_is_warning_not_refusal(audit, store, task):
    """§6.5：max_claims_per_holder 是软指标——铺得开就记警告，但别让任务失败."""
    cs = _claims(audit)
    for i in range(cs.policy.max_per_holder):
        t = store.create("GOAL-1", f"批量 {i}", acceptance=["a"])
        cs.grant("GOAL-1", t.task_id, holder="run-a", store=store)
    extra = store.create("GOAL-1", "第 N 条", acceptance=["a"])
    claim = cs.grant("GOAL-1", extra.task_id, holder="run-a", store=store)
    assert claim.is_active(tc.now_ms())
    events = _events(audit)
    assert any(e.get("reason_code") == "claim_quota_exceeded_warning" for e in events)


# ---------------------------------------------------------------- T-1.2 工具语义


def test_renew_keeps_generation_and_extends(audit, store, task):
    cs = _claims(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    renewed = cs.renew("GOAL-1", task.task_id, token=claim.token, holder="run-a")
    assert renewed.generation == claim.generation
    assert renewed.expires_ms >= claim.expires_ms


def test_renew_after_expiry_is_allowed_when_not_taken_over(audit, store, task):
    """N2-A7/Q33：过期不是失权。未被接管时允许续期，回执标注 renewed_after_expiry."""
    cs = _claims(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    real = tc.now_ms
    tc.now_ms = lambda: real() + 3_600_000
    try:
        renewed = cs.renew("GOAL-1", task.task_id, token=claim.token, holder="run-a")
    finally:
        tc.now_ms = real
    assert renewed.renewed_after_expiry is True
    assert renewed.receipt(tc.now_ms())["renewed_after_expiry"] is True
    assert renewed.generation == claim.generation


def test_expired_but_not_taken_over_write_succeeds_and_renews(audit, store, task):
    """G4/N2-A15 软过期：过期 + generation 匹配 + 未撤销 → 写入成功并顺带续期."""
    cs = _claims(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    real = tc.now_ms
    tc.now_ms = lambda: real() + 3_600_000
    try:
        task_out, notes = cs.update_task_under_claim(
            store, "GOAL-1", task.task_id, token=claim.token, holder="run-a", status="in_progress"
        , authorized=True)
        renewed = cs.current("GOAL-1", task.task_id)
    finally:
        tc.now_ms = real
    assert task_out.status == "in_progress"
    assert notes.get("claim_expired_renewed") is True
    assert renewed.expires_ms > claim.expires_ms


def test_write_after_release_is_refused(audit, store, task):
    cs = _claims(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    cs.release("GOAL-1", task.task_id, token=claim.token, holder="run-a")
    with pytest.raises(ClaimRefusedError) as exc:
        cs.update_task_under_claim(
            store, "GOAL-1", task.task_id, token=claim.token, holder="run-a", status="in_progress"
        , authorized=True)
    assert exc.value.code == "claim_released"


def test_release_then_other_holder_can_take(audit, store, task):
    cs = _claims(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    assert cs.release("GOAL-1", task.task_id, token=claim.token, holder="run-a") is True
    other = cs.grant("GOAL-1", task.task_id, holder="run-b", store=store)
    assert other.holder == "run-b"


def test_release_without_active_claim_is_noop(audit, store, task):
    assert _claims(audit).release("GOAL-1", task.task_id, holder="run-a") is False


# ---------------------------------------------------------------- T-1.3 / T-1.4 / T-1.5


def test_update_with_token_writes_and_renews_in_one_critical_section(audit, store, task):
    cs = _claims(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    task_out, notes = cs.update_task_under_claim(
        store, "GOAL-1", task.task_id, token=claim.token, holder="run-a", status="in_progress"
    , authorized=True)
    assert task_out.status == "in_progress"
    assert notes.get("claim_renewed") is True
    assert store.get("GOAL-1", task.task_id).status == "in_progress"


def test_implicit_claim_on_pending_to_in_progress(audit, store, task):
    cs = _claims(audit)
    _, notes = cs.update_task_under_claim(store, "GOAL-1", task.task_id, holder="run-c", status="in_progress", authorized=True)
    assert notes.get("auto_claimed")
    assert cs.current("GOAL-1", task.task_id).holder == "run-c"


def test_write_without_token_warns_but_still_writes(audit, store, task):
    cs = _claims(audit)
    cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    task_out, notes = cs.update_task_under_claim(
        store, "GOAL-1", task.task_id, holder="run-b", title="改名"
    , authorized=True)
    assert task_out.title == "改名"
    assert notes.get("claim_conflict_warning") == "run-a"


def test_reopen_revokes_claim_before_writing(audit, store, task):
    cs = _claims(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    cs.update_task_under_claim(store, "GOAL-1", task.task_id, token=claim.token, holder="run-a", status="in_progress", authorized=True)
    cs.update_task_under_claim(store, "GOAL-1", task.task_id, token=claim.token, holder="run-a", status="done", authorized=True)
    task_out, notes = cs.update_task_under_claim(
        store, "GOAL-1", task.task_id, holder="run-a", status="in_progress", confirm=True
    , authorized=True)
    assert task_out.status == "in_progress"
    assert notes.get("revoked_claim_id")
    assert cs.current("GOAL-1", task.task_id).state == "revoked"


def test_revoke_failure_refuses_reopen(audit, store, task, monkeypatch):
    """§6.3：撤销失败必须拒绝重开——否则旧 owner 会带着有效 claim 回来."""
    cs = _claims(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    cs.update_task_under_claim(store, "GOAL-1", task.task_id, token=claim.token, holder="run-a", status="in_progress", authorized=True)
    cs.update_task_under_claim(store, "GOAL-1", task.task_id, token=claim.token, holder="run-a", status="done", authorized=True)

    def boom(_claim):
        raise ClaimLedgerUnavailableError("claim_ledger_unavailable", "模拟写失败")

    monkeypatch.setattr(ClaimStore, "_append", staticmethod(boom))
    with pytest.raises(ClaimLedgerUnavailableError):
        ClaimStore(audit).update_task_under_claim(
            store, "GOAL-1", task.task_id, holder="run-a", status="in_progress", confirm=True
        , authorized=True)
    assert store.get("GOAL-1", task.task_id).status == "done"


def test_claim_ledger_write_failure_denies_claim(audit, store, task, monkeypatch):
    def boom(_claim):
        raise ClaimLedgerUnavailableError("claim_ledger_unavailable", "模拟写失败")

    monkeypatch.setattr(ClaimStore, "_append", staticmethod(boom))
    with pytest.raises(ClaimLedgerUnavailableError):
        _claims(audit).grant("GOAL-1", task.task_id, holder="run-a", store=store)


def test_task_not_claimable_for_done_task(audit, store, task):
    cs = _claims(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    cs.update_task_under_claim(store, "GOAL-1", task.task_id, token=claim.token, holder="run-a", status="in_progress", authorized=True)
    cs.update_task_under_claim(store, "GOAL-1", task.task_id, token=claim.token, holder="run-a", status="done", authorized=True)
    with pytest.raises(ClaimRefusedError):
        cs.grant("GOAL-1", task.task_id, holder="run-b", store=store)


# ---------------------------------------------------------------- 存储韧性


def test_half_line_is_tolerated_and_claim_still_works(audit, store, task):
    cs = _claims(audit)
    cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    ledger = cs.ledger_path("GOAL-1")
    ledger.write_text(ledger.read_text() + '{"claim_id":"TRUNC', encoding="utf-8")
    fresh = ClaimStore(audit)
    assert fresh.current("GOAL-1", task.task_id) is not None
    assert fresh.bad_lines == 1
    assert fresh.grant("GOAL-1", task.task_id, holder="run-a", store=store) is not None


def test_ledger_compaction_keeps_current_state(audit, store, task, monkeypatch):
    monkeypatch.setattr(tc, "COMPACT_ROW_THRESHOLD", 3)
    cs = _claims(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    for _ in range(4):
        cs.renew("GOAL-1", task.task_id, token=claim.token, holder="run-a")
    lines = [ln for ln in cs.ledger_path("GOAL-1").read_text().splitlines() if ln.strip()]
    assert len(lines) <= 3
    assert ClaimStore(audit).current("GOAL-1", task.task_id).claim_id == claim.claim_id


def test_claim_and_task_use_same_safe_id(audit, store):
    """claim 账本与 task 账本必须落在**同一个归一化名字**上（T-1.7 的真断言）.

    2026-11-03 审查指出旧版本是空断言（`safe_goal_id(goal) and "/tmp"` 恒为 "/tmp"，
    从未比较两条路径），这里改为真的比较磁盘上的文件名。
    """
    goal = "GOAL/with:weird.chars"
    task = store.create(goal, "任务 A", acceptance=["可验收"])
    _claims(audit).grant(goal, task.task_id, holder="run-a", store=store)

    task_names = sorted(p.stem for p in (Path(audit) / "tasks").glob("*.jsonl"))
    claim_names = sorted(p.stem.removeprefix("claim-") for p in (Path(audit) / "claims").glob("claim-*.jsonl"))
    assert task_names == claim_names == [safe_goal_id(goal)]
    assert "/" not in safe_goal_id(goal)


def test_clock_regression_does_not_shrink_lease(audit, store, task):
    cs = _claims(audit)
    claim = cs.grant("GOAL-1", task.task_id, holder="run-a", store=store)
    real = tc.now_ms
    tc.now_ms = lambda: real() - 3_600_000  # 时钟回拨
    try:
        renewed = cs.renew("GOAL-1", task.task_id, token=claim.token, holder="run-a")
    finally:
        tc.now_ms = real
    assert renewed.expires_ms >= claim.expires_ms
    assert renewed.renewed_ms >= claim.renewed_ms


# ---------------------------------------------------------------- 并发与路径


def test_concurrent_claim_has_exactly_one_winner(audit, store, task):
    winners, losers = [], []

    def attempt(holder):
        try:
            winners.append(ClaimStore(audit).grant("GOAL-1", task.task_id, holder=holder, store=store))
        except ClaimRefusedError as exc:
            losers.append(exc.code)

    threads = [threading.Thread(target=attempt, args=(f"run-{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(winners) == 1
    assert len(losers) == 5


def test_path_overlap_detection():
    assert overlapping_paths(["src/a"], ["src/a/b.py"])
    assert not overlapping_paths(["src/a"], ["src/ab"])


# ---------------------------------------------------------------- 配置一致性


def test_policy_matches_config_defaults():
    """config.py 与 task_claim.policy_from_env 读同一批环境变量——两处默认值必须一致."""
    from llm_loop.config import ToolRuntimeSettings

    tr = ToolRuntimeSettings()
    policy = tc.ClaimPolicy()
    assert (tr.claim_ttl_s, tr.claim_max_ttl_s) == (policy.ttl_s, policy.max_ttl_s)
    assert tr.claim_enforcement == policy.enforcement
    assert tr.max_claims_per_holder == policy.max_per_holder
    assert tr.claim_allow_unbounded is policy.allow_unbounded


def test_claim_tools_are_registered():
    from llm_loop.introspection.tools_task import TASK_TOOL_DEFS

    names = {d["name"] for d in TASK_TOOL_DEFS}
    assert {"claim_task", "renew_task", "release_task"} <= names


def test_task_update_accepts_claim_token():
    from llm_loop.introspection.tools_task import TASK_UPDATE_TOOL_DEF

    assert "claim_token" in TASK_UPDATE_TOOL_DEF["parameters"]["properties"]


# ---------------------------------------------------------------- helpers


def _events(audit):
    path = ClaimStore(audit).ledger_path("GOAL-1").parent / "events.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            with contextlib.suppress(json.JSONDecodeError):
                out.append(json.loads(line))
    return out

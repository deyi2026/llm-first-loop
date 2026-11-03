"""T-0.6 埋点骨架：claims/events.jsonl 的写入语义与三条不变量（DESIGN-20261103 §6.6）."""

from __future__ import annotations

import json

import pytest

from llm_loop.introspection.claims import events as ev
from llm_loop.introspection.task_store import TaskStore


def _read_lines(audit_dir):
    path = ev.events_path(audit_dir)
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


@pytest.fixture()
def audit_dir(tmp_path):
    ev.reset_write_failures()
    d = tmp_path / "audit"
    d.mkdir()
    yield d
    ev.reset_write_failures()


def _store(audit_dir):
    """TaskStore 根 = 审计根：真实布局里 task 账本与 claims/ 同在 data/audit 下。"""
    return TaskStore(str(audit_dir))


def _seed(store, goal="GOAL-1"):
    task = store.create(goal, "任务标题", acceptance=["a"])
    return task.task_id


# ---------- 写入基本语义 ----------


def test_write_event_creates_one_line_with_schema(audit_dir):
    assert ev.write_event(audit_dir, "claim_decision", goal_id="G1", task_id="T1") is True
    rows = _read_lines(audit_dir)
    assert len(rows) == 1
    row = rows[0]
    assert row["v"] == ev.SCHEMA_VERSION
    assert row["kind"] == "claim_decision"
    assert row["goal_id"] == "G1"
    assert row["ts"]  # 有本地时间戳
    assert ev.write_failures(audit_dir) == 0


def test_write_event_creates_parent_dir_lazily(audit_dir):
    nested = audit_dir / "deeper"
    assert ev.write_event(nested, "fanout_decision", decision="allow") is True
    assert ev.events_path(nested).exists()


def test_long_string_fields_are_trimmed(audit_dir):
    assert ev.write_event(audit_dir, "fanout_decision", parent="p" * 500) is True
    row = _read_lines(audit_dir)[0]
    assert len(row["parent"]) <= ev.MAX_STR_FIELD
    assert row["parent"].endswith("…")


def test_oversized_line_is_rejected_and_counted(audit_dir):
    """行超 1KB 不写半条：宁缺一条事件，不写超长行（不变量 1 的代价明确）。"""
    payload = {f"f{i}": "x" * 90 for i in range(20)}
    assert ev.write_event(audit_dir, "fanout_decision", **payload) is False
    assert _read_lines(audit_dir) == []
    assert ev.write_failures(audit_dir) == 1


def test_write_failure_never_raises(audit_dir):
    """claims 路径被占用（无法建目录）→ 返回 False + 计数，绝不抛异常。"""
    (audit_dir / ev.CLAIMS_DIRNAME).write_text("not a dir", encoding="utf-8")
    assert ev.write_event(audit_dir, "claim_decision") is False
    assert ev.write_failures(audit_dir) == 1


# ---------- 不变量 3：分母残缺要看得见 ----------


def test_snapshot_reports_claims_metrics(audit_dir, tmp_path):
    ev.write_event(audit_dir, "claim_decision", goal_id="G1")

    from llm_loop.introspection.goal_coordination import _collect_claim_metrics

    block, notes = _collect_claim_metrics(str(audit_dir))
    assert block["claims_events"]["lines"] == 1
    assert block["claims_events"]["bytes"] > 0
    assert block["claim_event_write_failures"] == 0
    assert notes == []


def test_snapshot_flags_write_failures_in_degraded(audit_dir):
    from llm_loop.introspection.goal_coordination import _collect_claim_metrics

    (audit_dir / ev.CLAIMS_DIRNAME).write_text("not a dir", encoding="utf-8")
    ev.write_event(audit_dir, "claim_decision")
    _block, notes = _collect_claim_metrics(str(audit_dir))
    assert any("分母不完整" in n for n in notes)


def test_bad_tail_line_is_counted_not_degraded(audit_dir):
    """崩溃留下的半行是预期现象：计数但不报 degraded。"""
    from llm_loop.introspection.goal_coordination import _collect_claim_metrics

    ev.write_event(audit_dir, "claim_decision")
    with ev.events_path(audit_dir).open("ab") as handle:
        handle.write(b'{"v":1,"kind":"claim_dec')
    block, notes = _collect_claim_metrics(str(audit_dir))
    assert block["claims_events"]["lines"] == 2
    assert block["claims_events"]["bad_lines"] == 1
    assert notes == []


# ---------- E-1：task 写路径埋点 ----------


def test_update_emits_one_event_per_successful_write(tmp_path, audit_dir):
    store = _store(audit_dir)
    task_id = _seed(store)
    assert _read_lines(audit_dir) == []  # create 不埋点（口径：只统计 update 落笔）

    store.update("GOAL-1", task_id, status="in_progress")
    store.update("GOAL-1", task_id, status="blocked", blocked_reason="等上游")
    store.update("GOAL-1", task_id, status="in_progress")

    rows = _read_lines(audit_dir)
    assert len(rows) == 3
    assert {r["kind"] for r in rows} == {"claim_decision"}
    assert all(r["decision"] == "passthrough" for r in rows)
    assert all(r["task_id"] == task_id for r in rows)
    assert all(r["claim_generation"] == 0 for r in rows)
    assert all(isinstance(r["latency_ms"], (int, float)) for r in rows)


def test_no_change_update_writes_nothing(tmp_path, audit_dir):
    """无实质变化的 update 不落账本 → 也不得写事件（否则行数 != 写入次数）。"""
    store = _store(audit_dir)
    task_id = _seed(store)
    store.update("GOAL-1", task_id)  # 全 None → no_change 早退
    assert _read_lines(audit_dir) == []


def test_failed_update_writes_no_event(tmp_path, audit_dir):
    store = _store(audit_dir)
    _seed(store)
    with pytest.raises(ValueError):
        store.update("GOAL-1", "TASK-1-999", status="done")
    assert _read_lines(audit_dir) == []


def test_update_still_succeeds_when_event_write_fails(tmp_path, audit_dir):
    """不变量 1：观测失败绝不改变权威写入结果。"""
    store = _store(audit_dir)
    task_id = _seed(store)
    (audit_dir / ev.CLAIMS_DIRNAME).write_text("not a dir", encoding="utf-8")

    task = store.update("GOAL-1", task_id, status="in_progress")
    assert task.status == "in_progress"
    assert store.get("GOAL-1", task_id).status == "in_progress"
    assert ev.write_failures(audit_dir) == 1


def test_holder_is_none_without_run_context(tmp_path, audit_dir):
    store = _store(audit_dir)
    task_id = _seed(store)
    store.update("GOAL-1", task_id, status="in_progress")
    assert _read_lines(audit_dir)[0]["holder"] is None

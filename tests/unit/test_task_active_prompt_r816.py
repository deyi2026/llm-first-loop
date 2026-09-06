from __future__ import annotations

import json
from pathlib import Path

from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_store import TaskStore


def _seed(engine, sid: str):
    audit = Path(engine.settings.data_dir) / "audit"
    goal = GoalStore(audit).create("R8.16 task active prompt test", session_id=sid)
    tasks = TaskStore(audit)
    return goal, tasks


def _wire(fake) -> str:
    return json.dumps(fake.calls[-1]["messages"], ensure_ascii=False)


def test_unique_in_progress_projects_only_minimal_identity(build_test_engine):
    engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
    sid = engine.session.create()
    goal, tasks = _seed(engine, sid)

    done = tasks.create(goal.id, "DONE-SHOULD-NOT-AUTO-PROJECT", acceptance=["done"])
    tasks.update(goal.id, done.task_id, status="in_progress")
    tasks.update(goal.id, done.task_id, status="done")
    blocked = tasks.create(goal.id, "BLOCKED-SHOULD-NOT-AUTO-PROJECT", acceptance=["blocked"])
    tasks.update(goal.id, blocked.task_id, status="in_progress")
    tasks.update(goal.id, blocked.task_id, status="blocked", blocked_reason="BLOCKED-REASON-HIDDEN")
    active = tasks.create(goal.id, "ACTIVE-TASK-TITLE", acceptance=["active"])
    tasks.update(goal.id, active.task_id, status="in_progress")
    tasks.create(goal.id, "READY-SHOULD-NOT-AUTO-PROJECT", acceptance=["ready"])

    engine.run(sid, "继续当前工作")
    wire = _wire(fake)

    assert "slot:task_active" not in wire
    assert "slot:task_frontier" not in wire
    assert f"goal={goal.id}" not in wire
    assert f"task={active.task_id}" not in wire
    assert "ACTIVE-TASK-TITLE" not in wire
    assert "DONE-SHOULD-NOT-AUTO-PROJECT" not in wire
    assert "BLOCKED-SHOULD-NOT-AUTO-PROJECT" not in wire
    assert "BLOCKED-REASON-HIDDEN" not in wire
    assert "READY-SHOULD-NOT-AUTO-PROJECT" not in wire
    assert "unreachable" not in wire.lower()


def test_ready_only_graph_is_on_demand(build_test_engine):
    engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
    sid = engine.session.create()
    goal, tasks = _seed(engine, sid)
    tasks.create(goal.id, "READY-ONLY-TITLE", acceptance=["ready"])

    engine.run(sid, "普通新问题")
    wire = _wire(fake)

    assert "slot:task_active" not in wire
    assert "slot:task_frontier" not in wire
    assert "READY-ONLY-TITLE" not in wire


def test_all_done_graph_is_not_observability_prompt(build_test_engine):
    engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
    sid = engine.session.create()
    goal, tasks = _seed(engine, sid)
    task = tasks.create(goal.id, "DONE-ONLY-TITLE", acceptance=["done"])
    tasks.update(goal.id, task.task_id, status="in_progress")
    tasks.update(goal.id, task.task_id, status="done")

    engine.run(sid, "另一个问题")
    wire = _wire(fake)

    assert "slot:task_active" not in wire
    assert "slot:task_frontier" not in wire
    assert "DONE-ONLY-TITLE" not in wire
    assert "open=0" not in wire


def test_multiple_in_progress_is_ambiguous_and_on_demand(build_test_engine):
    engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
    sid = engine.session.create()
    goal, tasks = _seed(engine, sid)
    first = tasks.create(goal.id, "ACTIVE-A", acceptance=["a"])
    second = tasks.create(goal.id, "ACTIVE-B", acceptance=["b"])
    tasks.update(goal.id, first.task_id, status="in_progress")
    tasks.update(goal.id, second.task_id, status="in_progress")

    engine.run(sid, "继续")
    wire = _wire(fake)

    assert "slot:task_active" not in wire
    assert "slot:task_frontier" not in wire
    assert "ACTIVE-A" not in wire
    assert "ACTIVE-B" not in wire

"""Agency-first task continuity gates.

Explicit user continuation remains an authorization/provenance fact, but does not grant
program-owned task state prompt authority. Goal/task state is retrieval-only through
get_goal/task_frontier. Memory/history references are likewise retrieval intent only.
"""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_store import TaskStore


class _ActionSpy:
    """record_action 收集器（替换 engine.status 的 action 面，其余透传）."""

    def __init__(self, inner):
        self._inner = inner
        self.calls: list[tuple[str, str, str]] = []

    def record_action(self, phase, action_type, detail):
        self.calls.append((phase, action_type, detail))

    def record_phase(self, phase):
        self._inner.record_phase(phase)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _wire(fake) -> str:
    return json.dumps(fake.calls[-1]["messages"], ensure_ascii=False)


def _seed_active_goal(engine, sid: str, *, title="授权能力门目标", n_in_progress=1):
    audit = Path(engine.settings.data_dir) / "audit"
    goal = GoalStore(audit).create(title, session_id=sid)
    tasks = TaskStore(audit)
    for i in range(n_in_progress):
        t = tasks.create(goal.id, f"IN-PROGRESS-{i}", acceptance=[f"a{i}"])
        tasks.update(goal.id, t.task_id, status="in_progress")
    return goal, tasks


def _spy_actions(engine) -> _ActionSpy:
    spy = _ActionSpy(engine.status)
    engine.status = spy
    return spy


# ── 场景 1: 恢复正确 ───────────────────────────────────────────────


def test_authorized_continuation_projects_identity(build_test_engine):
    engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
    sid = engine.session.create()
    goal, _ = _seed_active_goal(engine, sid)

    spy = _spy_actions(engine)
    engine.run(sid, "继续上次任务")
    wire = _wire(fake)

    assert "slot:task_active" not in wire
    assert f"goal={goal.id}" not in wire
    assert "IN-PROGRESS-0" not in wire
    assert not [c for c in spy.calls if c[0] == "task.active"]


def test_plain_question_defers_goal_read(build_test_engine):
    engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
    sid = engine.session.create()
    _seed_active_goal(engine, sid)

    spy = _spy_actions(engine)
    engine.run(sid, "一个全新的普通问题")
    wire = _wire(fake)

    assert "slot:task_active" not in wire
    assert "IN-PROGRESS-0" not in wire
    assert not [c for c in spy.calls if c[0] in {"task.active", "task.frontier"}]


def test_ambiguous_frontier_never_guesses(build_test_engine):
    engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
    sid = engine.session.create()
    _seed_active_goal(engine, sid, n_in_progress=2)

    spy = _spy_actions(engine)
    engine.run(sid, "继续上次任务")
    wire = _wire(fake)

    assert "slot:task_active" not in wire
    assert "IN-PROGRESS-0" not in wire and "IN-PROGRESS-1" not in wire
    assert not [c for c in spy.calls if c[0] in {"task.active", "task.frontier"}]


def test_tool_rounds_reuse_frozen_identity(build_test_engine):
    from tests.unit.test_injection_fingerprint import _build as _fp_build

    engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
    sid = engine.session.create()
    goal, tasks = _seed_active_goal(engine, sid)

    spy = _spy_actions(engine)
    engine.run(sid, "继续上次任务")
    assert not hasattr(engine, "_authorized_task_identity_cache")

    later = tasks.create(goal.id, "LATER-TASK-DOES-NOT-DRIFT", acceptance=["later"])
    tasks.update(goal.id, later.task_id, status="in_progress")
    sess = engine.session.load(sid)
    out = _fp_build(engine, sess, [])
    wire_text = "\n".join(str(m.get("content") or "") for m in out)
    assert "IN-PROGRESS-0" not in wire_text
    assert "LATER-TASK-DOES-NOT-DRIFT" not in wire_text
    assert "slot:task_active" not in wire_text
    assert not [c for c in spy.calls if c[0] == "task.active"]


def test_memory_reference_does_not_authorize_prompt_projection(build_test_engine):
    from llm_loop.core.injection_labels import InjectionLayer, origin_metadata
    from llm_loop.core.message import Message, MessageSource

    engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
    sid = engine.session.create()
    engine.run(sid, "你记得按我之前说的部署步骤吗")  # 显式指代

    wire = _wire(fake)
    # 无论是否存在快照，用户表达“记得之前”只是检索意图，不授予程序
    # 自动选择历史内容并塞入 provider prompt 的权限。
    assert "slot:memory_authorized" not in wire

    # 即使 durable 快照在场，仍保持 retrieval-only。

    engine.session.append(
        sid,
        Message(
            role="user",
            content="部署步骤事实: 先迁移再切流",
            source=MessageSource.USER,
            metadata=origin_metadata(
                InjectionLayer.REFERENCE,
                injection_kind="memory_snapshot",
                persisted_injection=True,
                turn_ref=0,
                query_fp="deadbeefcafe",
            ),
        ),
    )
    engine.run(sid, "你记得按我之前说的部署步骤吗")
    wire2 = _wire(fake)
    assert "slot:memory_authorized" not in wire2
    assert "部署步骤事实" not in wire2


def test_task_frontier_current_alias_resolves_active_goal(build_test_engine):
    from types import SimpleNamespace

    from llm_loop.introspection.tools_task import run_task_frontier

    engine, _fake = build_test_engine([])
    sid = engine.session.create()
    goal, _tasks = _seed_active_goal(engine, sid)
    ctx = SimpleNamespace(session_id=sid)
    host = SimpleNamespace(audit_dir=Path(engine.settings.data_dir) / "audit")
    result = run_task_frontier(ctx, host, {"goal_id": "current"})
    assert result.status.value == "success"
    assert "goal current" not in result.content
    assert "IN-PROGRESS-0" in result.content

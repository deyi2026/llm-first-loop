"""R8.24-E E-3.3: task_active 授权能力门五场景（E-D5，设计包 E §3）.

task_active 从 ACTIVE_STATE 收紧为 USER_AUTHORIZED_STATE——五场景能力门：
1. 恢复正确: 授权触发词 + 恰一 in_progress → identity 投影 + authorized_inject 审计；
2. 零误读: 普通新问题（活跃 goal 在场）→ 零投影 + goal_read=deferred（E-G5）；
3. ambiguous 零注入: 授权 + 多 in_progress → 不猜测（fail-open = 零注入）；
4. 工具链不伤: 同 run 内后续 build → identity 冻结快照照常注入（authorized_
   inject_frozen），不随账本中途漂移；
5. 指代可取回: memory 显式指代 → memory_authorized 投影（E-D1 恢复路径 1）。

授权绑定事件（task.active/authorized_inject 等）经 _record_action 落
ArchitectureStatusProvider——E-G2/E-G5 决策日志判据源。
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

    assert "slot:task_active" in wire
    assert f"goal={goal.id}" in wire
    assert "IN-PROGRESS-0" in wire
    authz = [c for c in spy.calls if c[:2] == ("task.active", "authorized_inject")]
    assert authz, "授权绑定审计（E-3.2③）必须在场"
    assert f"goal={goal.id}" in authz[0][2]


# ── 场景 2: 零误读（普通新问题不自动读取 Goal，E-G5）──────────────────


def test_plain_question_defers_goal_read(build_test_engine):
    engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
    sid = engine.session.create()
    _seed_active_goal(engine, sid)  # 活跃 goal + in_progress 在场

    spy = _spy_actions(engine)
    engine.run(sid, "一个全新的普通问题")
    wire = _wire(fake)

    assert "slot:task_active" not in wire
    assert "IN-PROGRESS-0" not in wire
    deferred = [
        c for c in spy.calls
        if c[:2] == ("task.active", "unauthorized_zero_projection")
        and "goal_read=deferred" in c[2]
    ]
    assert deferred, "零误读轮必须记录 goal_read=deferred（E-G5 判据）"


# ── 场景 3: ambiguous 零注入 ────────────────────────────────────────


def test_ambiguous_frontier_never_guesses(build_test_engine):
    engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
    sid = engine.session.create()
    _seed_active_goal(engine, sid, n_in_progress=2)

    spy = _spy_actions(engine)
    engine.run(sid, "继续上次任务")
    wire = _wire(fake)

    assert "slot:task_active" not in wire, "多 in_progress 不得猜测当前任务"
    assert "IN-PROGRESS-0" not in wire and "IN-PROGRESS-1" not in wire
    assert any(
        c[:2] == ("task.frontier", "on_demand_only") for c in spy.calls
    ), "ambiguous 态记录 on_demand_only（fail-open 零注入）"


# ── 场景 4: 工具链不伤（同 run identity 冻结快照）────────────────────


def test_tool_rounds_reuse_frozen_identity(build_test_engine):
    from tests.unit.test_injection_fingerprint import _build as _fp_build

    engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
    sid = engine.session.create()
    goal, tasks = _seed_active_goal(engine, sid)

    spy = _spy_actions(engine)
    engine.run(sid, "继续上次任务")  # 授权轮: 建立快照
    assert any(c[:2] == ("task.active", "authorized_inject") for c in spy.calls)

    # 模拟同 run 的后续 build（tool-followup 轮）: 账本中途变化不影响快照
    later = tasks.create(goal.id, "LATER-TASK-DOES-NOT-DRIFT", acceptance=["later"])
    tasks.update(goal.id, later.task_id, status="in_progress")  # 变 ambiguous
    sess = engine.session.load(sid)
    out = _fp_build(engine, sess, [])
    wire_text = "\n".join(str(m.get("content") or "") for m in out)
    # 冻结快照仍含原 identity（authorized_inject_frozen）
    assert "IN-PROGRESS-0" in wire_text
    assert "LATER-TASK-DOES-NOT-DRIFT" not in wire_text, "identity 冻结——不随账本漂移"
    frozen = [c for c in spy.calls if c[:2] == ("task.active", "authorized_inject_frozen")]
    assert frozen, "冻结快照注入必须落审计"


# ── 场景 5: 指代可取回（E-D1 恢复路径 1: 显式指代授权一次）────────────


def test_memory_reference_authorizes_retrieval_projection(build_test_engine):
    from llm_loop.core.injection_labels import InjectionLayer, origin_metadata
    from llm_loop.core.message import Message, MessageSource

    engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
    sid = engine.session.create()
    engine.run(sid, "你记得按我之前说的部署步骤吗")  # 显式指代

    wire = _wire(fake)
    # 未持久化快照时零投影（resolved is retrievable, not injectable——
    # 授权只打开通道，投影需要真实存储数据在场）
    assert "slot:memory_authorized" not in wire

    # 快照在场（engine 理解段落盘形态）+ 本轮指代 → 授权投影可取回

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
    assert "slot:memory_authorized" in wire2
    assert "部署步骤事实" in wire2, "显式指代 → 真实数据投影可取回（恢复路径 1）"

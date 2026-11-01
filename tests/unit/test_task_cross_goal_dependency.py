"""DESIGN-20261101 §4.5/§6 (L3): 跨 goal 依赖 blocked_by_goals 的存储、求值与环检测.

覆盖:
- 旧记录无字段兼容 / 归一化去重 / 禁自指 / 成环拒绝（dependency_cycle）
- frontier: 上游未 complete → waiting_cross_goal（不进 ready）；complete → ready
- 上游 blocked/cancelled → 计入 blocked + reason_code=upstream_goal_aborted
- deadline_at 到期 → blocked + reason_code=upstream_deadline_exceeded
- render_frontier 追加 waiting/blocked 行；工具层 task_create 透传与回执标注
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.core.run_context import current_session_id as _sid
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_store import Task, TaskStore
from llm_loop.introspection.tools_task import run_task_create
from llm_loop.timekeeping import system_local_now

SID = "sess-l3"


@pytest.fixture(autouse=True)
def _bind():
    token = _sid.set(SID)
    yield
    _sid.reset(token)


def _host(tmp_path):
    return SimpleNamespace(audit_dir=str(tmp_path), ctx=SimpleNamespace())


def _two_goals(tmp_path):
    gs = GoalStore(str(tmp_path))
    a = gs.create("上游目标", session_id=SID)
    b = gs.create("下游目标", session_id=SID)
    return gs, a, b


def test_legacy_task_has_empty_xdeps(tmp_path):
    gs, a, _ = _two_goals(tmp_path)
    ts = TaskStore(str(tmp_path))
    t = ts.create(a.id, "老式任务", acceptance=["ok"])
    assert t.blocked_by_goals == []
    assert "blocked_by_goals" in t.to_dict()
    assert Task.from_dict({"task_id": "T", "goal_id": "G", "title": "x"}).blocked_by_goals == []


def test_xdeps_normalized_and_deduped(tmp_path):
    gs, a, b = _two_goals(tmp_path)
    ts = TaskStore(str(tmp_path))
    t = ts.create(a.id, "归一化", acceptance=["ok"], blocked_by_goals=[" " + b.id + " ", "", b.id])
    assert t.blocked_by_goals == [b.id]


def test_self_reference_rejected(tmp_path):
    gs, a, _ = _two_goals(tmp_path)
    with pytest.raises(ValueError, match="dependency_cycle"):
        TaskStore(str(tmp_path)).create(a.id, "自指", acceptance=["ok"], blocked_by_goals=[a.id])


def test_cycle_rejected(tmp_path):
    gs, a, b = _two_goals(tmp_path)
    ts = TaskStore(str(tmp_path))
    ts.create(a.id, "A 等 B", acceptance=["ok"], blocked_by_goals=[b.id])
    with pytest.raises(ValueError, match="dependency_cycle"):
        ts.create(b.id, "B 等 A", acceptance=["ok"], blocked_by_goals=[a.id])


def test_waiting_until_upstream_complete(tmp_path):
    gs, a, b = _two_goals(tmp_path)
    ts = TaskStore(str(tmp_path))
    t = ts.create(a.id, "等上游", acceptance=["ok"], blocked_by_goals=[b.id])

    fr = ts.compute_frontier(a.id)
    assert [x.task_id for x in fr["ready"]] == []
    assert [e["task"].task_id for e in fr["waiting_cross_goal"]] == [t.task_id]
    assert fr["open_count"] == 1

    gs.update(b.id, "complete", "上游收口")
    fr2 = ts.compute_frontier(a.id)
    assert [x.task_id for x in fr2["ready"]] == [t.task_id]
    assert fr2["waiting_cross_goal"] == []


def test_upstream_aborted_blocks_task(tmp_path):
    gs, a, b = _two_goals(tmp_path)
    ts = TaskStore(str(tmp_path))
    t = ts.create(a.id, "上游中止", acceptance=["ok"], blocked_by_goals=[b.id])
    gs.update(b.id, "blocked", "上游被阻塞")

    fr = ts.compute_frontier(a.id)
    assert fr["waiting_cross_goal"] == []
    assert [x.task_id for x in fr["blocked"]] == [t.task_id]
    assert fr["blocked_upstream"][0]["reason_code"] == "upstream_goal_aborted"
    assert fr["blocked_upstream"][0]["task"].status == "pending"  # 不自动 failed


def test_deadline_exceeded_blocks_task(tmp_path):
    gs, a, b = _two_goals(tmp_path)
    ts = TaskStore(str(tmp_path))
    past = (system_local_now() - timedelta(hours=1)).isoformat()
    t = ts.create(a.id, "等超期", acceptance=["ok"], blocked_by_goals=[b.id], deadline_at=past)

    fr = ts.compute_frontier(a.id)
    assert [x.task_id for x in fr["blocked"]] == [t.task_id]
    assert fr["blocked_upstream"][0]["reason_code"] == "upstream_deadline_exceeded"


def test_invalid_deadline_rejected(tmp_path):
    gs, a, b = _two_goals(tmp_path)
    with pytest.raises(ValueError, match="deadline_at"):
        TaskStore(str(tmp_path)).create(
            a.id, "坏期限", acceptance=["ok"], blocked_by_goals=[b.id], deadline_at="明天"
        )


def test_render_shows_waiting_and_xgoal_block(tmp_path):
    gs, a, b = _two_goals(tmp_path)
    ts = TaskStore(str(tmp_path))
    ts.create(a.id, "等待中", acceptance=["ok"], blocked_by_goals=[b.id])
    text = ts.render_frontier(a.id)
    assert "waiting_xgoal" in text

    gs.update(b.id, "blocked", "上游取消")
    ts.create(a.id, "被上游拖死", acceptance=["ok"], blocked_by_goals=[b.id])
    text2 = ts.render_frontier(a.id)
    assert "reason_code=upstream_goal_aborted" in text2


def test_tool_task_create_passes_xdeps(tmp_path):
    gs, a, b = _two_goals(tmp_path)
    res = run_task_create(
        None,
        _host(tmp_path),
        {
            "goal_id": a.id,
            "title": "工具层跨 goal",
            "acceptance": ["ok"],
            "blocked_by_goals": [b.id],
        },
    )
    assert res.status == ToolResultStatus.SUCCESS
    assert f"xdeps: {b.id}" in res.content

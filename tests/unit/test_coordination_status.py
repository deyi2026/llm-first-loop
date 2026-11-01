"""DESIGN-20261101 §4.4/§6 (L2): coordination_status 只读协调视图.

覆盖:
- 回执含 goals/sessions/running/recent_events/degraded 五段结构
- 跨会话归属可见（owner=other 的 goal 不会被当成自己的）
- 任务计数来自 frontier（ready/doing/blocked/xwait）
- window_hours / only_in_flight 过滤
- 未接线数据源（children/jobs/events）进 degraded，不伪造空值结论
- 零写：调用前后 goal 账本字节不变
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.core.run_context import current_session_id as _sid
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_store import TaskStore
from llm_loop.introspection.tools_goal import GOAL_TOOL_DEFS, run_coordination_status

SELF = "sess-self-l2"
OTHER = "sess-other-l2"


@pytest.fixture(autouse=True)
def _bind():
    token = _sid.set(SELF)
    yield
    _sid.reset(token)


def _host(tmp_path):
    return SimpleNamespace(audit_dir=str(tmp_path), ctx=SimpleNamespace())


def test_view_contains_all_sections_and_owners(tmp_path):
    gs = GoalStore(str(tmp_path))
    mine = gs.create("我方目标", session_id=SELF)
    theirs = gs.create("他方目标", session_id=OTHER)
    ts = TaskStore(str(tmp_path))
    ts.create(mine.id, "可做任务", acceptance=["ok"])
    ts.create(mine.id, "等他方", acceptance=["ok"], blocked_by_goals=[theirs.id])

    snap_res = run_coordination_status(None, _host(tmp_path), {"window_hours": 0})
    assert snap_res.status == ToolResultStatus.SUCCESS
    text = snap_res.content
    assert "[coordination_status]" in text
    assert mine.id in text and theirs.id in text
    assert "owner=other" in text
    assert "xwait=1" in text
    assert "degraded: running.children" in text
    assert "degraded: recent_events" in text


def test_window_filter(tmp_path):
    gs = GoalStore(str(tmp_path))
    gs.create("目标", session_id=SELF)
    recent = run_coordination_status(None, _host(tmp_path), {"window_hours": 1})
    assert "goals=1" in recent.content
    # 用 window_hours=0 表示不限窗口，至少不会更少
    older = run_coordination_status(None, _host(tmp_path), {"window_hours": 0})
    assert "goals=1" in older.content


def test_only_in_flight(tmp_path):
    gs = GoalStore(str(tmp_path))
    g = gs.create("将完成的目标", session_id=SELF)
    gs.update(g.id, "complete", "已完成")
    res = run_coordination_status(None, _host(tmp_path), {"window_hours": 0, "only_in_flight": True})
    assert "goals=0" in res.content
    # 设计 §170: 默认窗口 = 最近 24h 且 only_in_flight=true；展开已完成须显式 false
    res_default = run_coordination_status(None, _host(tmp_path), {"window_hours": 0})
    assert "goals=0" in res_default.content
    res_all = run_coordination_status(
        None, _host(tmp_path), {"window_hours": 0, "only_in_flight": False}
    )
    assert "goals=1" in res_all.content


def test_read_only_no_mutation(tmp_path):
    gs = GoalStore(str(tmp_path))
    gs.create("只读校验", session_id=SELF)
    path = tmp_path / "goals.jsonl"
    before = path.read_bytes()
    run_coordination_status(None, _host(tmp_path), {"window_hours": 0})
    assert path.read_bytes() == before


def test_tool_registered(tmp_path):
    assert "coordination_status" in [d["name"] for d in GOAL_TOOL_DEFS]
    from llm_loop.introspection.registry_goal import execute

    host = SimpleNamespace(audit_dir=str(tmp_path), ctx=SimpleNamespace())
    res = execute("coordination_status", {"window_hours": 0}, host)
    assert res is not None and res.status == ToolResultStatus.SUCCESS

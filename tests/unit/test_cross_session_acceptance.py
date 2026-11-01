"""DESIGN-20261101 §6 验收矩阵 A1-A12 的机器化落地（单文件总览）.

A1 单会话零变化 / A2 跨会话写拒绝且字节不变 / A3 拒绝先于收口门 / A6 归属标注字段
A7 create_goal 并行 goal 摘要 / A11 同 expected_version 并发一成一败 / A12 只读工具零写。
（A4/A5/A8/A9/A10 分别在 test_goal_coordination_l1 / test_task_cross_goal_dependency /
test_goal_version_cas 中覆盖）
"""

from __future__ import annotations

import hashlib
import os
from types import SimpleNamespace

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.core.run_context import current_session_id as _sid
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_store import TaskStore
from llm_loop.introspection.tools_goal import (
    run_checkpoint_goal,
    run_coordination_status,
    run_create_goal,
    run_get_goal,
    run_update_goal,
)
from llm_loop.introspection.tools_task import run_task_create

SELF = "sess-self-acc"
OTHER = "sess-other-acc"


@pytest.fixture(autouse=True)
def _bind():
    token = _sid.set(SELF)
    yield
    _sid.reset(token)


def _host(tmp_path):
    return SimpleNamespace(audit_dir=str(tmp_path), ctx=SimpleNamespace())


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


# A1: 跨会话写被拒时 goal 账本字节不变（失败不落盘）
def test_a1_denied_write_leaves_bytes_unchanged(tmp_path):
    g = GoalStore(str(tmp_path)).create("A1 目标", session_id=OTHER)
    path = tmp_path / "goals.jsonl"
    before, before_mtime = _sha(path), path.stat().st_mtime_ns

    res = run_checkpoint_goal(None, _host(tmp_path), {"goal_id": g.id, "what": "越权写"})
    assert res.status == ToolResultStatus.FAILURE
    assert _sha(path) == before
    assert path.stat().st_mtime_ns == before_mtime


# A2: 任务图写入被拒时 tasks 账本不变
def test_a2_denied_task_write_leaves_bytes_unchanged(tmp_path):
    g = GoalStore(str(tmp_path)).create("A2 目标", session_id=OTHER)
    tasks_file = tmp_path / "tasks" / f"{g.id}.jsonl"
    before = _sha(tasks_file)

    res = run_task_create(None, _host(tmp_path), {"goal_id": g.id, "title": "越权建任务"})
    assert res.status == ToolResultStatus.FAILURE
    assert "reason_code=cross_session_write_denied" in res.content
    assert _sha(tasks_file) == before


# A3: 拒绝先于收口门（complete 门未运行，未产生门文案）
def test_a3_denial_precedes_completion_gate(tmp_path):
    g = GoalStore(str(tmp_path)).create("A3 目标", session_id=OTHER)
    TaskStore(str(tmp_path)).create(g.id, "未完成任务", acceptance=["ok"])

    res = run_update_goal(None, _host(tmp_path), {"goal_id": g.id, "status": "complete", "reason": "x"})
    assert res.status == ToolResultStatus.FAILURE
    assert "reason_code=cross_session_write_denied" in res.content
    assert "任务图收口" not in res.content


# A6: get_goal 标注 owner_session_id 与非当前会话提示
def test_a6_get_goal_owner_field(tmp_path):
    g = GoalStore(str(tmp_path)).create("A6 目标", session_id=OTHER)
    res = run_get_goal(None, _host(tmp_path), {"goal_id": g.id})
    assert "owner_session_id=" in res.content
    assert "其他会话" in res.content


# A7: create_goal 回执列出其他 active goal
def test_a7_create_goal_lists_parallel_goals(tmp_path):
    gs = GoalStore(str(tmp_path))
    other = gs.create("已有的并行目标", session_id=SELF)

    res = run_create_goal(None, _host(tmp_path), {"objective": "新目标"})
    assert res.status == ToolResultStatus.SUCCESS
    assert "并行 goal" in res.content
    assert other.id in res.content


# A11: 两个写者同 expected_version → 一成一败（后者拿到 current_version）
def test_a11_concurrent_writers_one_wins(tmp_path):
    store = GoalStore(str(tmp_path))
    g = store.create("A11 目标", session_id=SELF)
    first = run_checkpoint_goal(
        None, _host(tmp_path), {"goal_id": g.id, "what": "写者一", "expected_version": 1}
    )
    second = run_checkpoint_goal(
        None, _host(tmp_path), {"goal_id": g.id, "what": "写者二", "expected_version": 1}
    )
    assert first.status == ToolResultStatus.SUCCESS
    assert second.status == ToolResultStatus.FAILURE
    assert "reason_code=version_conflict" in second.content
    assert "current_version=2" in second.content
    assert len(GoalStore(str(tmp_path)).get(g.id)["checkpoints"]) == 1


# A12: 只读工具调用前后 goals/tasks 账本 sha256 与 mtime 均不变
def test_a12_coordination_status_is_read_only(tmp_path):
    gs = GoalStore(str(tmp_path))
    g = gs.create("A12 目标", session_id=SELF)
    TaskStore(str(tmp_path)).create(g.id, "任务", acceptance=["ok"])

    goals_file = tmp_path / "goals.jsonl"
    tasks_file = tmp_path / "tasks" / f"{g.id}.jsonl"
    snap = {
        p: (_sha(p), p.stat().st_mtime_ns, os.stat(p).st_size)
        for p in (goals_file, tasks_file)
    }
    res = run_coordination_status(None, _host(tmp_path), {"window_hours": 0})
    assert res.status == ToolResultStatus.SUCCESS
    for p, before in snap.items():
        assert (_sha(p), p.stat().st_mtime_ns, os.stat(p).st_size) == before


# A13: task_* 无跨会话出口——即便手工塞进 cross_session/reason/evidence_refs 参数组合，
# 代码也不得放行（拒绝文案否认的通道不能存在，否则同一目标两套真值）
def test_a13_task_gate_ignores_cross_session_args(tmp_path):
    from llm_loop.introspection.tools_task import run_task_update

    g = GoalStore(str(tmp_path)).create("A13 目标", session_id=OTHER)
    ts = TaskStore(str(tmp_path))
    ts.create(g.id, "已有任务", acceptance=["ok"])
    task_id = ts.list_for_goal(g.id)[0].task_id
    tasks_file = tmp_path / "tasks" / f"{g.id}.jsonl"
    before = _sha(tasks_file)
    override = {
        "cross_session": True,
        "reason": "试图用参数级放行越权",
        "evidence_refs": ["evidence://v1/" + "0" * 64],
    }

    created = run_task_create(
        None, _host(tmp_path), {"goal_id": g.id, "title": "越权建任务", **override}
    )
    updated = run_task_update(
        None,
        _host(tmp_path),
        {"goal_id": g.id, "task_id": task_id, "status": "in_progress", **override},
    )
    for res in (created, updated):
        assert res.status == ToolResultStatus.FAILURE
        assert "reason_code=cross_session_write_denied" in res.content
        assert "cross_session=true" not in res.content  # 文案不指幻影出口
    assert _sha(tasks_file) == before
    assert ts.list_for_goal(g.id)[0].status == "pending"


# A14: 结构守卫——_require_active_goal 不得有 args 透传口（防回退成"文案否认、代码支持"）
def test_a14_task_gate_has_no_args_passthrough():
    import inspect

    from llm_loop.introspection.tools_task import _require_active_goal

    assert "args" not in inspect.signature(_require_active_goal).parameters

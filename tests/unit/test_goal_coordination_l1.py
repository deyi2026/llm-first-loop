"""DESIGN-20261101 §6 L1 验收: 跨会话 goal 写侧仲裁 + 读侧归属标注.

覆盖 A1/A2/A3/A4/A5/A10:
- A1 单会话既有流程零行为变化（self session 写入照旧成功）
- A2 跨会话写被拒（reason_code=cross_session_write_denied）且 goal 记录未被改
- A3 LFL_GOAL_ENFORCE_WRITE_PREF=off → 告警放行且写入生效
- A4 get_goal 回执含归属标注（self/other/unclaimed/unknown 四态）
- A5 pre-check 顺序: 存在性先于 owner（不存在 goal 报不存在，不报跨会话拒绝）
- A10 既有回执行首行/字段不变，只追加

session 身份真值源: llm_loop.core.run_context.current_session_id（bound_session_id）。
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from llm_loop.core.message import ToolResultStatus
from llm_loop.core.run_context import current_session_id as _sid
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.tools_goal import (
    run_checkpoint_goal,
    run_get_goal,
    run_update_goal,
)
from llm_loop.introspection.tools_task import run_task_create


OWNER = "sess-owner-0001"
OTHER = "sess-other-0002"


def _bind(sid: str):
    token = _sid.set(sid)
    return token


def _host(tmp_path):
    return SimpleNamespace(audit_dir=str(tmp_path), ctx=SimpleNamespace())


def _goal(tmp_path, session_id=OWNER):
    return GoalStore(str(tmp_path)).create("跨会话仲裁测试目标", session_id=session_id)


@pytest.fixture(autouse=True)
def _reset_sid():
    token = _sid.set("")
    yield
    _sid.reset(token)


# A1: 同会话写入零行为变化
def test_same_session_write_allowed(tmp_path):
    g = _goal(tmp_path)
    _bind(OWNER)
    host = _host(tmp_path)

    cp = run_checkpoint_goal(None, host, {"goal_id": g.id, "what": "完成 L1 判定", "next": "补测试"})
    assert cp.status == ToolResultStatus.SUCCESS
    assert "checkpoint 已记录" in cp.content
    assert "注意:" not in cp.content

    up = run_update_goal(None, host, {"goal_id": g.id, "status": "blocked", "reason": "等人工"})
    assert up.status == ToolResultStatus.SUCCESS
    store = GoalStore(str(tmp_path))
    assert len(store.get(g.id)["checkpoints"]) == 1


# A2: 跨会话写入被拒且不落盘
def test_foreign_session_write_blocked(tmp_path):
    g = _goal(tmp_path)
    _bind(OTHER)
    host = _host(tmp_path)

    cp = run_checkpoint_goal(None, host, {"goal_id": g.id, "what": "外部会话写入"})
    assert cp.status == ToolResultStatus.FAILURE
    assert "reason_code=cross_session_write_denied" in cp.content
    assert "未被接受" in cp.content
    assert len(GoalStore(str(tmp_path)).get(g.id)["checkpoints"]) == 0

    up = run_update_goal(None, host, {"goal_id": g.id, "status": "blocked", "reason": "外部会话"})
    assert up.status == ToolResultStatus.FAILURE
    assert "reason_code=cross_session_write_denied" in up.content
    assert GoalStore(str(tmp_path)).get(g.id)["status"] == "active"


# A2b: 任务图写入同源拦截
def test_foreign_session_task_create_blocked(tmp_path):
    g = _goal(tmp_path)
    _bind(OTHER)
    res = run_task_create(None, _host(tmp_path), {"goal_id": g.id, "title": "外部会话建任务"})
    assert res.status == ToolResultStatus.FAILURE
    assert "reason_code=cross_session_write_denied" in res.content


# A3: 显式跨会话授权（cross_session + reason + evidence_refs）→ allow_annotated
def test_cross_session_authorized_allows(tmp_path):
    g = _goal(tmp_path)
    _bind(OTHER)

    cp = run_checkpoint_goal(
        None,
        _host(tmp_path),
        {
            "goal_id": g.id,
            "what": "经授权的跨会话写入",
            "cross_session": True,
            "reason": "owner 会话已停止，用户要求本会话接管收口",
            "evidence_refs": ["evidence://v1/deadbeef"],
        },
    )
    assert cp.status == ToolResultStatus.SUCCESS
    assert "cross_session_authorized" in cp.content
    assert len(GoalStore(str(tmp_path)).get(g.id)["checkpoints"]) == 1


def test_cross_session_without_evidence_still_denied(tmp_path):
    g = _goal(tmp_path)
    _bind(OTHER)
    cp = run_checkpoint_goal(
        None,
        _host(tmp_path),
        {"goal_id": g.id, "what": "缺证据的授权", "cross_session": True, "reason": "想写"},
    )
    assert cp.status == ToolResultStatus.FAILURE
    assert "reason_code=cross_session_write_denied" in cp.content
    assert len(GoalStore(str(tmp_path)).get(g.id)["checkpoints"]) == 0


# A1b: 未认领 goal 允许首个写入者
def test_unclaimed_goal_writable(tmp_path):
    g = _goal(tmp_path, session_id="")
    _bind(OTHER)
    cp = run_checkpoint_goal(None, _host(tmp_path), {"goal_id": g.id, "what": "首写认领"})
    assert cp.status == ToolResultStatus.SUCCESS
    assert "owner_unknown" in cp.content


# 无 session binding: 放行但如实标注未验证（残余风险，DESIGN §7）
def test_missing_session_binding_warns(tmp_path):
    g = _goal(tmp_path)
    _bind("")
    cp = run_checkpoint_goal(None, _host(tmp_path), {"goal_id": g.id, "what": "无绑定写入"})
    assert cp.status == ToolResultStatus.SUCCESS
    assert "session_unverified" in cp.content


# A4: get_goal 归属四态
def test_get_goal_ownership_banner_states(tmp_path):
    g_own = _goal(tmp_path)
    _bind(OWNER)
    host = _host(tmp_path)
    own = run_get_goal(None, host, {"goal_id": g_own.id})
    assert "归属: 本会话" in own.content

    _bind(OTHER)
    foreign = run_get_goal(None, host, {"goal_id": g_own.id})
    assert "归属: 其他会话" in foreign.content
    assert "跨会话写将被拒绝" in foreign.content

    g_unclaimed = _goal(tmp_path, session_id="")
    un = run_get_goal(None, host, {"goal_id": g_unclaimed.id})
    assert "归属: 未认领" in un.content

    _bind("")
    unknown = run_get_goal(None, host, {"goal_id": g_own.id})
    assert "身份不可证明" in unknown.content


# A5: pre-check 顺序——存在性优先
def test_missing_goal_reports_not_found_not_foreign(tmp_path):
    _bind(OTHER)
    res = run_update_goal(None, _host(tmp_path), {"goal_id": "GOAL-NOT-EXIST", "status": "blocked", "reason": "x"})
    assert res.status == ToolResultStatus.FAILURE
    assert "不存在" in res.content
    assert "foreign_goal_owner" not in res.content


# A10: 既有回执字段保持
def test_get_goal_existing_fields_preserved(tmp_path):
    g = _goal(tmp_path)
    _bind(OWNER)
    res = run_get_goal(None, _host(tmp_path), {"goal_id": g.id})
    lines = res.content.split("\n")
    assert lines[0].startswith("目标: ")
    assert lines[1] == f"状态: active | id={g.id}"

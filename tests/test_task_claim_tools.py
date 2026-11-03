"""claim 工具面端到端：claim_task → task_update(带 token) → release_task.

模块级测试证明的是存储语义；这里证明**工具路径**上没有把语义丢掉
（回执文本、token 传递、无 token 时的告警、holder 由程序注入而非模型给）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from llm_loop.core.run_context import current_session_id
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_claim import ClaimStore
from llm_loop.introspection.task_store import TaskStore
from llm_loop.introspection.tools_task import run_claim_task, run_release_task, run_task_update

SESSION = "run-claim-tools"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    audit = str(tmp_path / "audit")
    token = current_session_id.set(SESSION)
    monkeypatch.setenv("LFL_AUDIT_DIR", audit)
    goal = GoalStore(audit).create("claim 工具面验收", session_id=SESSION)
    task = TaskStore(audit).create(goal.id, "带 claim 的任务", acceptance=["可验收"])
    yield SimpleNamespace(
        audit=audit,
        goal_id=goal.id,
        task_id=task.task_id,
        ctx=SimpleNamespace(),
        host=SimpleNamespace(audit_dir=audit),
    )
    current_session_id.reset(token)


def test_claim_then_update_then_release(env):
    claimed = run_claim_task(env.ctx, env.host, {"goal_id": env.goal_id, "task_id": env.task_id})
    assert claimed.status.name == "SUCCESS"
    assert "token=CLM-" in claimed.content
    token = claimed.content.split("token=")[1].split()[0]

    updated = run_task_update(
        env.ctx,
        env.host,
        {
            "goal_id": env.goal_id,
            "task_id": env.task_id,
            "status": "in_progress",
            "claim_token": token,
        },
    )
    assert updated.status.name == "SUCCESS"
    assert "claim: 已随本次写入续租" in updated.content

    released = run_release_task(
        env.ctx, env.host, {"goal_id": env.goal_id, "task_id": env.task_id, "claim_token": token}
    )
    assert released.status.name == "SUCCESS"
    assert "claim 已释放" in released.content


def test_cross_session_write_is_denied_before_claim_logic(env):
    """归属闸在 fencing 之前：另一会话连写都写不进来.

    这意味着 ``claim_conflict_warning`` 在**跨会话**场景下不可达——跨会话冲突
    已经被归属校验拦掉，warn 分支只在同一会话内（如 background child 与父会话
    都算同一 session id）才可能触发。登记为 R22，不做假的"跨会话冲突率"。
    """
    claimed = run_claim_task(env.ctx, env.host, {"goal_id": env.goal_id, "task_id": env.task_id})
    assert claimed.status.name == "SUCCESS"
    token = current_session_id.set("run-intruder")
    try:
        updated = run_task_update(
            env.ctx,
            env.host,
            {"goal_id": env.goal_id, "task_id": env.task_id, "title": "改名"},
        )
    finally:
        current_session_id.reset(token)
    assert updated.status.name == "FAILURE"
    assert "cross_session_write_denied" in updated.content
    assert TaskStore(env.audit).get(env.goal_id, env.task_id).title == "带 claim 的任务"


def test_stale_token_is_refused_over_tool_path(env):
    claimed = run_claim_task(env.ctx, env.host, {"goal_id": env.goal_id, "task_id": env.task_id})
    token = claimed.content.split("token=")[1].split()[0]
    # 让另一个 holder 接管（把租约判成已过期需要改时钟，这里直接撤销后重领）
    ClaimStore(env.audit).revoke(env.goal_id, env.task_id, actor="test")
    refreshed = run_claim_task(env.ctx, env.host, {"goal_id": env.goal_id, "task_id": env.task_id})
    assert refreshed.status.name == "SUCCESS"

    stale = run_task_update(
        env.ctx,
        env.host,
        {"goal_id": env.goal_id, "task_id": env.task_id, "status": "in_progress", "claim_token": token},
    )
    assert stale.status.name == "FAILURE"
    assert "claim_generation_stale" in stale.content

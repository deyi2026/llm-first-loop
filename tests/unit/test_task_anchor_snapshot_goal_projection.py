"""任务锚快照·Goal 投影反向用例（2026-09-16 拷问：通道A/B）.

对应 EVO-20260916-ccc978b2 锚点 pinning 优化的复核结论——原实现只验收
"锚能保住"，未覆盖"锚会不会咬人"：
  通道A: build 侧 GoalStore.get 未带 strict_session=True → 本会话无 goal
         时，别的会话/全局 goal 会经 `active`/`latest` 回退链投进本会话
         每一个压缩态窗口。
  通道B: update_goal(complete/blocked) 不清 checkpoints[-1].next，快照又
         只投 what|next|evidence 不投 status/时间戳 → 已过时 next 以活性
         口吻常驻压缩态。

修复验收（src/llm_loop/core/loop/build.py::_task_anchor_goal_parts）：
  1. 本会话无 goal → 不回退投影其他会话/全局 goal（返回空）;
  2. 终态 goal → 只投状态+时间戳行，objective/旧 next/checkpoint/frontier
     均不在场;
  3. blocked → 状态行含 blocked_reason，不含 objective;
  4. active → objective/next 在场且带 status/updated_at/checkpoint ts
     （模型可自判陈旧）;
  5. "[任务锚点" 注入块被 _is_injected_block 识别（不会被当成真实 user
     指令参与锚点 pin——自强化回路阻断）。
"""

from __future__ import annotations

from llm_loop.core.history import _is_injected_block
from llm_loop.core.loop.build import _task_anchor_goal_parts
from llm_loop.core.message import Message, MessageSource
from llm_loop.introspection.goal import GoalStore


def _audit(tmp_path) -> str:
    return str(tmp_path / "audit")


def test_channel_a_no_fallback_to_foreign_active_goal(tmp_path):
    store = GoalStore(_audit(tmp_path))
    other = store.create("旧目标：把部署脚本全部迁到新仓库", session_id="sess-other")
    assert other is not None
    # 本会话没建过 goal：不允许回退投影别人的 active goal
    assert _task_anchor_goal_parts(_audit(tmp_path), "sess-mine") == []


def test_channel_a_no_fallback_to_global_latest_terminal_goal(tmp_path):
    store = GoalStore(_audit(tmp_path))
    g = store.create("已完结旧目标", session_id="sess-old")
    store.update(g.id, "complete")
    # 全局 latest 存在但终态：同样不得投进无 goal 的新会话
    assert _task_anchor_goal_parts(_audit(tmp_path), "sess-new") == []


def test_channel_b_terminal_goal_projects_status_only(tmp_path):
    store = GoalStore(_audit(tmp_path))
    g = store.create("重写迁移脚本", session_id="sess-done")
    store.checkpoint(
        g.id,
        what="已交付 v2",
        evidence="e://t/1",
        next_step="继续执行旧目标：清理旧仓库 remote 7f3a",
    )
    store.update(g.id, "complete")
    parts = _task_anchor_goal_parts(_audit(tmp_path), "sess-done")
    joined = "\n".join(parts)
    assert parts, "终态仍应投一行状态（durable 事实，不是静默消失）"
    assert "status: complete" in joined
    assert "completed_at:" in joined
    # 旧指令/objective/frontier 均不得以活性口吻回投压缩态
    assert "清理旧仓库" not in joined
    assert "重写迁移脚本" not in joined
    assert "[Checkpoint" not in joined
    assert "[Frontier" not in joined


def test_channel_b_blocked_goal_projects_reason_not_objective(tmp_path):
    store = GoalStore(_audit(tmp_path))
    g = store.create("等待外部授权的目标", session_id="sess-blk")
    store.update(g.id, "blocked", reason="生产库无写权限")
    joined = "\n".join(_task_anchor_goal_parts(_audit(tmp_path), "sess-blk"))
    assert "status: blocked" in joined
    assert "blocked_reason: 生产库无写权限" in joined
    assert "等待外部授权的目标" not in joined


def test_active_goal_keeps_projection_with_status_and_ts(tmp_path):
    store = GoalStore(_audit(tmp_path))
    g = store.create("完成压测报告", session_id="sess-live")
    store.checkpoint(
        g.id, what="首轮压测完成", evidence="e://t/9", next_step="跑第二轮"
    )
    joined = "\n".join(_task_anchor_goal_parts(_audit(tmp_path), "sess-live"))
    assert "完成压测报告" in joined
    assert "status: active" in joined
    assert "updated_at:" in joined
    assert "next: 跑第二轮" in joined
    assert "[Checkpoint ts: " in joined  # checkpoint 时间在场，可判陈旧


def test_empty_store_returns_no_parts(tmp_path):
    # 无任何 goal：fail-open 返回空，而不是回退全局
    assert _task_anchor_goal_parts(_audit(tmp_path), "sess-x") == []


def test_anchor_block_prefix_recognized_as_injected():
    # 防自强化：锚快照块即便未来被持久化为 user message，也不再被当作
    # 真实用户指令参与锚点 pin（_INJECTED_USER_PREFIXES 已含 "[任务锚点"）
    m = Message(
        role="user",
        content=(
            "[任务锚点·压缩存活快照]（程序逐字投影 durable 事实，非摘要）\n"
            "[Goal GOAL-X] status: active | updated_at: t\nobjective: x"
        ),
        source=MessageSource.USER,
    )
    assert _is_injected_block(m) is True

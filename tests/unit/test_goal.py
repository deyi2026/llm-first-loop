"""单元测试: 任务级 Goal 状态机 + checkpoint 四要素（EVO-20260824-3cd4d74b）.

覆盖:
1. create → checkpoint（四要素）→ get（恢复视图）→ complete 生命周期
2. blocked 仅严格条件（状态机限制）
3. 非 active 目标 checkpoint 拒绝（如实不写入）
4. 多 checkpoint 累积 + 最近优先
"""

import json
from pathlib import Path

from llm_loop.introspection.goal import GOAL_STATUSES, GoalStore


def _store(tmp_path: Path) -> GoalStore:
    return GoalStore(str(tmp_path))


def test_lifecycle_create_checkpoint_complete(tmp_path):
    s = _store(tmp_path)
    g = s.create("深度审计项目", session_id="s1")
    assert g.status == "active"
    assert g.id.startswith("GOAL-")

    # checkpoint 四要素
    upd = s.checkpoint(
        g.id,
        what="完成审计框架",
        evidence="architecture_status success",
        path="src/llm_loop/",
        next_step="分析缓存命中",
    )
    assert upd is not None
    assert len(upd["checkpoints"]) == 1
    cp = upd["checkpoints"][0]
    assert cp["what"] == "完成审计框架"
    assert cp["evidence"] == "architecture_status success"
    assert cp["path"] == "src/llm_loop/"
    assert cp["next"] == "分析缓存命中"

    # get 恢复视图
    got = s.get(g.id)
    assert got["id"] == g.id
    assert got["status"] == "active"
    assert len(got["checkpoints"]) == 1

    # complete（证据驱动）
    done = s.update(g.id, "complete", reason="全部需求已用工具回执验证")
    assert done["status"] == "complete"
    assert done["completed_at"]


def test_checkpoint_rejected_when_not_active(tmp_path):
    s = _store(tmp_path)
    g = s.create("任务", session_id="s1")
    s.update(g.id, "complete")
    # 非 active 目标 checkpoint → 返回现状不追加（如实）
    upd = s.checkpoint(g.id, what="不应写入")
    assert upd is not None
    assert len(upd.get("checkpoints", [])) == 0


def test_update_blocked_requires_reason_path(tmp_path):
    s = _store(tmp_path)
    g = s.create("任务", session_id="s1")
    b = s.update(g.id, "blocked", reason="外部依赖未就绪")
    assert b["status"] == "blocked"
    assert b["blocked_reason"] == "外部依赖未就绪"


def test_invalid_status_rejected(tmp_path):
    s = _store(tmp_path)
    g = s.create("任务", session_id="s1")
    try:
        s.update(g.id, "done")
        raise AssertionError("应拒绝非法状态")
    except ValueError:
        pass


def test_get_returns_latest_active_or_last(tmp_path):
    s = _store(tmp_path)
    g1 = s.create("目标1", session_id="s1")
    s.update(g1.id, "complete")
    g2 = s.create("目标2", session_id="s1")
    got = s.get()  # 无 id: 最近 active（目标2）
    assert got["id"] == g2.id
    # 全部 complete 后 → 取最近一条
    s.update(g2.id, "complete")
    got2 = s.get()
    assert got2["id"] == g2.id


def test_multiple_checkpoints_recent_first(tmp_path):
    s = _store(tmp_path)
    g = s.create("任务", session_id="s1")
    for i in range(5):
        s.checkpoint(g.id, what=f"里程碑{i}", evidence="ev", path="p", next_step="n")
    got = s.get(g.id)
    assert len(got["checkpoints"]) == 5
    assert got["checkpoints"][-1]["what"] == "里程碑4"


def test_goal_statuses_constant():
    assert set(GOAL_STATUSES) == {"active", "complete", "blocked"}

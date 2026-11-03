"""协调视图容量与窗口口径的回归测试（2026-11-03）.

E8: limit=200 在真实 239 行账本上静默丢掉 12 个 active goal → 改 500 且必须自证截断
E9: 24h 窗口会把「全部 active 都超窗」渲染成空视图 → 必须 window_empty 自证并给出口
N1-A8: 窗口口径 = max(goal.updated_at, 最新 task.updated_at)，不是只看 goal
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from llm_loop.introspection.goal_coordination import (
    _GOALS_VIEW_LIMIT,
    coordination_snapshot,
    render_coordination,
)
from llm_loop.timekeeping import system_local_now


def _ts(hours_ago: float = 0) -> str:
    return (system_local_now() - timedelta(hours=hours_ago)).isoformat()


def _goal(gid: str, *, status: str = "active", updated: str | None = None) -> dict:
    updated = updated or _ts(0)
    return {
        "id": gid,
        "objective": f"obj-{gid}",
        "status": status,
        "session_id": "sess-test",
        "created_at": updated,
        "updated_at": updated,
        "version": 1,
        "checkpoints": [],
    }


def _write_goals(audit: Path, rows: list[dict]) -> None:
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "goals.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


def _write_task(audit: Path, gid: str, *, updated: str) -> None:
    d = audit / "tasks"
    d.mkdir(parents=True, exist_ok=True)
    row = {
        "task_id": f"{gid}-t1",
        "goal_id": gid,
        "title": "t1",
        "status": "in_progress",
        "created_at": updated,
        "updated_at": updated,
    }
    (d / f"{gid}.jsonl").write_text(
        json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def test_ledger_longer_than_limit_self_reports_truncation(tmp_path):
    """600 行账本 → 只给 500 条，且必须在 capacity/degraded 里说明丢了 100 条."""
    _write_goals(tmp_path, [_goal(f"g{i:04d}") for i in range(600)])
    snap = coordination_snapshot(str(tmp_path), window_hours=0, only_in_flight=False)
    assert len(snap["goals"]) == _GOALS_VIEW_LIMIT
    assert snap["capacity"]["goals_in_ledger"] == 600
    assert snap["capacity"]["truncated"] is True
    assert "goals_truncated: 500/600" in "\n".join(snap["degraded"])


def test_empty_window_self_reports_hidden_active(tmp_path):
    """90 个 active 全部超 24h 窗 → 视图空，但必须说明「账本里还有 90 个」."""
    _write_goals(tmp_path, [_goal(f"g{i:03d}", updated=_ts(48)) for i in range(90)])
    snap = coordination_snapshot(str(tmp_path), window_hours=24, only_in_flight=True)
    assert snap["goals"] == []
    degraded = "\n".join(snap["degraded"])
    assert "window_empty" in degraded
    assert "90 个 active goal" in degraded
    assert "window_hours=0" in degraded


def test_window_uses_task_activity_when_goal_is_stale(tmp_path):
    """N1-A8: goal 48h 前改过、任务 1h 前有写入 → 仍在 24h 窗口内，来源标 task."""
    gid = "g-stale"
    stale = _ts(48)
    _write_goals(tmp_path, [_goal(gid, updated=stale)])
    _write_task(tmp_path, gid, updated=_ts(1))
    snap = coordination_snapshot(str(tmp_path), window_hours=24, only_in_flight=True)
    assert [g["goal_id"] for g in snap["goals"]] == [gid]
    entry = snap["goals"][0]
    assert entry["activity_source"] == "task"
    assert entry["updated_at"] == stale  # goal 侧原始时间不被篡改


def test_capacity_in_render_first_line(tmp_path):
    _write_goals(tmp_path, [_goal("g1")])
    snap = coordination_snapshot(str(tmp_path), window_hours=0)
    first = render_coordination(snap).splitlines()[0]
    assert "capacity=1/500" in first

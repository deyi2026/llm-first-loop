"""L1/L2 独立审查 P1 修复的回归测试（2026-11-01）.

P1-1 deadline_at 无时区 → 与 tz-aware now 比较不再 TypeError
P1-2 单条 goal 记录不可解析 → 整视图不崩，降级条目形状一致且不伪造结论
P1-3 coordination 默认窗口 = 24h 且 only_in_flight=true（设计 §170）
P1-4 环检测进锁 → 两条反向边并发只允许一条通过
P1-5 拒绝文案只指真实出口 → task_* 不再提示 cross_session=true
"""

from __future__ import annotations

import inspect
import threading
from datetime import datetime

from llm_loop.introspection import goal_coordination
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.goal_coordination import coordination_snapshot, write_refusal_text
from llm_loop.introspection.task_store import TaskStore


def _goals(tmp_path) -> tuple[str, str]:
    """两个已登记 goal：跨 goal 判环依赖 GoalStore 里的 goal 记录（边从其任务图读出）."""
    gs = GoalStore(str(tmp_path))
    return gs.create("目标A", session_id="sess-a").id, gs.create("目标B", session_id="sess-a").id


def test_naive_deadline_normalized_and_frontier_survives(tmp_path):
    ts = TaskStore(str(tmp_path))
    ga, gb = _goals(tmp_path)
    ts.create(ga, "上游任务", acceptance=["ok"])
    task = ts.create(
        gb,
        "下游任务",
        acceptance=["ok"],
        blocked_by_goals=[ga],
        deadline_at="2030-01-02T03:04:05",  # 无时区
    )
    assert datetime.fromisoformat(task.deadline_at).tzinfo is not None
    fr = ts.compute_frontier(gb)  # 修复前：naive >= aware → TypeError 冒到工具层
    dumped = str(fr)
    assert "waiting_cross_goal" in dumped and ga in dumped


def test_reverse_edges_concurrently_only_one_succeeds(tmp_path):
    ts = TaskStore(str(tmp_path))
    ga, gb = _goals(tmp_path)
    ts.create(ga, "种子A", acceptance=["ok"])
    ts.create(gb, "种子B", acceptance=["ok"])
    barrier = threading.Barrier(2)
    guard = threading.Lock()
    outcomes: list[str] = []

    def worker(src: str, dst: str) -> None:
        barrier.wait()
        try:
            ts.create(src, f"{src}->{dst}", acceptance=["ok"], blocked_by_goals=[dst])
            out = "ok"
        except ValueError as exc:
            out = "cycle" if "dependency_cycle" in str(exc) else f"other:{exc}"
        with guard:
            outcomes.append(out)

    threads = [
        threading.Thread(target=worker, args=(ga, gb)),
        threading.Thread(target=worker, args=(gb, ga)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 判环与写入在同一临界区：后写者必然看见先写者的边 → 恰好一条被拒
    assert sorted(outcomes) == ["cycle", "ok"], outcomes


def test_malformed_goal_record_degrades_instead_of_crashing(tmp_path, monkeypatch):
    gs = GoalStore(str(tmp_path))
    gs.create("正常目标", session_id="sess-x")

    def boom(*_a, **_k):
        raise ValueError("bad shape")

    monkeypatch.setattr(goal_coordination, "_coordination_goal_entry", boom)
    snap = coordination_snapshot(str(tmp_path), window_hours=0)
    assert snap["ok"] is True
    assert len(snap["goals"]) == 1
    entry = snap["goals"][0]
    assert entry["owned_by"] == "unknown"
    assert entry["version"] == 0
    assert any("不可解析" in d for d in snap["degraded"])


def test_coordination_defaults_match_design():
    sig = inspect.signature(coordination_snapshot)
    assert sig.parameters["window_hours"].default == 24
    assert sig.parameters["only_in_flight"].default is True


def test_task_refusal_offers_no_phantom_cross_session_exit():
    perm = {
        "owner_masked": "a***1",
        "current_masked": "b***2",
        "reason_code": "cross_session_denied",
    }
    task_text = write_refusal_text("G-1", perm, supports_cross_session=False)
    assert "cross_session=true" not in task_text
    assert "owner 会话" in task_text
    goal_text = write_refusal_text("G-1", perm)
    assert "cross_session=true" in goal_text

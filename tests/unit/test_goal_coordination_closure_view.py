# M3 Goal 收口只读视图（DESIGN-20261116 §5）: 判据机械复用 goal_gates，零写路径。
#
# 覆盖:
# - 收口候选: goal_gates 三道门全过才投影，且与 complete_gate 直调输出一致（P1-5）
# - 待补证据: 图收口但证据有缺口 → 列具体缺口（缺 verified 的 task_id / 缺 refs），
#   永不输出「可 complete」结论
# - 停滞候选: activity_at 落后窗口阈值 → 提示 owner 检查（不判僵尸、无 TTL 结论）
# - capacity.truncated=true → 收口候选段标注「视图不完整」且不投影收口候选（宁缺勿假）
# - 时间戳不可读 → 宁缺勿假（不标停滞）
# - 零写路径: 快照前后 goals/lanes/merge_queue 三个账本文件字节不变

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from llm_loop.introspection import goal_coordination
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.goal_coordination import coordination_snapshot, render_coordination
from llm_loop.introspection.goal_gates import complete_gate
from llm_loop.introspection.task_store import TaskStore


class _FakeVerifier:
    # 轻量 verifier: verify(refs) -> report(status=verified)（手法同终局证据门测试）
    def verify(self, refs):
        return SimpleNamespace(status="verified", failing_ref="", checked_at="", refs_digest="d0")


def _goal(tmp_path, title="收口视图测试目标"):
    store = GoalStore(str(tmp_path))
    return store.create(title, session_id="s-view").id


def _done_verified_task(tmp_path, gid):
    ts = TaskStore(str(tmp_path), evidence_verifier=_FakeVerifier())
    t = ts.create(gid, "需要证据的任务", acceptance=["验收"], evidence_required=True)
    ts.update(gid, t.task_id, status="in_progress")
    ts.update(gid, t.task_id, status="done", evidence_refs=["evidence://v1/x"])
    return t.task_id


def _stale_done_unverified_task(tmp_path, gid):
    # 存量数据模拟: done 但 evidence_verification_status=not_checked（手法同终局证据门测试）
    ts = TaskStore(str(tmp_path))
    t = ts.create(gid, "未验证已完成任务", acceptance=["验收"], evidence_required=True)
    ts.update(gid, t.task_id, status="in_progress")
    stale = t.to_dict()
    stale.update(
        status="done",
        evidence_refs=["evidence://v1/x"],
        evidence_verification_status="not_checked",
    )
    ledger = Path(str(tmp_path)) / "tasks" / (gid + ".jsonl")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps(stale, ensure_ascii=False) + "\n")
    return t.task_id


def _snapshot(tmp_path, **kw):
    return coordination_snapshot(str(tmp_path), window_hours=0, **kw)


def _entry(snap, gid):
    return next(g for g in snap["goals"] if g["goal_id"] == gid)


def _gate_host(tmp_path, ctx=None):
    # 与视图内部同形的判据宿主投影（audit_dir + ctx.verifier 透传）
    return SimpleNamespace(audit_dir=str(tmp_path), ctx=ctx)


def _rewrite_goal_updated_at(tmp_path, gid, ts_text):
    p = tmp_path / "goals.jsonl"
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("id") == gid:
            row["updated_at"] = ts_text
        rows.append(row)
    p.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )


def _rewrite_goal_status(tmp_path, gid, status):
    # 直改 goals.jsonl 的 status 行（GoalStore 终态门不可逆，负测只能绕道账本行）
    p = tmp_path / "goals.jsonl"
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("id") == gid:
            row["status"] = status
        rows.append(row)
    p.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )


def test_closure_candidate_projects_when_gates_pass(tmp_path):
    gid = _goal(tmp_path)
    _done_verified_task(tmp_path, gid)
    snap = _snapshot(tmp_path)
    e = _entry(snap, gid)
    assert e["closure"]["kind"] == "candidate"
    assert e["closure"]["gates_source"] == "goal_gates"
    assert e["closure"]["gaps"] == []
    text = render_coordination(snap)
    assert "收口候选" in text
    assert gid in text
    assert "update_goal complete" in text
    assert "判据=goal_gates" in text
    # P1-5 一致性: 判定与 goal_gates 直调输出一致（gate=None ⇔ 收口候选）
    assert complete_gate(_gate_host(tmp_path), gid, {}) is None


def test_pending_evidence_lists_unverified_task_ids(tmp_path):
    gid = _goal(tmp_path)
    tid = _stale_done_unverified_task(tmp_path, gid)
    snap = _snapshot(tmp_path)
    e = _entry(snap, gid)
    assert e["closure"]["kind"] == "pending_evidence"
    gaps = e["closure"]["gaps"]
    assert gaps and any(tid in x for x in gaps)
    text = render_coordination(snap)
    assert "待补证据" in text
    assert tid in text
    assert "不构成" in text  # 永不输出「可 complete」结论
    assert "收口候选" not in text
    # P1-5 一致性: gate=BLOCKED evidence_unverified ⇔ 待补证据（缺 verified）
    gate = complete_gate(_gate_host(tmp_path), gid, {})
    assert str(gate.status) == "blocked"
    assert "reason_code=evidence_unverified" in gate.content


def test_empty_graph_never_candidate_only_missing_refs(tmp_path):
    gid = _goal(tmp_path)  # 空任务图: 视图不自报 evidence_refs → 只能是待补证据
    snap = _snapshot(tmp_path)
    e = _entry(snap, gid)
    assert e["closure"]["kind"] == "pending_evidence"
    assert any("evidence_refs" in x for x in e["closure"]["gaps"])
    assert "收口候选" not in render_coordination(snap)
    gate = complete_gate(_gate_host(tmp_path), gid, {})
    assert str(gate.status) == "blocked"
    assert "reason_code=no_finality_evidence" in gate.content


def test_open_tasks_no_closure_projection(tmp_path):
    gid = _goal(tmp_path)
    TaskStore(str(tmp_path)).create(gid, "未完成任务", acceptance=["验收"])
    snap = _snapshot(tmp_path)
    e = _entry(snap, gid)
    assert e["closure"] is None  # 无收口迹象: 不投影任何收口行
    assert "收口候选" not in render_coordination(snap)
    assert "待补证据" not in render_coordination(snap)
    gate = complete_gate(_gate_host(tmp_path), gid, {})
    assert str(gate.status) == "failure"  # 与 goal_gates 直调一致


def test_gate_probe_unavailable_degrades_not_fabricates(tmp_path, monkeypatch):
    gid = _goal(tmp_path)

    def _boom(self, goal_id, **kwargs):
        raise OSError("ledger unreadable")

    monkeypatch.setattr(
        "llm_loop.introspection.task_store.TaskStore.goal_completion_ready", _boom
    )
    snap = _snapshot(tmp_path)
    e = _entry(snap, gid)
    assert e["closure"] is None  # 账本不可读 → 宁缺勿假，不投影
    assert any("收口判据" in d for d in snap["degraded"])


def test_truncated_view_suppresses_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(goal_coordination, "_GOALS_VIEW_LIMIT", 1)
    gid_a = _goal(tmp_path, "候选目标A")
    _done_verified_task(tmp_path, gid_a)
    _goal(tmp_path, "占位目标B")  # 第二个 goal → 触发 goals 截断
    snap = _snapshot(tmp_path)
    assert snap["capacity"]["truncated"] is True
    text = render_coordination(snap)
    assert "视图不完整" in text  # 收口候选段标注
    assert "✅" not in text  # 截断状态下不投影收口候选（宁缺勿假）


def test_stalled_active_goal_hint_row(tmp_path):
    gid = _goal(tmp_path)
    _rewrite_goal_updated_at(tmp_path, gid, "2020-01-01T00:00:00+08:00")
    snap = _snapshot(tmp_path)  # window_hours=0 → 全量窗口，停滞行可见
    e = _entry(snap, gid)
    assert e["stalled"] is True
    text = render_coordination(snap)
    assert "停滞候选" in text
    assert "不判僵尸" in text  # 提示 owner 检查，不判僵尸/无 TTL 结论


def test_unreadable_timestamp_no_stall_hint(tmp_path):
    gid = _goal(tmp_path)
    _rewrite_goal_updated_at(tmp_path, gid, "not-a-timestamp")
    snap = _snapshot(tmp_path)
    e = _entry(snap, gid)
    assert e["stalled"] is False  # 时间戳不可读 → 宁缺勿假
    assert "停滞候选" not in render_coordination(snap)


def test_complete_goal_never_closure_projection(tmp_path):
    # BUG-11 回归: 已 complete 的 goal 即使三道门全过，也不得再投影收口候选/
    # 待补证据（非 active 不建议再次 complete；goal_gates 判据输出保持不变）
    gid = _goal(tmp_path)
    _done_verified_task(tmp_path, gid)
    assert complete_gate(_gate_host(tmp_path), gid, {}) is None  # 判据本身仍通过
    _rewrite_goal_status(tmp_path, gid, "complete")
    snap = _snapshot(tmp_path, only_in_flight=False)
    e = _entry(snap, gid)
    assert e["status"] == "complete"
    assert e["closure"] is None  # 非 active: 不投影任何收口行
    text = render_coordination(snap)
    assert "收口候选" not in text
    assert "待补证据" not in text


def test_paused_goal_never_closure_projection(tmp_path):
    # BUG-11 回归: GOAL_STATUSES 之外的历史值（如 paused）同样不投影——
    # 未知/异常 status 宁缺勿假，不伪造收口建议
    gid = _goal(tmp_path)
    _done_verified_task(tmp_path, gid)
    _rewrite_goal_status(tmp_path, gid, "paused")
    snap = _snapshot(tmp_path, only_in_flight=False)
    e = _entry(snap, gid)
    assert e["status"] == "paused"
    assert e["closure"] is None
    assert "收口候选" not in render_coordination(snap)
    assert "待补证据" not in render_coordination(snap)


def test_snapshot_zero_write_and_dual_track_fields(tmp_path):
    (tmp_path / "merge_queue.jsonl").write_text(
        json.dumps(
            {
                "queue_id": "q1",
                "lane_id": "l-live",
                "status": "failed",
                "last_preflight": {
                    "checks": [
                        {"check": "base_main_current", "verdict": "fail", "reason_code": "base_stale"}
                    ]
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "lanes.jsonl").write_text(
        json.dumps({"lane_id": "l-live", "status": "active"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    before = {
        name: (tmp_path / name).read_bytes()
        for name in ("merge_queue.jsonl", "lanes.jsonl")
    }
    snap = _snapshot(tmp_path)
    mq = snap["merge_queue"]
    assert mq["actionable_total"] == 1
    assert mq["overall_view_ok"] is True
    assert mq["safe_to_execute"] is True
    for name, blob in before.items():
        assert (tmp_path / name).read_bytes() == blob  # 零写路径: 账本字节不变

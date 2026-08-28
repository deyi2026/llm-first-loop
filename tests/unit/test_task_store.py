"""TaskStore / Task Frontier 单测（DESIGN-20260828）.

覆盖: create 校验（title/acceptance/依赖存在/上限）、replay last-wins、坏行跳过、
状态机合法转移、evidence-gate、blocked_reason 必填、done 重开→下游 premise_stale、
环检测 unreachable、frontier 计算（ready/blocking）、goal_completion_ready、
render_frontier/summary_line、no-change 幂等不落盘。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_loop.introspection.task_store import Task, TaskStore


@pytest.fixture()
def store(tmp_path: Path) -> TaskStore:
    return TaskStore(str(tmp_path))


def _mk(store: TaskStore, gid: str = "G1", title: str = "t", **kw) -> Task:
    return store.create(gid, title, acceptance=["a1"], **kw)


# ---------- create 校验 ----------

def test_create_rejects_empty_title_or_acceptance(store: TaskStore):
    with pytest.raises(ValueError, match="title"):
        store.create("G1", "", acceptance=["a"])
    with pytest.raises(ValueError, match="acceptance"):
        store.create("G1", "t", acceptance=[])


def test_create_rejects_unknown_dependency(store: TaskStore):
    with pytest.raises(ValueError, match="依赖任务不存在"):
        store.create("G1", "t", acceptance=["a"], dependencies=["TASK-X"])


def test_create_limit_per_goal(store: TaskStore):
    for i in range(40):
        store.create("G1", f"t{i}", acceptance=["a"])
    with pytest.raises(ValueError, match="上限"):
        store.create("G1", "over", acceptance=["a"])


def test_goal_isolation(store: TaskStore):
    t1 = _mk(store, "G1", "one")
    t2 = _mk(store, "G2", "two")
    assert t1.task_id.endswith("-001") and t2.task_id.endswith("-001")
    assert store.count_for_goal("G1") == 1 and store.count_for_goal("G2") == 1


# ---------- replay 持久化 ----------

def test_replay_last_wins_and_badline_skip(store: TaskStore, tmp_path: Path):
    t = _mk(store)
    store.update("G1", t.task_id, status="in_progress")
    f = tmp_path / "tasks" / "G1.jsonl"
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"op": "create", "task": {"task_id": t.task_id, "title": "bad"}}) + "\n")
        fh.write("not-json\n")
    tasks = store.list_for_goal("G1")
    assert len(tasks) == 1
    assert tasks[0].status == "in_progress"
    assert tasks[0].title == "t"


def test_no_change_update_writes_nothing(store: TaskStore, tmp_path: Path):
    t = _mk(store)
    f = tmp_path / "tasks" / "G1.jsonl"
    n0 = len(open(f, encoding="utf-8").readlines())
    store.update("G1", t.task_id)  # 全 None
    assert len(open(f, encoding="utf-8").readlines()) == n0


# ---------- 状态机 ----------

def test_transition_matrix(store: TaskStore):
    t = _mk(store)
    with pytest.raises(ValueError, match="非法转移"):
        store.update("G1", t.task_id, status="done")  # pending→done 非法
    store.update("G1", t.task_id, status="in_progress")
    with pytest.raises(ValueError, match="blocked_reason"):
        store.update("G1", t.task_id, status="blocked")
    store.update("G1", t.task_id, status="blocked", blocked_reason="等外部")
    store.update("G1", t.task_id, status="in_progress")
    store.update("G1", t.task_id, status="done", evidence_refs=["evidence://v1/x"])


def test_evidence_gate(store: TaskStore):
    t = _mk(store, evidence_required=True)
    store.update("G1", t.task_id, status="in_progress")
    with pytest.raises(ValueError, match="evidence"):
        store.update("G1", t.task_id, status="done")
    with pytest.raises(ValueError, match="evidence://"):
        store.update("G1", t.task_id, status="done", evidence_refs=["http://x"])
    store.update("G1", t.task_id, status="done", evidence_refs=["evidence://v1/a", "evidence://v1/b"])
    got = store.get("G1", t.task_id)
    assert got.status == "done" and len(got.evidence_refs) == 2


def test_acceptance_revision_leaves_trace(store: TaskStore):
    t = _mk(store)
    store.update("G1", t.task_id, acceptance=["a1", "a2"])
    got = store.get("G1", t.task_id)
    assert got.acceptance == ["a1", "a2"] and got.acceptance_revised is True


# ---------- 依赖 / frontier ----------

def test_dependency_blocking_and_ready(store: TaskStore):
    t1 = _mk(store, "G1", "first")
    t2 = _mk(store, "G1", "second", dependencies=[t1.task_id])
    fr = store.compute_frontier("G1")
    assert [x.task_id for x in fr["ready"]] == [t1.task_id]
    store.update("G1", t1.task_id, status="in_progress")
    store.update("G1", t1.task_id, status="done", evidence_refs=["evidence://v1/d"])
    fr = store.compute_frontier("G1")
    assert [x.task_id for x in fr["ready"]] == [t2.task_id]


def test_reopen_marks_downstream_premise_stale(store: TaskStore):
    t1 = _mk(store, "G1", "base")
    t2 = _mk(store, "G1", "down", dependencies=[t1.task_id])
    for tid in (t1.task_id, t2.task_id):
        store.update("G1", tid, status="in_progress")
        store.update("G1", tid, status="done")
    store.update("G1", t1.task_id, status="in_progress")  # 重开
    assert store.get("G1", t2.task_id).premise_stale is True
    fr = store.compute_frontier("G1")
    assert t2.task_id not in [x.task_id for x in fr["ready"]]


def test_cycle_detection_unreachable(store: TaskStore, tmp_path: Path):
    a = _mk(store, "G1", "a")
    b = _mk(store, "G1", "b", dependencies=[a.task_id])
    # 通过追加 last-wins 行构造环（a 改依赖 b，b 已依赖 a）；create 前向路径挡不了反向补环
    from dataclasses import asdict

    a2 = asdict(store.get("G1", a.task_id))
    a2["dependencies"] = [b.task_id]
    f = tmp_path / "tasks" / "G1.jsonl"
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(a2, ensure_ascii=False) + "\n")
    fr = store.compute_frontier("G1")
    assert set(x.task_id for x in fr["unreachable"]) == {a.task_id, b.task_id}


def test_goal_completion_ready(store: TaskStore):
    t1 = _mk(store, "G1", "one")
    t2 = _mk(store, "G1", "two")
    ok, detail = store.goal_completion_ready("G1")
    assert not ok
    for tid in (t1.task_id, t2.task_id):
        store.update("G1", tid, status="in_progress")
        store.update("G1", tid, status="done")
    ok, detail = store.goal_completion_ready("G1")
    assert ok
    t3 = _mk(store, "G1", "three")
    store.update("G1", t3.task_id, status="in_progress")
    store.update("G1", t3.task_id, status="blocked", blocked_reason="等")
    ok, detail = store.goal_completion_ready("G1")
    assert not ok and "blocked" in detail


# ---------- 渲染 ----------

def test_render_and_summary(store: TaskStore):
    t1 = _mk(store, "G1", "唯一任务")
    store.update("G1", t1.task_id, status="in_progress")
    fr = store.render_frontier("G1")
    assert "[Task Frontier]" in fr and "唯一任务" in fr and "doing" in fr
    s = store.summary_line("G1")
    assert "tasks: 1 open / 1" in s
    assert store.summary_line("G-NOPE") == ""

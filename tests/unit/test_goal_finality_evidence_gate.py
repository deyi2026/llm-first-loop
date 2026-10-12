"""EVO-20260923-6bcc4880 §步骤2: update_goal(complete) 终局证据硬门.

门语义（complete 专用；blocked 是异常出口不走门）:
  G1 任务账本不可读 → BLOCKED probe_unavailable（fail-closed: 不写终局，非照写）
  G2 open>0 → 既有 FAILURE 拒绝（保留）
  G3 evidence_required 任务 evidence_verification_status != verified → BLOCKED evidence_unverified
  G4 done=0（空任务图/全非 done）→ 需自报 evidence_refs 且 verifier 校验 verified
     - 无 refs → BLOCKED no_finality_evidence
     - verifier 未装配 → BLOCKED probe_unavailable
     - 校验未过 → BLOCKED evidence_below_threshold
出口防死锁: 拒绝文案必须指路（补证据/建任务图/人工 waive），不是无路可走。
拒绝的是书写不是记录: BLOCKED ToolResult 本身进历史与事件流。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_store import TaskStore
from llm_loop.introspection.tools_goal import run_update_goal


class _FakeVerifier:
    """轻量 verifier: 只暴露 verify(refs) -> report(status)."""

    def __init__(self, status: str = "verified") -> None:
        self.status = status
        self.calls: list[list[str]] = []

    def verify(self, refs) -> SimpleNamespace:  # noqa: ANN001
        self.calls.append(list(refs))
        return SimpleNamespace(
            status=self.status,
            failing_ref="",
            checked_at="2026-09-24T07:00:00+08:00",
            refs_digest="digest0",
        )


def _host(tmp_path, verifier=None):
    ctx = SimpleNamespace(task_evidence_verifier=verifier)
    return SimpleNamespace(audit_dir=str(tmp_path), ctx=ctx, session_id="s-gate")


def _goal(tmp_path, title="证据门测试目标") -> str:
    store = GoalStore(str(tmp_path))
    g = store.create(title, session_id="s-gate")
    return g.id


def _complete(host, gid, evidence_refs=None):
    args = {"goal_id": gid, "status": "complete"}
    if evidence_refs is not None:
        args["evidence_refs"] = evidence_refs
    return run_update_goal(None, host, args)


# ---------- G4: 空任务图 ----------

def test_empty_task_graph_complete_without_refs_blocked(tmp_path):
    host = _host(tmp_path, verifier=_FakeVerifier())
    gid = _goal(tmp_path)
    result = _complete(host, gid)
    assert result.status == ToolResultStatus.BLOCKED
    assert "reason_code=no_finality_evidence" in result.content
    # 防死锁: 出口指路
    assert "waive" in result.content or "人工" in result.content


def test_empty_task_graph_complete_with_verified_refs_passes(tmp_path):
    verifier = _FakeVerifier("verified")
    host = _host(tmp_path, verifier=verifier)
    gid = _goal(tmp_path)
    result = _complete(host, gid, evidence_refs=["evidence://v1/abc"])
    assert result.status == ToolResultStatus.SUCCESS
    assert verifier.calls and verifier.calls[0] == ["evidence://v1/abc"]


def test_empty_task_graph_complete_with_failing_refs_blocked(tmp_path):
    host = _host(tmp_path, verifier=_FakeVerifier("blob_missing"))
    gid = _goal(tmp_path)
    result = _complete(host, gid, evidence_refs=["evidence://v1/gone"])
    assert result.status == ToolResultStatus.BLOCKED
    assert "reason_code=evidence_below_threshold" in result.content
    assert "blob_missing" in result.content


def test_empty_task_graph_complete_no_verifier_blocked(tmp_path):
    host = _host(tmp_path, verifier=None)
    gid = _goal(tmp_path)
    result = _complete(host, gid, evidence_refs=["evidence://v1/abc"])
    assert result.status == ToolResultStatus.BLOCKED
    assert "reason_code=probe_unavailable" in result.content


# ---------- G3: evidence_required 任务未 verified ----------

def test_complete_blocked_by_unverified_required_task(tmp_path):
    host = _host(tmp_path, verifier=_FakeVerifier())
    gid = _goal(tmp_path)
    # 存量数据模拟: verifier 强制上线前的 done 行（evidence_verification_status=not_checked）
    import json as _json
    from pathlib import Path as _Path

    ts = TaskStore(str(tmp_path))
    t = ts.create(gid, "需要证据的任务", acceptance=["验收1"], evidence_required=True)
    ts.update(gid, t.task_id, status="in_progress")
    stale = t.to_dict()
    stale.update(
        status="done",
        evidence_refs=["evidence://v1/x"],
        evidence_verification_status="not_checked",
    )
    ledger = _Path(str(tmp_path)) / "tasks" / f"{gid}.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as f:
        f.write(_json.dumps(stale, ensure_ascii=False) + "\n")
    result = _complete(host, gid)
    assert result.status == ToolResultStatus.BLOCKED
    assert "reason_code=evidence_unverified" in result.content
    assert t.task_id in result.content


def test_complete_passes_when_required_task_verified(tmp_path):
    verifier = _FakeVerifier("verified")
    host = _host(tmp_path, verifier=verifier)
    gid = _goal(tmp_path)
    ts = TaskStore(str(tmp_path), evidence_verifier=verifier)
    t = ts.create(gid, "需要证据的任务", acceptance=["验收1"], evidence_required=True)
    ts.update(gid, t.task_id, status="in_progress")
    ts.update(gid, t.task_id, status="done", evidence_refs=["evidence://v1/x"])
    result = _complete(host, gid)
    assert result.status == ToolResultStatus.SUCCESS


# ---------- G1: 账本不可读 fail-closed ----------

def test_complete_fails_closed_when_task_store_unreadable(tmp_path, monkeypatch):
    host = _host(tmp_path, verifier=_FakeVerifier())
    gid = _goal(tmp_path)

    def _boom(self, goal_id, **kwargs):  # noqa: ANN001
        raise OSError("ledger unreadable")

    monkeypatch.setattr("llm_loop.introspection.task_store.TaskStore.goal_completion_ready", _boom)
    result = _complete(host, gid)
    assert result.status == ToolResultStatus.BLOCKED
    assert "reason_code=probe_unavailable" in result.content


# ---------- G2: 既有 open 拒绝保持 ----------

def test_complete_with_open_task_still_rejected(tmp_path):
    host = _host(tmp_path, verifier=_FakeVerifier())
    gid = _goal(tmp_path)
    TaskStore(str(tmp_path)).create(gid, "未完成任务", acceptance=["验收"])
    result = _complete(host, gid)
    assert result.status == ToolResultStatus.FAILURE  # 既有语义不变
    assert "open 任务" in result.content


# ---------- blocked 不走门 ----------

def test_blocked_status_bypasses_evidence_gate(tmp_path):
    host = _host(tmp_path, verifier=_FakeVerifier())
    gid = _goal(tmp_path)  # 空任务图、无 refs —— blocked 仍应放行
    result = run_update_goal(
        None, host, {"goal_id": gid, "status": "blocked", "reason": "外部依赖不可用"}
    )
    assert result.status == ToolResultStatus.SUCCESS


# ---------- 诊断优先级: goal 记录损坏不被证据门掩盖 ----------

def test_corrupted_goal_ledger_reports_corruption_not_gate(tmp_path):
    """goals.jsonl 损坏 → 优先报 [goal 存储损坏]，而非证据门 BLOCKED。"""
    from llm_loop.introspection.goal import GoalStore

    store = GoalStore(str(tmp_path))
    g = store.create("损坏目标", session_id="s-gate")
    ledger = tmp_path / "goals.jsonl"
    ledger.write_text('{"id": "x", "titl', encoding="utf-8")  # 半行 JSON
    host = _host(tmp_path, verifier=_FakeVerifier())
    result = _complete(host, g.id)
    assert result.status == ToolResultStatus.FAILURE
    assert "[goal 存储损坏]" in result.content

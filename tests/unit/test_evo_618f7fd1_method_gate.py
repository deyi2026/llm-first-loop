"""EVO-20260923-618f7fd1 ①②③: 方法 use 回记——收尾提醒 / goal 级硬门 / 开场 active 卡清单.

三条链路的机械验证（不测模型行为，只测程序面）：
① method_injection.scan_method_use_ledger + build_use_reminder_message（状态层载体）
② GoalStore.method_use_gate + task_update 门禁（默认关、fail-open、会话归属）
③ build_active_cards_message + has_active_cards_injection（引用层、祈使句降级）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_loop.core import run_context
from llm_loop.core.injection_labels import InjectionLayer
from llm_loop.core.loop.engine_services.method_injection import (
    build_active_cards_message,
    build_use_reminder_message,
    has_active_cards_injection,
    scan_method_use_ledger,
)
from llm_loop.core.trace_leak.invariant import metadata_satisfies_invariant
from llm_loop.introspection import tools_task
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_evidence import TaskEvidenceVerificationReport
from llm_loop.introspection.task_store import TaskStore
from llm_loop.methods.store import MethodStore

# ---------- ① 收尾提醒：tool_trace 扫描与消息载体 ----------


@pytest.fixture(autouse=True)
def _isolate_session_contextvar():
    """隔离 run_context.current_session_id：先清空、测试后恢复原值。

    门禁测试在用例内 set("sess-gate")；若不恢复，残留 ContextVar 会污染
    同进程后续"缺上下文必须失败"类用例（test_missing_context_authority 等）。
    """
    token = run_context.current_session_id.set("")
    yield
    run_context.current_session_id.reset(token)


def test_ledger_counts_exact_hydration_only():
    rows = [
        {"id": "t1", "name": "search_records", "arguments": {"kind": "method", "query": "method:abc"}, "status": "success"},
        {"id": "t2", "name": "search_records", "arguments": {"kind": "method", "query": "导航发现"}, "status": "success"},  # 发现式查询不计
        {"id": "t3", "name": "search_records", "arguments": {"kind": "method", "query": "method:def"}, "status": "error"},  # 失败不计
        {"id": "t4", "name": "search_records", "arguments": {"kind": "experience", "query": "method:zzz"}, "status": "success"},  # 非 method kind 不计
        {"id": "t5", "name": "method_manage", "arguments": {"action": "record_use", "method_ref": "method:abc"}, "status": "success"},
        {"id": "t6", "name": "method_manage", "arguments": {"action": "save_candidate", "name": "x"}, "status": "success"},  # 非 record_use 不计
    ]
    ledger = scan_method_use_ledger(rows)
    assert ledger.hydrated == ("method:abc",)
    assert ledger.recorded == ("method:abc",)
    assert ledger.unrecorded() == ()


def test_ledger_reports_unrecorded_refs():
    rows = [
        {"name": "search_records", "arguments": {"kind": "method", "query": "method:x"}, "status": "success"},
        {"name": "search_records", "arguments": {"kind": "method", "query": "method:y"}, "status": "success"},
        {"name": "method_manage", "arguments": {"action": "record_use", "method_ref": "method:y"}, "status": "success"},
    ]
    assert scan_method_use_ledger(rows).unrecorded() == ("method:x",)


def test_reminder_message_is_status_layer_program_origin():
    msg = build_use_reminder_message(("method:x", "method:y"))
    assert msg.role == "user"
    assert msg.metadata.get("injection_kind") == "method_use_reminder"
    assert msg.metadata.get("origin_layer") == InjectionLayer.STATUS.value
    assert metadata_satisfies_invariant(msg.metadata)
    assert "method:x" in msg.content and "method:y" in msg.content


def test_reminder_never_fires_without_exact_hydration():
    rows = [{"name": "search_records", "arguments": {"kind": "method", "query": "导航"}, "status": "success"}]
    assert scan_method_use_ledger(rows).unrecorded() == ()


# ---------- ② goal 级硬门 ----------

class _StubVerifier:
    def verify(self, refs):
        return TaskEvidenceVerificationReport(status="verified", checked_at="now", refs_digest="d", checked_count=len(refs), failing_ref="")


class _Ctx:
    task_evidence_verifier = _StubVerifier()


def _make_goal_and_task(audit: Path, gate: bool):
    gs = GoalStore(str(audit))
    ts = TaskStore(str(audit))
    goal = gs.create("目标", session_id="sess-gate", method_use_gate=gate)
    task = ts.create(goal.id, "T", acceptance=["验收"], evidence_required=True)
    ts.update(goal.id, task.task_id, status="in_progress")
    return gs, ts, goal, task


def _host(audit: Path, methods: Path | None):
    class Host:
        pass

    h = Host()
    h.audit_dir = str(audit)
    h.ctx = _Ctx()
    if methods is not None:
        h.method_store = MethodStore(str(methods))
    return h


def test_goal_method_use_gate_field_roundtrip(tmp_path):
    gs = GoalStore(str(tmp_path / "audit"))
    g1 = gs.create("开", method_use_gate=True)
    g2 = gs.create("关")
    assert g1.method_use_gate is True and g2.method_use_gate is False
    assert gs.get(goal_id=g1.id)["method_use_gate"] is True
    assert gs.get(goal_id=g2.id)["method_use_gate"] is False


def test_goal_old_record_without_gate_defaults_off(tmp_path):
    audit = tmp_path / "audit"
    audit.mkdir()
    goal_file = audit / "goals.jsonl"
    goal_file.write_text(json.dumps({"id": "GOAL-X", "objective": "旧", "status": "active"}, ensure_ascii=False) + "\n")
    assert GoalStore(str(audit)).get(goal_id="GOAL-X").get("method_use_gate") in (None, False)


def test_gate_blocks_done_without_record_use(tmp_path):
    audit, methods = tmp_path / "audit", tmp_path / "methods"
    _, _, goal, task = _make_goal_and_task(audit, gate=True)
    run_context.current_session_id.set("sess-gate")
    r = tools_task.run_task_update(_Ctx(), _host(audit, methods), {
        "goal_id": goal.id, "task_id": task.task_id, "status": "done",
        "evidence_refs": ["evidence://v1/t-1"],
    })
    assert r.status.name == "FAILURE"
    assert "method_use_gate" in r.content


def test_gate_passes_with_explicit_declaration(tmp_path):
    audit, methods = tmp_path / "audit", tmp_path / "methods"
    _, _, goal, task = _make_goal_and_task(audit, gate=True)
    run_context.current_session_id.set("sess-gate")
    r = tools_task.run_task_update(_Ctx(), _host(audit, methods), {
        "goal_id": goal.id, "task_id": task.task_id, "status": "done",
        "evidence_refs": ["evidence://v1/t-1"], "method_no_contact": True,
    })
    assert r.status.name == "SUCCESS"


def test_gate_passes_with_session_record_use(tmp_path):
    audit, methods = tmp_path / "audit", tmp_path / "methods"
    _, _, goal, task = _make_goal_and_task(audit, gate=True)
    card = methods / "commit-then-verify-000000000001"
    card.mkdir(parents=True)
    (card / "METHOD.md").write_text("---\nid: commit-then-verify-000000000001\nname: c\n---\n正文")
    MethodStore(str(methods)).record_use(
        "method:commit-then-verify-000000000001",
        episode_ref="episode:x", decision="applied", session_id="sess-gate",
    )
    run_context.current_session_id.set("sess-gate")
    r = tools_task.run_task_update(_Ctx(), _host(audit, methods), {
        "goal_id": goal.id, "task_id": task.task_id, "status": "done",
        "evidence_refs": ["evidence://v1/t-1"],
    })
    assert r.status.name == "SUCCESS"


def test_gate_ignores_other_session_record_use(tmp_path):
    audit, methods = tmp_path / "audit", tmp_path / "methods"
    _, _, goal, task = _make_goal_and_task(audit, gate=True)
    card = methods / "commit-then-verify-000000000002"
    card.mkdir(parents=True)
    (card / "METHOD.md").write_text("---\nid: commit-then-verify-000000000002\nname: c\n---\n正文")
    MethodStore(str(methods)).record_use(
        "method:commit-then-verify-000000000002",
        episode_ref="episode:x", decision="applied", session_id="sess-other",
    )
    run_context.current_session_id.set("sess-gate")
    r = tools_task.run_task_update(_Ctx(), _host(audit, methods), {
        "goal_id": goal.id, "task_id": task.task_id, "status": "done",
        "evidence_refs": ["evidence://v1/t-1"],
    })
    assert r.status.name == "FAILURE"


def test_gate_off_by_default_and_not_done_never_blocks(tmp_path):
    audit, methods = tmp_path / "audit", tmp_path / "methods"
    _, ts, goal, task = _make_goal_and_task(audit, gate=False)
    run_context.current_session_id.set("sess-gate")
    r = tools_task.run_task_update(_Ctx(), _host(audit, methods), {
        "goal_id": goal.id, "task_id": task.task_id, "status": "done",
        "evidence_refs": ["evidence://v1/t-1"],
    })
    assert r.status.name == "SUCCESS"
    t2 = ts.create(goal.id, "T2", acceptance=["验收"], evidence_required=True)
    r2 = tools_task.run_task_update(_Ctx(), _host(audit, methods), {
        "goal_id": goal.id, "task_id": t2.task_id, "status": "in_progress",
    })
    assert r2.status.name == "SUCCESS"


def test_gate_fail_open_without_method_store(tmp_path):
    audit = tmp_path / "audit"
    _, _, goal, task = _make_goal_and_task(audit, gate=True)
    run_context.current_session_id.set("sess-gate")
    r = tools_task.run_task_update(_Ctx(), _host(audit, None), {
        "goal_id": goal.id, "task_id": task.task_id, "status": "done",
        "evidence_refs": ["evidence://v1/t-1"],
    })
    assert r.status.name == "SUCCESS"


# ---------- ③ 开场 active 卡清单 ----------

def _write_card(methods: Path, cid: str, name: str, desc: str, *, promote: bool = True):
    """写卡并按真实生命周期 candidate→qualified→active 晋升（需 promotion=pass qualification）。"""
    d = methods / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / "METHOD.md").write_text(f"---\nid: {cid}\nname: {name}\ndescription: {desc}\n---\n正文")
    if not promote:
        return
    store = MethodStore(str(methods))
    ref = f"method:{cid}"
    store.record_qualification(ref, task_ref="episode:fixture-qual-1", verdict="pass", promotion="pass")
    store.update_status(ref, "qualified")
    store.update_status(ref, "active")


def test_active_cards_message_lists_active_only(tmp_path):
    methods = tmp_path / "methods"
    _write_card(methods, "alpha-000000000001", "alpha", "触发条件 A")
    _write_card(methods, "beta-000000000001", "beta", "触发条件 B")
    msg = build_active_cards_message(str(methods))
    assert msg is not None
    assert msg.metadata.get("injection_kind") == "method_active_cards"
    assert msg.metadata.get("origin_layer") == InjectionLayer.REFERENCE.value
    assert metadata_satisfies_invariant(msg.metadata)
    # 活跃卡在（种子卡默认 active）；候选语义不在本测试范围（无 seed 时不注入）
    assert "alpha" in msg.content


def test_active_cards_message_none_when_empty(tmp_path):
    assert build_active_cards_message(str(tmp_path / "nothing")) is None


def test_active_cards_imperative_description_degrades(tmp_path):
    methods = tmp_path / "methods"
    _write_card(methods, "gamma-000000000001", "gamma", "必须先做 X 再做 Y")
    msg = build_active_cards_message(str(methods))
    assert msg is not None
    # 整段触发祈使句过滤 → 降级为仅名称清单，消息仍可用
    assert "gamma" in msg.content


def test_active_cards_injection_idempotency_probe():
    from llm_loop.core.injection_labels import origin_metadata
    from llm_loop.core.message import Message, MessageSource

    class Sess:
        messages = [
            Message(role="user", source=MessageSource.USER, content="hi", metadata={}),
            Message(
                role="user", source=MessageSource.USER, content="卡片",
                metadata=origin_metadata(InjectionLayer.REFERENCE, injection_kind="method_active_cards"),
            ),
        ]

    assert has_active_cards_injection(Sess()) is True
    assert has_active_cards_injection(type("S", (), {"messages": []})()) is False

"""Regression for long-running, multi-thousand-message handoff.

New conversation must be small and source-attributed, even when source is busy.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.core.message import Message, MessageSource
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_store import TaskStore
from llm_loop.web import build_app


def _client(engine):
    return TestClient(build_app(engine=engine))


def test_handoff_creates_empty_session_with_goal_and_task(build_test_engine):
    engine, _ = build_test_engine([])
    sid = engine.session.create(model_override="minimax/MiniMax-M3.1-Flash")
    src = engine.session.load(sid)
    src.title = "长任务测试"
    src.messages.append(Message(role="user", content="请按测试计划实施", source=MessageSource.USER))
    for n in range(1800):
        src.messages.append(Message(role="tool", content=f"tool-{n}", source=MessageSource.USER, tool_name="read_file"))
    src.messages.append(Message(role="user", content="现在交接到新会话继续", source=MessageSource.USER))
    engine.session.save(src)
    audit = Path(engine.settings.data_dir) / "audit"
    goal = GoalStore(audit).create("独立跑完 Agent 评估", session_id=sid)
    TaskStore(audit).create(goal.id, "完成盲审回归", acceptance=["真实回执"])

    old_path = Path(engine.session._path(sid))
    old_bytes = old_path.read_bytes()
    response = _client(engine).post(f"/api/v1/sessions/{sid}/handoff")
    assert response.status_code == 200, response.text
    data = response.json()
    new_id = data["new_session_id"]
    assert new_id != sid
    assert data["source_session_id"] == sid
    assert data["inherited_message_count"] == 0
    assert data["inherited_event_count"] == 0
    assert data["source_message_count"] == 1802
    assert data["goal_id"] == goal.id
    assert data["open_task_count"] == 1
    assert "完成盲审回归" in data["continuation_prompt"]
    assert "现在交接到新会话继续" in data["continuation_prompt"]
    assert len(data["continuation_prompt"]) <= 4900
    child = engine.session.load(new_id)
    assert child.messages == []
    assert child.parent_id == sid
    assert child.model_override == src.model_override
    assert engine.session.load(sid).messages == src.messages
    assert old_path.read_bytes() == old_bytes


def test_handoff_never_imports_other_sessions_goal(build_test_engine):
    engine, _ = build_test_engine([])
    source = engine.session.create()
    another = engine.session.create()
    GoalStore(Path(engine.settings.data_dir) / "audit").create(
        "秘密的另一个任务", session_id=another,
    )
    data = _client(engine).post(f"/api/v1/sessions/{source}/handoff").json()
    assert data["goal_id"] == ""
    assert data["goal_status"] == "unavailable"
    assert "秘密的另一个任务" not in data["continuation_prompt"]


def test_handoff_missing_or_archived_source_is_rejected(build_test_engine):
    engine, _ = build_test_engine([])
    client = _client(engine)
    assert client.post("/api/v1/sessions/missing/handoff").status_code == 404
    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.status = "archived"
    engine.session.save(sess)
    assert client.post(f"/api/v1/sessions/{sid}/handoff").status_code == 409


def test_handoff_created_while_source_run_lease_is_busy(build_test_engine):
    """Source run must remain untouched; handoff may prepare an independent session."""
    engine, _ = build_test_engine([])
    sid = engine.session.create()
    with engine.session.run_lease(sid) as acquired:
        assert acquired is True
        response = _client(engine).post(f"/api/v1/sessions/{sid}/handoff")
        assert response.status_code == 200
        assert engine.session.load(response.json()["new_session_id"]).messages == []
    assert engine.session.exists(sid)


def test_handoff_reloads_prompt_only_for_prepared_child(build_test_engine):
    engine, _ = build_test_engine([])
    sid = engine.session.create()
    client = _client(engine)
    assert client.get("/api/v1/capabilities").json()["capabilities"]["handoff"] is True
    assert client.get(f"/api/v1/sessions/{sid}/handoff").status_code == 404
    created = client.post(f"/api/v1/sessions/{sid}/handoff").json()
    child = created["new_session_id"]
    reloaded = client.get(f"/api/v1/sessions/{child}/handoff")
    assert reloaded.status_code == 200
    assert reloaded.json()["continuation_prompt"] == created["continuation_prompt"]
    assert reloaded.json()["source_session_id"] == sid


def test_handoff_event_log_replay_keeps_identity_and_snapshot(tmp_path):
    """No second JSON-only metadata update: EventStore replay must match JSON."""
    from llm_loop.core.session import SessionStore
    from llm_loop.event_log.store import EventStore
    from llm_loop.introspection.session_handoff import create_handoff_session

    event_store = EventStore(tmp_path / "events")
    store = SessionStore(
        tmp_path / "sessions", event_store=event_store,
        read_path_source="event_log",
    )
    sid = store.create(model_override="minimax/MiniMax-M3.1-Flash")
    source = store.load(sid)
    source.messages.append(Message(role="user", content="请先创建交接新会话", source=MessageSource.USER))
    store.save(source)
    result = create_handoff_session(store, sid, audit_dir=tmp_path / "audit")
    child = store.load(result["new_session_id"])
    assert child.parent_id == sid
    assert child.messages == []
    assert child.model_override == "minimax/MiniMax-M3.1-Flash"
    assert child.branch_summary == result["continuation_prompt"]
    events = event_store.read(child.session_id)
    assert len(events) == 1
    assert events[0].type == "session.created"
    assert events[0].payload["parent_id"] == sid
    assert events[0].payload["branch_summary"] == result["continuation_prompt"]


def test_web_handoff_does_not_adopt_cli_or_eval_session(build_test_engine):
    """Handoff must not bypass the existing Web/Feishu ingress ownership fence."""
    engine, _ = build_test_engine([])
    sid = engine.session.create()
    source = engine.session.load(sid)
    source.channel = "cli"
    engine.session.save(source)
    resp = _client(engine).post(f"/api/v1/sessions/{sid}/handoff")
    assert resp.status_code == 409
    assert resp.json()["error"] == "session_ingress_mismatch"

from __future__ import annotations

import hashlib
from pathlib import Path

from llm_loop.core.message import ToolCall
from llm_loop.core.session import SessionStore
from llm_loop.core.tool_execution_journal import ToolExecutionJournal
from llm_loop.event_log.store import EventStore
from llm_loop.tools.builtin.edit_file import EditFileTool
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _journal(tmp_path: Path, *, enabled: bool = True):
    events = EventStore(tmp_path / "events", enabled=enabled)
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    journal = ToolExecutionJournal(
        event_store=events,
        result_root=tmp_path / "tool-results",
        session_store=sessions,
    )
    return journal, events, sessions, sid


def _started_edit(journal: ToolExecutionJournal, sessions: SessionStore, sid: str):
    call = ToolCall(
        id="call-edit-effect",
        name="edit_file",
        arguments={"path": "target.txt", "old_string": "BEFORE", "new_string": "AFTER"},
    )
    sess = sessions.load(sid)
    execution_id = journal.declared(sess, call, round_no=1)
    assert execution_id
    assert journal.started(sid, execution_id=execution_id, round_no=1, call=call)
    return call, execution_id


def test_current_started_edit_crash_window_has_no_execution_bound_effect_fact(
    tmp_path: Path,
) -> None:
    """RED baseline proof: target bytes can change while WAL still has only declared/started."""
    journal, events, sessions, sid = _journal(tmp_path)
    call, _execution_id = _started_edit(journal, sessions, sid)
    target = tmp_path / "target.txt"
    target.write_text("BEFORE\n", encoding="utf-8")

    result = EditFileTool().execute(path=str(target), old_string="BEFORE", new_string="AFTER")
    assert result.status.value == "success"
    assert target.read_text(encoding="utf-8") == "AFTER\n"
    # Simulate crash before ToolExecutionJournal.finished().
    effect_events = [e for e in events.read(sid) if e.type.startswith("tool.execution.effect_")]
    assert effect_events == []
    wal_types = [e.type for e in events.read(sid) if e.type.startswith("tool.execution.")]
    assert wal_types == ["tool.execution.declared", "tool.execution.started"]
    assert call.name == "edit_file"


def test_effect_prepared_must_be_durable_before_edit_file_replaces_target(
    tmp_path: Path, monkeypatch
) -> None:
    journal, _events, sessions, sid = _journal(tmp_path)
    call, execution_id = _started_edit(journal, sessions, sid)
    target = tmp_path / "target.txt"
    target.write_text("BEFORE\n", encoding="utf-8")

    original_append = journal._append_event  # noqa: SLF001 - deterministic durability fault

    def fail_prepared(session_id: str, event_type: str, payload: dict):
        if event_type == "tool.execution.effect_prepared":
            return None
        return original_append(session_id, event_type, payload)

    monkeypatch.setattr(journal, "_append_event", fail_prepared)
    with journal.effect_context(
        session_id=sid,
        execution_id=execution_id,
        round_no=1,
        call=call,
        workspace_root=str(tmp_path),
    ):
        result = EditFileTool().execute(path=str(target), old_string="BEFORE", new_string="AFTER")

    assert result.status.value == "error"
    assert result.error_type == "EffectPreparedUnavailable"
    assert target.read_text(encoding="utf-8") == "BEFORE\n"


def test_successful_edit_persists_exact_prepared_and_observed_effect_facts(tmp_path: Path) -> None:
    journal, events, sessions, sid = _journal(tmp_path)
    call, execution_id = _started_edit(journal, sessions, sid)
    target = tmp_path / "target.txt"
    before = b"BEFORE\n"
    after = b"AFTER\n"
    target.write_bytes(before)

    with journal.effect_context(
        session_id=sid,
        execution_id=execution_id,
        round_no=1,
        call=call,
        workspace_root=str(tmp_path),
    ):
        result = EditFileTool().execute(path=str(target), old_string="BEFORE", new_string="AFTER")

    assert result.status.value == "success"
    effect_events = [e for e in events.read(sid) if e.type.startswith("tool.execution.effect_")]
    assert [e.type for e in effect_events] == [
        "tool.execution.effect_prepared",
        "tool.execution.effect_observed",
    ]
    prepared, observed = [e.payload for e in effect_events]
    assert prepared["execution_id"] == execution_id
    assert prepared["effect_kind"] == "file_replace"
    assert prepared["workspace_root"] == str(tmp_path.resolve())
    assert prepared["canonical_path"] == str(target.resolve())
    assert prepared["before_sha256"] == _sha(before)
    assert prepared["expected_after_sha256"] == _sha(after)
    assert observed["actual_after_sha256"] == _sha(after)
    assert observed["matches_expected"] is True
    assert observed["actual_size"] == len(after)


def test_crash_after_replace_before_observed_recovers_current_expected_match_without_causation(
    tmp_path: Path, monkeypatch
) -> None:
    journal, events, sessions, sid = _journal(tmp_path)
    call, execution_id = _started_edit(journal, sessions, sid)
    target = tmp_path / "target.txt"
    target.write_text("BEFORE\n", encoding="utf-8")

    monkeypatch.setattr(journal, "effect_observed", lambda **_kwargs: False)
    with journal.effect_context(
        session_id=sid,
        execution_id=execution_id,
        round_no=1,
        call=call,
        workspace_root=str(tmp_path),
    ):
        result = EditFileTool().execute(path=str(target), old_string="BEFORE", new_string="AFTER")
    assert result.status.value == "success"
    assert [e.type for e in events.read(sid) if e.type.startswith("tool.execution.effect_")] == [
        "tool.execution.effect_prepared"
    ]

    fresh = ToolExecutionJournal(
        event_store=events,
        result_root=tmp_path / "fresh-results",
        session_store=sessions,
    )
    snapshot = fresh.effect_snapshot(sid, execution_id, workspace_root=str(tmp_path))
    assert snapshot is not None
    assert snapshot["effect_state"] == "current_matches_expected_after"
    assert snapshot["execution_outcome"] == "unknown"
    assert snapshot["causation_proven"] is False
    assert snapshot["auto_reexecuted"] is False


def test_prepared_current_before_is_only_mechanical_match_not_proof_of_nonexecution(
    tmp_path: Path,
) -> None:
    journal, _events, _sessions, sid = _journal(tmp_path)
    target = tmp_path / "target.txt"
    before = b"BEFORE\n"
    after = b"AFTER\n"
    target.write_bytes(before)

    assert journal.effect_prepared(
        sid,
        execution_id="exec-before",
        round_no=1,
        tool_call_id="call-before",
        tool_name="edit_file",
        workspace_root=str(tmp_path),
        canonical_path=str(target),
        effect_kind="file_replace",
        before_bytes=before,
        expected_after_bytes=after,
    )
    snapshot = journal.effect_snapshot(sid, "exec-before", workspace_root=str(tmp_path))
    assert snapshot is not None
    assert snapshot["effect_state"] == "current_matches_before"
    assert snapshot["execution_outcome"] == "unknown"
    assert snapshot["causation_proven"] is False
    assert snapshot["auto_reexecuted"] is False


def test_prepared_current_divergence_is_visible_and_never_overwritten(tmp_path: Path) -> None:
    journal, _events, _sessions, sid = _journal(tmp_path)
    target = tmp_path / "target.txt"
    before = b"BEFORE\n"
    after = b"AFTER\n"
    target.write_bytes(before)
    assert journal.effect_prepared(
        sid,
        execution_id="exec-diverged",
        round_no=1,
        tool_call_id="call-diverged",
        tool_name="edit_file",
        workspace_root=str(tmp_path),
        canonical_path=str(target),
        effect_kind="file_replace",
        before_bytes=before,
        expected_after_bytes=after,
    )
    target.write_bytes(b"OTHER-WRITER\n")

    snapshot = journal.effect_snapshot(sid, "exec-diverged", workspace_root=str(tmp_path))
    assert snapshot is not None
    assert snapshot["effect_state"] == "current_diverged"
    assert target.read_bytes() == b"OTHER-WRITER\n"
    assert snapshot["auto_reexecuted"] is False


def test_effect_recovery_is_owner_and_workspace_scoped(tmp_path: Path) -> None:
    journal, _events, _sessions, sid = _journal(tmp_path)
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    workspace_a.mkdir()
    workspace_b.mkdir()
    target = workspace_a / "target.txt"
    target.write_bytes(b"A\n")
    assert journal.effect_prepared(
        sid,
        execution_id="exec-scope",
        round_no=1,
        tool_call_id="call-scope",
        tool_name="edit_file",
        workspace_root=str(workspace_a),
        canonical_path=str(target),
        effect_kind="file_replace",
        before_bytes=b"A\n",
        expected_after_bytes=b"B\n",
    )

    stale = journal.effect_snapshot(sid, "exec-scope", workspace_root=str(workspace_b))
    assert stale is not None
    assert stale["effect_state"] == "workspace_mismatch"
    assert stale["path_inspected"] is False
    assert (
        journal.effect_snapshot("different-session", "exec-scope", workspace_root=str(workspace_a))
        is None
    )


def test_event_store_disabled_keeps_legacy_edit_behavior_without_fake_durability(
    tmp_path: Path,
) -> None:
    journal, events, _sessions, sid = _journal(tmp_path, enabled=False)
    target = tmp_path / "target.txt"
    target.write_text("BEFORE\n", encoding="utf-8")
    call = ToolCall(
        id="legacy-edit",
        name="edit_file",
        arguments={"path": str(target), "old_string": "BEFORE", "new_string": "AFTER"},
    )
    with journal.effect_context(
        session_id=sid,
        execution_id="legacy-exec",
        round_no=1,
        call=call,
        workspace_root=str(tmp_path),
    ):
        result = EditFileTool().execute(path=str(target), old_string="BEFORE", new_string="AFTER")
    assert result.status.value == "success"
    assert target.read_text(encoding="utf-8") == "AFTER\n"
    assert events.read(sid) == []
    assert journal.effect_snapshot(sid, "legacy-exec", workspace_root=str(tmp_path)) is None


def test_generic_execute_command_does_not_infer_write_set_from_shell_text(tmp_path: Path) -> None:
    journal, events, _sessions, sid = _journal(tmp_path)
    target = tmp_path / "shell-created.txt"
    call = ToolCall(
        id="shell-effect-unknown",
        name="execute_command",
        arguments={"command": f"printf shell > {target}"},
    )
    with journal.effect_context(
        session_id=sid,
        execution_id="exec-shell",
        round_no=1,
        call=call,
        workspace_root=str(tmp_path),
    ):
        result = ExecuteCommandTool(timeout_s=5).execute(command=call.arguments["command"])
    assert result.status.value == "success"
    assert target.read_text(encoding="utf-8") == "shell"
    assert [e for e in events.read(sid) if e.type.startswith("tool.execution.effect_")] == []


def test_started_unknown_recovery_receipt_exposes_mechanical_effect_state(tmp_path: Path) -> None:
    from llm_loop.core.message import Message, MessageSource
    from llm_loop.core.run_context import current_workspace_root

    journal, _events, sessions, sid = _journal(tmp_path)
    target = tmp_path / "target.txt"
    before = b"BEFORE\n"
    after = b"AFTER\n"
    target.write_bytes(before)
    call = ToolCall(
        id="recover-effect",
        name="edit_file",
        arguments={"path": "target.txt", "old_string": "BEFORE", "new_string": "AFTER"},
    )
    sess = sessions.load(sid)
    sess.messages.append(
        Message(
            role="assistant",
            content="",
            source=MessageSource.USER,
            tool_calls=[
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": "{}"},
                }
            ],
        )
    )
    sessions.save(sess)
    execution_id = journal.declared(sess, call, round_no=1)
    assert journal.started(sid, execution_id=execution_id, round_no=1, call=call)
    assert journal.effect_prepared(
        sid,
        execution_id=execution_id,
        round_no=1,
        tool_call_id=call.id,
        tool_name=call.name,
        workspace_root=str(tmp_path),
        canonical_path=str(target),
        effect_kind="file_replace",
        before_bytes=before,
        expected_after_bytes=after,
    )
    target.write_bytes(after)

    token = current_workspace_root.set(str(tmp_path.resolve()))
    try:
        assert journal.recover(sid, sess) == 1
    finally:
        current_workspace_root.reset(token)
    receipt = next(m for m in sess.messages if m.role == "tool" and m.tool_call_id == call.id)
    recovery = receipt.metadata["tool_execution_recovery"]
    assert recovery["state"] == "started_outcome_unknown"
    assert recovery["auto_reexecuted"] is False
    assert recovery["effect"]["effect_state"] == "current_matches_expected_after"
    assert recovery["effect"]["causation_proven"] is False
    assert "effect_state=current_matches_expected_after" in receipt.content
    assert "execution_outcome=unknown_after_restart" in receipt.content


def test_real_engine_edit_file_uses_execution_bound_effect_facts(
    build_test_engine, tmp_path: Path
) -> None:
    from llm_loop.event_log.store import EventStore
    from llm_loop.llm.client import LLMResponse

    target = tmp_path / "target.txt"
    target.write_text("BEFORE\n", encoding="utf-8")
    call = ToolCall(
        id="engine-edit-effect",
        name="edit_file",
        arguments={"path": "target.txt", "old_string": "BEFORE", "new_string": "AFTER"},
    )
    engine, _fake = build_test_engine(
        [
            LLMResponse(content="", tool_calls=[call], provider="fake"),
            LLMResponse(content="DONE", tool_calls=[], provider="fake"),
        ]
    )
    engine.registry.register(EditFileTool())
    engine.workspace_root = str(tmp_path.resolve())
    events = EventStore(tmp_path / "engine-events", enabled=True)
    engine._event_store = events  # noqa: SLF001 - exact integration WAL source
    sid = engine.session.create()

    result = engine.run(sid, "edit target")
    assert result.final_answer == "DONE"
    assert target.read_text(encoding="utf-8") == "AFTER\n"
    effect_events = [e for e in events.read(sid) if e.type.startswith("tool.execution.effect_")]
    assert [e.type for e in effect_events] == [
        "tool.execution.effect_prepared",
        "tool.execution.effect_observed",
    ]
    assert effect_events[0].payload["canonical_path"] == str(target.resolve())
    assert effect_events[1].payload["matches_expected"] is True


def test_subagent_edit_file_uses_same_execution_effect_journal(tmp_path: Path) -> None:
    from llm_loop.core.run_context import current_session_id, current_workspace_root
    from llm_loop.llm.client import LLMResponse
    from llm_loop.subagent.runner import SubAgentRunner
    from llm_loop.tools.registry import ToolRegistry

    class _EditLLM:
        def __init__(self) -> None:
            self.calls = 0

        def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="child-edit-effect",
                            name="edit_file",
                            arguments={
                                "path": "target.txt",
                                "old_string": "BEFORE",
                                "new_string": "AFTER",
                            },
                        )
                    ],
                    provider="fake",
                )
            return LLMResponse(content="child done", tool_calls=[], provider="fake")

    events = EventStore(tmp_path / "child-events", enabled=True)
    sessions = SessionStore(tmp_path / "child-sessions", event_store=events)
    registry = ToolRegistry()
    registry.register(EditFileTool())
    runner = SubAgentRunner(llm=_EditLLM(), registry=registry, session_store=sessions)  # type: ignore[arg-type]
    target = tmp_path / "target.txt"
    target.write_text("BEFORE\n", encoding="utf-8")
    sid_token = current_session_id.set("parent-effect-owner")
    ws_token = current_workspace_root.set(str(tmp_path.resolve()))
    try:
        result = runner.run(task="edit target once", depth=0)
    finally:
        current_workspace_root.reset(ws_token)
        current_session_id.reset(sid_token)
    assert result.outcome == "completed"
    assert target.read_text(encoding="utf-8") == "AFTER\n"
    child_files = sorted(sessions.root.glob("subagent_*.json"))
    assert len(child_files) == 1
    child_id = child_files[0].stem
    effect_events = [
        e for e in events.read(child_id) if e.type.startswith("tool.execution.effect_")
    ]
    assert [e.type for e in effect_events] == [
        "tool.execution.effect_prepared",
        "tool.execution.effect_observed",
    ]
    assert effect_events[0].payload["workspace_root"] == str(tmp_path.resolve())


def test_effect_prepared_rejects_target_outside_bound_workspace_without_fact(
    tmp_path: Path,
) -> None:
    journal, events, _sessions, sid = _journal(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"BEFORE\n")
    assert not journal.effect_prepared(
        sid,
        execution_id="exec-outside",
        round_no=1,
        tool_call_id="call-outside",
        tool_name="edit_file",
        workspace_root=str(workspace),
        canonical_path=str(outside),
        effect_kind="file_replace",
        before_bytes=b"BEFORE\n",
        expected_after_bytes=b"AFTER\n",
    )
    assert [e for e in events.read(sid) if e.type.startswith("tool.execution.effect_")] == []
    assert outside.read_bytes() == b"BEFORE\n"


def test_real_engine_effect_prepare_failure_blocks_edit_before_replace(
    build_test_engine, tmp_path: Path, monkeypatch
) -> None:
    from llm_loop.event_log.store import EventStore
    from llm_loop.llm.client import LLMResponse

    target = tmp_path / "target.txt"
    target.write_text("BEFORE\n", encoding="utf-8")
    call = ToolCall(
        id="engine-edit-prepare-fail",
        name="edit_file",
        arguments={"path": "target.txt", "old_string": "BEFORE", "new_string": "AFTER"},
    )
    engine, fake = build_test_engine(
        [
            LLMResponse(content="", tool_calls=[call], provider="fake"),
            LLMResponse(content="DONE", tool_calls=[], provider="fake"),
        ]
    )
    engine.registry.register(EditFileTool())
    engine.workspace_root = str(tmp_path.resolve())
    events = EventStore(tmp_path / "engine-fail-events", enabled=True)
    engine._event_store = events  # noqa: SLF001
    real_append = engine._event_append  # noqa: SLF001

    def fail_effect_prepare(session_id: str, event_type: str, payload: dict):
        if event_type == "tool.execution.effect_prepared":
            return None
        return real_append(session_id, event_type, payload)

    monkeypatch.setattr(engine, "_event_append", fail_effect_prepare)
    sid = engine.session.create()
    result = engine.run(sid, "edit target")
    assert result.final_answer == "DONE"
    assert target.read_text(encoding="utf-8") == "BEFORE\n"
    tool_wire = next(m for m in fake.calls[-1]["messages"] if m.get("role") == "tool")
    assert (
        "EffectPreparedUnavailable" in tool_wire["content"]
        or "执行效果准备事实" in tool_wire["content"]
    )
    assert [e for e in events.read(sid) if e.type.startswith("tool.execution.effect_")] == []

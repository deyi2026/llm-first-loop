"""CK-FINAL: deterministic closure gates for Continuity Kernel v1.

These tests cover only mechanical ownership/precedence invariants. They do not
score model strategy, evidence quality, completion quality, or cache hit rate.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from llm_loop.config import Settings
from llm_loop.core.external_execution import ExternalExecutionJournal
from llm_loop.core.message import ToolResultStatus
from llm_loop.core.run_context import current_session_id, current_workspace_root
from llm_loop.core.session import SessionExternalResourceBusyError
from llm_loop.tools.builtin.read_file import ReadFileTool


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        "k",
        "https://x.invalid/v1",
        "m",
        data_dir=str(tmp_path / "data"),
        archive_enabled=False,
        self_inspection_enabled=False,
        extract_enabled=False,
    )


def test_ck_final_terminal_release_preserves_workspace_artifact_across_session_delete(
    tmp_path: Path,
) -> None:
    """D0 + D0.5 compose without turning session deletion into artifact ownership."""
    from llm_loop.factory import build_engine

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "result.txt"
    original = b"IMMUTABLE-RESULT\n"
    target.write_bytes(original)

    engine = build_engine(_settings(tmp_path))
    read_tool = engine.registry.get("read_file")
    assert isinstance(read_tool, ReadFileTool)
    assert read_tool.artifact_store is not None
    events = engine.session.event_store
    assert events is not None

    producer_sid = engine.session.create()
    record = read_tool.artifact_store.create(
        workspace_scope=str(workspace),
        canonical_path=str(target),
        data=original,
        owner_session_id=producer_sid,
        execution_id="ck-final-edit",
        tool_call_id="ck-final-call",
        tool_name="edit_file",
        effect_kind="file_replace",
    )
    journal = ExternalExecutionJournal(events)
    assert journal.launched(
        session_id=producer_sid,
        job_id="ck-final-job",
        workspace_root=str(workspace),
        executor="execute_command",
        command_sha256="d" * 64,
        pid=8181,
        pgid=8181,
    ) is not None

    # A nonterminal external execution is a mechanical deletion fence. Deletion
    # must not signal/reclaim the process or erase its durable ownership facts.
    with pytest.raises(SessionExternalResourceBusyError):
        engine.session.delete(producer_sid)
    assert engine.session.exists(producer_sid) is True
    assert events.exists(producer_sid) is True
    pending = journal.state(producer_sid, "ck-final-job")
    assert pending is not None and pending.state == "running"

    # Only a durable terminal fact releases the physical-session deletion fence.
    assert journal.terminal(
        session_id=producer_sid,
        job_id="ck-final-job",
        exit_code=0,
        killed=False,
    ) is not None
    assert engine.session.delete(producer_sid) is True
    assert engine.session.exists(producer_sid) is False
    assert events.exists(producer_sid) is False

    # Session deletion does not own workspace artifact retention. Even if the
    # mutable workspace path diverges, a later session in the same workspace can
    # hydrate the exact immutable producer snapshot by its already-known ref.
    target.write_bytes(b"CURRENT-WORKSPACE-BYTES\n")
    consumer_sid = engine.session.create()
    sid_token = current_session_id.set(consumer_sid)
    ws_token = current_workspace_root.set(str(workspace.resolve()))
    try:
        result = read_tool.execute(path=record.ref)
    finally:
        current_workspace_root.reset(ws_token)
        current_session_id.reset(sid_token)

    assert result.status is ToolResultStatus.SUCCESS
    assert "IMMUTABLE-RESULT" in result.content
    assert "CURRENT-WORKSPACE-BYTES" not in result.content
    recovered = read_tool.artifact_store.resolve(record.ref, workspace_scope=str(workspace))
    assert recovered.owner_session_id == producer_sid
    assert recovered.sha256 == record.sha256


def test_ck_final_working_state_checkpoint_producer_remains_hold() -> None:
    """CK v1 may consume a valid checkpoint, but production must not author one yet."""
    root = Path(__file__).resolve().parents[2] / "src" / "llm_loop"
    calls: list[str] = []
    definitions = 0
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == (
                "build_working_state_checkpoint"
            ):
                definitions += 1
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name == "build_working_state_checkpoint":
                calls.append(f"{path}:{node.lineno}")

    assert definitions == 1
    assert calls == [], f"production checkpoint producer left HOLD: {calls}"


def test_ck_final_external_execution_events_never_grant_auto_reclaim(tmp_path: Path) -> None:
    """Lifecycle facts may describe an orphan; they never grant restart control authority."""
    from llm_loop.event_log.store import EventStore

    events = EventStore(tmp_path / "events", enabled=True)
    sid = "ck-final-owner"
    journal = ExternalExecutionJournal(events)
    assert journal.launched(
        session_id=sid,
        job_id="ck-final-job",
        workspace_root=str(tmp_path),
        executor="execute_command",
        command_sha256="e" * 64,
        pid=9191,
        pgid=9191,
    ) is not None
    assert journal.cancel_requested(
        session_id=sid,
        job_id="ck-final-job",
        reason="user_job_kill",
    ) is not None
    assert journal.terminal(
        session_id=sid,
        job_id="ck-final-job",
        exit_code=-15,
        killed=True,
    ) is not None

    lifecycle = [event for event in events.read(sid) if event.type.startswith("external.execution.")]
    assert [event.type for event in lifecycle] == [
        "external.execution.launched",
        "external.execution.cancel_requested",
        "external.execution.terminal",
    ]
    assert all(event.payload.get("auto_reclaim") is False for event in lifecycle)

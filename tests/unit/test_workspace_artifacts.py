from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from llm_loop.config import Settings
from llm_loop.core.episode_history import _tool_evidence_receipt
from llm_loop.core.message import (
    RecoverabilityStatus,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)
from llm_loop.core.run_context import current_session_id, current_workspace_root
from llm_loop.core.session import SessionStore
from llm_loop.core.tool_execution_journal import ToolExecutionJournal
from llm_loop.event_log.store import EventStore
from llm_loop.memory.evidence import SourceVersionPolicy
from llm_loop.tools.builtin.edit_file import EditFileTool
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.evidence_shadow import source_for_call
from llm_loop.tools.registry import tool_result_to_message
from llm_loop.workspace.artifacts import ArtifactError, WorkspaceArtifactStore


def _store(tmp_path: Path) -> tuple[WorkspaceArtifactStore, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return WorkspaceArtifactStore(tmp_path / "data"), workspace


def _create_record(store: WorkspaceArtifactStore, workspace: Path, data: bytes = b"VERSION-1\n"):
    target = workspace / "out" / "result.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    record = store.create(
        workspace_scope=str(workspace),
        canonical_path=str(target),
        data=data,
        owner_session_id="session-owner",
        execution_id="exec-1",
        tool_call_id="call-1",
        tool_name="edit_file",
        effect_kind="file_replace",
    )
    return record, target


def test_artifact_ref_is_workspace_scoped_opaque_and_restart_stable(tmp_path: Path) -> None:
    store, workspace = _store(tmp_path)
    record, target = _create_record(store, workspace)

    assert re.fullmatch(r"artifact://v1/[0-9a-f]{32}", record.ref)
    assert record.relative_path == "out/result.txt"
    public = record.public_facts()
    assert public["artifact_ref"] == record.ref
    assert public["path"] == "out/result.txt"
    assert str(workspace.resolve()) not in json.dumps(public, ensure_ascii=False)

    fresh = WorkspaceArtifactStore(tmp_path / "data")
    recovered = fresh.resolve(record.ref, workspace_scope=str(workspace))
    assert recovered == record
    assert fresh.read_bytes(record.ref, workspace_scope=str(workspace)) == target.read_bytes()


def test_artifact_ref_wrong_workspace_and_metadata_escape_fail_closed(tmp_path: Path) -> None:
    store, workspace = _store(tmp_path)
    record, _target = _create_record(store, workspace)
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ArtifactError, match="工作区"):
        store.resolve(record.ref, workspace_scope=str(other))

    metadata_path = next((tmp_path / "data" / "artifacts" / "records").rglob("*.json"))
    raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    raw["relative_path"] = "../outside.txt"
    metadata_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ArtifactError, match="路径"):
        store.resolve(record.ref, workspace_scope=str(workspace))


def test_artifact_keeps_exact_immutable_bytes_when_workspace_path_diverges(tmp_path: Path) -> None:
    store, workspace = _store(tmp_path)
    original = b"VERSION-1\n"
    record, target = _create_record(store, workspace, original)

    initial = store.snapshot(record.ref, workspace_scope=str(workspace))
    assert initial.workspace_path_state == "current_match"
    target.write_bytes(b"VERSION-2\n")
    changed = store.snapshot(record.ref, workspace_scope=str(workspace))
    assert changed.workspace_path_state == "current_diverged"
    assert store.read_bytes(record.ref, workspace_scope=str(workspace)) == original
    target.unlink()
    missing = store.snapshot(record.ref, workspace_scope=str(workspace))
    assert missing.workspace_path_state == "missing"
    assert store.read_bytes(record.ref, workspace_scope=str(workspace)) == original


def test_artifact_blob_integrity_is_verified(tmp_path: Path) -> None:
    store, workspace = _store(tmp_path)
    record, _target = _create_record(store, workspace)
    blob = next((tmp_path / "data" / "artifacts" / "blobs").rglob("*.blob"))
    blob.write_bytes(b"tampered")
    with pytest.raises(ArtifactError, match="完整性"):
        store.read_bytes(record.ref, workspace_scope=str(workspace))


def test_execution_bound_edit_mints_artifact_and_binds_it_to_effect_event(tmp_path: Path) -> None:
    store, workspace = _store(tmp_path)
    target = workspace / "target.txt"
    target.write_text("BEFORE\n", encoding="utf-8")
    events = EventStore(tmp_path / "events", enabled=True)
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    journal = ToolExecutionJournal(
        event_store=events,
        result_root=tmp_path / "tool-results",
        session_store=sessions,
    )
    call = ToolCall(
        id="artifact-edit",
        name="edit_file",
        arguments={"path": "target.txt", "old_string": "BEFORE", "new_string": "AFTER"},
    )
    sess = sessions.load(sid)
    execution_id = journal.declared(sess, call, round_no=1)
    assert journal.started(sid, execution_id=execution_id, round_no=1, call=call)

    token = current_workspace_root.set(str(workspace.resolve()))
    try:
        with journal.effect_context(
            session_id=sid,
            execution_id=execution_id,
            round_no=1,
            call=call,
            workspace_root=str(workspace),
        ):
            result = EditFileTool(artifact_store=store).execute(
                path="target.txt", old_string="BEFORE", new_string="AFTER"
            )
    finally:
        current_workspace_root.reset(token)

    assert result.status.value == "success"
    assert len(result.artifact_facts) == 1
    fact = result.artifact_facts[0]
    assert fact["path"] == "target.txt"
    assert fact["task_applicability"] == "not_evaluated"
    assert fact["artifact_ref"] in result.content
    record = store.resolve(str(fact["artifact_ref"]), workspace_scope=str(workspace))
    assert record.owner_session_id == sid
    assert record.execution_id == execution_id
    observed = [e for e in events.read(sid) if e.type == "tool.execution.effect_observed"][-1]
    assert observed.payload["artifact_ref"] == record.ref


def test_artifact_persistence_failure_never_rolls_back_successful_edit(
    tmp_path: Path, monkeypatch
) -> None:
    store, workspace = _store(tmp_path)
    target = workspace / "target.txt"
    target.write_text("BEFORE\n", encoding="utf-8")
    events = EventStore(tmp_path / "events", enabled=True)
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    journal = ToolExecutionJournal(
        event_store=events,
        result_root=tmp_path / "tool-results",
        session_store=sessions,
    )
    call = ToolCall(
        id="artifact-fail-edit",
        name="edit_file",
        arguments={"path": "target.txt", "old_string": "BEFORE", "new_string": "AFTER"},
    )
    sess = sessions.load(sid)
    execution_id = journal.declared(sess, call, round_no=1)
    assert journal.started(sid, execution_id=execution_id, round_no=1, call=call)

    def _fail_create(**_kwargs):
        raise OSError("artifact-store-down")

    monkeypatch.setattr(store, "create", _fail_create)
    token = current_workspace_root.set(str(workspace.resolve()))
    try:
        with journal.effect_context(
            session_id=sid,
            execution_id=execution_id,
            round_no=1,
            call=call,
            workspace_root=str(workspace),
        ):
            result = EditFileTool(artifact_store=store).execute(
                path="target.txt", old_string="BEFORE", new_string="AFTER"
            )
    finally:
        current_workspace_root.reset(token)

    assert result.status.value == "success"
    assert target.read_text(encoding="utf-8") == "AFTER\n"
    assert result.artifact_facts == ()
    assert "artifact_ref_unavailable=true" in result.content


def test_read_file_hydrates_exact_artifact_bytes_and_reports_current_path_state(tmp_path: Path) -> None:
    store, workspace = _store(tmp_path)
    record, target = _create_record(store, workspace, b"OLD\n")
    target.write_bytes(b"NEW\n")
    token = current_workspace_root.set(str(workspace.resolve()))
    try:
        result = ReadFileTool(artifact_store=store).execute(path=record.ref)
    finally:
        current_workspace_root.reset(token)

    assert result.status.value == "success"
    assert "OLD" in result.content
    assert "NEW" not in result.content
    assert record.ref in result.content
    assert "path=out/result.txt" in result.content
    assert "workspace_path_state=current_diverged" in result.content
    assert str(workspace.resolve()) not in result.content
    assert result.evidence_source_version_token == f"artifact-sha256:{record.sha256}"


def test_artifact_read_has_versioned_evidence_source_contract(tmp_path: Path) -> None:
    store, workspace = _store(tmp_path)
    record, _target = _create_record(store, workspace)
    call = ToolCall(id="artifact-read", name="read_file", arguments={"path": record.ref})
    source, _coverage = source_for_call(call)
    assert source.locator == record.ref
    assert source.version_policy is SourceVersionPolicy.VERSIONED


def test_tool_result_message_and_fold_receipt_preserve_only_mechanical_artifact_facts() -> None:
    artifact = {
        "artifact_ref": "artifact://v1/" + "a" * 32,
        "path": "out/result.txt",
        "sha256": "b" * 64,
        "size_bytes": 12,
        "task_applicability": "not_evaluated",
    }
    result = ToolResult(
        status=ToolResultStatus.SUCCESS,
        content="done",
        tool_call_id="call-artifact",
        tool_name="edit_file",
        recoverability_status=RecoverabilityStatus.RECORDED,
        evidence_ref="evidence://abc",
        artifact_facts=(artifact,),
    )
    direct = result.to_message()
    helper = tool_result_to_message(result)
    assert direct.metadata["artifact_facts"] == [artifact]
    assert helper.metadata["artifact_facts"] == [artifact]

    receipt = _tool_evidence_receipt(helper)
    assert receipt is not None
    assert f"artifact_ref={artifact['artifact_ref']}" in receipt.content
    assert "artifact_path=out/result.txt" in receipt.content
    assert f"artifact_sha256={artifact['sha256']}" in receipt.content
    assert "task_applicability=not_evaluated" in receipt.content


def test_event_store_disabled_does_not_mint_execution_artifact(tmp_path: Path) -> None:
    store, workspace = _store(tmp_path)
    target = workspace / "target.txt"
    target.write_text("BEFORE\n", encoding="utf-8")
    events = EventStore(tmp_path / "events", enabled=False)
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    journal = ToolExecutionJournal(
        event_store=events,
        result_root=tmp_path / "tool-results",
        session_store=sessions,
    )
    call = ToolCall(
        id="legacy-artifact-edit",
        name="edit_file",
        arguments={"path": "target.txt", "old_string": "BEFORE", "new_string": "AFTER"},
    )
    token = current_workspace_root.set(str(workspace.resolve()))
    try:
        with journal.effect_context(
            session_id=sid,
            execution_id="legacy-exec",
            round_no=1,
            call=call,
            workspace_root=str(workspace),
        ):
            result = EditFileTool(artifact_store=store).execute(
                path="target.txt", old_string="BEFORE", new_string="AFTER"
            )
    finally:
        current_workspace_root.reset(token)

    assert result.status.value == "success"
    assert result.artifact_facts == ()
    assert not any(store.records_root.rglob("*.json"))


def test_generic_shell_effect_never_infers_artifact_identity(tmp_path: Path) -> None:
    store, workspace = _store(tmp_path)
    target = workspace / "shell-created.txt"
    events = EventStore(tmp_path / "events", enabled=True)
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    journal = ToolExecutionJournal(
        event_store=events,
        result_root=tmp_path / "tool-results",
        session_store=sessions,
    )
    call = ToolCall(
        id="shell-artifact-unknown",
        name="execute_command",
        arguments={"command": f"printf shell > {target}"},
    )
    with journal.effect_context(
        session_id=sid,
        execution_id="shell-exec",
        round_no=1,
        call=call,
        workspace_root=str(workspace),
    ):
        result = ExecuteCommandTool(timeout_s=5).execute(command=call.arguments["command"])
    assert result.status.value == "success"
    assert target.read_text(encoding="utf-8") == "shell"
    assert result.artifact_facts == ()
    assert not any(store.records_root.rglob("*.json"))


def test_session_delete_keeps_workspace_artifact_for_next_session_same_workspace(
    tmp_path: Path,
) -> None:
    from llm_loop.factory import build_engine

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "result.txt"
    original = b"PRODUCER-SNAPSHOT\n"
    target.write_bytes(original)

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
    )
    engine = build_engine(settings)  # type: ignore[arg-type]
    read_tool = engine.registry.get("read_file")
    assert isinstance(read_tool, ReadFileTool)
    assert read_tool.artifact_store is not None

    producer_sid = engine.session.create()
    record = read_tool.artifact_store.create(
        workspace_scope=str(workspace),
        canonical_path=str(target),
        data=original,
        owner_session_id=producer_sid,
        execution_id="producer-exec",
        tool_call_id="producer-call",
        tool_name="edit_file",
        effect_kind="file_replace",
    )

    assert engine.session.delete(producer_sid) is True
    assert engine.session.exists(producer_sid) is False

    # The workspace path may move on; the immutable artifact remains exact and the
    # deleted producer sid remains provenance rather than retention authority.
    target.write_bytes(b"CURRENT-WORKSPACE-BYTES\n")
    consumer_sid = engine.session.create()
    assert consumer_sid != producer_sid

    sid_token = current_session_id.set(consumer_sid)
    ws_token = current_workspace_root.set(str(workspace.resolve()))
    try:
        result = read_tool.execute(path=record.ref)
    finally:
        current_workspace_root.reset(ws_token)
        current_session_id.reset(sid_token)

    assert result.status is ToolResultStatus.SUCCESS
    assert "PRODUCER-SNAPSHOT" in result.content
    assert "CURRENT-WORKSPACE-BYTES" not in result.content
    recovered = read_tool.artifact_store.resolve(record.ref, workspace_scope=str(workspace))
    assert recovered.owner_session_id == producer_sid
    assert recovered.sha256 == record.sha256


def test_factory_shares_one_artifact_store_between_edit_and_read(tmp_path: Path) -> None:
    from llm_loop.factory import build_engine

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
    )
    engine = build_engine(settings)  # type: ignore[arg-type]
    read_tool = engine.registry.get("read_file")
    edit_tool = engine.registry.get("edit_file")
    assert isinstance(read_tool, ReadFileTool)
    assert isinstance(edit_tool, EditFileTool)
    assert read_tool.artifact_store is edit_tool.artifact_store
    assert read_tool.artifact_store is not None
    assert read_tool.artifact_store.root == (tmp_path / "data" / "artifacts").resolve()


def test_subagent_edit_uses_same_execution_bound_artifact_contract(tmp_path: Path) -> None:
    from llm_loop.core.run_context import current_session_id
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
                            id="child-artifact-edit",
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

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "target.txt"
    target.write_text("BEFORE\n", encoding="utf-8")
    store = WorkspaceArtifactStore(tmp_path / "data")
    events = EventStore(tmp_path / "events", enabled=True)
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    registry = ToolRegistry()
    registry.register(EditFileTool(artifact_store=store))
    runner = SubAgentRunner(llm=_EditLLM(), registry=registry, session_store=sessions)  # type: ignore[arg-type]

    sid_token = current_session_id.set("parent-artifact-owner")
    ws_token = current_workspace_root.set(str(workspace.resolve()))
    try:
        result = runner.run(task="edit target once", depth=0)
    finally:
        current_workspace_root.reset(ws_token)
        current_session_id.reset(sid_token)

    assert result.outcome == "completed"
    child_files = sorted(sessions.root.glob("subagent_*.json"))
    assert len(child_files) == 1
    child_id = child_files[0].stem
    child = sessions.load(child_id)
    tool_message = next(m for m in child.messages if m.role == "tool")
    facts = tool_message.metadata["artifact_facts"]
    assert len(facts) == 1
    assert facts[0]["path"] == "target.txt"
    record = store.resolve(facts[0]["artifact_ref"], workspace_scope=str(workspace))
    assert record.owner_session_id == child_id
    observed = [e for e in events.read(child_id) if e.type == "tool.execution.effect_observed"][-1]
    assert observed.payload["artifact_ref"] == record.ref

"""P2 T06-T15: explicit file snapshots, version preconditions and coordinated writes."""

from __future__ import annotations

import hashlib
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.core.message import ToolCall
from llm_loop.core.run_context import current_workspace_root
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.evidence_source_resolver import EvidenceSourceResolver
from llm_loop.workspace.artifacts import WorkspaceArtifactStore
from llm_loop.workspace.file_effects import FileArtifactProvenance
from llm_loop.workspace.file_service import FileService, FileServiceError


def _service(tmp_path: Path) -> tuple[FileService, WorkspaceArtifactStore, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = WorkspaceArtifactStore(tmp_path / "data")
    service = FileService(
        artifact_store=store,
        lock_root=tmp_path / "data" / "file_locks",
    )
    return service, store, workspace


def _provenance(workspace: Path, operation: str = "op-observe") -> FileArtifactProvenance:
    return FileArtifactProvenance(
        workspace_scope=str(workspace),
        owner_session_id="sid-p2",
        operation_id=operation,
        tool_call_id="call-p2",
        tool_name="read_file",
        effect_kind="file_observation",
    )


def test_t06_snapshot_keeps_full_bytes_while_returning_selected_range(tmp_path: Path) -> None:
    service, store, workspace = _service(tmp_path)
    path = workspace / "notes.txt"
    full = b"line1\nline2\nline3\n"
    path.write_bytes(full)
    token = current_workspace_root.set(str(workspace))
    try:
        result = ReadFileTool(artifact_store=store, file_service=service).execute(
            path="notes.txt", snapshot=True, offset=1, limit=1
        )
    finally:
        current_workspace_root.reset(token)

    assert result.status.value == "success"
    assert "file_contract_version=1" in result.content
    assert "2 | line2" in result.content
    assert "1 | line1" not in result.content
    assert len(result.artifact_facts) == 1
    ref = str(result.artifact_facts[0]["artifact_ref"])
    record = store.resolve(ref, workspace_scope=str(workspace))
    assert record.effect_kind == "file_observation"
    assert record.sha256 == hashlib.sha256(full).hexdigest()
    assert store.read_bytes(ref, workspace_scope=str(workspace)) == full


def test_t07_snapshot_forces_physical_read_and_bypasses_evidence_reuse(tmp_path: Path) -> None:
    class LedgerMustNotBeRead:
        def find_by_source(self, *_args, **_kwargs):
            raise AssertionError("snapshot request must bypass evidence resolver")

    resolver = EvidenceSourceResolver(
        LedgerMustNotBeRead(),
        freshness=SimpleNamespace(),
        owner_resolver=lambda: SimpleNamespace(),
        blobs=None,
    )
    call = ToolCall(
        id="snapshot-call",
        name="read_file",
        arguments={"path": str(tmp_path / "a.txt"), "snapshot": True},
    )
    assert resolver.resolve(call) is None


def test_t08_matching_expected_snapshot_allows_versioned_edit(tmp_path: Path) -> None:
    service, _store, workspace = _service(tmp_path)
    path = workspace / "a.txt"
    path.write_bytes(b"draft\n")
    observation = service.observe(
        path=path,
        workspace_scope=str(workspace),
        provenance=_provenance(workspace),
    )

    result = service.edit(
        path=path,
        old_string="draft",
        new_string="reviewed",
        workspace_scope=str(workspace),
        expected_snapshot_ref=observation.snapshot_ref,
    )

    assert result.applied is True
    assert result.precondition_checked is True
    assert path.read_bytes() == b"reviewed\n"


def test_t09_same_size_and_same_mtime_but_different_bytes_is_version_conflict(tmp_path: Path) -> None:
    service, _store, workspace = _service(tmp_path)
    path = workspace / "a.txt"
    path.write_bytes(b"AAAA\n")
    observation = service.observe(
        path=path,
        workspace_scope=str(workspace),
        provenance=_provenance(workspace),
    )
    original_stat = path.stat()
    path.write_bytes(b"BBBB\n")
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    with pytest.raises(FileServiceError) as exc:
        service.edit(
            path=path,
            old_string="AAAA",
            new_string="CCCC",
            workspace_scope=str(workspace),
            expected_snapshot_ref=observation.snapshot_ref,
        )
    assert exc.value.error_type == "VersionConflict"
    assert path.read_bytes() == b"BBBB\n"


def test_t10_expected_snapshot_cannot_cross_workspace_or_path(tmp_path: Path) -> None:
    service, _store, workspace = _service(tmp_path)
    other_workspace = tmp_path / "other"
    other_workspace.mkdir()
    a = workspace / "a.txt"
    b = workspace / "b.txt"
    other = other_workspace / "a.txt"
    for path in (a, b, other):
        path.write_bytes(b"draft\n")

    obs_a = service.observe(
        path=a, workspace_scope=str(workspace), provenance=_provenance(workspace, "obs-a")
    )
    other_store = WorkspaceArtifactStore(tmp_path / "data")
    other_service = FileService(
        artifact_store=other_store,
        lock_root=tmp_path / "data" / "file_locks",
    )
    obs_other = other_service.observe(
        path=other,
        workspace_scope=str(other_workspace),
        provenance=_provenance(other_workspace, "obs-other"),
    )

    with pytest.raises(FileServiceError) as wrong_path:
        service.edit(
            path=b,
            old_string="draft",
            new_string="mine",
            workspace_scope=str(workspace),
            expected_snapshot_ref=obs_a.snapshot_ref,
        )
    assert wrong_path.value.error_type == "VersionPreconditionInvalid"

    with pytest.raises(FileServiceError) as wrong_workspace:
        service.edit(
            path=a,
            old_string="draft",
            new_string="mine",
            workspace_scope=str(workspace),
            expected_snapshot_ref=obs_other.snapshot_ref,
        )
    assert wrong_workspace.value.error_type == "VersionPreconditionInvalid"
    assert a.read_bytes() == b"draft\n"
    assert b.read_bytes() == b"draft\n"


def test_t11_dry_run_does_not_reserve_old_snapshot_for_later_apply(tmp_path: Path) -> None:
    service, _store, workspace = _service(tmp_path)
    path = workspace / "a.txt"
    path.write_bytes(b"draft\n")
    observation = service.observe(
        path=path, workspace_scope=str(workspace), provenance=_provenance(workspace)
    )
    preview = service.edit(
        path=path,
        old_string="draft",
        new_string="model",
        dry_run=True,
        workspace_scope=str(workspace),
        expected_snapshot_ref=observation.snapshot_ref,
    )
    assert preview.dry_run is True and preview.precondition_checked is True

    path.write_bytes(b"human\n")
    with pytest.raises(FileServiceError) as exc:
        service.edit(
            path=path,
            old_string="draft",
            new_string="model",
            workspace_scope=str(workspace),
            expected_snapshot_ref=observation.snapshot_ref,
        )
    assert exc.value.error_type == "VersionConflict"
    assert path.read_bytes() == b"human\n"


def test_t12_same_snapshot_concurrent_writers_only_one_applies(tmp_path: Path) -> None:
    service, _store, workspace = _service(tmp_path)
    path = workspace / "a.txt"
    path.write_bytes(b"draft\n")
    observation = service.observe(
        path=path, workspace_scope=str(workspace), provenance=_provenance(workspace)
    )
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def worker(replacement: str) -> None:
        barrier.wait()
        try:
            service.edit(
                path=path,
                old_string="draft",
                new_string=replacement,
                workspace_scope=str(workspace),
                expected_snapshot_ref=observation.snapshot_ref,
            )
            outcomes.append("applied")
        except FileServiceError as exc:
            outcomes.append(exc.error_type)

    threads = [threading.Thread(target=worker, args=(value,)) for value in ("A", "B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert not any(thread.is_alive() for thread in threads)
    assert sorted(outcomes) == ["VersionConflict", "applied"]
    assert path.read_bytes() in {b"A\n", b"B\n"}


class _BarrierSink:
    workspace_scope: str
    owner_session_id = "sid"
    operation_id = "op"
    tool_call_id = "call"
    tool_name = "edit_file"
    effect_kind = "file_replace"
    records_durable = False

    def __init__(self, workspace_scope: str, barrier: threading.Barrier) -> None:
        self.workspace_scope = workspace_scope
        self._barrier = barrier

    def prepared(self, **_kwargs) -> bool:
        self._barrier.wait(timeout=2)
        return True

    def observed(self, **_kwargs) -> bool:
        return False


def test_t13_different_paths_do_not_share_one_global_lock(tmp_path: Path) -> None:
    service, _store, workspace = _service(tmp_path)
    paths = [workspace / "a.txt", workspace / "b.txt"]
    for path in paths:
        path.write_bytes(b"draft\n")
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def worker(path: Path, replacement: str) -> None:
        try:
            service.edit(
                path=path,
                old_string="draft",
                new_string=replacement,
                workspace_scope=str(workspace),
                effect_sink=_BarrierSink(str(workspace), barrier),
            )
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(paths[0], "A")),
        threading.Thread(target=worker, args=(paths[1], "B")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert errors == []
    assert paths[0].read_bytes() == b"A\n"
    assert paths[1].read_bytes() == b"B\n"


def test_t13_lock_failure_is_fail_closed_before_mutation(tmp_path: Path, monkeypatch) -> None:
    service, _store, workspace = _service(tmp_path)
    path = workspace / "a.txt"
    path.write_bytes(b"draft\n")

    @contextmanager
    def broken_lock(*_args, **_kwargs):
        raise FileServiceError("PathLockUnavailable")
        yield  # pragma: no cover

    monkeypatch.setattr(service, "_path_lock", broken_lock)
    with pytest.raises(FileServiceError) as exc:
        service.edit(
            path=path,
            old_string="draft",
            new_string="mine",
            workspace_scope=str(workspace),
        )
    assert exc.value.error_type == "PathLockUnavailable"
    assert path.read_bytes() == b"draft\n"


def test_t14_prepared_failure_keeps_original_bytes(tmp_path: Path) -> None:
    service, _store, workspace = _service(tmp_path)
    path = workspace / "a.txt"
    path.write_bytes(b"draft\n")
    sink = SimpleNamespace(
        workspace_scope=str(workspace),
        owner_session_id="sid",
        operation_id="op",
        tool_call_id="call",
        tool_name="edit_file",
        effect_kind="file_replace",
        records_durable=False,
        prepared=lambda **_kwargs: False,
        observed=lambda **_kwargs: True,
    )
    with pytest.raises(FileServiceError) as exc:
        service.edit(
            path=path,
            old_string="draft",
            new_string="mine",
            workspace_scope=str(workspace),
            effect_sink=sink,
        )
    assert exc.value.error_type == "EffectPreparedUnavailable"
    assert path.read_bytes() == b"draft\n"


def test_t15_observed_failure_does_not_turn_successful_write_into_not_applied(tmp_path: Path) -> None:
    service, _store, workspace = _service(tmp_path)
    path = workspace / "a.txt"
    path.write_bytes(b"draft\n")
    sink = SimpleNamespace(
        workspace_scope=str(workspace),
        owner_session_id="sid",
        operation_id="op",
        tool_call_id="call",
        tool_name="edit_file",
        effect_kind="file_replace",
        records_durable=False,
        prepared=lambda **_kwargs: True,
        observed=lambda **_kwargs: False,
    )
    result = service.edit(
        path=path,
        old_string="draft",
        new_string="mine",
        workspace_scope=str(workspace),
        effect_sink=sink,
    )
    assert result.applied is True
    assert result.receipt_state == "recording_failed"
    assert path.read_bytes() == b"mine\n"


def test_t08_tool_contract_uses_snapshot_ref_with_durable_journal(tmp_path: Path) -> None:
    from llm_loop.core.session import SessionStore
    from llm_loop.core.tool_execution_journal import ToolExecutionJournal
    from llm_loop.event_log.store import EventStore
    from llm_loop.tools.builtin.edit_file import EditFileTool

    service, store, workspace = _service(tmp_path)
    path = workspace / "tool.txt"
    path.write_bytes(b"draft\n")
    token = current_workspace_root.set(str(workspace))
    try:
        snapshot_result = ReadFileTool(artifact_store=store, file_service=service).execute(
            path="tool.txt", snapshot=True
        )
        ref = str(snapshot_result.artifact_facts[0]["artifact_ref"])

        events = EventStore(tmp_path / "events", enabled=True)
        sessions = SessionStore(tmp_path / "sessions", event_store=events)
        sid = sessions.create()
        journal = ToolExecutionJournal(
            event_store=events,
            result_root=tmp_path / "tool-results",
            session_store=sessions,
        )
        call = ToolCall(
            id="versioned-edit",
            name="edit_file",
            arguments={
                "path": "tool.txt",
                "old_string": "draft",
                "new_string": "reviewed",
                "expected_snapshot_ref": ref,
            },
        )
        execution_id = journal.declared(sessions.load(sid), call, round_no=1)
        assert journal.started(sid, execution_id=execution_id, round_no=1, call=call)
        with journal.effect_context(
            session_id=sid,
            execution_id=execution_id,
            round_no=1,
            call=call,
            workspace_root=str(workspace),
        ):
            result = EditFileTool(artifact_store=store, file_service=service).execute(
                path="tool.txt",
                old_string="draft",
                new_string="reviewed",
                expected_snapshot_ref=ref,
            )
    finally:
        current_workspace_root.reset(token)

    assert result.status.value == "success"
    assert "file_contract] version=1 precondition_checked=true" in result.content
    assert "receipt_state=recorded" in result.content
    assert path.read_bytes() == b"reviewed\n"


def test_t14_versioned_tool_refuses_when_effect_journal_is_disabled(tmp_path: Path) -> None:
    from llm_loop.core.session import SessionStore
    from llm_loop.core.tool_execution_journal import ToolExecutionJournal
    from llm_loop.event_log.store import EventStore
    from llm_loop.tools.builtin.edit_file import EditFileTool

    service, store, workspace = _service(tmp_path)
    path = workspace / "tool.txt"
    path.write_bytes(b"draft\n")
    observation = service.observe(
        path=path,
        workspace_scope=str(workspace),
        provenance=_provenance(workspace),
    )
    events = EventStore(tmp_path / "events-off", enabled=False)
    sessions = SessionStore(tmp_path / "sessions-off", event_store=events)
    sid = sessions.create()
    journal = ToolExecutionJournal(
        event_store=events,
        result_root=tmp_path / "tool-results-off",
        session_store=sessions,
    )
    call = ToolCall(
        id="versioned-edit-off",
        name="edit_file",
        arguments={
            "path": "tool.txt",
            "old_string": "draft",
            "new_string": "reviewed",
            "expected_snapshot_ref": observation.snapshot_ref,
        },
    )
    execution_id = journal.declared(sessions.load(sid), call, round_no=1)
    assert journal.started(sid, execution_id=execution_id, round_no=1, call=call)
    token = current_workspace_root.set(str(workspace))
    try:
        with journal.effect_context(
            session_id=sid,
            execution_id=execution_id,
            round_no=1,
            call=call,
            workspace_root=str(workspace),
        ):
            result = EditFileTool(artifact_store=store, file_service=service).execute(
                path="tool.txt",
                old_string="draft",
                new_string="reviewed",
                expected_snapshot_ref=observation.snapshot_ref,
            )
    finally:
        current_workspace_root.reset(token)

    assert result.status.value == "error"
    assert result.error_type == "EffectPreparedUnavailable"
    assert path.read_bytes() == b"draft\n"

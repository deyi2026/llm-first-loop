from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.core.session import SessionStore
from llm_loop.event_log.model import (
    EVENT_HUMAN_FILE_EDIT_OBSERVED,
    EVENT_HUMAN_FILE_EDIT_PREPARED,
    EVENT_MESSAGE_APPENDED,
)
from llm_loop.event_log.store import EventStore
from llm_loop.workspace.artifacts import WorkspaceArtifactStore
from llm_loop.workspace.file_effect_query import FileEffectQueryService
from llm_loop.workspace.file_service import FileService
from llm_loop.workspace.human_file_ops import HumanFileOperationError, HumanFileOperationService


def _service(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    events = EventStore(tmp_path / "events", enabled=True)
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    artifacts = WorkspaceArtifactStore(tmp_path / "data")
    files = FileService(artifact_store=artifacts, lock_root=tmp_path / "locks")
    query = FileEffectQueryService(events)
    human = HumanFileOperationService(
        session_store=sessions,
        event_store=events,
        file_service=files,
        query_service=query,
        max_file_bytes=1024 * 1024,
    )
    return workspace, events, sessions, sid, human, query


def test_observe_preserves_exact_crlf_and_trailing_newline(tmp_path: Path) -> None:
    workspace, _events, _sessions, sid, human, _query = _service(tmp_path)
    target = workspace / "a.txt"
    target.write_bytes(b"one\r\ntwo\r\n")
    observed = human.observe(
        session_id=sid, workspace_scope=str(workspace), relative_path="a.txt", offset=0, limit=10
    )
    assert observed.content == "one\r\ntwo\r\n"
    assert observed.size_bytes == len(b"one\r\ntwo\r\n")
    assert observed.path == "a.txt"


def test_human_edit_is_idempotent_and_never_creates_model_messages(tmp_path: Path) -> None:
    workspace, events, _sessions, sid, human, query = _service(tmp_path)
    target = workspace / "a.txt"
    target.write_text("before\n", encoding="utf-8")
    baseline = human.observe(
        session_id=sid, workspace_scope=str(workspace), relative_path="a.txt"
    )
    first = human.edit(
        session_id=sid,
        workspace_scope=str(workspace),
        request_id="request-0001",
        relative_path="a.txt",
        expected_snapshot_ref=baseline.snapshot_ref,
        content="after\n",
        file_contract_version=1,
    )
    second = human.edit(
        session_id=sid,
        workspace_scope=str(workspace),
        request_id="request-0001",
        relative_path="a.txt",
        expected_snapshot_ref=baseline.snapshot_ref,
        content="after\n",
        file_contract_version=1,
    )
    assert first.operation_id == second.operation_id
    assert target.read_text(encoding="utf-8") == "after\n"
    types = [event.type for event in events.read(sid)]
    assert types.count(EVENT_HUMAN_FILE_EDIT_PREPARED) == 1
    assert types.count(EVENT_HUMAN_FILE_EDIT_OBSERVED) == 1
    assert EVENT_MESSAGE_APPENDED not in types
    exact = query.query(
        session_id=sid,
        workspace_scope=str(workspace),
        query=f"operation:{first.operation_id}",
        limit=10,
    )
    assert exact.receipts[0].effect_state == "observed_match"


def test_same_request_id_different_params_is_conflict(tmp_path: Path) -> None:
    workspace, _events, _sessions, sid, human, _query = _service(tmp_path)
    target = workspace / "a.txt"
    target.write_text("before\n", encoding="utf-8")
    baseline = human.observe(
        session_id=sid, workspace_scope=str(workspace), relative_path="a.txt"
    )
    human.edit(
        session_id=sid,
        workspace_scope=str(workspace),
        request_id="request-0002",
        relative_path="a.txt",
        expected_snapshot_ref=baseline.snapshot_ref,
        content="one\n",
        file_contract_version=1,
    )
    with pytest.raises(HumanFileOperationError, match="request_conflict"):
        human.edit(
            session_id=sid,
            workspace_scope=str(workspace),
            request_id="request-0002",
            relative_path="a.txt",
            expected_snapshot_ref=baseline.snapshot_ref,
            content="two\n",
            file_contract_version=1,
        )


def test_prepared_only_retry_is_read_only_unknown_not_replayed(tmp_path: Path) -> None:
    workspace, events, _sessions, sid, human, _query = _service(tmp_path)
    target = workspace / "a.txt"
    target.write_text("before\n", encoding="utf-8")
    baseline = human.observe(
        session_id=sid, workspace_scope=str(workspace), relative_path="a.txt"
    )
    digest = human.request_digest(
        session_id=sid,
        workspace_scope=str(workspace),
        relative_path="a.txt",
        expected_snapshot_ref=baseline.snapshot_ref,
        content="after\n",
        file_contract_version=1,
    )
    assert events.append(
        sid,
        EVENT_HUMAN_FILE_EDIT_PREPARED,
        {
            "operation_id": "prepared-only",
            "request_id": "request-0003",
            "request_sha256": digest,
            "origin": "authenticated_user",
            "workspace_root": str(workspace.resolve()),
            "relative_path": "a.txt",
            "before_sha256": baseline.sha256,
            "before_size": baseline.size_bytes,
            "expected_after_sha256": "0" * 64,
            "expected_after_size": 6,
            "expected_snapshot_ref": baseline.snapshot_ref,
            "precondition_checked": True,
            "file_contract_version": 1,
        },
    )
    receipt = human.edit(
        session_id=sid,
        workspace_scope=str(workspace),
        request_id="request-0003",
        relative_path="a.txt",
        expected_snapshot_ref=baseline.snapshot_ref,
        content="after\n",
        file_contract_version=1,
    )
    assert receipt.operation_id == "prepared-only"
    assert receipt.effect_state == "outcome_unknown"
    assert receipt.causation_proven is False
    assert target.read_text(encoding="utf-8") == "before\n"
    assert [e.type for e in events.read(sid)].count(EVENT_HUMAN_FILE_EDIT_PREPARED) == 1


def test_busy_session_does_not_write_or_consume_request_id(tmp_path: Path) -> None:
    workspace, events, sessions, sid, human, _query = _service(tmp_path)
    target = workspace / "a.txt"
    target.write_text("before\n", encoding="utf-8")
    baseline = human.observe(
        session_id=sid, workspace_scope=str(workspace), relative_path="a.txt"
    )
    with sessions.run_lease(sid) as acquired:
        assert acquired
        with pytest.raises(HumanFileOperationError, match="session_busy"):
            human.edit(
                session_id=sid,
                workspace_scope=str(workspace),
                request_id="request-0004",
                relative_path="a.txt",
                expected_snapshot_ref=baseline.snapshot_ref,
                content="after\n",
                file_contract_version=1,
            )
    assert target.read_text(encoding="utf-8") == "before\n"
    assert not any(
        e.payload.get("request_id") == "request-0004" for e in events.read(sid)
    )


def test_human_path_is_relative_utf8_regular_and_no_symlink(tmp_path: Path) -> None:
    workspace, _events, _sessions, sid, human, _query = _service(tmp_path)
    target = workspace / "a.txt"
    target.write_text("ok", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    for invalid in (str(target.resolve()), "../outside.txt"):
        with pytest.raises(HumanFileOperationError):
            human.observe(session_id=sid, workspace_scope=str(workspace), relative_path=invalid)

    link = workspace / "link.txt"
    link.symlink_to(target)
    with pytest.raises(HumanFileOperationError, match="symlink"):
        human.observe(session_id=sid, workspace_scope=str(workspace), relative_path="link.txt")

    binary = workspace / "binary.bin"
    binary.write_bytes(b"\xff\xfe")
    with pytest.raises(HumanFileOperationError, match="unsupported_text_encoding"):
        human.observe(session_id=sid, workspace_scope=str(workspace), relative_path="binary.bin")


def test_human_bom_editor_content_excludes_marker_but_save_preserves_one_bom(tmp_path: Path) -> None:
    workspace, _events, _sessions, sid, human, _query = _service(tmp_path)
    target = workspace / "bom.txt"
    target.write_bytes(b"\xef\xbb\xbfbefore\n")
    baseline = human.observe(
        session_id=sid, workspace_scope=str(workspace), relative_path="bom.txt"
    )
    assert baseline.content == "before\n"
    human.edit(
        session_id=sid,
        workspace_scope=str(workspace),
        request_id="request-bom-01",
        relative_path="bom.txt",
        expected_snapshot_ref=baseline.snapshot_ref,
        content="after\n",
        file_contract_version=1,
    )
    assert target.read_bytes() == b"\xef\xbb\xbfafter\n"


def test_rejected_request_replays_same_rejection_without_new_effect(tmp_path: Path) -> None:
    workspace, events, _sessions, sid, human, _query = _service(tmp_path)
    target = workspace / "a.txt"
    target.write_text("base\n", encoding="utf-8")
    baseline = human.observe(session_id=sid, workspace_scope=str(workspace), relative_path="a.txt")
    target.write_text("external\n", encoding="utf-8")
    kwargs = dict(
        session_id=sid,
        workspace_scope=str(workspace),
        request_id="request-reject-1",
        relative_path="a.txt",
        expected_snapshot_ref=baseline.snapshot_ref,
        content="stale\n",
        file_contract_version=1,
    )
    with pytest.raises(HumanFileOperationError, match="version_conflict"):
        human.edit(**kwargs)
    count = len(events.read(sid))
    with pytest.raises(HumanFileOperationError, match="version_conflict"):
        human.edit(**kwargs)
    assert len(events.read(sid)) == count
    assert target.read_text(encoding="utf-8") == "external\n"


def test_human_save_holds_run_lease_against_cross_process_run_and_delete(
    tmp_path: Path, monkeypatch
) -> None:
    import os
    import subprocess
    import sys
    import threading

    workspace, _events, sessions, sid, human, _query = _service(tmp_path)
    target = workspace / "a.txt"
    target.write_text("before\n", encoding="utf-8")
    baseline = human.observe(
        session_id=sid, workspace_scope=str(workspace), relative_path="a.txt"
    )
    entered = threading.Event()
    release = threading.Event()
    failures: list[BaseException] = []
    original_edit = human.file_service.edit

    def blocking_edit(**kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return original_edit(**kwargs)

    monkeypatch.setattr(human.file_service, "edit", blocking_edit)

    def save() -> None:
        try:
            human.edit(
                session_id=sid,
                workspace_scope=str(workspace),
                request_id="request-lease-01",
                relative_path="a.txt",
                expected_snapshot_ref=baseline.snapshot_ref,
                content="after\n",
                file_contract_version=1,
            )
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)

    thread = threading.Thread(target=save, daemon=True)
    thread.start()
    assert entered.wait(timeout=5)

    source_root = str(Path(__file__).resolve().parents[2] / "src")
    script = r'''
import sys
from llm_loop.core.session import SessionMutationBusyError, SessionStore
store = SessionStore(sys.argv[1])
sid = sys.argv[2]
with store.run_lease(sid) as acquired:
    print("run=acquired" if acquired else "run=busy")
try:
    store.delete(sid)
except SessionMutationBusyError:
    print("delete=busy")
else:
    print("delete=not_busy")
'''
    env = os.environ.copy()
    env["PYTHONPATH"] = source_root
    proc = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "sessions"), sid],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "run=busy" in proc.stdout
    assert "delete=busy" in proc.stdout
    assert sessions.exists(sid)
    assert target.read_text(encoding="utf-8") == "before\n"

    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert failures == []
    assert target.read_text(encoding="utf-8") == "after\n"

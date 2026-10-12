"""ST2-D0: physical session deletion must fence unfinished external resources.

The fence is mechanical only: a nonterminal execution owned by the session blocks
physical deletion.  It never decides whether the execution is useful, should be
continued, or should be reclaimed after restart.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_loop.config import Settings
from llm_loop.core.external_execution import ExternalExecutionJournal
from llm_loop.core.session import SessionExternalResourceBusyError
from llm_loop.tools.builtin.job_registry import JobRegistry


class _FakeProc:
    def __init__(self, *, pid: int = 4242) -> None:
        self.pid = pid
        self.returncode = None
        self.stdout = None
        self.stderr = None
        self.terminated = False

    def wait(self) -> int:
        return int(self.returncode or 0)

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15


def _settings(tmp_path: Path, *, event_log_enabled: bool = True) -> Settings:
    return Settings(
        "k",
        "https://x.invalid/v1",
        "m",
        data_dir=str(tmp_path / "data"),
        event_log_enabled=event_log_enabled,
        archive_enabled=False,
        self_inspection_enabled=False,
        extract_enabled=False,
    )


@pytest.fixture(autouse=True)
def _isolate_job_registry():
    previous = JobRegistry._instance
    JobRegistry._instance = None
    try:
        yield
    finally:
        JobRegistry._instance = previous


def test_external_journal_lists_only_nonterminal_owner_executions(tmp_path: Path) -> None:
    from llm_loop.event_log.store import EventStore

    events = EventStore(tmp_path / "events", enabled=True)
    journal = ExternalExecutionJournal(events)
    for job_id in ("job-running", "job-done"):
        assert journal.launched(
            session_id="owner-a",
            job_id=job_id,
            workspace_root=str(tmp_path),
            executor="execute_command",
            command_sha256="a" * 64,
        ) is not None
    assert journal.terminal(
        session_id="owner-a", job_id="job-done", exit_code=0, killed=False
    ) is not None

    pending = journal.nonterminal("owner-a")

    assert [state.job_id for state in pending] == ["job-running"]
    assert pending[0].state == "running"
    assert journal.nonterminal("different-owner") == ()


def test_local_active_external_execution_blocks_delete_without_signalling_process(
    tmp_path: Path,
) -> None:
    from llm_loop.factory import build_engine

    engine = build_engine(_settings(tmp_path))
    sid = engine.session.create()
    proc = _FakeProc()
    registry = JobRegistry.instance()
    job_id = registry.create(
        proc,
        "sleep 30",
        session_id=sid,
        workspace_root=str(tmp_path),
        executor="execute_command",
    )

    with pytest.raises(SessionExternalResourceBusyError, match="外部执行"):
        engine.session.delete(sid)

    assert proc.terminated is False
    assert engine.session.exists(sid) is True
    assert engine.session.event_store is not None
    assert engine.session.event_store.exists(sid) is True
    state = ExternalExecutionJournal(engine.session.event_store).state(sid, job_id)
    assert state is not None and state.state == "running"


def test_fresh_durable_orphan_blocks_delete_and_preserves_owner_facts(tmp_path: Path) -> None:
    from llm_loop.factory import build_engine

    engine = build_engine(_settings(tmp_path))
    sid = engine.session.create()
    events = engine.session.event_store
    assert events is not None
    journal = ExternalExecutionJournal(events)
    assert journal.launched(
        session_id=sid,
        job_id="job-orphan",
        workspace_root=str(tmp_path),
        executor="execute_command",
        command_sha256="b" * 64,
        pid=9090,
        pgid=9090,
    ) is not None

    # No local JobRegistry handle exists: this models a fresh runtime after restart.
    JobRegistry._instance = JobRegistry(event_store=events)
    with pytest.raises(SessionExternalResourceBusyError):
        engine.session.delete(sid)

    assert engine.session.exists(sid) is True
    recovered = journal.state(sid, "job-orphan")
    assert recovered is not None and recovered.state == "running"


def test_durable_terminal_execution_no_longer_blocks_physical_delete(tmp_path: Path) -> None:
    from llm_loop.factory import build_engine

    engine = build_engine(_settings(tmp_path))
    sid = engine.session.create()
    events = engine.session.event_store
    assert events is not None
    journal = ExternalExecutionJournal(events)
    assert journal.launched(
        session_id=sid,
        job_id="job-complete",
        workspace_root=str(tmp_path),
        executor="execute_command",
        command_sha256="c" * 64,
    ) is not None
    assert journal.terminal(
        session_id=sid, job_id="job-complete", exit_code=0, killed=False
    ) is not None

    assert engine.session.delete(sid) is True
    assert engine.session.exists(sid) is False
    assert events.exists(sid) is False


def test_event_log_disabled_still_fences_process_local_active_job(tmp_path: Path) -> None:
    from llm_loop.factory import build_engine

    engine = build_engine(_settings(tmp_path, event_log_enabled=False))
    sid = engine.session.create()
    proc = _FakeProc()
    registry = JobRegistry.instance()
    job_id = registry.create(
        proc,
        "sleep 30",
        session_id=sid,
        workspace_root=str(tmp_path),
        executor="execute_command",
    )
    assert registry.snapshot(job_id, session_id=sid)["durable"] is False

    with pytest.raises(SessionExternalResourceBusyError):
        engine.session.delete(sid)

    assert proc.terminated is False
    assert engine.session.exists(sid) is True


def test_web_delete_maps_external_resource_fence_to_specific_409(tmp_path: Path) -> None:
    from llm_loop.factory import build_engine
    from llm_loop.web import build_app

    engine = build_engine(_settings(tmp_path))
    sid = engine.session.create()
    journal = ExternalExecutionJournal(engine.session.event_store)
    assert journal.launched(
        session_id=sid,
        job_id="job-web-orphan",
        workspace_root=str(tmp_path),
        executor="execute_command",
        command_sha256="d" * 64,
    ) is not None

    response = TestClient(build_app(engine=engine)).delete(
        f"/api/v1/sessions/{sid}?confirm=true"
    )

    assert response.status_code == 409
    assert response.json()["error"] == "external_resource_busy"
    assert engine.session.exists(sid) is True


def test_cli_delete_reports_external_resource_busy_without_deleting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from llm_loop.cli import _cmd_delete
    from llm_loop.factory import build_engine

    engine = build_engine(_settings(tmp_path))
    sid = engine.session.create()
    journal = ExternalExecutionJournal(engine.session.event_store)
    assert journal.launched(
        session_id=sid,
        job_id="job-cli-orphan",
        workspace_root=str(tmp_path),
        executor="execute_command",
        command_sha256="e" * 64,
    ) is not None

    rc = _cmd_delete(engine, sid, True)
    output = capsys.readouterr().out

    assert rc == 1
    assert "外部资源" in output or "外部执行" in output
    assert engine.session.exists(sid) is True

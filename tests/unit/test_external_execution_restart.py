from __future__ import annotations

import os
import time

import pytest

from llm_loop.core.external_execution import ExternalExecutionJournal
from llm_loop.core.run_context import current_session_id, current_workspace_root
from llm_loop.event_log.store import EventStore
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.builtin.job_kill import JobKillTool
from llm_loop.tools.builtin.job_output import JobOutputTool
from llm_loop.tools.builtin.job_registry import JobRegistry


class _FakeProc:
    def __init__(self, *, pid: int = 12345, exit_code: int = 0) -> None:
        self.pid = pid
        self.returncode = exit_code
        self.stdout = None
        self.stderr = None
        self.terminated = False

    def wait(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15


def _fresh_registry(events: EventStore | None = None) -> JobRegistry:
    return JobRegistry(event_store=events)


def test_durable_launch_is_owner_scoped_and_fresh_runtime_reports_orphaned(tmp_path) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    reg = _fresh_registry(events)
    job_id = reg.create(
        _FakeProc(),
        "sleep 30",
        session_id="owner-a",
        workspace_root=str(tmp_path / "ws-a"),
        executor="execute_command",
    )
    assert job_id.startswith("job-")
    assert len(job_id) > len("job-1")

    local = reg.snapshot(job_id, session_id="owner-a")
    assert local is not None and local["state"] == "running"
    assert local["local_handle"] is True
    assert local["durable"] is True

    fresh = _fresh_registry(events)
    recovered = fresh.snapshot(job_id, session_id="owner-a")
    assert recovered is not None
    assert recovered["state"] == "orphaned"
    assert recovered["local_handle"] is False
    assert recovered["auto_reclaim"] is False
    assert recovered["workspace_root"] == str((tmp_path / "ws-a").resolve())
    assert fresh.snapshot(job_id, session_id="owner-b") is None


def test_terminal_watcher_persists_exact_exit_code_for_fresh_runtime(tmp_path, monkeypatch) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    reg = _fresh_registry(events)
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path / "data"))
    job_id = reg.create(
        _FakeProc(exit_code=7),
        "false",
        session_id="owner-terminal",
        workspace_root=str(tmp_path),
        executor="execute_command",
    )
    reg.start_readers(job_id)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        snap = reg.snapshot(job_id, session_id="owner-terminal")
        if snap and snap["state"] == "failed":
            break
        time.sleep(0.01)
    fresh = _fresh_registry(events).snapshot(job_id, session_id="owner-terminal")
    assert fresh is not None
    assert fresh["state"] == "failed"
    assert fresh["exit_code"] == 7
    assert fresh["local_handle"] is False


def test_durable_launch_failure_cannot_return_success_or_leave_unowned_process(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    reg = _fresh_registry(events)
    JobRegistry._instance = reg
    original_append = events.append

    def _fail_launch(session_id, event_type, payload):  # noqa: ANN001, ANN202
        if event_type == "external.execution.launched":
            return None
        return original_append(session_id, event_type, payload)

    monkeypatch.setattr(events, "append", _fail_launch)
    ws = tmp_path / "ws"
    ws.mkdir()
    marker = ws / "must-not-appear.txt"
    sid_token = current_session_id.set("owner-launch-fail")
    ws_token = current_workspace_root.set(str(ws))
    try:
        result = ExecuteCommandTool(timeout_s=5).execute(
            command=f"sleep 0.2; echo BAD > {marker.name}",
            run_in_background=True,
        )
    finally:
        current_workspace_root.reset(ws_token)
        current_session_id.reset(sid_token)
    assert result.status.value != "success"
    time.sleep(0.5)
    assert marker.exists() is False
    assert reg.active_count() == 0


def test_session_cancel_attempts_durable_fact_before_local_signal(tmp_path, monkeypatch) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    reg = _fresh_registry(events)
    proc = _FakeProc()
    job_id = reg.create(
        proc,
        "sleep 30",
        session_id="owner-cancel",
        workspace_root=str(tmp_path),
        executor="execute_command",
    )
    original_append = events.append
    observed: list[bool] = []

    def _observe(session_id, event_type, payload):  # noqa: ANN001, ANN202
        if event_type == "external.execution.cancel_requested":
            observed.append(proc.terminated)
        return original_append(session_id, event_type, payload)

    monkeypatch.setattr(events, "append", _observe)
    monkeypatch.setattr(os, "getpgid", lambda _pid: (_ for _ in ()).throw(ProcessLookupError()))
    assert reg.cancel_session("owner-cancel") == 1
    assert observed == [False]
    assert proc.terminated is True
    snap = reg.snapshot(job_id, session_id="owner-cancel")
    assert snap is not None and snap["cancel_requested"] is True


def test_cancel_fact_failure_still_stops_local_job_without_false_recovery_fact(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    reg = _fresh_registry(events)
    proc = _FakeProc()
    job_id = reg.create(
        proc,
        "sleep 30",
        session_id="owner-cancel-fail",
        workspace_root=str(tmp_path),
        executor="execute_command",
    )
    original_append = events.append

    def _fail_cancel(session_id, event_type, payload):  # noqa: ANN001, ANN202
        if event_type == "external.execution.cancel_requested":
            return None
        return original_append(session_id, event_type, payload)

    monkeypatch.setattr(events, "append", _fail_cancel)
    monkeypatch.setattr(os, "getpgid", lambda _pid: (_ for _ in ()).throw(ProcessLookupError()))
    assert reg.cancel_session("owner-cancel-fail") == 1
    assert proc.terminated is True
    fresh = _fresh_registry(events).snapshot(job_id, session_id="owner-cancel-fail")
    assert fresh is not None
    assert fresh["state"] == "orphaned"
    assert fresh["cancel_requested"] is False
    assert fresh["auto_reclaim"] is False


def test_fresh_job_output_reads_durable_facts_but_job_kill_never_reclaims_orphan(
    tmp_path,
) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    reg = _fresh_registry(events)
    job_id = reg.create(
        _FakeProc(),
        "sleep 30",
        session_id="owner-query",
        workspace_root=str(tmp_path),
        executor="execute_command",
    )
    JobRegistry._instance = _fresh_registry(events)
    token = current_session_id.set("owner-query")
    try:
        out = JobOutputTool().execute(job_id=job_id)
        kill = JobKillTool().execute(job_id=job_id)
    finally:
        current_session_id.reset(token)
    assert out.status.value == "success"
    assert "orphaned" in out.content
    assert "auto_reclaim=false" in out.content
    assert kill.status.value == "failure"
    assert "orphan" in kill.content.lower() or "本进程" in kill.content


def test_eventstore_disabled_is_explicit_legacy_process_local() -> None:
    events = EventStore("/tmp/unused-external-execution-events", enabled=False)
    reg = _fresh_registry(events)
    job_id = reg.create(_FakeProc(), "echo ok", session_id="legacy")
    local = reg.snapshot(job_id, session_id="legacy")
    assert local is not None
    assert local["durable"] is False
    assert local["state"] == "running"
    assert _fresh_registry(events).snapshot(job_id, session_id="legacy") is None


def test_external_execution_events_are_mechanical_and_registered(tmp_path) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    journal = ExternalExecutionJournal(events)
    job_id = "job-contract"
    launched = journal.launched(
        session_id="owner-contract",
        job_id=job_id,
        workspace_root=str(tmp_path),
        executor="execute_command",
        command_sha256="a" * 64,
        pid=12,
        pgid=12,
    )
    assert launched is not None
    assert journal.cancel_requested(
        session_id="owner-contract", job_id=job_id, reason="session_cancel"
    ) is not None
    assert journal.terminal(
        session_id="owner-contract", job_id=job_id, exit_code=-15, killed=True
    ) is not None
    state = journal.state("owner-contract", job_id)
    assert state is not None
    assert state.state == "killed"
    assert state.exit_code == -15
    assert state.cancel_requested is True


def test_tool_registry_session_cancel_reaches_local_external_jobs_without_completion_gate(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from llm_loop.tools.registry import ToolRegistry

    events = EventStore(tmp_path / "events", enabled=True)
    reg = _fresh_registry(events)
    proc = _FakeProc()
    job_id = reg.create(
        proc,
        "sleep 30",
        session_id="owner-hook",
        workspace_root=str(tmp_path),
        executor="execute_command",
    )
    tools = ToolRegistry()
    tools.add_session_cancel_hook(reg.cancel_session)
    monkeypatch.setattr(os, "getpgid", lambda _pid: (_ for _ in ()).throw(ProcessLookupError()))

    # Durable external jobs are lifecycle resources, not a semantic completion gate.
    assert tools.async_obligations("owner-hook") == []
    assert tools.cancel_session("owner-hook") == 1
    assert proc.terminated is True
    snap = reg.snapshot(job_id, session_id="owner-hook")
    assert snap is not None and snap["killed"] is True


def test_dsh_background_reuses_same_durable_external_execution_contract(tmp_path) -> None:
    from llm_loop.tools.builtin.dsh_task import DshTaskTool

    events = EventStore(tmp_path / "events", enabled=True)
    JobRegistry._instance = _fresh_registry(events)
    token = current_session_id.set("owner-dsh")
    try:
        receipt = DshTaskTool()._start_background(  # noqa: SLF001 - focused lifecycle contract
            "durable dsh probe",
            str(tmp_path),
            "/bin/echo",
        )
    finally:
        current_session_id.reset(token)
    assert receipt.status.value == "success"
    job_id = receipt.content.split("job_id=")[1].split()[0]
    deadline = time.monotonic() + 2
    journal = ExternalExecutionJournal(events)
    state = None
    while time.monotonic() < deadline:
        state = journal.state("owner-dsh", job_id)
        if state is not None and state.terminal_seq:
            break
        time.sleep(0.01)
    assert state is not None
    assert state.executor == "dsh_task"
    assert state.state == "completed"
    assert state.exit_code == 0

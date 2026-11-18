"""Trusted Host Task activation: session binding, Lane/Git CAS and Run ContextVar."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from llm_loop.core.run_context import (
    current_session_id,
    current_task_execution,
    current_workspace_root,
)
from llm_loop.core.task_capabilities import CapabilityResource, TaskLeaseClaims
from llm_loop.introspection.lane import LaneStore
from llm_loop.tools.task_runtime import (
    TaskRuntimeActivationError,
    resolve_task_execution_for_run,
)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def active_binding(tmp_path, monkeypatch):
    import llm_loop.tools.task_runtime as runtime

    a, b, host, data = (tmp_path / name for name in ("project-a", "project-b", "host", "data"))
    for path in (a, b, host, data):
        path.mkdir(exist_ok=True)
    a, b, host, data = (p.resolve() for p in (a, b, host, data))
    _git(a, "init", "-q")
    (a / "source.txt").write_text("version one")
    _git(a, "add", "source.txt")
    _git(
        a,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-q",
        "-m",
        "initial",
    )
    head = _git(a, "rev-parse", "HEAD")
    audit = data / "audit"
    audit.mkdir()
    lanes = LaneStore(audit, lock_strict=True, enforce_cross_goal=True, repo_root=tmp_path)
    lane = lanes.create(
        branch="task",
        worktree=str(a),
        base_main_sha=head,
        goal_id="GOAL-test",
        owner_session_id="owner-1",
        paths=["source.txt"],
    )
    row = lanes.update(lane.lane_id, expected_version=1, status="active", head_sha=head)
    claims = TaskLeaseClaims(
        "lease-12345678",
        "GOAL-test",
        "TASK-test",
        "owner-1",
        "agent-1",
        lane.lane_id,
        1,
        datetime.now(UTC) + timedelta(hours=1),
        (
            CapabilityResource("project", str(a), frozenset({"read", "write"})),
            CapabilityResource("project", str(b), frozenset({"read", "write"})),
        ),
    )

    class Authority:
        def __init__(self, root):
            self.root = root

        def discover_for_session(self, session_id):
            return claims

        def verify(self, lease_id, request):
            assert lease_id == claims.lease_id
            return claims

    monkeypatch.setattr(runtime, "RootOwnedTaskAuthority", Authority)
    return a, b, host, data, lanes, claims, row


def test_missing_installation_keeps_legacy_context(tmp_path):
    assert (
        resolve_task_execution_for_run(
            session_id="owner-1",
            workspace_root=str(tmp_path),
            data_dir=str(tmp_path),
            authority_root=tmp_path / "not-installed",
        )
        is None
    )


def test_signed_session_binding_activates_only_matching_lane_and_head(active_binding):
    a, b, host, data, _lanes, claims, row = active_binding
    ctx = resolve_task_execution_for_run(
        session_id="owner-1",
        workspace_root=str(a),
        data_dir=str(data),
        authority_root=host,
    )
    assert ctx is not None
    assert ctx.lease_id == claims.lease_id
    assert ctx.lane_version == row["version"]
    sid = current_session_id.set("owner-1")
    ws = current_workspace_root.set(str(a))
    task = current_task_execution.set(ctx)
    try:
        assert ctx.authorize_file(str(b / "new.txt"), "write") == str(b)
    finally:
        current_task_execution.reset(task)
        current_workspace_root.reset(ws)
        current_session_id.reset(sid)


def test_wrong_workspace_or_git_head_fails_closed(active_binding):
    a, b, host, data, _lanes, _claims, _row = active_binding
    with pytest.raises(TaskRuntimeActivationError, match="task_lane_binding_mismatch"):
        resolve_task_execution_for_run(
            session_id="owner-1",
            workspace_root=str(b),
            data_dir=str(data),
            authority_root=host,
        )
    (a / "source.txt").write_text("version two")
    _git(a, "add", "source.txt")
    _git(
        a,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-q",
        "-m",
        "new head",
    )
    with pytest.raises(TaskRuntimeActivationError, match="task_git_head_cas_conflict"):
        resolve_task_execution_for_run(
            session_id="owner-1",
            workspace_root=str(a),
            data_dir=str(data),
            authority_root=host,
        )


def test_loop_generator_resumes_with_task_context_and_resets(build_test_engine, monkeypatch):
    import llm_loop.tools.task_runtime as runtime

    sentinel = object()
    observed = []
    monkeypatch.setattr(runtime, "resolve_task_execution_for_run", lambda **kwargs: sentinel)
    engine, _llm = build_test_engine([{"content": "unused"}])

    def fake_inner(*args, **kwargs):
        observed.append(current_task_execution.get())
        yield "first"
        observed.append(current_task_execution.get())
        yield "second"
        observed.append(current_task_execution.get())
        return None

    monkeypatch.setattr(engine, "_run_stream_inner", fake_inner)
    stream = engine.run_stream("s1", "hello")
    assert next(stream) == "first"
    assert current_task_execution.get() is None
    assert next(stream) == "second"
    assert current_task_execution.get() is None
    with pytest.raises(StopIteration):
        next(stream)
    assert observed == [sentinel, sentinel, sentinel]
    assert current_task_execution.get() is None


def test_loop_invalid_binding_never_enters_provider(build_test_engine, monkeypatch):
    import llm_loop.tools.task_runtime as runtime

    def invalid(**kwargs):
        raise TaskRuntimeActivationError("authority_bindings_ambiguous")

    monkeypatch.setattr(runtime, "resolve_task_execution_for_run", invalid)
    engine, _llm = build_test_engine([{"content": "unused"}])
    entered = []
    monkeypatch.setattr(
        engine,
        "_run_stream_inner",
        lambda *args, **kwargs: entered.append(True),
    )
    with pytest.raises(TaskRuntimeActivationError, match="authority_bindings_ambiguous"):
        list(engine.run_stream("s1", "hello"))
    assert entered == []
    assert current_task_execution.get() is None

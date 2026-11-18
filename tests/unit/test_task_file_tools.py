"""Native read_file/edit_file Task Lease E2E with existing WAL binding."""

from __future__ import annotations

import hashlib
import re
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.core.run_context import (
    current_session_id,
    current_task_execution,
    current_workspace_root,
    current_write_scope,
)
from llm_loop.core.task_capabilities import CapabilityResource, TaskLeaseClaims
from llm_loop.introspection.lane import LaneStore
from llm_loop.tools.builtin.edit_file import EditFileTool
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.task_authority import TaskAuthorityError
from llm_loop.tools.task_execution import TrustedTaskExecution


class FakeAuthority:
    def __init__(self, root, claims):
        self.root = root
        self.claims = claims
        self.revoked = False

    def verify(self, lease_id, request):
        if self.revoked:
            raise TaskAuthorityError("authority_lease_revoked")
        assert lease_id == self.claims.lease_id
        return self.claims


class FakeJournal:
    enabled = True

    def __init__(self, expected_root: Path, authority: FakeAuthority):
        self.expected_root = str(expected_root)
        self.authority = authority
        self.events = []
        self.revoke_at_fence = False

    def effect_prepared(self, session_id, **kwargs):
        assert kwargs["workspace_root"] == self.expected_root
        self.events.append(("prepared", kwargs["canonical_path"]))
        return True

    def effect_observed(self, **kwargs):
        assert kwargs["workspace_root"] == self.expected_root
        self.events.append(("observed", kwargs["canonical_path"]))
        return True

    @contextmanager
    def effect_mutation_authority(self, binding):
        if self.revoke_at_fence:
            self.authority.revoked = True
        yield True


@pytest.fixture
def tool_env(tmp_path, monkeypatch):
    a, b, c, audit, host = (tmp_path / name for name in ("a", "b", "c", "audit", "host"))
    for p in (a, b, c, audit, host):
        p.mkdir(mode=0o700)
    a, b, c, audit, host = (p.resolve() for p in (a, b, c, audit, host))
    target = b / "file.txt"
    target.write_text("original text\n")
    lanes = LaneStore(audit, lock_strict=True, enforce_cross_goal=True, repo_root=a)
    lane = lanes.create(
        branch="task",
        worktree=str(a),
        base_main_sha="a" * 40,
        goal_id="GOAL-test",
        owner_session_id="owner-1",
        paths=["file.txt"],
    )
    row = lanes.update(lane.lane_id, expected_version=1, status="active", head_sha="a" * 40)
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
    authority = FakeAuthority(host, claims)
    task = TrustedTaskExecution(
        authority=cast(Any, authority),
        lanes=lanes,
        lease_id=claims.lease_id,
        goal_id=claims.goal_id,
        task_id=claims.task_id,
        owner_session_id=claims.owner_session_id,
        agent_id=claims.agent_id,
        lane_id=claims.lane_id,
        revision=claims.revision,
        lane_version=row["version"],
        expected_head=row["head_sha"],
        protected_roots=(str(audit), str(host)),
    )
    journal = FakeJournal(b, authority)
    binding = SimpleNamespace(
        journal=journal,
        workspace_root=str(a),
        session_id="owner-1",
        execution_id="exec-1",
        round_no=1,
        tool_call_id="call-1",
        tool_name="edit_file",
    )
    import llm_loop.core.tool_execution_journal as journal_module

    monkeypatch.setattr(journal_module, "current_tool_effect_binding", lambda: binding)
    tokens = (
        current_session_id.set("owner-1"),
        current_workspace_root.set(str(a)),
        current_task_execution.set(task),
        current_write_scope.set(None),
    )
    try:
        yield a, b, c, target, authority, journal, binding
    finally:
        current_write_scope.reset(tokens[3])
        current_task_execution.reset(tokens[2])
        current_workspace_root.reset(tokens[1])
        current_session_id.reset(tokens[0])


def _ref(read_result):
    match = re.search(r"snapshot_ref=(sha256:[0-9a-f]{64})", read_result.content)
    assert match is not None, read_result.content
    return match.group(1)


def test_native_task_read_snapshot_to_edit_with_original_wal(tool_env):
    _a, b, _c, target, _authority, journal, _binding = tool_env
    read = ReadFileTool().execute(path=str(target), snapshot=True)
    assert read.status == ToolResultStatus.SUCCESS, read.content
    assert "original text" in read.content
    assert _ref(read) == "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
    edited = EditFileTool().run(
        {
            "path": str(target),
            "old_string": "original",
            "new_string": "approved",
            "expected_snapshot_ref": _ref(read),
        }
    )
    assert edited.status == ToolResultStatus.SUCCESS, edited.content
    assert target.read_text() == "approved text\n"
    assert journal.events == [("prepared", str(target)), ("observed", str(target))]


def test_native_task_unapproved_read_and_sensitive_snapshot_denied(tool_env):
    _a, b, c, _target, _authority, _journal, _binding = tool_env
    outside = c / "secret.txt"
    outside.write_text("do not read")
    result = ReadFileTool().execute(path=str(outside), snapshot=False)
    assert result.status == ToolResultStatus.UNAUTHORIZED
    assert "do not read" not in result.content
    sensitive = b / ".env"
    sensitive.write_text("SECRET_KEY=private-value")
    result = ReadFileTool().execute(path=str(sensitive), snapshot=True)
    assert result.status == ToolResultStatus.FAILURE
    assert result.error_type == "SensitivePathSnapshotRefused"
    assert "private-value" not in result.content


def test_native_task_fd_read_rejects_hardlink_and_symlink_parent(tool_env):
    _a, b, c, _target, _authority, _journal, _binding = tool_env
    outside = c / "outside.txt"
    outside.write_text("never expose outside bytes")
    hardlink = b / "hardlink.txt"
    hardlink.hardlink_to(outside)
    result = ReadFileTool().execute(path=str(hardlink), snapshot=True)
    assert result.error_type == "TaskFileIdentityInvalid"
    assert "never expose" not in result.content
    alias = b / "alias"
    alias.symlink_to(c, target_is_directory=True)
    result = ReadFileTool().execute(path=str(alias / "outside.txt"), snapshot=False)
    assert result.status == ToolResultStatus.UNAUTHORIZED
    assert "never expose" not in result.content


def test_native_task_sensitive_read_redacts_without_snapshot(tool_env):
    _a, b, _c, _target, _authority, _journal, _binding = tool_env
    sensitive = b / ".env"
    sensitive.write_text("SECRET_KEY=secretvalue123456")
    result = ReadFileTool().execute(path=str(sensitive), snapshot=False)
    assert result.status == ToolResultStatus.SUCCESS
    assert "secretvalue123456" not in result.content
    assert "敏感内容已脱敏" in result.content


def test_native_task_stale_sha_and_missing_journal_denied(tool_env, monkeypatch):
    _a, _b, _c, target, _authority, journal, binding = tool_env
    ref = _ref(ReadFileTool().execute(path=str(target), snapshot=True))
    target.write_text("original text\nexternal change")
    result = EditFileTool().run(
        {
            "path": str(target),
            "old_string": "original",
            "new_string": "bad",
            "expected_snapshot_ref": ref,
        }
    )
    assert result.error_type == "VersionConflict"
    assert target.read_text() == "original text\nexternal change"
    binding.journal.enabled = False
    result = EditFileTool().run(
        {
            "path": str(target),
            "old_string": "original",
            "new_string": "bad",
            "expected_snapshot_ref": "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest(),
        }
    )
    assert result.error_type == "task_file_durable_effect_sink_required"
    assert target.read_text() == "original text\nexternal change"


def test_native_task_revocation_at_wal_mutation_fence(tool_env):
    _a, _b, _c, target, _authority, journal, _binding = tool_env
    ref = _ref(ReadFileTool().execute(path=str(target), snapshot=True))
    journal.revoke_at_fence = True
    result = EditFileTool().run(
        {
            "path": str(target),
            "old_string": "original",
            "new_string": "bad",
            "expected_snapshot_ref": ref,
        }
    )
    assert result.status == ToolResultStatus.UNAUTHORIZED
    assert result.error_type == "authority_lease_revoked"
    assert target.read_text() == "original text\n"
    assert journal.events == [("prepared", str(target))]


def test_native_task_real_eventstore_persists_cross_project_wal(tool_env, tmp_path, monkeypatch):
    import llm_loop.core.tool_execution_journal as journal_module
    from llm_loop.core.tool_execution_journal import ToolExecutionJournal
    from llm_loop.event_log.model import (
        EVENT_TOOL_EXECUTION_EFFECT_OBSERVED,
        EVENT_TOOL_EXECUTION_EFFECT_PREPARED,
    )
    from llm_loop.event_log.store import EventStore

    a, b, _c, target, _authority, _fake_journal, _binding = tool_env
    store = EventStore(tmp_path / "events", enabled=True)
    journal = ToolExecutionJournal(
        event_store=store,
        result_root=tmp_path / "results",
        session_store=cast(Any, SimpleNamespace()),
    )
    monkeypatch.setattr(
        journal_module,
        "current_tool_effect_binding",
        lambda: journal_module._current_effect_binding.get(),
    )
    ref = _ref(ReadFileTool().execute(path=str(target), snapshot=True))
    with journal.effect_context(
        session_id="owner-1",
        execution_id="exec-real",
        round_no=1,
        call=SimpleNamespace(id="call-real", name="edit_file"),
        workspace_root=str(a),
    ):
        result = EditFileTool().run(
            {
                "path": str(target),
                "old_string": "original",
                "new_string": "approved",
                "expected_snapshot_ref": ref,
            }
        )
    assert result.status == ToolResultStatus.SUCCESS, result.content
    assert target.read_text() == "approved text\n"
    events = [
        e
        for e in store.read("owner-1")
        if e.type in (EVENT_TOOL_EXECUTION_EFFECT_PREPARED, EVENT_TOOL_EXECUTION_EFFECT_OBSERVED)
    ]
    assert [e.type for e in events] == [
        EVENT_TOOL_EXECUTION_EFFECT_PREPARED,
        EVENT_TOOL_EXECUTION_EFFECT_OBSERVED,
    ]
    assert all(e.payload["workspace_root"] == str(b) for e in events)
    assert all(e.payload["canonical_path"] == str(target) for e in events)


def test_native_task_real_run_lease_fence_denies_cross_project_mutation(
    tool_env,
    tmp_path,
    monkeypatch,
):
    import llm_loop.core.tool_execution_journal as journal_module
    from llm_loop.core.tool_execution_journal import ToolExecutionJournal
    from llm_loop.event_log.model import EVENT_TOOL_EXECUTION_EFFECT_PREPARED
    from llm_loop.event_log.store import EventStore

    a, _b, _c, target, _authority, _fake_journal, _binding = tool_env
    store = EventStore(tmp_path / "events", enabled=True)
    journal = ToolExecutionJournal(
        event_store=store,
        result_root=tmp_path / "results",
        session_store=cast(Any, SimpleNamespace()),
    )
    monkeypatch.setattr(
        journal_module,
        "current_tool_effect_binding",
        lambda: journal_module._current_effect_binding.get(),
    )
    ref = _ref(ReadFileTool().execute(path=str(target), snapshot=True))
    with journal.effect_context(
        session_id="owner-1",
        execution_id="exec-revoked",
        round_no=1,
        call=SimpleNamespace(id="call-revoked", name="edit_file"),
        workspace_root=str(a),
        lease_fence=lambda: False,
    ):
        result = EditFileTool().run(
            {
                "path": str(target),
                "old_string": "original",
                "new_string": "forbidden",
                "expected_snapshot_ref": ref,
            }
        )
    assert result.status != ToolResultStatus.SUCCESS
    assert target.read_text() == "original text\n"
    assert any(e.type == EVENT_TOOL_EXECUTION_EFFECT_PREPARED for e in store.read("owner-1"))


def test_native_task_real_run_generation_takeover_denies_write(tool_env, tmp_path, monkeypatch):
    import llm_loop.core.tool_execution_journal as journal_module
    from llm_loop.core.run_context import current_run_generation
    from llm_loop.core.tool_execution_journal import ToolExecutionJournal
    from llm_loop.event_log.store import EventStore

    class SessionGeneration:
        def active_run_generation(self, session_id):
            assert session_id == "owner-1"
            return "generation-new"

        @contextmanager
        def run_generation_authority(self, session_id, generation):
            assert session_id == "owner-1"
            yield generation == "generation-new"

    a, _b, _c, target, _authority, _fake_journal, _binding = tool_env
    store = EventStore(tmp_path / "events", enabled=True)
    journal = ToolExecutionJournal(
        event_store=store,
        result_root=tmp_path / "results",
        session_store=cast(Any, SessionGeneration()),
    )
    monkeypatch.setattr(
        journal_module,
        "current_tool_effect_binding",
        lambda: journal_module._current_effect_binding.get(),
    )
    ref = _ref(ReadFileTool().execute(path=str(target), snapshot=True))
    token = current_run_generation.set("generation-old")
    try:
        with journal.effect_context(
            session_id="owner-1",
            execution_id="exec-old",
            round_no=1,
            call=SimpleNamespace(id="call-old", name="edit_file"),
            workspace_root=str(a),
        ):
            result = EditFileTool().run(
                {
                    "path": str(target),
                    "old_string": "original",
                    "new_string": "forbidden",
                    "expected_snapshot_ref": ref,
                }
            )
    finally:
        current_run_generation.reset(token)
    assert result.status == ToolResultStatus.UNAUTHORIZED
    assert result.error_type == "E4_GENERATION_AUTHORITY"
    assert target.read_text() == "original text\n"

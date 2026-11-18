"""Task FileService cross-project edits with signed scope, WAL and CAS."""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from llm_loop.core.run_context import (
    current_session_id,
    current_task_execution,
    current_workspace_root,
    current_write_scope,
)
from llm_loop.core.task_capabilities import CapabilityResource, TaskLeaseClaims
from llm_loop.core.write_scope import WriteScope
from llm_loop.introspection.lane import LaneStore
from llm_loop.tools.task_authority import TaskAuthorityError
from llm_loop.tools.task_execution import TrustedTaskExecution
from llm_loop.tools.task_files import TaskFileAdapter, TaskFileError
from llm_loop.workspace.file_service import FileService, FileServiceError


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


class DurableSink:
    operation_id = "op-1"
    tool_call_id = "tool-1"
    tool_name = "edit_file"
    effect_kind = "file_edit"

    def __init__(self, root: Path, owner: str, authority: FakeAuthority):
        self.workspace_scope = str(root)
        self.owner_session_id = owner
        self.authority = authority
        self.prepared_count = 0
        self.observed_count = 0
        self.revoke_after_prepared = False
        self.on_prepared = None

    @property
    def records_durable(self):
        return True

    def prepared(self, *, canonical_path, before_bytes, expected_after_bytes):
        self.prepared_count += 1
        if self.on_prepared is not None:
            self.on_prepared()
        if self.revoke_after_prepared:
            self.authority.revoked = True
        return True

    def observed(
        self,
        *,
        canonical_path,
        actual_after_bytes,
        expected_after_bytes,
        actual_mtime_ns,
        artifact_ref,
    ):
        self.observed_count += 1
        return True

    @contextmanager
    def mutation_authority(self):
        yield True


@pytest.fixture
def cross_project(tmp_path):
    a, b, c, audit, authroot = (
        tmp_path / name for name in ("project-a", "project-b", "project-c", "audit", "host-trust")
    )
    for p in (a, b, c, audit, authroot):
        p.mkdir(mode=0o700)
    a, b, c, audit, authroot = (p.resolve() for p in (a, b, c, audit, authroot))
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
    authority = FakeAuthority(authroot, claims)
    ctx = TrustedTaskExecution(
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
        protected_roots=(str(audit), str(authroot)),
    )
    service = FileService(lock_root=audit / "file-locks")
    adapter = TaskFileAdapter(task=ctx, service=service)
    sink = DurableSink(b, "owner-1", authority)
    tokens = (
        current_session_id.set("owner-1"),
        current_workspace_root.set(str(a)),
        current_task_execution.set(ctx),
        current_write_scope.set(None),
    )
    try:
        yield a, b, c, audit, lanes, authority, ctx, adapter, sink, target
    finally:
        current_write_scope.reset(tokens[3])
        current_task_execution.reset(tokens[2])
        current_workspace_root.reset(tokens[1])
        current_session_id.reset(tokens[0])


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _edit(adapter, sink, target, *, sha=None):
    return adapter.edit_existing(
        path=str(target),
        old_string="original",
        new_string="approved",
        expected_sha256=sha or _sha(target),
        effect_sink=sink,
    )


def test_real_cross_project_edit_with_durable_fence(cross_project):
    _a, _b, _c, _audit, _lanes, _authority, _ctx, adapter, sink, target = cross_project
    result = _edit(adapter, sink, target)
    assert result.applied
    assert result.precondition_checked
    assert target.read_text() == "approved text\n"
    assert sink.prepared_count == 1
    assert sink.observed_count == 1


def test_write_only_lease_cannot_edit_existing_file(cross_project, monkeypatch):
    _a, _b, _c, _audit, _lanes, authority, _ctx, adapter, sink, target = cross_project
    original = authority.verify

    def reject_read(lease_id, request):
        if request.verb == "read":
            raise TaskAuthorityError("authority_read_verb_missing")
        return original(lease_id, request)

    monkeypatch.setattr(authority, "verify", reject_read)
    with pytest.raises(TaskFileError, match="authority_read_verb_missing"):
        _edit(adapter, sink, target)
    assert target.read_text() == "original text\n"
    assert sink.prepared_count == 0


def test_stale_exact_hash_and_unauthorized_third_project(cross_project):
    _a, _b, c, _audit, _lanes, _authority, _ctx, adapter, sink, target = cross_project
    stale = _sha(target)
    target.write_text("original text\nnew line")
    with pytest.raises(FileServiceError, match="VersionConflict"):
        _edit(adapter, sink, target, sha=stale)
    third = c / "file.txt"
    third.write_text("original text\n")
    with pytest.raises(TaskFileError, match="task_file_root_not_authorized"):
        _edit(adapter, sink, third)
    assert third.read_text() == "original text\n"


def test_revoked_between_prepared_and_mutation_no_write(cross_project):
    _a, _b, _c, _audit, _lanes, _authority, _ctx, adapter, sink, target = cross_project
    sink.revoke_after_prepared = True
    with pytest.raises(TaskFileError, match="authority_lease_revoked"):
        _edit(adapter, sink, target)
    assert target.read_text() == "original text\n"
    assert sink.prepared_count == 1
    assert sink.observed_count == 0


def test_sink_owner_scope_and_lock_root_must_match(cross_project, tmp_path):
    _a, b, _c, _audit, _lanes, authority, ctx, adapter, sink, target = cross_project
    sink.owner_session_id = "another-owner"
    with pytest.raises(TaskFileError, match="task_file_sink_identity_mismatch"):
        _edit(adapter, sink, target)
    sink.owner_session_id = "owner-1"
    wrong = DurableSink(tmp_path, "owner-1", authority)
    with pytest.raises(TaskFileError, match="task_file_sink_identity_mismatch"):
        _edit(adapter, wrong, target)
    unsafe_adapter = TaskFileAdapter(task=ctx, service=FileService(lock_root=b / "locks"))
    with pytest.raises(TaskFileError, match="task_file_lock_root_untrusted"):
        _edit(unsafe_adapter, sink, target)
    assert target.read_text() == "original text\n"


def test_other_lane_and_declared_parent_scope_denied(cross_project):
    a, b, _c, _audit, lanes, _authority, _ctx, adapter, sink, target = cross_project
    lanes.create(
        branch="other",
        worktree=str(b),
        base_main_sha="b" * 40,
        goal_id="GOAL-other",
        owner_session_id="another-owner",
        paths=["other.txt"],
    )
    with pytest.raises(TaskFileError, match="task_other_lane_worktree_conflict"):
        _edit(adapter, sink, target)
    # Remove other Lane by releasing it through CAS, then test parent scope.
    other = next(r for r in lanes.list() if r["goal_id"] == "GOAL-other")
    lanes.close(
        other["lane_id"],
        expected_version=other["version"],
        status="closed",
        reason="test fixture release",
    )
    token = current_write_scope.set(WriteScope(paths=("file.txt",), declared=True))
    try:
        with pytest.raises(TaskFileError, match="task_parent_scope_denied"):
            _edit(adapter, sink, target)
    finally:
        current_write_scope.reset(token)
    assert target.read_text() == "original text\n"


def test_symlink_and_missing_precondition_denied(cross_project):
    _a, b, c, _audit, _lanes, _authority, _ctx, adapter, sink, target = cross_project
    link = b / "link.txt"
    link.symlink_to(c / "outside.txt")
    with pytest.raises(TaskFileError, match="task_file_path_not_canonical"):
        _edit(adapter, sink, link, sha="0" * 64)
    with pytest.raises(TaskFileError, match="task_file_version_precondition_required"):
        _edit(adapter, sink, target, sha="not-a-sha")
    assert target.read_text() == "original text\n"


def test_fd_pinned_edit_rejects_hardlinked_target(cross_project):
    _a, _b, c, _audit, _lanes, _authority, _ctx, adapter, sink, target = cross_project
    outside = c / "outside.txt"
    outside.write_text("original text\n")
    target.unlink()
    os.link(outside, target)
    with pytest.raises(FileServiceError, match="TaskFileIdentityInvalid"):
        _edit(adapter, sink, target)
    assert outside.read_text() == "original text\n"
    assert sink.prepared_count == 0


def test_fd_pinned_edit_rejects_same_bytes_inode_swap_after_wal_prepared(cross_project):
    _a, b, _c, _audit, _lanes, _authority, _ctx, adapter, sink, target = cross_project
    replacement = b / "replacement.txt"
    replacement.write_text("original text\n")
    sink.on_prepared = lambda: os.replace(replacement, target)
    with pytest.raises(FileServiceError, match="BaselineChanged"):
        _edit(adapter, sink, target)
    assert target.read_text() == "original text\n"
    assert sink.prepared_count == 1
    assert sink.observed_count == 0


def test_fd_pinned_edit_rejects_parent_directory_swap_after_wal_prepared(cross_project):
    _a, b, c, _audit, _lanes, _authority, _ctx, adapter, sink, _target = cross_project
    parent = b / "nested"
    parent.mkdir()
    target = parent / "file.txt"
    target.write_text("original text\n")
    outside_dir = c / "outside"
    outside_dir.mkdir()
    outside = outside_dir / "file.txt"
    outside.write_text("original text\n")

    def replace_parent():
        parent.rename(b / "moved")
        parent.symlink_to(outside_dir, target_is_directory=True)

    sink.on_prepared = replace_parent
    with pytest.raises((TaskFileError, FileServiceError)):
        _edit(adapter, sink, target)
    assert outside.read_text() == "original text\n"
    assert (b / "moved" / "file.txt").read_text() == "original text\n"
    assert sink.prepared_count == 1
    assert sink.observed_count == 0

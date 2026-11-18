"""Real execute_command Task Lease multi-root integration (foreground/background)."""

from __future__ import annotations

import sys
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
from llm_loop.core.write_scope import WriteScope
from llm_loop.introspection.lane import LaneStore
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.task_authority import TaskAuthorityError
from llm_loop.tools.task_execution import TrustedTaskExecution


class FakeAuthority:
    """Test-only claims source. Production must use root-owned signed receipts."""

    def __init__(self, root: Path, claims: TaskLeaseClaims) -> None:
        self.root = root
        self.claims = claims
        self.calls = 0
        self.revoke_on_call = 0

    def verify(self, lease_id, request):
        self.calls += 1
        if self.revoke_on_call and self.calls >= self.revoke_on_call:
            raise TaskAuthorityError("authority_lease_revoked")
        assert lease_id == self.claims.lease_id
        return self.claims


@pytest.fixture
def task_context(tmp_path):
    a, b, c = (tmp_path / name for name in ("project-a", "project-b", "project-c"))
    audit = tmp_path / "audit"
    authority_root = tmp_path / "root-owned-authority-stub"
    for path in (a, b, c, audit, authority_root):
        path.mkdir(mode=0o700)
    a, b, c, audit, authority_root = (p.resolve() for p in (a, b, c, audit, authority_root))
    lanes = LaneStore(audit, lock_strict=True, enforce_cross_goal=True, repo_root=a)
    lane = lanes.create(
        branch="task",
        worktree=str(a),
        base_main_sha="a" * 40,
        goal_id="GOAL-test",
        owner_session_id="owner-1",
        paths=["approved.txt"],
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
            CapabilityResource("project", str(a), frozenset({"write"})),
            CapabilityResource("project", str(b), frozenset({"write"})),
        ),
    )
    authority = FakeAuthority(authority_root, claims)
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
        protected_roots=(str(audit), str(authority_root)),
    )
    token_session = current_session_id.set("owner-1")
    token_root = current_workspace_root.set(str(a))
    token_task = current_task_execution.set(ctx)
    token_scope = current_write_scope.set(None)
    try:
        yield a, b, c, audit, authority, lanes, ctx
    finally:
        current_write_scope.reset(token_scope)
        current_task_execution.reset(token_task)
        current_workspace_root.reset(token_root)
        current_session_id.reset(token_session)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS real Seatbelt test")
def test_foreground_two_roots_allowed_third_denied(task_context):
    a, b, c, audit, authority, _lanes, _ctx = task_context
    good, bad = b / "approved.txt", c / "blocked.txt"
    tool = ExecuteCommandTool(sandbox_mode="sandbox-exec", safety_audit_dir=audit, timeout_s=10)
    result = tool.execute(
        command=f"printf approved > {good}; printf forbidden > {bad}", workdir=str(a)
    )
    assert good.read_text() == "approved"
    assert not bad.exists()
    assert result.status != ToolResultStatus.SUCCESS
    assert authority.calls >= 2


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS real Seatbelt test")
def test_foreground_create_and_rename_in_b_with_c_denied(task_context):
    """A signed Task sandbox allows normal B create/mv without opening C."""
    a, b, c, audit, _authority, _lanes, _ctx = task_context
    initial, renamed, forbidden = (b / "new.txt", b / "renamed.txt", c / "forbidden-rename.txt")
    command = (
        f"printf approved > {initial} && mv {initial} {renamed} && printf forbidden > {forbidden}"
    )
    result = ExecuteCommandTool(
        sandbox_mode="sandbox-exec",
        safety_audit_dir=audit,
        timeout_s=10,
    ).execute(command=command, workdir=str(a))
    assert result.status != ToolResultStatus.SUCCESS
    assert not initial.exists()
    assert renamed.read_text() == "approved"
    assert not forbidden.exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS real Seatbelt test")
def test_background_uses_same_task_sandbox(task_context):
    a, b, c, audit, authority, _lanes, _ctx = task_context
    good, bad = b / "background.txt", c / "blocked-bg.txt"
    tool = ExecuteCommandTool(sandbox_mode="sandbox-exec", safety_audit_dir=audit, timeout_s=10)
    result = tool.execute(
        command=f"printf background > {good}; printf denied > {bad}",
        workdir=str(a),
        run_in_background=True,
    )
    assert result.status == ToolResultStatus.SUCCESS, result.content
    for _ in range(100):
        if good.exists():
            break
        time.sleep(0.05)
    assert good.read_text() == "background"
    assert not bad.exists()
    assert authority.calls >= 2


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS real Seatbelt test")
def test_revocation_at_spawn_fence_denies_all_effects(task_context):
    a, b, _c, audit, authority, _lanes, _ctx = task_context
    authority.revoke_on_call = 2
    target = b / "must-not-exist.txt"
    tool = ExecuteCommandTool(sandbox_mode="sandbox-exec", safety_audit_dir=audit, timeout_s=10)
    result = tool.execute(command=f"printf forbidden > {target}", workdir=str(a))
    assert result.status == ToolResultStatus.UNAUTHORIZED
    assert result.error_type == "authority_lease_revoked"
    assert not target.exists()


def test_none_backend_fails_closed(task_context):
    a, b, _c, audit, _authority, _lanes, _ctx = task_context
    target = b / "must-not-exist.txt"
    tool = ExecuteCommandTool(sandbox_mode="none", safety_audit_dir=audit, timeout_s=10)
    result = tool.execute(command=f"printf forbidden > {target}", workdir=str(a))
    assert result.status == ToolResultStatus.ERROR
    assert result.error_type == "task_sandbox_backend_or_roots_unsupported"
    assert not target.exists()


def test_lane_cas_and_parent_scope_fail_closed(task_context):
    a, b, _c, audit, _authority, lanes, ctx = task_context
    target = b / "must-not-exist.txt"
    tool = ExecuteCommandTool(sandbox_mode="sandbox-exec", safety_audit_dir=audit, timeout_s=10)
    lanes.update(ctx.lane_id, expected_version=ctx.lane_version, head_sha="b" * 40)
    result = tool.execute(command=f"printf forbidden > {target}", workdir=str(a))
    assert result.error_type == "task_lane_cas_conflict"
    token = current_write_scope.set(WriteScope(paths=("approved.txt",), declared=True))
    try:
        result = tool.execute(command=f"printf forbidden > {target}", workdir=str(a))
        assert result.error_type in (
            "write_scope_violation",
            "task_parent_scope_requires_precise_compilation",
        )
    finally:
        current_write_scope.reset(token)
    assert not target.exists()


def test_other_active_lane_project_root_is_not_transferred(task_context):
    a, b, _c, audit, _authority, lanes, _ctx = task_context
    lanes.create(
        branch="other-lane",
        worktree=str(b),
        base_main_sha="c" * 40,
        goal_id="GOAL-other",
        owner_session_id="another-owner",
        paths=["other.txt"],
    )
    target = b / "must-not-exist.txt"
    tool = ExecuteCommandTool(sandbox_mode="sandbox-exec", safety_audit_dir=audit, timeout_s=10)
    result = tool.execute(command=f"printf forbidden > {target}", workdir=str(a))
    assert result.error_type == "task_other_lane_worktree_conflict"
    assert not target.exists()


def test_task_context_does_not_combine_with_host_grant(task_context):
    a, _b, _c, audit, _authority, _lanes, _ctx = task_context
    tool = ExecuteCommandTool(sandbox_mode="sandbox-exec", safety_audit_dir=audit, timeout_s=10)
    result = tool.execute(command="true", workdir=str(a), host_grant_id="abcdef123")
    assert result.error_type == "task_host_grant_conflict"


def test_unverified_parent_lease_cannot_widen_task(task_context):
    a, b, _c, audit, authority, _lanes, _ctx = task_context
    authority.claims = replace(authority.claims, parent_lease_id="lease-parent123")
    target = b / "must-not-exist.txt"
    tool = ExecuteCommandTool(sandbox_mode="sandbox-exec", safety_audit_dir=audit, timeout_s=10)
    result = tool.execute(command=f"printf forbidden > {target}", workdir=str(a))
    assert result.error_type == "task_parent_lease_chain_unverified"
    assert not target.exists()

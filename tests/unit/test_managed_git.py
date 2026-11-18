"""Real linked-worktree Git broker tests; never touch production Git metadata."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from llm_loop.core.run_context import (
    current_session_id,
    current_workspace_root,
    current_write_scope,
)
from llm_loop.core.task_capabilities import CapabilityRequest, CapabilityResource, TaskLeaseClaims
from llm_loop.core.write_scope import WriteScope
from llm_loop.introspection.lane import LaneStore
from llm_loop.tools.managed_git import GitCommitRequest, ManagedGitAdapter, ManagedGitError


def git(path: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


class FakeTrustedAuthority:
    """Only a unit-test fixture. Production requires RootOwnedTaskAuthority."""

    def __init__(self, claims: TaskLeaseClaims) -> None:
        self.claims = claims
        self.revoked = False

    def verify(self, lease_id: str, request: CapabilityRequest) -> TaskLeaseClaims:
        if self.revoked:
            from llm_loop.tools.task_authority import TaskAuthorityError

            raise TaskAuthorityError("authority_lease_revoked")
        assert lease_id == self.claims.lease_id
        return self.claims


@pytest.fixture
def setup_git(tmp_path):
    main = tmp_path / "repo"
    main.mkdir()
    git(main, "init", "-b", "main")
    git(main, "config", "user.name", "Test User")
    git(main, "config", "user.email", "test@example.invalid")
    (main / "initial.txt").write_text("initial\n")
    git(main, "add", "--", "initial.txt")
    git(main, "commit", "-m", "initial")
    linked = (tmp_path / "linked").resolve()
    git(main, "worktree", "add", "-b", "task", str(linked))
    assert (linked / ".git").is_file()
    assert str(linked) != git(linked, "rev-parse", "--absolute-git-dir")
    (linked / "hello.txt").write_text("hello\n")
    (linked / "other.txt").write_text("other\n")

    audit = tmp_path / "audit"
    audit.mkdir(mode=0o700)
    locks = audit / "git-locks"
    locks.mkdir(mode=0o700)
    store = LaneStore(audit, lock_strict=True, enforce_cross_goal=True, repo_root=linked)
    lane = store.create(
        branch="task",
        worktree=str(linked),
        base_main_sha=git(linked, "rev-parse", "HEAD"),
        goal_id="GOAL-test",
        owner_session_id="owner-1",
        paths=["hello.txt"],
    )
    row = store.update(
        lane.lane_id, expected_version=1, status="active", head_sha=git(linked, "rev-parse", "HEAD")
    )
    req = CapabilityRequest(
        "GOAL-test",
        "TASK-test",
        "owner-1",
        "agent-1",
        lane.lane_id,
        1,
        "project",
        str(linked),
        "git_commit",
    )
    claims = TaskLeaseClaims(
        "lease-12345678",
        req.goal_id,
        req.task_id,
        req.owner_session_id,
        req.agent_id,
        req.lane_id,
        req.expected_revision,
        datetime.now(UTC) + timedelta(hours=1),
        (CapabilityResource("project", str(linked), frozenset({"git_commit"})),),
    )
    authority = FakeTrustedAuthority(claims)
    adapter = ManagedGitAdapter(
        authority=cast(Any, authority),
        lanes=store,
        lock_dir=locks,
        protected_roots=(str(audit),),
    )
    item = GitCommitRequest(
        lease_id=claims.lease_id,
        capability=req,
        worktree=str(linked),
        expected_head=row["head_sha"],
        expected_lane_version=row["version"],
        expected_gitdir=git(linked, "rev-parse", "--absolute-git-dir"),
        expected_common_dir=git(linked, "rev-parse", "--git-common-dir"),
        paths=("hello.txt",),
        message="feat: safe commit",
    )
    token_session = current_session_id.set("owner-1")
    token_root = current_workspace_root.set(str(linked))
    token_scope = current_write_scope.set(None)
    try:
        yield main, linked, audit, store, authority, adapter, item
    finally:
        current_write_scope.reset(token_scope)
        current_workspace_root.reset(token_root)
        current_session_id.reset(token_session)


def test_real_linked_worktree_commit_and_lane_cas(setup_git):
    _main, linked, _audit, store, _authority, adapter, item = setup_git
    # A real hook must NOT execute even if installed in the common gitdir.
    hook = Path(git(linked, "rev-parse", "--git-common-dir")) / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 47\n")
    hook.chmod(0o755)
    receipt = adapter.commit_paths(item)
    assert receipt.old_head == item.expected_head
    assert receipt.new_head == git(linked, "rev-parse", "HEAD")
    assert git(linked, "rev-list", "--parents", "-n", "1", "HEAD").split()[1] == item.expected_head
    assert git(linked, "show", "--pretty=format:", "--name-only", "HEAD") == "hello.txt"
    assert (linked / "other.txt").read_text() == "other\n"
    assert store.get(item.capability.lane_id)["head_sha"] == receipt.new_head
    assert receipt.lane_version == item.expected_lane_version + 1


def test_lane_unowned_path_denied_before_git_write(setup_git):
    _main, linked, _audit, _store, _authority, adapter, item = setup_git
    malicious = GitCommitRequest(**{**item.__dict__, "paths": ("other.txt",)})
    with pytest.raises(ManagedGitError, match="git_lane_path_denied"):
        adapter.commit_paths(malicious)
    assert not git(linked, "diff", "--cached", "--name-only")


def test_stale_head_and_lane_version_denied(setup_git):
    _main, linked, _audit, _store, _authority, adapter, item = setup_git
    bad = GitCommitRequest(**{**item.__dict__, "expected_lane_version": 999})
    with pytest.raises(ManagedGitError, match="git_lane_cas_conflict"):
        adapter.commit_paths(bad)
    bad = GitCommitRequest(**{**item.__dict__, "expected_head": "0" * 40})
    with pytest.raises(ManagedGitError, match="git_lane_cas_conflict"):
        adapter.commit_paths(bad)
    assert not git(linked, "diff", "--cached", "--name-only")


def test_git_metadata_binding_denies_retargeting(setup_git):
    _main, linked, _audit, _store, _authority, adapter, item = setup_git
    changed = GitCommitRequest(**{**item.__dict__, "expected_gitdir": str(linked / ".git")})
    with pytest.raises(ManagedGitError, match="git_metadata_identity_mismatch"):
        adapter.commit_paths(changed)
    assert not git(linked, "diff", "--cached", "--name-only")


def test_revocation_and_parent_scope_denied(setup_git):
    _main, linked, _audit, _store, authority, adapter, item = setup_git
    authority.revoked = True
    with pytest.raises(ManagedGitError, match="authority_lease_revoked"):
        adapter.commit_paths(item)
    authority.revoked = False
    token = current_write_scope.set(WriteScope(paths=("other.txt",), declared=True))
    try:
        with pytest.raises(ManagedGitError, match="parent_scope_denied"):
            adapter.commit_paths(item)
    finally:
        current_write_scope.reset(token)
    assert not git(linked, "diff", "--cached", "--name-only")


def test_symlink_and_git_path_and_message_denied(setup_git):
    _main, linked, _audit, _store, _authority, adapter, item = setup_git
    (linked / "link.txt").symlink_to(linked / "hello.txt")
    for path in ("../escape", ".git/config", "link.txt", "-c"):
        bad = GitCommitRequest(**{**item.__dict__, "paths": (path,)})
        with pytest.raises(ManagedGitError):
            adapter.commit_paths(bad)
    bad = GitCommitRequest(**{**item.__dict__, "message": "\n--exec-path=/tmp"})
    with pytest.raises(ManagedGitError, match="git_message_invalid"):
        adapter.commit_paths(bad)


def test_external_filter_and_existing_staged_index_denied(setup_git):
    _main, linked, _audit, _store, _authority, adapter, item = setup_git
    (linked / ".gitattributes").write_text("hello.txt filter=evil\n")
    with pytest.raises(ManagedGitError, match="git_external_filter_denied"):
        adapter.commit_paths(item)
    (linked / ".gitattributes").unlink()
    git(linked, "add", "--", "other.txt")
    with pytest.raises(ManagedGitError, match="git_index_not_clean"):
        adapter.commit_paths(item)


def test_wrong_session_denied(setup_git):
    _main, _linked, _audit, _store, _authority, adapter, item = setup_git
    token = current_session_id.set("different-session")
    try:
        with pytest.raises(ManagedGitError, match="git_request_identity_invalid"):
            adapter.commit_paths(item)
    finally:
        current_session_id.reset(token)


def test_unverified_parent_lease_denies_git_effect(setup_git):
    _main, linked, _audit, _store, authority, adapter, item = setup_git
    authority.claims = replace(authority.claims, parent_lease_id="lease-parent123")
    with pytest.raises(ManagedGitError, match="git_parent_lease_chain_unverified"):
        adapter.commit_paths(item)
    assert not git(linked, "diff", "--cached", "--name-only")

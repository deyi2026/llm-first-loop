"""Model-facing bounded Task Git tool; real isolated linked-worktree effects only."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.core.run_context import current_session_id, current_task_execution
from llm_loop.introspection.task_store import TaskStore
from llm_loop.tools.builtin.task_git_commit import TaskGitCommitTool
from llm_loop.tools.task_execution import TrustedTaskExecution
from tests.unit.test_managed_git import git

pytest_plugins = ("tests.unit.test_managed_git",)


@pytest.fixture
def signed_git_task(setup_git):
    _main, linked, audit, lanes, authority, _adapter, item = setup_git
    claims = authority.claims
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
        lane_version=item.expected_lane_version,
        expected_head=item.expected_head,
        protected_roots=(str(audit),),
        task_state_validator=lambda: None,
    )
    token = current_task_execution.set(task)
    try:
        yield linked, audit, lanes, authority, item
    finally:
        current_task_execution.reset(token)


def test_model_tool_real_commit_updates_only_lane_owned_path(signed_git_task):
    linked, _audit, lanes, _authority, item = signed_git_task
    result = TaskGitCommitTool().execute(
        paths=["hello.txt"], message="feat: bounded model commit",
    )
    assert result.status == ToolResultStatus.SUCCESS
    body = json.loads(result.content.split("] ", 1)[1])
    assert body["old_head"] == item.expected_head
    assert body["new_head"] == git(linked, "rev-parse", "HEAD")
    assert body["paths"] == ["hello.txt"]
    assert body["pushed"] is False
    assert body["merged"] is False
    assert body["deployed"] is False
    assert lanes.get(item.capability.lane_id)["head_sha"] == body["new_head"]


def test_model_tool_missing_context_and_unknown_git_options_hold(setup_git):
    _main, linked, _audit, _lanes, _authority, _adapter, item = setup_git
    tool = TaskGitCommitTool()
    denied = tool.execute(paths=["hello.txt"], message="feat: test")
    assert denied.status == ToolResultStatus.UNAUTHORIZED
    assert denied.error_type == "task_context_not_active"
    denied = tool.execute(paths=["hello.txt"], message="feat: test", push=True)
    assert denied.error_type == "task_git_arguments_invalid"
    assert git(linked, "rev-parse", "HEAD") == item.expected_head


def test_model_tool_unowned_file_and_revoked_lease_do_not_stage(signed_git_task):
    linked, _audit, _lanes, authority, item = signed_git_task
    tool = TaskGitCommitTool()
    denied = tool.execute(paths=["other.txt"], message="feat: invalid path")
    assert denied.error_type == "git_lane_path_denied"
    authority.revoked = True
    denied = tool.execute(paths=["hello.txt"], message="feat: revoked")
    assert denied.error_type == "authority_lease_revoked"
    assert git(linked, "rev-parse", "HEAD") == item.expected_head
    assert not git(linked, "diff", "--cached", "--name-only")


def test_model_tool_task_done_or_wrong_session_denied(signed_git_task):
    linked, audit, _lanes, _authority, item = signed_git_task
    tool = TaskGitCommitTool()
    TaskStore(audit).update(
        item.capability.goal_id, item.capability.task_id, status="done",
    )
    denied = tool.execute(paths=["hello.txt"], message="feat: stale task")
    assert denied.error_type == "task_not_in_progress"
    sid = current_session_id.set("different-session")
    try:
        denied = tool.execute(paths=["hello.txt"], message="feat: wrong owner")
        assert denied.error_type == "task_git_workspace_or_session_invalid"
    finally:
        current_session_id.reset(sid)
    assert git(linked, "rev-parse", "HEAD") == item.expected_head


def test_model_tool_missing_lock_root_denies_without_effect(signed_git_task):
    linked, audit, _lanes, _authority, item = signed_git_task
    (audit / "git-locks").rmdir()
    denied = TaskGitCommitTool().execute(
        paths=["hello.txt"], message="feat: no lock",
    )
    assert denied.error_type == "git_lock_unavailable"
    assert git(linked, "rev-parse", "HEAD") == item.expected_head


def test_factory_registers_git_broker_only_after_host_install(
    fake_settings, tmp_path, monkeypatch,
):
    import llm_loop.tools.task_runtime as runtime
    from llm_loop.factory import build_engine

    host = tmp_path / "test-host"
    monkeypatch.setattr(runtime, "_installed_authority_root", lambda: host)
    legacy = build_engine(fake_settings)
    assert "task_git_commit" not in legacy.registry.names()
    host.mkdir()
    installed = build_engine(fake_settings)
    assert "task_git_commit" in installed.registry.names()
    assert (fake_settings.audit_dir / "git-locks").is_dir()

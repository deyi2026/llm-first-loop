"""Task-scoped service restart: signed admission plus detached worker revalidation."""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import llm_loop.runtime.service_control as sc
from llm_loop.core.message import ToolResultStatus
from llm_loop.core.run_context import current_session_id, current_task_execution
from llm_loop.tools.builtin.service_control import ServiceControlTool
from llm_loop.tools.task_execution import TaskExecutionError
from tests.unit.test_service_control_autonomous_restart import _git_fixture, _publish_gen1


@dataclass
class _Task:
    lease_id: str = "host-signed-lease-1"
    owner_session_id: str = "sess-task"
    lane_id: str = "lane-task"
    worktree: str = ""
    revoked: bool = False
    calls: list[tuple[str, bool]] = field(default_factory=list)

    @property
    def lanes(self):
        return self

    def get(self, _lane_id):
        return {"worktree": self.worktree}

    def authorize_service(self, target: str, *, os_permission_granted: bool) -> None:
        self.calls.append((target, os_permission_granted))
        if self.revoked:
            raise TaskExecutionError("authority_lease_revoked")


def _execute_as_task(tool, task, **kwargs):
    owner = current_session_id.set(task.owner_session_id)
    token = current_task_execution.set(task)
    try:
        return tool.execute(**kwargs)
    finally:
        current_task_execution.reset(token)
        current_session_id.reset(owner)


def test_signed_task_service_restart_is_durable_and_worker_fenced(tmp_path):
    _git_fixture(tmp_path)
    _publish_gen1(tmp_path)
    store = sc.ManagedServiceDeploymentStore(tmp_path / "data")
    spawned: list[str] = []
    tool = ServiceControlTool(store=store, worker_spawner=spawned.append)
    task = _Task(worktree=str(tmp_path))
    result = _execute_as_task(tool, task, action="restart", target="web", expected_generation=1)
    assert result.status == ToolResultStatus.SUCCESS
    assert len(spawned) == 1
    action = store.read_action(spawned[0])
    assert action is not None
    assert action.origin == "task-restart"
    assert action.task_lease_id == task.lease_id
    assert action.task_owner_session_id == task.owner_session_id
    assert action.task_worktree == str(tmp_path)
    assert action.deployment_generation == 1
    assert task.calls == [("web", True)]


@pytest.mark.parametrize("kwargs", [
    {"action": "restart", "target": "web"},
    {"action": "restart", "target": "all", "expected_generation": 1},
    {"action": "publish", "code_root": "/tmp/candidate"},
    {"action": "override", "action_id": "svc-x", "gate": "waiting_for_idle", "evidence": "x", "evidence_level": "E1", "reason": "x"},
    {"action": "restart", "target": "web", "expected_generation": 1, "task_lease_id": "model-forged"},
])
def test_task_service_unapproved_actions_remain_hold(tmp_path, kwargs):
    _git_fixture(tmp_path)
    _publish_gen1(tmp_path)
    store = sc.ManagedServiceDeploymentStore(tmp_path / "data")
    spawned: list[str] = []
    task = _Task(worktree=str(tmp_path))
    result = _execute_as_task(ServiceControlTool(store=store, worker_spawner=spawned.append), task, **kwargs)
    assert result.status == ToolResultStatus.FAILURE
    assert "task_service_worker_fence_unavailable" in result.content
    assert spawned == []
    assert list(store.actions_dir.glob("*.json")) == []


def test_task_service_revoked_before_accept_does_not_create_action(tmp_path):
    _git_fixture(tmp_path)
    _publish_gen1(tmp_path)
    store = sc.ManagedServiceDeploymentStore(tmp_path / "data")
    spawned: list[str] = []
    task = _Task(worktree=str(tmp_path), revoked=True)
    result = _execute_as_task(
        ServiceControlTool(store=store, worker_spawner=spawned.append),
        task, action="restart", target="web", expected_generation=1,
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "authority_lease_revoked" in result.content
    assert spawned == []
    assert list(store.actions_dir.glob("*.json")) == []


def test_task_worker_rejects_changed_lease_or_revocation(monkeypatch, tmp_path):
    _git_fixture(tmp_path)
    deployment = _publish_gen1(tmp_path)
    store = sc.ManagedServiceDeploymentStore(tmp_path / "data")
    action = store.accept_restart(
        target="web", expected_generation=1, requester_session_id="sess-task",
        origin="task-restart", task_lease_id="host-signed-lease-1",
        task_owner_session_id="sess-task", task_worktree=str(tmp_path),
    )
    import llm_loop.tools.task_runtime as task_runtime

    task = _Task(worktree=str(tmp_path))
    monkeypatch.setattr(task_runtime, "resolve_task_execution_for_run", lambda **_kwargs: task)
    assert sc._task_service_worker_fence(action, deployment) is None
    assert task.calls == [("web", True)]
    task.lease_id = "different-lease"
    assert sc._task_service_worker_fence(action, deployment) == "task_service_lease_changed"
    task.lease_id = action.task_lease_id
    task.revoked = True
    assert sc._task_service_worker_fence(action, deployment) == "authority_lease_revoked"


def test_task_worker_revocation_denies_before_physical_restart(monkeypatch, tmp_path):
    _git_fixture(tmp_path, script_body="#!/usr/bin/env bash\necho executed > marker.txt\n")
    _publish_gen1(tmp_path)
    store = sc.ManagedServiceDeploymentStore(tmp_path / "data")
    action = store.accept_restart(
        target="web", expected_generation=1, requester_session_id="sess-task",
        origin="task-restart", task_lease_id="host-signed-lease-1",
        task_owner_session_id="sess-task", task_worktree=str(tmp_path),
    )
    monkeypatch.setattr(sc, "_wait_for", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sc, "_task_service_worker_fence", lambda *_args: "authority_lease_revoked")
    rc = sc.run_action_worker(store, action.action_id)
    assert rc != 0
    final = store.read_action(action.action_id)
    assert final is not None and final.status == "failed"
    assert "authority_lease_revoked" in final.detail
    assert not (tmp_path / "marker.txt").exists()


def test_task_worker_revocation_between_admission_and_effect_denies(monkeypatch, tmp_path):
    _git_fixture(tmp_path, script_body="#!/usr/bin/env bash\necho executed > marker.txt\n")
    _publish_gen1(tmp_path)
    store = sc.ManagedServiceDeploymentStore(tmp_path / "data")
    action = store.accept_restart(
        target="web", expected_generation=1, requester_session_id="sess-task",
        origin="task-restart", task_lease_id="host-signed-lease-1",
        task_owner_session_id="sess-task", task_worktree=str(tmp_path),
    )
    monkeypatch.setattr(sc, "_wait_for", lambda *_args, **_kwargs: True)
    checks = 0

    def fence(_action, _deployment):
        nonlocal checks
        checks += 1
        return None if checks == 1 else "authority_lease_revoked"

    monkeypatch.setattr(sc, "_task_service_worker_fence", fence)
    assert sc.run_action_worker(store, action.action_id) != 0
    assert checks == 2
    final = store.read_action(action.action_id)
    assert final is not None and final.status == "failed"
    assert "authority_lease_revoked" in final.detail
    assert not (tmp_path / "marker.txt").exists()

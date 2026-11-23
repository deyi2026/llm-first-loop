"""Task-scoped service restart: signed admission plus detached worker revalidation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

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

    def authorize_service(self, target: str, *, os_permission_granted: bool, backend_supported: bool) -> None:
        self.calls.append((target, os_permission_granted))
        if self.revoked:
            raise TaskExecutionError("authority_lease_revoked")
        if not os_permission_granted or not backend_supported:
            raise TaskExecutionError("task_os_permission_required")


def _host_restart_capability(root: Path) -> None:
    script = root / "scripts" / "restart_mirror.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o700)


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
    _host_restart_capability(tmp_path)
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
    _host_restart_capability(tmp_path)
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
    worker_script = Path(deployment.code_root) / "src" / "llm_loop" / "tools" / "task_service_worker.py"
    worker_script.parent.mkdir(parents=True, exist_ok=True)
    worker_script.write_text("# test fixture\n")
    monkeypatch.setattr(task_runtime, "resolve_task_execution_for_run", lambda **_kwargs: task)
    import json
    from types import SimpleNamespace
    responses = [
        {"decision": "PASS", "action_id": action.action_id, "target": "web", "generation": 1},
        {"decision": "DENY", "reason": "task_service_lease_changed"},
        {"decision": "DENY", "reason": "authority_lease_revoked"},
    ]
    monkeypatch.setattr(sc.subprocess, "run", lambda *_a, **_k: SimpleNamespace(
        returncode=0 if responses[0]["decision"] == "PASS" else 1,
        stdout=json.dumps(responses.pop(0)),
    ))
    assert sc._task_service_worker_fence(store, action, deployment) is None
    assert sc._task_service_worker_fence(store, action, deployment) == "task_service_lease_changed"
    assert sc._task_service_worker_fence(store, action, deployment) == "authority_lease_revoked"


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

    def fence(_store, _action, _deployment):
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


def test_tools_plane_worker_verifies_persisted_action_and_real_resolver(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from llm_loop.tools import task_service_worker

    action = SimpleNamespace(
        action_id="svc-task-1", task_lease_id="host-signed-lease-1",
        origin="task-restart", target="web", status="running",
        deployment_generation=4, deployment_id="deploy-4",
        task_owner_session_id="sess-task", task_worktree=str(tmp_path),
    )
    desired = SimpleNamespace(generation=4, deployment_id="deploy-4", runtime_root=str(tmp_path))
    _host_restart_capability(tmp_path)
    class Store:
        def __init__(self, _path): pass
        def read_action(self, _id): return action
        def read(self): return desired
    task = _Task(worktree=str(tmp_path))
    monkeypatch.setattr(task_service_worker, "ManagedServiceDeploymentStore", Store)
    monkeypatch.setattr(task_service_worker, "resolve_task_execution_for_run", lambda **_kwargs: task)
    result = task_service_worker.verify_action(str(tmp_path), action.action_id)
    assert result == {"decision": "PASS", "action_id": "svc-task-1", "target": "web", "generation": 4}
    assert task.calls == [("web", True)]
    task.revoked = True
    result = task_service_worker.verify_action(str(tmp_path), action.action_id)
    assert result["decision"] == "DENY" and result["reason"] == "authority_lease_revoked"


def test_tools_plane_worker_denies_action_generation_or_forged_fields(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from llm_loop.tools import task_service_worker

    action = SimpleNamespace(
        action_id="svc-task-2", task_lease_id="host-signed-lease-1",
        origin="task-restart", target="all", status="running",
        deployment_generation=3, deployment_id="deploy-3",
        task_owner_session_id="sess-task", task_worktree=str(tmp_path),
    )
    desired = SimpleNamespace(generation=4, deployment_id="deploy-4", runtime_root=str(tmp_path))
    class Store:
        def __init__(self, _path): pass
        def read_action(self, _id): return action
        def read(self): return desired
    monkeypatch.setattr(task_service_worker, "ManagedServiceDeploymentStore", Store)
    monkeypatch.setattr(task_service_worker, "resolve_task_execution_for_run", lambda **_kwargs: pytest.fail("must not resolve a forged all action"))
    result = task_service_worker.verify_action(str(tmp_path), action.action_id)
    assert result["decision"] == "DENY"
    assert result["reason"] == "task_service_action_binding_invalid"


def test_detached_worker_real_isolated_subprocess_denies_without_action(tmp_path):
    """The real -I process must load crypto dependencies, not fail import."""
    import json
    import os
    import subprocess
    import sys
    from types import SimpleNamespace
    from typing import Any, cast

    code_root = Path(__file__).resolve().parents[2]
    script = code_root / "src" / "llm_loop" / "tools" / "task_service_worker.py"
    env = {**os.environ, "PYTHONPATH": str(tmp_path / "poison"), "PYTHONHOME": str(tmp_path / "bad")}
    proc = subprocess.run(
        [sys.executable, "-I", str(script), "--data-dir", str(tmp_path / "data"), "--action-id", "missing"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15, check=False,
    )
    assert proc.returncode == 1, proc.stderr
    assert json.loads(proc.stdout) == {"decision": "DENY", "reason": "task_service_action_missing"}
    assert "Traceback" not in proc.stderr

    action = SimpleNamespace(
        action_id="missing", task_lease_id="signed-lease", origin="task-restart", target="web",
    )
    deployment = SimpleNamespace(code_root=str(code_root), runtime_root=str(tmp_path), generation=1)
    store = SimpleNamespace(data_dir=tmp_path / "data")
    assert sc._task_service_worker_fence(
        cast(Any, store), cast(Any, action), cast(Any, deployment),
    ) == "task_service_action_missing"


def test_detached_worker_never_inherits_ambient_provider_or_python_environment(
    tmp_path, monkeypatch,
):
    """A service Host verifier must receive a minimal, non-secret environment."""
    import subprocess
    from types import SimpleNamespace
    from typing import Any, cast

    for key, value in (
        ("LLM_API_KEY", "do-not-forward-secret"),
        ("PYTHONHOME", str(tmp_path / "poison-home")),
        ("PYTHONPATH", str(tmp_path / "poison-src")),
        ("PYTHONINSPECT", "1"),
        ("PYTHONSTARTUP", str(tmp_path / "poison-startup")),
    ):
        monkeypatch.setenv(key, value)
    code_root = Path(__file__).resolve().parents[2]
    action = SimpleNamespace(
        action_id="nonexistent", task_lease_id="signed-lease",
        origin="task-restart", target="web",
    )
    deployment = SimpleNamespace(
        code_root=str(code_root), runtime_root=str(tmp_path), generation=1,
    )
    store = SimpleNamespace(data_dir=tmp_path / "data")
    real_run = subprocess.run
    observed: list[dict[str, str]] = []

    def recording_run(*args, **kwargs):
        observed.append(dict(kwargs["env"]))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(sc.subprocess, "run", recording_run)
    assert sc._task_service_worker_fence(
        cast(Any, store), cast(Any, action), cast(Any, deployment),
    ) == "task_service_action_missing"
    assert len(observed) == 1
    assert not set(observed[0]).intersection({
        "LLM_API_KEY", "PYTHONHOME", "PYTHONPATH", "PYTHONINSPECT", "PYTHONSTARTUP",
    })
    assert observed[0]["LFL_RUNTIME_ROOT"] == str(tmp_path)
    assert observed[0]["LFL_WORKSPACE_ROOT"] == str(code_root)

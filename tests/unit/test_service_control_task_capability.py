"""Task Lease cannot authorize detached service effects without worker-side fencing."""

from __future__ import annotations

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.core.run_context import current_task_execution
from tests.unit.test_service_control_argument_contract import _tool


@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "restart", "target": "web"},
        {"action": "restart", "target": "all"},
        {"action": "publish", "code_root": "/tmp/candidate"},
        {"action": "update", "code_root": "/tmp/candidate", "reason": "release"},
        {"action": "release", "service": "web", "reason": "release barrier"},
        {
            "action": "adopt",
            "service": "web",
            "expected_owner": "old",
            "evidence": "observed",
            "reason": "handoff",
        },
        {
            "action": "override",
            "action_id": "svc-1",
            "gate": "waiting_for_idle",
            "evidence": "observed",
            "evidence_level": "E1",
            "reason": "handoff",
        },
        {
            "action": "verify_acknowledge",
            "action_id": "svc-1",
            "verdict": "accept",
            "evidence": "observed",
            "reason": "confirm",
        },
    ],
)
def test_task_service_mutation_is_held_before_store_or_worker(tmp_path, arguments):
    tool, store, spawned = _tool(tmp_path)
    token = current_task_execution.set(object())
    try:
        result = tool.execute(**arguments)
    finally:
        current_task_execution.reset(token)
    assert result.status == ToolResultStatus.FAILURE
    assert "task_service_worker_fence_unavailable" in result.content
    assert spawned == []
    assert store.read() is None
    assert list(store.actions_dir.glob("*.json")) == []


def test_task_service_status_remains_read_only(tmp_path):
    tool, store, spawned = _tool(tmp_path)
    token = current_task_execution.set(object())
    try:
        result = tool.execute(action="status")
    finally:
        current_task_execution.reset(token)
    assert result.status == ToolResultStatus.SUCCESS
    assert "task_service_worker_fence_unavailable" not in result.content
    assert spawned == []
    assert store.read() is None


def test_legacy_service_restart_retains_original_generation_path(tmp_path):
    tool, _store, spawned = _tool(tmp_path)
    result = tool.execute(action="restart", target="web")
    assert "task_service_worker_fence_unavailable" not in result.content
    # Existing desired/generation gate, not Task, decides the outcome.
    assert result.status in (ToolResultStatus.SUCCESS, ToolResultStatus.FAILURE)
    assert not spawned or len(spawned) == 1

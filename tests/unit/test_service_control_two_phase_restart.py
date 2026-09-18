"""Two-phase self-restart: waiting holds no lifecycle lease (P0-A follow-up).

Covers the deadlock closed by this change: a session that dispatches a web/all
restart must be able to end its turn (releasing its whole-run lease) while the
detached worker waits, and a desired-state publish must proceed while any
restart action is only waiting.
"""

from __future__ import annotations

import dataclasses
import fcntl
import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

import llm_loop.runtime.service_control as sc
from llm_loop.runtime.service_control import (
    ManagedServiceDeployment,
    ManagedServiceDeploymentStore,
    run_action_worker,
)
from llm_loop.tools.builtin.service_control import ServiceControlTool


def _deployment(tmp_path: Path, generation: int = 1) -> ManagedServiceDeployment:
    scripts = tmp_path / "scripts"
    scripts.mkdir(exist_ok=True)
    script = scripts / "restart_mirror.sh"
    if not script.exists():
        script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)
    return ManagedServiceDeployment(
        schema="managed-service-deployment/v1",
        deployment_id=f"deploy-{generation}",
        generation=generation,
        git_head="a" * 40,
        code_root=str(tmp_path.resolve()),
        runtime_root=str(tmp_path.resolve()),
        webui_artifact_sha256="b" * 64,
    )


class _HeldRunLock:
    """Hold a session run lock exactly like an active foreground run."""

    def __init__(self, sessions_dir: Path, session_id: str) -> None:
        self.path = sessions_dir / f"{session_id}.run.lock"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)

    def release(self) -> None:
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()


def _write_heartbeat(
    runtime_root: Path, *, processing: str = "", queue_depth: int = 0
) -> None:
    path = runtime_root / "data" / "feishu_heartbeat.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"processing_msg_id": processing, "queue_depth": queue_depth}),
        encoding="utf-8",
    )


def _record_target_script(tmp_path: Path) -> None:
    script = tmp_path / "scripts" / "restart_mirror.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf "target=%s\\n" "$1" > "$LFL_RESTART_RUNTIME_ROOT/marker.txt"\n',
        encoding="utf-8",
    )
    script.chmod(0o755)


@pytest.fixture()
def fast_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc, "_REQUESTER_EXIT_POLL_S", 0.02)
    monkeypatch.setattr(sc, "_REQUESTER_EXIT_TIMEOUT_S", 0.5)
    monkeypatch.setattr(sc, "_IDLE_POLL_S", 0.02)
    monkeypatch.setattr(sc, "_IDLE_TIMEOUT_S", 0.5)
    monkeypatch.setattr(sc, "_STALE_WAITING_MARGIN_S", 0.0)


def _wait_for_status(
    store: ManagedServiceDeploymentStore, action_id: str, wanted: set[str]
):
    deadline = time.monotonic() + 5.0
    action = store.read_action(action_id)
    while time.monotonic() < deadline:
        action = store.read_action(action_id)
        if action is not None and action.status in wanted:
            return action
        time.sleep(0.01)
    return action


def test_web_restart_waits_for_requester_without_lifecycle_lease(
    tmp_path: Path, fast_waits: None
) -> None:
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    _record_target_script(tmp_path)
    store.compare_and_swap(_deployment(tmp_path), expected_generation=0)
    action = store.accept_restart(
        target="web", expected_generation=1, requester_session_id="session-A"
    )
    lock = _HeldRunLock(tmp_path / "data" / "sessions", "session-A")

    outcome: dict[str, int] = {}

    def _worker() -> None:
        outcome["rc"] = run_action_worker(store, action.action_id)

    thread = threading.Thread(target=_worker)
    thread.start()
    try:
        waiting = _wait_for_status(
            store, action.action_id, {"waiting_for_requester_exit"}
        )
        assert waiting is not None
        assert waiting.status == "waiting_for_requester_exit"

        # P0-A invariant: while the action only waits, the lifecycle lease is
        # free, so an operator publish would not be blocked.
        handle = store.lifecycle_lock_path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
    finally:
        lock.release()
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert outcome["rc"] == 0
    final = store.read_action(action.action_id)
    assert final is not None
    assert final.status == "succeeded"
    assert (tmp_path / "marker.txt").read_text(encoding="utf-8").strip() == "target=web"


def test_publish_during_wait_supersedes_action_without_restart(
    tmp_path: Path, fast_waits: None
) -> None:
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    _record_target_script(tmp_path)
    deployment = _deployment(tmp_path)
    store.compare_and_swap(deployment, expected_generation=0)
    action = store.accept_restart(
        target="web", expected_generation=1, requester_session_id="session-A"
    )
    lock = _HeldRunLock(tmp_path / "data" / "sessions", "session-A")

    outcome: dict[str, int] = {}

    def _worker() -> None:
        outcome["rc"] = run_action_worker(store, action.action_id)

    thread = threading.Thread(target=_worker)
    thread.start()
    try:
        waiting = _wait_for_status(
            store, action.action_id, {"waiting_for_requester_exit"}
        )
        assert waiting is not None
        assert waiting.status == "waiting_for_requester_exit"
        # Generation CAS during the wait proves publication was not blocked by
        # the waiting action (compare_and_swap needs the lifecycle lease).
        deployment2 = dataclasses.replace(
            deployment, deployment_id="deploy-2", generation=2
        )
        store.compare_and_swap(deployment2, expected_generation=1)
    finally:
        lock.release()
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert outcome["rc"] == 3
    final = store.read_action(action.action_id)
    assert final is not None
    assert final.status == "failed"
    assert "advanced while waiting" in final.detail
    assert not (tmp_path / "marker.txt").exists()


def test_requester_timeout_fails_closed(tmp_path: Path, fast_waits: None) -> None:
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(_deployment(tmp_path), expected_generation=0)
    action = store.accept_restart(
        target="web", expected_generation=1, requester_session_id="session-A"
    )
    lock = _HeldRunLock(tmp_path / "data" / "sessions", "session-A")
    try:
        rc = run_action_worker(store, action.action_id)
    finally:
        lock.release()
    assert rc == 1
    final = store.read_action(action.action_id)
    assert final is not None
    assert final.status == "failed"
    assert "requester run still active" in final.detail


def test_idle_timeout_fails_closed(tmp_path: Path, fast_waits: None) -> None:
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(_deployment(tmp_path), expected_generation=0)
    action = store.accept_restart(
        target="all", expected_generation=1, requester_session_id="session-A"
    )
    # requester already gone; a busy feishu heartbeat keeps the target non-idle
    _write_heartbeat(tmp_path, processing="msg-1")
    rc = run_action_worker(store, action.action_id)
    assert rc == 1
    final = store.read_action(action.action_id)
    assert final is not None
    assert final.status == "failed"
    assert "target still busy" in final.detail
    assert "feishu busy" in final.detail


def test_feishu_restart_skips_requester_gate(
    tmp_path: Path, fast_waits: None
) -> None:
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    _record_target_script(tmp_path)
    store.compare_and_swap(_deployment(tmp_path), expected_generation=0)
    action = store.accept_restart(
        target="feishu", expected_generation=1, requester_session_id="session-A"
    )
    lock = _HeldRunLock(tmp_path / "data" / "sessions", "session-A")
    try:
        rc = run_action_worker(store, action.action_id)
    finally:
        lock.release()
    assert rc == 0
    final = store.read_action(action.action_id)
    assert final is not None
    assert final.status == "succeeded"
    assert (tmp_path / "marker.txt").read_text(encoding="utf-8").strip() == "target=feishu"


def test_learning_target_records_targeted_action(tmp_path: Path) -> None:
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(_deployment(tmp_path), expected_generation=0)
    spawned: list[str] = []

    def _spawner(action_id: str) -> None:
        spawned.append(action_id)

    tool = ServiceControlTool(store=store, worker_spawner=_spawner)
    result = tool.execute(
        action="restart",
        target="learning",
        expected_generation=1,
        requester_session_id="session-tool",
    )
    assert result.status.value == "success"
    assert len(spawned) == 1
    recorded = store.read_action(spawned[0])
    assert recorded is not None
    assert recorded.target == "learning"
    assert "结束本轮" in result.content


def test_stale_waiting_action_reaped_on_next_accept(
    tmp_path: Path, fast_waits: None
) -> None:
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(_deployment(tmp_path), expected_generation=0)
    action = store.accept_restart(
        target="web", expected_generation=1, requester_session_id="session-A"
    )
    stale_age_s = sc._REQUESTER_EXIT_TIMEOUT_S + sc._IDLE_TIMEOUT_S + 10.0
    stale = dataclasses.replace(
        action,
        status="waiting_for_idle",
        updated_at=datetime.fromtimestamp(
            datetime.now(UTC).timestamp() - stale_age_s
        ).isoformat(),
    )
    with store.lease():
        store._write_action_unlocked(stale)

    fresh = store.accept_restart(
        target="web", expected_generation=1, requester_session_id="session-B"
    )
    reaped = store.read_action(action.action_id)
    assert reaped is not None
    assert reaped.status == "failed"
    assert "stale waiting state reaped" in reaped.detail
    assert fresh.status == "accepted"

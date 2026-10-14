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


def _git_deployment(tmp_path: Path, generation: int = 1) -> ManagedServiceDeployment:
    """Git-backed deployment for tests that reach Phase 3.

    The P0-A.1 in-lease binding reverify rejects targets that are not a
    clean git checkout matching the published HEAD, so success-path tests
    must build their deployment via ``build_deployment`` over a real repo.
    """
    import subprocess

    dist = tmp_path / "webui" / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text("<html>fixture</html>\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@test.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    return sc.build_deployment(
        code_root=str(tmp_path), runtime_root=str(tmp_path), generation=generation
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
    # EVO-20260920-213965a1 案1: 模拟"新进程"写 runtime manifest——
    # git_head 取 verify_head.txt（测试在部署构建后写入），pid=1 恒存活，
    # started_at 取当前 UTC（晚于 worker 捕获的 restarted_at）。
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf "target=%s\\n" "$1" > "$LFL_RESTART_RUNTIME_ROOT/marker.txt"\n'
        'head=$(cat "$LFL_RESTART_RUNTIME_ROOT/verify_head.txt" 2>/dev/null || echo "")\n'
        'started=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)\n'
        'mkdir -p "$LFL_RESTART_RUNTIME_ROOT/data/runtime"\n'
        'svcs="$1"\n'
        'if [ "$svcs" = "all" ]; then svcs="web feishu learning"; fi\n'
        "for svc in $svcs; do\n"
        '  printf \'{"pid": 1, "git_head": "%s", "started_at": "%s"}\\n\' "$head" "$started" \\\n'
        '    > "$LFL_RESTART_RUNTIME_ROOT/data/runtime/runtime_manifest.$svc.json"\n'
        "done\n",
        encoding="utf-8",
    )
    script.chmod(0o755)


def _write_verify_head(tmp_path: Path, deployment: ManagedServiceDeployment) -> None:
    """成功路径: manifest head 与 desired 一致（自核验通过）."""
    (tmp_path / "verify_head.txt").write_text(deployment.git_head, encoding="utf-8")


@pytest.fixture()
def fast_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc, "_REQUESTER_EXIT_POLL_S", 0.02)
    monkeypatch.setattr(sc, "_REQUESTER_EXIT_TIMEOUT_S", 0.5)
    monkeypatch.setattr(sc, "_IDLE_POLL_S", 0.02)
    monkeypatch.setattr(sc, "_IDLE_TIMEOUT_S", 0.5)
    monkeypatch.setattr(sc, "_STALE_WAITING_MARGIN_S", 0.0)
    monkeypatch.setattr(sc, "_VERIFY_POLL_S", 0.02)
    monkeypatch.setattr(sc, "_VERIFY_TIMEOUT_S", 0.3)


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
    deployment = _git_deployment(tmp_path)
    _write_verify_head(tmp_path, deployment)
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
    # EVO-20260920-213965a1 案1: 终态记录含控制面自核验结论。
    assert "verify=confirmed_ok" in (final.detail or "")
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
    # B（2026-10-14）：supersede 从 Phase3 lease 复检（rc=3）提前到等待
    # 循环（rc=1），语义等价——终态 failed、不执行 restart、证据链保留。
    assert outcome["rc"] == 1
    final = store.read_action(action.action_id)
    assert final is not None
    assert final.status == "failed"
    assert "superseded while waiting" in final.detail
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
    deployment = _git_deployment(tmp_path)
    _write_verify_head(tmp_path, deployment)
    store.compare_and_swap(deployment, expected_generation=0)
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
    assert "verify=confirmed_ok" in (final.detail or "")
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
    # accepted 回执提供终态查询路径，不强制发起方立即结束本轮
    # （EVO-20260924-8266b693 C：受理≠完成 + 终态核对入口）
    assert "受理≠完成" in result.content
    assert "终态核对入口" in result.content
    assert "service_action_terminal" in result.content


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


def test_verify_failure_records_evidence_without_rerun(
    tmp_path: Path, fast_waits: None
) -> None:
    """lifecycle_agency L6/L7: 脚本 rc=0 但核验证据明确失败 → failed(rc=5)。

    manifest git_head 持续 mismatch，模拟"新进程没起来/起的还是旧版本"。
    程序只如实落三态证据（confirmed_fail + git_head_mismatch），不再自动
    重跑物理脚本、不再自动替模型判终态。
    """
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    _record_target_script(tmp_path)
    script = tmp_path / "scripts" / "restart_mirror.sh"
    script.write_text(
        script.read_text(encoding="utf-8")
        + 'echo run >> "$LFL_RESTART_RUNTIME_ROOT/runs.txt"\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    deployment = _git_deployment(tmp_path)
    (tmp_path / "verify_head.txt").write_text("f" * 40, encoding="utf-8")
    store.compare_and_swap(deployment, expected_generation=0)
    action = store.accept_restart(
        target="feishu", expected_generation=1, requester_session_id="session-A"
    )
    lock = _HeldRunLock(tmp_path / "data" / "sessions", "session-A")
    try:
        rc = run_action_worker(store, action.action_id)
    finally:
        lock.release()
    assert rc == 5
    final = store.read_action(action.action_id)
    assert final is not None
    assert final.status == "failed"
    assert final.verify_verdict == "confirmed_fail"
    assert "verify=confirmed_fail" in (final.detail or "")
    assert "git_head_mismatch" in (final.detail or "")
    # L6: 程序不再据核验结论自动重跑——物理脚本只执行一次。
    assert (tmp_path / "runs.txt").read_text(encoding="utf-8").splitlines() == ["run"]

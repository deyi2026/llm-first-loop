"""Restart admission-barrier regressions (design v1.2 §8.2/§8.3; T31/T08/T10/T11).

The waiting window of a managed restart must block NEW run creation on its
target services: a message arriving during the window may only receive a
durable queued receipt carrying the operation id.  These tests pin the store
side of that contract: barriers established atomically with acceptance,
released exactly where the §8.3 lifecycle says, never clearable by foreign
owners or timeouts, with an explicit operator override exit.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from llm_loop.runtime import service_control as sc
from llm_loop.runtime.admission_barrier import (
    AdmissionBarrierRegistry,
    BarrierConflictError,
)


def _deployment(tmp_path: Path, generation: int = 1, code_root: str | None = None) -> sc.ManagedServiceDeployment:
    return sc.ManagedServiceDeployment(
        schema=sc._DEPLOYMENT_SCHEMA,
        deployment_id=f"dep-{generation}",
        generation=generation,
        git_head="a" * 40,
        code_root=code_root or str(tmp_path),
        runtime_root=str(tmp_path),
        webui_artifact_sha256="b" * 64,
    )


def _publish(store: sc.ManagedServiceDeploymentStore, deployment: sc.ManagedServiceDeployment, expected: int) -> None:
    store.compare_and_swap(deployment, expected_generation=expected)


def _store(tmp_path: Path) -> sc.ManagedServiceDeploymentStore:
    store = sc.ManagedServiceDeploymentStore(tmp_path / "data")
    _publish(store, _deployment(tmp_path), 0)
    return store


class _HeldRunLock:
    """Fake active-run lock on a session (foreground.py layout)."""

    def __init__(self, data_dir: Path, session_id: str) -> None:
        run_root = data_dir / "runs" / session_id
        run_root.mkdir(parents=True, exist_ok=True)
        (run_root / "run.lock").write_text(
            json.dumps({"session_id": session_id, "pid": os.getpid(), "started_at": "2026-09-20T00:00:00+00:00"}),
            encoding="utf-8",
        )

    def release(self) -> None:
        for path in sorted(Path(self.run_root).glob("run.lock")):  # noqa: B007 - trivial
            path.unlink(missing_ok=True)


@pytest.fixture()
def fast_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc, "_REQUESTER_EXIT_POLL_S", 0.02)
    monkeypatch.setattr(sc, "_REQUESTER_EXIT_TIMEOUT_S", 0.1)
    monkeypatch.setattr(sc, "_IDLE_POLL_S", 0.02)
    monkeypatch.setattr(sc, "_IDLE_TIMEOUT_S", 0.1)
    monkeypatch.setattr(sc, "_VERIFY_POLL_S", 0.02)
    monkeypatch.setattr(sc, "_VERIFY_TIMEOUT_S", 0.1)
    monkeypatch.setattr(sc, "_VERIFY_MANIFEST_WAIT_S", 0.02)


class TestRegistrySemantics:
    def test_blocked_missing_dir_is_none_and_read_only(self, tmp_path: Path) -> None:
        reg = AdmissionBarrierRegistry(tmp_path)
        assert reg.blocked("web") is None
        assert not (tmp_path / "runtime" / "service-control-barriers").exists()

    def test_establish_then_blocked_returns_owner(self, tmp_path: Path) -> None:
        reg = AdmissionBarrierRegistry(tmp_path)
        barrier = reg.establish("web", operation_id="svc-1", reason="restart")
        assert barrier.service == "web"
        view = reg.blocked("web")
        assert view is not None
        assert view.operation_id == "svc-1"
        assert not view.corrupt

    def test_establish_conflict_with_other_owner(self, tmp_path: Path) -> None:
        reg = AdmissionBarrierRegistry(tmp_path)
        reg.establish("web", operation_id="svc-1", reason="restart")
        with pytest.raises(BarrierConflictError):
            reg.establish("web", operation_id="svc-2", reason="restart")

    def test_establish_same_owner_idempotent(self, tmp_path: Path) -> None:
        reg = AdmissionBarrierRegistry(tmp_path)
        reg.establish("web", operation_id="svc-1", reason="restart")
        again = reg.establish("web", operation_id="svc-1", reason="restart")
        assert again.operation_id == "svc-1"

    def test_release_is_ownership_checked(self, tmp_path: Path) -> None:
        reg = AdmissionBarrierRegistry(tmp_path)
        reg.establish("web", operation_id="svc-1", reason="restart")
        assert reg.release("web", operation_id="svc-2") is False
        assert reg.blocked("web") is not None
        assert reg.release("web", operation_id="svc-1") is True
        assert reg.blocked("web") is None

    def test_corrupt_barrier_blocks_and_needs_override(self, tmp_path: Path) -> None:
        reg = AdmissionBarrierRegistry(tmp_path)
        path = reg.barrier_path("web")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not-json", encoding="utf-8")
        view = reg.blocked("web")
        assert view is not None and view.corrupt
        assert reg.release("web", operation_id="") is False
        assert reg.force_release("web", reason="operator cleanup") is True
        assert reg.blocked("web") is None

    def test_snapshot_lists_all_services(self, tmp_path: Path) -> None:
        reg = AdmissionBarrierRegistry(tmp_path)
        reg.establish("web", operation_id="svc-1", reason="restart")
        reg.establish("feishu", operation_id="svc-1", reason="restart")
        assert [b.service for b in reg.snapshot()] == ["feishu", "web"]


class TestAcceptEstablishesBarriers:
    def test_accept_web_blocks_only_web(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        action = store.accept_restart(target="web", expected_generation=1, requester_session_id="s1")
        reg = AdmissionBarrierRegistry(tmp_path / "data")
        blocked = reg.blocked("web")
        assert blocked is not None and blocked.operation_id == action.action_id
        assert reg.blocked("feishu") is None
        assert reg.blocked("learning") is None

    def test_accept_all_blocks_three_services(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        action = store.accept_restart(target="all", expected_generation=1, requester_session_id="s1")
        reg = AdmissionBarrierRegistry(tmp_path / "data")
        for service in ("web", "feishu", "learning"):
            blocked = reg.blocked(service)
            assert blocked is not None and blocked.operation_id == action.action_id, service

    def test_conflicting_barrier_rejects_acceptance_and_keeps_owner(
        self, tmp_path: Path
    ) -> None:
        store = _store(tmp_path)
        reg = AdmissionBarrierRegistry(tmp_path / "data")
        reg.establish("web", operation_id="svc-owner", reason="restart")
        with pytest.raises(sc.DeploymentGenerationConflictError):
            store.accept_restart(target="web", expected_generation=1, requester_session_id="s1")
        assert reg.blocked("web").operation_id == "svc-owner"
        # the rejected attempt must leave an auditable failed action and no
        # barrier of its own
        actions = sorted((store.actions_dir).glob("*.json"))
        assert len(actions) == 1
        raw = json.loads(actions[0].read_text(encoding="utf-8"))
        assert raw["status"] == "failed"
        assert "barrier" in raw["detail"]
        barrier_files = sorted((tmp_path / "data" / "runtime" / "service-control-barriers").glob("*.json"))
        owners = [json.loads(p.read_text(encoding="utf-8"))["operation_id"] for p in barrier_files]
        assert raw["action_id"] not in owners

    def test_establish_failure_rolls_back_partial_barriers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _store(tmp_path)
        reg = AdmissionBarrierRegistry(tmp_path / "data")
        original = store.barriers.establish

        def flaky(service: str, *, operation_id: str, reason: str = "restart"):
            if service == "feishu":
                raise OSError("disk full")
            return original(service, operation_id=operation_id, reason=reason)

        monkeypatch.setattr(store.barriers, "establish", flaky)
        with pytest.raises(RuntimeError):
            store.accept_restart(target="all", expected_generation=1, requester_session_id="s1")
        # no barrier of the rejected action remains on any service
        for service in ("web", "feishu", "learning"):
            assert reg.blocked(service) is None, service
        actions = sorted(store.actions_dir.glob("*.json"))
        assert len(actions) == 1
        raw = json.loads(actions[0].read_text(encoding="utf-8"))
        assert raw["status"] == "failed"


class TestReleaseLifecycle:
    def test_waiting_terminal_releases_barriers(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        reg = AdmissionBarrierRegistry(tmp_path / "data")
        action = store.accept_restart(target="web", expected_generation=1, requester_session_id="s1")
        store.update_action(action.action_id, status="waiting_for_requester_exit", detail="")
        store.update_action(action.action_id, status="failed", detail="requester exit timeout")
        assert reg.blocked("web") is None

    def test_running_failure_keeps_barriers_fail_closed(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        reg = AdmissionBarrierRegistry(tmp_path / "data")
        action = store.accept_restart(target="web", expected_generation=1, requester_session_id="s1")
        store.update_action(action.action_id, status="waiting_for_idle", detail="")
        store.update_action(action.action_id, status="running", detail="")
        store.update_action(action.action_id, status="failed", detail="physical rc=2")
        blocked = reg.blocked("web")
        assert blocked is not None and blocked.operation_id == action.action_id

    def test_succeeded_releases_barriers(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        reg = AdmissionBarrierRegistry(tmp_path / "data")
        action = store.accept_restart(target="web", expected_generation=1, requester_session_id="s1")
        store.update_action(action.action_id, status="running", detail="")
        store.update_action(action.action_id, status="succeeded", detail="verify=ok")
        assert reg.blocked("web") is None

    def test_stale_reap_releases_then_new_accept_owns_barrier(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        reg = AdmissionBarrierRegistry(tmp_path / "data")
        stale = store.accept_restart(target="web", expected_generation=1, requester_session_id="s1")
        path = store.action_path(stale.action_id)
        raw = json.loads(path.read_text(encoding="utf-8"))
        # make the action look like a stale waiting worker (only waiting
        # states are reap candidates)
        raw["status"] = "waiting_for_requester_exit"
        raw["updated_at"] = "2020-01-01T00:00:00+00:00"
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        fresh = store.accept_restart(target="web", expected_generation=1, requester_session_id="s2")
        assert store.read_action(stale.action_id).status == "failed"
        blocked = reg.blocked("web")
        assert blocked is not None and blocked.operation_id == fresh.action_id

    def test_foreign_release_cannot_clear_owner_barrier(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        reg = AdmissionBarrierRegistry(tmp_path / "data")
        action = store.accept_restart(target="web", expected_generation=1, requester_session_id="s1")
        assert reg.release("web", operation_id="svc-not-mine") is False
        assert reg.blocked("web").operation_id == action.action_id
        store.update_action(action.action_id, status="succeeded", detail="verify=ok")
        assert reg.blocked("web") is None


class TestWorkerPaths:
    def test_worker_binding_failure_releases_barriers(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        reg = AdmissionBarrierRegistry(tmp_path / "data")
        action = store.accept_restart(target="web", expected_generation=1, requester_session_id="s1")
        # publish a newer generation before the worker looks at desired state
        _publish(store, _deployment(tmp_path, generation=2), 1)
        rc = sc.run_action_worker(store, action.action_id)
        assert rc == 3
        assert store.read_action(action.action_id).status == "failed"
        assert reg.blocked("web") is None

    def test_worker_requester_timeout_releases_barriers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _store(tmp_path)
        reg = AdmissionBarrierRegistry(tmp_path / "data")
        action = store.accept_restart(target="web", expected_generation=1, requester_session_id="s1")
        monkeypatch.setattr(sc, "_requester_run_active", lambda *a, **k: True)
        monkeypatch.setattr(sc, "_REQUESTER_EXIT_POLL_S", 0.02)
        monkeypatch.setattr(sc, "_REQUESTER_EXIT_TIMEOUT_S", 0.1)
        rc = sc.run_action_worker(store, action.action_id)
        assert rc == 1
        assert store.read_action(action.action_id).status == "failed"
        assert reg.blocked("web") is None

    def test_worker_idle_timeout_releases_barriers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _store(tmp_path)
        reg = AdmissionBarrierRegistry(tmp_path / "data")
        action = store.accept_restart(target="web", expected_generation=1, requester_session_id="s1")
        monkeypatch.setattr(sc, "_target_busy_reason", lambda *a, **k: "web: learning run active")
        monkeypatch.setattr(sc, "_REQUESTER_EXIT_POLL_S", 0.02)
        monkeypatch.setattr(sc, "_REQUESTER_EXIT_TIMEOUT_S", 0.1)
        monkeypatch.setattr(sc, "_IDLE_POLL_S", 0.02)
        monkeypatch.setattr(sc, "_IDLE_TIMEOUT_S", 0.1)
        rc = sc.run_action_worker(store, action.action_id)
        assert rc == 1
        assert store.read_action(action.action_id).status == "failed"
        assert reg.blocked("web") is None


class TestPhysicalFailKeepsBarriers:
    def test_worker_physical_failure_keeps_barriers_for_operator(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import subprocess as sp

        monkeypatch.setattr(sc, "_REQUESTER_EXIT_POLL_S", 0.02)
        monkeypatch.setattr(sc, "_REQUESTER_EXIT_TIMEOUT_S", 0.5)
        monkeypatch.setattr(sc, "_IDLE_POLL_S", 0.02)
        monkeypatch.setattr(sc, "_IDLE_TIMEOUT_S", 0.5)
        dist = tmp_path / "webui" / "dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text("<html>fixture</html>\n", encoding="utf-8")
        script = tmp_path / "scripts" / "restart_mirror.sh"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("#!/usr/bin/env bash\nexit 3\n", encoding="utf-8")
        script.chmod(0o755)
        sp.run(["git", "init", "-q", str(tmp_path)], check=True)
        sp.run(["git", "-C", str(tmp_path), "add", "-A", "."], check=True)
        sp.run(
            ["git", "-C", str(tmp_path), "-c", "user.name=fixture", "-c", "user.email=fixture@test.invalid", "commit", "-qm", "fixture"],
            check=True,
        )
        store = sc.ManagedServiceDeploymentStore(tmp_path / "data")
        deployment = sc.build_deployment(code_root=str(tmp_path), runtime_root=str(tmp_path), generation=1)
        store.compare_and_swap(deployment, expected_generation=0)
        reg = AdmissionBarrierRegistry(tmp_path / "data")
        action = store.accept_restart(target="web", expected_generation=1, requester_session_id="s1")
        rc = sc.run_action_worker(store, action.action_id)
        assert rc == 3
        blocked = reg.blocked("web")
        assert blocked is not None and blocked.operation_id == action.action_id
        # operator override is the only exit
        assert reg.release("web", operation_id=action.action_id) is True
        assert reg.blocked("web") is None


class TestCliOverrideExit:
    def test_barrier_cli_lists_and_releases(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        reg = AdmissionBarrierRegistry(tmp_path)
        reg.establish("feishu", operation_id="svc-9", reason="restart")
        data_dir = str(tmp_path)
        rc = sc.main(["barriers", "--data-dir", data_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "svc-9" in out and "feishu" in out
        rc = sc.main(
            ["barrier-release", "--data-dir", data_dir, "--service", "feishu", "--operation-id", "svc-wrong", "--reason", "x"]
        )
        assert rc != 0
        assert reg.blocked("feishu") is not None
        rc = sc.main(
            [
                "barrier-release",
                "--data-dir", data_dir,
                "--service", "feishu",
                "--operation-id", "svc-9",
                "--reason", "operator override after manual recovery",
            ]
        )
        assert rc == 0
        assert reg.blocked("feishu") is None


class TestFeishuDefer:
    """§8.2-2 feishu 侧：waiting 窗口内消息延迟保留，不发起 run."""

    def _connector(self, maxsize: int = 4):
        import queue as _queue

        from llm_loop.feishu.bridge import _WsConnector

        conn = object.__new__(_WsConnector)
        conn._msg_queue = _queue.Queue(maxsize=maxsize)
        calls: list[dict] = []

        def _on_message(payload):
            calls.append({"kind": "processed", "payload": payload})

        def _handle_queue_full(payload):
            calls.append({"kind": "queue_full", "payload": payload})

        conn._on_message = _on_message
        conn._handle_queue_full = _handle_queue_full
        conn._retraction_lock = __import__("threading").Lock()
        conn._processing_msg_id = ""
        conn._deferred_recall_facts = {}
        conn._processing_since = None
        conn._processing_timeout_reported = False
        conn._processing_chat_id = ""
        conn._processing_reply_id = ""
        conn._processing_reply_type = ""
        conn._last_processed_ts = None
        return conn, calls

    def test_barrier_defers_message_without_processing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from llm_loop.feishu import bridge as fb

        reg = AdmissionBarrierRegistry(tmp_path / "data")
        reg.establish("feishu", operation_id="svc-f1", reason="restart")
        monkeypatch.chdir(tmp_path)
        # 心跳路径默认 data/feishu_heartbeat.json（cwd 相对）→ 与注册表同 data 根
        conn, calls = self._connector()
        monkeypatch.setattr(fb, "_BARRIER_DEFER_POLL_S", 0.0)
        monkeypatch.setattr(fb, "_BARRIER_DEFER_WAIT_S", 0.05)
        payload = {"event": {"message": {"message_id": "om_1", "message_type": "text"}}}
        conn._safe_handle_message(payload)
        assert calls == []  # 未处理：延迟保留
        assert conn._msg_queue.qsize() == 1
        assert conn._msg_queue.get_nowait() is payload

    def test_barrier_overflow_uses_queue_full_receipt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from llm_loop.feishu import bridge as fb

        reg = AdmissionBarrierRegistry(tmp_path / "data")
        reg.establish("feishu", operation_id="svc-f2", reason="restart")
        monkeypatch.chdir(tmp_path)
        conn, calls = self._connector(maxsize=1)
        conn._msg_queue.put({"event": {"message": {"message_id": "om_backlog"}}})
        monkeypatch.setattr(fb, "_BARRIER_DEFER_POLL_S", 0.0)
        monkeypatch.setattr(fb, "_BARRIER_DEFER_WAIT_S", 0.05)
        conn._safe_handle_message({"event": {"message": {"message_id": "om_2"}}})
        # 有界队列满 → 走既有 QUEUE_FULL 补偿回执路径（不静默丢）
        assert [c["kind"] for c in calls] == ["queue_full"]

    def test_no_barrier_processes_normally(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from llm_loop.feishu import bridge as fb

        monkeypatch.chdir(tmp_path)
        conn, calls = self._connector()
        monkeypatch.setattr(fb, "_BARRIER_DEFER_POLL_S", 0.0)
        payload = {"event": {"message": {"message_id": "om_3", "message_type": "text"}}}
        conn._safe_handle_message(payload)
        assert [c["kind"] for c in calls] == ["processed"]


# ---------------------------------------------------------------------------
# R1 (SPEC-20260922-service-control-restart-fixpack-v1): rc!=0 时 worker 消费
# restart_mirror 落盘回执。矩阵：4 个预检链标记 → release（零物理副作用）；
# mid-run 标记 / 无回执 / 解析失败 / scope、rc 不匹配 / 陈旧回执 → keep。
# 脚本 fixture 经 $LFL_RESTART_RUNTIME_ROOT/$LFL_RESTART_RECEIPT_REL 写回执，
# 端到端覆盖 §6 单源路径契约注入。
# ---------------------------------------------------------------------------
_R1_PRECHECK_MARKERS = (
    "webui_artifact_preflight_failed",
    "service_control_binding_failed",
    "active_run_precheck_failed",
    "knowledge_preflight_failed",
)


class TestR1ReceiptConsumption:
    def _fixture(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script_body: str, *, target: str = "web"):
        import subprocess as sp

        monkeypatch.setattr(sc, "_REQUESTER_EXIT_POLL_S", 0.02)
        monkeypatch.setattr(sc, "_REQUESTER_EXIT_TIMEOUT_S", 0.5)
        monkeypatch.setattr(sc, "_IDLE_POLL_S", 0.02)
        monkeypatch.setattr(sc, "_IDLE_TIMEOUT_S", 0.5)
        dist = tmp_path / "webui" / "dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text("<html>fixture</html>\n", encoding="utf-8")
        script = tmp_path / "scripts" / "restart_mirror.sh"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(script_body, encoding="utf-8")
        script.chmod(0o755)
        sp.run(["git", "init", "-q", str(tmp_path)], check=True)
        sp.run(["git", "-C", str(tmp_path), "add", "-A", "."], check=True)
        sp.run(
            ["git", "-C", str(tmp_path), "-c", "user.name=fixture", "-c", "user.email=fixture@test.invalid", "commit", "-qm", "fixture"],
            check=True,
        )
        store = sc.ManagedServiceDeploymentStore(tmp_path / "data")
        deployment = sc.build_deployment(code_root=str(tmp_path), runtime_root=str(tmp_path), generation=1)
        store.compare_and_swap(deployment, expected_generation=0)
        reg = AdmissionBarrierRegistry(tmp_path / "data")
        action = store.accept_restart(target=target, expected_generation=1, requester_session_id="s1")
        return store, reg, action

    def _script(
        self,
        *,
        action: str = "web",
        rc: int = 1,
        detail: str = "",
        stale_ts: str | None = None,
        write_receipt: bool = True,
        raw_receipt: str | None = None,
        exit_code: int | None = None,
    ) -> str:
        import shlex

        if raw_receipt is not None:
            payload_line = f"printf '%s\\n' {shlex.quote(raw_receipt)} > \"$LFL_RESTART_RUNTIME_ROOT/$LFL_RESTART_RECEIPT_REL\"\n"
        elif write_receipt:
            fixed = json.dumps(
                {"action": action, "rc": rc, "detail": detail, "git_head": "fixture"},
                ensure_ascii=False,
            )
            # ts 于脚本运行时生成（与真实 _write_receipt 同为秒分辨率本地时区），
            # 保证 ≥ worker 的 restarted_at；格式串只含一个 %s，参数在 bash 侧
            # 拼接——printf 会复用格式串，多参数会产生第二行非法 JSON。
            if stale_ts:
                line = fixed[:-1] + f',"ts":"{stale_ts}"}}'
                payload_line = f"printf '%s\\n' {shlex.quote(line)} > \"$LFL_RESTART_RUNTIME_ROOT/$LFL_RESTART_RECEIPT_REL\"\n"
            else:
                prefix = fixed[:-1] + ',"ts":"'
                payload_line = (
                    'ts="$(date +%Y-%m-%dT%H:%M:%S%z)"\n'
                    f"printf '%s\\n' {shlex.quote(prefix)}\"$ts\"'\"}}' > \"$LFL_RESTART_RUNTIME_ROOT/$LFL_RESTART_RECEIPT_REL\"\n"
                )
        else:
            payload_line = ""
        return (
            "#!/usr/bin/env bash\n"
            'mkdir -p "$LFL_RESTART_RUNTIME_ROOT/data"\n'
            f"{payload_line}"
            f"exit {exit_code if exit_code is not None else rc}\n"
        )

    @pytest.mark.parametrize("marker", _R1_PRECHECK_MARKERS)
    def test_precheck_marker_releases_barriers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, marker: str
    ) -> None:
        store, reg, action = self._fixture(
            tmp_path, monkeypatch, self._script(action="web", rc=1, detail=marker)
        )
        rc = sc.run_action_worker(store, action.action_id)
        assert rc == 1
        final = store.read_action(action.action_id)
        assert final.status == "failed"
        assert f"receipt={marker}" in final.detail
        assert reg.blocked("web") is None  # 预检失败零副作用 → 自动释放

    def test_precheck_marker_all_target_releases_three_services(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, reg, action = self._fixture(
            tmp_path,
            monkeypatch,
            self._script(action="all", rc=1, detail="active_run_precheck_failed"),
            target="all",
        )
        rc = sc.run_action_worker(store, action.action_id)
        assert rc == 1
        for service in ("web", "feishu", "learning"):
            assert reg.blocked(service) is None, service

    def test_midrun_marker_keeps_barriers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, reg, action = self._fixture(
            tmp_path,
            monkeypatch,
            self._script(action="web", rc=1, detail="port=8317 web_stopped=true"),
        )
        rc = sc.run_action_worker(store, action.action_id)
        assert rc == 1
        final = store.read_action(action.action_id)
        assert final.status == "failed"
        assert "marker=" in final.detail  # 非 OK-reason 标记 → keep
        blocked = reg.blocked("web")
        assert blocked is not None and blocked.operation_id == action.action_id

    def test_absent_receipt_keeps_barriers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, reg, action = self._fixture(
            tmp_path, monkeypatch, self._script(rc=1, write_receipt=False)
        )
        rc = sc.run_action_worker(store, action.action_id)
        assert rc == 1
        final = store.read_action(action.action_id)
        assert "receipt=absent" in final.detail
        assert reg.blocked("web") is not None

    def test_unparseable_receipt_keeps_barriers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, reg, action = self._fixture(
            tmp_path, monkeypatch, self._script(rc=1, raw_receipt='{"oops')
        )
        rc = sc.run_action_worker(store, action.action_id)
        assert rc == 1
        final = store.read_action(action.action_id)
        assert "receipt=unparseable" in final.detail
        assert reg.blocked("web") is not None

    def test_scope_mismatch_keeps_barriers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, reg, action = self._fixture(
            tmp_path,
            monkeypatch,
            self._script(action="feishu", rc=1, detail="knowledge_preflight_failed"),
        )
        rc = sc.run_action_worker(store, action.action_id)  # target=web
        assert rc == 1
        final = store.read_action(action.action_id)
        assert "scope=" in final.detail
        assert reg.blocked("web") is not None

    def test_rc_mismatch_keeps_barriers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, reg, action = self._fixture(
            tmp_path,
            monkeypatch,
            self._script(
                action="web", rc=0, detail="knowledge_preflight_failed", exit_code=1
            ),
        )
        rc = sc.run_action_worker(store, action.action_id)  # 回执 rc=0，脚本 exit 1
        assert rc == 1
        final = store.read_action(action.action_id)
        assert "rc=0!=1" in final.detail
        assert reg.blocked("web") is not None

    def test_stale_receipt_keeps_barriers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, reg, action = self._fixture(
            tmp_path,
            monkeypatch,
            self._script(
                action="web",
                rc=1,
                detail="knowledge_preflight_failed",
                stale_ts="2020-01-01T00:00:00+08:00",
            ),
        )
        rc = sc.run_action_worker(store, action.action_id)
        assert rc == 1
        final = store.read_action(action.action_id)
        assert "receipt=stale" in final.detail
        assert reg.blocked("web") is not None

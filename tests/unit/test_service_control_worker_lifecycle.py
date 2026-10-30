"""GOAL-20261008-f143e051 · service-control worker 生命周期加固测试。

覆盖：
- CLI restart/update 默认 detach worker（spawn_service_control_worker），
  --wait 显式内联并打印 worst-case 提示（防 caller 超时误杀孤儿化）。
- ServiceControlAction.worker_pid 字段向后兼容（旧 JSON 无键 → 0）。
- record_worker_pid 幂等（不重复 bump updated_at）。
- _reap_stale_waiting_actions_unlocked：死 pid 快路径（宽限外秒级回收）、
  存活 pid 不回收、无 pid 旧 action 回退 2100s 时间窗。
- run_action_worker 入口盖章 pid（fail-fast 前即写）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import llm_loop.runtime.service_control as sc
from llm_loop.runtime.service_control import ManagedServiceDeploymentStore


def _write_waiting_action(
    store: ManagedServiceDeploymentStore,
    action_id: str,
    *,
    age_s: float,
    worker_pid: int | None,
    status: str = "waiting_for_idle",
) -> None:
    store.actions_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    ts = (now - timedelta(seconds=age_s)).isoformat()
    raw: dict[str, object] = {
        "schema": sc._ACTION_SCHEMA,
        "action_id": action_id,
        "action": "restart",
        "target": "web",
        "deployment_id": "dep-test",
        "deployment_generation": 1,
        "requester_session_id": "sess-test",
        "status": status,
        "created_at": ts,
        "updated_at": ts,
        "detail": "",
    }
    if worker_pid is not None:
        raw["worker_pid"] = worker_pid
    (store.actions_dir / f"{action_id}.json").write_text(
        json.dumps(raw), encoding="utf-8"
    )


def _reap(store: ManagedServiceDeploymentStore) -> None:
    with store.lease():
        store._reap_stale_waiting_actions_unlocked()


class TestCliDispatch:
    """CLI restart/update 默认 detach；--wait 才内联。"""

    @pytest.fixture()
    def fake_store_cls(self, monkeypatch: pytest.MonkeyPatch):
        calls = {"spawn": [], "inline": 0}
        action = SimpleNamespace(
            action_id="act-x",
            status="waiting_for_idle",
            detail="d",
            reason_ref="",
            next_step="",
        )

        class FakeStore:
            def __init__(self, root: str) -> None:
                pass

            def read(self):
                return SimpleNamespace(generation=196, git_head="x" * 40)

            compare_and_swap = lambda self, dep, expected_generation: True  # noqa: E731

            def accept_restart(self, **kwargs):
                return action

            def read_action(self, action_id: str):
                return action

            def lease(self):
                class _L:
                    __enter__ = lambda self: None  # noqa: E731
                    __exit__ = lambda self, *a: False  # noqa: E731

                return _L()

            record_worker_pid = lambda self, aid, pid: None  # noqa: E731

        def fake_spawn(store, action_id: str) -> None:
            calls["spawn"].append(action_id)

        def fake_inline(store, action_id: str) -> int:
            calls["inline"] += 1
            return 0

        monkeypatch.setattr(sc, "ManagedServiceDeploymentStore", FakeStore)
        monkeypatch.setattr(sc, "spawn_service_control_worker", fake_spawn)
        monkeypatch.setattr(sc, "run_action_worker", fake_inline)
        monkeypatch.setattr(sc, "compose_convergence_view", lambda store: {})
        return calls

    def test_restart_detaches_by_default(
        self, tmp_path: Path, fake_store_cls, capsys: pytest.CaptureFixture
    ) -> None:
        rc = sc.main(["restart", "--data-dir", str(tmp_path), "--target", "web"])
        assert rc == 0
        assert fake_store_cls["spawn"] == ["act-x"]
        assert fake_store_cls["inline"] == 0
        receipt = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert receipt["detached"] is True
        assert receipt["ok"] is True
        assert "hint" in receipt

    def test_restart_wait_runs_inline_with_warning(
        self, tmp_path: Path, fake_store_cls, capsys: pytest.CaptureFixture
    ) -> None:
        rc = sc.main(
            ["restart", "--data-dir", str(tmp_path), "--target", "web", "--wait"]
        )
        assert rc == 0
        assert fake_store_cls["inline"] == 1
        assert fake_store_cls["spawn"] == []
        err = capsys.readouterr().err
        assert "--wait" in err and "worst-case" in err

    def test_update_detaches_by_default(
        self, tmp_path: Path, fake_store_cls, capsys: pytest.CaptureFixture
    ) -> None:
        # update 路径在 accept 前对 code-root 做 git rev-parse；给一个最小仓库。
        import subprocess

        code_root = tmp_path / "repo"
        code_root.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=code_root, check=True)
        (code_root / "README").write_text("x", encoding="utf-8")
        subprocess.run(
            ["git", "add", "."], cwd=code_root, check=True,
        )
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
            cwd=code_root,
            check=True,
        )
        # update 在 accept 前校验 webui/dist 产物存在（svc_deploy I5）。
        dist = code_root / "webui" / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")
        rc = sc.main(
            [
                "update",
                "--code-root",
                str(code_root),
                "--runtime-root",
                str(tmp_path),
                "--data-dir",
                str(tmp_path),
                # T2（2026-10-27）：basename "repo" 推不出服务名 token，缺省
                # --target 是 NEEDS_TARGET 拒绝（不隐式兜底 all）；本用例锚定
                # 显式 --target 下的默认 detach 语义，故必须显式传 web。
                "--target",
                "web",
            ]
        )
        assert rc == 0
        assert fake_store_cls["spawn"] == ["act-x"]
        assert fake_store_cls["inline"] == 0
        receipt = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert receipt["detached"] is True

    def test_update_without_target_rejects_needs_target_zero_side_effect(
        self, tmp_path: Path, fake_store_cls, capsys: pytest.CaptureFixture
    ) -> None:
        """T2（2026-10-27）契约锚定：basename 推不出服务名且未传 --target →
        NEEDS_TARGET 拒绝（rc=2，stderr 末行 JSON），先于任何 publish/CAS
        写入（fake store 零 spawn/inline）。不恢复隐式 all 兜底。"""
        import subprocess

        code_root = tmp_path / "repo"
        code_root.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=code_root, check=True)
        (code_root / "README").write_text("x", encoding="utf-8")
        subprocess.run(
            ["git", "add", "."], cwd=code_root, check=True,
        )
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
            cwd=code_root,
            check=True,
        )
        dist = code_root / "webui" / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")

        rc = sc.main(
            [
                "update",
                "--code-root",
                str(code_root),
                "--runtime-root",
                str(tmp_path),
                "--data-dir",
                str(tmp_path),
            ]
        )

        assert rc == 2
        payload = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
        assert payload["error"] == "NEEDS_TARGET"
        assert payload["basename"] == "repo"
        assert payload["targets"] == ["web", "feishu", "wecom", "learning", "all"]
        assert "--target" in payload["example"]
        assert "未产生任何 publish/CAS 写入" in payload["detail"]
        # 零副作用：拒绝发生在 build_deployment/CAS 之前，worker 未 spawn 也未内联。
        assert fake_store_cls["spawn"] == []
        assert fake_store_cls["inline"] == 0


class TestWorkerPidField:
    def test_backcompat_missing_key_is_zero(self) -> None:
        raw = {
            "schema": sc._ACTION_SCHEMA,
            "action_id": "a",
            "action": "restart",
            "target": "web",
            "deployment_id": "d",
            "deployment_generation": 1,
            "requester_session_id": "s",
            "status": "accepted",
            "created_at": "2026-10-08T00:00:00",
            "updated_at": "2026-10-08T00:00:00",
            "detail": "",
        }
        action = sc.ServiceControlAction.from_dict(raw)
        assert action.worker_pid == 0
        assert action.to_dict()["worker_pid"] == 0

    def test_record_worker_pid_idempotent(self, tmp_path: Path) -> None:
        store = ManagedServiceDeploymentStore(tmp_path)
        store.actions_dir.mkdir(parents=True, exist_ok=True)
        _write_waiting_action(store, "act-a", age_s=0, worker_pid=0)
        store.record_worker_pid("act-a", 4242)
        stamped = store.read_action("act-a")
        assert stamped is not None
        assert stamped.worker_pid == 4242
        store.record_worker_pid("act-a", 4242)
        reread = store.read_action("act-a")
        assert reread is not None
        assert reread.updated_at == stamped.updated_at


class TestReaperLiveness:
    def test_dead_pid_reaped_fast(self, tmp_path: Path) -> None:
        store = ManagedServiceDeploymentStore(tmp_path)
        _write_waiting_action(
            store, "act-dead", age_s=120, worker_pid=999_999_999
        )
        _reap(store)
        action = store.read_action("act-dead")
        assert action is not None and action.status == "failed"
        assert "999999999" in action.detail

    def test_live_pid_not_reaped(self, tmp_path: Path) -> None:
        store = ManagedServiceDeploymentStore(tmp_path)
        _write_waiting_action(store, "act-live", age_s=120, worker_pid=os.getpid())
        _reap(store)
        action = store.read_action("act-live")
        assert action is not None and action.status == "waiting_for_idle"

    def test_dead_pid_within_grace_not_reaped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sc, "_STALE_PID_GRACE_S", 600.0)
        store = ManagedServiceDeploymentStore(tmp_path)
        _write_waiting_action(
            store, "act-fresh", age_s=120, worker_pid=999_999_999
        )
        _reap(store)
        action = store.read_action("act-fresh")
        assert action is not None and action.status == "waiting_for_idle"

    def test_no_pid_falls_back_to_legacy_window(self, tmp_path: Path) -> None:
        store = ManagedServiceDeploymentStore(tmp_path)
        _write_waiting_action(store, "act-recent", age_s=120, worker_pid=None)
        _write_waiting_action(store, "act-ancient", age_s=2200, worker_pid=None)
        _reap(store)
        recent = store.read_action("act-recent")
        ancient = store.read_action("act-ancient")
        assert recent is not None and recent.status == "waiting_for_idle"
        assert ancient is not None and ancient.status == "failed"
        assert "presumed dead" in ancient.detail


class TestReaperAcceptedCoverage:
    """accepted 覆盖（2026-10-14 终审必补项）。

    worker 在盖章 pid 前死亡（spawn→入口的 kill-9/OOM 窗口）卡 accepted，
    此前 reaper 谓词不含 accepted：死 pid 快路径与 2100s 兜底双双跳过，
    屏障永久占坑。误杀面由等待循环入口守卫兜住（终态即零续写退出）。
    """

    def test_fails_accepted_with_dead_worker_pid(self, tmp_path: Path) -> None:
        store = ManagedServiceDeploymentStore(tmp_path)
        _write_waiting_action(
            store, "act-acc-dead", age_s=60, worker_pid=999_999_999, status="accepted"
        )
        _reap(store)
        action = store.read_action("act-acc-dead")
        assert action is not None and action.status == "failed"
        assert "999999999" in action.detail

    def test_fails_accepted_never_stamped_pid_after_grace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sc, "_STALE_ACCEPTED_NO_PID_GRACE_S", 60.0)
        store = ManagedServiceDeploymentStore(tmp_path)
        _write_waiting_action(
            store, "act-acc-orphan", age_s=120, worker_pid=0, status="accepted"
        )
        _write_waiting_action(
            store, "act-acc-fresh", age_s=30, worker_pid=0, status="accepted"
        )
        _reap(store)
        orphan = store.read_action("act-acc-orphan")
        fresh = store.read_action("act-acc-fresh")
        assert orphan is not None and orphan.status == "failed"
        assert "never stamped pid" in orphan.detail
        assert fresh is not None and fresh.status == "accepted"

    def test_accepted_live_pid_not_reaped(self, tmp_path: Path) -> None:
        store = ManagedServiceDeploymentStore(tmp_path)
        _write_waiting_action(
            store, "act-acc-live", age_s=120, worker_pid=os.getpid(), status="accepted"
        )
        _reap(store)
        action = store.read_action("act-acc-live")
        assert action is not None and action.status == "accepted"


class TestWorkerStampsPid:
    def test_run_action_worker_stamps_before_fail_fast(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = ManagedServiceDeploymentStore(tmp_path)
        store.actions_dir.mkdir(parents=True, exist_ok=True)
        _write_waiting_action(store, "act-stamp", age_s=0, worker_pid=0)
        # deployment 缺失 → run_action_worker 在 fail-fast 前应已盖章 pid。
        assert store.read() is None
        rc = sc.run_action_worker(store, "act-stamp")
        assert rc == 2
        action = store.read_action("act-stamp")
        assert action is not None
        assert action.worker_pid == os.getpid()

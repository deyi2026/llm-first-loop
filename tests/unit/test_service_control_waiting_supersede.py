"""B（等待循环主动 stale 检测）前置测试——2026-10-14 终审组合。

已核前提：
- `_wait_for` 等待阶段零物理副作用；desired 绑定此前只在 Phase3 lease
  内复检，屏障最长占 ~1800s 才走到复检。
- B 把废弃时机提前到等待循环内：desired 前进/记录缺失 → superseded
  （标准 update_action 路径，§8.3 屏障随终态释放）；读异常不判死。
- 硬约束：所有写入前 fresh 重读；外部已关闭（终态/缺失）→ 零续写退出，
  不得复活已释放屏障的终态（supersede 后 return，本 worker 零续写）。
"""

from __future__ import annotations

from pathlib import Path

import llm_loop.runtime.service_control as sc


def _deployment(tmp_path: Path, generation: int = 1) -> sc.ManagedServiceDeployment:
    return sc.ManagedServiceDeployment(
        schema=sc._DEPLOYMENT_SCHEMA,
        deployment_id=f"dep-{generation}",
        generation=generation,
        git_head="a" * 40,
        code_root=str(tmp_path),
        runtime_root=str(tmp_path),
        webui_artifact_sha256="b" * 64,
    )


def _store(tmp_path: Path) -> sc.ManagedServiceDeploymentStore:
    store = sc.ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(_deployment(tmp_path), expected_generation=0)
    return store


def _accepted_action(store: sc.ManagedServiceDeploymentStore) -> sc.ServiceControlAction:
    return store.accept_restart(
        target="web", expected_generation=1, requester_session_id="sess-b"
    )


def _wait_idle(
    store: sc.ManagedServiceDeploymentStore,
    action: sc.ServiceControlAction,
    *,
    busy_probe,
    timeout_s: float = 5.0,
) -> bool:
    return sc._wait_for(
        store,
        action,
        status="waiting_for_idle",
        busy_probe=busy_probe,
        poll_s=0.02,
        timeout_s=timeout_s,
        timeout_detail="target still busy",
        gate="waiting_for_idle",
    )


class TestWaitForStaleSupersede:
    def test_supersedes_when_desired_generation_advances(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        action = _accepted_action(store)
        if store.barriers.blocked("web") is None:
            store.barriers.establish(
                "web", operation_id=action.action_id, reason="restart"
            )
        assert store.barriers.blocked("web") is not None

        calls = {"n": 0}

        def busy_probe():
            calls["n"] += 1
            if calls["n"] == 1:
                # 首轮探针期间 desired 前进（等待中有人 publish 新代）
                store.compare_and_swap(
                    _deployment(tmp_path, generation=2), expected_generation=1
                )
            return True

        assert _wait_idle(store, action, busy_probe=busy_probe) is False
        final = store.read_action(action.action_id)
        assert final is not None
        assert final.status == "failed"
        assert "superseded while waiting" in final.detail
        assert "current_generation=2" in final.detail
        # supersede 在下一轮探针前触发（快速退出的可核验证据）
        assert calls["n"] == 1
        # §8.3：等待零副作用，屏障随终态释放
        assert store.barriers.blocked("web") is None

    def test_supersedes_when_deployment_record_missing(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        action = _accepted_action(store)
        Path(store.path).unlink()
        assert _wait_idle(store, action, busy_probe=lambda: True) is False
        final = store.read_action(action.action_id)
        assert final is not None and final.status == "failed"
        assert "desired deployment record missing" in final.detail

    def test_keeps_waiting_when_deployment_read_fails(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        action = _accepted_action(store)
        # desired 记录损坏：读异常≠缺失，不得据此判死
        Path(store.path).write_text("{corrupt", encoding="utf-8")
        probes = iter([True, False])
        assert _wait_idle(store, action, busy_probe=lambda: next(probes)) is True
        final = store.read_action(action.action_id)
        assert final is not None and final.status == "waiting_for_idle"
        assert "superseded" not in (final.detail or "")

    def test_exits_without_resurrecting_when_closed_externally(
        self, tmp_path: Path
    ) -> None:
        store = _store(tmp_path)
        action = _accepted_action(store)
        store.update_action(
            action.action_id,
            status="failed",
            detail="stale waiting state reaped: worker pid 1 dead",
        )
        pre = store.read_action(action.action_id)
        assert pre is not None and pre.status == "failed"
        assert _wait_idle(store, action, busy_probe=lambda: True) is False
        final = store.read_action(action.action_id)
        assert final is not None
        assert final.status == "failed"
        # 零续写：终态记录（含 detail/updated_at）不被旧对象复活或改写
        assert final.detail == pre.detail
        assert final.updated_at == pre.updated_at

    def test_exits_without_recreating_missing_action_record(
        self, tmp_path: Path
    ) -> None:
        store = _store(tmp_path)
        action = _accepted_action(store)
        action_path = store.actions_dir / f"{action.action_id}.json"
        action_path.unlink()
        assert _wait_idle(store, action, busy_probe=lambda: True) is False
        assert not action_path.exists()

    def test_normal_advance_regression(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        action = _accepted_action(store)
        probes = iter([True, False])
        assert _wait_idle(store, action, busy_probe=lambda: next(probes)) is True
        final = store.read_action(action.action_id)
        assert final is not None and final.status == "waiting_for_idle"


class TestSupersedeHelper:
    def test_supersede_skips_terminal_action(self, tmp_path: Path) -> None:
        """已终态（如 reaper 先行关闭）不写——废弃与回收幂等收敛。"""
        store = _store(tmp_path)
        action = _accepted_action(store)
        store.update_action(action.action_id, status="failed", detail="reaped first")
        pre = store.read_action(action.action_id)
        sc._supersede_waiting_action(store, action.action_id, "desired advanced")
        final = store.read_action(action.action_id)
        assert final is not None and final.status == "failed"
        assert final.detail == pre.detail

"""TASK-005: desired/live/stable service identity view (read-only observation)."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from llm_loop.runtime.service_control import (
    ManagedServiceDeployment,
    ManagedServiceDeploymentStore,
    ServiceControlAction,
    compose_service_identity_view,
    run_action_worker,
)
from llm_loop.tools.builtin.service_control import ServiceControlTool
from llm_loop.web.routes import router as web_router

HEAD_A = "a" * 40
HEAD_B = "b" * 40
SHA = "c" * 64


def _deployment(tmp_path: Path, generation: int, git_head: str) -> ManagedServiceDeployment:
    return ManagedServiceDeployment(
        schema="managed-service-deployment/v1",
        deployment_id=f"deploy-{generation}",
        generation=generation,
        git_head=git_head,
        code_root=str(tmp_path / "code"),
        runtime_root=str(tmp_path / "runtime-root"),
        webui_artifact_sha256=SHA,
    )


def _publish(store: ManagedServiceDeploymentStore, deployment: ManagedServiceDeployment) -> None:
    store.compare_and_swap(deployment, expected_generation=deployment.generation - 1)


def _write_manifest(
    store: ManagedServiceDeploymentStore, service: str, *, pid: int, git_head: str
) -> None:
    store.runtime_dir.mkdir(parents=True, exist_ok=True)
    (store.runtime_dir / f"runtime_manifest.{service}.json").write_text(
        json.dumps(
            {
                "service": service,
                "pid": pid,
                "started_at": "2026-09-18T00:00:00+00:00",
                "git_head": git_head,
            }
        ),
        encoding="utf-8",
    )


def _write_receipt(
    store: ManagedServiceDeploymentStore,
    *,
    action_id: str,
    target: str,
    generation: int,
    updated_at: str,
) -> None:
    action = ServiceControlAction(
        schema="service-control-action/v1",
        action_id=action_id,
        action="restart",
        target=target,  # type: ignore[arg-type]
        deployment_id=f"deploy-{generation}",
        deployment_generation=generation,
        requester_session_id="sess-x",
        status="succeeded",
        created_at=updated_at,
        updated_at=updated_at,
        detail="restart_mirror rc=0",
    )
    store._write_action_unlocked(action)


def _green_store(tmp_path: Path) -> ManagedServiceDeploymentStore:
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    _publish(store, _deployment(tmp_path, 1, HEAD_A))
    for service in ("web", "feishu", "learning"):
        _write_manifest(store, service, pid=os.getpid(), git_head=HEAD_A)
    return store


def test_identity_view_green_when_live_matches_desired(tmp_path: Path) -> None:
    store = _green_store(tmp_path)
    _write_receipt(
        store, action_id="svc-all-1", target="all", generation=1,
        updated_at="2026-09-18T10:00:00+00:00",
    )
    view = compose_service_identity_view(store)
    assert view["deployment"]["generation"] == 1
    assert set(view["services"]) == {"web", "feishu", "learning"}
    for entry in view["services"].values():
        assert entry["restart_required"] is False
        assert entry["reasons"] == []
        assert entry["live"]["git_head"] == HEAD_A
        assert entry["live"]["pid_alive"] is True
        stable = entry["stable"]
        assert stable["target"] == "all"
        assert stable["generation"] == 1
        assert stable["matches_desired_generation"] is True
        assert stable["git_head"] == HEAD_A


def test_live_generation_match_marked_inferred_with_evidence(tmp_path: Path) -> None:
    """L8: live 代次匹配是 git_head 相等性推断，须标注 inferred 并列原始证据."""
    store = _green_store(tmp_path)
    view = compose_service_identity_view(store)
    web = view["services"]["web"]
    live = web["live"]
    assert live["matches_desired_generation"] is True
    assert live["matches_desired_generation_inferred"] is True
    evidence = live["matches_desired_generation_evidence"]
    assert evidence["pid_alive"] is True
    assert evidence["git_head"] == HEAD_A
    assert evidence["desired_git_head"] == HEAD_A
    # 只暴露文件名，不落绝对私有路径（spec 4.3-3）
    assert evidence["manifest"] == "runtime_manifest.web.json"
    assert evidence["manifest_present"] is True


def test_identity_view_flags_drift_and_missing_manifest(tmp_path: Path) -> None:
    store = _green_store(tmp_path)
    # web: live code advanced beyond desired
    _write_manifest(store, "web", pid=os.getpid(), git_head=HEAD_B)
    # feishu: manifest pid no longer alive
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    _write_manifest(store, "feishu", pid=dead.pid, git_head=HEAD_A)
    # learning: no manifest at all
    (store.runtime_dir / "runtime_manifest.learning.json").unlink()
    view = compose_service_identity_view(store)
    web = view["services"]["web"]
    assert web["restart_required"] is True
    assert any(r.startswith("live_git_head_mismatch") for r in web["reasons"])
    feishu = view["services"]["feishu"]
    assert "live_pid_not_running" in feishu["reasons"]
    learning = view["services"]["learning"]
    assert "live_manifest_missing" in learning["reasons"]


def test_stale_stable_receipt_keeps_generation_only(tmp_path: Path) -> None:
    store = _green_store(tmp_path)
    _write_receipt(
        store, action_id="svc-web-old", target="web", generation=1,
        updated_at="2026-09-18T10:00:00+00:00",
    )
    _publish(store, _deployment(tmp_path, 2, HEAD_B))
    view = compose_service_identity_view(store)
    stable = view["services"]["web"]["stable"]
    assert stable["generation"] == 1
    assert stable["matches_desired_generation"] is False
    assert stable["git_head"] is None
    assert view["services"]["web"]["restart_required"] is True


def test_service_specific_receipt_beats_all_receipt(tmp_path: Path) -> None:
    store = _green_store(tmp_path)
    _write_receipt(
        store, action_id="svc-all-old", target="all", generation=1,
        updated_at="2026-09-18T09:00:00+00:00",
    )
    _write_receipt(
        store, action_id="svc-web-new", target="web", generation=1,
        updated_at="2026-09-18T11:00:00+00:00",
    )
    view = compose_service_identity_view(store)
    assert view["services"]["web"]["stable"]["action_id"] == "svc-web-new"
    assert view["services"]["feishu"]["stable"]["action_id"] == "svc-all-old"


def test_tool_status_exposes_identity_view(tmp_path: Path) -> None:
    store = _green_store(tmp_path)
    tool = ServiceControlTool(
        store=store,
        worker_spawner=lambda _action_id: None,
        session_id_getter=lambda: "s",
    )
    result = tool.execute(action="status")
    assert result.status.name == "SUCCESS"
    body = json.loads(result.content)
    assert set(body["services"]) == {"web", "feishu", "learning"}
    assert body["deployment"]["git_head"] == HEAD_A


def test_worker_success_detail_records_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _green_store(tmp_path)
    action = store.accept_restart(
        target="learning", expected_generation=1, requester_session_id="s"
    )

    class _Proc:
        returncode = 0

    monkeypatch.setattr(
        "llm_loop.runtime.service_control.subprocess.run", lambda *a, **k: _Proc()
    )
    # Merged P0-A.1: run_action_worker now re-verifies the desired binding
    # inside the lifecycle lease (drift => fail closed, needs real git/dist).
    # That gate has its own coverage in test_managed_service_control_p0a.py;
    # stub it here so this test isolates success-detail identity recording.
    monkeypatch.setattr(
        "llm_loop.runtime.service_control.verify_deployment_binding",
        lambda *_a, **_k: [],
    )
    # EVO-20260920-213965a1 案1: Phase-4 post-restart self-verify has its own
    # coverage in test_service_control_two_phase_restart.py; stub it here so
    # this test still isolates success-detail identity recording.
    # lifecycle_agency L6/L7: 三态纯证据签名 (verdict, summary, healthy)。
    monkeypatch.setattr(
        "llm_loop.runtime.service_control._verify_restart_targets",
        lambda *_a, **_k: ("confirmed_ok", "verify=confirmed_ok(stub)", ()),
    )
    assert run_action_worker(store, action.action_id) == 0
    receipt = store.read_action(action.action_id)
    assert receipt is not None and receipt.status == "succeeded"
    assert receipt.detail.startswith("restart_mirror rc=0")
    assert "generation=1" in receipt.detail
    assert HEAD_A in receipt.detail


def test_services_status_route(tmp_path: Path) -> None:
    store = _green_store(tmp_path)
    app = FastAPI()
    app.include_router(web_router)
    app.state.engine = SimpleNamespace(
        settings=SimpleNamespace(data_dir=str(store.data_dir))
    )
    client = TestClient(app)
    resp = client.get("/api/v1/services/status")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["services"]) == {"web", "feishu", "learning"}
    assert body["services"]["web"]["restart_required"] is False


def test_live_newer_than_receipt_marks_stale_not_required(tmp_path: Path) -> None:
    """R6: 直连重启后 live 已达期望代、stable 回执落后 → stale 标记而非谎报."""
    store = _green_store(tmp_path)
    # 受控回执停在 gen1（HEAD_A 时代）
    _write_receipt(
        store, action_id="svc-old-1", target="all", generation=1,
        updated_at="2026-09-22T07:00:00+00:00",
    )
    # desired 推进 gen2(HEAD_B)，live 由直连重启拉到 HEAD_B（无回执）
    _publish(store, _deployment(tmp_path, 2, HEAD_B))
    _write_manifest(store, "web", pid=os.getpid(), git_head=HEAD_B)
    view = compose_service_identity_view(store)
    web = view["services"]["web"]
    # live 是真相源：健康且已达期望代 → 不需要重启
    assert web["restart_required"] is False
    assert web["live"]["matches_desired_generation"] is True
    # stable 落后被显式标记，且只作完整性事实（不进 reasons）
    assert web["stable"]["stale"] is True
    assert web["stable"]["lag_generations"] == 1
    assert "以 live 为准" in web["stable"]["note"]
    assert not any("receipt" in r for r in web["reasons"])


def test_receipt_lag_without_live_match_is_not_stale(tmp_path: Path) -> None:
    """R6 边界: live 未达期望代时回执落后只是普通 lag，不算 stale（部署确实没到）."""
    store = _green_store(tmp_path)
    _write_receipt(
        store, action_id="svc-old-2", target="all", generation=1,
        updated_at="2026-09-22T07:00:00+00:00",
    )
    _publish(store, _deployment(tmp_path, 2, HEAD_B))
    # web live 还在旧代 HEAD_A → git_head mismatch（真信号）
    _write_manifest(store, "web", pid=os.getpid(), git_head=HEAD_A)
    view = compose_service_identity_view(store)
    web = view["services"]["web"]
    assert web["restart_required"] is True
    assert any(r.startswith("live_git_head_mismatch") for r in web["reasons"])
    assert web["stable"].get("stale") is not True
    assert web["stable"]["lag_generations"] == 1


def test_terminal_action_barrier_flagged_in_identity_view(tmp_path: Path) -> None:
    """R3②: 终态 action 仍持屏障 → 孤儿屏障硬信号（需操作员介入）."""
    store = _green_store(tmp_path)
    reg = store.barriers
    reg.establish("web", operation_id="svc-orphan-1", reason="restart")
    orphan = ServiceControlAction(
        schema="service-control-action/v1",
        action_id="svc-orphan-1",
        action="restart",
        target="web",
        deployment_id="deploy-1",
        deployment_generation=1,
        requester_session_id="sess-x",
        status="failed",
        created_at="2026-09-22T07:00:00+00:00",
        updated_at="2026-09-22T07:01:00+00:00",
        detail="physical rc=2",
    )
    store._write_action_unlocked(orphan)
    view = compose_service_identity_view(store)
    web = view["services"]["web"]
    assert web["admission_barrier"]["operation_id"] == "svc-orphan-1"
    assert web["terminal_action_barrier"] == "terminal_action_holds_barrier status=failed"
    # 其他服务无屏障 → 无孤儿信号
    assert view["services"]["feishu"]["terminal_action_barrier"] is None


def test_active_action_barrier_not_flagged(tmp_path: Path) -> None:
    """R3② 边界: 活跃 action 持屏障是正常态，不触发孤儿信号."""
    store = _green_store(tmp_path)
    store.barriers.establish("web", operation_id="svc-live-1", reason="restart")
    active = ServiceControlAction(
        schema="service-control-action/v1",
        action_id="svc-live-1",
        action="restart",
        target="web",
        deployment_id="deploy-1",
        deployment_generation=1,
        requester_session_id="sess-x",
        status="waiting_for_idle",
        created_at="2026-09-22T07:00:00+00:00",
        updated_at="2026-09-22T07:00:30+00:00",
        detail="",
    )
    store._write_action_unlocked(active)
    view = compose_service_identity_view(store)
    assert view["services"]["web"]["terminal_action_barrier"] is None


def test_identity_view_exposes_server_tz_offset(tmp_path: Path) -> None:
    """前端渲染"服务器挂钟"所需的时区事实字段（含夏令时实时值）."""
    from datetime import datetime as _dt

    view = compose_service_identity_view(_green_store(tmp_path))
    off = view["server_tz_offset_minutes"]
    assert isinstance(off, int)
    assert off == round(_dt.now().astimezone().utcoffset().total_seconds() // 60)

def test_status_evidence_fields_present_and_well_formed(tmp_path: Path) -> None:
    """L19/L20/L22/L24/tasks 9.1: status 只读证据面字段齐全且取值合法."""
    store = _green_store(tmp_path)
    view = compose_service_identity_view(store)
    for key in (
        "available_exits",
        "gate_classification",
        "compat_retirement",
        "idle_state",
        "stage_facts",
        "evidence_refs",
        "audit_signals",
    ):
        assert key in view, key
    # live 代次是推断事实（L8）
    assert view["services"]["web"]["live"]["inferred"] is True
    # 分级表覆盖门禁（只读证据）
    assert {row["gate"] for row in view["gate_classification"]} >= {"barrier", "verify"}
    # 空闲三态（L22）
    for entry in view["idle_state"].values():
        assert entry["state"] in {"confirmed_busy", "confirmed_idle", "unconfirmable"}
    # 四条审计信号（L24）
    assert set(view["audit_signals"]) == {
        "generation_lag",
        "orphan_barrier",
        "barrier_dir_changed",
        "waiting_timeout",
    }


def test_status_evidence_view_is_read_only(tmp_path: Path) -> None:
    """读取路径零副作用：不建目录、不落锁（spec 6.3）."""
    data_dir = tmp_path / "data"
    store = ManagedServiceDeploymentStore(data_dir)
    before = sorted(p.name for p in data_dir.iterdir()) if data_dir.exists() else []
    compose_service_identity_view(store)
    after = sorted(p.name for p in data_dir.iterdir()) if data_dir.exists() else []
    assert before == after
    assert not (data_dir / "audit").exists()


def test_available_exits_reflect_barrier_state(tmp_path: Path) -> None:
    """L20: 屏障出现/消失时可用出口列表随之变化."""
    store = _green_store(tmp_path)
    assert not any(
        row["gate"] == "barrier" for row in compose_service_identity_view(store)["available_exits"]
    )
    store.barriers.establish("web", operation_id="svc-exit-1", reason="restart")
    rows = [
        row
        for row in compose_service_identity_view(store)["available_exits"]
        if row["gate"] == "barrier"
    ]
    assert len(rows) == 1
    assert rows[0]["service"] == "web"
    assert set(rows[0]["exits"]) == {"release", "adopt", "override"}
    # 屏障视图并列 owner 动作状态与可用出口
    barrier = compose_service_identity_view(store)["services"]["web"]["admission_barrier"]
    assert "owner_action_status" in barrier
    assert barrier["available_exits"] == ["release", "adopt", "override"]


def test_audit_signals_surface_stale_waiting_without_new_blocking(tmp_path: Path) -> None:
    """L24: 等待超时/孤儿屏障作为只读信号呈现，不新增阻断行为."""
    store = _green_store(tmp_path)
    stale = ServiceControlAction(
        schema="service-control-action/v1",
        action_id="svc-stale-1",
        action="restart",
        target="web",
        deployment_id="deploy-1",
        deployment_generation=1,
        requester_session_id="sess-x",
        status="waiting_for_idle",
        created_at="2020-01-01T00:00:00+00:00",
        updated_at="2020-01-01T00:00:00+00:00",
        detail="",
    )
    store._write_action_unlocked(stale)
    store.barriers.establish("web", operation_id=stale.action_id, reason="restart")
    view = compose_service_identity_view(store)
    signals = view["audit_signals"]
    assert any(row["action_id"] == "svc-stale-1" for row in signals["waiting_timeout"])
    # 活跃 owner 的屏障不是孤儿；信号只呈现事实
    assert signals["orphan_barrier"] == []
    assert view["stage_facts"]["web"]["action_id"] == "svc-stale-1"

def test_audit_signals_never_create_restart_required(tmp_path: Path) -> None:
    """AC-19/L24: 审计信号只作只读证据，不进入 restart_required（不新增门禁）."""
    store = _green_store(tmp_path)
    stale = ServiceControlAction(
        schema="service-control-action/v1",
        action_id="svc-stale-2",
        action="restart",
        target="web",
        deployment_id="deploy-1",
        deployment_generation=1,
        requester_session_id="sess-x",
        status="waiting_for_idle",
        created_at="2020-01-01T00:00:00+00:00",
        updated_at="2020-01-01T00:00:00+00:00",
        detail="",
    )
    store._write_action_unlocked(stale)
    store.barriers.establish("web", operation_id=stale.action_id, reason="restart")
    web = compose_service_identity_view(store)["services"]["web"]
    assert web["restart_required"] is False
    assert web["reasons"] == []



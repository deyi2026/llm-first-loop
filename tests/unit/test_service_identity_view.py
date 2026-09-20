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
    monkeypatch.setattr(
        "llm_loop.runtime.service_control._verify_restart_targets",
        lambda *_a, **_k: (True, "verify=ok(stub)"),
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

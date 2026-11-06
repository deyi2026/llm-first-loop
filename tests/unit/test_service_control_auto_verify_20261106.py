"""EVO-20261106-fbcfb3e6: restart 收敛自动复核 + requester-exit suggested_next。"""
from __future__ import annotations

import json
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


def test_accept_restart_roundtrip_preserves_auto_verify(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = store.accept_restart(
        target="web",
        expected_generation=1,
        requester_session_id="sess-x",
        auto_verify=True,
    )
    assert action.auto_verify is True
    raw = action.to_dict()
    assert raw["auto_verify"] is True and raw["auto_verify_receipt"] == ""
    restored = sc.ServiceControlAction.from_dict(raw)
    assert restored.auto_verify is True


def test_old_action_dict_defaults_auto_verify_absent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = store.accept_restart(
        target="web", expected_generation=1, requester_session_id="sess-y"
    )
    raw = action.to_dict()
    raw.pop("auto_verify", None)
    raw.pop("auto_verify_receipt", None)
    restored = sc.ServiceControlAction.from_dict(raw)
    assert restored.auto_verify is False
    assert restored.auto_verify_receipt == ""


def test_auto_verify_receipt_only_when_requested(tmp_path: Path) -> None:
    store = _store(tmp_path)
    on = store.accept_restart(
        target="web", expected_generation=1, requester_session_id="s", auto_verify=True
    )
    receipt = sc._auto_verify_receipt(on, "confirmed_ok", converged=True, summary="all ok")
    payload = json.loads(receipt)
    assert payload["converged"] is True
    assert payload["verdict"] == "confirmed_ok"
    assert payload["desired_generation"] == 1

    store2 = _store(tmp_path / "second")
    off = store2.accept_restart(
        target="web", expected_generation=1, requester_session_id="s"
    )
    assert sc._auto_verify_receipt(off, "confirmed_ok", converged=True, summary="x") is None


def test_requester_exit_timeout_writes_suggested_next(tmp_path: Path) -> None:
    store = _store(tmp_path)
    action = store.accept_restart(
        target="web", expected_generation=1, requester_session_id="sess-z"
    )
    ok = sc._wait_for(
        store,
        action,
        status="waiting_for_requester_exit",
        busy_probe=lambda: True,
        poll_s=0.01,
        timeout_s=0.05,
        timeout_detail="requester run still active",
        gate="waiting_for_requester_exit",
    )
    assert ok is False
    final = store.read_action(action.action_id)
    assert final is not None and final.status == "failed"
    assert final.next_step, "requester-exit 超时必须写结构化 suggested_next"
    payload = json.loads(final.next_step)
    assert payload["kind"] == "requester_exit_timeout"
    assert payload["params"]["expected_generation"] == 1

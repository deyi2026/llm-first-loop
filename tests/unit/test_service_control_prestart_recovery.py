"""Pre-restart failure recovery must not strand admission barriers."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from llm_loop.runtime import service_control as sc
from llm_loop.runtime import unified_release as ur


def _store(tmp_path):
    store = sc.ManagedServiceDeploymentStore(tmp_path / "data")
    dep = sc.ManagedServiceDeployment(
        schema=sc._DEPLOYMENT_SCHEMA, deployment_id="dep-recovery", generation=1,
        git_head="a" * 40, code_root=str(tmp_path), runtime_root=str(tmp_path),
        webui_artifact_sha256="b" * 64,
    )
    store.compare_and_swap(dep, expected_generation=0)
    return store, dep


def _deny(reason):
    raise PermissionError("reason store denied")


def test_idle_timeout_with_denied_reason_store_releases_owned_barriers(tmp_path, monkeypatch):
    store, _ = _store(tmp_path)
    action = store.accept_restart(target="all", expected_generation=1, requester_session_id="tester")
    monkeypatch.setattr(store.evidence, "write_full", _deny)
    assert sc._wait_for(
        store, action, status="waiting_for_idle", busy_probe=lambda: True,
        poll_s=0, timeout_s=0, timeout_detail="target still busy", gate="waiting_for_idle",
    ) is False
    final = store.read_action(action.action_id)
    assert final is not None and final.status == "failed"
    assert "target still busy" in final.detail
    assert final.reason_ref == ""
    assert not store.barriers.snapshot()


def test_prestart_failure_keeps_full_inline_reason_not_old_ref(tmp_path, monkeypatch):
    store, _ = _store(tmp_path)
    action = store.accept_restart(target="web", expected_generation=1, requester_session_id="tester")
    waiting = store.update_action(action.action_id, status="waiting_for_idle", detail="old")
    assert waiting.reason_ref
    monkeypatch.setattr(store.evidence, "write_full", _deny)
    full = "complete reason " * 200
    final = store.update_action(action.action_id, status="failed", detail=full)
    assert final.detail == full
    assert final.reason_ref == ""
    assert store.barriers.blocked("web") is None


def test_running_failure_does_not_relax_evidence_or_release_barrier(tmp_path, monkeypatch):
    store, _ = _store(tmp_path)
    action = store.accept_restart(target="web", expected_generation=1, requester_session_id="tester")
    store.update_action(action.action_id, status="running")
    monkeypatch.setattr(store.evidence, "write_full", _deny)
    with pytest.raises(PermissionError):
        store.update_action(action.action_id, status="failed", detail="physical failure")
    current = store.read_action(action.action_id)
    assert current is not None and current.status == "running"
    assert store.barriers.blocked("web") is not None


def _old_worker(store, action, *, status="waiting_for_idle"):
    import dataclasses

    updated = dataclasses.replace(
        action, status=status, worker_pid=os.getpid(),
        updated_at=(datetime.now().astimezone() - timedelta(seconds=5000)).isoformat(),
    )
    with store.lease():
        store._write_action_unlocked(updated)
    return updated


def test_coordinator_reaps_zombie_without_new_restart(tmp_path, monkeypatch):
    store, dep = _store(tmp_path)
    action = store.accept_restart(target="all", expected_generation=1, requester_session_id="tester")
    _old_worker(store, action)
    monkeypatch.setattr(sc.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="Z+\n"))
    with pytest.raises(RuntimeError, match="failed; no automatic retry"):
        ur._await_action(store, dep, action.action_id, timeout_s=1, poll_s=0)
    final = store.read_action(action.action_id)
    assert final is not None and final.status == "failed"
    assert final.stage_fact == "not_started"
    assert not store.barriers.snapshot()


def test_confirmed_only_does_not_reap_live_or_running(tmp_path, monkeypatch):
    store, _ = _store(tmp_path)
    action = store.accept_restart(target="web", expected_generation=1, requester_session_id="tester")
    _old_worker(store, action)
    monkeypatch.setattr(sc.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="S\n"))
    store.reap_dead_waiting_action(action.action_id)
    live = store.read_action(action.action_id)
    assert live is not None and live.status == "waiting_for_idle"
    _old_worker(store, live, status="running")
    monkeypatch.setattr(sc, "_pid_dead", lambda pid: True)
    store.reap_dead_waiting_action(action.action_id)
    running = store.read_action(action.action_id)
    assert running is not None and running.status == "running"
    assert store.barriers.blocked("web") is not None

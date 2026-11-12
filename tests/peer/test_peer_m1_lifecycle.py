"""Peer normal-path preview, execution ownership and interrupted-write regressions."""
from __future__ import annotations

import importlib.util
import runpy
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.peer.errors import PeerError

_FIX = runpy.run_path(str(Path(__file__).with_name("test_peer_supervision.py")))
_env, _held, _grant, _write_payload = (_FIX[k] for k in ("_env", "_held", "_grant", "_write_payload"))
GRANT_ID = _FIX["GRANT_ID"]
REPO = Path(__file__).resolve().parents[2]


def _operator_module():
    spec = importlib.util.spec_from_file_location("peer_m1_operator", REPO / "scripts/peer_operator.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_binds_target_before_human_confirmation(tmp_path, monkeypatch):
    service, store, root = _env(tmp_path)
    store.issue_grant(_grant(root))
    target = root / "out.txt"
    target.write_bytes(b"shown before confirmation")
    payload = _write_payload(root)
    payload["params"]["overwrite"] = True
    task_id = service.submit(payload)["task_id"]
    module = _operator_module()
    monkeypatch.setattr(module, "_service", lambda args: service)
    monkeypatch.setattr(module, "_print_scope", lambda args: None)
    monkeypatch.setattr(module, "_data_dir_owned_by_me", lambda args: True)
    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: True)

    def confirm_after_change(prompt):
        target.write_bytes(b"changed while human was reading")
        return task_id[-6:]

    monkeypatch.setattr("builtins.input", confirm_after_change)
    args = SimpleNamespace(task_id=task_id, operator="human-qa", data_dir=store.root)
    with pytest.raises(PeerError) as error:
        module._cmd_confirm(args)
    assert error.value.reason_code == "supervision_ticket_mismatch"
    assert target.read_bytes() == b"changed while human was reading"
    assert store.get_grant(GRANT_ID).tasks_used == 0


def test_startup_recovery_does_not_reap_live_executor(tmp_path, monkeypatch):
    service, store, root, task_id = _held(_env(tmp_path))
    observer, _, _ = _env(tmp_path)
    service.issue_supervision_ticket(task_id, issued_by="qa")
    execute = service._executor.run
    observed = []

    def run_with_recovery(**kwargs):
        observed.extend(observer.recover_interrupted())
        assert store.get_task(task_id).state == "running"
        return execute(**kwargs)

    monkeypatch.setattr(service._executor, "run", run_with_recovery)
    assert service.resume_supervised(task_id, decided_by="qa")["state"] == "succeeded"
    assert observed == []
    assert (root / "out.txt").read_bytes() == b"hello"
    assert store.get_grant(GRANT_ID).tasks_used == 1


@pytest.mark.parametrize("competing_action", ["reject", "confirm"])
def test_competing_decision_observes_execution_without_second_audit(tmp_path, monkeypatch, competing_action):
    service, store, root, task_id = _held(_env(tmp_path))
    observer, _, _ = _env(tmp_path)
    service.issue_supervision_ticket(task_id, issued_by="first")
    entered, release = threading.Event(), threading.Event()
    execute = service._executor.run
    results, failures = [], []

    def held_execute(**kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return execute(**kwargs)

    def worker():
        try:
            results.append(service.resume_supervised(task_id, decided_by="first"))
        except BaseException as exc:
            failures.append(exc)

    monkeypatch.setattr(service._executor, "run", held_execute)
    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert entered.wait(timeout=5)
        if competing_action == "reject":
            other = observer.reject_supervised(task_id, decided_by="second")
        else:
            other = observer.resume_supervised(task_id, decided_by="second")
        assert other["state"] == "running"
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert failures == []
    assert results[0]["state"] == "succeeded"
    assert (root / "out.txt").read_bytes() == b"hello"
    assert store.get_grant(GRANT_ID).tasks_used == 1
    assert len(list((store.root / "admissions").glob("*.json"))) == 1


@pytest.mark.parametrize("cut_point", ["after_ticket", "after_commit"])
def test_process_crash_preserves_unknown_outcome_without_rewrite(tmp_path, cut_point):
    service, store, root, task_id = _held(_env(tmp_path))
    service.issue_supervision_ticket(task_id, issued_by="qa")
    child = """
import os, runpy, sys
from pathlib import Path
fixture = runpy.run_path(str(Path("tests/peer/test_peer_supervision.py")))
service, store, root = fixture["_env"](Path(sys.argv[1]))
task_id, cut = sys.argv[2:]
if cut == "after_ticket":
    original = service._operator.consume
    def crash(*args, **kwargs):
        original(*args, **kwargs)
        os._exit(17)
    service._operator.consume = crash
else:
    original = service._executor.run
    def crash(**kwargs):
        original(**kwargs)
        os._exit(17)
    service._executor.run = crash
service.resume_supervised(task_id, decided_by="qa")
"""
    proc = subprocess.run(
        [sys.executable, "-c", child, str(tmp_path), task_id, cut_point],
        cwd=REPO, capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 17, proc.stderr
    assert store.get_grant(GRANT_ID).tasks_used == 1
    recovered = service.recover_interrupted()
    assert [(t.task_id, t.state) for t in recovered] == [(task_id, "unknown_outcome")]
    target = root / "out.txt"
    before = target.read_bytes() if target.exists() else None
    assert before == (b"hello" if cut_point == "after_commit" else None)
    replay = service.submit(_write_payload(root))
    assert replay["task_id"] == task_id
    assert replay["state"] == "unknown_outcome"
    assert (target.read_bytes() if target.exists() else None) == before
    assert store.get_grant(GRANT_ID).tasks_used == 1

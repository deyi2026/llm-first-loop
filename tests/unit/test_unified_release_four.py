"""Four-service release: one CAS, two verified actions, no replay."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from llm_loop.runtime import service_control as sc
from llm_loop.runtime import unified_release as ur


class FakeStore:
    def __init__(self, data_dir: Path, *, current=None):
        self.data_dir = data_dir
        self.current = current
        self.actions = []
        self.calls = []

    def read(self):
        return self.current

    def compare_and_swap(self, candidate, *, expected_generation):
        self.calls.append(("cas", expected_generation))
        assert self.current is None or self.current.generation == expected_generation
        self.current = candidate

    def accept_restart(self, *, target, expected_generation, requester_session_id, origin):
        assert self.current is not None
        assert self.current.generation == expected_generation
        action = sc.ServiceControlAction(
            schema=sc._ACTION_SCHEMA,
            action_id=f"svc-{len(self.actions)+1}",
            action="restart", target=target,
            deployment_id=self.current.deployment_id,
            deployment_generation=expected_generation,
            requester_session_id=requester_session_id,
            status="accepted", created_at="2026-11-15T10:00:00+00:00",
            updated_at="2026-11-15T10:00:00+00:00", origin=origin,
        )
        self.actions.append(action)
        self.calls.append(("accept", target))
        return action

    def read_action(self, action_id):
        return next((a for a in self.actions if a.action_id == action_id), None)

    def set_action(self, action_id, **changes):
        self.actions = [dataclasses.replace(a, **changes) if a.action_id == action_id else a for a in self.actions]


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    candidate = sc.ManagedServiceDeployment(
        schema=sc._DEPLOYMENT_SCHEMA,
        deployment_id="deploy-four", generation=12,
        git_head="a" * 40,
        code_root=str(tmp_path / "release"),
        runtime_root=str(tmp_path),
        webui_artifact_sha256="b" * 64,
    )
    store = FakeStore(tmp_path)
    monkeypatch.setattr(ur.sc, "build_deployment", lambda **kw: candidate)
    monkeypatch.setattr(ur.sc, "read_all_actions", lambda store: list(store.actions))

    def spawn(store, action_id):
        action = store.read_action(action_id)
        store.calls.append(("spawn", action.target))
        store.set_action(action_id, status="succeeded", verify_verdict="confirmed_ok", worker_pid=10)

    monkeypatch.setattr(ur.sc, "spawn_service_control_worker", spawn)

    def identity(store):
        return {
            "services": {
                name: {
                    "live": {"pid_alive": True, "matches_desired_generation": True},
                    "restart_required": False, "admission_barrier": None,
                }
                for name in ur._SERVICES
            },
            "admission_barriers": [],
        }

    monkeypatch.setattr(ur.sc, "compose_service_identity_view", identity)
    path, _, _ = ur._paths(tmp_path, "release-test")
    path.parent.mkdir(parents=True)
    ur._save(path, {
        "schema": 1, "release_id": "release-test", "data_dir": str(tmp_path),
        "code_root": str(tmp_path / "release"), "runtime_root": str(tmp_path),
        "expected_generation": 11, "expected_sha": "a" * 40,
        "requester": "tester", "reason": "test", "status": "planned",
    })
    return SimpleNamespace(store=store, candidate=candidate, journal=path)


def test_one_cas_two_verified_stages_and_no_replay(rig):
    result = ur.run_release(rig.store, "release-test", timeout_s=0.1, poll_s=0)
    assert result["status"] == "succeeded"
    assert result["phase1_action_id"] == "svc-1"
    assert result["phase2_action_id"] == "svc-2"
    assert all(a.requester_session_id == "tester" for a in rig.store.actions)
    assert [a.origin for a in rig.store.actions] == [
        "unified-release:release-test:phase1", "unified-release:release-test:phase2",
    ]
    assert rig.store.calls == [
        ("cas", 11), ("accept", "all"), ("spawn", "all"),
        ("accept", "wecom"), ("spawn", "wecom"),
    ]
    assert ur.run_release(rig.store, "release-test") == result
    assert len(rig.store.calls) == 5


def test_first_stage_failure_blocks_wecom(rig, monkeypatch):
    def fail_spawn(store, action_id):
        action = store.read_action(action_id)
        store.calls.append(("spawn", action.target))
        store.set_action(action_id, status="failed", verify_verdict="confirmed_fail")

    monkeypatch.setattr(ur.sc, "spawn_service_control_worker", fail_spawn)
    with pytest.raises(RuntimeError, match="failed"):
        ur.run_release(rig.store, "release-test", timeout_s=0.1, poll_s=0)
    assert ur._read(rig.journal)["status"] == "blocked"
    assert [a.target for a in rig.store.actions] == ["all"]
    with pytest.raises(RuntimeError, match="failed"):
        ur.run_release(rig.store, "release-test", timeout_s=0.1, poll_s=0)
    assert [a.target for a in rig.store.actions] == ["all"]


def test_resume_from_verified_first_stage_without_restarting_it(rig):
    rig.store.current = rig.candidate
    a = rig.store.accept_restart(target="all", expected_generation=12,
                                 requester_session_id="tester",
                                 origin="unified-release:release-test:phase1")
    rig.store.set_action(a.action_id, status="succeeded", verify_verdict="confirmed_ok")
    ur._save(rig.journal, ur._read(rig.journal), candidate=rig.candidate.to_dict(),
             phase1_action_id=a.action_id, phase1_spawn_intent=True,
             phase1_spawned=True, status="phase1_verified")
    rig.store.calls.clear()
    result = ur.run_release(rig.store, "release-test", timeout_s=0.1, poll_s=0)
    assert result["status"] == "succeeded"
    assert rig.store.calls == [("accept", "wecom"), ("spawn", "wecom")]


def test_adopt_existing_verified_wecom_without_double_restart(rig):
    rig.store.current = rig.candidate
    first = rig.store.accept_restart(target="all", expected_generation=12,
                                     requester_session_id="tester",
                                     origin="unified-release:release-test:phase1")
    rig.store.set_action(first.action_id, status="succeeded", verify_verdict="confirmed_ok")
    other = rig.store.accept_restart(target="wecom", expected_generation=12,
                                     requester_session_id="another-session", origin="restart")
    rig.store.set_action(other.action_id, status="succeeded", verify_verdict="confirmed_ok")
    ur._save(rig.journal, ur._read(rig.journal), candidate=rig.candidate.to_dict(),
             phase1_action_id=first.action_id, status="phase1_verified")
    rig.store.calls.clear()
    result = ur.run_release(rig.store, "release-test", timeout_s=0.1, poll_s=0)
    assert result["phase2_adopted"] is True
    assert result["phase2_action_id"] == other.action_id
    assert rig.store.calls == []


def test_unknown_spawn_outcome_never_replays(rig):
    rig.store.current = rig.candidate
    action = rig.store.accept_restart(target="all", expected_generation=12,
                                      requester_session_id="tester",
                                      origin="unified-release:release-test:phase1")
    ur._save(rig.journal, ur._read(rig.journal), candidate=rig.candidate.to_dict(),
             phase1_action_id=action.action_id, phase1_spawn_intent=True)
    rig.store.calls.clear()
    with pytest.raises(RuntimeError, match="no automatic second spawn"):
        ur.run_release(rig.store, "release-test", timeout_s=0.1, poll_s=0)
    assert rig.store.calls == []


def test_generation_conflict_fails_before_any_restart(rig):
    rig.store.current = dataclasses.replace(rig.candidate, generation=19)
    with pytest.raises(RuntimeError, match="generation changed"):
        ur.run_release(rig.store, "release-test", timeout_s=0.1, poll_s=0)
    assert not rig.store.actions
    assert not rig.store.calls


def test_unverified_live_blocks_second_stage(rig, monkeypatch):
    def bad_identity(store):
        return {"services": {
            n: {"live": {"pid_alive": n != "learning", "matches_desired_generation": True},
                "restart_required": False, "admission_barrier": None}
            for n in ur._SERVICES}, "admission_barriers": []}
    monkeypatch.setattr(ur.sc, "compose_service_identity_view", bad_identity)
    with pytest.raises(RuntimeError, match="learning not verified"):
        ur.run_release(rig.store, "release-test", timeout_s=0.1, poll_s=0)
    assert [a.target for a in rig.store.actions] == ["all"]


def test_id_rejects_traversal(tmp_path):
    for invalid in ("../outside", "", "a/b", "a.b", "a" * 65):
        with pytest.raises(ValueError, match="release-id"):
            ur._paths(tmp_path, invalid)


def test_journal_contains_only_explicit_actions(rig):
    ur.run_release(rig.store, "release-test", timeout_s=0.1, poll_s=0)
    payload = json.loads(rig.journal.read_text())
    assert payload["generation"] == 12
    assert payload["git_head"] == "a" * 40
    assert payload["phase1_action_id"] != payload["phase2_action_id"]
    assert payload["completed_at"]


def test_second_stage_failure_does_not_replay_any_stage(rig, monkeypatch):
    def selective_spawn(store, action_id):
        action = store.read_action(action_id)
        store.calls.append(("spawn", action.target))
        if action.target == "wecom":
            store.set_action(action_id, status="failed", verify_verdict="confirmed_fail")
        else:
            store.set_action(action_id, status="succeeded", verify_verdict="confirmed_ok")

    monkeypatch.setattr(ur.sc, "spawn_service_control_worker", selective_spawn)
    with pytest.raises(RuntimeError, match="failed"):
        ur.run_release(rig.store, "release-test", timeout_s=0.1, poll_s=0)
    assert [a.target for a in rig.store.actions] == ["all", "wecom"]
    count = len(rig.store.calls)
    with pytest.raises(RuntimeError, match="failed"):
        ur.run_release(rig.store, "release-test", timeout_s=0.1, poll_s=0)
    assert len(rig.store.calls) == count


def test_existing_worker_pid_does_not_spawn_duplicate(rig):
    rig.store.current = rig.candidate
    action = rig.store.accept_restart(target="all", expected_generation=12,
                                      requester_session_id="tester",
                                      origin="unified-release:release-test:phase1")
    rig.store.set_action(action.action_id, worker_pid=998)
    ur._save(rig.journal, ur._read(rig.journal), candidate=rig.candidate.to_dict())
    rig.store.calls.clear()
    with pytest.raises(TimeoutError, match="still accepted"):
        ur.run_release(rig.store, "release-test", timeout_s=0, poll_s=0)
    assert rig.store.calls == []
    assert ur._read(rig.journal)["phase1_spawned"] is True


def test_symlinked_journal_is_refused(tmp_path):
    path, _, _ = ur._paths(tmp_path, "release-test")
    path.parent.mkdir(parents=True)
    target = tmp_path / "sensitive"
    target.write_text("keep")
    path.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        ur.run_release(cast(sc.ManagedServiceDeploymentStore, FakeStore(tmp_path)), "release-test")
    assert target.read_text() == "keep"


def test_exact_sha_mismatch_fails_before_cas(rig):
    ur._save(rig.journal, ur._read(rig.journal), expected_sha="c" * 40)
    with pytest.raises(RuntimeError, match="reviewed SHA"):
        ur.run_release(rig.store, "release-test", timeout_s=0.1, poll_s=0)
    assert not rig.store.actions
    assert not rig.store.calls


def test_busy_wecom_wait_is_resumable_without_new_action(rig, monkeypatch):
    def wait_on_wecom(store, action_id):
        action = store.read_action(action_id)
        store.calls.append(("spawn", action.target))
        if action.target == "wecom":
            store.set_action(action_id, status="waiting_for_idle", worker_pid=333)
        else:
            store.set_action(action_id, status="succeeded", verify_verdict="confirmed_ok")

    monkeypatch.setattr(ur.sc, "spawn_service_control_worker", wait_on_wecom)
    with pytest.raises(TimeoutError, match="waiting_for_idle"):
        ur.run_release(rig.store, "release-test", timeout_s=0, poll_s=0)
    assert [a.target for a in rig.store.actions] == ["all", "wecom"]
    calls = list(rig.store.calls)
    rig.store.set_action("svc-2", status="succeeded", verify_verdict="confirmed_ok")
    assert ur.run_release(rig.store, "release-test", timeout_s=0, poll_s=0)["status"] == "succeeded"
    assert rig.store.calls == calls


def test_global_coordinator_lock_blocks_parallel_release(rig):
    import fcntl
    import os

    _, lock, _ = ur._paths(rig.store.data_dir, "other-release")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="already running"):
            ur.run_release(rig.store, "release-test", timeout_s=0, poll_s=0)
        assert not rig.store.calls
    finally:
        os.close(fd)


def test_cli_requires_explicit_requester_and_sha(tmp_path, capsys):
    args = [
        "release-four", "--release-id", "new-one", "--data-dir", str(tmp_path),
        "--code-root", str(tmp_path), "--runtime-root", str(tmp_path),
        "--expected-generation", "4", "--expected-sha", "a" * 40,
    ]
    assert sc.main(args) == 2
    assert "requester" in capsys.readouterr().err
    assert not (tmp_path / "runtime/unified-releases/new-one.json").exists()


def test_verify_evidence_ready_waits_without_retry(rig, monkeypatch):
    def pending_spawn(store, action_id):
        action = store.read_action(action_id)
        store.calls.append(("spawn", action.target))
        store.set_action(action_id, status="verify_evidence_ready", worker_pid=123)

    monkeypatch.setattr(ur.sc, "spawn_service_control_worker", pending_spawn)
    with pytest.raises(TimeoutError, match="verify_evidence_ready"):
        ur.run_release(rig.store, "release-test", timeout_s=0, poll_s=0)
    assert [a.target for a in rig.store.actions] == ["all"]
    assert rig.store.calls.count(("spawn", "all")) == 1


def test_detached_duplicate_is_reported_as_already_running(rig, monkeypatch, capsys):
    import fcntl
    import os

    _, lock, log = ur._paths(rig.store.data_dir, "release-test")
    monkeypatch.setattr(ur.sc, "ManagedServiceDeploymentStore", lambda path: rig.store)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert ur._launch_worker(ur._read(rig.journal), rig.journal, log, wait=False) == 12
        assert json.loads(capsys.readouterr().out)["status"] == "already_running"
        assert not rig.store.calls
    finally:
        os.close(fd)


def test_detached_symlinked_log_is_refused(rig, monkeypatch):
    _, _, log = ur._paths(rig.store.data_dir, "release-test")
    target = rig.store.data_dir / "protected"
    target.write_text("unchanged")
    log.symlink_to(target)
    monkeypatch.setattr(ur.sc, "ManagedServiceDeploymentStore", lambda path: rig.store)
    monkeypatch.setattr(ur.sc, "_control_subprocess_env", lambda **kw: {})
    with pytest.raises(ValueError, match="log must not be a symlink"):
        ur._launch_worker(ur._read(rig.journal), rig.journal, log, wait=False)
    assert target.read_text() == "unchanged"
    assert not rig.store.calls


def test_adopted_wecom_resume_after_live_check_interruption(rig, monkeypatch):
    rig.store.current = rig.candidate
    first = rig.store.accept_restart(
        target="all", expected_generation=12, requester_session_id="tester",
        origin="unified-release:release-test:phase1",
    )
    rig.store.set_action(first.action_id, status="succeeded", verify_verdict="confirmed_ok")
    external = rig.store.accept_restart(
        target="wecom", expected_generation=12, requester_session_id="another-session",
        origin="restart",
    )
    rig.store.set_action(external.action_id, status="succeeded", verify_verdict="confirmed_ok")
    ur._save(rig.journal, ur._read(rig.journal), candidate=rig.candidate.to_dict(),
             phase1_action_id=first.action_id, status="phase1_verified")
    rig.store.calls.clear()
    real_verify = ur._verify_live
    failures = {"remaining": 1}

    def interrupt_after_adoption(store, candidate, names):
        if names == ur._SERVICES and failures["remaining"]:
            failures["remaining"] -= 1
            raise RuntimeError("simulated interruption after adoption")
        real_verify(store, candidate, names)

    monkeypatch.setattr(ur, "_verify_live", interrupt_after_adoption)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        ur.run_release(rig.store, "release-test", timeout_s=0.1, poll_s=0)
    blocked = ur._read(rig.journal)
    assert blocked["status"] == "blocked"
    assert blocked["phase2_adopted"] is True
    assert blocked["phase2_action_id"] == external.action_id
    assert ur.run_release(rig.store, "release-test", timeout_s=0.1, poll_s=0)["status"] == "succeeded"
    assert rig.store.calls == []
    assert len(rig.store.actions) == 2


def test_adopted_wecom_receipt_identity_change_fails_closed(rig):
    rig.store.current = rig.candidate
    first = rig.store.accept_restart(
        target="all", expected_generation=12, requester_session_id="tester",
        origin="unified-release:release-test:phase1",
    )
    rig.store.set_action(first.action_id, status="succeeded", verify_verdict="confirmed_ok")
    external = rig.store.accept_restart(
        target="wecom", expected_generation=12, requester_session_id="another-session",
        origin="restart",
    )
    rig.store.set_action(external.action_id, status="succeeded", verify_verdict="confirmed_fail")
    ur._save(rig.journal, ur._read(rig.journal), candidate=rig.candidate.to_dict(),
             phase1_action_id=first.action_id, phase2_action_id=external.action_id,
             phase2_adopted=True, status="blocked")
    rig.store.calls.clear()
    with pytest.raises(RuntimeError, match="adopted WeCom receipt missing or invalid"):
        ur.run_release(rig.store, "release-test", timeout_s=0.1, poll_s=0)
    assert rig.store.calls == []
    assert len(rig.store.actions) == 2

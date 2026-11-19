"""Gate C negative security tests. Mocked Host identity is NOT real UID463 acceptance."""

from __future__ import annotations

import json
import os
import threading

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from llm_loop.embodied_sim import attestation, oracle_daemon
from llm_loop.embodied_sim.contract import VerificationStatus


@pytest.fixture()
def keys(tmp_path):
    key = Ed25519PrivateKey.generate()
    private = tmp_path / "test.key"
    public = tmp_path / "test.pub"
    private.write_text(
        key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        ).hex()
    )
    public.write_text(
        key.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex()
    )
    return key, private, public


@pytest.fixture()
def daemon(keys):
    return oracle_daemon.build_daemon_from_scene_seed(
        7, run_id="run-A", private_key_path=str(keys[1])
    )


@pytest.fixture()
def ledger(tmp_path):
    return attestation.ReplayLedger(tmp_path / "replay.sqlite3")


def _nonce(i: int) -> str:
    return f"{i:032x}"


def _fake_receipt(key, *, claim_kind="place", uid=463):
    core = {
        "claim_kind": claim_kind,
        "run_id": "run-A",
        "scene_epoch": 1,
        "action_seq": 0,
        "nonce": _nonce(10),
        "snapshot_hash": "0" * 64,
        "oracle_execution": "host_uid463_managed",
        "verdict": "success",
        "uid": uid,
        "experiment_id": "M1-SIM-001",
        "oracle_impl": "embodied-m1-oracle-daemon-v0",
        "evidence": {"check": "mock"},
    }
    return {**core, "signature": key.sign(attestation.canonical(core)).hex()}


def _verify(receipt, public, ledger, **overrides):
    args = {
        "pubkey_path": str(public),
        "expected_run": "run-A",
        "expected_epoch": 1,
        "expected_action_seq": 0,
        "expected_nonce": _nonce(10),
        "expected_experiment_id": "M1-SIM-001",
        "replay_ledger": ledger,
    }
    args.update(overrides)
    return attestation.verify_attestation(receipt, **args)


def test_no_host_queue_fails_closed(tmp_path):
    with pytest.raises(attestation.AttestationUnavailableError):
        attestation.request_attestation(
            {"skill": "verify_place"},
            run_id="run-A",
            action_seq=0,
            jobs_dir=str(tmp_path / "absent-jobs"),
            receipts_dir=str(tmp_path / "absent-receipts"),
        )


def test_client_retains_issued_nonce_independently_of_receipt(daemon, tmp_path):
    jobs, receipts = tmp_path / "jobs", tmp_path / "receipts"
    jobs.mkdir()
    receipts.mkdir()
    timer = threading.Timer(0.05, lambda: daemon.process_pending(str(jobs), str(receipts)))
    timer.start()
    nonce, receipt = attestation.request_attestation(
        {"skill": "observe"},
        run_id="run-A",
        action_seq=0,
        jobs_dir=str(jobs),
        receipts_dir=str(receipts),
    )
    timer.join()
    assert len(nonce) == 32
    assert receipt["oracle_execution"] == "observation_only"
    assert "nonce" not in receipt  # cannot derive expected nonce from response


@pytest.mark.parametrize(
    "command",
    [
        {"skill": "teleport_cube"},
        {"skill": "shell", "params": {"cmd": "id"}},
        {"skill": "observe", "snapshot": {"cube": {}}},
        {"skill": "verify_place", "path": "/tmp/forged.json"},
        {"skill": "grasp", "params": {"force": 1}},
        {"skill": "verify_grasp", "params": {"snapshot": {}}},
        {"skill": "move_to", "params": {"x": 0.1, "y": 0, "z": 0.1, "file": "/etc/passwd"}},
        {"skill": "move_to", "params": {"x": 0.1, "y": 0, "z": float("nan")}},
        {"skill": "move_to", "params": {"x": 0.1, "y": 0, "z": float("inf")}},
        {"skill": "move_to", "params": {"x": True, "y": 0, "z": 0.1}},
        {"skill": "move_to", "params": {"x": 99, "y": 0, "z": 0.1}},
        {"skill": "move_to", "params": {"x": 10**400, "y": 0, "z": 0.1}},
        {"skill": "move_to", "params": []},
    ],
)
def test_command_rejects_unsafe_inputs(command):
    with pytest.raises(attestation.AttestationUnavailableError):
        attestation.validate_command(command)


def test_allowlisted_commands():
    for skill in ("observe", "grasp", "release", "verify_grasp", "verify_place"):
        assert attestation.validate_command({"skill": skill}) == skill
    assert (
        attestation.validate_command({"skill": "move_to", "params": {"x": 0.18, "y": 0, "z": 0.05}})
        == "move_to"
    )


def test_daemon_run_and_nonce_checks(daemon):
    r = daemon.handle_command({"skill": "observe"}, "run-B", 0, _nonce(1))
    assert r["oracle_execution"] == "daemon_fail_closed"
    r = daemon.handle_command({"skill": "observe"}, "run-A", 0, "../x")
    assert r["oracle_execution"] == "daemon_fail_closed"
    r = daemon.handle_command({"skill": "observe"}, "run-A", 1, _nonce(2))
    assert r["oracle_execution"] == "daemon_fail_closed"


def test_observation_and_actions_cannot_self_promote(daemon, keys, ledger):
    r = daemon.handle_command({"skill": "observe"}, "run-A", 0, _nonce(1))
    assert r["oracle_execution"] == "observation_only"
    assert "signature" not in r
    assert _verify(r, keys[2], ledger) == VerificationStatus.FAILED_CLAIM
    replay = daemon.handle_command({"skill": "observe"}, "run-A", 0, _nonce(1))
    assert replay["oracle_execution"] == "daemon_fail_closed"
    action = daemon.handle_command({"skill": "release"}, "run-A", 1, _nonce(2))
    assert action["oracle_execution"] == "action_only"
    assert "signature" not in action


def test_non_host_private_key_cannot_sign_even_with_mocked_uid(daemon, monkeypatch):
    monkeypatch.setattr(os, "getuid", lambda: 463)
    r = daemon.handle_command({"skill": "verify_place"}, "run-A", 0, _nonce(3))
    assert r["oracle_execution"] == "daemon_fail_closed"
    assert "Host-installed private key" in r["error"]


def test_rogue_public_key_forgery_rejected(keys, ledger):
    """Regression for the observed P0: attacker-chosen key used to self-verify."""
    fake = _fake_receipt(keys[0])
    assert _verify(fake, keys[2], ledger) == VerificationStatus.FAILED_CLAIM


def test_observe_claim_never_counts_as_place(keys, ledger, monkeypatch):
    fake = _fake_receipt(keys[0], claim_kind="action:observe")
    monkeypatch.setattr(attestation, "PROD_PUBLIC_KEY_PATH", str(keys[2]))
    monkeypatch.setattr(attestation, "PROD_REPLAY_LEDGER_PATH", str(ledger.path))
    monkeypatch.setattr(attestation, "_trusted_host_file", lambda *_args, **_kw: True)
    assert _verify(fake, keys[2], ledger) == VerificationStatus.FAILED_CLAIM


def test_mocked_trust_checks_signature_binding_and_replay(keys, ledger, monkeypatch):
    """Unit mechanism test only: monkeypatch is not proof of a real Host boundary."""
    monkeypatch.setattr(attestation, "PROD_PUBLIC_KEY_PATH", str(keys[2]))
    monkeypatch.setattr(attestation, "PROD_REPLAY_LEDGER_PATH", str(ledger.path))
    monkeypatch.setattr(attestation, "_trusted_host_file", lambda *_args, **_kw: True)
    fake = _fake_receipt(keys[0])
    for kwargs in (
        {"expected_run": "run-B"},
        {"expected_epoch": 2},
        {"expected_action_seq": 1},
        {"expected_nonce": _nonce(11)},
        {"expected_experiment_id": "M1-SIM-002"},
        {"expected_claim_kind": "grasp"},
    ):
        assert _verify(fake, keys[2], ledger, **kwargs) == VerificationStatus.FAILED_CLAIM
    altered = dict(fake, verdict="failure")
    assert _verify(altered, keys[2], ledger) == VerificationStatus.FAILED_CLAIM
    altered_evidence = dict(fake, evidence={"check": "forged"})
    assert _verify(altered_evidence, keys[2], ledger) == VerificationStatus.FAILED_CLAIM
    altered_extra = dict(fake, extra_untrusted="value")
    assert _verify(altered_extra, keys[2], ledger) == VerificationStatus.FAILED_CLAIM
    # Client-side verification remains advisory, never an authority.
    assert _verify(fake, keys[2], ledger) == VerificationStatus.PENDING_ORACLE
    assert _verify(fake, keys[2], ledger) == VerificationStatus.PENDING_ORACLE
    monkeypatch.setattr(os, "getuid", lambda: 463)
    args = {
        "pubkey_path": str(keys[2]),
        "expected_run": "run-A",
        "expected_epoch": 1,
        "expected_action_seq": 0,
        "expected_nonce": _nonce(10),
        "expected_experiment_id": "M1-SIM-001",
        "replay_ledger": ledger,
    }
    assert (
        attestation.verify_attestation_host(fake, **args) == VerificationStatus.VERIFIED_BY_ORACLE
    )
    assert attestation.verify_attestation_host(fake, **args) == VerificationStatus.FAILED_CLAIM
    new_ledger = attestation.ReplayLedger(ledger.path)
    assert _verify(fake, keys[2], new_ledger) == VerificationStatus.FAILED_CLAIM


def test_replay_ledger_atomic_across_threads(ledger):
    results = []

    def consume():
        results.append(ledger.record(_nonce(20), "digest"))

    threads = [threading.Thread(target=consume) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(True) == 1
    assert results.count(False) == 7
    assert attestation.ReplayLedger(ledger.path).seen(_nonce(20))


def test_job_path_traversal_and_symlink_rejected(daemon, tmp_path):
    jobs, receipts = tmp_path / "jobs", tmp_path / "receipts"
    jobs.mkdir()
    receipts.mkdir()
    nonce = _nonce(30)
    (jobs / f"{nonce}.job").write_text(
        json.dumps(
            {
                "command": {"skill": "verify_place"},
                "run_id": "run-A",
                "action_seq": 0,
                "nonce": "../../escape",
            }
        )
    )
    assert daemon.process_pending(str(jobs), str(receipts)) == 0
    assert list(receipts.iterdir()) == []
    target = tmp_path / "target.json"
    target.write_text("{}")
    (jobs / f"{_nonce(31)}.job").symlink_to(target)
    assert daemon.process_pending(str(jobs), str(receipts)) == 0
    assert target.read_text() == "{}"


def test_host_job_never_signs_invalid_command(daemon, tmp_path):
    jobs, receipts = tmp_path / "jobs", tmp_path / "receipts"
    jobs.mkdir()
    receipts.mkdir()
    nonce = _nonce(40)
    (jobs / f"{nonce}.job").write_text(
        json.dumps(
            {
                "command": {"skill": "python", "params": {"code": "pass"}},
                "run_id": "run-A",
                "action_seq": 0,
                "nonce": nonce,
            }
        )
    )
    assert daemon.process_pending(str(jobs), str(receipts)) == 1
    receipt = json.loads((receipts / f"{nonce}.receipt.json").read_text())
    assert receipt["oracle_execution"] == "daemon_fail_closed"
    assert "signature" not in receipt

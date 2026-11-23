"""Mocked UID463 Host bridge tests; real cross-UID acceptance is separate."""

from __future__ import annotations

import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from llm_loop.embodied_sim import attestation, host_bridge, oracle_daemon
from llm_loop.embodied_sim.contract import VerificationStatus


@pytest.fixture()
def host(tmp_path, monkeypatch):
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
        .public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        .hex()
    )
    ledger = attestation.ReplayLedger(tmp_path / "ledger.sqlite3")
    monkeypatch.setattr(os, "getuid", lambda: 463)
    monkeypatch.setattr(attestation, "PROD_REPLAY_LEDGER_PATH", str(ledger.path))
    monkeypatch.setattr(host_bridge, "PROD_REPLAY_LEDGER_PATH", str(ledger.path))
    monkeypatch.setattr(attestation, "PROD_PUBLIC_KEY_PATH", str(public))
    monkeypatch.setattr(host_bridge, "PROD_PUBLIC_KEY_PATH", str(public))
    monkeypatch.setattr(oracle_daemon, "PROD_PRIVATE_KEY_PATH", str(private))
    monkeypatch.setattr(host_bridge, "PROD_PRIVATE_KEY_PATH", str(private))
    monkeypatch.setattr(attestation, "_trusted_host_file", lambda *_a, **_kw: True)
    monkeypatch.setattr(host_bridge, "_trusted_host_file", lambda *_a, **_kw: True)
    monkeypatch.setattr(oracle_daemon, "_trusted_host_file", lambda *_a, **_kw: True)
    daemon = oracle_daemon.build_daemon_from_scene_seed(7, "run-A", str(private))
    jobs, receipts = tmp_path / "jobs", tmp_path / "receipts"
    jobs.mkdir()
    receipts.mkdir()
    return key, daemon, ledger, public, jobs, receipts


def _signed_receipt(key, nonce: str) -> dict:
    core = {
        "claim_kind": "grasp",
        "run_id": "run-A",
        "scene_epoch": 1,
        "action_seq": 0,
        "nonce": nonce,
        "snapshot_hash": "a" * 64,
        "oracle_execution": "host_uid463_managed",
        "verdict": "success",
        "uid": 463,
        "experiment_id": "M1-SIM-001",
        "oracle_impl": "embodied-m1-oracle-daemon-v0",
        "evidence": {"mock": True},
    }
    return {**core, "signature": key.sign(attestation.canonical(core)).hex()}


def _binding(nonce: str) -> dict:
    return {
        "expected_run": "run-A",
        "expected_epoch": 1,
        "expected_action_seq": 0,
        "expected_nonce": nonce,
        "expected_experiment_id": "M1-SIM-001",
        "expected_claim_kind": "grasp",
    }


def _process(host, receipt, binding, request_nonce):
    _key, daemon, ledger, _public, jobs, receipts = host
    host_bridge._atomic_publish(
        jobs / f"{request_nonce}.verify.json",
        {"request_nonce": request_nonce, "receipt": receipt, **binding},
    )
    assert (
        host_bridge.process_verification_jobs(
            daemon,
            ledger,
            str(jobs),
            str(receipts),
        )
        == 1
    )
    return json.loads((receipts / f"{request_nonce}.verified.json").read_text())


def test_host_signed_positive_then_persistent_replay_rejected(host):
    key, _daemon, ledger, public, _jobs, _receipts = host
    nonce = "1" * 32
    receipt, binding = _signed_receipt(key, nonce), _binding(nonce)
    result = _process(host, receipt, binding, "2" * 32)
    assert (
        host_bridge.verify_host_response(
            result,
            request_nonce="2" * 32,
            receipt=receipt,
            binding=binding,
            pubkey_path=str(public),
        )
        == VerificationStatus.VERIFIED_BY_ORACLE
    )
    assert ledger.seen(nonce)
    assert attestation.ReplayLedger(ledger.path).seen(nonce)
    replay = _process(host, receipt, binding, "3" * 32)
    assert (
        host_bridge.verify_host_response(
            replay,
            request_nonce="3" * 32,
            receipt=receipt,
            binding=binding,
            pubkey_path=str(public),
        )
        == VerificationStatus.FAILED_CLAIM
    )


@pytest.mark.parametrize(
    "change",
    [
        {"expected_run": "run-B"},
        {"expected_epoch": 2},
        {"expected_action_seq": 1},
        {"expected_nonce": "a" * 32},
        {"expected_experiment_id": "wrong-experiment"},
        {"expected_claim_kind": "place"},
    ],
)
def test_host_rejects_wrong_binding_before_consuming_nonce(host, change):
    key, _daemon, ledger, public, _jobs, _receipts = host
    nonce = "4" * 32
    receipt = _signed_receipt(key, nonce)
    binding = {**_binding(nonce), **change}
    result = _process(host, receipt, binding, "5" * 32)
    assert (
        host_bridge.verify_host_response(
            result,
            request_nonce="5" * 32,
            receipt=receipt,
            binding=binding,
            pubkey_path=str(public),
        )
        == VerificationStatus.FAILED_CLAIM
    )
    assert not ledger.seen(nonce)


def test_host_rejects_forged_receipt_and_client_response(host):
    key, _daemon, ledger, public, _jobs, _receipts = host
    nonce = "6" * 32
    receipt = _signed_receipt(key, nonce)
    forged = dict(receipt, verdict="failure")
    binding = _binding(nonce)
    result = _process(host, forged, binding, "7" * 32)
    assert (
        host_bridge.verify_host_response(
            result,
            request_nonce="7" * 32,
            receipt=forged,
            binding=binding,
            pubkey_path=str(public),
        )
        == VerificationStatus.FAILED_CLAIM
    )
    assert not ledger.seen(nonce)
    original = _process(host, receipt, binding, "8" * 32)
    forged_response = dict(original, status=VerificationStatus.FAILED_CLAIM.value)
    assert (
        host_bridge.verify_host_response(
            forged_response,
            request_nonce="8" * 32,
            receipt=receipt,
            binding=binding,
            pubkey_path=str(public),
        )
        == VerificationStatus.FAILED_CLAIM
    )
    assert (
        host_bridge.verify_host_response(
            original,
            request_nonce="9" * 32,
            receipt=receipt,
            binding=binding,
            pubkey_path=str(public),
        )
        == VerificationStatus.FAILED_CLAIM
    )


def test_host_rejects_untrusted_public_key_and_non_host_uid(host, monkeypatch):
    key, daemon, ledger, public, jobs, receipts = host
    nonce = "a" * 32
    receipt = _signed_receipt(key, nonce)
    binding = _binding(nonce)
    result = _process(host, receipt, binding, "b" * 32)
    monkeypatch.setattr(host_bridge, "_trusted_host_file", lambda *_a, **_kw: False)
    assert (
        host_bridge.verify_host_response(
            result,
            request_nonce="b" * 32,
            receipt=receipt,
            binding=binding,
            pubkey_path=str(public),
        )
        == VerificationStatus.FAILED_CLAIM
    )
    monkeypatch.setattr(os, "getuid", lambda: 501)
    with pytest.raises(attestation.AttestationUnavailableError, match="UID463"):
        host_bridge.process_verification_jobs(daemon, ledger, str(jobs), str(receipts))


def test_verification_client_requires_host_queue(tmp_path):
    with pytest.raises(attestation.AttestationUnavailableError, match="not installed"):
        host_bridge.request_host_verification(
            {},
            expected_run="run-A",
            expected_epoch=1,
            expected_action_seq=0,
            expected_nonce="0" * 32,
            expected_experiment_id="M1-SIM-001",
            jobs_dir=str(tmp_path / "absent"),
            receipts_dir=str(tmp_path / "absent2"),
        )


def test_client_only_accepts_host_signed_response(host, monkeypatch):
    key, daemon, ledger, public, jobs, receipts = host
    nonce = "c" * 32
    receipt = _signed_receipt(key, nonce)
    binding = _binding(nonce)
    monkeypatch.setattr(host_bridge, "PROD_VERIFY_JOBS_DIR", str(jobs))
    monkeypatch.setattr(host_bridge, "PROD_VERIFY_RECEIPTS_DIR", str(receipts))
    monkeypatch.setattr(host_bridge, "_trusted_host_file", lambda *_a, **_kw: True)
    original_pub = host_bridge.PROD_PUBLIC_KEY_PATH
    monkeypatch.setattr(host_bridge, "PROD_PUBLIC_KEY_PATH", str(public))
    assert original_pub == str(public)
    original_publish = host_bridge._atomic_publish

    def publish_then_process(path, obj):
        original_publish(path, obj)
        if path.name.endswith(".verify.json"):
            assert (
                host_bridge.process_verification_jobs(
                    daemon,
                    ledger,
                    str(jobs),
                    str(receipts),
                )
                == 1
            )

    monkeypatch.setattr(host_bridge, "_atomic_publish", publish_then_process)
    result = host_bridge.request_host_verification(
        receipt,
        **binding,
        jobs_dir=str(jobs),
        receipts_dir=str(receipts),
    )
    assert result == VerificationStatus.VERIFIED_BY_ORACLE


def test_real_host_scene_settles_before_grasp_and_place_verdicts(host):
    """A command's terminal state is not a stationary physics observation."""
    _key, daemon, _ledger, _public, _jobs, _receipts = host
    obs = daemon.scene.observe()
    cube = obs["cube"]["pos"]
    tray = obs["tray_pos"]
    seq = 0
    for skill, params in (
        ("move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.07}),
        ("move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.010}),
        ("grasp", {}),
        ("move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.13}),
    ):
        seq += 1
        action = daemon.handle_command(
            {"skill": skill, "params": params}, "run-A", seq, f"{seq:032x}"
        )
        assert action["action_status"]["state"] == "done"
    grasp = daemon.handle_command({"skill": "verify_grasp"}, "run-A", seq, "a" * 32)
    assert grasp["verdict"] == "success"
    assert grasp["evidence"]["oracle_settle_steps"] == 30
    off_target = daemon.handle_command({"skill": "verify_place"}, "run-A", seq, "b" * 32)
    assert off_target["verdict"] == "failure"
    assert off_target["evidence"]["oracle_settle_steps"] == 150
    for skill, params in (
        ("move_to", {"x": tray[0], "y": tray[1], "z": cube[2] + 0.15}),
        ("release", {}),
    ):
        seq += 1
        action = daemon.handle_command(
            {"skill": skill, "params": params}, "run-A", seq, f"{seq:032x}"
        )
        assert action["action_status"]["state"] == "done"
    place = daemon.handle_command({"skill": "verify_place"}, "run-A", seq, "c" * 32)
    assert place["verdict"] == "success"
    assert place["evidence"]["oracle_settle_steps"] == 150


def test_v2_signed_trial_binding_positive_and_replay(host):
    key, legacy, ledger, public, jobs, receipts = host
    trial = {"phase": "smoke", "arm": "B1", "trial_index": 7, "seed": 7}
    daemon = oracle_daemon.build_daemon_from_scene_seed(
        7, "run-A", legacy._key_path, trial=trial)
    v2 = (key, daemon, ledger, public, jobs, receipts)
    nonce = "d" * 32
    core = {k: v for k, v in _signed_receipt(key, nonce).items() if k != "signature"}
    core.update(experiment_id="M1-SIM-002", trial=trial)
    signed = {**core, "signature": key.sign(attestation.canonical(core)).hex()}
    binding = {**_binding(nonce), "expected_experiment_id": "M1-SIM-002",
               "expected_trial": trial}
    result = _process(v2, signed, binding, "e" * 32)
    assert result["trial"] == trial
    assert host_bridge.verify_host_response(
        result, request_nonce="e" * 32, receipt=signed, binding=binding,
        pubkey_path=str(public)) == VerificationStatus.VERIFIED_BY_ORACLE
    assert ledger.seen(nonce)
    replay = _process(v2, signed, binding, "f" * 32)
    assert host_bridge.verify_host_response(
        replay, request_nonce="f" * 32, receipt=signed, binding=binding,
        pubkey_path=str(public)) == VerificationStatus.FAILED_CLAIM


def test_deepseek_experiment_host_signature_cannot_be_reused_as_glm(host):
    key, legacy, ledger, public, jobs, receipts = host
    trial = {"phase": "smoke", "arm": "B2", "trial_index": 5, "seed": 5}
    daemon = oracle_daemon.build_daemon_from_scene_seed(
        5, "run-A", legacy._key_path, trial=trial, experiment_id="M1-SIM-003")
    assert daemon.experiment_id == "M1-SIM-003"
    new_host = (key, daemon, ledger, public, jobs, receipts)
    nonce = "1" * 32
    core = {k: v for k, v in _signed_receipt(key, nonce).items() if k != "signature"}
    core.update(experiment_id="M1-SIM-003", trial=trial)
    signed = {**core, "signature": key.sign(attestation.canonical(core)).hex()}
    wrong = {**_binding(nonce), "expected_experiment_id": "M1-SIM-002",
             "expected_trial": trial}
    rejected = _process(new_host, signed, wrong, "2" * 32)
    assert host_bridge.verify_host_response(
        rejected, request_nonce="2" * 32, receipt=signed, binding=wrong,
        pubkey_path=str(public)) == VerificationStatus.FAILED_CLAIM
    assert not ledger.seen(nonce)
    correct = {**wrong, "expected_experiment_id": "M1-SIM-003"}
    accepted = _process(new_host, signed, correct, "3" * 32)
    assert host_bridge.verify_host_response(
        accepted, request_nonce="3" * 32, receipt=signed, binding=correct,
        pubkey_path=str(public)) == VerificationStatus.VERIFIED_BY_ORACLE
    assert ledger.seen(nonce)


@pytest.mark.parametrize("mutation", ["wrong_arm", "wrong_seed", "forged_receipt"])
def test_v2_trial_tampering_never_consumes_nonce(host, mutation):
    key, legacy, ledger, public, jobs, receipts = host
    trial = {"phase": "smoke", "arm": "B1", "trial_index": 7, "seed": 7}
    daemon = oracle_daemon.build_daemon_from_scene_seed(
        7, "run-A", legacy._key_path, trial=trial)
    v2 = (key, daemon, ledger, public, jobs, receipts)
    nonce = "a" * 32
    core = {k: v for k, v in _signed_receipt(key, nonce).items() if k != "signature"}
    core.update(experiment_id="M1-SIM-002", trial=trial)
    signed = {**core, "signature": key.sign(attestation.canonical(core)).hex()}
    binding = {**_binding(nonce), "expected_experiment_id": "M1-SIM-002",
               "expected_trial": dict(trial)}
    if mutation == "wrong_arm":
        binding["expected_trial"]["arm"] = "B2"
    elif mutation == "wrong_seed":
        binding["expected_trial"]["seed"] = 8
    else:
        signed["trial"] = {**trial, "arm": "B2"}
    result = _process(v2, signed, binding, "b" * 32)
    assert host_bridge.verify_host_response(
        result, request_nonce="b" * 32, receipt=signed, binding=binding,
        pubkey_path=str(public)) == VerificationStatus.FAILED_CLAIM
    assert not ledger.seen(nonce)


def test_v2_host_rejects_missing_trial_binding(host):
    key, legacy, ledger, _public, jobs, receipts = host
    trial = {"phase": "smoke", "arm": "B1", "trial_index": 7, "seed": 7}
    daemon = oracle_daemon.build_daemon_from_scene_seed(
        7, "run-A", legacy._key_path, trial=trial)
    nonce = "c" * 32
    core = {k: v for k, v in _signed_receipt(key, nonce).items() if k != "signature"}
    core.update(experiment_id="M1-SIM-002", trial=trial)
    signed = {**core, "signature": key.sign(attestation.canonical(core)).hex()}
    host_bridge._atomic_publish(jobs / f"{nonce}.verify.json", {
        "request_nonce": nonce, "receipt": signed,
        **{**_binding(nonce), "expected_experiment_id": "M1-SIM-002"},
    })
    assert host_bridge.process_verification_jobs(daemon, ledger, str(jobs), str(receipts)) == 0
    assert not ledger.seen(nonce)


def test_v2_real_physics_claim_signs_seed_arm_and_trial(host):
    key, legacy, ledger, public, jobs, receipts = host
    trial = {"phase": "smoke", "arm": "B2", "trial_index": 7, "seed": 7}
    daemon = oracle_daemon.build_daemon_from_scene_seed(
        7, "run-A", legacy._key_path, trial=trial)
    v2 = (key, daemon, ledger, public, jobs, receipts)
    obs = daemon.handle_command({"skill": "observe"}, "run-A", 0, "1" * 32)
    assert obs["trial"] == trial
    cube = obs["observation"]["cube"]["pos"]
    for seq, (skill, params) in enumerate((
        ("move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.07}),
        ("move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.010}),
        ("grasp", {}),
        ("move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.13}),
    ), 1):
        action = daemon.handle_command({"skill": skill, "params": params},
                                       "run-A", seq, f"{seq + 1:032x}")
        assert action["trial"] == trial
        assert action["action_status"]["state"] == "done"
    nonce = "7" * 32
    signed = daemon.handle_command({"skill": "verify_grasp"}, "run-A", 4, nonce)
    assert signed["verdict"] == "success" and signed["trial"] == trial
    binding = {**_binding(nonce), "expected_experiment_id": "M1-SIM-002",
               "expected_action_seq": 4, "expected_trial": trial}
    forged = {**signed, "trial": {**trial, "arm": "B1"}}
    rejected = _process(v2, forged, binding, "8" * 32)
    assert host_bridge.verify_host_response(
        rejected, request_nonce="8" * 32, receipt=forged, binding=binding,
        pubkey_path=str(public)) == VerificationStatus.FAILED_CLAIM
    assert not ledger.seen(nonce)
    accepted = _process(v2, signed, binding, "9" * 32)
    assert host_bridge.verify_host_response(
        accepted, request_nonce="9" * 32, receipt=signed, binding=binding,
        pubkey_path=str(public)) == VerificationStatus.VERIFIED_BY_ORACLE

"""Gate A L0 contract tests: TTL, epoch, grant revocation, intent idempotency,
stop separation, frozen UNKNOWN ledger, and Oracle fail-closed rejection of
fake success claims.
"""
from __future__ import annotations

import pytest

from llm_loop.embodied_sim import MuJoCoScene
from llm_loop.embodied_sim.contract import (
    ClaimGuard,
    ContractKernel,
    EpochMismatchError,
    FrozenLedger,
    GrantRegistry,
    GrantRevokedError,
    ObservationExpiredError,
    StopNotRequestedError,
    VerificationStatus,
)
from llm_loop.embodied_sim.oracle import ORACLE_EXECUTION, judge_grasp, make_receipt, verify_receipt
from llm_loop.embodied_sim.skills import EmbodiedInterface


def _iface(tmp_path):
    s = MuJoCoScene(seed=7)
    s.step(50)
    return EmbodiedInterface(s, ledger_path=str(tmp_path / "ledger.jsonl"))


def _cube_target(iface):
    cube = iface.observe()["observation"]["cube"]["pos"]
    return {"x": cube[0], "y": cube[1], "z": cube[2] + 0.06}


def test_observation_ttl_expiry_rejected():
    now = [0.0]
    k = ContractKernel(clock=lambda: now[0], observation_ttl_s=1.0)
    ticket = k.issue_observation_ref(1)
    now[0] = 0.999
    assert k.check_observation(ticket, 1) == ticket.ref
    now[0] = 1.0
    with pytest.raises(ObservationExpiredError):
        k.check_observation(ticket, 1)


def test_observation_epoch_mismatch_rejected():
    k = ContractKernel(clock=lambda: 0.0)
    ticket = k.issue_observation_ref(1)
    with pytest.raises(EpochMismatchError):
        k.check_observation(ticket, 2)


def test_grant_revocation_blocks_skill_and_freezes_record(tmp_path):
    iface = _iface(tmp_path)
    with pytest.raises(GrantRevokedError):
        iface.execute_skill("move_to", _cube_target(iface), "k0", 99)
    assert iface.ledger is not None
    rec = iface.ledger.reconcile()
    assert rec["chain_ok"] is True and rec["records"] >= 1


def test_grant_registry_versions_monotonic():
    g = GrantRegistry()
    v1 = g.grant("grasp")
    assert g.check("grasp", v1) is True
    v2 = g.revoke("grasp")
    assert g.check("grasp", v1) is False
    assert g.check("grasp", v2) is False, "revoked grant version must not validate"
    v3 = g.grant("grasp")
    assert v3 == v2 + 1 and g.check("grasp", v3) is True


def test_intent_key_idempotent_no_double_count(tmp_path):
    iface = _iface(tmp_path)
    target = _cube_target(iface)
    r1 = iface.execute_skill("move_to", target, "same-key", 1)
    count = iface.tool_action_count
    r2 = iface.execute_skill("move_to", target, "same-key", 1)
    assert r1["action_id"] == r2["action_id"]
    assert r2.get("idempotent") is True
    assert iface.tool_action_count == count


def test_stop_request_and_confirm_separated(tmp_path):
    iface = _iface(tmp_path)
    with pytest.raises(StopNotRequestedError):
        iface.confirm_stop("stop-999999")
    req = iface.stop("qa stop")
    assert req["state"] == "requested"
    conf = iface.confirm_stop(req["stop_id"])
    assert conf["state"] == "confirmed"
    assert iface.stopper.is_confirmed(req["stop_id"]) is True
    r = iface.execute_skill("move_to", _cube_target(iface), "k-after-stop", 1)
    assert r.get("error") == "STOP_CONFIRMED"


def test_unknown_skill_frozen_and_rejected(tmp_path):
    iface = _iface(tmp_path)
    r = iface.execute_skill("teleport_cube", {}, "kT", 1)
    assert r["error"] == "UNKNOWN_SKILL"
    assert iface.ledger is not None
    rec = iface.ledger.reconcile()
    assert rec["chain_ok"] is True and rec["records"] >= 1


def test_frozen_ledger_detects_tamper(tmp_path):
    led = FrozenLedger(tmp_path / "led.jsonl")
    led.append({"a": 1})
    led.append({"b": 2})
    assert led.reconcile()["chain_ok"] is True
    p = tmp_path / "led.jsonl"
    p.write_text(p.read_text().replace('"a":1', '"a":999'))
    assert led.reconcile()["chain_ok"] is False


def _grasp_snapshot():
    return {
        "t": 1.0,
        "contact_pairs": [["cube_geom", "fingertip_left", 0.0], ["cube_geom", "fingertip_right", 0.0]],
        "cube": {"pos": [0.1, 0.0, 0.06], "vel": [0.0, 0.0, 0.0]},
    }


def test_success_claim_without_receipt_is_failed_claim():
    g = ClaimGuard()
    assert g.evaluate_claim("c1", True, 3) == VerificationStatus.FAILED_CLAIM
    assert g.evaluate_claim("c1", False, 3) == VerificationStatus.UNVERIFIED


def test_oracle_receipt_fail_closed_matrix():
    snap = _grasp_snapshot()
    ok, ev = judge_grasp(snap)
    assert ok is True
    receipt = make_receipt(snap, "grasp", ok, ev, "exp-gate-a", 3)
    assert verify_receipt(receipt, 3, snap) == VerificationStatus.VERIFIED_BY_ORACLE
    # stale epoch
    assert verify_receipt(receipt, 4, snap) == VerificationStatus.FAILED_CLAIM
    # tampered snapshot binding
    snap2 = dict(snap)
    snap2["t"] = 2.0
    assert verify_receipt(receipt, 3, snap2) == VerificationStatus.FAILED_CLAIM
    # missing fields
    broken = {k: v for k, v in receipt.items() if k != "verdict"}
    assert verify_receipt(broken, 3, snap) == VerificationStatus.FAILED_CLAIM
    # registered via ClaimGuard end-to-end
    g = ClaimGuard()
    g.register_receipt("c-ok", receipt)
    assert g.evaluate_claim("c-ok", True, 3) == VerificationStatus.VERIFIED_BY_ORACLE


def test_oracle_independence_marker_remains_honest():
    assert ORACLE_EXECUTION == "in_process_pending_host_uid", (
        "cross-UID oracle execution requires Host-managed acceptance; must not be claimed"
    )

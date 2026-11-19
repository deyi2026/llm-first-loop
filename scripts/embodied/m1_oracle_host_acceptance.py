#!/usr/bin/env python3
"""Real cross-UID Host Oracle acceptance (model-free infrastructure probe).

This does NOT demonstrate autonomous GLM behavior. It requires an installed
UID463 LaunchDaemon, independently signed physics receipt, and Host-owned
one-use verification ledger. No system changes or restarts are performed.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from llm_loop.embodied_sim.attestation import (  # noqa: E402
    PROD_PUBLIC_KEY_PATH,
    PROD_RECEIPTS_DIR,
    AttestationUnavailableError,
    request_attestation,
)
from llm_loop.embodied_sim.contract import VerificationStatus  # noqa: E402
from llm_loop.embodied_sim.host_bridge import request_host_verification  # noqa: E402

RUN_INFO = Path("/private/var/run/lfl-m1-oracle/runtime/run.json")
PRIVATE = Path("/usr/local/etc/lfl-m1-oracle-ed25519.key")
LEDGER = Path("/private/var/db/lfl-m1-oracle/verified-nonces.sqlite3")


def _assert_isolation() -> None:
    if os.getuid() == 0 or os.getuid() == 463:
        raise RuntimeError("acceptance must be a separate unprivileged client UID")
    if RUN_INFO.stat().st_uid != 463:
        raise RuntimeError("run metadata not Host UID463-owned")
    for path in (PRIVATE, LEDGER):
        try:
            path.read_bytes()
        except PermissionError:
            continue
        raise RuntimeError(f"client can read Host secret/ledger: {path}")
    for path in (Path(PROD_RECEIPTS_DIR), Path(PROD_RECEIPTS_DIR).parent / "verify-receipts"):
        temp = path / f".{secrets.token_hex(16)}.client-probe"
        try:
            fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except PermissionError:
            continue
        else:
            os.close(fd)
            temp.unlink()
            raise RuntimeError(f"client can forge Host receipt in: {path}")
    if not Path(PROD_PUBLIC_KEY_PATH).is_file():
        raise RuntimeError("Host public key missing")


def _run_command(command: dict, run_id: str, seq: int) -> tuple[str, dict]:
    nonce, receipt = request_attestation(
        command,
        run_id=run_id,
        action_seq=seq,
        timeout_s=30,
    )
    if receipt.get("oracle_execution") == "daemon_fail_closed":
        raise RuntimeError(f"Host command rejected: {receipt.get('error')}")
    return nonce, receipt


def _verify(receipt: dict, nonce: str, run: dict, seq: int, **overrides: Any):
    binding = {
        "expected_run": run["run_id"],
        "expected_epoch": run["scene_epoch"],
        "expected_action_seq": seq,
        "expected_nonce": nonce,
        "expected_experiment_id": run["experiment_id"],
        "expected_claim_kind": "grasp",
    }
    binding.update(overrides)
    return request_host_verification(receipt, **binding, timeout_s=30)


def run() -> dict:
    _assert_isolation()
    run = json.loads(RUN_INFO.read_text(encoding="utf-8"))
    run_id = run["run_id"]
    if len(run_id) != 32 or run["experiment_id"] != "M1-SIM-001":
        raise RuntimeError("invalid Host run identity")
    _, obs = _run_command({"skill": "observe"}, run_id, 0)
    cube = obs["observation"]["cube"]["pos"]
    seq = 0
    stages = (
        ("move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.07}),
        ("move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.010}),
        ("grasp", {}),
        ("move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.13}),
    )
    for skill, params in stages:
        seq += 1
        _, action = _run_command({"skill": skill, "params": params}, run_id, seq)
        if action.get("action_status", {}).get("state") != "done":
            raise RuntimeError(f"real Host physics stage failed: {skill}: {action}")
    nonce, receipt = _run_command({"skill": "verify_grasp"}, run_id, seq)
    if receipt.get("uid") != 463 or receipt.get("verdict") != "success":
        raise RuntimeError("independent physics Oracle did not confirm grasp")
    # Test binding/forgery before consuming the valid nonce, otherwise replay
    # protection alone could mask a broken binding validator.
    negatives = {}
    negatives["wrong_run"] = _verify(receipt, nonce, run, seq, expected_run="wrong-run")
    negatives["wrong_epoch"] = _verify(receipt, nonce, run, seq, expected_epoch=999)
    negatives["wrong_seq"] = _verify(receipt, nonce, run, seq, expected_action_seq=seq + 1)
    negatives["wrong_nonce"] = _verify(
        receipt, nonce, run, seq, expected_nonce=secrets.token_hex(16)
    )
    negatives["wrong_experiment"] = _verify(
        receipt, nonce, run, seq, expected_experiment_id="wrong-experiment"
    )
    negatives["wrong_claim"] = _verify(receipt, nonce, run, seq, expected_claim_kind="place")
    tampered = dict(receipt, verdict="failure")
    negatives["forged_receipt"] = _verify(tampered, nonce, run, seq)
    if _verify(receipt, nonce, run, seq) != VerificationStatus.VERIFIED_BY_ORACLE:
        raise RuntimeError("Host did not sign/consume positive verification")
    negatives["replay"] = _verify(receipt, nonce, run, seq)

    # A grasped cube is not yet in the tray. A real signed failure must
    # remain FAILED_CLAIM, even when submitted through the Host verifier.
    off_nonce, off_receipt = _run_command({"skill": "verify_place"}, run_id, seq)
    if off_receipt.get("verdict") != "failure":
        raise RuntimeError("off-target place unexpectedly accepted")
    negatives["off_target_place"] = _verify(
        off_receipt, off_nonce, run, seq, expected_claim_kind="place"
    )

    tray = obs["observation"]["tray_pos"]
    for skill, params in (
        ("move_to", {"x": tray[0], "y": tray[1], "z": cube[2] + 0.15}),
        ("release", {}),
    ):
        seq += 1
        _, action = _run_command({"skill": skill, "params": params}, run_id, seq)
        if action.get("action_status", {}).get("state") != "done":
            raise RuntimeError(f"real Host place stage failed: {skill}: {action}")
    place_nonce, place_receipt = _run_command({"skill": "verify_place"}, run_id, seq)
    if place_receipt.get("uid") != 463 or place_receipt.get("verdict") != "success":
        raise RuntimeError("independent physics Oracle did not confirm placement")
    if (
        _verify(place_receipt, place_nonce, run, seq, expected_claim_kind="place")
        != VerificationStatus.VERIFIED_BY_ORACLE
    ):
        raise RuntimeError("Host did not sign/consume positive placement verification")
    negatives["place_replay"] = _verify(
        place_receipt, place_nonce, run, seq, expected_claim_kind="place"
    )
    if any(value != VerificationStatus.FAILED_CLAIM for value in negatives.values()):
        raise RuntimeError(f"Host failed negative binding tests: {negatives}")
    try:
        request_attestation(
            {"skill": "verify_place"},
            run_id=run_id,
            action_seq=seq,
            jobs_dir="/private/var/run/lfl-m1-oracle/absent-jobs",
            receipts_dir="/private/var/run/lfl-m1-oracle/absent-receipts",
        )
    except AttestationUnavailableError:
        negatives["missing_queue"] = VerificationStatus.FAILED_CLAIM
    else:
        raise RuntimeError("missing Host queue did not fail closed")
    return {
        "schema": "lfl.m1-host-cross-uid-acceptance/v1",
        "status": "PASS",
        "client_uid": os.getuid(),
        "host_uid": 463,
        "run_id": run_id,
        "scene_epoch": run["scene_epoch"],
        "action_seq": seq,
        "positive_grasp": VerificationStatus.VERIFIED_BY_ORACLE.value,
        "positive_place": VerificationStatus.VERIFIED_BY_ORACLE.value,
        "negative_tests": {k: v.value for k, v in negatives.items()},
        "model_autonomy": "NOT_TESTED (deterministic infrastructure probe)",
    }


if __name__ == "__main__":
    try:
        print(json.dumps(run(), sort_keys=True, indent=2))
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print("M1_HOST_ACCEPTANCE=NO_GO " + str(exc), file=sys.stderr)
        sys.exit(77)

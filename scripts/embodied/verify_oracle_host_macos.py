"""Real UID-463 fixed-command Host acceptance, with negative tests.

This is an acceptance probe, NOT an Oracle trust-signing channel. It never
claims VERIFIED_BY_ORACLE from a caller-provided snapshot. No provider/robot.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

WORKER = Path("/Library/PrivilegedHelperTools/lfl-oracle-v1/oracle_worker.py")
PROFILE = Path("/Library/PrivilegedHelperTools/lfl-oracle-v1/oracle.sb")
WORKER_SHA = "e83e3d837ca18bf5622f66f954e9c2be7c7b35132afc6f8c060c442e3b8f8f98"
PROFILE_SHA = "b3ed2b80cd5ec6201a8a10627461fc82a2c1e7275d505c0cff1a6f34cc869c76"
FIXED = [
    "/usr/bin/sudo", "-n", "-u", "_lfl_oracle",
    "/usr/bin/sandbox-exec", "-f", str(PROFILE),
    "/usr/bin/python3", "-I", "-S", "-B", str(WORKER),
]


def _run(payload: dict | str, *, args: list[str] | None = None) -> subprocess.CompletedProcess:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(args or FIXED, input=data, text=True, capture_output=True,
                          timeout=12, check=False,
                          env={"PATH": "/usr/bin:/bin", "HOME": "/var/empty"})


def _snapshot(*, weld: bool = True, contact: bool = True,
              tray_contact: bool = False, pos=None) -> dict:
    pairs = ([["cube_geom", "fingertip_left", -0.001],
              ["cube_geom", "fingertip_right", -0.001]]
             if contact else [])
    if tray_contact:
        pairs.append(["cube_geom", "tray_floor", -0.001])
    return {
        "cube": {"pos": pos or [0.1, 0.0, 0.06], "vel": [0.0, 0.0, 0.0]},
        "weld_active": weld,
        "contact_pairs": pairs,
    }


def run() -> dict:
    if sys.platform != "darwin" or os.getuid() == 0:
        raise RuntimeError("NO-GO: macOS non-root caller required")
    for path, digest in ((WORKER, WORKER_SHA), (PROFILE, PROFILE_SHA)):
        if path.is_symlink() or not path.is_file() or path.stat().st_uid != 0:
            raise RuntimeError(f"NO-GO: untrusted Host file: {path}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"NO-GO: Host file digest mismatch: {path}")
    cases = {
        "grasp_positive": {
            "snapshot": _snapshot(), "claim_kind": "grasp",
            "scene_epoch": 3, "experiment_id": "M1-UID463-ACCEPTANCE",
        },
        "grasp_empty": {
            "snapshot": _snapshot(weld=False), "claim_kind": "grasp",
            "scene_epoch": 3, "experiment_id": "M1-UID463-ACCEPTANCE",
        },
        "grasp_forged_weld_without_contact": {
            "snapshot": _snapshot(contact=False), "claim_kind": "grasp",
            "scene_epoch": 3, "experiment_id": "M1-UID463-ACCEPTANCE",
        },
        "place_positive": {
            "snapshot": _snapshot(weld=False, contact=False, tray_contact=True,
                                  pos=[0.0, 0.18, 0.04]),
            "claim_kind": "place", "tray_pos": [0.0, 0.18, 0.01],
            "scene_epoch": 3, "experiment_id": "M1-UID463-ACCEPTANCE",
        },
        "place_held_above_tray": {
            "snapshot": _snapshot(weld=True, contact=True,
                                  pos=[0.0, 0.18, 0.077]),
            "claim_kind": "place", "tray_pos": [0.0, 0.18, 0.01],
            "scene_epoch": 3, "experiment_id": "M1-UID463-ACCEPTANCE",
        },
        "place_hover_without_contact": {
            "snapshot": _snapshot(weld=False, contact=False,
                                  pos=[0.0, 0.18, 0.04]),
            "claim_kind": "place", "tray_pos": [0.0, 0.18, 0.01],
            "scene_epoch": 3, "experiment_id": "M1-UID463-ACCEPTANCE",
        },
        "place_off_target": {
            "snapshot": _snapshot(weld=False, contact=False, tray_contact=True),
            "claim_kind": "place", "tray_pos": [0.0, 0.18, 0.01],
            "scene_epoch": 3, "experiment_id": "M1-UID463-ACCEPTANCE",
        },
    }
    outcomes = {}
    for name, payload in cases.items():
        proc = _run(payload)
        if proc.returncode != 0:
            raise RuntimeError(f"NO-GO: {name} worker exit {proc.returncode}: {proc.stderr[:150]}")
        receipt = json.loads(proc.stdout)
        expected = name.endswith("positive")
        if ((receipt.get("verdict") == "success") != expected
                or receipt.get("oracle_uid") != 463
                or receipt.get("oracle_gid") != 463
                or receipt.get("oracle_execution") != "oracle_worker_stdin"
                or receipt.get("host_acceptance") != "NOT_ISSUED"):
            raise RuntimeError(f"NO-GO: {name} wrong verdict/UID/acceptance")
        outcomes[name] = {"pass": True, "verdict": receipt["verdict"], "uid": 463}
    invalid = _run("{not-json")
    if invalid.returncode != 2 or json.loads(invalid.stdout).get("verdict") != "failure":
        raise RuntimeError("NO-GO: malformed input not rejected")
    outcomes["malformed_json_rejected"] = True
    oversized = _run(" " * 65537)
    if oversized.returncode != 2:
        raise RuntimeError("NO-GO: oversized input not rejected")
    outcomes["oversized_input_rejected"] = True

    unauthorized = {
        "arbitrary_command": ["/usr/bin/sudo", "-n", "-u", "_lfl_oracle", "/usr/bin/id", "-u"],
        "extra_worker_arg": FIXED + ["--help"],
        "root_command": ["/usr/bin/sudo", "-n", "-u", "root", "/usr/bin/id", "-u"],
    }
    for name, cmd in unauthorized.items():
        proc = _run("", args=cmd)
        if proc.returncode == 0:
            raise RuntimeError(f"NO-GO: unauthorized command accepted: {name}")
        outcomes[name + "_denied"] = True

    # Caller-controlled receipts are never upgraded to independent acceptance.
    from llm_loop.embodied_sim.contract import VerificationStatus
    from llm_loop.embodied_sim.oracle import verify_receipt
    receipt = json.loads(_run(cases["grasp_positive"]).stdout)
    if verify_receipt(receipt, 3, cases["grasp_positive"]["snapshot"]) != VerificationStatus.PENDING_ORACLE:
        raise RuntimeError("NO-GO: caller-provided receipt was trusted")
    outcomes["no_self_promotion"] = True
    return {
        "schema": "lfl.embodied.m1-host-uid463-acceptance/v1",
        "status": "PASS",
        "worker_sha256": WORKER_SHA,
        "profile_sha256": PROFILE_SHA,
        "tests": outcomes,
        "host_trust_signer": "NOT_INSTALLED",
        "oracle_verification_status": "PENDING_ORACLE",
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))

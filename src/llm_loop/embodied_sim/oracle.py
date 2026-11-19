"""Independent Oracle for M1: privileged-truth judgments that never enter the model context.

Fail-closed everywhere: missing/malformed/stale receipts are never VERIFIED.

Isolation note: in-process module separation now; real cross-UID execution
(unprivileged uid 463) requires Host-managed acceptance and is NOT faked here
(ORACLE_EXECUTION stays "in_process_pending_host_uid").
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from llm_loop.embodied_sim.contract import VerificationStatus, verify_receipt_fields

ORACLE_IMPL = "embodied-m1-oracle-local-v0"
ORACLE_EXECUTION = "in_process_pending_host_uid"  # uid 463 cross-UID run: awaiting Host acceptance

_CUBE_GEOM = "cube_geom"
_FTIP_L = "fingertip_left"
_FTIP_R = "fingertip_right"


def _contact_set(snapshot: dict[str, Any]) -> set[frozenset[str]]:
    out: set[frozenset[str]] = set()
    for g1, g2, _dist in snapshot.get("contact_pairs", []):
        out.add(frozenset((g1, g2)))
    return out


def judge_grasp(snapshot: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Grasp truth: both fingertips contact the cube, cube lifted, quasi-static."""
    contacts = _contact_set(snapshot)
    cube = snapshot.get("cube", {})
    pos = cube.get("pos", [0, 0, 0])
    vel = cube.get("vel", [0, 0, 0])
    speed = float(sum(v * v for v in vel)) ** 0.5
    both_fingers = frozenset((_CUBE_GEOM, _FTIP_L)) in contacts and frozenset((_CUBE_GEOM, _FTIP_R)) in contacts
    lifted = float(pos[2]) > 0.05
    ok = bool(both_fingers and lifted and speed < 0.08)
    return ok, {
        "both_fingertips_contacting": both_fingers,
        "cube_z": float(pos[2]),
        "cube_speed": speed,
        "n_contacts": len(snapshot.get("contact_pairs", [])),
    }


def judge_place(snapshot: dict[str, Any], tray_pos: list[float]) -> tuple[bool, dict[str, Any]]:
    """Place truth: cube resting inside tray footprint, near tray height, quasi-static."""
    cube = snapshot.get("cube", {})
    pos = cube.get("pos", [0, 0, 0])
    vel = cube.get("vel", [0, 0, 0])
    speed = float(sum(v * v for v in vel)) ** 0.5
    inside = (abs(float(pos[0]) - float(tray_pos[0])) < 0.055
              and abs(float(pos[1]) - float(tray_pos[1])) < 0.055)
    height_ok = 0.015 <= float(pos[2]) <= 0.09
    ok = bool(inside and height_ok and speed < 0.06)
    return ok, {
        "inside_tray_xy": inside,
        "height_ok": height_ok,
        "cube_speed": speed,
        "cube_z": float(pos[2]),
    }


def make_receipt(snapshot: dict[str, Any], claim_kind: str, verdict: bool,
                 evidence: dict[str, Any], experiment_id: str, scene_epoch: int) -> dict[str, Any]:
    snap_sha = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "oracle_impl": ORACLE_IMPL,
        "oracle_execution": ORACLE_EXECUTION,
        "experiment_id": experiment_id,
        "claim_kind": claim_kind,
        "scene_epoch": int(scene_epoch),
        "verdict": "success" if verdict else "failure",
        "snapshot_sha256": snap_sha,
        "evidence": evidence,
    }


def verify_receipt(receipt: dict[str, Any], expected_scene_epoch: int,
                   snapshot: dict[str, Any] | None = None) -> VerificationStatus:
    """Fail-closed verification; optionally binds receipt to a live snapshot."""
    status = verify_receipt_fields(receipt, expected_scene_epoch)
    if status is not VerificationStatus.VERIFIED_BY_ORACLE:
        return status
    if snapshot is not None:
        snap_sha = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if snap_sha != receipt.get("snapshot_sha256"):
            return VerificationStatus.FAILED_CLAIM
    return VerificationStatus.VERIFIED_BY_ORACLE

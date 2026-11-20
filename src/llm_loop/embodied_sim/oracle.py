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
    """Grasp truth (disclosed mechanism): weld constraint active AND real
    fingertip-cube contact present AND cube lifted quasi-statically. The weld
    is only ever activated by the skills layer after confirmed physical
    contact; Oracle re-checks the privileged state independently."""
    contacts = _contact_set(snapshot)
    cube = snapshot.get("cube", {})
    pos = cube.get("pos", [0, 0, 0])
    vel = cube.get("vel", [0, 0, 0])
    speed = float(sum(v * v for v in vel)) ** 0.5
    weld = bool(snapshot.get("weld_active", False))
    tips = {frozenset((_CUBE_GEOM, _FTIP_L)), frozenset((_CUBE_GEOM, _FTIP_R))}
    touching = any(c in tips for c in contacts)
    lifted = float(pos[2]) > 0.05
    ok = bool(weld and touching and lifted and speed < 0.08)
    return ok, {
        "grasp_mechanism": "contact_confirmed_weld",
        "weld_active": weld,
        "fingertips_contacting": touching,
        "lifted": lifted,
        "cube_z": float(pos[2]),
        "cube_speed": speed,
    }


def judge_place(snapshot: dict[str, Any], tray_pos: list[float]) -> tuple[bool, dict[str, Any]]:
    """Place truth: cube resting inside tray footprint, near tray height, quasi-static."""
    cube = snapshot.get("cube", {})
    pos = cube.get("pos", [0, 0, 0])
    vel = cube.get("vel", [0, 0, 0])
    speed = float(sum(v * v for v in vel)) ** 0.5
    inside = (abs(float(pos[0]) - float(tray_pos[0])) < 0.055
              and abs(float(pos[1]) - float(tray_pos[1])) < 0.055)
    # Tray floor top is 0.01 m above tray body origin; the 0.02 m cube
    # half-size puts a resting cube centre ~0.03 m above that origin.
    # Geometric overlap alone is not placement: the gripper must have
    # released and the cube must physically contact the tray floor.
    height_ok = 0.025 <= float(pos[2]) - float(tray_pos[2]) <= 0.045
    released = not bool(snapshot.get("weld_active", True))
    tray_contact = frozenset((_CUBE_GEOM, "tray_floor")) in _contact_set(snapshot)
    ok = bool(inside and height_ok and released and tray_contact and speed < 0.06)
    return ok, {
        "inside_tray_xy": inside,
        "height_ok": height_ok,
        "released": released,
        "tray_contact": tray_contact,
        "cube_speed": speed,
        "cube_z": float(pos[2]),
    }


def make_receipt(snapshot: dict[str, Any], claim_kind: str, verdict: bool,
                 evidence: dict[str, Any], experiment_id: str, scene_epoch: int, *,
                 goal_binding: dict[str, Any] | None = None) -> dict[str, Any]:
    snap_sha = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    receipt = {
        "oracle_impl": ORACLE_IMPL,
        "oracle_execution": ORACLE_EXECUTION,
        "experiment_id": experiment_id,
        "claim_kind": claim_kind,
        "scene_epoch": int(scene_epoch),
        "verdict": "success" if verdict else "failure",
        "snapshot_sha256": snap_sha,
        "evidence": evidence,
    }
    if goal_binding is not None:
        receipt["goal"] = dict(goal_binding)
    return receipt


def verify_receipt(receipt: dict[str, Any], expected_scene_epoch: int,
                   snapshot: dict[str, Any] | None = None, *,
                   expected_goal_digest: str | None = None) -> VerificationStatus:
    """Fail-closed verification; optionally binds receipt to a live snapshot.

    Severity order: integrity violations (missing fields, stale epoch, tampered
    binding) are FAILED_CLAIM and trump everything; only integrity-clean receipts
    resolve to PENDING_ORACLE (in-process oracle) or VERIFIED_BY_ORACLE
    (Host-managed independent channel).
    """
    status = verify_receipt_fields(receipt, expected_scene_epoch,
                                   expected_goal_digest=expected_goal_digest)
    if snapshot is not None and status is not VerificationStatus.FAILED_CLAIM:
        snap_sha = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if snap_sha != receipt.get("snapshot_sha256"):
            return VerificationStatus.FAILED_CLAIM
    return status

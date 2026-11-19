#!/usr/bin/python3
"""Frozen, stdlib-only Oracle worker for a root-owned macOS UID-463 installation.

Runs under /usr/bin/python3 -I -S -B and a fixed Seatbelt profile. Reads one
bounded JSON snapshot from stdin; writes one JSON receipt to stdout. No file,
network, shell, provider or robot APIs. Its output is PENDING_ORACLE until a
separate Host verifier proves snapshot provenance and signs acceptance.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import resource
import sys

ORACLE_UID = 463
MAX_INPUT_BYTES = 65536
ORACLE_EXECUTION = "oracle_worker_stdin"
ORACLE_IMPL = "embodied-m1-host-oracle-v1"


def _vec3(value: object, label: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(label + ": expected 3-vector")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in value):
        raise ValueError(label + ": nonnumeric coordinate")
    result = tuple(float(x) for x in value)
    if not all(math.isfinite(x) for x in result):
        raise ValueError(label + ": nonfinite coordinate")
    return result  # type: ignore[return-value]


def _snapshot(payload: object) -> tuple[dict, str, int, str]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be object")
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be object")
    cube = snapshot.get("cube")
    if not isinstance(cube, dict):
        raise ValueError("cube must be object")
    _vec3(cube.get("pos"), "cube.pos")
    _vec3(cube.get("vel"), "cube.vel")
    pairs = snapshot.get("contact_pairs")
    if not isinstance(pairs, list) or len(pairs) > 128:
        raise ValueError("invalid contact pairs")
    for pair in pairs:
        if (not isinstance(pair, list) or len(pair) != 3
                or not all(isinstance(x, str) and len(x) <= 64 for x in pair[:2])
                or isinstance(pair[2], bool)
                or not isinstance(pair[2], (int, float))
                or not math.isfinite(float(pair[2]))):
            raise ValueError("invalid contact pair")
    if not isinstance(snapshot.get("weld_active"), bool):
        raise ValueError("weld_active must be boolean")
    kind = payload.get("claim_kind")
    if kind not in ("grasp", "place"):
        raise ValueError("unsupported claim_kind")
    epoch = payload.get("scene_epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
        raise ValueError("invalid scene_epoch")
    experiment = payload.get("experiment_id")
    if (not isinstance(experiment, str) or not 1 <= len(experiment) <= 80
            or any(ord(c) < 32 for c in experiment)):
        raise ValueError("invalid experiment_id")
    if kind == "place":
        _vec3(payload.get("tray_pos"), "tray_pos")
    return snapshot, kind, epoch, experiment


def _judge(snapshot: dict, kind: str, payload: dict) -> tuple[bool, dict]:
    cube = snapshot["cube"]
    pos = _vec3(cube["pos"], "cube.pos")
    vel = _vec3(cube["vel"], "cube.vel")
    speed = math.sqrt(sum(v * v for v in vel))
    if kind == "grasp":
        contacts = {frozenset((a, b)) for a, b, _ in snapshot["contact_pairs"]}
        tips = {
            frozenset(("cube_geom", "fingertip_left")),
            frozenset(("cube_geom", "fingertip_right")),
        }
        touching = bool(contacts & tips)
        lifted = pos[2] > 0.05
        weld = snapshot["weld_active"]
        # Host judgement is intentionally stricter than the in-process
        # diagnostic: a forged weld flag without fingertip contact cannot pass.
        ok = weld and touching and lifted and speed < 0.08
        return ok, {
            "grasp_mechanism": "contact_confirmed_weld",
            "weld_active": weld,
            "fingertips_contacting": touching,
            "lifted": lifted,
            "cube_z": pos[2],
            "cube_speed": speed,
        }
    tray = _vec3(payload["tray_pos"], "tray_pos")
    inside = abs(pos[0] - tray[0]) < 0.055 and abs(pos[1] - tray[1]) < 0.055
    height_ok = 0.015 <= pos[2] <= 0.09
    ok = inside and height_ok and speed < 0.06
    return ok, {
        "inside_tray_xy": inside,
        "height_ok": height_ok,
        "cube_speed": speed,
        "cube_z": pos[2],
    }


def judge_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload must be object")
    snapshot, kind, epoch, experiment = _snapshot(payload)
    ok, evidence = _judge(snapshot, kind, payload)
    digest = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False)
        .encode("utf-8")
    ).hexdigest()
    return {
        "oracle_impl": ORACLE_IMPL,
        "oracle_execution": ORACLE_EXECUTION,
        "experiment_id": experiment,
        "claim_kind": kind,
        "scene_epoch": epoch,
        "verdict": "success" if ok else "failure",
        "snapshot_sha256": digest,
        "evidence": evidence,
        "oracle_uid": os.getuid(),
        "oracle_gid": os.getgid(),
        "host_acceptance": "NOT_ISSUED",
    }


def main() -> int:
    if len(sys.argv) != 1 or os.getuid() != ORACLE_UID or os.geteuid() != ORACLE_UID:
        print(json.dumps({"oracle_execution": ORACLE_EXECUTION,
                          "verdict": "failure", "error": "uid_or_argv_rejected"}))
        return 77
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if not raw or len(raw) > MAX_INPUT_BYTES:
            raise ValueError("invalid input size")
        payload = json.loads(raw.decode("utf-8"),
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        receipt = judge_payload(payload)
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError,
            UnicodeError) as exc:
        print(json.dumps({"oracle_execution": ORACLE_EXECUTION,
                          "verdict": "failure", "error": type(exc).__name__}))
        return 2
    print(json.dumps(receipt, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

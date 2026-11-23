#!/usr/bin/env python
"""Gate B evidence: deterministic grasp-lift-place E2E + L3 failure recovery.

Mechanism disclosure: contact_confirmed_weld (real closure contact gates weld
activation; cube motion always via mj_step constraint solving). Oracle verdicts
are measured and recorded honestly; privileged truth stays out of observations.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from llm_loop.embodied_sim import MuJoCoScene  # noqa: E402
from llm_loop.embodied_sim.oracle import (  # noqa: E402
    judge_grasp,
    judge_place,
    make_receipt,
    verify_receipt,
)
from llm_loop.embodied_sim.skills import GRASP_MECHANISM, EmbodiedInterface  # noqa: E402

OUT = ROOT / "experiments" / "embodied" / "m1" / "gate_b" / "e2e_report.json"


def _run(iface, name, params, key):
    r = iface.execute_skill(name, params, key, 1)
    if "action_id" not in r:
        return r
    aid = r["action_id"]
    while iface.get_action_status(aid)["state"] == "running":
        iface.advance(60)
    return iface.get_action_status(aid)


def main() -> int:
    started = time.time()
    report: dict[str, Any] = {"probe": "m1-gate-b-e2e", "mechanism": GRASP_MECHANISM,
                              "seed": 7, "started_at": started}

    s = MuJoCoScene(seed=7)
    s.step(100)
    iface = EmbodiedInterface(s, ledger_path=str(ROOT / "experiments/embodied/m1/gate_b/ledger.jsonl"))
    cube = iface.observe()["observation"]["cube"]["pos"]

    report["trace"] = {
        "above": _run(iface, "move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.07}, "e1"),
        "down": _run(iface, "move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.010}, "e2"),
    }
    g = _run(iface, "grasp", {}, "e3")
    report["trace"]["grasp"] = g

    max_step = 0.0
    for _ in range(240):
        prev = np.array(s.data.qpos[s._cube_qadr:s._cube_qadr + 3], copy=True)
        s.step(1)
        max_step = max(max_step, float(np.linalg.norm(s.data.qpos[s._cube_qadr:s._cube_qadr + 3] - prev)))
    report["weld_lift_max_single_step_m"] = round(max_step, 6)

    _run(iface, "move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.13}, "e4")
    s.step(30)
    snap = s.oracle_snapshot()
    ok, ev = judge_grasp(snap)
    # Local geometry verdict may be true; independent verification stays PENDING
    # until the Host-managed UID-463 oracle channel issues an acceptance block.
    rv = verify_receipt(make_receipt(snap, "grasp", ok, ev, "m1-sim-gateb-001", s.scene_epoch),
                        s.scene_epoch, snap)
    report["oracle_grasp"] = {"local_geometry_ok": ok, "evidence": ev,
                              "independent_verification": rv.name}

    tray = iface.observe()["observation"]["tray_pos"]
    report["trace"]["to_tray"] = _run(iface, "move_to", {"x": tray[0], "y": tray[1], "z": cube[2] + 0.15}, "e5")
    report["trace"]["release"] = _run(iface, "release", {}, "e6")
    s.step(150)
    final = iface.observe()["observation"]["cube"]["pos"]
    okp, evp = judge_place(s.oracle_snapshot(), tray)
    report["oracle_place"] = {"ok": okp, "evidence": evp, "final_cube": [round(v, 4) for v in final]}

    # L3: honest failure at an empty offset point, then open-gripper recovery
    s2 = MuJoCoScene(seed=7)
    s2.step(100)
    iface2 = EmbodiedInterface(s2, ledger_path=str(ROOT / "experiments/embodied/m1/gate_b/ledger_l3.jsonl"))
    c0 = iface2.observe()["observation"]["cube"]["pos"]
    l3: dict[str, Any] = {}
    l3["approach_empty"] = _run(iface2, "move_to", {"x": c0[0] + 0.03, "y": c0[1] + 0.06, "z": c0[2] + 0.06}, "l1")
    l3["grasp_empty"] = _run(iface2, "grasp", {}, "l2")
    l3["weld_after_failed_grasp"] = s2.weld_active()
    l3["release"] = _run(iface2, "release", {}, "l3")
    c1 = iface2.observe()["observation"]["cube"]["pos"]
    l3["re_approach_above"] = _run(iface2, "move_to", {"x": c1[0], "y": c1[1], "z": c1[2] + 0.07}, "l4")
    l3["re_approach_down"] = _run(iface2, "move_to", {"x": c1[0], "y": c1[1], "z": c1[2] + 0.010}, "l5")
    l3["re_grasp"] = _run(iface2, "grasp", {}, "l6")
    l3["re_lift"] = _run(iface2, "move_to", {"x": c1[0], "y": c1[1], "z": c1[2] + 0.13}, "l7")
    s2.step(30)
    ok2, ev2 = judge_grasp(s2.oracle_snapshot())
    l3["oracle_grasp_after_recovery"] = {"ok": ok2, "evidence": ev2}
    report["l3_recovery"] = l3
    report["tool_action_count_main"] = iface.tool_action_count
    report["tool_action_count_l3"] = iface2.tool_action_count
    assert iface.ledger is not None
    report["ledger_reconcile"] = iface.ledger.reconcile()
    report["oracle_execution"] = "in_process_pending_host_uid"
    report["elapsed_s"] = round(time.time() - started, 3)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "oracle_grasp", "oracle_place", "weld_lift_max_single_step_m",
        "l3_recovery", "oracle_execution")}, indent=2, sort_keys=True))
    core = (report["oracle_grasp"]["local_geometry_ok"] and report["oracle_place"]["ok"]
            and report["weld_lift_max_single_step_m"] < 0.02
            and l3["grasp_empty"]["state"] == "failed"
            and l3["oracle_grasp_after_recovery"]["ok"])
    return 0 if core else 1


if __name__ == "__main__":
    sys.exit(main())

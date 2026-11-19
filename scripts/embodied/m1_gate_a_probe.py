#!/usr/bin/env python
"""M1 Gate A probe: real MuJoCo physics evidence, deterministic seeds, honest verdicts.

Writes experiments/embodied/m1/gate_a/physics_probe.json. No network, no hardware,
no privileged-truth leakage into observations. Grasp/place verdicts are recorded
as measured (pass or fail); Gate A acceptance does not require grasp success.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import mujoco as _mujoco_impl  # noqa: E402

from llm_loop.embodied_sim import MuJoCoScene  # noqa: E402
from llm_loop.embodied_sim.oracle import judge_grasp, judge_place  # noqa: E402

mujoco: Any = _mujoco_impl
from llm_loop.embodied_sim.skills import EmbodiedInterface  # noqa: E402

OUT = ROOT / "experiments" / "embodied" / "m1" / "gate_a" / "physics_probe.json"


def main() -> int:
    started = time.time()
    report: dict[str, object] = {
        "probe": "m1-gate-a-physics",
        "mujoco_version": mujoco.__version__,
        "python": sys.version.split()[0],
        "started_at": started,
    }

    # 1. deterministic seeds
    s1 = MuJoCoScene(seed=42)
    s2 = MuJoCoScene(seed=42)
    s3 = MuJoCoScene(seed=43)
    report["seed_determinism"] = {
        "same_seed_digest_equal": s1.state_digest() == s2.state_digest(),
        "diff_seed_digest_differs": s1.state_digest() != s3.state_digest(),
    }

    # 2. free fall: real gravity changes state with zero control (vz sampled mid-fall)
    s = MuJoCoScene(seed=1)
    ca = s._cube_qadr  # white-box physical initial condition (not a teleport API on skills layer)
    s.data.qpos[ca + 0] = 0.45  # physically isolated: outside arm envelope (x<=0.35) and away from tray
    s.data.qpos[ca + 1] = 0.45
    s.data.qpos[ca + 2] = 0.15
    mujoco.mj_forward(s.model, s.data)
    z0 = float(s.data.qpos[ca + 2])
    t0 = float(s.data.time)
    s.step(40)  # 0.08 s of true free fall => ~31 mm drop under g=9.81
    z1 = float(s.data.qpos[ca + 2])
    vz = float(s.data.qvel[ca + 2])
    contacts_midfall = 0  # count ONLY cube-involving contact pairs, not scene background
    for i in range(s.data.ncon):
        c = s.data.contact[i]
        g1 = mujoco.mj_id2name(s.model, mujoco.mjtObj.mjOBJ_GEOM, int(c.geom1))
        g2 = mujoco.mj_id2name(s.model, mujoco.mjtObj.mjOBJ_GEOM, int(c.geom2))
        if "cube_geom" in (g1, g2):
            contacts_midfall += 1
    s.step(80)
    report["free_fall"] = {
        "z0": z0, "z1": z1, "fell": z1 < z0 - 0.02,
        "vz_strictly_negative": vz < -0.1,
        "sim_time_advanced": float(s.data.time) > t0,
        "cube_contacts_midfall": contacts_midfall,
        "isolated_no_contacts": contacts_midfall == 0,
    }

    # 3. thin skills end-to-end attempt; verdicts measured honestly
    s = MuJoCoScene(seed=7)
    s.step(100)
    iface = EmbodiedInterface(s, ledger_path=str(ROOT / "experiments/embodied/m1/gate_a/smoke_ledger.jsonl"))
    cube = iface.observe()["observation"]["cube"]["pos"]

    def run(name, params, key):
        r = iface.execute_skill(name, params, key, 1)
        if "action_id" not in r:
            return r
        aid = r["action_id"]
        while iface.get_action_status(aid)["state"] == "running":
            iface.advance(60)
        return iface.get_action_status(aid)

    st1 = run("move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.06}, "p1")
    st2 = run("move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.010}, "p2")
    st3 = run("grasp", {}, "p3")
    st4 = run("move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.13}, "p4")
    s.step(50)
    grasp_ok, grasp_ev = judge_grasp(s.oracle_snapshot())
    tray = iface.observe()["observation"]["tray_pos"]
    st5 = run("move_to", {"x": tray[0], "y": tray[1], "z": cube[2] + 0.14}, "p5")
    st6 = run("release", {}, "p6")
    s.step(150)
    place_ok, place_ev = judge_place(s.oracle_snapshot(), tray)

    report["skill_trace"] = {
        "move_above": st1["state"], "move_to_cube": st2["state"],
        "grasp": st3["state"], "lift": st4["state"],
        "move_to_tray": st5["state"], "release": st6["state"],
    }
    report["skill_errors_m"] = {
        "move_above": st1.get("last_err_m"), "move_to_cube": st2.get("last_err_m"),
        "lift": st4.get("last_err_m"), "move_to_tray": st5.get("last_err_m"),
    }
    report["oracle_verdicts_measured"] = {  # honest: may be failure at Gate A
        "grasp": {"ok": grasp_ok, "evidence": grasp_ev},
        "place": {"ok": place_ok, "evidence": place_ev},
        "oracle_execution": "in_process_pending_host_uid",
    }
    report["tool_action_count"] = iface.tool_action_count
    assert iface.ledger is not None
    report["ledger_reconcile"] = iface.ledger.reconcile()
    report["elapsed_s"] = round(time.time() - started, 3)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    core = (report["seed_determinism"]["same_seed_digest_equal"]
            and report["seed_determinism"]["diff_seed_digest_differs"]
            and report["free_fall"]["fell"] and report["free_fall"]["vz_strictly_negative"]
            and report["free_fall"]["isolated_no_contacts"])
    return 0 if core else 1


if __name__ == "__main__":
    sys.exit(main())

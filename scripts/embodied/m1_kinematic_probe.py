#!/usr/bin/env python
"""Read-only kinematic/diagnostic probe (no teleport API, no file writes).

1. Pure kinematics: solve IK for the approach_down target and report the
   forward-kinematics residual of that joint solution (no physics stepping).
2. Optional --dynamic: replicate the independent Host QA diagnostic (600-step
   descent with contact counting), reporting wrist_rod<->cube and
   wrist_rod<->floor step counts. Diagnostic only - never counted as task
   success; the cube is NEVER relocated or teleported here.

Usage: data/.venv-m1/bin/python scripts/embodied/m1_kinematic_probe.py [--dynamic] [--seed 7]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import mujoco as _mujoco_impl  # noqa: E402

mujoco: Any = _mujoco_impl  # C-extension boundary facade

from llm_loop.embodied_sim import MuJoCoScene, solve_ik_site  # noqa: E402


def kinematic_residual(seed: int) -> dict[str, Any]:
    s = MuJoCoScene(seed=seed)
    s.step(100)
    obs = s.observe()
    cube = obs["cube"]["pos"]
    target = (cube[0], cube[1], cube[2] + 0.010)
    qt = solve_ik_site(s.model, obs["arm_qpos"], target)
    probe = mujoco.MjData(s.model)
    for jid, name in enumerate(("shoulder_pan", "shoulder_lift", "elbow", "wrist_roll")):
        j = mujoco.mj_name2id(s.model, mujoco.mjtObj.mjOBJ_JOINT, name)
        probe.qpos[s.model.jnt_qposadr[j]] = qt[jid]
    mujoco.mj_forward(s.model, probe)
    site = mujoco.mj_name2id(s.model, mujoco.mjtObj.mjOBJ_SITE, "tool_site")
    err = float(sum((a - b) ** 2 for a, b in zip(probe.site_xpos[site], target, strict=True)) ** 0.5)
    return {"target": [round(v, 6) for v in target], "q_target": [round(v, 4) for v in qt],
            "fk_residual_m": round(err, 6),
            "note": "pure kinematics via isolated MjData; live scene untouched"}


def dynamic_descent_diagnostic(seed: int, steps: int = 600) -> dict[str, Any]:
    """Contact-counting descent (diagnostic; NOT task execution, NOT success)."""
    s = MuJoCoScene(seed=seed)
    s.step(100)
    obs = s.observe()
    cube = obs["cube"]["pos"]
    qt = solve_ik_site(s.model, obs["arm_qpos"], (cube[0], cube[1], cube[2] + 0.010))
    for i, act in enumerate(("a_shoulder_pan", "a_shoulder_lift", "a_elbow", "a_wrist_roll")):
        s.set_ctrl({act: qt[i]})
    rod_cube = 0
    rod_floor = 0
    for _ in range(steps):
        s.step(1)
        for i in range(s.data.ncon):
            c = s.data.contact[i]
            g1 = mujoco.mj_id2name(s.model, mujoco.mjtObj.mjOBJ_GEOM, int(c.geom1))
            g2 = mujoco.mj_id2name(s.model, mujoco.mjtObj.mjOBJ_GEOM, int(c.geom2))
            pair = {str(g1), str(g2)}
            if "wrist_rod" in pair and "cube_geom" in pair:
                rod_cube += 1
            if "wrist_rod" in pair and "floor" in pair:
                rod_floor += 1
    o = s.observe()
    err = float(sum((a - b) ** 2 for a, b in zip(o["tool_pos"], (cube[0], cube[1], cube[2] + 0.010), strict=True)) ** 0.5)
    return {"steps": steps, "wrist_rod_cube_contact_steps": rod_cube,
            "wrist_rod_floor_contact_steps": rod_floor, "final_tool_err_m": round(err, 6),
            "disclaimer": "diagnostic contact counting; never a task-success claim"}


def main() -> int:
    seed = 7
    dynamic = False
    args = list(sys.argv[1:])
    while args:
        a = args.pop(0)
        if a == "--dynamic":
            dynamic = True
        elif a == "--seed":
            seed = int(args.pop(0))
    report: dict[str, Any] = {"probe": "m1-kinematic-diagnostic", "seed": seed,
                              "kinematic": kinematic_residual(seed)}
    if dynamic:
        report["dynamic_descent"] = dynamic_descent_diagnostic(seed)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

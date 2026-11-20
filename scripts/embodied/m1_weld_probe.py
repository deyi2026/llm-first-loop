#!/usr/bin/env python
"""Decisive layout probe for mjEQ_WELD eq_data in mujoco 4.0.1.

Tries candidate layouts for [anchor3, relpose...] and reports which keeps the
cube glued to the gripper (dist stays ~initial, no per-step jump) under lift.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import mujoco as _mujoco_impl  # noqa: E402

mujoco: Any = _mujoco_impl

from llm_loop.embodied_sim import MuJoCoScene, solve_ik_site  # noqa: E402

ARM = (("shoulder_pan", "a_shoulder_pan"), ("shoulder_lift", "a_shoulder_lift"),
       ("elbow", "a_elbow"), ("wrist_roll", "a_wrist_roll"))


def apply_q(s: MuJoCoScene, qt: list[float]) -> None:
    for i, (_, act) in enumerate(ARM):
        s.set_ctrl({act: qt[i]})


def settle_to_cube(s: MuJoCoScene):
    s.step(100)
    obs = s.observe()
    cube = obs["cube"]["pos"]
    apply_q(s, solve_ik_site(s.model, obs["arm_qpos"], (cube[0], cube[1], cube[2] + 0.010)))
    for _ in range(300):
        s.step(1)
    s.set_ctrl({"a_finger_left": 0.041, "a_finger_right": 0.041})
    for _ in range(120):
        s.step(1)
    return s.observe()


def relpose_wrt(model, data, b2: str, b1: str):
    i1 = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, b1)
    i2 = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, b2)
    p1, p2 = data.xpos[i1], data.xpos[i2]
    q1, q2 = data.xquat[i1].copy(), data.xquat[i2].copy()
    r1 = np.zeros(9)
    mujoco.mju_quat2Mat(r1, q1)
    p_rel = r1.reshape(3, 3).T @ (p2 - p1)
    q1[1:] *= -1.0
    q_rel = np.zeros(4)
    mujoco.mju_mulQuat(q_rel, q1, q2)
    return q_rel, p_rel


def attempt(layout: str) -> dict[str, Any]:
    s = MuJoCoScene(seed=7)
    obs = settle_to_cube(s)
    q_rel, p_rel = relpose_wrt(s.model, s.data, "cube", "gripper")
    eq = 0
    s.model.eq_data[eq, :] = 0.0
    if layout == "A":  # [anchor3, quat4, pos3, ts]
        s.model.eq_data[eq, 3:7] = q_rel
        s.model.eq_data[eq, 7:10] = p_rel
    else:  # B: [anchor3, pos3, quat4, ts]
        s.model.eq_data[eq, 3:6] = p_rel
        s.model.eq_data[eq, 6:10] = q_rel
    s.model.eq_data[eq, 10] = 1.0
    site = mujoco.mj_name2id(s.model, mujoco.mjtObj.mjOBJ_SITE, "tool_site")
    cube_b = mujoco.mj_name2id(s.model, mujoco.mjtObj.mjOBJ_BODY, "cube")
    d0 = float(np.linalg.norm(s.data.xpos[cube_b] - s.data.site_xpos[site]))
    s.data.eq_active[eq] = 1
    apply_q(s, solve_ik_site(s.model, s.observe()["arm_qpos"],
                             (obs["tool_pos"][0], obs["tool_pos"][1], obs["tool_pos"][2] + 0.10)))
    max_step = 0.0
    for _ in range(300):
        prev = np.array(s.data.qpos[s._cube_qadr:s._cube_qadr + 3], copy=True)
        s.step(1)
        max_step = max(max_step, float(np.linalg.norm(
            s.data.qpos[s._cube_qadr:s._cube_qadr + 3] - prev)))
    d1 = float(np.linalg.norm(s.data.xpos[cube_b] - s.data.site_xpos[site]))
    z = float(s.data.qpos[s._cube_qadr + 2])
    return {"layout": layout, "d0": round(d0, 4), "d1": round(d1, 4),
            "z_after": round(z, 4), "max_step": round(max_step, 5),
            "ok": abs(d1 - d0) < 0.03 and max_step < 0.02 and z > 0.08}


def main() -> int:
    results = [attempt("A"), attempt("B")]
    for r in results:
        print(r)
    return 0 if any(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())

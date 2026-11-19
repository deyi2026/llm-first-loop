"""Real MuJoCo physics adapter for M1.

Rules enforced here (no exceptions, no teleport):
- Scene state changes ONLY via mujoco.mj_step integration.
- set_ctrl writes servo targets; actuators realize them physically.
- Deterministic reset from integer seed (numpy default_rng).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import mujoco as _mujoco_impl
import numpy as np

from llm_loop.embodied_sim.scene import SCENE_CONSTANTS, build_scene_xml

# MuJoCo C-extension API is dynamic at type level; explicit Any facade at this boundary only.
mujoco: Any = _mujoco_impl

_ARM_JOINTS = ("shoulder_pan", "shoulder_lift", "elbow", "wrist_roll")
_FINGER_JOINTS = ("finger_left_slide", "finger_right_slide")


class MuJoCoScene:
    """Load, reset (seeded), step, and observe the frozen M1 scene."""

    def __init__(self, seed: int = SCENE_CONSTANTS["initial_seed_default"], xml: str | None = None):
        self.xml = xml or build_scene_xml()
        self.model = mujoco.MjModel.from_xml_string(self.xml)
        self.data = mujoco.MjData(self.model)
        self._ids = {
            "site_tool": mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_SITE, "tool_site"),
            "body_cube": mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "cube"),
            "body_tray": mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "tray_a"),
            "geom_cube": mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, "cube_geom"),
            "geom_ftip_l": mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, "fingertip_left"),
            "geom_ftip_r": mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, "fingertip_right"),
        }
        self._arm_qadr = [self.model.jnt_qposadr[self._joint_id(n)] for n in _ARM_JOINTS]
        self._finger_qadr = [self.model.jnt_qposadr[self._joint_id(n)] for n in _FINGER_JOINTS]
        self._cube_qadr = int(self.model.jnt_qposadr[self._joint_id("cube_free")])
        self.seed = int(seed)
        self.scene_epoch = 0
        self.reset(self.seed)

    def _joint_id(self, name: str) -> int:
        jid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, name)
        if jid < 0:
            raise KeyError(f"joint not in scene: {name}")
        return jid

    # -- lifecycle --------------------------------------------------------
    def reset(self, seed: int | None = None) -> dict[str, Any]:
        """Deterministic re-init; cube xy gets seeded mm-scale jitter (real body, real physics)."""
        if seed is not None:
            self.seed = int(seed)
        mujoco.mj_resetData(self.model, self.data)
        rng = np.random.default_rng(self.seed)
        jitter = rng.normal(0.0, SCENE_CONSTANTS["cube_spawn_xy_jitter_std"], size=2)
        base = np.array([0.18, 0.0])
        spawn = np.clip(base + jitter, [0.14, -0.06], [0.24, 0.06])
        self.data.qpos[self._cube_qadr + 0] = float(spawn[0])
        self.data.qpos[self._cube_qadr + 1] = float(spawn[1])
        self.data.qpos[self._cube_qadr + 2] = SCENE_CONSTANTS["cube_half_size"] + 0.001
        eq_weld = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_EQUALITY, "grasp_weld")
        if eq_weld >= 0:
            self.data.eq_active[eq_weld] = 0  # weld grasp OFF by default; skills activate on confirmed contact
        mujoco.mj_forward(self.model, self.data)
        self.scene_epoch += 1
        return {"seed": self.seed, "scene_epoch": self.scene_epoch,
                "cube_spawn_xy": [float(spawn[0]), float(spawn[1])]}

    # -- physics ----------------------------------------------------------
    def step(self, n: int = 1) -> int:
        """Advance real physics; the ONLY way scene state changes."""
        n = max(0, int(n))
        for _ in range(n):
            mujoco.mj_step(self.model, self.data)
        return n

    def set_ctrl(self, targets: dict[str, float]) -> dict[str, list[float]]:
        """Write position-servo targets (clipped to ctrlrange). Does NOT move anything by itself."""
        applied: dict[str, list[float]] = {}
        for name, value in targets.items():
            aid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, name)
            if aid < 0:
                raise KeyError(f"actuator not in scene: {name}")
            lo, hi = self.model.actuator_ctrlrange[aid]
            self.data.ctrl[aid] = float(np.clip(value, lo, hi))
            applied[name] = [float(lo), float(hi)]
        return applied

    # -- observation ------------------------------------------------------
    def observe(self) -> dict[str, Any]:
        arm_qpos = [float(self.data.qpos[a]) for a in self._arm_qadr]
        arm_qvel = [float(self.data.qvel[a]) for a in self._arm_qadr]
        finger_qpos = [float(self.data.qpos[a]) for a in self._finger_qadr]
        ca = self._cube_qadr
        cube = {
            "pos": [float(v) for v in self.data.qpos[ca:ca + 3]],
            "quat_wxyz": [float(v) for v in self.data.qpos[ca + 3:ca + 7]],
            "vel": [float(v) for v in self.data.qvel[ca:ca + 3]],
            "angvel": [float(v) for v in self.data.qvel[ca + 3:ca + 6]],
        }
        tray_id = self._ids["body_tray"]
        return {
            "t": float(self.data.time),
            "arm_qpos": arm_qpos,
            "arm_qvel": arm_qvel,
            "finger_qpos": finger_qpos,
            "tool_pos": [float(v) for v in self.data.site_xpos[self._ids["site_tool"]]],
            "cube": cube,
            "tray_pos": [float(v) for v in self.data.xpos[tray_id]],
            "n_contacts": int(self.data.ncon),
            "workspace_bounds": dict(SCENE_CONSTANTS["workspace_bounds"]),
            # NOTE: no privileged truth here (grasp verdicts live only in Oracle).
        }

    def state_digest(self) -> str:
        payload = {
            "qpos": [float(v) for v in self.data.qpos],
            "qvel": [float(v) for v in self.data.qvel],
            "t": float(self.data.time),
        }
        blob = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def weld_active(self) -> bool:
        eq_weld = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_EQUALITY, "grasp_weld")
        return bool(self.data.eq_active[eq_weld]) if eq_weld >= 0 else False

    def has_fingertip_cube_contact(self) -> bool:
        for i in range(self.data.ncon):
            pair = {int(self.data.contact[i].geom1), int(self.data.contact[i].geom2)}
            if pair == {self._ids["geom_cube"], self._ids["geom_ftip_l"]} or pair == {self._ids["geom_cube"], self._ids["geom_ftip_r"]}:
                return True
        return False

    def _cube_relpose_in_gripper(self) -> tuple[list[float], list[float]]:
        i1 = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "gripper")
        i2 = self._ids["body_cube"]
        p1, p2 = self.data.xpos[i1], self.data.xpos[i2]
        q1 = np.array(self.data.xquat[i1], copy=True)
        q2 = np.array(self.data.xquat[i2], copy=True)
        r1 = np.zeros(9)
        mujoco.mju_quat2Mat(r1, q1)
        p_rel = r1.reshape(3, 3).T @ (p2 - p1)
        q1[1:] *= -1.0
        q_rel = np.zeros(4)
        mujoco.mju_mulQuat(q_rel, q1, q2)
        return [float(v) for v in q_rel], [float(v) for v in p_rel]

    def activate_weld_grasp(self) -> bool:
        """DISCLOSED simplified grasp: weld at CURRENT relative pose; caller must
        have confirmed real fingertip-cube contact. State changes still flow
        through mj_step constraint solving only."""
        eq = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_EQUALITY, "grasp_weld")
        if eq < 0 or self.weld_active():
            return self.weld_active()
        q_rel, p_rel = self._cube_relpose_in_gripper()
        self.model.eq_data[eq, 0:3] = 0.0
        self.model.eq_data[eq, 3:6] = p_rel
        self.model.eq_data[eq, 6:10] = q_rel
        self.model.eq_data[eq, 10] = 1.0
        self.data.eq_active[eq] = 1
        return True

    def deactivate_weld_grasp(self) -> bool:
        eq = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_EQUALITY, "grasp_weld")
        if eq < 0:
            return False
        self.data.eq_active[eq] = 0
        return True

    # -- privileged snapshot (Oracle-only consumption) --------------------
    def oracle_snapshot(self) -> dict[str, Any]:
        """Full state incl. contact pairs. NEVER expose via observe()."""
        pairs = []
        for i in range(self.data.ncon):
            c = self.data.contact[i]
            g1 = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, int(c.geom1))
            g2 = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, int(c.geom2))
            pairs.append([g1, g2, float(c.dist)])
        return {
            "t": float(self.data.time),
            "scene_digest": self.state_digest(),
            "weld_active": self.weld_active(),
            "contact_pairs": pairs,
            "cube": self.observe()["cube"],
            "tool_pos": self.observe()["tool_pos"],
        }


# -- numeric IK (damped least squares on tool_site) -----------------------
def solve_ik_site(model: Any, qpos_arm_init: Any, target_xyz: tuple[float, float, float],
                  iters: int = 150, tol: float = 0.003, lam: float = 0.05) -> list[float]:
    """Return arm servo targets [pan, lift, elbow, roll] putting tool_site at target_xyz.

    Uses an isolated MjData so the live scene is never touched. Position-only IK;
    wrist_roll target stays 0 (roll axis passes through the site, position-invariant).
    """
    site_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, "tool_site")
    arm_jids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, n) for n in _ARM_JOINTS]
    qadr = [int(model.jnt_qposadr[j]) for j in arm_jids]
    dofadr = [int(model.jnt_dofadr[j]) for j in arm_jids]
    jnt_ranges = [model.jnt_range[j] for j in arm_jids]

    ik_data = mujoco.MjData(model)
    ik_data.qpos[:] = 0.0
    ik_data.qpos[qadr[1]] = 0.2   # seed lift slightly forward
    ik_data.qpos[qadr[2]] = -0.4  # seed elbow bent
    q = np.array(qpos_arm_init, dtype=float)

    jacp = np.zeros((3, model.nv))
    target = np.asarray(target_xyz, dtype=float)
    for _ in range(iters):
        ik_data.qpos[qadr[0]] = q[0]
        ik_data.qpos[qadr[1]] = q[1]
        ik_data.qpos[qadr[2]] = q[2]
        ik_data.qpos[qadr[3]] = 0.0
        mujoco.mj_forward(model, ik_data)
        err = target - ik_data.site_xpos[site_id]
        if float(np.linalg.norm(err)) < tol:
            break
        mujoco.mj_jacSite(model, ik_data, jacp, None, site_id)
        j = jacp[:, dofadr[:3]]  # pan/lift/elbow position the site
        jjt = j @ j.T + lam * np.eye(3)
        dq = j.T @ np.linalg.solve(jjt, err)
        step = np.clip(dq, -0.25, 0.25)
        for k in range(3):
            q[k] = float(np.clip(q[k] + step[k], jnt_ranges[k][0], jnt_ranges[k][1]))
    return [float(q[0]), float(q[1]), float(q[2]), 0.0]

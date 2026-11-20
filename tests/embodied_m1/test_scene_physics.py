"""Gate A physics: real mj_step evidence, seeded determinism, continuous servo motion.

No network, no hardware, no privileged-truth leakage. Deterministic seeds only.
"""
from __future__ import annotations

from typing import Any

import mujoco as _mujoco_impl

from llm_loop.embodied_sim import MuJoCoScene
from llm_loop.embodied_sim.skills import EmbodiedInterface

mujoco: Any = _mujoco_impl


def _cube_contact_count(scene) -> int:
    n = 0
    for i in range(scene.data.ncon):
        c = scene.data.contact[i]
        g1 = mujoco.mj_id2name(scene.model, mujoco.mjtObj.mjOBJ_GEOM, int(c.geom1))
        g2 = mujoco.mj_id2name(scene.model, mujoco.mjtObj.mjOBJ_GEOM, int(c.geom2))
        if "cube_geom" in (g1, g2):
            n += 1
    return n


def test_same_seed_deterministic_reset_and_evolution():
    a = MuJoCoScene(seed=42)
    b = MuJoCoScene(seed=42)
    assert a.state_digest() == b.state_digest()
    a.step(37)
    b.step(37)
    assert a.state_digest() == b.state_digest(), "identical seeds must evolve identically"


def test_different_seed_diverges():
    a = MuJoCoScene(seed=42)
    b = MuJoCoScene(seed=43)
    assert a.state_digest() != b.state_digest()


def test_isolated_free_fall_real_gravity_no_contacts():
    s = MuJoCoScene(seed=1)
    ca = s._cube_qadr
    s.data.qpos[ca + 0] = 0.45  # outside arm envelope, away from tray
    s.data.qpos[ca + 1] = 0.45
    s.data.qpos[ca + 2] = 0.15
    mujoco.mj_forward(s.model, s.data)
    z0 = float(s.data.qpos[ca + 2])
    s.step(40)  # 0.08 s free fall => ~31 mm under g
    z1 = float(s.data.qpos[ca + 2])
    vz = float(s.data.qvel[ca + 2])
    assert z1 < z0 - 0.02, "cube must actually fall under gravity"
    assert vz < -0.1, "downward velocity must be strictly negative mid-fall"
    assert _cube_contact_count(s) == 0, "isolated falling cube must touch nothing"


def test_ctrl_target_alone_moves_nothing():
    s = MuJoCoScene(seed=7)
    s.step(50)
    before = s.state_digest()
    s.set_ctrl({"a_shoulder_lift": -0.3})
    assert s.state_digest() == before, "writing servo targets must not integrate physics"


def test_servo_realizes_target_continuously_not_teleport():
    s = MuJoCoScene(seed=7)
    s.step(50)
    s.set_ctrl({"a_shoulder_lift": -0.4})
    max_speed = 0.0
    for _ in range(300):
        s.step(1)
        max_speed = max(max_speed, abs(float(s.observe()["arm_qvel"][1])))
    final = s.observe()["arm_qpos"][1]
    assert abs(final - (-0.4)) < 0.05, f"servo must converge to target, got {final}"
    # bounded transient peak (kp160 servo) still means continuous motion; a teleport would be infinite
    assert max_speed < 6.0, f"joint speed must stay bounded (continuous motion), got {max_speed}"


def test_move_above_skill_converges_via_real_physics():
    iface = EmbodiedInterface(MuJoCoScene(seed=7))
    iface.scene.step(100)
    cube = iface.observe()["observation"]["cube"]["pos"]
    r = iface.execute_skill("move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.06}, "k1", 1)
    aid = r["action_id"]
    while iface.get_action_status(aid)["state"] == "running":
        iface.advance(60)
    assert iface.get_action_status(aid)["state"] == "done"


def test_observation_contract_fields_epoch_and_determinism():
    s = MuJoCoScene(seed=3)
    iface = EmbodiedInterface(s)
    obs1 = iface.observe()
    required = {"t", "arm_qpos", "arm_qvel", "finger_qpos", "tool_pos",
                "cube", "tray_pos", "workspace_bounds"}
    assert required <= set(obs1["observation"].keys())
    assert obs1["scene_epoch"] == s.scene_epoch == 1
    assert obs1["observation_ref"].startswith("obs-epoch1-")
    t1 = obs1["observation"]["t"]
    obs2 = iface.observe()
    assert obs2["observation"]["t"] == t1, "no step => deterministic time"
    s.reset()
    assert s.scene_epoch == 2, "reset must bump scene_epoch"


def test_no_privileged_truth_in_observations():
    iface = EmbodiedInterface(MuJoCoScene(seed=3))
    blob = repr(iface.observe())
    assert "contact_pairs" not in blob, "contact pair snapshot is Oracle-privileged"
    assert "verdict" not in blob, "Oracle verdicts must never leak into observations"

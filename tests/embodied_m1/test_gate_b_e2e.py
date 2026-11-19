"""Gate B: grasp-lift-place E2E over real physics + honest failure recovery (L3).

Disclosed grasp mechanism: contact_confirmed_weld (closure contact is real;
the weld constraint then carries the cube through the solver). Every state
change flows through mujoco.mj_step; reset is the only qpos writer. Privileged
truth stays behind oracle_snapshot(); assertions here use it only in this test
layer, never as model context.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from llm_loop.embodied_sim import MuJoCoScene
from llm_loop.embodied_sim.oracle import judge_grasp, judge_place, make_receipt, verify_receipt
from llm_loop.embodied_sim.skills import EmbodiedInterface

SRC_SKILLS = (Path(__file__).resolve().parents[2] / "src/llm_loop/embodied_sim/skills.py")


def _iface(tmp_path):
    s = MuJoCoScene(seed=7)
    s.step(100)
    return EmbodiedInterface(s, ledger_path=str(tmp_path / "gate_b_ledger.jsonl"))


def _run(iface, name, params, key):
    r = iface.execute_skill(name, params, key, 1)
    if "action_id" not in r:
        return r
    aid = r["action_id"]
    while iface.get_action_status(aid)["state"] == "running":
        iface.advance(60)
    return iface.get_action_status(aid)


def _cube_xy(iface):
    return iface.observe()["observation"]["cube"]["pos"]


def test_grasp_lift_place_deterministic(tmp_path):
    iface = _iface(tmp_path)
    s = iface.scene
    cube = _cube_xy(iface)
    assert _run(iface, "move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.07}, "g1")["state"] == "done"
    assert _run(iface, "move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.010}, "g2")["state"] == "done"
    g = _run(iface, "grasp", {}, "g3")
    assert g["state"] == "done" and g["grasp_mechanism"] == "contact_confirmed_weld"
    # continuous motion under weld: cube follows the gripper via the solver, no jumps
    max_step = 0.0
    for _ in range(240):
        prev = np.array(s.data.qpos[s._cube_qadr:s._cube_qadr + 3], copy=True)
        s.step(1)
        max_step = max(max_step, float(np.linalg.norm(s.data.qpos[s._cube_qadr:s._cube_qadr + 3] - prev)))
    assert max_step < 0.02  # any teleport would dwarf this
    assert _run(iface, "move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.13}, "g4")["state"] == "done"
    s.step(30)
    snap = s.oracle_snapshot()
    ok, ev = judge_grasp(snap)
    assert ok and ev["weld_active"] and ev["fingertips_contacting"] and ev["lifted"]
    receipt = make_receipt(snap, "grasp", ok, ev, experiment_id="m1-sim-gateb-test", scene_epoch=s.scene_epoch)
    # local geometry true, but in-process independence unproven -> PENDING_ORACLE
    assert verify_receipt(receipt, s.scene_epoch, snap).name == "PENDING_ORACLE"
    tray = iface.observe()["observation"]["tray_pos"]
    assert _run(iface, "move_to", {"x": tray[0], "y": tray[1], "z": cube[2] + 0.15}, "g5")["state"] == "done"
    assert _run(iface, "release", {}, "g6")["state"] == "done"
    s.step(150)
    final = _cube_xy(iface)
    inside = abs(final[0] - tray[0]) < 0.055 and abs(final[1] - tray[1]) < 0.055
    okp, evp = judge_place(s.oracle_snapshot(), tray)
    assert okp and evp["inside_tray_xy"] and inside


def test_grasp_failure_recovery_l3(tmp_path):
    iface = _iface(tmp_path)
    s = iface.scene
    # L3: attempt grasp where no cube exists -> honest failure, weld stays off
    cube0 = iface.observe()["observation"]["cube"]["pos"]
    assert _run(iface, "move_to", {"x": cube0[0] + 0.03, "y": cube0[1] + 0.06, "z": cube0[2] + 0.06}, "f1")["state"] == "done"
    g = _run(iface, "grasp", {}, "f2")
    assert g["state"] == "failed"
    assert "no sustained" in g["reason"] or "contact" in g["reason"]
    assert not s.weld_active()  # privileged side-check: nothing was faked
    # recovery: re-observe, approach the actual cube, grasp, lift, verify
    # recovery step 0: open the gripper first (honest recovery)
    assert _run(iface, "release", {}, "f2r")["state"] == "done"
    cube = _cube_xy(iface)
    assert _run(iface, "move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.07}, "f3")["state"] == "done"
    assert _run(iface, "move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.010}, "f4")["state"] == "done"
    g2 = _run(iface, "grasp", {}, "f5")
    assert g2["state"] == "done" and g2["grasp_mechanism"] == "contact_confirmed_weld"
    assert _run(iface, "move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.13}, "f6")["state"] == "done"
    s.step(30)
    ok, ev = judge_grasp(s.oracle_snapshot())
    assert ok and ev["lifted"]


@pytest.mark.parametrize("seed", range(10))
def test_l3_engineering_seed_recovery_and_place_within_action_budget(seed):
    """Prereg 10 engineering seeds; local Oracle is NOT independent Host truth."""
    scene = MuJoCoScene(seed=seed)  # keep paired seeds 20261117+ untouched
    scene.step(100)
    iface = EmbodiedInterface(scene)
    failed = _run(iface, "grasp", {}, "fault1")
    assert failed["state"] == "failed" and not scene.weld_active()
    assert _run(iface, "release", {}, "recover1")["state"] == "done"
    cube = _cube_xy(iface)
    assert _run(iface, "move_to", {"x": cube[0], "y": cube[1],
                                    "z": cube[2] + 0.07}, "k1")["state"] == "done"
    assert _run(iface, "move_to", {"x": cube[0], "y": cube[1],
                                    "z": cube[2] + 0.012}, "k2")["state"] == "done"
    assert _run(iface, "grasp", {}, "k3")["state"] == "done"
    tray = iface.observe()["observation"]["tray_pos"]
    assert _run(iface, "move_to", {"x": tray[0], "y": tray[1],
                                    "z": 0.1}, "k4")["state"] == "done"
    scene.step(30)
    assert judge_grasp(scene.oracle_snapshot())[0]
    assert _run(iface, "release", {}, "k5")["state"] == "done"
    scene.step(150)
    assert judge_place(scene.oracle_snapshot(), tray)[0]
    assert iface.tool_action_count == 7  # 1 injected + 1 reset + 5 task actions <= 8


def test_skills_layer_never_writes_cube_pose(tmp_path):
    text = SRC_SKILLS.read_text()
    assert "qpos[" not in text, "skills layer must not touch qpos (no teleport path)"
    assert "data.qpos" not in text


def test_weld_off_by_default_and_release_deactivates(tmp_path):
    s = MuJoCoScene(seed=3)
    assert not s.weld_active()
    iface = EmbodiedInterface(s)
    cube = iface.observe()["observation"]["cube"]["pos"]
    _run(iface, "move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.07}, "w1")
    _run(iface, "move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.010}, "w2")
    assert _run(iface, "grasp", {}, "w3")["state"] == "done"
    assert s.weld_active()
    assert _run(iface, "release", {}, "w4")["state"] == "done"
    assert not s.weld_active()

"""M2 over real MuJoCo: the target moves, the claim follows it.

The tray is the external moving target. These tests relocate it the only way an
external actor could — `model.body_pos` for the static tray body followed by
`mj_forward` — and then let real contact physics decide where the released cube
comes to rest. No robot state is written by the test and no verdict is faked:
`judge_place` still runs on the Oracle snapshot.

Pre-M2 the runner cached the tray pose before the loop, so the final verdict was
computed against a pose the cube was never near (asserted explicitly below).
"""
from __future__ import annotations

import re
from pathlib import Path

import mujoco
import pytest

from embodied_m2.harness import ScriptedProvider, decision
from llm_loop.embodied_sim.episode import EpisodeBudget, run_episode
from llm_loop.embodied_sim.oracle import judge_place
from llm_loop.embodied_sim.sim import MuJoCoScene
from llm_loop.embodied_sim.skills import EmbodiedInterface

BUDGET = EpisodeBudget(max_provider_attempts=14, max_tool_actions=12, deadline_s=180.0)
_VEC = r"\[([-\d.eE+]+), ([-\d.eE+]+), ([-\d.eE+]+)\]"


def _vec(state_text: str, key: str) -> list[float]:
    m = re.search(key + "=" + _VEC, state_text)
    assert m is not None, f"{key} missing from state_text"
    return [float(m.group(i)) for i in (1, 2, 3)]


def _move_tray(scene: MuJoCoScene, dx: float) -> None:
    """Environment-side motion of the static tray body (never robot state)."""
    bid = mujoco.mj_name2id(scene.model, mujoco.mjtObj.mjOBJ_BODY, "tray_a")
    assert bid >= 0
    scene.model.body_pos[bid, 0] += float(dx)
    mujoco.mj_forward(scene.model, scene.data)


def _iface(tmp_path: Path) -> EmbodiedInterface:
    scene = MuJoCoScene(seed=7)
    scene.step(100)
    return EmbodiedInterface(scene, ledger_path=str(tmp_path / "m2_ledger.jsonl"))


def test_mujoco_l3_replan_after_target_moves_then_place_is_verified(tmp_path) -> None:
    iface = _iface(tmp_path)
    scene = iface.scene
    tray0 = list(iface.observe()["observation"]["tray_pos"])
    moved = {"done": False}
    stale_plan: dict[str, list[float]] = {}

    def grasp_setup(state: str) -> str:
        cube = _vec(state, "cube")
        return decision("move_to", "approach", x=cube[0], y=cube[1], z=cube[2] + 0.07)

    def descend(state: str) -> str:
        cube = _vec(state, "cube")
        return decision("move_to", "descend", x=cube[0], y=cube[1], z=cube[2] + 0.010)

    def lift(state: str) -> str:
        cube = _vec(state, "cube")
        return decision("move_to", "lift", x=cube[0], y=cube[1], z=cube[2] + 0.13)

    def move_world_then_plan_stale(state: str) -> str:
        """The target moves after this decision's observation was rendered.

        The model therefore plans against the OLD pose — exactly the stale-plan
        case the runner must catch, invalidate and replan from.
        """
        if not moved["done"]:
            moved["done"] = True
            _move_tray(scene, 0.08)  # L3 trigger: the target moves mid-episode
        tray = _vec(state, "tray")  # state_text was built before the move
        stale_plan["tray"] = list(tray)
        return decision("move_to", "to-tray-stale", x=tray[0], y=tray[1], z=0.10)

    def replan_to_fresh_tray(state: str) -> str:
        tray = _vec(state, "tray")  # the replan sees the NEW pose
        return decision("move_to", "to-tray-fresh", x=tray[0], y=tray[1], z=0.10)

    provider = ScriptedProvider([grasp_setup, descend, ("grasp", {}), lift,
                                 move_world_then_plan_stale, replan_to_fresh_tray,
                                 ("release", {})])
    result = run_episode(iface, provider, BUDGET, experiment_id="M2-SIM-MOVING-TARGET")

    events = [e["event"] for e in result["trace"]]
    assert result["terminated_by"] == "place_verified_locally_pending_oracle", events
    assert result["goal_rebinds"] >= 1
    assert "GOAL_CHANGED_MID_ACTION" in events
    assert stale_plan["tray"][0] == pytest.approx(tray0[0])  # stale plan really was stale
    assert result["claim_state"] == "pending_oracle"
    new_tray = list(iface.observe()["observation"]["tray_pos"])
    assert new_tray[0] == pytest.approx(tray0[0] + 0.08, abs=1e-6)
    assert result["oracle_receipt"]["goal"]["pos"][0] == pytest.approx(new_tray[0])
    assert result["oracle_receipt"]["goal"]["digest"] == result["goal"]["digest"]
    # discrimination proof: the same physical snapshot fails against the OLD goal
    snapshot = scene.oracle_snapshot()
    ok_new, ev_new = judge_place(snapshot, new_tray)
    ok_old, ev_old = judge_place(snapshot, tray0)
    assert ok_new and ev_new["inside_tray_xy"] and ev_new["tray_contact"]
    assert not ok_old and not ev_old["inside_tray_xy"]
    assert len(result["goal_history"]) >= 2


def test_mujoco_l4_reset_recovery_never_reuses_pre_reset_evidence(tmp_path) -> None:
    iface = _iface(tmp_path)
    scene = iface.scene
    epoch0 = scene.scene_epoch
    reset_done = {"done": False}

    def approach(state: str) -> str:
        cube = _vec(state, "cube")
        return decision("move_to", "a1", x=cube[0], y=cube[1], z=cube[2] + 0.07)

    def descend(state: str) -> str:
        cube = _vec(state, "cube")
        return decision("move_to", "a2", x=cube[0], y=cube[1], z=cube[2] + 0.010)

    def reset_world(state: str) -> str:
        if not reset_done["done"]:
            reset_done["done"] = True
            scene.reset()  # L4 trigger: everything observed so far is void
        cube = _vec(state, "cube")
        return decision("move_to", "a3", x=cube[0], y=cube[1], z=cube[2] + 0.07)

    def descend2(state: str) -> str:
        cube = _vec(state, "cube")
        return decision("move_to", "a4", x=cube[0], y=cube[1], z=cube[2] + 0.010)

    def to_tray(state: str) -> str:
        tray = _vec(state, "tray")
        return decision("move_to", "a6", x=tray[0], y=tray[1], z=0.10)

    provider = ScriptedProvider([approach, descend, reset_world, descend2,
                                 ("grasp", {}), to_tray, ("release", {})])
    result = run_episode(iface, provider, BUDGET, experiment_id="M2-SIM-RESET-RECOVERY")

    events = [e["event"] for e in result["trace"]]
    assert "SCENE_RESET" in events
    assert result["goal_version"] >= 2
    assert result["stale_evidence_invalidated"] >= 1
    assert scene.scene_epoch == epoch0 + 1
    assert result["oracle_receipt"] is not None
    assert result["oracle_receipt"]["scene_epoch"] == scene.scene_epoch
    assert result["terminated_by"] == "place_verified_locally_pending_oracle", events

"""Deterministic M2 mechanism harness: a scripted world whose tray can move.

The scene is deliberately a *mechanism* stub — it produces the geometric facts
`judge_place` consumes, but no physics is claimed. Physics honesty is covered
by tests/embodied_m2/test_mujoco_moving_target.py against real MuJoCo.

Fault injection points modelled here (issue #79):
  * target moves between actions          -> FakeScene.move_tray via provider hook
  * target moves during an action         -> FakeScene.move_tray via advance hook
  * scene reset (epoch bump)              -> FakeScene.reset
  * duplicate intent after the goal moved -> repeated intent_key
  * indeterminate execution state         -> FakeIface.hold_actions
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from llm_loop.embodied_sim.contract import ContractKernel

TRAY0 = (0.0, 0.18, 0.01)
CUBE_SPAWN = (0.18, 0.0, 0.011)
CUBE_GEOM = "cube_geom"

Step = tuple[str, dict[str, Any]] | Callable[[str], str]


class FakeScene:
    """Scripted world. `placed` means the cube rests on the CURRENT tray pose."""

    def __init__(self, tray: tuple[float, float, float] = TRAY0) -> None:
        self.tray = [float(v) for v in tray]
        self.placed = False
        self.scene_epoch = 1
        self.step_calls = 0
        self._arm_after: int | None = None
        self._arm_dx = 0.0
        self._armed_observes = 0

    # -- world motion (the moving external target) ------------------------
    def move_tray(self, dx: float, dy: float = 0.0) -> None:
        self.tray[0] += float(dx)
        self.tray[1] += float(dy)

    def arm_move_after(self, observes: int, dx: float) -> None:
        """Move the target out of band, `observes` observe() calls from now.

        Models an external actor that moves the tray while the runner is *not*
        executing an action (the only window where no skill can see it move).
        """
        self._arm_after = int(observes)
        self._arm_dx = float(dx)
        self._armed_observes = 0

    def reset(self) -> None:
        self.placed = False
        self.scene_epoch += 1

    # -- SceneProtocol ----------------------------------------------------
    def observe(self) -> dict[str, Any]:
        if self._arm_after is not None:
            self._armed_observes += 1
            if self._armed_observes >= self._arm_after:
                self._arm_after = None
                self.move_tray(self._arm_dx)
        cube = self._cube_pos()
        return {
            "t": float(self.step_calls),
            "arm_qpos": [0.0, 0.0, 0.0, 0.0],
            "arm_qvel": [0.0, 0.0, 0.0, 0.0],
            "finger_qpos": [0.0, 0.0],
            "tool_pos": list(cube),
            "cube": {"pos": list(cube), "vel": [0.0, 0.0, 0.0]},
            "tray_pos": list(self.tray),
            "n_contacts": 0,
            "workspace_bounds": {"x": [-0.35, 0.35], "y": [-0.35, 0.35], "z": [0.0, 0.4]},
            "pre_grasp_point": [cube[0], cube[1], cube[2] + 0.07],
        }

    def step(self, n: int = 1) -> int:
        self.step_calls += int(n)
        return int(n)

    def oracle_snapshot(self) -> dict[str, Any]:
        cube = self._cube_pos()
        pairs = [[CUBE_GEOM, "tray_floor", 0.0]] if self.placed else []
        return {
            "cube": {"pos": list(cube), "vel": [0.0, 0.0, 0.0]},
            "contact_pairs": pairs,
            "weld_active": not self.placed,
        }

    def _cube_pos(self) -> tuple[float, float, float]:
        if self.placed:
            return (self.tray[0], self.tray[1], self.tray[2] + 0.03)
        return CUBE_SPAWN


class FakeIface:
    """Minimal EmbodiedInterface: one advance per action, scripted statuses."""

    model_used = "scripted/mechanism"

    def __init__(self, scene: FakeScene, *, clock: Callable[[], float] | None = None,
                 observation_ttl_s: float = 10_000.0) -> None:
        self.scene = scene
        self.kernel = ContractKernel(clock=clock, observation_ttl_s=observation_ttl_s)
        self._actions: dict[str, dict[str, Any]] = {}
        self._intents: dict[str, str] = {}
        self._n = 0
        self.advance_calls = 0
        self.on_advance: Callable[[FakeIface], None] | None = None
        self.hold_actions = False
        self.on_duplicate: Callable[[FakeIface], None] | None = None
        self.stop_requests: list[dict[str, Any]] = []

    def observe(self) -> dict[str, Any]:
        return {"observation": self.scene.observe(), "scene_epoch": self.scene.scene_epoch}

    def execute_skill(self, skill: str, params: dict[str, Any], *,
                      intent_key: str, grant_version: int) -> dict[str, Any]:
        prior = self._intents.get(intent_key)
        if prior is not None:
            if self.on_duplicate is not None:
                self.on_duplicate(self)
            return {"action_id": prior, "idempotent": True}
        self._n += 1
        action_id = f"act-{self._n}"
        self._intents[intent_key] = action_id
        self._actions[action_id] = {"skill": skill, "params": dict(params), "state": "running",
                                    "settled": False, "epoch": self.scene.scene_epoch}
        return {"action_id": action_id, "state": "running"}

    def get_action_status(self, action_id: str) -> dict[str, Any]:
        rec = self._actions[action_id]
        if self.hold_actions:
            return {"action_id": action_id, "state": "running", "skill": rec["skill"]}
        if not rec["settled"]:
            rec["settled"] = True
            rec["state"] = "done"
            if rec["skill"] == "release" and rec["epoch"] == self.scene.scene_epoch:
                # an action submitted in an older epoch cannot take effect after a reset
                self.scene.placed = True
        return {"action_id": action_id, "state": "done", "skill": rec["skill"]}

    def advance(self, n: int) -> int:
        self.advance_calls += 1
        if self.on_advance is not None:
            self.on_advance(self)
        return int(n)

    def stop(self, reason: str) -> dict[str, Any]:
        self.stop_requests.append({"reason": reason})
        return {"stop_id": "stop-1", "state": "requested"}

    def confirm_stop(self, stop_id: str) -> dict[str, Any]:
        return {"stop_id": stop_id, "state": "confirmed"}


class ScriptedProvider:
    """Deterministic decision source (never presented as model autonomy)."""

    model_used = "scripted/mechanism"

    def __init__(self, steps: list[Step]) -> None:
        self.steps = list(steps)
        self.i = 0
        self.prompts: list[str] = []

    def decide(self, state_text: str) -> str:
        self.prompts.append(state_text)
        if self.i >= len(self.steps):
            self.i += 1
            return json.dumps({"skill": "stop", "params": {"reason": "script exhausted"},
                               "intent_key": f"stop-{len(self.prompts)}"})
        step = self.steps[self.i]
        self.i += 1
        if callable(step):
            return step(state_text)
        skill, params = step
        return json.dumps({"skill": skill, "params": params, "intent_key": f"intent-{self.i}"})


def decision(skill: str, intent_key: str, **params: Any) -> str:
    return json.dumps({"skill": skill, "params": params, "intent_key": intent_key})

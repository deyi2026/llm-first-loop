"""Thin embodied interface for M1: observe / execute_skill / get_action_status / stop.

The model-facing surface exposes ONLY physical observations and skill status.
Privileged truth (contact-pair snapshots, weld state, Oracle verdicts) never
flows through observe().

Control targets are servo set-points; every state change is realized by real
mujoco.mj_step physics inside advance(). No teleport, no scripted sequences.

DISCLOSED simplification (grasp): finger closure is realized by position
actuators; when closure converges AND a real fingertip-cube contact exists,
the interface activates the scene's predefined weld equality at the CURRENT
relative pose, so the cube follows the gripper through the constraint solver.
The weld is never activated without confirmed physical contact, release
deactivates it, and the mechanism is surfaced honestly in action status and
Oracle evidence as "contact_confirmed_weld".
"""
from __future__ import annotations

from typing import Any

from llm_loop.embodied_sim.contract import (
    ClaimGuard,
    ContractKernel,
    FrozenLedger,
    GrantRegistry,
    GrantRevokedError,
    IntentLedger,
    StopController,
)
from llm_loop.embodied_sim.scene import SCENE_CONSTANTS
from llm_loop.embodied_sim.sim import MuJoCoScene, solve_ik_site

SKILL_NAMES = ("move_to", "grasp", "release")
GRASP_MECHANISM = "contact_confirmed_weld"

_ARM_ACTUATORS = {
    "shoulder_pan": "a_shoulder_pan",
    "shoulder_lift": "a_shoulder_lift",
    "elbow": "a_elbow",
    "wrist_roll": "a_wrist_roll",
}
_ARM_ORDER = ("shoulder_pan", "shoulder_lift", "elbow", "wrist_roll")
_FINGER_ACTUATORS = ("a_finger_left", "a_finger_right")

_MOVE_TOL_M = 0.013
_MOVE_SETTLE_STEPS = 20
_MOVE_MAX_STEPS = 600
_FINGER_TOL_M = 0.003
_FINGER_SETTLE_STEPS = 10
_FINGER_MAX_STEPS = 200
_GRASP_CONTACT_SETTLE_STEPS = 15


class EmbodiedInterface:
    """Model-facing thin interface. One instance binds one MuJoCoScene."""

    def __init__(self, scene: MuJoCoScene, ledger_path: str | None = None,
                 clock: Any = None):
        self.scene = scene
        self.kernel = ContractKernel(clock=clock)
        self.grants = GrantRegistry()
        self.intents = IntentLedger()
        self.stopper = StopController()
        self.claims = ClaimGuard()
        self.ledger = FrozenLedger(ledger_path) if ledger_path else None
        for skill in SKILL_NAMES:
            self.grants.grant(skill)
        self._actions: dict[str, dict[str, Any]] = {}
        self._seq = 0
        self.tool_action_count = 0
        self._stop_confirmed_id: str | None = None

    # -- privileged ledger --------------------------------------------
    def freeze_unknown(self, kind: str, payload: dict[str, Any]) -> None:
        if self.ledger is not None:
            self.ledger.append({"kind": kind, "payload": payload,
                                "scene_epoch": self.scene.scene_epoch,
                                "t": self.scene.observe()["t"]})

    # -- 1. observe -----------------------------------------------------
    def observe(self) -> dict[str, Any]:
        ticket = self.kernel.issue_observation_ref(self.scene.scene_epoch)
        return {
            "observation": self.scene.observe(),
            "observation_ref": ticket.ref,
            "scene_epoch": self.scene.scene_epoch,
            "observation_ttl_s": self.kernel.observation_ttl_s,
        }

    # -- 2. execute_skill -----------------------------------------------
    def execute_skill(self, name: str, params: dict[str, Any], intent_key: str,
                      grant_version: int) -> dict[str, Any]:
        if self._stop_confirmed_id is not None:
            return {"error": "STOP_CONFIRMED", "stop_id": self._stop_confirmed_id}
        if name not in SKILL_NAMES:
            self.freeze_unknown("UNKNOWN_SKILL_REQUEST", {"skill": str(name), "intent_key": str(intent_key)})
            return {"error": "UNKNOWN_SKILL", "skill": str(name)}
        if not self.grants.check(name, grant_version):
            self.freeze_unknown("GRANT_CHECK_FAILED", {"skill": name, "grant_version": grant_version})
            raise GrantRevokedError(f"skill {name} grant version {grant_version} not valid")
        action_id, fresh = self.intents.submit(str(intent_key), lambda: self._new_action_id())
        if not fresh:
            return {"action_id": action_id, "state": "duplicate_intent_key", "idempotent": True}
        self.tool_action_count += 1

        if name == "move_to":
            bounds = SCENE_CONSTANTS["workspace_bounds"]
            target = [float(params[k]) for k in ("x", "y", "z")]
            for axis_i, axis in enumerate(("x", "y", "z")):
                lo, hi = bounds[axis]
                if not (lo <= target[axis_i] <= hi):
                    self.freeze_unknown("TARGET_OUT_OF_WORKSPACE", {"target": target, "axis": axis})
                    self._actions[action_id] = self._failed_action(action_id, name,
                                                                   "target outside workspace bounds")
                    return {"action_id": action_id, "state": "failed",
                            "reason": "target outside workspace bounds"}
            obs = self.scene.observe()
            q_target = solve_ik_site(self.scene.model, obs["arm_qpos"], (target[0], target[1], target[2]))
            self._actions[action_id] = {
                "action_id": action_id, "skill": name, "state": "running",
                "params": params, "q_target": q_target, "finger_target": None,
                "target_xyz": target, "steps": 0, "max_steps": _MOVE_MAX_STEPS,
                "settle": 0, "settle_needed": _MOVE_SETTLE_STEPS, "tol": _MOVE_TOL_M,
                "grasp_mechanism": None,
            }
        elif name == "grasp":
            self._actions[action_id] = self._finger_action(action_id, name,
                                                           SCENE_CONSTANTS["finger_grasp_ctrl"])
        elif name == "release":
            # Physically honest release: constraint off first, then fingers open.
            self.scene.deactivate_weld_grasp()
            self._actions[action_id] = self._finger_action(action_id, name,
                                                           SCENE_CONSTANTS["finger_open_ctrl"])
        return {"action_id": action_id, "state": "running"}

    def _finger_action(self, action_id: str, name: str, finger_target: float) -> dict[str, Any]:
        return {
            "action_id": action_id, "skill": name, "state": "running",
            "params": {}, "q_target": None, "finger_target": float(finger_target),
            "target_xyz": None, "steps": 0, "max_steps": _FINGER_MAX_STEPS,
            "settle": 0, "settle_needed": _FINGER_SETTLE_STEPS, "tol": _FINGER_TOL_M,
            "grasp_mechanism": None,
        }

    def _failed_action(self, action_id: str, name: str, reason: str) -> dict[str, Any]:
        return {"action_id": action_id, "skill": name, "state": "failed",
                "reason": reason, "params": {}, "q_target": None, "finger_target": None,
                "target_xyz": None, "steps": 0, "max_steps": 0, "settle": 0,
                "settle_needed": 0, "tol": 0.0, "grasp_mechanism": None}

    def _new_action_id(self) -> str:
        self._seq += 1
        return f"act-{self._seq:06d}"

    # -- physics driver ---------------------------------------------------
    def advance(self, n_steps: int = 50) -> dict[str, Any]:
        """Push real physics forward while any action is running; servo targets only."""
        advanced = 0
        for _ in range(int(n_steps)):
            active = [a for a in self._actions.values() if a["state"] == "running"]
            if not active:
                break
            ctrl: dict[str, float] = {}
            for a in active:
                if a["q_target"] is not None:
                    for i, act in enumerate(_ARM_ACTUATORS.values()):
                        ctrl[act] = a["q_target"][i]
                if a["finger_target"] is not None:
                    for act in _FINGER_ACTUATORS:
                        ctrl[act] = a["finger_target"]
            if ctrl:
                self.scene.set_ctrl(ctrl)
            self.scene.step(1)
            advanced += 1
            for a in active:
                self._check_progress(a)
        statuses = {aid: self.get_action_status(aid) for aid in self._actions}
        return {"steps_advanced": advanced, "statuses": statuses}

    def _check_progress(self, a: dict[str, Any]) -> None:
        a["steps"] += 1
        obs = self.scene.observe()
        if a["skill"] == "move_to":
            err = sum((o - t) ** 2 for o, t in zip(obs["tool_pos"], a["target_xyz"], strict=True)) ** 0.5
            if err < a["tol"]:
                a["settle"] += 1
                if a["settle"] >= a["settle_needed"]:
                    a["state"] = "done"
                    a["final_err_m"] = err
            else:
                a["settle"] = 0
                a["last_err_m"] = err
        elif a["skill"] == "grasp":
            # Contact-led closure: the cube physically stops the fingers short of
            # the servo target; sustained real contact is the completion criterion.
            err = max(abs(q - a["finger_target"]) for q in obs["finger_qpos"])
            a["last_err_m"] = err
            if self.scene.has_fingertip_cube_contact():
                a["settle"] += 1
                if a["settle"] >= _GRASP_CONTACT_SETTLE_STEPS:
                    self.scene.activate_weld_grasp()
                    a["state"] = "done"
                    a["final_err_m"] = err
                    a["grasp_mechanism"] = GRASP_MECHANISM
            else:
                a["settle"] = 0
        else:  # release
            err = max(abs(q - a["finger_target"]) for q in obs["finger_qpos"])
            if err < a["tol"]:
                a["settle"] += 1
                if a["settle"] >= a["settle_needed"]:
                    a["state"] = "done"
                    a["final_err_m"] = err
            else:
                a["settle"] = 0
                a["last_err_m"] = err
        if a["state"] == "running" and a["steps"] >= a["max_steps"]:
            a["state"] = "failed"
            if a["skill"] == "grasp":
                a["reason"] = "closure timed out without sustained fingertip-cube contact; weld not activated"
            else:
                a["reason"] = f"timeout after {a['steps']} physics steps (last_err_m={a.get('last_err_m')})"

    # -- 3. get_action_status (read-only, never advances physics) ----------
    def get_action_status(self, action_id: str) -> dict[str, Any]:
        a = self._actions.get(action_id)
        if a is None:
            return {"action_id": action_id, "state": "unknown_action"}
        return {
            "action_id": action_id,
            "skill": a["skill"],
            "state": a["state"],
            "steps": a["steps"],
            "reason": a.get("reason"),
            "grasp_mechanism": a.get("grasp_mechanism"),
            "last_err_m": a.get("last_err_m") if a.get("last_err_m") is not None else a.get("final_err_m"),
        }

    # -- 4/5. stop: request and confirm separated ---------------------------
    def stop(self, reason: str) -> dict[str, str]:
        req = self.stopper.request(reason)
        return req

    def confirm_stop(self, stop_id: str) -> dict[str, Any]:
        conf = self.stopper.confirm(stop_id)
        self._stop_confirmed_id = stop_id
        # Real safe stop: zero all servo targets; physics keeps integrating gravity.
        for act in list(_ARM_ACTUATORS.values()) + list(_FINGER_ACTUATORS):
            self.scene.set_ctrl({act: 0.0})
        for a in self._actions.values():
            if a["state"] == "running":
                a["state"] = "failed"
                a["reason"] = "stopped after confirmed stop request"
        return conf

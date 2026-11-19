"""Model-facing decision policy layer for M1 episodes.

The real provider is glm/glm-5.3-flash (prereg model_required). GLMHttpProvider
lives in the gate script (scripts/embodied/m1_gate_c_episode.py) so the src
test surface stays free of provider/network dependencies; this module defines
the protocol, deterministic prompt building, decision parsing/validation, and
the stub used ONLY by mechanism tests (never presented as autonomy).
"""
from __future__ import annotations

import json
import re
from typing import Any, Protocol

SKILL_CATALOG: dict[str, set[str]] = {
    "move_to": {"x", "y", "z"},
    "grasp": set(),
    "release": set(),
    "stop": {"reason"},
}

WORKSPACE_HINT = "workspace x[-0.25,0.35] y[-0.25,0.35] z[0.005,0.30] (meters)"
TASK_BRIEF = (
    "Task: pick the red cube and place it into tray-A. "
    "Output ONLY a JSON object: "
    '{"skill": "move_to"|"grasp"|"release"|"stop", '
    '"params": {"x": 0.0, "y": 0.0, "z": 0.0}, "intent_key": "kN"}. '
    "intent_key MUST be unique per action: use k1, k2, k3, ... incrementing the "
    "counter every time; a repeated key is rejected as a duplicate and wastes "
    "your budget. Typical solution: move_to above the cube, move_to down to the "
    "cube, grasp, move_to above tray-A, release. "
    "move_to targets the gripper tool site. grasp closes the fingers (only "
    "succeeds with a real fingertip-cube contact). release opens them. "
    "Approach note: if a previous move_to pushed the cube, use the NEW cube "
    "position from state (not the old one) and descend from directly above "
    "(pre_grasp_point). Descend target depth: z = cube_z + 0.012 exactly; "
    "NEVER go below cube_z + 0.010 - deeper descents collide with the wrist "
    "assembly and push the cube away. The state includes last_action error "
    "feedback (last_err_m): if it is large, pick a closer intermediate target. "
    f"{WORKSPACE_HINT}."
)


class DecisionError(ValueError):
    """Raised when provider output is not a valid, catalogued decision."""


def build_prompt(obs: dict[str, Any], history: list[dict[str, Any]] | None = None) -> str:
    """Compact, privileged-truth-free state text (observe() content only).

    history carries the model's own prior decisions so a stateless completion
    call still sees its used intent_keys and past choices.
    """
    o = obs["observation"]
    decisions = [h.get("decision", h) for h in (history or [])]
    last_status = (history or [{}])[-1].get("status") if history else None
    return (
        f"state: tool={ [round(v, 4) for v in o['tool_pos']] } "
        f"cube={ [round(v, 4) for v in o['cube']['pos']] } "
        f"tray={ [round(v, 4) for v in o['tray_pos']] } "
        f"fingers={ [round(v, 4) for v in o['finger_qpos']] } "
        f"pre_grasp_hint={ [round(v, 4) for v in o.get('pre_grasp_point', [0, 0, 0])] } "
        f"last_action={ json.dumps(last_status, ensure_ascii=False) if last_status else 'none' } "
        f"actions_so_far={ json.dumps(decisions, ensure_ascii=False) }"
    )


def parse_decision(content: str) -> dict[str, Any]:
    """Parse and validate a provider decision; raise DecisionError if invalid."""
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    brace = text.find("{")
    end = text.rfind("}")
    if brace >= 0 and end > brace:
        text = text[brace:end + 1]
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise DecisionError(f"decision is not JSON: {e}") from None
    if not isinstance(raw, dict):
        raise DecisionError("decision is not an object")
    skill = str(raw.get("skill", ""))
    if skill not in SKILL_CATALOG:
        raise DecisionError(f"unknown skill '{skill}'")
    params = raw.get("params") or {}
    required = SKILL_CATALOG[skill]
    missing = [k for k in required if k not in params]
    if missing:
        raise DecisionError(f"skill '{skill}' missing params {missing}")
    if skill == "move_to":
        clean_params = {k: float(params[k]) for k in required}
    else:  # grasp/release take no params; stop carries a string reason
        clean_params = {k: params[k] for k in required}
    clean = {"skill": skill, "params": clean_params, "intent_key": str(raw.get("intent_key", ""))}
    if not clean["intent_key"]:
        raise DecisionError("decision missing intent_key")
    return clean


class DecisionProvider(Protocol):
    model_used: str

    def decide(self, state_text: str) -> str:
        """Return raw provider content (str) for one decision round."""
        ...


class ScriptedStubProvider:
    """Deterministic stub for MECHANISM tests only (budgets, replans, contracts).

    It is never presented as model autonomy; real autonomy evidence comes from
    GLMHttpProvider episodes whose traces record model_used + raw decisions.
    """

    def __init__(self, script: list[str], model_used: str = "stub/scripted"):
        self._script = list(script)
        self.model_used = model_used
        self.calls = 0

    def decide(self, state_text: str) -> str:
        self.calls += 1
        if not self._script:
            return '{"skill": "stop", "params": {"reason": "script exhausted"}, "intent_key": "kEnd"}'
        return self._script.pop(0)


class FlakyStubProvider(ScriptedStubProvider):
    """Stub that fails N times before answering (provider timeout/5xx recovery)."""

    def __init__(self, script: list[str], failures: int, model_used: str = "stub/flaky"):
        super().__init__(script, model_used)
        self._remaining_failures = int(failures)

    def decide(self, state_text: str) -> str:
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise TimeoutError("simulated provider timeout")
        return super().decide(state_text)

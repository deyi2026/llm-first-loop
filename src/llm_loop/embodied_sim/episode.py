"""Real-provider episode runner for M1 (budget-bounded, learning off).

Drives the thin embodied interface with provider decisions (glm/glm-5.3-flash
in the real gate script; ScriptedStubProvider only in mechanism tests, which
are never presented as autonomy). Privileged truth (oracle verdicts) never
enters the model context: the model sees only observe() content and skill
status. Learning/memory writes are off by contract.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from llm_loop.embodied_sim.contract import GrantRevokedError
from llm_loop.embodied_sim.oracle import judge_place, make_receipt
from llm_loop.embodied_sim.policy import DecisionError

DEFAULT_MODEL_USED = "glm/glm-5.3-flash"


@dataclass(frozen=True)
class EpisodeBudget:
    max_provider_attempts: int = 6
    max_tool_actions: int = 8
    deadline_s: float = 180.0
    learning: str = "off"  # prereg comparison.learning


_DEFAULT_BUDGET = EpisodeBudget()


def run_episode(iface: Any, provider: Any, budget: EpisodeBudget = _DEFAULT_BUDGET,
                *, experiment_id: str = "M1-SIM-001", clock: Callable[[], float] | None = None,
                claim_kind: str = "place") -> dict[str, Any]:
    """Run ONE autonomous episode; return an honest trace + pending oracle receipt."""
    now: Callable[[], float] = clock or time.monotonic
    t0 = now()
    scene = iface.scene
    tray = scene.observe()["tray_pos"]
    grant_version = 1
    attempts = 0
    tool_actions = 0
    replans = 0
    trace: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    terminated_by: str | None = None
    stop_receipts: dict[str, Any] = {}
    last_local = {"ok": False, "evidence": {}}
    receipt: dict[str, Any] | None = None

    def elapsed() -> float:
        return now() - t0

    while terminated_by is None:
        # budget gates (fail-closed)
        if attempts >= budget.max_provider_attempts:
            terminated_by = "provider_attempt_budget_exhausted"
            break
        if tool_actions >= budget.max_tool_actions:
            terminated_by = "tool_action_budget_exhausted"
            break
        if elapsed() > budget.deadline_s:
            terminated_by = "episode_deadline_exceeded"
            break

        # observation freshness self-check (defensive; TTL enforced by kernel)
        epoch = scene.scene_epoch
        ticket = iface.kernel.issue_observation_ref(epoch)
        try:
            iface.kernel.check_observation(ticket, epoch)
        except Exception as e:
            trace.append({"event": "OBSERVATION_EXPIRED", "detail": str(e),
                          "observation_ref": ticket.ref})
            terminated_by = "observation_ref_invalid"
            break

        state_text = build_state(iface, history)
        try:
            raw = provider.decide(state_text)
        except Exception as e:  # provider timeout/5xx/network -> replan within budget
            attempts += 1
            replans += 1
            trace.append({"event": "provider_retry", "attempts": attempts,
                          "error": type(e).__name__})
            continue
        attempts += 1

        decision = provider.parse(raw) if hasattr(provider, "parse") else parse_raw(raw)
        if decision is None:
            replans += 1
            trace.append({"event": "decision_invalid", "attempts": attempts})
            continue

        skill = decision["skill"]
        if skill == "stop":
            req = iface.stop(str(decision["params"].get("reason", "model requested stop")))
            stop_receipts["request"] = req
            conf = iface.confirm_stop(req["stop_id"])
            stop_receipts["confirmation"] = conf
            trace.append({"event": "stop_two_phase", "request": req, "confirmation": conf})
            terminated_by = "stop_confirmed"
            break

        try:
            result = iface.execute_skill(skill, decision["params"],
                                         intent_key=decision["intent_key"],
                                         grant_version=grant_version)
        except GrantRevokedError as e:
            trace.append({"event": "GRANT_REVOKED", "detail": str(e)})
            terminated_by = "grant_revoked"
            break
        if "error" in result:
            trace.append({"event": "execute_rejected", "error": result["error"],
                          "detail": result})
            continue  # replan: model sees rejection in next state
        if result.get("idempotent"):
            trace.append({"event": "duplicate_intent_key", "action_id": result["action_id"]})
            continue
        tool_actions += 1

        status: dict[str, Any] = result
        while status["state"] == "running":
            iface.advance(60)
            status = iface.get_action_status(result["action_id"])
            if elapsed() > budget.deadline_s:
                break
        trace.append({"event": "tool_action", "decision": decision, "status": status,
                      "t_s": round(elapsed(), 3)})
        history.append({"decision": decision, "status": status})
        if skill == "release" and status["state"] == "done":
            # let the released object settle under gravity before judging place
            scene.step(150)

        # privileged success check (never enters model context)
        snap = scene.oracle_snapshot()
        if claim_kind == "place":
            ok, ev = judge_place(snap, tray)
            last_local = {"ok": ok, "evidence": ev}
            receipt = make_receipt(snap, "place", ok, ev, experiment_id, scene.scene_epoch)
            if ok:
                terminated_by = "place_verified_locally_pending_oracle"
                break

    if terminated_by is None:
        terminated_by = "no_progress_halt"
    return {
        "experiment_id": experiment_id,
        "model_used": provider.model_used,
        "learning": budget.learning,
        "terminated_by": terminated_by,
        "provider_attempts": attempts,
        "tool_actions": tool_actions,
        "replans": replans,
        "elapsed_s": round(elapsed(), 3),
        "budget": {"max_provider_attempts": budget.max_provider_attempts,
                   "max_tool_actions": budget.max_tool_actions,
                   "deadline_s": budget.deadline_s},
        "stop_receipts": stop_receipts,
        "local_verdict": last_local,
        "oracle_receipt": receipt,
        "oracle_execution": (receipt or {}).get("oracle_execution", "not_issued"),
        "trace": trace,
    }


def parse_raw(raw: str) -> dict[str, Any] | None:
    from llm_loop.embodied_sim.policy import parse_decision
    try:
        return parse_decision(raw)
    except DecisionError:
        return None


def build_state(iface: Any, history: list[dict[str, Any]]) -> str:
    from llm_loop.embodied_sim.policy import build_prompt
    return build_prompt(iface.observe(), history)

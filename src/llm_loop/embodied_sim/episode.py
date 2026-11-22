"""Real-provider episode runner (M1 budget-bounded; M2 goal-bound).

Drives the thin embodied interface with provider decisions (glm/glm-5.3-flash
in the real gate script; ScriptedStubProvider only in mechanism tests, which
are never presented as autonomy). Privileged truth (oracle verdicts) never
enters the model context: the model sees only observe() content and skill
status. Learning/memory writes are off by contract.

M2 (issue #79): the target is a *moving* goal. The runner never caches a target
pose across actions: `_GoalState` re-observes the target and the scene epoch
before every decision, after every action and again at verification, and binds
every claim to the goal observed for it. When the goal moves or the scene
resets, stale target evidence is invalidated and the episode replans from the
fresh observation instead of silently accepting the old goal. An indeterminate
execution state HOLDs as UNKNOWN instead of producing a claim.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from llm_loop.embodied_sim.contract import GrantRevokedError
from llm_loop.embodied_sim.goal_binding import GoalBinding, bind_goal
from llm_loop.embodied_sim.oracle import judge_place, make_receipt
from llm_loop.embodied_sim.policy import DecisionError

DEFAULT_MODEL_USED = "glm/glm-5.3-flash"

GOAL_REBIND_BUDGET_EXHAUSTED = "goal_rebind_budget_exhausted"
HOLD_UNKNOWN = "hold_unknown_pending_reconciliation"
CLAIM_PENDING = "pending_oracle"
CLAIM_HOLD = "hold_unknown"

SCENE_RESET = "SCENE_RESET"
GOAL_MOVED_BETWEEN_ACTIONS = "GOAL_CHANGED_BETWEEN_ACTIONS"
GOAL_MOVED_MID_ACTION = "GOAL_CHANGED_MID_ACTION"
GOAL_MOVED_BEFORE_VERIFICATION = "GOAL_CHANGED_BEFORE_VERIFICATION"
DUPLICATE_STALE = "DUPLICATE_INTENT_STALE_GOAL"

REPLAN = "replan"
ABORT = "abort"
_PROCEED = None


@dataclass(frozen=True)
class EpisodeBudget:
    max_provider_attempts: int = 6
    max_tool_actions: int = 8
    deadline_s: float = 180.0
    learning: str = "off"  # prereg comparison.learning
    max_goal_rebinds: int = 4  # M2: bounds a target that never stops moving


_DEFAULT_BUDGET = EpisodeBudget()


class _GoalState:
    """M2 bookkeeping: which goal the next claim may be bound to, and what voids it.

    Every method that detects a goal/epoch change returns REPLAN (the caller must
    replan from a fresh observation) or ABORT (rebind budget spent) or _PROCEED.
    Invalidation is fail-closed: evidence formed against the old goal is dropped
    and can never be re-used, and the claim state is demoted to hold_unknown
    until a fresh verification succeeds.
    """

    def __init__(self, scene: Any, budget: EpisodeBudget) -> None:
        self.scene = scene
        self.budget = budget
        self.goal: GoalBinding = bind_goal(scene, version=1)
        self.goal_rebinds = 0
        self.stale_invalidated = 0
        self.claim_state = "none"
        self.trace: list[dict[str, Any]] = []
        self.history: list[dict[str, Any]] = []
        self.last_local: dict[str, Any] = {"ok": False, "evidence": {}}
        self.receipt: dict[str, Any] | None = None
        self.goal_history: list[dict[str, Any]] = [{"event": "GOAL_BOUND", **self.goal.receipt_fields()}]
        self.action_goal: dict[str, str] = {}
        self.action_history: dict[str, int] = {}

    # -- invalidation ------------------------------------------------------
    def _invalidate(self, index: int | None, reason: str) -> None:
        if index is None or index < 0 or index >= len(self.history):
            return
        entry = self.history[index]
        if entry.get("stale_goal"):
            return
        entry["stale_goal"] = True
        entry["invalidation"] = reason
        self.stale_invalidated += 1

    def invalidate_claims(self, reason: str, *, all_history: bool = False,
                          action_id: str | None = None) -> None:
        """Drop target evidence that was formed against the previous goal."""
        if all_history:
            for i in range(len(self.history)):
                self._invalidate(i, reason)
        elif action_id is not None:
            self._invalidate(self.action_history.get(action_id), reason)
        if self.last_local.get("evidence") or self.last_local.get("ok"):
            self.last_local = {"ok": False, "evidence": {}, "invalidated": reason}
            self.stale_invalidated += 1
        self.receipt = None

    def rebind(self, reason: str) -> bool:
        """Accept the freshly observed goal as the new baseline; False = budget spent."""
        if self.goal_rebinds >= self.budget.max_goal_rebinds:
            return False
        self.goal_rebinds += 1
        self.goal = bind_goal(self.scene, version=self.goal.version + 1)
        self.claim_state = CLAIM_HOLD
        self.goal_history.append({"event": reason, **self.goal.receipt_fields()})
        self.trace.append({"event": reason, "goal_version": self.goal.version,
                           "goal_digest": self.goal.digest, "scene_epoch": self.goal.scene_epoch})
        return True

    def _rebind_or_abort(self, reason: str, **kwargs: Any) -> str:
        """Void stale evidence, accept the fresh goal, and require a replan.

        Every call site observes a goal change, so success means the episode
        must plan again from the fresh observation — never fall through and use
        the decision that was formed against the old goal.
        """
        self.invalidate_claims(reason, **kwargs)
        return REPLAN if self.rebind(reason) else ABORT

    # -- observation points ------------------------------------------------
    def precheck(self) -> str | None:
        """Before each decision: never plan against a goal that already moved."""
        observed = bind_goal(self.scene, version=self.goal.version)
        if observed.scene_epoch != self.goal.scene_epoch:
            return self._rebind_or_abort(SCENE_RESET, all_history=True)
        if observed.digest != self.goal.digest:
            return self._rebind_or_abort(GOAL_MOVED_BETWEEN_ACTIONS)
        return _PROCEED

    def duplicate(self, action_id: str) -> str | None:
        """A duplicate intent is only replayable for the goal it ran against."""
        prior = self.action_goal.get(action_id)
        current = bind_goal(self.scene, version=self.goal.version)
        if prior is not None and (current.digest != prior
                                  or current.scene_epoch != self.goal.scene_epoch):
            return self._rebind_or_abort(DUPLICATE_STALE, action_id=action_id)
        self.trace.append({"event": "duplicate_intent_key", "action_id": action_id})
        return _PROCEED

    def after_action(self, action_id: str, status: dict[str, Any]) -> str | None:
        """Immediately after the action: epoch reset voids everything, a moved
        goal voids this action's evidence."""
        post = bind_goal(self.scene, version=self.goal.version)
        if post.scene_epoch != self.goal.scene_epoch:
            return self._rebind_or_abort(SCENE_RESET, all_history=True)
        if post.digest != self.goal.digest:
            return self._rebind_or_abort(GOAL_MOVED_MID_ACTION, action_id=action_id)
        return _PROCEED

    def hold(self, status: dict[str, Any]) -> None:
        self.trace.append({"event": "HOLD_UNKNOWN", "reason": "indeterminate_execution",
                           "action_id": status.get("action_id"), "status": status})
        self.claim_state = CLAIM_HOLD

    def record(self, decision: dict[str, Any], status: dict[str, Any], action_id: str,
               *, t_s: float) -> None:
        self.trace.append({"event": "tool_action", "decision": decision, "status": status,
                           "t_s": t_s, "goal_version": self.goal.version,
                           "goal_digest": self.goal.digest})
        self.history.append({"decision": decision, "status": status,
                             "goal_digest": self.goal.digest})
        self.action_history[action_id] = len(self.history) - 1
        self.action_goal[action_id] = self.goal.digest

    def record_voided(self, decision: dict[str, Any], status: dict[str, Any],
                      *, goal_version: int, goal_digest: str, t_s: float) -> None:
        """Keep an executed action visible, tagged with the goal it RAN against.

        Its evidence is void (the goal moved mid-action). Tagging it with the
        rebound goal would attribute a stale-planned action to the new target,
        so it carries the executed goal's version/digest and a `stale_goal`
        marker instead.
        """
        self.trace.append({"event": "tool_action", "decision": decision, "status": status,
                           "t_s": t_s, "goal_version": goal_version,
                           "goal_digest": goal_digest, "stale_goal": True})
        self.history.append({"decision": decision, "status": status,
                             "goal_digest": goal_digest, "stale_goal": True})

    def verify(self) -> GoalBinding | str:
        """At verification: bind the goal observed *now*; never reuse an older one."""
        verify_goal = bind_goal(self.scene, version=self.goal.version)
        if verify_goal.scene_epoch != self.goal.scene_epoch:
            return self._rebind_or_abort(SCENE_RESET, all_history=True)
        if verify_goal.digest != self.goal.digest:
            return self._rebind_or_abort(GOAL_MOVED_BEFORE_VERIFICATION)
        return verify_goal

    def judge_place(self, binding: GoalBinding, experiment_id: str) -> dict[str, Any]:
        snap = self.scene.oracle_snapshot()
        ok, evidence = judge_place(snap, list(binding.pos))
        self.last_local = {"ok": ok, "evidence": evidence, "goal": binding.receipt_fields()}
        self.receipt = make_receipt(snap, "place", ok, evidence, experiment_id,
                                    self.scene.scene_epoch, goal_binding=binding.receipt_fields())
        if ok:
            self.claim_state = CLAIM_PENDING
        return self.receipt


def _budget_halt(attempts: int, actions: int, budget: EpisodeBudget,
                 elapsed: Callable[[], float]) -> str | None:
    """Fail-closed budget gates: each one ends the episode, none is advisory."""
    if attempts >= budget.max_provider_attempts:
        return "provider_attempt_budget_exhausted"
    if actions >= budget.max_tool_actions:
        return "tool_action_budget_exhausted"
    if elapsed() > budget.deadline_s:
        return "episode_deadline_exceeded"
    return None


def _fresh_observation(iface: Any, scene: Any, trace: list[dict[str, Any]]) -> str | None:
    """Defensive observation-refresh self-check (TTL is enforced by the kernel)."""
    epoch = scene.scene_epoch
    ticket = iface.kernel.issue_observation_ref(epoch)
    try:
        iface.kernel.check_observation(ticket, epoch)
    except Exception as e:
        trace.append({"event": "OBSERVATION_EXPIRED", "detail": str(e),
                      "observation_ref": ticket.ref})
        return "observation_ref_invalid"
    return None


def _decide(provider: Any, iface: Any, history: list[dict[str, Any]]
            ) -> tuple[dict[str, Any] | None, str | None]:
    """One provider call. Returns (decision, provider_error_name)."""
    try:
        raw = provider.decide(build_state(iface, history))
    except Exception as e:  # provider timeout/5xx/network -> replan within budget
        return None, type(e).__name__
    return (provider.parse(raw) if hasattr(provider, "parse") else parse_raw(raw)), None


def _stop_two_phase(iface: Any, decision: dict[str, Any],
                    trace: list[dict[str, Any]]) -> dict[str, Any]:
    req = iface.stop(str(decision["params"].get("reason", "model requested stop")))
    conf = iface.confirm_stop(req["stop_id"])
    trace.append({"event": "stop_two_phase", "request": req, "confirmation": conf})
    return {"request": req, "confirmation": conf}


def _execute(iface: Any, decision: dict[str, Any], grant_version: int,
             history: list[dict[str, Any]], trace: list[dict[str, Any]]
             ) -> tuple[dict[str, Any] | None, str | None]:
    """Execute one skill. Returns (result, "grant_revoked"|REPLAN|None)."""
    try:
        result = iface.execute_skill(decision["skill"], decision["params"],
                                     intent_key=decision["intent_key"],
                                     grant_version=grant_version)
    except GrantRevokedError as e:
        trace.append({"event": "GRANT_REVOKED", "detail": str(e)})
        return None, "grant_revoked"
    if "error" in result:
        trace.append({"event": "execute_rejected", "error": result["error"],
                      "decision": decision, "detail": result})
        # A rejected action must be visible in the next model observation,
        # otherwise the model repeats the same invalid decision forever.
        history.append({"decision": decision,
                        "status": {"state": "rejected", "error": result["error"],
                                   "reason": result.get("reason")}})
        return None, REPLAN
    return result, None


def _settle(iface: Any, result: dict[str, Any], elapsed: Callable[[], float],
            budget: EpisodeBudget) -> dict[str, Any]:
    status = result
    while status["state"] == "running":
        iface.advance(60)
        status = iface.get_action_status(result["action_id"])
        if elapsed() > budget.deadline_s:
            break
    return status


def run_episode(iface: Any, provider: Any, budget: EpisodeBudget = _DEFAULT_BUDGET,
                *, experiment_id: str = "M1-SIM-001", clock: Callable[[], float] | None = None,
                claim_kind: str = "place") -> dict[str, Any]:
    """Run ONE autonomous episode; return an honest trace + goal-bound receipt."""
    now: Callable[[], float] = clock or time.monotonic
    t0 = now()
    scene = iface.scene
    goals = _GoalState(scene, budget)
    attempts = tool_actions = replans = 0
    terminated_by: str | None = None
    stop_receipts: dict[str, Any] = {}

    def elapsed() -> float:
        return now() - t0

    while terminated_by is None:
        halted = _budget_halt(attempts, tool_actions, budget, elapsed)
        if halted is not None:
            terminated_by = halted
            break
        halted = _fresh_observation(iface, scene, goals.trace)
        if halted is not None:
            terminated_by = halted
            break
        # M2: the goal may move between actions; never plan against a stale one.
        verdict = goals.precheck()
        if verdict is ABORT:
            terminated_by = GOAL_REBIND_BUDGET_EXHAUSTED
            break
        if verdict is REPLAN:
            replans += 1
            continue
        decision, provider_error = _decide(provider, iface, goals.history)
        attempts += 1
        if provider_error is not None:
            replans += 1
            goals.trace.append({"event": "provider_retry", "attempts": attempts,
                                "error": provider_error})
            continue
        if decision is None:
            replans += 1
            goals.trace.append({"event": "decision_invalid", "attempts": attempts})
            continue
        if decision["skill"] == "stop":
            stop_receipts = _stop_two_phase(iface, decision, goals.trace)
            terminated_by = "stop_confirmed"
            break
        result, failure = _execute(iface, decision, 1, goals.history, goals.trace)
        if failure == "grant_revoked":
            terminated_by = "grant_revoked"
            break
        if failure is REPLAN:
            replans += 1
            continue
        if result.get("idempotent"):
            verdict = goals.duplicate(str(result["action_id"]))
            if verdict is ABORT:
                terminated_by = GOAL_REBIND_BUDGET_EXHAUSTED
                break
            replans += 1 if verdict is REPLAN else 0
            continue
        tool_actions += 1
        executed_version, executed_digest = goals.goal.version, goals.goal.digest
        status = _settle(iface, result, elapsed, budget)
        # M2: re-observe immediately after the action, before any judgement.
        verdict = goals.after_action(str(result["action_id"]), status)
        if verdict is ABORT:
            terminated_by = GOAL_REBIND_BUDGET_EXHAUSTED
            break
        if verdict is REPLAN:
            # The action ran against the previous goal: keep it visible in the
            # trace/history, but never attribute it to the goal it did not run
            # against (its evidence was voided by the rebind).
            goals.record_voided(decision, status, goal_version=executed_version,
                                goal_digest=executed_digest, t_s=round(elapsed(), 3))
            replans += 1
            continue
        if status["state"] != "done":
            goals.hold(status)
            terminated_by = HOLD_UNKNOWN
            break
        goals.record(decision, status, str(result["action_id"]), t_s=round(elapsed(), 3))
        if decision["skill"] == "release" and status["state"] == "done":
            scene.step(150)  # let the released object settle before judging place
        # M2: verify against a goal observed at verification time, not earlier.
        verify_goal = goals.verify()
        if verify_goal is ABORT:
            terminated_by = GOAL_REBIND_BUDGET_EXHAUSTED
            break
        if verify_goal is REPLAN:
            replans += 1
            continue
        if claim_kind == "place":
            goals.judge_place(verify_goal, experiment_id)
            if goals.claim_state == CLAIM_PENDING:
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
                   "deadline_s": budget.deadline_s,
                   "max_goal_rebinds": budget.max_goal_rebinds},
        "claim_state": goals.claim_state,
        "goal": goals.goal.receipt_fields(),
        "goal_version": goals.goal.version,
        "goal_rebinds": goals.goal_rebinds,
        "stale_evidence_invalidated": goals.stale_invalidated,
        "goal_history": goals.goal_history,
        "stop_receipts": stop_receipts,
        "local_verdict": goals.last_local,
        "oracle_receipt": goals.receipt,
        "oracle_execution": (goals.receipt or {}).get("oracle_execution", "not_issued"),
        "trace": goals.trace,
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

#!/usr/bin/env python3
"""One diagnostic L3 failure/recovery smoke; NOT a frozen paired trial.

Only the FIRST grasp decision is deliberately scripted to provoke a real
no-contact failure on a fresh UID463 Host scene. All subsequent decisions
come from the real GLM provider through the unchanged Host episode executor.
The Host performs the actual grasp and returns its actual failure status;
no action receipt, Oracle verdict, or simulator state is forged.

The scripted decision consumes one of the same six decision attempts and one
of the same eight tool actions. Both B1 and B2 use smoke seed 9 only. The
result discloses the injected decision and the number of REAL model calls.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from m1_gate_c_host_episode import (
    BUDGET,
    ROOT,
    HostLinkError,
    HostOracleLink,
    HostStaleSceneError,
    fresh_precheck,
    load_run_identity,
    run_host_episode,
    validate_run_identity,
)

from llm_loop.embodied_sim.attestation import AttestationUnavailableError
from llm_loop.embodied_sim.trial import EXPERIMENT_ID


def validate_probe_trial(run: dict[str, Any]) -> str:
    validate_run_identity(run)
    trial = run.get("trial")
    if (run["experiment_id"] != EXPERIMENT_ID
            or not isinstance(trial, dict)
            or trial.get("phase") != "smoke"
            or trial.get("trial_index") != 9
            or trial.get("seed") != 9
            or trial.get("arm") not in ("B1", "B2")):
        raise HostLinkError("L3 diagnostic requires root-selected smoke seed 9")
    return str(trial["arm"])


class OneScriptedFaultThenLiveModel:
    """Disclosed, budgeted fault trigger; never impersonates a model call."""

    def __init__(self, live: Any):
        self.live = live
        self.model_used = live.model_used
        self.scripted_decisions = 0
        self.real_model_attempts = 0

    def decide(self, state_text: str) -> str:
        if self.scripted_decisions == 0:
            self.scripted_decisions = 1
            return json.dumps({"skill": "grasp", "params": {},
                               "intent_key": "l3-diagnostic-fault"})
        self.real_model_attempts += 1
        return str(self.live.decide(state_text))


def assess_probe(result: dict[str, Any], *, arm: str) -> tuple[str, bool]:
    trace = result.get("trace", [])
    first_action = next((t for t in trace if t.get("event") == "tool_action"), {})
    actual_failure = (
        first_action.get("seq") == 1
        and first_action.get("decision", {}).get("skill") == "grasp"
        and first_action.get("status", {}).get("state") == "failed"
        and any(t.get("event") == "grasp_failed" and t.get("seq") == 1
                for t in trace)
    )
    if not actual_failure or result.get("terminated_by") == "host_fail_closed":
        return "L3_PROBE_HOLD", False
    if arm == "B1":
        return "L3_B1_CONTROL_RECORDED", True
    recovered = (
        result.get("managed_recoveries") == 1
        and any(t.get("event") == "managed_grasp_recovery_release"
                and t.get("seq") == 2
                and t.get("status", {}).get("state") == "done"
                for t in trace)
        and result.get("terminated_by") == "place_host_verified"
        and all(result.get("host_claims", {}).get(k, {}).get("status")
                == "VERIFIED_BY_ORACLE" for k in ("grasp", "place"))
        and result.get("provider_attempts", 99) <= BUDGET["max_provider_attempts"]
        and result.get("tool_actions", 99) <= BUDGET["max_tool_actions"]
        and result.get("elapsed_s", 999) <= BUDGET["deadline_s"]
    )
    return ("L3_B2_HOST_RECOVERY_VERIFIED" if recovered else "L3_B2_RECOVERY_HOLD",
            recovered)


def main(argv: list[str]) -> int:
    if argv != ["--l3-smoke-probe"]:
        print(json.dumps({"status": "HOLD", "reason": "explicit --l3-smoke-probe required"}))
        return 2
    try:
        run = load_run_identity()
        arm = validate_probe_trial(run)
        link = HostOracleLink(run)
        fresh = fresh_precheck(link)
    except (HostLinkError, HostStaleSceneError, AttestationUnavailableError,
            OSError, ValueError) as exc:
        print(json.dumps({"status": "HOLD", "reason": str(exc)}))
        return 2
    trial = run["trial"]
    path = ROOT / "experiments/embodied/m1/m1-sim-002" / (
        f"l3_probe_{trial['phase']}_{arm}_{trial['trial_index']:02d}_{run['run_id']}.json")
    if path.exists() or path.is_symlink():
        print(json.dumps({"status": "HOLD", "reason": "diagnostic evidence already exists"}))
        return 2

    try:
        from m1_gate_c_episode import GLMHttpProvider
        live = GLMHttpProvider()
        if live.model_used != "glm/glm-5.3-flash":
            raise ValueError("wrong live model identity")
    except Exception as exc:
        print(json.dumps({"status": "HOLD",
                          "reason": f"provider unavailable: {type(exc).__name__}"}))
        return 2

    provider = OneScriptedFaultThenLiveModel(live)
    # The scripted Host fault is NOT a Provider call. The unchanged executor
    # counts decisions, so reserve one extra internal slot for that disclosed
    # diagnostic action; still cap REAL model attempts at the frozen six.
    internal_budget = {**BUDGET,
                       "max_provider_attempts": BUDGET["max_provider_attempts"] + 1}
    result = run_host_episode(provider, link, fresh_receipt=fresh,
                              budget=internal_budget,
                              auto_recover_failed_grasp=(arm == "B2"))
    internal_attempts = result["provider_attempts"]
    accounting_ok = (
        internal_attempts == provider.scripted_decisions + provider.real_model_attempts
        and provider.scripted_decisions == 1
        and provider.real_model_attempts <= BUDGET["max_provider_attempts"]
    )
    result["provider_attempts"] = provider.real_model_attempts
    result["provider_calls_bounded"] = [
        {k: call.get(k) for k in ("latency_ms", "status", "finish_reason")}
        for call in live.calls]
    result["l3_diagnostic"] = {
        "diagnostic_only": True,
        "not_a_frozen_paired_trial": True,
        "scripted_first_decision": "grasp without initial move_to",
        "scripted_decisions_counted_in_budget": provider.scripted_decisions,
        "real_model_attempts": provider.real_model_attempts,
        "real_model_http_responses": len(live.calls),
        "provider_attempts_including_scripted_decision": internal_attempts,
        "real_model_attempt_budget": BUDGET["max_provider_attempts"],
        "internal_decision_budget_including_scripted_probe": internal_budget["max_provider_attempts"],
        "accounting_verified": accounting_ok,
        "model_decisions_after_fault": provider.real_model_attempts > 0,
    }
    status, accepted = assess_probe(result, arm=arm)
    if not accounting_ok:
        status, accepted = "L3_PROBE_ACCOUNTING_HOLD", False
    result["l3_diagnostic"]["assessment"] = status
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": status, "model_used": live.model_used,
                      "real_model_attempts": provider.real_model_attempts,
                      "real_model_http_responses": len(live.calls),
                      "tool_actions": result["tool_actions"],
                      "terminated_by": result["terminated_by"],
                      "evidence": str(path)}))
    return 0 if accepted else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

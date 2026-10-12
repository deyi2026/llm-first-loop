from __future__ import annotations

from copy import deepcopy

from evals.browser_smc_peer_capability_routing_ab_mf534r2.protocol import (
    build_plan,
    qualification_gate,
)


def _worker(*, first_ok: bool = True, cross_fail: bool = False) -> dict:
    calls = []
    if first_ok:
        calls.append(
            {
                "index": 1,
                "name": "browser_operate",
                "status": "success",
                "operation_do": "navigate",
            }
        )
    elif cross_fail:
        calls.extend(
            [
                {
                    "index": 1,
                    "name": "browser_perceive",
                    "status": "failure",
                    "perceive_action": "navigate",
                },
                {
                    "index": 2,
                    "name": "browser_operate",
                    "status": "success",
                    "operation_do": "navigate",
                },
            ]
        )
    return {
        "surface_exact": True,
        "fallback_used": False,
        "tool_calls": calls,
        "tool_call_count": len(calls),
        "operation_tool_failure_count": 0,
        "operation_tool_error_count": 0,
        "direct_atomic_browser_call_count": 0,
        "duplicate_successful_mutation_count": 0,
        "operation_automatic_retry_true_count": 0,
        "task_completion_violation_count": 0,
        "undeclared_boundary_continuation_count": 0,
        "operation_unparsed_result_count": 0,
        "protocol_repair_episode_count": int(cross_fail),
        "get_tool_schema_count": 0,
        "perceive_tool_failure_count": int(cross_fail),
        "rounds": 1,
        "tokens_in": 10,
        "tokens_out": 2,
        "cache_hit_tokens": 5,
        "action_receipt_facts": {"automatic_retry_true_count": 0},
    }


def _record(row: dict, *, first_ok: bool = True, cross_fail: bool = False) -> dict:
    return {
        **row,
        "status": "PASS",
        "oracle": {"pass": True},
        "worker": _worker(first_ok=first_ok, cross_fail=cross_fail),
        "security_agent_spawned": False,
    }


def test_plan_is_exact_paired_counterbalanced_matrix() -> None:
    plan = build_plan()
    assert len(plan) == 12
    pairs: dict[str, list[str]] = {}
    for row in plan:
        pairs.setdefault(str(row["pair_id"]), []).append(str(row["arm"]))
    assert all(sorted(arms) == ["A", "B"] for arms in pairs.values())
    assert [row["arm"] for row in plan] == ["A", "B", "B", "A", "A", "B", "B", "A", "A", "B", "B", "A"]


def test_gate_keeps_first_routing_failure_even_when_task_recovers_and_passes() -> None:
    records = [_record(row) for row in build_plan()]
    a_row = next(row for row in records if row["arm"] == "A" and row["pair_id"] == "delayed_wait-r1")
    a_row["worker"] = _worker(first_ok=False, cross_fail=True)

    gate = qualification_gate(records)

    assert gate["measurement_valid"] is True
    assert gate["arms"]["A"]["task_pass"] == 6
    assert gate["arms"]["A"]["first_call_routing_pass"] == 5
    assert gate["arms"]["A"]["cross_capability_failures"] == 1
    assert gate["arms"]["A"]["recovered_later"] == 1
    assert gate["arms"]["B"]["first_call_routing_pass"] == 6
    assert gate["treatment_signal"] == "IMPROVED"
    assert gate["task_success_overrides_routing"] is False


def test_gate_reports_no_observed_improvement_when_both_arms_are_clean() -> None:
    records = [_record(row) for row in build_plan()]
    gate = qualification_gate(deepcopy(records))
    assert gate["measurement_valid"] is True
    assert gate["arms"]["A"]["first_call_routing_pass"] == 6
    assert gate["arms"]["B"]["first_call_routing_pass"] == 6
    assert gate["treatment_signal"] == "NO_OBSERVED_IMPROVEMENT"

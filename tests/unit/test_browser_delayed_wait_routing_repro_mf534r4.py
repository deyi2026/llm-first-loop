from __future__ import annotations

from copy import deepcopy

from evals.browser_smc_delayed_wait_routing_repro_mf534r4.protocol import (
    build_plan,
    diagnostic_gate,
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


def test_plan_is_exact_eight_pair_delayed_wait_counterbalance() -> None:
    plan = build_plan()
    assert len(plan) == 16
    assert {row["task_id"] for row in plan} == {"delayed_wait"}
    pairs: dict[str, list[str]] = {}
    for row in plan:
        pairs.setdefault(str(row["pair_id"]), []).append(str(row["arm"]))
    assert len(pairs) == 8
    assert all(sorted(arms) == ["A", "B"] for arms in pairs.values())
    assert [row["arm"] for row in plan] == [
        "A", "B", "B", "A", "A", "B", "B", "A",
        "A", "B", "B", "A", "A", "B", "B", "A",
    ]


def test_clean_control_is_inconclusive_ceiling_not_no_improvement() -> None:
    records = [_record(row) for row in build_plan()]
    gate = diagnostic_gate(deepcopy(records))
    assert gate["measurement_valid"] is True
    assert gate["arms"]["A"]["first_call_routing_pass"] == 8
    assert gate["arms"]["B"]["first_call_routing_pass"] == 8
    assert gate["control_discriminator_observed"] is False
    assert gate["targeted_signal"] == "INCONCLUSIVE_CEILING"
    assert gate["full_qualification_authorized"] is False
    assert gate["production_change_authorized"] is False


def test_historical_style_failure_survives_recovery_and_can_discriminate() -> None:
    records = [_record(row) for row in build_plan()]
    for pair_id in ("delayed_wait-r1", "delayed_wait-r5"):
        a_row = next(row for row in records if row["arm"] == "A" and row["pair_id"] == pair_id)
        a_row["worker"] = _worker(first_ok=False, cross_fail=True)

    gate = diagnostic_gate(records)
    assert gate["measurement_valid"] is True
    assert gate["arms"]["A"]["task_pass"] == 8
    assert gate["arms"]["A"]["first_call_routing_pass"] == 6
    assert gate["arms"]["A"]["cross_capability_failures"] == 2
    assert gate["arms"]["A"]["recovered_later"] == 2
    assert gate["arms"]["B"]["first_call_routing_pass"] == 8
    assert gate["control_discriminator_observed"] is True
    assert gate["targeted_signal"] == "IMPROVED"
    assert gate["task_success_overrides_routing"] is False


def test_task_failure_invalidates_targeted_measurement() -> None:
    records = [_record(row) for row in build_plan()]
    records[0]["oracle"] = {"pass": False}
    records[0]["status"] = "TASK_FAIL"
    gate = diagnostic_gate(records)
    assert gate["measurement_valid"] is False
    assert gate["targeted_signal"] == "INVALID"

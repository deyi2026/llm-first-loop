"""Frozen targeted delayed-wait routing reproduction for MF534-R4."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from evals.browser_smc_cognition_preserving_actuation_mf534.protocol import (
    prompt_template_sha256,
)
from evals.browser_smc_peer_capability_routing_red_mf534r1.scorer import (
    score_historical_trace,
)

SCHEMA = "smc.browser_delayed_wait_routing_reproduction_mf534r4.v0.1"
SEED = 2026091702
ROUTING_RED_COMMIT = "3fe30b5c07a34394b6c46234c554d5d7789ff47e"
REF_KIND_RED_COMMIT = "ce688c0c3de6e2c48cfb54a729f0d7ba486a284f"
PRODUCTION_ANCHOR = "d908adbf58610e1c136ede69b33203acc7422207"

# Eight exact delayed_wait pairs. First-arm order alternates to avoid a fixed
# warm/cold or temporal ordering advantage. No other task enters this diagnostic.
PAIR_ORDER = tuple(
    ("delayed_wait", repeat, arm)
    for repeat in range(1, 9)
    for arm in (("A", "B") if repeat % 2 else ("B", "A"))
)


def build_plan(seed: int = SEED) -> list[dict[str, Any]]:
    if seed != SEED:
        raise ValueError("targeted delayed_wait plan seed is frozen")
    return [
        {
            "index": index,
            "task_id": task_id,
            "repeat": repeat,
            "pair_id": f"{task_id}-r{repeat}",
            "arm": arm,
            "prompt_template_sha256": prompt_template_sha256(task_id),
        }
        for index, (task_id, repeat, arm) in enumerate(PAIR_ORDER, start=1)
    ]


def plan_sha256(plan: list[dict[str, Any]]) -> str:
    raw = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def routing_score(record: dict[str, Any]) -> dict[str, Any]:
    worker = record.get("worker") or {}
    return score_historical_trace(
        {
            "tool_calls": list(worker.get("tool_calls") or []),
            "task_oracle_pass": bool((record.get("oracle") or {}).get("pass")),
        }
    )


def _worker_int(row: dict[str, Any], key: str) -> int:
    return int((row.get("worker") or {}).get(key) or 0)


def _receipt_int(row: dict[str, Any], key: str) -> int:
    facts = (row.get("worker") or {}).get("action_receipt_facts") or {}
    return int(facts.get(key) or 0)


def _arm_metrics(records: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    rows = [row for row in records if row.get("arm") == arm]
    routing = [dict(row.get("routing") or routing_score(row)) for row in rows]
    infra_valid = len(rows) == 8 and all(
        row.get("status") not in {"INFRA_FAIL", "TIMEOUT", "INVALID"} for row in rows
    )
    task_pass = sum(bool((row.get("oracle") or {}).get("pass")) for row in rows)
    first_pass = sum(bool(item.get("first_call_routing_valid")) for item in routing)
    cross_fail = sum(item.get("failure_kind") == "cross_capability_routing" for item in routing)
    recovered = sum(bool(item.get("recovered_later")) for item in routing)
    mechanical_safe = (
        len(rows) == 8
        and all(bool((row.get("worker") or {}).get("surface_exact")) for row in rows)
        and all(not bool((row.get("worker") or {}).get("fallback_used")) for row in rows)
        and all(not bool(row.get("security_agent_spawned")) for row in rows)
        and sum(_worker_int(row, "operation_tool_failure_count") for row in rows) == 0
        and sum(_worker_int(row, "operation_tool_error_count") for row in rows) == 0
        and sum(_worker_int(row, "direct_atomic_browser_call_count") for row in rows) == 0
        and sum(_worker_int(row, "duplicate_successful_mutation_count") for row in rows) == 0
        and sum(_receipt_int(row, "automatic_retry_true_count") for row in rows) == 0
        and sum(_worker_int(row, "operation_automatic_retry_true_count") for row in rows) == 0
        and sum(_worker_int(row, "task_completion_violation_count") for row in rows) == 0
        and sum(_worker_int(row, "undeclared_boundary_continuation_count") for row in rows) == 0
        and sum(_worker_int(row, "operation_unparsed_result_count") for row in rows) == 0
    )
    return {
        "rows": len(rows),
        "infra_valid": infra_valid,
        "task_pass": task_pass,
        "task_pass_required": 8,
        "mechanical_safe": mechanical_safe,
        "first_call_routing_pass": first_pass,
        "first_call_routing_required": 8,
        "cross_capability_failures": cross_fail,
        "recovered_later": recovered,
        "protocol_repair_episodes": sum(
            _worker_int(row, "protocol_repair_episode_count") for row in rows
        ),
        "get_tool_schema_calls": sum(_worker_int(row, "get_tool_schema_count") for row in rows),
        "perceive_failures": sum(_worker_int(row, "perceive_tool_failure_count") for row in rows),
        "operation_failures": sum(_worker_int(row, "operation_tool_failure_count") for row in rows),
        "rounds": sum(_worker_int(row, "rounds") for row in rows),
        "tokens_in": sum(_worker_int(row, "tokens_in") for row in rows),
        "tokens_out": sum(_worker_int(row, "tokens_out") for row in rows),
        "cache_hit_tokens": sum(_worker_int(row, "cache_hit_tokens") for row in rows),
        "tool_calls": sum(_worker_int(row, "tool_call_count") for row in rows),
    }


def diagnostic_gate(records: list[dict[str, Any]]) -> dict[str, Any]:
    plan = build_plan()
    expected = len(plan)
    complete = len(records) == expected and sorted(
        int(row.get("index") or 0) for row in records
    ) == list(range(1, expected + 1))
    arms = {arm: _arm_metrics(records, arm) for arm in ("A", "B")}

    paired: list[dict[str, Any]] = []
    if complete:
        by_pair_arm = {(str(row["pair_id"]), str(row["arm"])): row for row in records}
        for repeat in range(1, 9):
            pair_id = f"delayed_wait-r{repeat}"
            a_ok = bool(
                (by_pair_arm[(pair_id, "A")].get("routing") or {}).get(
                    "first_call_routing_valid"
                )
            )
            b_ok = bool(
                (by_pair_arm[(pair_id, "B")].get("routing") or {}).get(
                    "first_call_routing_valid"
                )
            )
            result = "tie"
            if b_ok and not a_ok:
                result = "B_win"
            elif a_ok and not b_ok:
                result = "A_win"
            paired.append({"pair_id": pair_id, "A": a_ok, "B": b_ok, "result": result})

    measurement_valid = (
        complete
        and arms["A"]["infra_valid"]
        and arms["B"]["infra_valid"]
        and arms["A"]["task_pass"] == 8
        and arms["B"]["task_pass"] == 8
        and arms["A"]["mechanical_safe"]
        and arms["B"]["mechanical_safe"]
    )
    control_discriminator_observed = arms["A"]["cross_capability_failures"] > 0
    if not measurement_valid:
        signal = "INVALID"
    elif not control_discriminator_observed:
        signal = "INCONCLUSIVE_CEILING"
    elif (
        arms["B"]["cross_capability_failures"] < arms["A"]["cross_capability_failures"]
        and arms["B"]["first_call_routing_pass"] > arms["A"]["first_call_routing_pass"]
    ):
        signal = "IMPROVED"
    elif arms["B"]["cross_capability_failures"] > arms["A"]["cross_capability_failures"]:
        signal = "REGRESSED"
    elif (
        arms["B"]["cross_capability_failures"] == arms["A"]["cross_capability_failures"]
        and arms["B"]["first_call_routing_pass"] == arms["A"]["first_call_routing_pass"]
    ):
        signal = "NO_OBSERVED_DIFFERENCE"
    else:
        signal = "MIXED"

    return {
        "schema": SCHEMA + ".gate",
        "diagnostic_only": True,
        "measurement_valid": measurement_valid,
        "control_discriminator_observed": control_discriminator_observed,
        "targeted_signal": signal,
        "complete_rows": len(records),
        "expected_rows": expected,
        "arms": arms,
        "paired_routing": paired,
        "task_success_overrides_routing": False,
        "full_qualification_authorized": False,
        "production_change_authorized": False,
    }

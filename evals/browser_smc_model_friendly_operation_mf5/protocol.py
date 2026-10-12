"""Frozen MF-5 paired A/B qualification protocol for model-friendly Browser operations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

SCHEMA = "smc.browser_model_friendly_operation_mf5.v0.1"
SEED = 2026091601
MODEL_REF = "cognilocal/ornith-1.5-35b-a3b-mlx"
ALLOWED_TOOLS = ("browser_semantic_operation", "get_tool_schema", "read_evidence")
# Pair order alternates which arm goes first, limiting warm-order bias while staying serial.
SLOTS = (
    ("click_commit", 1, ("A", "B")),
    ("fill_submit", 1, ("B", "A")),
    ("delayed_wait", 1, ("A", "B")),
    ("delayed_wait", 2, ("B", "A")),
    ("fill_submit", 2, ("A", "B")),
    ("click_commit", 2, ("B", "A")),
)


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    prompt_template: str
    expected: dict[str, Any]
    semantic_decision_points: int


TASKS = {
    "click_commit": TaskSpec(
        "click_commit",
        "打开 {url}。页面中有一个名为“Commit choice”的按钮。点击它一次，确认页面已提交后结束。只根据真实页面状态操作，不要伪造完成。",
        {"event": "commit", "count": 1},
        2,
    ),
    "fill_submit": TaskSpec(
        "fill_submit",
        "打开 {url}。把 Project code 填写为 AB-7319，然后点击“Save code”保存。确认页面已保存后结束。只根据真实页面状态操作，不要伪造完成。",
        {"event": "save_code", "value": "AB-7319"},
        3,
    ),
    "delayed_wait": TaskSpec(
        "delayed_wait",
        "打开 {url}。页面最初还未准备好；只有状态变成 Ready 后，“Finalize after ready”才可以点击。等待真实页面达到 Ready，然后点击一次并结束。不要在 Ready 之前提交。",
        {"event": "ready_click", "count": 1},
        3,
    ),
}


def prompt_for(task_id: str, url: str) -> str:
    return TASKS[task_id].prompt_template.format(url=url)


def prompt_template_sha256(task_id: str) -> str:
    return hashlib.sha256(TASKS[task_id].prompt_template.encode()).hexdigest()


def build_plan(seed: int = SEED) -> list[dict[str, Any]]:
    if seed != SEED:
        raise ValueError("MF5 seed frozen")
    rows = []
    idx = 1
    for task_id, repeat, arms in SLOTS:
        pair_id = f"{task_id}-r{repeat}"
        for arm in arms:
            rows.append(
                {
                    "index": idx,
                    "pair_id": pair_id,
                    "task_id": task_id,
                    "repeat": repeat,
                    "arm": arm,
                    "semantic_decision_points": TASKS[task_id].semantic_decision_points,
                    "prompt_template_sha256": prompt_template_sha256(task_id),
                }
            )
            idx += 1
    return rows


def plan_sha256(plan: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def judge(task_id: str, state: dict[str, Any]) -> dict[str, Any]:
    events = [x for x in state.get("events", []) if isinstance(x, dict)]
    if task_id == "click_commit":
        n = sum(x.get("kind") == "commit" for x in events)
        return {"pass": n == 1, "commit_count": n}
    if task_id == "fill_submit":
        vals = [str(x.get("value") or "") for x in events if x.get("kind") == "save_code"]
        obs = vals[-1] if vals else ""
        return {
            "pass": obs == "AB-7319" and len(vals) == 1,
            "save_count": len(vals),
            "value_match": obs == "AB-7319",
        }
    if task_id == "delayed_wait":
        hits = sum(x.get("kind") == "ready_click" for x in events)
        early = sum(x.get("kind") == "early_click" for x in events)
        return {
            "pass": hits == 1 and early == 0,
            "ready_click_count": hits,
            "early_click_count": early,
        }
    raise KeyError(task_id)


def arm_aggregate(records: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    rows = [r for r in records if r.get("arm") == arm]

    def wi(r, k):
        return int((r.get("worker") or {}).get(k) or 0)

    decision_points = sum(int(r.get("semantic_decision_points") or 0) for r in rows)
    model_turns = sum(wi(r, "rounds") for r in rows)
    return {
        "rows": len(rows),
        "task_pass": sum(bool((r.get("oracle") or {}).get("pass")) for r in rows),
        "rounds": model_turns,
        "tool_calls": sum(wi(r, "tool_call_count") for r in rows),
        "operation_calls": sum(wi(r, "operation_call_count") for r in rows),
        "operation_failures": sum(wi(r, "operation_tool_failure_count") for r in rows),
        "operation_errors": sum(wi(r, "operation_tool_error_count") for r in rows),
        "get_tool_schema": sum(wi(r, "get_tool_schema_count") for r in rows),
        "read_evidence": sum(wi(r, "read_evidence_count") for r in rows),
        "operation_arg_chars": sum(wi(r, "operation_arg_chars_total") for r in rows),
        "operation_result_chars": sum(wi(r, "operation_result_chars_total") for r in rows),
        "tokens_in": sum(wi(r, "tokens_in") for r in rows),
        "tokens_out": sum(wi(r, "tokens_out") for r in rows),
        "cache_hit_tokens": sum(wi(r, "cache_hit_tokens") for r in rows),
        "semantic_decision_points": decision_points,
        "srta": (model_turns / decision_points if decision_points else None),
        "auto_retry_true": sum(wi(r, "operation_automatic_retry_true_count") for r in rows),
        "task_completion_violations": sum(wi(r, "task_completion_violation_count") for r in rows),
        "direct_atomic_calls": sum(wi(r, "direct_atomic_browser_call_count") for r in rows),
    }


def qualification_gate(records: list[dict[str, Any]]) -> dict[str, Any]:
    complete = len(records) == 12 and sorted(int(r.get("index") or 0) for r in records) == list(
        range(1, 13)
    )
    arm_a = arm_aggregate(records, "A")
    arm_b = arm_aggregate(records, "B")
    hard = complete and all(
        r.get("status") not in {"INFRA_FAIL", "TIMEOUT", "INVALID"} for r in records
    )
    hard = hard and arm_a["task_pass"] == 6 and arm_b["task_pass"] == 6
    for agg in (arm_a, arm_b):
        hard = (
            hard
            and agg["operation_failures"] == 0
            and agg["operation_errors"] == 0
            and agg["auto_retry_true"] == 0
            and agg["task_completion_violations"] == 0
            and agg["direct_atomic_calls"] == 0
        )
    # Efficiency is conjunctive but avoids post-hoc cherry-picking a single metric: B must reduce
    # total support calls and model-visible operation bytes, and must not increase rounds.
    support_a = arm_a["get_tool_schema"] + arm_a["read_evidence"]
    support_b = arm_b["get_tool_schema"] + arm_b["read_evidence"]
    bytes_a = arm_a["operation_arg_chars"] + arm_a["operation_result_chars"]
    bytes_b = arm_b["operation_arg_chars"] + arm_b["operation_result_chars"]
    efficiency = (
        complete
        and support_b < support_a
        and bytes_b < bytes_a
        and arm_b["rounds"] <= arm_a["rounds"]
    )
    return {
        "schema": SCHEMA + ".gate",
        "pass": bool(hard and efficiency),
        "hard_pass": bool(hard),
        "efficiency_pass": bool(efficiency),
        "A": arm_a,
        "B": arm_b,
        "support_calls": {"A": support_a, "B": support_b},
        "model_visible_operation_chars": {"A": bytes_a, "B": bytes_b},
        "requirements": {
            "rows_per_arm": 6,
            "task_pass_per_arm": 6,
            "operation_failures": 0,
            "operation_errors": 0,
            "auto_retry": 0,
            "task_completion_violations": 0,
            "direct_atomic_calls": 0,
            "B_support_calls_lt_A": True,
            "B_operation_chars_lt_A": True,
            "B_rounds_lte_A": True,
        },
    }

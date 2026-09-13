"""Frozen FC2-B real-model qualification protocol for bounded Browser semantic operation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

SCHEMA = "smc.browser_bounded_semantic_operation_fc2.v0.1"
SEED = 2026091312
IMPLEMENTATION_COMMIT = "5789d767199d570893cba3304b8e463f6c36bcb7"
MODEL_REF = "cognilocal/ornith-1.5-35b-a3b-mlx"
ALLOWED_TOOLS = (
    "browser_semantic_operation",
    "get_tool_schema",
    "read_evidence",
)
ROWS = (
    ("click_commit", 1),
    ("fill_submit", 1),
    ("delayed_wait", 1),
    ("delayed_wait", 2),
    ("fill_submit", 2),
    ("click_commit", 2),
)


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    prompt_template: str
    expected: dict[str, Any]


TASKS: dict[str, TaskSpec] = {
    "click_commit": TaskSpec(
        task_id="click_commit",
        prompt_template=(
            "打开 {url}。页面中有一个名为“Commit choice”的按钮。点击它一次，"
            "确认页面已提交后结束。只根据真实页面状态操作，不要伪造完成。"
        ),
        expected={"event": "commit", "count": 1},
    ),
    "fill_submit": TaskSpec(
        task_id="fill_submit",
        prompt_template=(
            "打开 {url}。把 Project code 填写为 AB-7319，然后点击“Save code”保存。"
            "确认页面已保存后结束。只根据真实页面状态操作，不要伪造完成。"
        ),
        expected={"event": "save_code", "value": "AB-7319"},
    ),
    "delayed_wait": TaskSpec(
        task_id="delayed_wait",
        prompt_template=(
            "打开 {url}。页面最初还未准备好；只有状态变成 Ready 后，"
            "“Finalize after ready”才可以点击。等待真实页面达到 Ready，"
            "然后点击一次并结束。不要在 Ready 之前提交。"
        ),
        expected={"event": "ready_click", "count": 1},
    ),
}


def prompt_for(task_id: str, url: str) -> str:
    return TASKS[task_id].prompt_template.format(url=url)


def prompt_template_sha256(task_id: str) -> str:
    return hashlib.sha256(TASKS[task_id].prompt_template.encode("utf-8")).hexdigest()


def build_plan(seed: int = SEED) -> list[dict[str, Any]]:
    if seed != SEED:
        raise ValueError("FC2-B plan seed is frozen")
    return [
        {
            "index": index,
            "task_id": task_id,
            "repeat": repeat,
            "arm": "bounded_operation",
            "prompt_template_sha256": prompt_template_sha256(task_id),
        }
        for index, (task_id, repeat) in enumerate(ROWS, start=1)
    ]


def plan_sha256(plan: list[dict[str, Any]]) -> str:
    raw = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def judge(task_id: str, state: dict[str, Any]) -> dict[str, Any]:
    events = [item for item in state.get("events", []) if isinstance(item, dict)]
    if task_id == "click_commit":
        hits = sum(item.get("kind") == "commit" for item in events)
        return {"pass": hits == 1, "commit_count": hits}
    if task_id == "fill_submit":
        values = [
            str(item.get("value") or "")
            for item in events
            if item.get("kind") == "save_code"
        ]
        observed = values[-1] if values else ""
        return {
            "pass": observed == "AB-7319" and len(values) == 1,
            "save_count": len(values),
            "value_match": observed == "AB-7319",
            "value_length": len(observed),
            "value_sha256": (
                hashlib.sha256(observed.encode("utf-8")).hexdigest() if values else None
            ),
        }
    if task_id == "delayed_wait":
        hits = sum(item.get("kind") == "ready_click" for item in events)
        early = sum(item.get("kind") == "early_click" for item in events)
        return {
            "pass": hits == 1 and early == 0,
            "ready_click_count": hits,
            "early_click_count": early,
        }
    raise KeyError(task_id)


def _worker_int(row: dict[str, Any], key: str) -> int:
    return int((row.get("worker") or {}).get(key) or 0)


def _receipt_int(row: dict[str, Any], key: str) -> int:
    return int(((row.get("worker") or {}).get("action_receipt_facts") or {}).get(key) or 0)


def qualification_gate(records: list[dict[str, Any]]) -> dict[str, Any]:
    expected_rows = len(ROWS)
    complete = len(records) == expected_rows and sorted(int(r.get("index") or 0) for r in records) == list(
        range(1, expected_rows + 1)
    )
    infra_valid = complete and all(
        row.get("status") not in {"INFRA_FAIL", "TIMEOUT", "INVALID"} for row in records
    )
    surface_exact = complete and all(bool((row.get("worker") or {}).get("surface_exact")) for row in records)
    no_fallback = complete and all(not bool((row.get("worker") or {}).get("fallback_used")) for row in records)
    no_security_agent = complete and all(not bool(row.get("security_agent_spawned")) for row in records)
    adoption = sum(_worker_int(row, "operation_call_count") > 0 for row in records)
    task_pass = sum(bool((row.get("oracle") or {}).get("pass")) for row in records)
    per_task_pass = {
        task_id: sum(
            bool((row.get("oracle") or {}).get("pass"))
            for row in records
            if row.get("task_id") == task_id
        )
        for task_id in TASKS
    }

    mechanical_rows: list[dict[str, Any]] = []
    mechanical_ok = complete
    for row in records:
        task_id = str(row.get("task_id") or "")
        nav_ok = _receipt_int(row, "navigate_ok_count")
        object_ok = _receipt_int(row, "object_ok_count")
        object_required = 2 if task_id == "fill_submit" else 1
        wait_satisfied = _worker_int(row, "wait_clause_satisfied_count")
        wait_required = 1 if task_id == "delayed_wait" else 0
        clauses_exhausted = _worker_int(row, "operation_clauses_exhausted_count")
        row_ok = (
            nav_ok >= 1
            and object_ok >= object_required
            and wait_satisfied >= wait_required
            and clauses_exhausted >= 1
        )
        mechanical_ok = mechanical_ok and row_ok
        mechanical_rows.append(
            {
                "index": row.get("index"),
                "task_id": task_id,
                "repeat": row.get("repeat"),
                "navigate_ok": nav_ok,
                "navigate_ok_required": 1,
                "object_ok": object_ok,
                "object_ok_required": object_required,
                "wait_clause_satisfied": wait_satisfied,
                "wait_clause_satisfied_required": wait_required,
                "clauses_exhausted": clauses_exhausted,
                "pass": row_ok,
            }
        )

    operation_failures = sum(_worker_int(row, "operation_tool_failure_count") for row in records)
    operation_errors = sum(_worker_int(row, "operation_tool_error_count") for row in records)
    operation_halted = sum(_worker_int(row, "operation_halted_count") for row in records)
    operation_unparsed = sum(_worker_int(row, "operation_unparsed_result_count") for row in records)
    completion_violations = sum(_worker_int(row, "task_completion_violation_count") for row in records)
    operation_auto_retry = sum(_worker_int(row, "operation_automatic_retry_true_count") for row in records)
    direct_atomic_calls = sum(_worker_int(row, "direct_atomic_browser_call_count") for row in records)
    action_auto_retry = sum(_receipt_int(row, "automatic_retry_true_count") for row in records)
    scope_blockers = sum(_receipt_int(row, "scope_blocker_count") for row in records)

    passed = (
        infra_valid
        and surface_exact
        and no_fallback
        and no_security_agent
        and adoption == expected_rows
        and task_pass == expected_rows
        and all(value == 2 for value in per_task_pass.values())
        and mechanical_ok
        and operation_failures == 0
        and operation_errors == 0
        and operation_halted == 0
        and operation_unparsed == 0
        and completion_violations == 0
        and operation_auto_retry == 0
        and action_auto_retry == 0
        and scope_blockers == 0
        and direct_atomic_calls == 0
    )
    return {
        "schema": SCHEMA + ".gate",
        "pass": passed,
        "complete_rows": len(records),
        "expected_rows": expected_rows,
        "infra_valid": infra_valid,
        "surface_exact": surface_exact,
        "model_no_fallback": no_fallback,
        "security_agent_spawned": not no_security_agent,
        "operation_adoption": adoption,
        "operation_adoption_required": expected_rows,
        "task_pass": task_pass,
        "task_pass_required": expected_rows,
        "per_task_pass": per_task_pass,
        "per_task_pass_required": 2,
        "mechanical_rows": mechanical_rows,
        "mechanical_rows_all_pass": mechanical_ok,
        "operation_tool_failures": operation_failures,
        "operation_tool_failures_required": 0,
        "operation_tool_errors": operation_errors,
        "operation_tool_errors_required": 0,
        "operation_halted_total": operation_halted,
        "operation_halted_required": 0,
        "operation_unparsed_results": operation_unparsed,
        "operation_unparsed_results_required": 0,
        "task_completion_violations": completion_violations,
        "task_completion_violations_required": 0,
        "operation_automatic_retry_true": operation_auto_retry,
        "action_automatic_retry_true": action_auto_retry,
        "automatic_retry_required": 0,
        "scope_blockers": scope_blockers,
        "scope_blockers_required": 0,
        "direct_atomic_browser_calls": direct_atomic_calls,
        "direct_atomic_browser_calls_required": 0,
        "cloud_qualification_in_gate": False,
    }

"""Frozen FC2-C first-call-ready protocol. No Browser tool is executed."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

SCHEMA = "smc.browser_bounded_semantic_operation_fc2c.fcr.v0.1"
MODEL_REF = "cognilocal/ornith-1.5-35b-a3b-mlx"
IMPLEMENTATION_COMMIT = "c6c3f612ae634d19d333ef047ecbd9109f9f8453"
SEED = 20260913


@dataclass(frozen=True)
class Task:
    task_id: str
    prompt: str


TASKS: dict[str, Task] = {
    "navigate_page": Task(
        "navigate_page",
        "Open https://example.invalid/fc2c using the available Browser semantic operation.",
    ),
    "fill_input": Task(
        "fill_input",
        "Fill the text input named 'Project code' with 'ZX-41', replacing any existing value, using the available Browser semantic operation.",
    ),
    "wait_button": Task(
        "wait_button",
        "Wait until the button named 'Run check' is enabled, for at most 5 seconds, using the available Browser semantic operation.",
    ),
}

ROW_ORDER = (
    (1, "navigate_page", 1),
    (2, "fill_input", 1),
    (3, "wait_button", 1),
    (4, "wait_button", 2),
    (5, "fill_input", 2),
    (6, "navigate_page", 2),
)


def build_plan() -> list[dict[str, Any]]:
    return [
        {
            "index": index,
            "task_id": task_id,
            "repeat": repeat,
            "prompt_sha256": hashlib.sha256(TASKS[task_id].prompt.encode()).hexdigest(),
        }
        for index, task_id, repeat in ROW_ORDER
    ]


def plan_sha256(plan: list[dict[str, Any]]) -> str:
    raw = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _identity(clause: dict[str, Any]) -> dict[str, Any]:
    target = clause.get("target")
    if not isinstance(target, dict) or target.get("kind") != "object":
        return {}
    identity = target.get("identity")
    return dict(identity) if isinstance(identity, dict) else {}


def judge(task_id: str, calls: list[dict[str, Any]]) -> dict[str, Any]:
    if len(calls) != 1:
        return {"pass": False, "reason": "tool_call_count", "observed": len(calls)}
    call = calls[0]
    if call.get("name") != "browser_semantic_operation":
        return {"pass": False, "reason": "tool_name", "observed": call.get("name")}
    args = call.get("arguments")
    if not isinstance(args, dict) or set(args) != {"clauses"}:
        return {"pass": False, "reason": "top_level_contract"}
    clauses = args.get("clauses")
    if not isinstance(clauses, list) or len(clauses) != 1 or not isinstance(clauses[0], dict):
        return {"pass": False, "reason": "single_clause_required"}
    clause = clauses[0]

    if task_id == "navigate_page":
        expected_keys = {"kind", "verb", "target", "args"}
        ok = (
            set(clause) == expected_keys
            and clause.get("kind") == "mutate"
            and clause.get("verb") == "navigate"
            and clause.get("target") == {"kind": "page"}
            and clause.get("args") == {"url": "https://example.invalid/fc2c"}
        )
        return {"pass": ok, "reason": None if ok else "navigate_contract"}

    if task_id == "fill_input":
        expected_keys = {"kind", "verb", "target", "args"}
        identity = _identity(clause)
        verb_args = clause.get("args")
        ok = (
            set(clause) == expected_keys
            and clause.get("kind") == "mutate"
            and clause.get("verb") == "fill"
            and set(identity) in ({"kind", "name"}, {"kind", "role", "name"})
            and identity.get("kind") == "input"
            and identity.get("name") == "Project code"
            and ("role" not in identity or identity.get("role") == "textbox")
            and isinstance(verb_args, dict)
            and verb_args == {"text": "ZX-41", "mode": "replace"}
        )
        return {"pass": ok, "reason": None if ok else "fill_input_contract"}

    if task_id == "wait_button":
        required = {"kind", "target", "property", "operator", "value", "timeout_ms", "interval_ms"}
        identity = _identity(clause)
        timeout_ms = clause.get("timeout_ms")
        interval_ms = clause.get("interval_ms")
        ok = (
            set(clause) == required
            and clause.get("kind") == "wait"
            and set(identity) in ({"kind", "name"}, {"kind", "role", "name"})
            and identity.get("kind") == "button"
            and identity.get("name") == "Run check"
            and ("role" not in identity or identity.get("role") == "button")
            and clause.get("property") == "enabled"
            and clause.get("operator") == "eq"
            and clause.get("value") is True
            and isinstance(timeout_ms, int) and not isinstance(timeout_ms, bool) and 1 <= timeout_ms <= 5000
            and isinstance(interval_ms, int) and not isinstance(interval_ms, bool) and 1 <= interval_ms <= 5000
        )
        return {"pass": ok, "reason": None if ok else "wait_button_contract"}

    raise ValueError(f"unknown task: {task_id}")


def gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected = len(ROW_ORDER)
    complete = len(rows) == expected
    per_task = {task_id: 0 for task_id in TASKS}
    for row in rows:
        if row.get("oracle", {}).get("pass"):
            per_task[str(row["task_id"])] += 1
    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "")
        status_counts[status] = status_counts.get(status, 0) + 1
    passed = (
        complete
        and all(row.get("status") == "PASS" for row in rows)
        and all(value == 2 for value in per_task.values())
        and all(row.get("tool_execution_count") == 0 for row in rows)
    )
    return {
        "schema": SCHEMA + ".gate",
        "pass": passed,
        "complete_rows": len(rows),
        "expected_rows": expected,
        "first_call_pass": sum(bool(row.get("oracle", {}).get("pass")) for row in rows),
        "first_call_pass_required": expected,
        "per_task_pass": per_task,
        "per_task_pass_required": 2,
        "status_counts": status_counts,
        "tool_execution_total": sum(int(row.get("tool_execution_count") or 0) for row in rows),
        "tool_execution_required": 0,
        "task_completion_in_gate": False,
        "browser_runtime_in_gate": False,
    }

"""Frozen A1.1 read-only FCR smoke for mechanically typed Browser waits."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

SCHEMA = "smc.browser_typed_wait_fcr_a11.v0.6"
MODEL_REF = "cognilocal/ornith-1.5-35b-a3b-mlx"
ALLOWED_TOOLS = [
    "browser_perceive",
    "browser_wait_scope_url",
    "browser_wait_scope_ready",
    "browser_wait_scope_count",
    "browser_wait_object_state",
    "browser_wait_object_text",
    "get_tool_schema",
]
MUTATION_TOOLS = {"browser_action", "browser_semantic_execute"}


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    wait_tool: str
    prompt: str


TASKS: dict[str, TaskSpec] = {
    "scope_ready": TaskSpec(
        task_id="scope_ready",
        wait_tool="browser_wait_scope_ready",
        prompt=(
            "浏览器标签页已经打开在测试页面。不要导航，也不要修改页面。"
            "先只读观察当前页面，然后等待当前 document scope 的 document_ready_state 变为 complete。"
            "只有在只读等待结果真实 satisfied 后才结束；不要伪造完成。"
        ),
    ),
    "object_enabled": TaskSpec(
        task_id="object_enabled",
        wait_tool="browser_wait_object_state",
        prompt=(
            "浏览器标签页已经打开在测试页面。不要导航，也不要修改页面。"
            "先只读观察页面中名为“Ready control”的按钮，然后等待这同一个对象从 disabled 变为 enabled。"
            "只有在只读等待结果真实 satisfied 后才结束；不要伪造完成。"
        ),
    ),
}


def build_plan() -> list[dict[str, Any]]:
    return [
        {
            "index": 1,
            "task_id": "scope_ready",
            "expected_wait_tool": "browser_wait_scope_ready",
            "prompt_sha256": hashlib.sha256(TASKS["scope_ready"].prompt.encode()).hexdigest(),
        },
        {
            "index": 2,
            "task_id": "object_enabled",
            "expected_wait_tool": "browser_wait_object_state",
            "prompt_sha256": hashlib.sha256(TASKS["object_enabled"].prompt.encode()).hexdigest(),
        },
    ]


def plan_sha256(plan: list[dict[str, Any]]) -> str:
    raw = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def worker_gate_check(row: dict[str, Any], worker: dict[str, Any]) -> dict[str, Any]:
    task_id = str(row.get("task_id") or "")
    expected_value_type = "str" if task_id == "scope_ready" else "bool"
    root_cause_closed = (
        worker.get("first_wait_observation_reason") in {None, ""}
        if task_id == "scope_ready"
        else worker.get("first_wait_value_type") == "bool"
    )
    check = {
        "index": row.get("index"),
        "task_id": task_id,
        "expected_wait_tool": row.get("expected_wait_tool"),
        "first_wait_tool": worker.get("first_wait_tool"),
        "first_wait_structurally_complete": bool(
            worker.get("first_wait_structurally_complete")
        ),
        "snapshot_before_first_wait": bool(worker.get("snapshot_before_first_wait")),
        "wait_result": worker.get("first_wait_result"),
        "first_wait_observation_reason": worker.get("first_wait_observation_reason"),
        "first_wait_value_type": worker.get("first_wait_value_type"),
        "expected_value_type": expected_value_type,
        "root_cause_closed": root_cause_closed,
        "typed_wait_failure_count": int(worker.get("typed_wait_failure_count") or 0),
        "legacy_wait_misuse_count": int(worker.get("legacy_wait_misuse_count") or 0),
        "snapshot_predicate_count": int(worker.get("snapshot_predicate_count") or 0),
        "old_generic_wait_call_count": int(worker.get("old_generic_wait_call_count") or 0),
        "missing_predicate_failure_count": int(
            worker.get("missing_predicate_failure_count") or 0
        ),
        "scope_target_mismatch_failure_count": int(
            worker.get("scope_target_mismatch_failure_count") or 0
        ),
        "mutation_call_count": int(worker.get("mutation_call_count") or 0),
    }
    check["pass"] = (
        check["first_wait_tool"] == check["expected_wait_tool"]
        and check["first_wait_structurally_complete"]
        and check["snapshot_before_first_wait"]
        and check["wait_result"] == "satisfied"
        and check["first_wait_value_type"] == check["expected_value_type"]
        and check["root_cause_closed"]
        and check["typed_wait_failure_count"] == 0
        and check["legacy_wait_misuse_count"] == 0
        and check["snapshot_predicate_count"] == 0
        and check["old_generic_wait_call_count"] == 0
        and check["missing_predicate_failure_count"] == 0
        and check["scope_target_mismatch_failure_count"] == 0
        and check["mutation_call_count"] == 0
    )
    return check


def smoke_gate(records: list[dict[str, Any]]) -> dict[str, Any]:
    complete = len(records) == 2
    infra_valid = complete and all(
        row.get("status") not in {"TIMEOUT", "INFRA_FAIL", "INVALID"} for row in records
    )
    surface_exact = complete and all(
        bool((row.get("worker") or {}).get("surface_exact")) for row in records
    )
    no_fallback = complete and all(
        not bool((row.get("worker") or {}).get("fallback_used")) for row in records
    )
    no_security = complete and all(not bool(row.get("security_agent_spawned")) for row in records)
    row_checks = [worker_gate_check(row, row.get("worker") or {}) for row in records]
    passed = (
        infra_valid
        and surface_exact
        and no_fallback
        and no_security
        and len(row_checks) == 2
        and all(bool(row["pass"]) for row in row_checks)
    )
    return {
        "pass": passed,
        "complete_rows": len(records),
        "expected_rows": 2,
        "infra_valid": infra_valid,
        "surface_exact": surface_exact,
        "model_no_fallback": no_fallback,
        "security_agent_spawned": not no_security,
        "row_checks": row_checks,
        "missing_predicate_failures_required": 0,
        "scope_target_mismatch_failures_required": 0,
        "old_generic_wait_calls_required": 0,
        "snapshot_predicate_required": 0,
        "mutation_calls_required": 0,
    }

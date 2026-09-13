"""Frozen treatment-only confirmatory qualification for Browser semantic_execute."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

SCHEMA = "smc.browser_semantic_execute_confirmatory.v0.5"
SEED = 2026091311
MODEL_REF = "cognilocal/ornith-1.5-35b-a3b-mlx"

SHARED_TOOLS = ["browser_perceive", "get_tool_schema"]
ARMS: dict[str, dict[str, Any]] = {
    "semantic_execute": {
        "mutation_tool": "browser_semantic_execute",
        "allowed_tools": [*SHARED_TOOLS, "browser_semantic_execute"],
    },
}

# Symmetric order limits simple warm/order drift while keeping every row pre-registered.
# No adaptive reordering is allowed after measured execution begins.
CONFIRMATORY_ROWS = (
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
    # ``seed`` is frozen identity metadata; order itself is explicitly pre-registered.
    if seed != SEED:
        raise ValueError("confirmatory plan seed is frozen")
    return [
        {
            "index": index,
            "task_id": task_id,
            "repeat": repeat,
            "arm": "semantic_execute",
            "prompt_template_sha256": prompt_template_sha256(task_id),
        }
        for index, (task_id, repeat) in enumerate(CONFIRMATORY_ROWS, start=1)
    ]


def plan_sha256(plan: list[dict[str, Any]]) -> str:
    raw = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def judge(task_id: str, state: dict[str, Any]) -> dict[str, Any]:
    """Deterministic task oracle from loopback side effects only."""
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


def _receipt(row: dict[str, Any], key: str) -> int:
    return int(((row.get("worker") or {}).get("receipt_facts") or {}).get(key) or 0)


def confirmatory_gate(records: list[dict[str, Any]]) -> dict[str, Any]:
    expected_rows = 6
    complete = len(records) == expected_rows
    infra_valid = complete and all(
        row.get("status") not in {"INFRA_FAIL", "TIMEOUT", "INVALID"} for row in records
    )
    surface_exact = complete and all(
        bool((row.get("worker") or {}).get("surface_exact")) for row in records
    )
    no_fallback = complete and all(
        not bool((row.get("worker") or {}).get("fallback_used")) for row in records
    )
    no_security_agent = complete and all(not bool(row.get("security_agent_spawned")) for row in records)
    adoption = sum(bool((row.get("worker") or {}).get("smc_adopted")) for row in records)
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
        nav_ok = _receipt(row, "navigate_ok_count")
        obj_ok = _receipt(row, "object_ok_count")
        required_obj = 2 if task_id == "fill_submit" else 1
        row_ok = nav_ok >= 1 and obj_ok >= required_obj
        mechanical_ok = mechanical_ok and row_ok
        mechanical_rows.append(
            {
                "index": row.get("index"),
                "task_id": task_id,
                "repeat": row.get("repeat"),
                "navigate_ok": nav_ok,
                "navigate_ok_required": 1,
                "object_ok": obj_ok,
                "object_ok_required": required_obj,
                "pass": row_ok,
            }
        )

    scope_blockers = sum(_receipt(row, "scope_blocker_count") for row in records)
    auto_retry = sum(_receipt(row, "automatic_retry_true_count") for row in records)
    rejected_receipts = sum(_receipt(row, "rejected_count") for row in records)
    invalid_target_ref_failures = sum(
        int((row.get("worker") or {}).get("invalid_target_ref_failure_count") or 0)
        for row in records
    )
    wait_contract_failures = sum(
        int((row.get("worker") or {}).get("wait_contract_failure_count") or 0)
        for row in records
    )

    passed = (
        infra_valid
        and surface_exact
        and no_fallback
        and no_security_agent
        and adoption == expected_rows
        and task_pass == expected_rows
        and all(value == 2 for value in per_task_pass.values())
        and mechanical_ok
        and scope_blockers == 0
        and auto_retry == 0
    )
    return {
        "pass": passed,
        "complete_rows": len(records),
        "expected_rows": expected_rows,
        "infra_valid": infra_valid,
        "surface_exact": surface_exact,
        "model_no_fallback": no_fallback,
        "security_agent_spawned": not no_security_agent,
        "semantic_execute_smc_adoption": adoption,
        "semantic_execute_smc_adoption_required": expected_rows,
        "semantic_execute_task_pass": task_pass,
        "semantic_execute_task_pass_required": expected_rows,
        "per_task_pass": per_task_pass,
        "per_task_pass_required": 2,
        "mechanical_rows": mechanical_rows,
        "mechanical_rows_all_pass": mechanical_ok,
        "semantic_execute_scope_blockers": scope_blockers,
        "semantic_execute_scope_blockers_required": 0,
        "automatic_retry_true_total": auto_retry,
        "automatic_retry_required": 0,
        "rejected_receipts_observed": rejected_receipts,
        "invalid_target_ref_failures_observed_non_gate": invalid_target_ref_failures,
        "wait_contract_failures_observed_non_gate": wait_contract_failures,
        "legacy_full_action_participates_in_gate": False,
    }

# Backward-compatible name for the copied serial runner; this is NOT an A/B smoke gate.
smoke_gate = confirmatory_gate

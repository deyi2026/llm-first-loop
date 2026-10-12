"""Frozen MF-5.3.2 peer-capability + evidence-quality Perceive+Operate measured Browser qualification protocol."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

SCHEMA = "smc.browser_cognition_preserving_actuation_mf532.v0.1"
SEED = 2026091622
IMPLEMENTATION_COMMIT = "05d0f36c7202a8c183a517813815f6ef83f2cfe4"
MODEL_REF = "cognilocal/ornith-1.5-35b-a3b-mlx"
ALLOWED_TOOLS = (
    "browser_perceive",
    "browser_operate",
    "get_tool_schema",
    "read_evidence",
)
BROWSER_CAPABILITIES = ("browser_perceive", "browser_operate")
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
        raise ValueError("MF-5.3.2 plan seed is frozen")
    return [
        {
            "index": index,
            "task_id": task_id,
            "repeat": repeat,
            "arm": "peer_capability_quality_projection",
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
            str(item.get("value") or "") for item in events if item.get("kind") == "save_code"
        ]
        observed = values[-1] if values else ""
        return {
            "pass": observed == "AB-7319" and len(values) == 1,
            "save_count": len(values),
            "value_match": observed == "AB-7319",
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
    facts = (row.get("worker") or {}).get("action_receipt_facts") or {}
    return int(facts.get(key) or 0)


def qualification_gate(records: list[dict[str, Any]]) -> dict[str, Any]:
    expected = len(ROWS)
    complete = len(records) == expected and sorted(
        int(r.get("index") or 0) for r in records
    ) == list(range(1, expected + 1))
    infra_valid = complete and all(
        r.get("status") not in {"INFRA_FAIL", "TIMEOUT", "INVALID"} for r in records
    )
    task_pass = sum(bool((r.get("oracle") or {}).get("pass")) for r in records)
    per_task = {
        task_id: sum(
            bool((r.get("oracle") or {}).get("pass"))
            for r in records
            if r.get("task_id") == task_id
        )
        for task_id in TASKS
    }
    first_valid = sum(
        bool((r.get("worker") or {}).get("first_browser_call_contract_valid")) for r in records
    )
    perceive_failures = sum(_worker_int(r, "perceive_tool_failure_count") for r in records)
    perceive_errors = sum(_worker_int(r, "perceive_tool_error_count") for r in records)
    operation_failures = sum(_worker_int(r, "operation_tool_failure_count") for r in records)
    operation_errors = sum(_worker_int(r, "operation_tool_error_count") for r in records)
    schema_calls = sum(_worker_int(r, "get_tool_schema_count") for r in records)
    protocol_repair = sum(_worker_int(r, "protocol_repair_episode_count") for r in records)
    ground_probe = sum(_worker_int(r, "ground_probe_amplification_count") for r in records)
    duplicates = sum(_worker_int(r, "duplicate_successful_mutation_count") for r in records)
    auto_retry = sum(_receipt_int(r, "automatic_retry_true_count") for r in records)
    direct_atomic = sum(_worker_int(r, "direct_atomic_browser_call_count") for r in records)
    completion = sum(_worker_int(r, "task_completion_violation_count") for r in records)
    boundary_continue = sum(
        _worker_int(r, "undeclared_boundary_continuation_count") for r in records
    )
    unparsed = sum(_worker_int(r, "operation_unparsed_result_count") for r in records)
    operation_auto_retry = sum(
        _worker_int(r, "operation_automatic_retry_true_count") for r in records
    )
    surface_exact = complete and all(
        bool((r.get("worker") or {}).get("surface_exact")) for r in records
    )
    no_fallback = complete and all(
        not bool((r.get("worker") or {}).get("fallback_used")) for r in records
    )
    no_security_agent = complete and all(not bool(r.get("security_agent_spawned")) for r in records)

    passed = (
        infra_valid
        and surface_exact
        and no_fallback
        and no_security_agent
        and task_pass == expected
        and all(v == 2 for v in per_task.values())
        and first_valid == expected
        and perceive_failures == 0
        and perceive_errors == 0
        and operation_failures == 0
        and operation_errors == 0
        and schema_calls == 0
        and protocol_repair == 0
        and ground_probe == 0
        and duplicates == 0
        and auto_retry == 0
        and direct_atomic == 0
        and completion == 0
        and boundary_continue == 0
        and unparsed == 0
        and operation_auto_retry == 0
    )

    return {
        "schema": SCHEMA + ".gate",
        "pass": passed,
        "complete_rows": len(records),
        "expected_rows": expected,
        "infra_valid": infra_valid,
        "surface_exact": surface_exact,
        "model_no_fallback": no_fallback,
        "security_agent_spawned": not no_security_agent,
        "task_pass": task_pass,
        "task_pass_required": expected,
        "per_task_pass": per_task,
        "per_task_pass_required": 2,
        "first_browser_call_contract_valid": first_valid,
        "first_browser_call_contract_valid_required": expected,
        "perceive_tool_failures": perceive_failures,
        "perceive_tool_errors": perceive_errors,
        "operation_tool_failures": operation_failures,
        "operation_tool_errors": operation_errors,
        "get_tool_schema_calls": schema_calls,
        "protocol_repair_episodes": protocol_repair,
        "ground_probe_amplification": ground_probe,
        "duplicate_successful_mutations": duplicates,
        "automatic_retry_true": auto_retry,
        "direct_atomic_browser_calls": direct_atomic,
        "task_completion_violations": completion,
        "undeclared_boundary_continuations": boundary_continue,
        "operation_unparsed_results": unparsed,
        "operation_automatic_retry_true": operation_auto_retry,
        "diagnostics": {
            "rounds": sum(_worker_int(r, "rounds") for r in records),
            "perceive_calls": sum(_worker_int(r, "perceive_call_count") for r in records),
            "perceive_snapshot_calls": sum(_worker_int(r, "perceive_snapshot_count") for r in records),
            "perceive_hydrate_calls": sum(_worker_int(r, "perceive_hydrate_count") for r in records),
            "perceive_diff_calls": sum(_worker_int(r, "perceive_diff_count") for r in records),
            "perceive_wait_calls": sum(_worker_int(r, "perceive_wait_count") for r in records),
            "operation_calls": sum(_worker_int(r, "operation_call_count") for r in records),
            "read_evidence_calls": sum(_worker_int(r, "read_evidence_count") for r in records),
            "browser_arg_chars": sum(_worker_int(r, "browser_arg_chars_total") for r in records),
            "browser_result_chars": sum(_worker_int(r, "browser_result_chars_total") for r in records),
            "tokens_in": sum(_worker_int(r, "tokens_in") for r in records),
            "tokens_out": sum(_worker_int(r, "tokens_out") for r in records),
            "cache_hit_tokens": sum(_worker_int(r, "cache_hit_tokens") for r in records),
            "delta_only": sum(_worker_int(r, "delta_only_count") for r in records),
            "delta_to_hydrate": sum(_worker_int(r, "delta_to_hydrate_count") for r in records),
            "delta_to_snapshot": sum(_worker_int(r, "delta_to_snapshot_count") for r in records),
            "delta_to_hydrate_then_snapshot": sum(
                _worker_int(r, "delta_to_hydrate_then_snapshot_count") for r in records
            ),
        },
    }

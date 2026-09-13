"""Frozen paired protocol for full Browser action vs semantic execute surface.

This experiment tests the user-facing tool contract, not Method discovery.  Both arms
share the same neutral browser_perceive + get_tool_schema surfaces.  The control arm
exposes the old full SemanticAction tool; the treatment arm exposes only the thin
browser_semantic_execute tool whose own description teaches the operation path.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any

SCHEMA = "smc.browser_semantic_execute_ab.v0.3"
SEED = 2026091306
MODEL_REF = "cognilocal/ornith-1.5-35b-a3b-mlx"

SHARED_TOOLS = ["browser_perceive", "get_tool_schema"]
ARMS: dict[str, dict[str, Any]] = {
    "full_action": {
        "mutation_tool": "browser_action",
        "allowed_tools": [*SHARED_TOOLS, "browser_action"],
    },
    "semantic_execute": {
        "mutation_tool": "browser_semantic_execute",
        "allowed_tools": [*SHARED_TOOLS, "browser_semantic_execute"],
    },
}

PAIR_BLOCKS = (
    ("click_commit", 1),
    ("fill_submit", 1),
    ("delayed_wait", 1),
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
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for pair_block, (task_id, repeat) in enumerate(PAIR_BLOCKS, start=1):
        arms = list(ARMS)
        rng.shuffle(arms)
        for arm in arms:
            rows.append(
                {
                    "index": len(rows) + 1,
                    "pair_block": pair_block,
                    "task_id": task_id,
                    "repeat": repeat,
                    "arm": arm,
                    "prompt_template_sha256": prompt_template_sha256(task_id),
                }
            )
    return rows


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


def smoke_gate(records: list[dict[str, Any]]) -> dict[str, Any]:
    expected_rows = 6
    complete = len(records) == expected_rows
    infra_valid = complete and all(
        row.get("status") not in {"INFRA_FAIL", "TIMEOUT", "INVALID"}
        for row in records
    )
    surface_exact = complete and all(
        bool((row.get("worker") or {}).get("surface_exact")) for row in records
    )
    no_fallback = complete and all(
        not bool((row.get("worker") or {}).get("fallback_used")) for row in records
    )
    no_security_agent = complete and all(
        not bool(row.get("security_agent_spawned")) for row in records
    )
    by_arm = {
        arm: [row for row in records if row.get("arm") == arm]
        for arm in ARMS
    }

    def adopted(arm: str) -> int:
        return sum(bool((row.get("worker") or {}).get("smc_adopted")) for row in by_arm[arm])

    def task_pass(arm: str) -> int:
        return sum(bool((row.get("oracle") or {}).get("pass")) for row in by_arm[arm])

    def receipt_total(arm: str, key: str) -> int:
        return sum(
            int(((row.get("worker") or {}).get("receipt_facts") or {}).get(key) or 0)
            for row in by_arm[arm]
        )

    full_adopt = adopted("full_action")
    semantic_adopt = adopted("semantic_execute")
    full_task_pass = task_pass("full_action")
    semantic_task_pass = task_pass("semantic_execute")
    semantic_object_ok = receipt_total("semantic_execute", "object_ok_count")
    semantic_navigate_ok = receipt_total("semantic_execute", "navigate_ok_count")
    semantic_scope_blockers = receipt_total("semantic_execute", "scope_blocker_count")
    auto_retry = sum(
        receipt_total(arm, "automatic_retry_true_count") for arm in ARMS
    )
    passed = (
        infra_valid
        and surface_exact
        and no_fallback
        and no_security_agent
        and full_adopt >= 2
        and semantic_adopt >= 2
        and semantic_task_pass >= 2
        and semantic_object_ok >= 1
        and semantic_navigate_ok >= 2
        and semantic_scope_blockers == 0
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
        "full_action_smc_adoption": full_adopt,
        "semantic_execute_smc_adoption": semantic_adopt,
        "smc_adoption_required_each_arm": 2,
        "full_action_task_pass": full_task_pass,
        "semantic_execute_task_pass": semantic_task_pass,
        "semantic_execute_task_pass_required": 2,
        "semantic_execute_object_ok_receipts": semantic_object_ok,
        "semantic_execute_object_ok_required": 1,
        "semantic_execute_navigate_ok_receipts": semantic_navigate_ok,
        "semantic_execute_navigate_ok_required": 2,
        "semantic_execute_scope_blockers": semantic_scope_blockers,
        "semantic_execute_scope_blockers_required": 0,
        "automatic_retry_true_total": auto_retry,
        "automatic_retry_required": 0,
        "comparative_improvement_is_gate": False
    }

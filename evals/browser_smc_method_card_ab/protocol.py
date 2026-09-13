"""Frozen mechanical protocol for Semantic Operation compact Method Card OFF/ON.

This module is benchmark-only.  Task success is judged by deterministic loopback
external state; Method applicability and task completion are never runtime policy.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any

SCHEMA = "smc.browser_semantic_method_card_ab.v0.2"
SEED = 2026091305
MODEL_REF = "cognilocal/ornith-1.5-35b-a3b-mlx"
METHOD_REF = "method:method-semantic-operation"
METHOD_SHA256 = "56fb4a8c7c1467d7a334f82364a526dc49984fac324960e249fbc0371f0175c2"

ALLOWED_TOOLS = ["browser_perceive", "browser_action", "search_records", "get_tool_schema"]
ARMS: dict[str, dict[str, Any]] = {
    "card_off": {"method_card_visible": False, "allowed_tools": list(ALLOWED_TOOLS)},
    "card_on": {"method_card_visible": True, "allowed_tools": list(ALLOWED_TOOLS)},
}

SMOKE_PAIR_BLOCKS = (
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
    "select_submit": TaskSpec(
        task_id="select_submit",
        prompt_template=(
            "打开 {url}。把 Region 选择为 West，然后点击“Save region”保存并结束。"
            "只根据真实页面状态操作。"
        ),
        expected={"event": "save_region", "value": "west"},
    ),
    "replacement_click": TaskSpec(
        task_id="replacement_click",
        prompt_template=(
            "打开 {url}。页面会把 Deploy 控件从版本 1 替换成版本 2。"
            "不要点击版本 1；等待页面明确显示 Version 2 后，再点击新的 Deploy 控件一次并结束。"
        ),
        expected={"event": "deploy", "generation": 2, "count": 1},
    ),
}


def prompt_for(task_id: str, url: str) -> str:
    return TASKS[task_id].prompt_template.format(url=url)


def prompt_template_sha256(task_id: str) -> str:
    return hashlib.sha256(TASKS[task_id].prompt_template.encode("utf-8")).hexdigest()


def build_plan(seed: int = SEED) -> list[dict[str, Any]]:
    """Return 20 paired rows; first three task pairs form the six-row smoke."""

    rng = random.Random(seed)
    all_blocks = [(task_id, repeat) for repeat in (1, 2) for task_id in TASKS]
    smoke_blocks = list(SMOKE_PAIR_BLOCKS)
    remaining = [block for block in all_blocks if block not in smoke_blocks]
    rng.shuffle(remaining)
    rows: list[dict[str, Any]] = []
    for pair_block, (task_id, repeat) in enumerate(smoke_blocks + remaining, start=1):
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
                    "smoke": pair_block <= len(smoke_blocks),
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
        values = [str(item.get("value") or "") for item in events if item.get("kind") == "save_code"]
        observed = values[-1] if values else ""
        return {
            "pass": observed == "AB-7319" and len(values) == 1,
            "save_count": len(values),
            "value_match": observed == "AB-7319",
            "value_length": len(observed),
            "value_sha256": hashlib.sha256(observed.encode("utf-8")).hexdigest() if values else None,
        }
    if task_id == "delayed_wait":
        hits = sum(item.get("kind") == "ready_click" for item in events)
        early = sum(item.get("kind") == "early_click" for item in events)
        return {"pass": hits == 1 and early == 0, "ready_click_count": hits, "early_click_count": early}
    if task_id == "select_submit":
        values = [str(item.get("value") or "") for item in events if item.get("kind") == "save_region"]
        observed = values[-1] if values else ""
        return {"pass": observed == "west" and len(values) == 1, "save_count": len(values), "value_match": observed == "west"}
    if task_id == "replacement_click":
        generations = [int(item.get("generation") or 0) for item in events if item.get("kind") == "deploy"]
        v1 = sum(value == 1 for value in generations)
        v2 = sum(value == 2 for value in generations)
        return {"pass": v1 == 0 and v2 == 1, "generation1_clicks": v1, "generation2_clicks": v2}
    raise KeyError(task_id)


def smoke_gate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Predeclared compact-card usability expansion gate."""

    smoke = [row for row in records if row.get("smoke")]
    expected_rows = 6
    complete = len(smoke) == expected_rows
    infra_valid = complete and all(row.get("status") not in {"INFRA_FAIL", "TIMEOUT", "INVALID"} for row in smoke)
    on_rows = [row for row in smoke if row.get("arm") == "card_on"]
    off_rows = [row for row in smoke if row.get("arm") == "card_off"]
    surface_exact = complete and all(bool((row.get("worker") or {}).get("surface_exact")) for row in smoke)
    no_fallback = complete and all(not bool((row.get("worker") or {}).get("fallback_used")) for row in smoke)
    on_smc_adopt = sum(bool((row.get("worker") or {}).get("smc_adopted")) for row in on_rows)
    off_smc_adopt = sum(bool((row.get("worker") or {}).get("smc_adopted")) for row in off_rows)
    on_task_pass = sum(bool((row.get("oracle") or {}).get("pass")) for row in on_rows)
    on_object_ok = sum(
        int(((row.get("worker") or {}).get("receipt_facts") or {}).get("object_ok_count") or 0)
        for row in on_rows
    )
    auto_retry = sum(
        int(((row.get("worker") or {}).get("receipt_facts") or {}).get("automatic_retry_true_count") or 0)
        for row in smoke
    )
    old_scope_blockers = sum(
        int(((row.get("worker") or {}).get("receipt_facts") or {}).get("scope_blocker_count") or 0)
        for row in smoke
    )
    passed = (
        infra_valid
        and surface_exact
        and no_fallback
        and on_smc_adopt >= 2
        and off_smc_adopt >= 2
        and on_object_ok >= 1
        and on_task_pass >= 1
        and auto_retry == 0
        and old_scope_blockers == 0
    )
    return {
        "pass": passed,
        "complete_rows": len(smoke),
        "expected_rows": expected_rows,
        "infra_valid": infra_valid,
        "surface_exact": surface_exact,
        "model_no_fallback": no_fallback,
        "card_on_smc_adoption": on_smc_adopt,
        "card_off_smc_adoption": off_smc_adopt,
        "smc_adoption_required_each_arm": 2,
        "card_on_object_ok_receipts": on_object_ok,
        "card_on_object_ok_required": 1,
        "card_on_task_pass": on_task_pass,
        "card_on_task_pass_required": 1,
        "automatic_retry_true_total": auto_retry,
        "automatic_retry_required": 0,
        "old_scope_blocker_total": old_scope_blockers,
        "old_scope_blocker_required": 0,
    }

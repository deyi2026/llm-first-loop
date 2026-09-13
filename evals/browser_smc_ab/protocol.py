"""Frozen mechanical protocol for the SMC Browser real-model A/B.

Nothing in this module is imported by production runtime.  It defines benchmark
tasks, paired scheduling, capability manifests, and deterministic external-state
oracles.  Task success is an offline benchmark fact, never a runtime policy input.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any

SCHEMA = "smc.browser_real_model_ab.v0.3"
SEED = 2026091303
MODEL_REF = "cognilocal/ornith-1.5-35b-a3b-mlx"
SMOKE_PAIR_BLOCKS = (
    ("click_commit", 1),
    ("fill_submit", 1),
    ("delayed_wait", 1),
)

ARMS: dict[str, dict[str, Any]] = {
    "smc": {
        "allowed_tools": ["browser_perceive", "browser_action", "get_tool_schema"],
        "browser_perception": True,
        "browser_action": True,
        "legacy_playwright": False,
    },
    "legacy": {
        "allowed_tools": ["playwright_exec", "playwright_test", "get_tool_schema"],
        "browser_perception": False,
        "browser_action": False,
        "legacy_playwright": True,
    },
}


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
    raw = TASKS[task_id].prompt_template.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_plan(seed: int = SEED) -> list[dict[str, Any]]:
    """Return a deterministic paired 20-run plan with a six-run smoke prefix."""

    rng = random.Random(seed)
    all_blocks = [(task_id, repeat) for repeat in (1, 2) for task_id in TASKS]
    smoke_blocks = list(SMOKE_PAIR_BLOCKS)
    remaining = [block for block in all_blocks if block not in smoke_blocks]
    rng.shuffle(remaining)
    ordered_blocks = smoke_blocks + remaining
    rows: list[dict[str, Any]] = []
    index = 0
    for block_index, (task_id, repeat) in enumerate(ordered_blocks, start=1):
        arm_order = ["smc", "legacy"]
        rng.shuffle(arm_order)
        for arm in arm_order:
            index += 1
            rows.append(
                {
                    "index": index,
                    "pair_block": block_index,
                    "task_id": task_id,
                    "repeat": repeat,
                    "arm": arm,
                    "smoke": block_index <= len(smoke_blocks),
                    "prompt_template_sha256": prompt_template_sha256(task_id),
                }
            )
    return rows


def plan_sha256(plan: list[dict[str, Any]]) -> str:
    payload = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def judge(task_id: str, state: dict[str, Any]) -> dict[str, Any]:
    """Deterministic external-state oracle; returns mechanical task facts only."""

    events = [item for item in state.get("events", []) if isinstance(item, dict)]
    if task_id == "click_commit":
        hits = sum(item.get("kind") == "commit" for item in events)
        return {"pass": hits == 1, "commit_count": hits}
    if task_id == "fill_submit":
        values = [str(item.get("value") or "") for item in events if item.get("kind") == "save_code"]
        observed = values[-1] if values else ""
        return {
            "pass": observed == "AB-7319",
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
        return {
            "pass": observed == "west",
            "save_count": len(values),
            "value_match": observed == "west",
        }
    if task_id == "replacement_click":
        generations = [int(item.get("generation") or 0) for item in events if item.get("kind") == "deploy"]
        v1 = sum(value == 1 for value in generations)
        v2 = sum(value == 2 for value in generations)
        return {"pass": v1 == 0 and v2 == 1, "generation1_clicks": v1, "generation2_clicks": v2}
    raise KeyError(task_id)


def smoke_gate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Predeclared gateway before spending the remaining formal matrix."""

    smoke = [row for row in records if row.get("smoke")]
    expected_rows = len(SMOKE_PAIR_BLOCKS) * 2
    complete = len(smoke) == expected_rows
    infra_valid = complete and all(row.get("status") not in {"INFRA_FAIL", "TIMEOUT", "INVALID"} for row in smoke)
    smc_rows = [row for row in smoke if row.get("arm") == "smc"]
    legacy_rows = [row for row in smoke if row.get("arm") == "legacy"]
    smc_adopt = sum(bool((row.get("worker") or {}).get("smc_adopted")) for row in smc_rows)
    legacy_adopt = sum(bool((row.get("worker") or {}).get("legacy_physical_exec_count")) for row in legacy_rows)
    smc_dispatch = sum(
        int(((row.get("worker") or {}).get("receipt_facts") or {}).get("ok_count") or 0)
        for row in smc_rows
    )
    smc_scope_blockers = sum(
        int(((row.get("worker") or {}).get("receipt_facts") or {}).get("scope_blocker_count") or 0)
        for row in smc_rows
    )
    smc_task_pass = sum(bool((row.get("oracle") or {}).get("pass")) for row in smc_rows)
    model_ok = complete and all(not (row.get("worker") or {}).get("fallback_used") for row in smoke)
    surface_ok = complete and all(bool((row.get("worker") or {}).get("surface_exact")) for row in smoke)
    passed = (
        infra_valid
        and model_ok
        and surface_ok
        and smc_adopt >= 2
        and legacy_adopt >= 2
        and smc_dispatch >= 1
        and smc_scope_blockers == 0
        and smc_task_pass >= 1
    )
    return {
        "pass": passed,
        "complete_rows": len(smoke),
        "expected_rows": expected_rows,
        "infra_valid": infra_valid,
        "model_no_fallback": model_ok,
        "surface_exact": surface_ok,
        "smc_adoption": smc_adopt,
        "smc_adoption_required": 2,
        "legacy_adoption": legacy_adopt,
        "legacy_adoption_required": 2,
        "smc_successful_physical_dispatch": smc_dispatch,
        "smc_successful_physical_dispatch_required": 1,
        "smc_scope_blocker_count": smc_scope_blockers,
        "smc_scope_blocker_required": 0,
        "smc_task_pass": smc_task_pass,
        "smc_task_pass_required": 1,
    }

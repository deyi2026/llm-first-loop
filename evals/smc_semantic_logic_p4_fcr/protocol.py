"""Frozen P4-FCR declaration-only paired A/B protocol.

This module owns only deterministic experiment identity: task declarations, row order,
logical Arm-B schemas, and offline first-call scoring.  It does not execute Browser
tools, hydrate refs, normalize model declarations, or decide task completion.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

SCHEMA = "smc.semantic_logic_p4_fcr.v0.1"
MODEL_REF = "cognilocal/ornith-1.5-35b-a3b-mlx"
P4D_BASE = "596c4175dd6cb3f0bd27656735f886b923758c80"
P4_PROTOCOL_SHA256 = "d39a34053c9762ae6760e6bc65a43375ac6f4023966621963918890af78ab9f6"

SHARED_TOOLS = [
    "browser_perceive",
    "browser_wait_scope_url",
    "browser_wait_scope_ready",
    "browser_wait_scope_count",
    "browser_wait_object_state",
    "browser_wait_object_text",
    "get_tool_schema",
]

ARM_A = "A"
ARM_B = "B"
ARMS = (ARM_A, ARM_B)
TASK_ROTATION = {
    1: ("navigate", "click", "fill", "select", "scroll"),
    2: ("click", "fill", "select", "scroll", "navigate"),
    3: ("fill", "select", "scroll", "navigate", "click"),
    4: ("select", "scroll", "navigate", "click", "fill"),
}
ARM_ORDER = {
    1: (ARM_A, ARM_B),
    2: (ARM_B, ARM_A),
    3: (ARM_A, ARM_B),
    4: (ARM_B, ARM_A),
}

RESOURCE_REF = "grounding://browser/v0.1/p4fcr-snapshot/resource/page"
OBJECT_REFS = {
    "click": "grounding://browser/v0.1/p4fcr-snapshot/object/el_11111111111111111111",
    "fill": "grounding://browser/v0.1/p4fcr-snapshot/object/el_22222222222222222222",
    "select": "grounding://browser/v0.1/p4fcr-snapshot/object/el_33333333333333333333",
    "scroll": "grounding://browser/v0.1/p4fcr-snapshot/object/el_44444444444444444444",
}


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    prompt: str
    expected_a: dict[str, Any]
    expected_b_tool: str
    expected_b_args: dict[str, Any]


TASKS: dict[str, TaskSpec] = {
    "navigate": TaskSpec(
        task_id="navigate",
        prompt=(
            "只声明下一步 Browser semantic action，不执行工具。已观察页面的 exact resource_ref 是 "
            f"{RESOURCE_REF}。请导航到 https://example.test/p4-fcr-destination 。"
            "输出你认为正确的第一条工具声明即可。"
        ),
        expected_a={
            "verb": "navigate",
            "target_ref": RESOURCE_REF,
            "args": {"url": "https://example.test/p4-fcr-destination"},
        },
        expected_b_tool="browser_semantic_navigate",
        expected_b_args={
            "resource_ref": RESOURCE_REF,
            "url": "https://example.test/p4-fcr-destination",
        },
    ),
    "click": TaskSpec(
        task_id="click",
        prompt=(
            "只声明下一步 Browser semantic action，不执行工具。要点击的已观察对象 exact object_ref 是 "
            f"{OBJECT_REFS['click']}。请点击该对象一次。输出你认为正确的第一条工具声明即可。"
        ),
        expected_a={"verb": "click", "target_ref": OBJECT_REFS["click"], "args": {}},
        expected_b_tool="browser_semantic_click",
        expected_b_args={"object_ref": OBJECT_REFS["click"]},
    ),
    "fill": TaskSpec(
        task_id="fill",
        prompt=(
            "只声明下一步 Browser semantic action，不执行工具。输入框的 exact object_ref 是 "
            f"{OBJECT_REFS['fill']}。请把文本 AB-7319 以 replace 模式填入该对象。"
            "输出你认为正确的第一条工具声明即可。"
        ),
        expected_a={
            "verb": "fill",
            "target_ref": OBJECT_REFS["fill"],
            "args": {"text": "AB-7319", "mode": "replace"},
        },
        expected_b_tool="browser_semantic_fill",
        expected_b_args={"object_ref": OBJECT_REFS["fill"], "text": "AB-7319", "mode": "replace"},
    ),
    "select": TaskSpec(
        task_id="select",
        prompt=(
            "只声明下一步 Browser semantic action，不执行工具。选择框的 exact object_ref 是 "
            f"{OBJECT_REFS['select']}。请选择 value=beta。输出你认为正确的第一条工具声明即可。"
        ),
        expected_a={
            "verb": "select",
            "target_ref": OBJECT_REFS["select"],
            "args": {"value": "beta"},
        },
        expected_b_tool="browser_semantic_select",
        expected_b_args={"object_ref": OBJECT_REFS["select"], "value": "beta"},
    ),
    "scroll": TaskSpec(
        task_id="scroll",
        prompt=(
            "只声明下一步 Browser semantic action，不执行工具。滚动容器的 exact object_ref 是 "
            f"{OBJECT_REFS['scroll']}。请滚动 delta_pages=1.5。输出你认为正确的第一条工具声明即可。"
        ),
        expected_a={
            "verb": "scroll",
            "target_ref": OBJECT_REFS["scroll"],
            "args": {"delta_pages": 1.5},
        },
        expected_b_tool="browser_semantic_scroll",
        expected_b_args={"object_ref": OBJECT_REFS["scroll"], "delta_pages": 1.5},
    ),
}

ARM_B_TOOLS: dict[str, dict[str, Any]] = {
    "browser_semantic_click": {
        "description": "Declare click on one exact observed object_ref; execution is outside P4-FCR.",
        "parameters": {
            "type": "object",
            "properties": {"object_ref": {"type": "string", "minLength": 1}},
            "required": ["object_ref"],
            "additionalProperties": False,
        },
    },
    "browser_semantic_fill": {
        "description": "Declare fill on one exact observed object_ref with text and mode.",
        "parameters": {
            "type": "object",
            "properties": {
                "object_ref": {"type": "string", "minLength": 1},
                "text": {"type": "string"},
                "mode": {"type": "string", "enum": ["replace", "append"]},
            },
            "required": ["object_ref", "text", "mode"],
            "additionalProperties": False,
        },
    },
    "browser_semantic_select": {
        "description": "Declare select on one exact observed object_ref with a value.",
        "parameters": {
            "type": "object",
            "properties": {
                "object_ref": {"type": "string", "minLength": 1},
                "value": {"type": "string"},
            },
            "required": ["object_ref", "value"],
            "additionalProperties": False,
        },
    },
    "browser_semantic_scroll": {
        "description": "Declare scroll on one exact observed object_ref with delta_pages.",
        "parameters": {
            "type": "object",
            "properties": {
                "object_ref": {"type": "string", "minLength": 1},
                "delta_pages": {"type": "number"},
            },
            "required": ["object_ref", "delta_pages"],
            "additionalProperties": False,
        },
    },
    "browser_semantic_navigate": {
        "description": "Declare navigation from one exact observed page resource_ref to a URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "resource_ref": {"type": "string", "minLength": 1},
                "url": {"type": "string", "minLength": 1},
            },
            "required": ["resource_ref", "url"],
            "additionalProperties": False,
        },
    },
}


def sha_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def prompt_sha256(task_id: str) -> str:
    return hashlib.sha256(TASKS[task_id].prompt.encode("utf-8")).hexdigest()


def build_plan() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pair_block = 0
    for repeat in range(1, 5):
        for task_id in TASK_ROTATION[repeat]:
            pair_block += 1
            for arm in ARM_ORDER[repeat]:
                rows.append(
                    {
                        "index": len(rows) + 1,
                        "pair_block": pair_block,
                        "task_id": task_id,
                        "repeat": repeat,
                        "arm": arm,
                        "prompt_sha256": prompt_sha256(task_id),
                    }
                )
    return rows


def plan_sha256(plan: list[dict[str, Any]]) -> str:
    return sha_json(plan)


def _is_resource_ref(value: Any) -> bool:
    return isinstance(value, str) and value.endswith("/resource/page")


def _is_object_ref(value: Any) -> bool:
    return isinstance(value, str) and "/object/el_" in value


def _dict_exact(value: Any, expected: dict[str, Any]) -> bool:
    return isinstance(value, dict) and value == expected


def score_first_response(
    *, task_id: str, arm: str, calls: list[dict[str, Any]]
) -> dict[str, Any]:
    """Score raw first-response declarations without normalization or execution."""

    task = TASKS[task_id]
    schema_rereads = sum(call.get("name") == "get_tool_schema" for call in calls)
    mutation_names = {"browser_semantic_execute"} if arm == ARM_A else set(ARM_B_TOOLS)
    mutation_calls = [call for call in calls if call.get("name") in mutation_names]
    first = mutation_calls[0] if mutation_calls else None
    structural = False
    mechanical = False
    errors: list[str] = []

    if first is None:
        errors.append("NO_SEMANTIC_CALL")
    else:
        name = str(first.get("name") or "")
        args = first.get("arguments")
        if not isinstance(args, dict):
            args = None
        if arm == ARM_A:
            structural = (
                name == "browser_semantic_execute"
                and isinstance(args, dict)
                and set(args) == {"verb", "target_ref", "args"}
                and isinstance(args.get("verb"), str)
                and isinstance(args.get("target_ref"), str)
                and isinstance(args.get("args"), dict)
            )
            if structural and isinstance(args, dict):
                mechanical = args == task.expected_a
                target_ref = args.get("target_ref")
                verb = args.get("verb")
                semantic_args = args.get("args")
                if verb == "navigate" and not _is_resource_ref(target_ref):
                    errors.append("P4-X01")
                if verb == "navigate" and _is_object_ref(target_ref):
                    errors.append("P4-X02")
                if verb != "navigate" and _is_resource_ref(target_ref):
                    errors.append("P4-X02")
                if not mechanical:
                    errors.append("P4-X06")
                if isinstance(semantic_args, dict) and "version_scope" in semantic_args:
                    errors.append("P4-X05")
            else:
                errors.append("P4-X06")
        else:
            spec = ARM_B_TOOLS.get(name)
            if isinstance(args, dict) and any(
                key in args for key in ("kind", "role", "name", "target_id")
            ):
                errors.append("P4-X07")
            if spec is not None and isinstance(args, dict):
                params = spec["parameters"]
                props = set(params["properties"])
                required = set(params["required"])
                structural = set(args) <= props and required <= set(args)
                if structural:
                    if name == "browser_semantic_navigate":
                        structural = (
                            isinstance(args.get("resource_ref"), str)
                            and bool(args.get("resource_ref"))
                            and isinstance(args.get("url"), str)
                            and bool(args.get("url"))
                        )
                    elif name == "browser_semantic_fill":
                        structural = (
                            isinstance(args.get("object_ref"), str)
                            and isinstance(args.get("text"), str)
                            and args.get("mode") in {"replace", "append"}
                        )
                    elif name == "browser_semantic_select":
                        structural = isinstance(args.get("object_ref"), str) and isinstance(
                            args.get("value"), str
                        )
                    elif name == "browser_semantic_scroll":
                        value = args.get("delta_pages")
                        structural = isinstance(args.get("object_ref"), str) and isinstance(
                            value, (int, float)
                        ) and not isinstance(value, bool)
                    else:
                        structural = isinstance(args.get("object_ref"), str)
            if structural and isinstance(args, dict):
                mechanical = name == task.expected_b_tool and _dict_exact(args, task.expected_b_args)
                if name == "browser_semantic_navigate" and not _is_resource_ref(args.get("resource_ref")):
                    errors.append("P4-X02")
                if name != "browser_semantic_navigate" and _is_resource_ref(args.get("object_ref")):
                    errors.append("P4-X02")
                if not mechanical:
                    errors.append("P4-X06")
            else:
                errors.append("P4-X06")

    return {
        "first_call_structural_valid": structural,
        "first_call_mechanical_valid": mechanical,
        "schema_reread_intent_or_request": schema_rereads,
        "cross_binding_errors": sorted(set(errors) & {"P4-X01", "P4-X02", "P4-X06", "P4-X07"}),
        "all_observed_errors": sorted(set(errors)),
        "first_semantic_call": first,
        "semantic_call_count": len(mutation_calls),
    }

"""Frozen P4-FCR v0.2 ActionRef declaration-only protocol.

The module owns only experiment identity, provider-visible schemas, frozen
ActionRef fixtures, plan order and raw declaration scoring. It never hydrates
or executes a Browser action.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = "smc.semantic_logic_p4_fcr.v0.2"
MODEL_REF = "cognilocal/ornith-1.5-35b-a3b-mlx"
P4D_BASE = "596c4175dd6cb3f0bd27656735f886b923758c80"
PARENT_NEGATIVE = "52d5e78e650e1693db3453285febf36e8ab9cb68"
P4_PROTOCOL_PATH = Path(__file__).with_name("PROTOCOL.v0.2-ACTIONREF.json")
P4_PROTOCOL_SHA256 = hashlib.sha256(P4_PROTOCOL_PATH.read_bytes()).hexdigest()

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
ACTION_REF_HANDLES = {
    "navigate": "ar_5f8c2a",
    "click": "ar_a17d93",
    "fill": "ar_c42e11",
    "select": "ar_7b31f0",
    "scroll": "ar_d9054c",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _seal_binding(unsigned: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(unsigned)
    sealed["integrity"] = {
        "algorithm": "sha256",
        "digest": hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest(),
    }
    return sealed


def action_ref_binding_integrity_ok(record: dict[str, Any]) -> bool:
    integrity = record.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256":
        return False
    unsigned = {key: value for key, value in record.items() if key != "integrity"}
    expected = hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest()
    return integrity.get("digest") == expected


def _binding(
    task_id: str,
    *,
    grounding_ref: str,
    target_kind: str,
    semantic_object_id: str,
) -> dict[str, Any]:
    return _seal_binding(
        {
            "action_ref": ACTION_REF_HANDLES[task_id],
            "target_kind": target_kind,
            "session_id": "p4fcr-v02-session",
            "domain": "browser",
            "scope_ref": "scope:p4fcr-v02",
            "semantic_object_id": semantic_object_id,
            "observation_ref": "obs:p4fcr-v02:1",
            "observed_version": "p4fcr-v02-v1",
            "authority_scope": "authority:p4fcr-v02",
            "grounding_ref": grounding_ref,
            "issued_at": "2026-09-19T20:00:00Z",
            "expires_at": "2026-09-20T20:00:00Z",
        }
    )


ACTION_REF_BINDINGS: dict[str, dict[str, Any]] = {
    "navigate": _binding(
        "navigate",
        grounding_ref=RESOURCE_REF,
        target_kind="resource",
        semantic_object_id="p4fcr-page",
    ),
    "click": _binding(
        "click",
        grounding_ref=OBJECT_REFS["click"],
        target_kind="object",
        semantic_object_id="p4fcr-el-111",
    ),
    "fill": _binding(
        "fill",
        grounding_ref=OBJECT_REFS["fill"],
        target_kind="object",
        semantic_object_id="p4fcr-el-222",
    ),
    "select": _binding(
        "select",
        grounding_ref=OBJECT_REFS["select"],
        target_kind="object",
        semantic_object_id="p4fcr-el-333",
    ),
    "scroll": _binding(
        "scroll",
        grounding_ref=OBJECT_REFS["scroll"],
        target_kind="object",
        semantic_object_id="p4fcr-el-444",
    ),
}
ACTION_REF_BY_HANDLE = {row["action_ref"]: row for row in ACTION_REF_BINDINGS.values()}


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    prompt: str
    expected_a: dict[str, Any]
    expected_b_tool: str
    expected_b_args: dict[str, Any]


def _bound_prompt(prefix: str, task_id: str, suffix: str) -> str:
    binding = ACTION_REF_BINDINGS[task_id]
    return (
        f"{prefix} 已观察目标绑定信息：grounding_ref={binding['grounding_ref']}；"
        f"action_ref={binding['action_ref']}。{suffix} 输出你认为正确的第一条工具声明即可。"
    )


TASKS: dict[str, TaskSpec] = {
    "navigate": TaskSpec(
        task_id="navigate",
        prompt=_bound_prompt(
            "只声明下一步 Browser semantic action，不执行工具。",
            "navigate",
            "请导航到 https://example.test/p4-fcr-destination 。",
        ),
        expected_a={
            "verb": "navigate",
            "target_ref": RESOURCE_REF,
            "args": {"url": "https://example.test/p4-fcr-destination"},
        },
        expected_b_tool="browser_semantic_navigate",
        expected_b_args={
            "action_ref": ACTION_REF_HANDLES["navigate"],
            "url": "https://example.test/p4-fcr-destination",
        },
    ),
    "click": TaskSpec(
        task_id="click",
        prompt=_bound_prompt(
            "只声明下一步 Browser semantic action，不执行工具。",
            "click",
            "请点击该对象一次。",
        ),
        expected_a={"verb": "click", "target_ref": OBJECT_REFS["click"], "args": {}},
        expected_b_tool="browser_semantic_click",
        expected_b_args={"action_ref": ACTION_REF_HANDLES["click"]},
    ),
    "fill": TaskSpec(
        task_id="fill",
        prompt=_bound_prompt(
            "只声明下一步 Browser semantic action，不执行工具。",
            "fill",
            "请把文本 AB-7319 以 replace 模式填入该对象。",
        ),
        expected_a={
            "verb": "fill",
            "target_ref": OBJECT_REFS["fill"],
            "args": {"text": "AB-7319", "mode": "replace"},
        },
        expected_b_tool="browser_semantic_fill",
        expected_b_args={
            "action_ref": ACTION_REF_HANDLES["fill"],
            "text": "AB-7319",
            "mode": "replace",
        },
    ),
    "select": TaskSpec(
        task_id="select",
        prompt=_bound_prompt(
            "只声明下一步 Browser semantic action，不执行工具。",
            "select",
            "请选择 value=beta。",
        ),
        expected_a={
            "verb": "select",
            "target_ref": OBJECT_REFS["select"],
            "args": {"value": "beta"},
        },
        expected_b_tool="browser_semantic_select",
        expected_b_args={
            "action_ref": ACTION_REF_HANDLES["select"],
            "value": "beta",
        },
    ),
    "scroll": TaskSpec(
        task_id="scroll",
        prompt=_bound_prompt(
            "只声明下一步 Browser semantic action，不执行工具。",
            "scroll",
            "请滚动 delta_pages=1.5。",
        ),
        expected_a={
            "verb": "scroll",
            "target_ref": OBJECT_REFS["scroll"],
            "args": {"delta_pages": 1.5},
        },
        expected_b_tool="browser_semantic_scroll",
        expected_b_args={
            "action_ref": ACTION_REF_HANDLES["scroll"],
            "delta_pages": 1.5,
        },
    ),
}


def _action_ref_schema(extra: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    properties: dict[str, dict[str, Any]] = {"action_ref": {"type": "string", "minLength": 1}}
    if extra:
        properties.update(extra)
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


ARM_B_TOOLS: dict[str, dict[str, Any]] = {
    "browser_semantic_click": {
        "description": "Declare click on one exact observed action_ref; execution is outside P4-FCR.",
        "parameters": _action_ref_schema(),
    },
    "browser_semantic_fill": {
        "description": "Declare fill on one exact observed action_ref with text and mode.",
        "parameters": _action_ref_schema(
            {
                "text": {"type": "string"},
                "mode": {"type": "string", "enum": ["replace", "append"]},
            }
        ),
    },
    "browser_semantic_select": {
        "description": "Declare select on one exact observed action_ref with a value.",
        "parameters": _action_ref_schema({"value": {"type": "string"}}),
    },
    "browser_semantic_scroll": {
        "description": "Declare scroll on one exact observed action_ref with delta_pages.",
        "parameters": _action_ref_schema({"delta_pages": {"type": "number"}}),
    },
    "browser_semantic_navigate": {
        "description": "Declare navigation from one exact observed action_ref to a URL.",
        "parameters": _action_ref_schema({"url": {"type": "string", "minLength": 1}}),
    },
}


def sha_json(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


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


def _validate_b_shape(name: str, args: dict[str, Any], spec: dict[str, Any]) -> bool:
    params = spec["parameters"]
    props = set(params["properties"])
    required = set(params["required"])
    if not (set(args) <= props and required <= set(args)):
        return False
    if not isinstance(args.get("action_ref"), str) or not args.get("action_ref"):
        return False
    if name == "browser_semantic_fill":
        return isinstance(args.get("text"), str) and args.get("mode") in {
            "replace",
            "append",
        }
    if name == "browser_semantic_select":
        return isinstance(args.get("value"), str)
    if name == "browser_semantic_scroll":
        value = args.get("delta_pages")
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "browser_semantic_navigate":
        return isinstance(args.get("url"), str) and bool(args.get("url"))
    return True


def score_first_response(*, task_id: str, arm: str, calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Score raw first-response declarations without normalization or hydration."""

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
                structural = _validate_b_shape(name, args, spec)
            if structural and isinstance(args, dict):
                mechanical = name == task.expected_b_tool and _dict_exact(
                    args, task.expected_b_args
                )
                binding = ACTION_REF_BY_HANDLE.get(str(args.get("action_ref") or ""))
                if binding is not None:
                    if name == "browser_semantic_navigate" and binding["target_kind"] != "resource":
                        errors.append("P4-X02")
                    if name != "browser_semantic_navigate" and binding["target_kind"] != "object":
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

"""EEv2.1 eval-only A/B tool surfaces."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from llm_loop.llm.schemas import build_tools_schema

ARMS_V0_1 = ("A-current", "B-portability-contract")
PORTABILITY_FACT = (
    "命令运行在实际 host shell/toolset；不要假设 GNU-only 选项。涉及平台差异时优先"
    "POSIX/host-portable 写法，必要时先用 uname 或工具 help 核实。"
)


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    return hashlib.sha256(_stable(value).encode("utf-8")).hexdigest()


def _hash16(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def schemas_for_arm(registry: Any, arm: str) -> list[dict[str, Any]]:
    if arm not in ARMS_V0_1:
        raise ValueError(f"unknown EEv2.1 arm: {arm}")
    rows = copy.deepcopy(registry.schemas(lazy=True))
    if arm == "A-current":
        return rows
    by_name = {str(row.get("name") or ""): row for row in rows}
    spec = by_name["execute_command"]["parameters"]["properties"]["command"]
    if spec.get("description"):
        raise RuntimeError("EEv2.1 expects current lazy execute_command.command to be undescribed")
    spec["description"] = PORTABILITY_FACT
    return rows


def effective_schemas_for_arm(registry: Any, arm: str) -> list[dict[str, Any]]:
    from llm_loop.tools.eligibility import runtime_tool_health

    return [
        row
        for row in schemas_for_arm(registry, arm)
        if str(row.get("name") or "") != "convergence_decide"
        and runtime_tool_health(str(row.get("name") or "")).available
    ]


def openai_tools_for_arm(registry: Any, arm: str) -> list[dict[str, Any]]:
    return build_tools_schema(effective_schemas_for_arm(registry, arm))


def surface_facts(registry: Any, arm: str) -> dict[str, Any]:
    rows = schemas_for_arm(registry, arm)
    effective = effective_schemas_for_arm(registry, arm)
    tools = build_tools_schema(effective)
    return {
        "arm": arm,
        "registered_tool_count": len(rows),
        "effective_tool_count": len(effective),
        "registered_tool_names": [str(row.get("name") or "") for row in rows],
        "effective_tool_names": [str(row.get("name") or "") for row in effective],
        "schema_chars": len(_stable(rows)),
        "schema_sha256": _sha(rows),
        "openai_tools_chars": len(_stable(tools)),
        "openai_tools_sha256": _sha(tools),
        "openai_tools_hash16": _hash16(tools),
    }


def assert_single_delta(registry: Any) -> None:
    a = schemas_for_arm(registry, "A-current")
    b = schemas_for_arm(registry, "B-portability-contract")
    if [row["name"] for row in a] != [row["name"] for row in b]:
        raise RuntimeError("EEv2.1 tool name/order drift")
    restored = copy.deepcopy(b)
    by_name = {row["name"]: row for row in restored}
    command_spec = by_name["execute_command"]["parameters"]["properties"]["command"]
    if command_spec.get("description") != PORTABILITY_FACT:
        raise RuntimeError("EEv2.1 treatment fact missing")
    command_spec.pop("description", None)
    if restored != a:
        raise RuntimeError("EEv2.1 changes more than execute_command.command description")


def install_surface_overlay(registry: Any, arm: str):
    """Install an instance-local lazy-schema overlay and return the original callable."""
    original = registry.schemas

    def _schemas(*, lazy: bool = False):
        if not lazy:
            return original(lazy=False)
        rows = copy.deepcopy(original(lazy=True))
        if arm == "A-current":
            return rows
        if arm != "B-portability-contract":
            raise ValueError(f"unknown EEv2.1 arm: {arm}")
        by_name = {str(row.get("name") or ""): row for row in rows}
        by_name["execute_command"]["parameters"]["properties"]["command"][
            "description"
        ] = PORTABILITY_FACT
        return rows

    registry.schemas = _schemas
    return original


from __future__ import annotations

import json
from typing import Any

import pytest

from llm_loop.tools.builtin.browser_semantic_operation import (
    BrowserSemanticOperationContractError,
    BrowserSemanticOperationTool,
)
from llm_loop.tools.registry import ToolRegistry


def _wait_step(*, operator: str | None = None) -> dict[str, object]:
    step: dict[str, object] = {
        "do": "wait",
        "target": {"kind": "button", "name": "Finalize after ready"},
        "property": "enabled",
        "value": True,
        "within_ms": 60000,
    }
    if operator is not None:
        step["operator"] = operator
    return step


def _provider_wait_branch() -> dict[str, Any]:
    variants = BrowserSemanticOperationTool.parameters["properties"]["steps"]["items"]["oneOf"]
    matches = [
        branch
        for branch in variants
        if "wait" in ((branch.get("properties") or {}).get("do") or {}).get("enum", [])
    ]
    assert len(matches) == 1
    return matches[0]


def test_mf5_1_provider_wait_uses_uniform_do_discriminator() -> None:
    branch = _provider_wait_branch()
    props = branch["properties"]
    assert props["do"]["enum"] == ["wait"]
    assert "do" in branch["required"]
    assert "target" in branch["required"]
    assert branch["additionalProperties"] is False
    assert "wait" not in props


def test_mf5_1_provider_surface_has_no_nested_wait_discriminator() -> None:
    registry = ToolRegistry()
    registry.register(BrowserSemanticOperationTool.__new__(BrowserSemanticOperationTool))
    for surface in (registry.schemas(lazy=True)[0], registry.schemas(lazy=False)[0]):
        params = surface["parameters"]
        wire = json.dumps(params, ensure_ascii=False, sort_keys=True)
        assert '"enum": ["wait"]' in wire
        assert '"wait": {' not in wire
        assert params["required"] == ["steps"]


def test_mf5_1_compiles_uniform_wait_to_existing_typed_predicate_primitive() -> None:
    assert BrowserSemanticOperationTool._compile_short_steps([_wait_step()]) == [
        {
            "kind": "wait",
            "target": {
                "kind": "object",
                "identity": {"kind": "button", "name": "Finalize after ready"},
            },
            "property": "enabled",
            "operator": "eq",
            "value": True,
            "timeout_ms": 60000,
            "interval_ms": 250,
        }
    ]


def test_mf5_1_explicit_wait_operator_is_preserved() -> None:
    clause = BrowserSemanticOperationTool._compile_short_steps([_wait_step(operator="eq")])[0]
    assert clause["operator"] == "eq"


def test_mf5_1_wait_still_requires_exact_kind_and_name() -> None:
    step = _wait_step()
    step["target"] = {"kind": "button"}
    with pytest.raises(BrowserSemanticOperationContractError, match="short_target_fields_mismatch"):
        BrowserSemanticOperationTool._compile_short_steps([step])


def test_mf5_1_uniform_wait_contract_rejects_extra_strategy_fields() -> None:
    step = _wait_step()
    step["retry"] = True
    with pytest.raises(BrowserSemanticOperationContractError, match="wait_step_fields_mismatch"):
        BrowserSemanticOperationTool._compile_short_steps([step])


def test_mf5_1_stringified_steps_remain_rejected_without_coercion() -> None:
    raw = json.dumps([_wait_step()], ensure_ascii=False)
    with pytest.raises(BrowserSemanticOperationContractError, match="steps_count_out_of_bounds"):
        BrowserSemanticOperationTool._compile_short_steps(raw)


def test_mf5_1_legacy_nested_wait_is_compatibility_only() -> None:
    legacy = {
        "wait": {
            "target": {"kind": "button", "name": "Finalize after ready"},
            "property": "enabled",
            "value": True,
        },
        "within_ms": 60000,
    }
    canonical = BrowserSemanticOperationTool._compile_short_steps([_wait_step()])
    assert BrowserSemanticOperationTool._compile_short_steps([legacy]) == canonical


def test_mf5_1_provider_contract_carries_no_program_strategy_authority() -> None:
    wire = json.dumps(BrowserSemanticOperationTool.parameters, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "fuzzy",
        "best_match",
        "auto_target",
        "auto_retry",
        "rebind",
        "latest",
        "task_success",
        "task_complete",
    ):
        assert forbidden not in wire

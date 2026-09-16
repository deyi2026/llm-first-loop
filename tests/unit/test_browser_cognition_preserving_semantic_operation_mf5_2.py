from __future__ import annotations

import json
from typing import Any

import pytest

from llm_loop.tools.builtin.browser_semantic_operation import (
    BrowserSemanticOperationContractError,
    BrowserSemanticOperationTool,
)


def _provider_wait_branch() -> dict[str, Any]:
    branches = BrowserSemanticOperationTool.parameters["properties"]["steps"]["items"]["oneOf"]
    matches = [
        branch
        for branch in branches
        if "wait" in ((branch.get("properties") or {}).get("do") or {}).get("enum", [])
    ]
    assert len(matches) == 1
    return matches[0]


def _common_wait(*, until: str = "enabled", within_ms: int | None = None) -> dict[str, object]:
    step: dict[str, object] = {
        "do": "wait",
        "target": {"kind": "button", "name": "Finalize after ready"},
        "until": until,
    }
    if within_ms is not None:
        step["within_ms"] = within_ms
    return step


def test_mf5_2_provider_common_wait_uses_natural_state_affordance() -> None:
    branch = _provider_wait_branch()
    props = branch["properties"]
    assert set(props) == {"do", "target", "until", "within_ms"}
    assert branch["required"] == ["do", "target", "until"]
    assert props["until"]["enum"] == [
        "exists",
        "enabled",
        "checked",
        "selected",
        "expanded",
        "focused",
        "editable",
    ]
    assert "property" not in props
    assert "operator" not in props
    assert "value" not in props


def test_mf5_2_enabled_wait_compiles_to_existing_predicate_mechanics() -> None:
    assert BrowserSemanticOperationTool._compile_short_steps([_common_wait()]) == [
        {
            "kind": "wait",
            "target": {
                "kind": "object",
                "identity": {"kind": "button", "name": "Finalize after ready"},
            },
            "property": "enabled",
            "operator": "eq",
            "value": True,
            "timeout_ms": 60_000,
            "interval_ms": 250,
        }
    ]


@pytest.mark.parametrize(
    "state",
    ["exists", "enabled", "checked", "selected", "expanded", "focused", "editable"],
)
def test_mf5_2_common_wait_states_compile_as_true_predicates(state: str) -> None:
    clause = BrowserSemanticOperationTool._compile_short_steps([_common_wait(until=state)])[0]
    assert clause["property"] == state
    assert clause["operator"] == "eq"
    assert clause["value"] is True
    assert clause["timeout_ms"] == 60_000
    assert clause["interval_ms"] == 250


def test_mf5_2_explicit_semantic_timeout_override_is_preserved() -> None:
    clause = BrowserSemanticOperationTool._compile_short_steps(
        [_common_wait(within_ms=5_000)]
    )[0]
    assert clause["timeout_ms"] == 5_000
    assert clause["interval_ms"] == 250


def test_mf5_2_common_wait_still_requires_exact_kind_and_name() -> None:
    step = _common_wait()
    step["target"] = {"kind": "button"}
    with pytest.raises(BrowserSemanticOperationContractError, match="short_target_fields_mismatch"):
        BrowserSemanticOperationTool._compile_short_steps([step])


def test_mf5_2_common_wait_rejects_unknown_state_without_inference() -> None:
    with pytest.raises(BrowserSemanticOperationContractError, match="wait_until_not_supported"):
        BrowserSemanticOperationTool._compile_short_steps([_common_wait(until="ready_enough")])


def test_mf5_2_description_treats_one_action_as_normal_and_batching_as_optional() -> None:
    description = BrowserSemanticOperationTool.description
    assert "单个已决定动作" in description
    assert "多个动作" in description
    assert "已经决定" in description
    assert "一次声明1..8个 ordered steps" not in description


def test_mf5_2_provider_common_wait_does_not_expose_predicate_bookkeeping() -> None:
    wire = json.dumps(_provider_wait_branch(), ensure_ascii=False, sort_keys=True)
    assert '"property"' not in wire
    assert '"operator"' not in wire
    assert '"value"' not in wire
    assert '"until"' in wire


def test_mf5_2_legacy_predicate_shorthand_can_remain_compatibility_only() -> None:
    legacy = {
        "do": "wait",
        "target": {"kind": "button", "name": "Finalize after ready"},
        "property": "enabled",
        "value": True,
        "within_ms": 60_000,
    }
    clause = BrowserSemanticOperationTool._compile_short_steps([legacy])[0]
    assert clause["property"] == "enabled"
    assert clause["operator"] == "eq"
    assert clause["value"] is True


def _provider_wait_text_branch() -> dict[str, Any]:
    branches = BrowserSemanticOperationTool.parameters["properties"]["steps"]["items"]["oneOf"]
    matches = [
        branch
        for branch in branches
        if "wait_text" in ((branch.get("properties") or {}).get("do") or {}).get("enum", [])
    ]
    assert len(matches) == 1
    return matches[0]


def test_mf5_2_provider_preserves_advanced_text_wait_as_semantic_escape_hatch() -> None:
    branch = _provider_wait_text_branch()
    props = branch["properties"]
    assert set(props) == {"do", "target", "field", "match", "text", "within_ms"}
    assert branch["required"] == ["do", "target", "field", "match", "text"]
    assert props["field"]["enum"] == ["name", "value_text"]
    assert props["match"]["enum"] == ["equals", "contains", "starts_with", "ends_with"]
    assert branch["additionalProperties"] is False


@pytest.mark.parametrize(
    ("match", "operator"),
    [
        ("equals", "eq"),
        ("contains", "contains"),
        ("starts_with", "prefix"),
        ("ends_with", "suffix"),
    ],
)
def test_mf5_2_wait_text_compiles_to_existing_string_predicate(
    match: str, operator: str
) -> None:
    clause = BrowserSemanticOperationTool._compile_short_steps(
        [
            {
                "do": "wait_text",
                "target": {"kind": "status", "name": "Build status"},
                "field": "value_text",
                "match": match,
                "text": "Ready",
            }
        ]
    )[0]
    assert clause["property"] == "value_text"
    assert clause["operator"] == operator
    assert clause["value"] == "Ready"
    assert clause["timeout_ms"] == 60_000
    assert clause["interval_ms"] == 250


def test_mf5_2_wait_text_rejects_unknown_match_without_inference() -> None:
    with pytest.raises(BrowserSemanticOperationContractError, match="wait_text_match_not_supported"):
        BrowserSemanticOperationTool._compile_short_steps(
            [
                {
                    "do": "wait_text",
                    "target": {"kind": "status", "name": "Build status"},
                    "field": "value_text",
                    "match": "approximately",
                    "text": "Ready",
                }
            ]
        )

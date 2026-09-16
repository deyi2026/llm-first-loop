from __future__ import annotations

from typing import Any

from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool
from llm_loop.tools.registry import ToolRegistry


def _provider_rows() -> tuple[dict[str, Any], dict[str, Any]]:
    registry = ToolRegistry()
    registry.register(BrowserPerceiveTool.__new__(BrowserPerceiveTool))
    lazy = registry.schemas(lazy=True)[0]
    full = registry.schemas(lazy=False)[0]
    assert lazy["name"] == "browser_perceive"
    assert full["name"] == "browser_perceive"
    return lazy, full


def _object_wait_branch(params: dict[str, Any], kind: str) -> dict[str, Any]:
    for branch in params.get("oneOf") or []:
        props = branch.get("properties") or {}
        if ((props.get("action") or {}).get("enum") or []) != ["wait"]:
            continue
        if ((props.get("kind") or {}).get("enum") or []) == [kind]:
            return branch
    raise AssertionError(f"wait branch {kind!r} not found")


def test_mf5_3_4a_compact_perceive_contract_names_grounding_ref_not_object_ref() -> None:
    lazy, _full = _provider_rows()
    description = str(lazy["description"])

    assert "grounding_ref" in description
    assert "object_ref" not in description


def test_mf5_3_4a_full_perceive_contract_already_names_grounding_ref() -> None:
    _lazy, full = _provider_rows()
    description = str(full["description"])

    assert "grounding_ref" in description
    assert "object_ref" not in description


def test_mf5_3_4a_machine_object_wait_schema_already_uses_grounding_ref() -> None:
    lazy, _full = _provider_rows()
    for kind in ("object_state", "object_text"):
        branch = _object_wait_branch(lazy["parameters"], kind)
        props = branch.get("properties") or {}
        required = set(branch.get("required") or [])
        assert "grounding_ref" in props
        assert "grounding_ref" in required
        assert "object_ref" not in props
        assert "object_ref" not in required

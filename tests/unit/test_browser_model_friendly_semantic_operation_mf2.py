from __future__ import annotations

import json

from llm_loop.tools.builtin.browser_semantic_operation import BrowserSemanticOperationTool


def test_mf2_compiles_navigation_without_model_page_target() -> None:
    assert BrowserSemanticOperationTool._compile_short_steps(
        [{"do": "navigate", "url": "https://example.invalid/form"}]
    ) == [
        {
            "kind": "mutate",
            "verb": "navigate",
            "target": {"kind": "page"},
            "args": {"url": "https://example.invalid/form"},
        }
    ]


def test_mf2_compiles_set_text_to_existing_fill_replace_primitive() -> None:
    assert BrowserSemanticOperationTool._compile_short_steps(
        [{"do": "set_text", "target": {"kind": "input", "name": "Project code"}, "text": "ZX-41"}]
    ) == [
        {
            "kind": "mutate",
            "verb": "fill",
            "target": {"kind": "object", "identity": {"kind": "input", "name": "Project code"}},
            "args": {"text": "ZX-41", "mode": "replace"},
        }
    ]


def test_mf2_compiles_wait_with_runtime_owned_poll_interval() -> None:
    clause = BrowserSemanticOperationTool._compile_short_steps(
        [{"wait": {"target": {"kind": "button", "name": "Run check"}, "property": "enabled", "value": True}, "within_ms": 5000}]
    )[0]
    assert clause["property"] == "enabled"
    assert clause["operator"] == "eq"
    assert clause["value"] is True
    assert clause["timeout_ms"] == 5000
    assert clause["interval_ms"] == 250


def test_mf2_model_surface_contains_only_steps_root() -> None:
    params = BrowserSemanticOperationTool.parameters
    assert params["required"] == ["steps"]
    assert set(params["properties"]) == {"steps"}
    assert params["additionalProperties"] is False


def test_mf2_provider_surface_exposes_short_steps_not_legacy_clauses() -> None:
    from llm_loop.tools.registry import ToolRegistry

    reg = ToolRegistry()
    reg.register(BrowserSemanticOperationTool.__new__(BrowserSemanticOperationTool))
    lazy = reg.schemas(lazy=True)[0]
    full = reg.schemas(lazy=False)[0]
    for surface in (lazy, full):
        params = surface["parameters"]
        assert params["required"] == ["steps"]
        assert set(params["properties"]) == {"steps"}
        assert "clauses" not in json.dumps(params, sort_keys=True)
    compact = lazy["description"]
    assert "steps" in compact
    assert "target=exact" in compact
    assert "clauses" not in compact
    assert "set_text" in json.dumps(lazy["parameters"], sort_keys=True)

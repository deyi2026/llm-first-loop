"""Capacity-aware schema representation: mechanical, no Provider/network in unit tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

from llm_loop.core.loop.engine_services.schema_capacity import (
    select_schema_capacity_projection,
)


def _schemas(*, count=101, discovery=True):
    names = (["get_tool_schema"] if discovery else []) + [
        f"tool_{i:03d}" for i in range(count - int(discovery))
    ]
    return [
        {
            "name": name,
            "description": "a" * 300,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "b" * 300},
                    "options": {"type": "object", "properties": {
                        "mode": {"type": "string", "enum": ["read", "write"]},
                    }},
                },
                "required": ["path"],
            },
        }
        for name in names
    ]


def _select(*, discovery=True, allowed=32768, counter=None, cpt=0.9):
    schemas = _schemas(discovery=discovery)
    registry = SimpleNamespace(
        index_schemas=lambda desc_chars: [
            {"name": row["name"], "description": row["description"][:desc_chars],
             "parameters": {"type": "object"}}
            for row in schemas
        ]
    )
    def converter(row):
        return {"type": "function", "function": row}

    return schemas, select_schema_capacity_projection(
        registry=registry,
        eligible_schemas=schemas,
        schema_to_param=converter,
        allowed_input_tokens=allowed,
        projection_chars_per_token=cpt,
        count_tool_schema_tokens=counter,
    )


def test_schema_pressure_switches_all_tools_to_index_without_hiding():
    schemas, chosen = _select(counter=lambda tools: len(json.dumps(tools)) // 3)
    assert chosen.mode == "index_80"
    assert chosen.original_tokens > chosen.threshold_tokens
    assert chosen.selected_tokens <= chosen.threshold_tokens
    assert [row["name"] for row in chosen.schemas] == [row["name"] for row in schemas]
    assert len(chosen.tools) == 101
    assert all(row["function"]["parameters"] == {"type": "object"} for row in chosen.tools)
    assert chosen.token_source == "authoritative_tokenizer"


def test_schema_without_callable_discovery_must_not_degrade():
    schemas, chosen = _select(discovery=False, counter=lambda tools: len(json.dumps(tools)) // 3)
    assert chosen.mode == "stable"
    assert chosen.reason == "discovery_unavailable"
    assert [row["name"] for row in chosen.schemas] == [row["name"] for row in schemas]


def test_schema_budget_unknown_preserves_full_surface():
    _schemas_original, chosen = _select(allowed=None)
    assert chosen.mode == "stable"
    assert chosen.reason == "capacity_unknown"


def test_no_pressure_keeps_full_parameter_contracts():
    schemas, chosen = _select(allowed=184000, counter=lambda _tools: 28000)
    assert chosen.mode == "stable"
    assert chosen.schemas[0]["parameters"] == schemas[0]["parameters"]


def test_counter_failure_falls_back_to_existing_char_density():
    def broken(_tools):
        raise RuntimeError("tokenizer offline")
    _schemas_original, chosen = _select(counter=broken)
    assert chosen.token_source == "projection_fallback"
    assert chosen.mode.startswith("index_")


def test_admission_never_promotes_filtered_or_unhealthy_tool():
    schemas = [row for row in _schemas() if row["name"] not in {"tool_001", "tool_005"}]
    registry = SimpleNamespace(index_schemas=lambda desc_chars: [
        {"name": row["name"], "description": row["description"][:desc_chars],
         "parameters": {"type": "object"}}
        for row in _schemas()  # full registry includes denied tools
    ])
    chosen = select_schema_capacity_projection(
        registry=registry,
        eligible_schemas=schemas,
        schema_to_param=lambda row: {"type": "function", "function": row},
        allowed_input_tokens=32768,
        projection_chars_per_token=0.9,
        count_tool_schema_tokens=lambda tools: len(json.dumps(tools)) // 3,
    )
    assert chosen.mode.startswith("index_")
    assert [row["name"] for row in chosen.schemas] == [row["name"] for row in schemas]
    assert "tool_001" not in [row["name"] for row in chosen.schemas]


def test_index_catalog_failure_preserves_original_surface():
    schemas = _schemas()

    def broken_index(**_kwargs):
        raise ValueError("index unavailable")

    chosen = select_schema_capacity_projection(
        registry=SimpleNamespace(index_schemas=broken_index),
        eligible_schemas=schemas,
        schema_to_param=lambda row: {"type": "function", "function": row},
        allowed_input_tokens=32768,
        projection_chars_per_token=0.9,
        count_tool_schema_tokens=lambda tools: len(json.dumps(tools)) // 3,
    )
    assert chosen.mode == "stable"
    assert chosen.reason == "index_invalid"
    assert [row["name"] for row in chosen.schemas] == [row["name"] for row in schemas]

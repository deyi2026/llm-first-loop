"""P4-D qualification-only typed Browser compiler.

This helper exists only under ``tools/semantic_logic`` for deterministic P4-D
qualification.  It validates the frozen Arm-B declaration shapes, translates a
declared typed call into the already-qualified Arm-A canonical request, and
delegates compilation to ``BrowserSemanticExecuteTool.compile_request``.

It intentionally has no registration, execution, retry, recovery, target
selection, or completion behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = ROOT / "docs/SMC-SEMANTIC-LOGIC-P4-AB-PROTOCOL-v0.1.json"
_PROTOCOL = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
P4_TYPED_TOOL_SCHEMAS: dict[str, dict[str, Any]] = _PROTOCOL["arm_b"]["mutation_tools"]


class P4TypedCompilerError(ValueError):
    """Frozen typed-surface declaration is structurally invalid."""


_TRANSLATION = {
    "browser_semantic_click": ("click", "object_ref", ()),
    "browser_semantic_fill": ("fill", "object_ref", ("text", "mode")),
    "browser_semantic_select": ("select", "object_ref", ("value",)),
    "browser_semantic_scroll": ("scroll", "object_ref", ("delta_pages",)),
    "browser_semantic_navigate": ("navigate", "resource_ref", ("url",)),
}


def _validate_scalar(*, field: str, value: Any, spec: dict[str, Any]) -> None:
    expected_type = spec.get("type")
    if expected_type == "string":
        if not isinstance(value, str):
            raise P4TypedCompilerError(f"{field}_must_be_string")
        minimum = int(spec.get("minLength", 0))
        if len(value) < minimum:
            raise P4TypedCompilerError(f"{field}_too_short")
    elif expected_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise P4TypedCompilerError(f"{field}_must_be_number")
    else:
        raise P4TypedCompilerError(f"{field}_unsupported_frozen_type:{expected_type}")

    enum = spec.get("enum")
    if isinstance(enum, list) and value not in enum:
        raise P4TypedCompilerError(f"{field}_not_in_frozen_enum")


def _validate_typed_request(tool_name: str, request: dict[str, Any]) -> None:
    schema = P4_TYPED_TOOL_SCHEMAS.get(tool_name)
    if not isinstance(schema, dict):
        raise P4TypedCompilerError("typed_tool_not_in_frozen_surface")

    required = schema.get("required_fields")
    properties = schema.get("properties")
    if not isinstance(required, list) or not isinstance(properties, dict):
        raise P4TypedCompilerError("frozen_typed_schema_invalid")
    if set(request) != set(required):
        raise P4TypedCompilerError("typed_request_fields_mismatch")

    for field in required:
        field_spec = properties.get(field)
        if not isinstance(field_spec, dict):
            raise P4TypedCompilerError(f"{field}_schema_missing")
        _validate_scalar(field=field, value=request[field], spec=field_spec)


class P4TypedCompiler:
    """Compile one frozen Arm-B declaration through the existing Arm-A compiler."""

    def __init__(self, semantic_execute: BrowserSemanticExecuteTool) -> None:
        self._semantic_execute = semantic_execute

    def canonical_request(self, tool_name: str, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise P4TypedCompilerError("typed_request_must_be_object")
        _validate_typed_request(tool_name, request)
        verb, ref_field, arg_fields = _TRANSLATION[tool_name]
        return {
            "verb": verb,
            "target_ref": request[ref_field],
            "args": {field: request[field] for field in arg_fields},
        }

    def compile(
        self,
        session_id: str,
        tool_name: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        canonical = self.canonical_request(tool_name, request)
        return self._semantic_execute.compile_request(session_id, canonical)

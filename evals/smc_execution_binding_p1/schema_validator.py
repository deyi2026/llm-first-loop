"""Tiny fail-closed validator for the frozen Execution Binding v0.1 schema.

This is intentionally evaluation-only. It implements only the JSON Schema
keywords used by the frozen v0.1 artifact and rejects unknown schema keywords,
so qualification cannot silently skip a constraint.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


class SchemaValidationError(ValueError):
    """Raised when an instance violates the frozen schema."""


class UnsupportedSchemaKeywordError(ValueError):
    """Raised when the frozen schema contains an unsupported keyword."""


_SUPPORTED_KEYWORDS = {
    "$schema",
    "$id",
    "$defs",
    "$ref",
    "title",
    "description",
    "oneOf",
    "anyOf",
    "type",
    "required",
    "properties",
    "additionalProperties",
    "const",
    "enum",
    "items",
    "uniqueItems",
    "minLength",
    "minimum",
    "pattern",
    "format",
}


class FrozenSchemaValidator:
    """Validate instances against the exact frozen schema keyword subset."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema

    @classmethod
    def from_path(cls, path: Path) -> FrozenSchemaValidator:
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def assert_supported_schema(self) -> None:
        self._assert_supported(self.schema, "$")

    def validate(self, instance: Any) -> None:
        self.assert_supported_schema()
        self._validate(instance, self.schema, "$")

    def _assert_supported(self, schema: Any, path: str) -> None:
        if not isinstance(schema, dict):
            raise UnsupportedSchemaKeywordError(f"{path}: schema node must be an object")
        unknown = set(schema) - _SUPPORTED_KEYWORDS
        if unknown:
            key = sorted(unknown)[0]
            raise UnsupportedSchemaKeywordError(f"{path}: unsupported schema keyword {key}")

        defs = schema.get("$defs")
        if defs is not None:
            if not isinstance(defs, dict):
                raise UnsupportedSchemaKeywordError(f"{path}.$defs: expected object")
            for name, child in defs.items():
                self._assert_supported(child, f"{path}.$defs.{name}")

        props = schema.get("properties")
        if props is not None:
            if not isinstance(props, dict):
                raise UnsupportedSchemaKeywordError(f"{path}.properties: expected object")
            for name, child in props.items():
                self._assert_supported(child, f"{path}.properties.{name}")

        for keyword in ("oneOf", "anyOf"):
            children = schema.get(keyword)
            if children is not None:
                if not isinstance(children, list):
                    raise UnsupportedSchemaKeywordError(f"{path}.{keyword}: expected array")
                for index, child in enumerate(children):
                    self._assert_supported(child, f"{path}.{keyword}[{index}]")

        items = schema.get("items")
        if items is not None:
            self._assert_supported(items, f"{path}.items")

    def _resolve_ref(self, ref: str) -> dict[str, Any]:
        if not ref.startswith("#/"):
            raise UnsupportedSchemaKeywordError(f"external $ref unsupported: {ref}")
        node: Any = self.schema
        for raw in ref[2:].split("/"):
            segment = raw.replace("~1", "/").replace("~0", "~")
            try:
                node = node[segment]
            except (KeyError, TypeError) as exc:
                raise UnsupportedSchemaKeywordError(f"unresolvable $ref: {ref}") from exc
        if not isinstance(node, dict):
            raise UnsupportedSchemaKeywordError(f"$ref target is not a schema object: {ref}")
        return node

    def _validate(self, instance: Any, schema: dict[str, Any], path: str) -> None:
        if "$ref" in schema:
            self._validate(instance, self._resolve_ref(schema["$ref"]), path)

        if "oneOf" in schema:
            matches = 0
            errors: list[str] = []
            for child in schema["oneOf"]:
                try:
                    self._validate(instance, child, path)
                except SchemaValidationError as exc:
                    errors.append(str(exc))
                    continue
                matches += 1
            if matches != 1:
                detail = "; ".join(errors)
                raise SchemaValidationError(
                    f"{path}: oneOf expected exactly one match, got {matches}; {detail}"
                )

        if "anyOf" in schema:
            errors = []
            for child in schema["anyOf"]:
                try:
                    self._validate(instance, child, path)
                except SchemaValidationError as exc:
                    errors.append(str(exc))
                    continue
                break
            else:
                raise SchemaValidationError(f"{path}: anyOf matched no branch; {'; '.join(errors)}")

        if "const" in schema and instance != schema["const"]:
            raise SchemaValidationError(
                f"{path}: const expected {schema['const']!r}, got {instance!r}"
            )

        if "enum" in schema and instance not in schema["enum"]:
            raise SchemaValidationError(
                f"{path}: enum value {instance!r} not in {schema['enum']!r}"
            )

        if "type" in schema and not self._matches_type(instance, schema["type"]):
            raise SchemaValidationError(
                f"{path}: type expected {schema['type']!r}, got {type(instance).__name__}"
            )

        if isinstance(instance, dict):
            self._validate_object(instance, schema, path)
        elif isinstance(instance, list):
            self._validate_array(instance, schema, path)
        elif isinstance(instance, str):
            self._validate_string(instance, schema, path)
        elif self._is_number(instance):
            minimum = schema.get("minimum")
            if minimum is not None and instance < minimum:
                raise SchemaValidationError(f"{path}: minimum {minimum} violated by {instance}")

    def _validate_object(self, instance: dict[str, Any], schema: dict[str, Any], path: str) -> None:
        required = schema.get("required", [])
        for name in required:
            if name not in instance:
                raise SchemaValidationError(f"{path}: required property missing: {name}")

        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(properties)
            if extra:
                raise SchemaValidationError(
                    f"{path}: additional property not allowed: {sorted(extra)[0]}"
                )

        for name, child in properties.items():
            if name in instance:
                self._validate(instance[name], child, f"{path}.{name}")

    def _validate_array(self, instance: list[Any], schema: dict[str, Any], path: str) -> None:
        items = schema.get("items")
        if items is not None:
            for index, value in enumerate(instance):
                self._validate(value, items, f"{path}[{index}]")
        if schema.get("uniqueItems"):
            seen: set[str] = set()
            for value in instance:
                canonical = json.dumps(
                    value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                if canonical in seen:
                    raise SchemaValidationError(f"{path}: uniqueItems violated")
                seen.add(canonical)

    def _validate_string(self, instance: str, schema: dict[str, Any], path: str) -> None:
        minimum = schema.get("minLength")
        if minimum is not None and len(instance) < minimum:
            raise SchemaValidationError(f"{path}: minLength {minimum} violated by {len(instance)}")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, instance) is None:
            raise SchemaValidationError(f"{path}: pattern {pattern!r} not matched by {instance!r}")
        fmt = schema.get("format")
        if fmt == "date-time":
            try:
                value = instance[:-1] + "+00:00" if instance.endswith("Z") else instance
                parsed = datetime.fromisoformat(value)
            except ValueError as exc:
                raise SchemaValidationError(
                    f"{path}: format date-time invalid: {instance!r}"
                ) from exc
            if parsed.tzinfo is None:
                raise SchemaValidationError(
                    f"{path}: format date-time requires timezone: {instance!r}"
                )
        elif fmt is not None:
            raise UnsupportedSchemaKeywordError(f"{path}: unsupported format {fmt!r}")

    @staticmethod
    def _is_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @classmethod
    def _matches_type(cls, instance: Any, expected: Any) -> bool:
        choices = expected if isinstance(expected, list) else [expected]
        return any(cls._matches_single_type(instance, choice) for choice in choices)

    @classmethod
    def _matches_single_type(cls, instance: Any, expected: str) -> bool:
        if expected == "object":
            return isinstance(instance, dict)
        if expected == "array":
            return isinstance(instance, list)
        if expected == "string":
            return isinstance(instance, str)
        if expected == "integer":
            return isinstance(instance, int) and not isinstance(instance, bool)
        if expected == "number":
            return cls._is_number(instance)
        if expected == "boolean":
            return isinstance(instance, bool)
        if expected == "null":
            return instance is None
        raise UnsupportedSchemaKeywordError(f"unsupported JSON Schema type {expected!r}")

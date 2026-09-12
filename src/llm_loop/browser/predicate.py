"""Mechanical Browser Predicate validation and single-snapshot evaluation.

This module deliberately knows nothing about tasks, relevance, completion, recovery,
or backend locators.  It evaluates the closed Browser Phase-1 Predicate vocabulary
against one already-persisted exact observation.  Polling is owned by the thin
model-facing tool layer; this module never retries or recaptures the world.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

_SEMANTIC_ID_RE = re.compile(r"el_[0-9a-f]{20}")

PREDICATE_SPECS: dict[str, dict[str, Any]] = {
    "exists": {
        "operators": ("eq",),
        "value_type": "boolean",
        "negative_requires_complete_coverage": True,
        "target_kind": "semantic_object",
    },
    "enabled": {
        "operators": ("eq",),
        "value_type": "boolean",
        "negative_requires_complete_coverage": False,
        "target_kind": "semantic_object",
    },
    "visible": {
        "operators": ("eq",),
        "value_type": "boolean",
        "negative_requires_complete_coverage": False,
        "target_kind": "semantic_object",
    },
    "checked": {
        "operators": ("eq",),
        "value_type": "boolean",
        "negative_requires_complete_coverage": False,
        "target_kind": "semantic_object",
    },
    "selected": {
        "operators": ("eq",),
        "value_type": "boolean",
        "negative_requires_complete_coverage": False,
        "target_kind": "semantic_object",
    },
    "expanded": {
        "operators": ("eq",),
        "value_type": "boolean",
        "negative_requires_complete_coverage": False,
        "target_kind": "semantic_object",
    },
    "focused": {
        "operators": ("eq",),
        "value_type": "boolean",
        "negative_requires_complete_coverage": False,
        "target_kind": "semantic_object",
    },
    "editable": {
        "operators": ("eq",),
        "value_type": "boolean",
        "negative_requires_complete_coverage": False,
        "target_kind": "semantic_object",
    },
    "url": {
        "operators": ("eq", "contains", "prefix", "suffix"),
        "value_type": "string",
        "negative_requires_complete_coverage": False,
        "target_kind": "scope",
    },
    "name": {
        "operators": ("eq", "contains", "prefix", "suffix"),
        "value_type": "string",
        "negative_requires_complete_coverage": False,
        "target_kind": "semantic_object",
    },
    "value_text": {
        "operators": ("eq", "contains", "prefix", "suffix"),
        "value_type": "string",
        "negative_requires_complete_coverage": False,
        "target_kind": "semantic_object",
    },
    "document_ready_state": {
        "operators": ("eq",),
        "value_type": "string",
        "value_enum": ("loading", "interactive", "complete"),
        "negative_requires_complete_coverage": False,
        "target_kind": "scope",
    },
    "object_count": {
        "operators": ("eq", "ge", "le"),
        "value_type": "integer",
        "negative_requires_complete_coverage": True,
        "target_kind": "scope",
    },
}

_PREDICATE_KEYS = {
    "schema",
    "domain",
    "scope_ref",
    "target",
    "property",
    "operator",
    "value",
}
_STATE_PROPERTIES = {
    "enabled",
    "visible",
    "checked",
    "selected",
    "expanded",
    "focused",
    "editable",
}
_ATTRIBUTE_PROPERTIES = {"name", "value_text"}


def predicate_parameter_schema() -> dict[str, Any]:
    """Return a closed provider-facing JSON schema for one Browser Predicate."""
    return {
        "type": "object",
        "properties": {
            "schema": {"type": "string", "enum": ["smc.predicate.v0.1"]},
            "domain": {"type": "string", "enum": ["browser"]},
            "scope_ref": {
                "type": "string",
                "minLength": 1,
                "description": "exact semantic scope_ref from Browser observation",
            },
            "target": {
                "type": "string",
                "minLength": 1,
                "description": "SemanticObject ID, or exactly scope_ref for scope predicates",
            },
            "property": {
                "type": "string",
                "enum": list(PREDICATE_SPECS),
            },
            "operator": {
                "type": "string",
                "enum": ["eq", "contains", "prefix", "suffix", "ge", "le"],
            },
            "value": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "boolean"},
                    {"type": "integer"},
                ]
            },
        },
        "required": [
            "schema",
            "domain",
            "scope_ref",
            "target",
            "property",
            "operator",
            "value",
        ],
        "additionalProperties": False,
    }


def validate_predicate(predicate: Any) -> str | None:
    """Return a mechanical contract error, or ``None`` when structurally valid."""
    if not isinstance(predicate, dict):
        return "predicate must be a structured object"
    extras = set(predicate) - _PREDICATE_KEYS
    missing = _PREDICATE_KEYS - set(predicate)
    if extras:
        return f"predicate additional properties are forbidden: {sorted(extras)}"
    if missing:
        return f"predicate missing required fields: {sorted(missing)}"
    if predicate.get("schema") != "smc.predicate.v0.1":
        return "predicate schema must be smc.predicate.v0.1"
    if predicate.get("domain") != "browser":
        return "predicate domain must be browser"
    scope_ref = predicate.get("scope_ref")
    target = predicate.get("target")
    if not isinstance(scope_ref, str) or not scope_ref.strip():
        return "predicate scope_ref must be a non-empty semantic scope reference"
    if not isinstance(target, str) or not target.strip():
        return "predicate target must be a non-empty semantic reference"

    property_name = predicate.get("property")
    spec = PREDICATE_SPECS.get(str(property_name))
    if spec is None:
        return f"unknown predicate property: {property_name!r}"
    operator = predicate.get("operator")
    if operator not in spec["operators"]:
        return f"predicate operator mismatch for {property_name}: {operator!r}"
    value = predicate.get("value")
    value_type = spec["value_type"]
    type_ok = {
        "boolean": isinstance(value, bool),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
    }[value_type]
    if not type_ok:
        return f"predicate value type mismatch for {property_name}: expected {value_type}"
    if "value_enum" in spec and value not in spec["value_enum"]:
        return f"predicate value enum mismatch for {property_name}: {value!r}"
    if spec["target_kind"] == "semantic_object":
        if _SEMANTIC_ID_RE.fullmatch(target) is None:
            return "object predicate target must be an exact Browser SemanticObject ID"
    elif target != scope_ref:
        return "scope predicate target must equal its exact scope_ref"
    return None


def _compare(observed: Any, operator: str, expected: Any) -> bool:
    if operator == "eq":
        return observed == expected
    if operator == "contains":
        return str(expected) in str(observed)
    if operator == "prefix":
        return str(observed).startswith(str(expected))
    if operator == "suffix":
        return str(observed).endswith(str(expected))
    if operator == "ge":
        return observed >= expected
    if operator == "le":
        return observed <= expected
    raise ValueError(f"unsupported predicate operator: {operator}")


def _scope_descendants(scope_facts: list[dict[str, Any]], scope_ref: str) -> set[str]:
    selected = {scope_ref}
    changed = True
    while changed:
        changed = False
        for fact in scope_facts:
            child = str(fact.get("scope_ref") or "")
            parent = str(fact.get("parent_scope_ref") or "")
            if child and parent in selected and child not in selected:
                selected.add(child)
                changed = True
    return selected


def _result(
    *,
    snapshot_id: str,
    scope_ref: str,
    target: str,
    property_name: str,
    result: str,
    observed_value: Any,
    coverage_complete: bool,
    reason: str | None,
    objects_ref: str,
) -> dict[str, Any]:
    return {
        "result": result,
        "snapshot_id": snapshot_id,
        "scope_ref": scope_ref,
        "target": target,
        "property": property_name,
        "observed_value": observed_value,
        "coverage_complete": coverage_complete,
        "reason": reason,
        "objects_ref": objects_ref,
    }


def evaluate_predicate(
    *,
    bundle: dict[str, Any],
    predicate: dict[str, Any],
    known_stable_scope: Callable[[str], str | None],
) -> dict[str, Any]:
    """Evaluate one valid Predicate against one exact persisted snapshot bundle."""
    validation_error = validate_predicate(predicate)
    if validation_error is not None:
        raise ValueError(validation_error)

    snapshot = dict(bundle.get("snapshot") or {})
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    scope_ref = str(predicate["scope_ref"])
    target = str(predicate["target"])
    property_name = str(predicate["property"])
    operator = str(predicate["operator"])
    expected = predicate["value"]
    completeness = dict(snapshot.get("completeness") or {})
    coverage_complete = bool(completeness.get("complete", False))
    objects_ref = str(snapshot.get("objects_ref") or "")
    scope_facts = [fact for fact in list(bundle.get("scope_facts") or []) if isinstance(fact, dict)]
    current_scopes = {str(fact.get("scope_ref") or "") for fact in scope_facts}

    if scope_ref not in current_scopes:
        return _result(
            snapshot_id=snapshot_id,
            scope_ref=scope_ref,
            target=target,
            property_name=property_name,
            result="indeterminate",
            observed_value=None,
            coverage_complete=False,
            reason="scope_not_observed",
            objects_ref=objects_ref,
        )

    objects = {
        str(obj.get("id") or ""): obj
        for obj in list(bundle.get("objects") or [])
        if isinstance(obj, dict) and obj.get("id")
    }
    spec = PREDICATE_SPECS[property_name]
    if spec["target_kind"] == "semantic_object":
        obj = objects.get(target)
        if obj is None:
            if property_name != "exists":
                return _result(
                    snapshot_id=snapshot_id,
                    scope_ref=scope_ref,
                    target=target,
                    property_name=property_name,
                    result="indeterminate",
                    observed_value=None,
                    coverage_complete=coverage_complete,
                    reason="target_not_observed",
                    objects_ref=objects_ref,
                )
            stable_scope = known_stable_scope(target)
            if stable_scope is None:
                return _result(
                    snapshot_id=snapshot_id,
                    scope_ref=scope_ref,
                    target=target,
                    property_name=property_name,
                    result="indeterminate",
                    observed_value=None,
                    coverage_complete=coverage_complete,
                    reason="target_identity_unknown_or_identity_unstable",
                    objects_ref=objects_ref,
                )
            if stable_scope != scope_ref:
                return _result(
                    snapshot_id=snapshot_id,
                    scope_ref=scope_ref,
                    target=target,
                    property_name=property_name,
                    result="indeterminate",
                    observed_value=None,
                    coverage_complete=coverage_complete,
                    reason="target_scope_mismatch",
                    objects_ref=objects_ref,
                )
            if not coverage_complete:
                return _result(
                    snapshot_id=snapshot_id,
                    scope_ref=scope_ref,
                    target=target,
                    property_name=property_name,
                    result="indeterminate",
                    observed_value=None,
                    coverage_complete=False,
                    reason="coverage_incomplete_for_absence",
                    objects_ref=objects_ref,
                )
            observed = False
        else:
            if str(obj.get("scope_ref") or "") != scope_ref:
                return _result(
                    snapshot_id=snapshot_id,
                    scope_ref=scope_ref,
                    target=target,
                    property_name=property_name,
                    result="indeterminate",
                    observed_value=None,
                    coverage_complete=coverage_complete,
                    reason="target_scope_mismatch",
                    objects_ref=objects_ref,
                )
            if property_name == "exists":
                observed = True
            elif property_name in _STATE_PROPERTIES:
                observed = (obj.get("state") or {}).get(property_name)
            elif property_name in _ATTRIBUTE_PROPERTIES:
                observed = (obj.get("attributes") or {}).get(property_name)
            else:  # pragma: no cover - vocabulary is closed above.
                raise AssertionError(f"unhandled object predicate property: {property_name}")
            if observed is None:
                return _result(
                    snapshot_id=snapshot_id,
                    scope_ref=scope_ref,
                    target=target,
                    property_name=property_name,
                    result="indeterminate",
                    observed_value=None,
                    coverage_complete=coverage_complete,
                    reason="property_unobserved",
                    objects_ref=objects_ref,
                )

        return _result(
            snapshot_id=snapshot_id,
            scope_ref=scope_ref,
            target=target,
            property_name=property_name,
            result="satisfied" if _compare(observed, operator, expected) else "unsatisfied",
            observed_value=observed,
            coverage_complete=coverage_complete,
            reason=None,
            objects_ref=objects_ref,
        )

    scope_observations = dict((bundle.get("private_capture") or {}).get("scope_observations") or {})
    if property_name in {"url", "document_ready_state"}:
        observed = (scope_observations.get(scope_ref) or {}).get(property_name)
        if observed is None:
            return _result(
                snapshot_id=snapshot_id,
                scope_ref=scope_ref,
                target=target,
                property_name=property_name,
                result="indeterminate",
                observed_value=None,
                coverage_complete=coverage_complete,
                reason="property_unobserved",
                objects_ref=objects_ref,
            )
        return _result(
            snapshot_id=snapshot_id,
            scope_ref=scope_ref,
            target=target,
            property_name=property_name,
            result="satisfied" if _compare(observed, operator, expected) else "unsatisfied",
            observed_value=observed,
            coverage_complete=coverage_complete,
            reason=None,
            objects_ref=objects_ref,
        )

    if property_name != "object_count":  # pragma: no cover - vocabulary is closed above.
        raise AssertionError(f"unhandled scope predicate property: {property_name}")
    selected_scopes = _scope_descendants(scope_facts, scope_ref)
    observed_count = sum(
        1 for obj in objects.values() if str(obj.get("scope_ref") or "") in selected_scopes
    )
    if coverage_complete:
        return _result(
            snapshot_id=snapshot_id,
            scope_ref=scope_ref,
            target=target,
            property_name=property_name,
            result="satisfied" if _compare(observed_count, operator, expected) else "unsatisfied",
            observed_value=observed_count,
            coverage_complete=True,
            reason=None,
            objects_ref=objects_ref,
        )

    decisive: bool | None = None
    if operator == "ge" and observed_count >= expected:
        decisive = True
    elif operator in {"eq", "le"} and observed_count > expected:
        decisive = False
    if decisive is None:
        return _result(
            snapshot_id=snapshot_id,
            scope_ref=scope_ref,
            target=target,
            property_name=property_name,
            result="indeterminate",
            observed_value=observed_count,
            coverage_complete=False,
            reason="coverage_incomplete_lower_bound_only",
            objects_ref=objects_ref,
        )
    return _result(
        snapshot_id=snapshot_id,
        scope_ref=scope_ref,
        target=target,
        property_name=property_name,
        result="satisfied" if decisive else "unsatisfied",
        observed_value=observed_count,
        coverage_complete=False,
        reason="coverage_incomplete_but_lower_bound_is_decisive",
        objects_ref=objects_ref,
    )

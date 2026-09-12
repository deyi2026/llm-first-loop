from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "docs" / "SMC-BROWSER-PHASE1-PROFILE-v0.1.json"
SCHEMA_PATH = ROOT / "docs" / "SMC-BROWSER-PHASE1-SCHEMA-v0.1.json"
R3_PATH = ROOT / "docs" / "SMC-R3-BROWSER-PAPER-STRESS-20260913.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_ref(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    assert ref.startswith("#/$defs/")
    return root["$defs"][ref.removeprefix("#/$defs/")]


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise AssertionError(f"unsupported test-schema type: {expected}")


def _validate(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str = "$") -> list[str]:
    schema = _resolve_ref(schema, root)
    errors: list[str] = []

    if "oneOf" in schema:
        matches = [
            branch
            for branch in schema["oneOf"]
            if not _validate(value, branch, root, path)
        ]
        if len(matches) != 1:
            return [f"{path}: expected exactly one oneOf branch, got {len(matches)}"]
        return []
    if "anyOf" in schema:
        if not any(not _validate(value, branch, root, path) for branch in schema["anyOf"]):
            return [f"{path}: no anyOf branch matched"]
        return []

    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        if not any(_matches_type(value, t) for t in expected_type):
            return [f"{path}: expected one of {expected_type}, got {type(value).__name__}"]
    elif isinstance(expected_type, str) and not _matches_type(value, expected_type):
        return [f"{path}: expected {expected_type}, got {type(value).__name__}"]

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum")
    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            errors.append(f"{path}: string shorter than minLength")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            errors.append(f"{path}: pattern mismatch")
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and "minimum" in schema
        and value < schema["minimum"]
    ):
        errors.append(f"{path}: below minimum")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than minItems")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                errors.extend(_validate(item, item_schema, root, f"{path}[{idx}]"))
    if isinstance(value, dict):
        required = set(schema.get("required", []))
        missing = required - set(value)
        if missing:
            errors.append(f"{path}: missing {sorted(missing)}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(properties)
            if extra:
                errors.append(f"{path}: unexpected {sorted(extra)}")
        for key, child in value.items():
            if key in properties:
                errors.extend(_validate(child, properties[key], root, f"{path}.{key}"))
    return errors


def _assert_valid(value: Any, schema_name: str, schema: dict[str, Any]) -> None:
    errors = _validate(value, {"$ref": f"#/$defs/{schema_name}"}, schema)
    assert errors == []


def _action_profile_errors(
    action: dict[str, Any], profile: dict[str, Any], schema: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    verb = action.get("verb")
    contract = profile["verb_contracts"].get(verb)
    if contract is None:
        return [f"unknown verb: {verb!r}"]
    for field in ("operation_class", "idempotency_class", "atomicity_class"):
        if action.get(field) != contract[field]:
            errors.append(f"{field} mismatch")
    errors.extend(
        _validate(
            action.get("args"),
            {"$ref": f"#/$defs/{contract['args_schema']}"},
            schema,
            "$.args",
        )
    )
    if contract["version_precondition"] == "required":
        if action.get("version_precondition") != "required":
            errors.append("version_precondition mismatch")
        if not action.get("expected_version"):
            errors.append("expected_version required")
        if action.get("version_scope") not in contract["version_scopes"]:
            errors.append("version_scope mismatch")
    else:
        if action.get("version_precondition") != contract["version_precondition"]:
            errors.append("version_precondition mismatch")
        if action.get("expected_version") is not None:
            errors.append("unexpected expected_version")
        if action.get("version_scope") is not None:
            errors.append("unexpected version_scope")
    return errors


def _predicate_profile_errors(predicate: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    prop = predicate.get("property")
    spec = profile["predicate_vocabulary"]["properties"].get(prop)
    if spec is None:
        return [f"unknown property: {prop!r}"]
    if predicate.get("operator") not in spec["operators"]:
        errors.append("operator mismatch")
    value = predicate.get("value")
    value_type = spec["value_type"]
    value_type_matches = {
        "boolean": isinstance(value, bool),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
    }.get(value_type, False)
    if not value_type_matches:
        errors.append("value type mismatch")
    if "value_enum" in spec and value not in spec["value_enum"]:
        errors.append("value enum mismatch")
    return errors


def test_browser_profile_covers_b0_b14_and_phase1_r3_cases() -> None:
    profile = _load(PROFILE_PATH)
    r3 = _load(R3_PATH)

    assert set(profile) == {
        "schema",
        "profile_id",
        "domain",
        "phase",
        "implementation_status",
        "profiles",
        "schema_file",
        "surface",
        "scope_model",
        "sensors",
        "conflict_contract",
        "field_vocabulary",
        "predicate_vocabulary",
        "verb_contracts",
        "diff_contract",
        "retry_contract",
        "receipt_contract",
        "grounding_contract",
        "boundary_event_vocabulary",
        "qualification_gate_map",
        "r3_phase1_fixture_map",
        "non_claims",
        "examples",
    }
    assert profile["schema"] == "smc.browser_phase1_profile.v0.1"
    assert profile["profile_id"] == "browser-phase1-v0.1"
    assert profile["domain"] == "browser"
    assert profile["phase"] == 1
    assert set(profile["profiles"]) == {"smc-perception-v0.1", "smc-manipulation-v0.1"}
    assert set(profile["qualification_gate_map"]) == {f"B{i}" for i in range(15)}

    deferred = {
        row["id"]
        for row in r3["scenarios"]
        if row["contract_verdict_after_amendment"] == "DEFERRED"
    }
    phase1_ids = {row["id"] for row in r3["scenarios"]} - deferred
    assert set(profile["r3_phase1_fixture_map"]) == phase1_ids
    assert deferred == {"R3-14", "R3-29"}


def test_surface_isolation_and_no_model_facing_ephemeral_locators() -> None:
    profile = _load(PROFILE_PATH)

    assert profile["surface"]["legacy_direct_model_tools"] == []
    assert set(profile["surface"]["legacy_backend_only_tools"]) >= {
        "playwright_exec",
        "playwright_test",
    }
    assert profile["surface"]["intervention_if_model_direct_legacy_tool"] is True
    assert set(profile["surface"]["forbidden_model_locator_types"]) == {
        "css_selector",
        "xpath",
        "coordinate",
        "cdp_node_id",
        "ax_index",
        "native_handle",
    }


def test_scope_sensor_and_c28_conflict_contract_are_closed() -> None:
    profile = _load(PROFILE_PATH)

    assert profile["scope_model"]["kinds"] == ["runtime", "page", "document", "frame"]
    assert profile["scope_model"]["id_uniqueness"] == "runtime_session"
    assert profile["scope_model"]["navigation_changes_document_generation"] is True
    assert profile["sensors"]["active"] == ["dom", "ax"]
    assert profile["sensors"]["vision"] == "explicit_only_deferred_phase2"
    assert profile["sensors"]["silent_source_priority"] is False
    assert profile["conflict_contract"]["unresolved_canonical_value"] is None
    assert profile["conflict_contract"]["preserve_source_value_grounding"] is True
    assert profile["conflict_contract"]["force_identity_fusion_on_ambiguity"] is False


def test_predicate_vocabulary_is_structured_and_typed() -> None:
    profile = _load(PROFILE_PATH)
    predicates = profile["predicate_vocabulary"]

    assert predicates["natural_language_predicate"] is False
    assert predicates["evaluation_results"] == ["satisfied", "unsatisfied", "indeterminate"]
    assert set(predicates["evaluation_modes"]) == {"single_sample", "polling", "event_driven"}
    for name, spec in predicates["properties"].items():
        assert spec["operators"]
        assert spec["value_type"] in {"boolean", "string", "number", "integer"}, name
        assert isinstance(spec["negative_requires_complete_coverage"], bool)


def test_verb_contracts_fix_operation_retry_atomicity_and_versions() -> None:
    profile = _load(PROFILE_PATH)
    verbs = profile["verb_contracts"]
    assert set(verbs) == {
        "observe",
        "hydrate",
        "diff",
        "wait",
        "assert",
        "click",
        "fill",
        "select",
        "navigate",
        "scroll",
    }
    assert all(v["operation_class"] in {"observe", "probe", "mutate"} for v in verbs.values())
    assert all(v["idempotency_class"] in {"read_only", "idempotent", "non_idempotent", "unknown"} for v in verbs.values())
    assert all(v["atomicity_class"] in {"atomic", "single_dispatch", "best_effort", "unknown"} for v in verbs.values())
    for name in {"click", "fill", "select", "navigate", "scroll"}:
        assert verbs[name]["operation_class"] == "mutate"
        assert verbs[name]["version_precondition"] == "required"
        assert verbs[name]["silent_retry_allowed"] is False
    assert verbs["click"]["idempotency_class"] == "unknown"
    assert verbs["navigate"]["idempotency_class"] == "unknown"


def test_all_model_facing_object_schemas_are_recursively_closed() -> None:
    schema = _load(SCHEMA_PATH)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "https://llm-first-loop.local/schema/smc-browser-phase1-v0.1.json"

    visited: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, node.get("title")
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.removeprefix("#/$defs/")
                if name not in visited:
                    visited.add(name)
                    walk(schema["$defs"][name])
            for key, child in node.items():
                if key != "$ref":
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(schema)
    assert {
        "semantic_object",
        "world_snapshot",
        "semantic_diff",
        "predicate",
        "semantic_action",
        "action_receipt",
    } <= set(schema["$defs"])


def test_schema_refs_args_schemas_and_property_names_are_mechanically_safe() -> None:
    profile = _load(PROFILE_PATH)
    schema = _load(SCHEMA_PATH)
    defs = schema["$defs"]
    refs: set[str] = set()
    property_names: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                refs.add(ref)
            properties = node.get("properties")
            if isinstance(properties, dict):
                property_names.update(str(key) for key in properties)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(schema)
    for ref in refs:
        assert ref.startswith("#/$defs/")
        assert ref.removeprefix("#/$defs/") in defs

    for contract in profile["verb_contracts"].values():
        assert contract["args_schema"] in defs

    forbidden_property_names = {
        "recommended_action",
        "best_candidate",
        "priority",
        "completion",
        "task_relevance",
        "recovery_sequence",
        "css_selector",
        "xpath",
        "x",
        "y",
        "cdp_node_id",
        "ax_index",
        "native_handle",
        "hint",
    }
    assert property_names.isdisjoint(forbidden_property_names)


def test_canonical_examples_validate_against_closed_schema() -> None:
    profile = _load(PROFILE_PATH)
    schema = _load(SCHEMA_PATH)
    for schema_name, example in profile["examples"].items():
        _assert_valid(example, schema_name, schema)


@pytest.mark.parametrize(
    ("schema_name", "field", "value"),
    [
        ("semantic_object", "recommended_action", "click"),
        ("semantic_object", "priority", 1),
        ("semantic_action", "css_selector", "#submit"),
        ("semantic_action", "xpath", "//button"),
        ("semantic_action", "x", 10),
        ("action_receipt", "next_best_candidate", "el_other"),
        ("action_receipt", "completion", True),
    ],
)
def test_closed_schema_rejects_strategy_and_ephemeral_locator_fields(
    schema_name: str, field: str, value: Any
) -> None:
    profile = _load(PROFILE_PATH)
    schema = _load(SCHEMA_PATH)
    bad = copy.deepcopy(profile["examples"][schema_name])
    bad[field] = value
    errors = _validate(bad, {"$ref": f"#/$defs/{schema_name}"}, schema)
    assert errors, (schema_name, field)


def test_closed_schema_rejects_nested_locator_and_freeform_hint() -> None:
    profile = _load(PROFILE_PATH)
    schema = _load(SCHEMA_PATH)

    bad_action = copy.deepcopy(profile["examples"]["semantic_action"])
    bad_action["args"] = {"css_selector": "#submit"}
    assert _validate(bad_action, {"$ref": "#/$defs/semantic_action"}, schema)

    bad_object = copy.deepcopy(profile["examples"]["semantic_object"])
    bad_object["attributes"]["hint"] = "主按钮"
    assert _validate(bad_object, {"$ref": "#/$defs/semantic_object"}, schema)


def test_action_examples_match_machine_verb_contracts() -> None:
    profile = _load(PROFILE_PATH)
    schema = _load(SCHEMA_PATH)
    action = profile["examples"]["semantic_action"]
    assert _action_profile_errors(action, profile, schema) == []


def test_action_profile_rejects_verb_arg_and_classification_mismatch() -> None:
    profile = _load(PROFILE_PATH)
    schema = _load(SCHEMA_PATH)

    wrong_args = copy.deepcopy(profile["examples"]["semantic_action"])
    wrong_args["args"] = {"url": "https://example.invalid/"}
    assert _action_profile_errors(wrong_args, profile, schema)

    wrong_class = copy.deepcopy(profile["examples"]["semantic_action"])
    wrong_class["idempotency_class"] = "idempotent"
    assert _action_profile_errors(wrong_class, profile, schema)

    missing_version = copy.deepcopy(profile["examples"]["semantic_action"])
    missing_version["expected_version"] = None
    assert _action_profile_errors(missing_version, profile, schema)


def test_predicate_profile_rejects_operator_type_and_enum_mismatch() -> None:
    profile = _load(PROFILE_PATH)
    predicate = profile["examples"]["predicate"]
    assert _predicate_profile_errors(predicate, profile) == []

    wrong_operator = copy.deepcopy(predicate)
    wrong_operator["operator"] = "contains"
    assert _predicate_profile_errors(wrong_operator, profile)

    wrong_type = copy.deepcopy(predicate)
    wrong_type["value"] = "true"
    assert _predicate_profile_errors(wrong_type, profile)

    ready = copy.deepcopy(predicate)
    ready.update(
        {
            "target": "br:page:p1/document:d1",
            "property": "document_ready_state",
            "operator": "eq",
            "value": "done",
        }
    )
    assert _predicate_profile_errors(ready, profile)


def test_receipt_and_grounding_contract_preserve_mechanical_honesty() -> None:
    profile = _load(PROFILE_PATH)
    receipt = profile["receipt_contract"]
    grounding = profile["grounding_contract"]

    assert profile["retry_contract"] == {
        "automatic_protocol_retry": "disabled_v0.1",
        "polling_samples_are_retries": False,
        "model_explicit_repeat_uses_new_action_id": True,
        "future_retry_requires_auditable_mechanical_idempotency_basis": True,
    }
    assert receipt["append_only"] is True
    assert receipt["receipt_seq"] == "strictly_monotonic_per_action_id"
    assert receipt["terminal_overwrites_prior_receipt"] is False
    assert receipt["status_is_task_completion"] is False
    assert receipt["silent_recovery_sequence"] is False
    assert set(profile["boundary_event_vocabulary"]) >= {
        "new_page",
        "new_window",
        "download_started",
        "dialog_opened",
        "permission_prompt",
        "scope_changed",
    }
    assert grounding["silent_similar_state_refetch"] is False
    assert set(grounding["availability_states"]) == {
        "available",
        "expired",
        "unavailable",
        "unauthorized",
    }


def test_bspec_does_not_claim_browser_implementation() -> None:
    profile = _load(PROFILE_PATH)
    assert profile["implementation_status"] == "spec_only_not_implemented"
    assert profile["non_claims"] == [
        "browser_adapter_implemented",
        "browser_implementation_conformant",
        "live_dom_ax_qualified",
        "vision_actionability_qualified",
        "native_ui_qualified",
    ]

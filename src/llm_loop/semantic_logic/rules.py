"""Closed P2 Core Rule Engine validation shell.

This first TDD slice intentionally performs **no semantic rule evaluation**.  It only
validates the frozen P2 RulePack and one asserted-fact input envelope before a later
group-specific evaluator is allowed to run.  A valid request therefore returns
``status=unimplemented`` with an empty derived set.

The module has no Browser/Runtime imports, performs no I/O, and cannot capture, hydrate,
reserve, dispatch, retry, or infer task completion.  It is shadow qualification code
until a separately qualified later phase changes that authority boundary.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final, Literal

type JsonScalar = None | bool | int | float | str

_RESULT_SCHEMA: Final = "smc.rule_engine_result.v0.1"
_PACK_SCHEMA: Final = "smc.rulepack.v0.1"
_PACK_ID: Final = "smc.browser.p2-core.v0.1"
_PACK_VERSION: Final = "0.1"
_PACK_PHASE: Final = "P2-design"
_ENGINE_PROFILE_SCHEMA: Final = "smc.rule_engine_profile.v0.1"
_INPUT_SCHEMA: Final = "smc.rule_engine_input.v0.1"
_FACT_SCHEMA: Final = "smc.semantic_fact.v0.1"

_GROUP_ORDER: Final = (
    "G1_grounding",
    "G2_scope",
    "G3_completeness_conflict",
    "G4_predicate",
    "G5_version_receipt",
)
_ALLOWED_AUTHORITY_CLASSES: Final = frozenset(
    {"mechanical_derivation", "execution_precondition_fact"}
)
_ALLOWED_INPUT_PROVENANCE: Final = frozenset(
    {"observed", "runtime_authority", "model_asserted"}
)
_EVALUATOR_OPS: Final = frozenset(
    {
        "grounding_exact_binding",
        "action_fixed_contract",
        "scope_descendant_closure",
        "scope_target_relation",
        "canonicalize_source_conflict",
        "derive_coverage_status",
        "separate_completeness",
        "identity_ambiguity_no_fusion",
        "predicate_bind_selected_condition",
        "predicate_evaluate",
        "version_assess",
        "receipt_sequence_validate",
        "receipt_dispatch_invariants",
    }
)
_PREDICATE_SPECS: Final = {
    "exists": {"operators": ("eq",), "value_type": "boolean", "target_kind": "semantic_object"},
    "enabled": {"operators": ("eq",), "value_type": "boolean", "target_kind": "semantic_object"},
    "visible": {"operators": ("eq",), "value_type": "boolean", "target_kind": "semantic_object"},
    "checked": {"operators": ("eq",), "value_type": "boolean", "target_kind": "semantic_object"},
    "selected": {"operators": ("eq",), "value_type": "boolean", "target_kind": "semantic_object"},
    "expanded": {"operators": ("eq",), "value_type": "boolean", "target_kind": "semantic_object"},
    "focused": {"operators": ("eq",), "value_type": "boolean", "target_kind": "semantic_object"},
    "editable": {"operators": ("eq",), "value_type": "boolean", "target_kind": "semantic_object"},
    "url": {
        "operators": ("eq", "contains", "prefix", "suffix"),
        "value_type": "string",
        "target_kind": "scope",
    },
    "name": {
        "operators": ("eq", "contains", "prefix", "suffix"),
        "value_type": "string",
        "target_kind": "semantic_object",
    },
    "value_text": {
        "operators": ("eq", "contains", "prefix", "suffix"),
        "value_type": "string",
        "target_kind": "semantic_object",
    },
    "document_ready_state": {
        "operators": ("eq",),
        "value_type": "string",
        "value_enum": ("loading", "interactive", "complete"),
        "target_kind": "scope",
    },
    "object_count": {
        "operators": ("eq", "ge", "le"),
        "value_type": "integer",
        "target_kind": "scope",
    },
}
_EVALUATOR_REQUIRED_INPUTS: Final = {
    "predicate_bind_selected_condition": frozenset(
        {
            "model_condition.scope_ref",
            "model_condition.target_ref",
            "model_condition.property",
            "model_condition.operator",
            "model_condition.value",
        }
    ),
    "predicate_evaluate": frozenset(
        {
            "predicate.schema",
            "predicate.domain",
            "predicate.scope_ref",
            "predicate.target",
            "predicate.property",
            "predicate.operator",
            "predicate.value",
            "scope.relation",
        }
    ),
}
_FORBIDDEN_OUTPUTS: Final = frozenset(
    {
        "important",
        "priority",
        "recommended",
        "best",
        "preferred",
        "task_relevant",
        "should_click",
        "should_fill",
        "should_navigate",
        "next_action",
        "recovery_sequence",
        "likely_complete",
        "task_complete",
        "goal_complete",
        "user_intent_is",
    }
)
_FROZEN_BOUNDS: Final = {
    "max_rules": 64,
    "max_asserted_facts": 4096,
    "max_derived_facts": 4096,
    "max_derivations": 4096,
    "max_contexts": 256,
    "max_rule_dependencies": 16,
    "max_scope_nodes": 1024,
    "max_scope_depth": 32,
    "max_output_facts_per_rule_context": 64,
    "max_input_fact_refs_per_derivation": 64,
    "max_engine_wall_ms_qualification": 5000,
    "rule_firings_per_context": 1,
}

_PACK_KEYS: Final = frozenset(
    {
        "schema",
        "rulepack_id",
        "rulepack_version",
        "domain",
        "phase",
        "status",
        "authority",
        "production_consumed",
        "baseline",
        "engine_profile",
        "group_order",
        "rules",
        "hash_contract",
        "source_refs",
        "rulepack_hash",
    }
)
_RULE_KEYS: Final = frozenset(
    {
        "kind",
        "schema",
        "rule_id",
        "rule_version",
        "rulepack_id",
        "domain",
        "group",
        "evaluator_op",
        "authority_class",
        "input_predicates",
        "output_predicates",
        "closed_world_requirements",
        "dependencies",
        "source_refs",
        "fixture_refs",
        "status",
        "production_consumed",
        "rule_hash",
    }
)
_INPUT_KEYS: Final = frozenset(
    {"schema", "authority", "production_consumed", "domain", "context_ref", "facts"}
)
_FACT_KEYS: Final = frozenset(
    {
        "kind",
        "schema",
        "fact_id",
        "domain",
        "subject",
        "predicate",
        "value",
        "value_type",
        "truth_state",
        "context",
        "observation_completeness",
        "projection_complete",
        "provenance",
    }
)
_CONTEXT_KEYS: Final = frozenset(
    {"domain", "scope_ref", "observed_version", "snapshot_id", "sensor_contract_ref"}
)
_PROVENANCE_KEYS: Final = frozenset(
    {
        "kind",
        "source",
        "grounding_ref",
        "observed_version",
        "derivation_ref",
        "rule_ref",
        "input_fact_refs",
    }
)


class _ValidationError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise _ValidationError("non_canonical_json_value") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _string_list(value: Any, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(_nonempty_string(item) for item in value):
        raise _ValidationError("string_list_invalid")
    if nonempty and not value:
        raise _ValidationError("string_list_empty")
    if len(value) != len(set(value)):
        raise _ValidationError("string_list_duplicate")
    return value


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise _ValidationError("non_finite_number")
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        _canonical_bytes(value)
        return "array"
    if isinstance(value, dict):
        _canonical_bytes(value)
        return "object"
    raise _ValidationError("unsupported_fact_value")


def _result(
    *,
    status: Literal["rejected", "unimplemented", "complete"],
    reason: str,
    pack: dict[str, Any] | None,
    input_document: dict[str, Any] | None,
    derived_facts: list[dict[str, Any]] | None = None,
    derivations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema": _RESULT_SCHEMA,
        "status": status,
        "reason": reason,
        "authority": "shadow_only",
        "production_consumed": False,
        "rulepack_id": pack.get("rulepack_id") if isinstance(pack, dict) else None,
        "rulepack_hash": pack.get("rulepack_hash") if isinstance(pack, dict) else None,
        "input_fingerprint": (
            _sha256(input_document) if isinstance(input_document, dict) else None
        ),
        "derived_facts": list(derived_facts or []),
        "derivations": list(derivations or []),
    }


def _validate_profile(profile: Any) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise _ValidationError("engine_profile_invalid")
    expected_scalars = {
        "schema": _ENGINE_PROFILE_SCHEMA,
        "mode": "shadow_qualification_only",
        "evaluation_strategy": "single_topological_pass",
        "dynamic_rule_loading": False,
        "arbitrary_code_execution": False,
        "recursion": False,
        "cycles": "reject",
        "unknown_dependency": "reject",
        "input_mutation": False,
        "runtime_authority_minting": False,
        "task_completion_authority": False,
    }
    for key, expected in expected_scalars.items():
        if profile.get(key) != expected:
            raise _ValidationError(f"engine_profile_mismatch:{key}")
    if set(profile.get("allowed_authority_classes") or []) != _ALLOWED_AUTHORITY_CLASSES:
        raise _ValidationError("allowed_authority_classes_mismatch")
    if set(profile.get("forbidden_authority_classes") or []) != {
        "runtime_authority",
        "model_semantic",
        "candidate_only",
    }:
        raise _ValidationError("forbidden_authority_classes_mismatch")
    if set(profile.get("forbidden_output_predicates") or []) != _FORBIDDEN_OUTPUTS:
        raise _ValidationError("forbidden_output_predicates_mismatch")
    if set(profile.get("evaluator_ops") or []) != _EVALUATOR_OPS:
        raise _ValidationError("evaluator_ops_profile_mismatch")
    if profile.get("bounds") != _FROZEN_BOUNDS:
        raise _ValidationError("bounds_profile_mismatch")
    negative = profile.get("negative_reasoning")
    if not isinstance(negative, dict) or negative != {
        "open_world_default": True,
        "negation_as_failure": False,
        "missing_fact_means_false": False,
        "negative_conclusion_requires_explicit_membership_fact": True,
        "closed_world_requirements_must_be_explicit": True,
    }:
        raise _ValidationError("negative_reasoning_profile_mismatch")
    return profile


def _validate_rule(rule: Any, *, pack_id: str, domain: str) -> dict[str, Any]:
    if not isinstance(rule, dict) or set(rule) != _RULE_KEYS:
        raise _ValidationError("rule_fields_mismatch")
    if rule.get("kind") != "rule" or rule.get("schema") != "smc.semantic_rule.v0.1":
        raise _ValidationError("rule_schema_mismatch")
    if not _nonempty_string(rule.get("rule_id")) or rule.get("rule_version") != "0.1":
        raise _ValidationError("rule_identity_mismatch")
    if rule.get("rulepack_id") != pack_id or rule.get("domain") != domain:
        raise _ValidationError("rule_scope_mismatch")
    if rule.get("group") not in _GROUP_ORDER:
        raise _ValidationError("rule_group_invalid")
    if rule.get("authority_class") not in _ALLOWED_AUTHORITY_CLASSES:
        raise _ValidationError("rule_authority_forbidden")
    if rule.get("evaluator_op") not in _EVALUATOR_OPS:
        raise _ValidationError("evaluator_op_forbidden")
    _string_list(rule.get("input_predicates"))
    outputs = _string_list(rule.get("output_predicates"), nonempty=True)
    _string_list(rule.get("closed_world_requirements"))
    dependencies = _string_list(rule.get("dependencies"))
    if len(dependencies) > _FROZEN_BOUNDS["max_rule_dependencies"]:
        raise _ValidationError("rule_dependency_cap_exceeded")
    _string_list(rule.get("source_refs"), nonempty=True)
    _string_list(rule.get("fixture_refs"))
    if rule.get("status") != "candidate" or rule.get("production_consumed") is not False:
        raise _ValidationError("rule_status_or_authority_mismatch")
    for predicate in outputs:
        if predicate in _FORBIDDEN_OUTPUTS:
            raise _ValidationError("forbidden_semantic_output")
        if predicate.startswith("runtime."):
            raise _ValidationError("runtime_authority_output_forbidden")
    claimed_hash = rule.get("rule_hash")
    if not isinstance(claimed_hash, str) or len(claimed_hash) != 64:
        raise _ValidationError("rule_hash_invalid")
    body = dict(rule)
    body.pop("rule_hash")
    if _sha256(body) != claimed_hash:
        raise _ValidationError("rule_hash_mismatch")
    return rule


def _validate_dag(rules: list[dict[str, Any]]) -> None:
    by_id = {str(rule["rule_id"]): rule for rule in rules}
    if len(by_id) != len(rules):
        raise _ValidationError("duplicate_rule_id")
    for rule in rules:
        for dependency in rule["dependencies"]:
            if dependency not in by_id:
                raise _ValidationError("unknown_rule_dependency")

    visited: set[str] = set()
    active: set[str] = set()

    def visit(rule_id: str) -> None:
        if rule_id in active:
            raise _ValidationError("rule_dependency_cycle")
        if rule_id in visited:
            return
        active.add(rule_id)
        for dependency in by_id[rule_id]["dependencies"]:
            visit(dependency)
        active.remove(rule_id)
        visited.add(rule_id)

    for rule_id in by_id:
        visit(rule_id)


def _validate_pack(pack: Any) -> tuple[dict[str, Any], set[str]]:
    if not isinstance(pack, dict) or set(pack) != _PACK_KEYS:
        raise _ValidationError("rulepack_fields_mismatch")
    if pack.get("schema") != _PACK_SCHEMA:
        raise _ValidationError("rulepack_schema_mismatch")
    if pack.get("rulepack_id") != _PACK_ID or pack.get("rulepack_version") != _PACK_VERSION:
        raise _ValidationError("rulepack_identity_mismatch")
    if pack.get("domain") != "browser" or pack.get("phase") != _PACK_PHASE:
        raise _ValidationError("rulepack_domain_or_phase_mismatch")
    if pack.get("status") != "candidate" or pack.get("authority") != "shadow_only":
        raise _ValidationError("rulepack_status_or_authority_mismatch")
    if pack.get("production_consumed") is not False:
        raise _ValidationError("production_consumed_forbidden")
    if tuple(pack.get("group_order") or ()) != _GROUP_ORDER:
        raise _ValidationError("group_order_mismatch")
    _validate_profile(pack.get("engine_profile"))
    rules = pack.get("rules")
    if not isinstance(rules, list) or not rules:
        raise _ValidationError("rules_missing")
    if len(rules) > _FROZEN_BOUNDS["max_rules"]:
        raise _ValidationError("max_rules_exceeded")
    validated = [
        _validate_rule(rule, pack_id=_PACK_ID, domain="browser") for rule in rules
    ]
    _validate_dag(validated)
    claimed_hash = pack.get("rulepack_hash")
    if not isinstance(claimed_hash, str) or len(claimed_hash) != 64:
        raise _ValidationError("rulepack_hash_invalid")
    body = dict(pack)
    body.pop("rulepack_hash")
    if _sha256(body) != claimed_hash:
        raise _ValidationError("rulepack_hash_mismatch")
    derived_predicates = {
        predicate for rule in validated for predicate in rule["output_predicates"]
    }
    return pack, derived_predicates


def _validate_context(context: Any, *, domain: str) -> dict[str, Any]:
    if not isinstance(context, dict) or set(context) != _CONTEXT_KEYS:
        raise _ValidationError("fact_context_fields_mismatch")
    if context.get("domain") != domain:
        raise _ValidationError("fact_context_domain_mismatch")
    for key in ("scope_ref", "observed_version", "snapshot_id", "sensor_contract_ref"):
        value = context.get(key)
        if value is not None and not _nonempty_string(value):
            raise _ValidationError(f"fact_context_invalid:{key}")
    return context


def _validate_provenance(provenance: Any) -> dict[str, Any]:
    if not isinstance(provenance, dict) or set(provenance) != _PROVENANCE_KEYS:
        raise _ValidationError("fact_provenance_fields_mismatch")
    kind = provenance.get("kind")
    if kind not in _ALLOWED_INPUT_PROVENANCE:
        raise _ValidationError("input_provenance_kind_forbidden")
    source = provenance.get("source")
    if not _nonempty_string(source):
        raise _ValidationError("input_provenance_source_missing")
    if provenance.get("derivation_ref") is not None or provenance.get("rule_ref") is not None:
        raise _ValidationError("derived_provenance_smuggled_as_input")
    if provenance.get("input_fact_refs") != []:
        raise _ValidationError("input_fact_refs_smuggled_as_input")
    if kind == "observed":
        if not _nonempty_string(provenance.get("grounding_ref")):
            raise _ValidationError("observed_grounding_ref_missing")
        if not _nonempty_string(provenance.get("observed_version")):
            raise _ValidationError("observed_version_missing")
    return provenance


def _validate_fact(
    fact: Any,
    *,
    domain: str,
    derived_predicates: set[str],
) -> tuple[str, bytes]:
    if not isinstance(fact, dict) or set(fact) != _FACT_KEYS:
        raise _ValidationError("fact_fields_mismatch")
    if fact.get("kind") != "fact" or fact.get("schema") != _FACT_SCHEMA:
        raise _ValidationError("fact_schema_mismatch")
    fact_id = fact.get("fact_id")
    if not _nonempty_string(fact_id):
        raise _ValidationError("fact_id_missing")
    if fact.get("domain") != domain:
        raise _ValidationError("fact_domain_mismatch")
    if not _nonempty_string(fact.get("subject")) or not _nonempty_string(fact.get("predicate")):
        raise _ValidationError("fact_subject_or_predicate_missing")
    predicate = str(fact["predicate"])
    if predicate in derived_predicates:
        raise _ValidationError("derived_output_smuggled_as_asserted_input")
    if fact.get("truth_state") != "asserted":
        raise _ValidationError("input_truth_state_must_be_asserted")
    if _value_type(fact.get("value")) != fact.get("value_type"):
        raise _ValidationError("fact_value_type_mismatch")
    context = _validate_context(fact.get("context"), domain=domain)
    _validate_provenance(fact.get("provenance"))
    completeness = fact.get("observation_completeness")
    if (
        not isinstance(completeness, dict)
        or set(completeness) != {"complete", "reasons"}
        or not isinstance(completeness.get("complete"), bool)
        or not isinstance(completeness.get("reasons"), list)
        or not all(isinstance(item, str) for item in completeness["reasons"])
    ):
        raise _ValidationError("observation_completeness_invalid")
    projection = fact.get("projection_complete")
    if projection is not None and not isinstance(projection, bool):
        raise _ValidationError("projection_complete_invalid")

    # This is low-level input-wire validation, not scope reasoning.  A parent reference
    # cannot be a JSON object; cycles/depth remain G2 semantic REDs for later slices.
    if (
        predicate == "scope.node.parent_scope_ref"
        and fact.get("value") is not None
        and not _nonempty_string(fact.get("value"))
    ):
        raise _ValidationError("scope_parent_ref_wire_type_invalid")
    if predicate == "scope.node.scope_ref" and not _nonempty_string(fact.get("value")):
        raise _ValidationError("scope_ref_wire_type_invalid")

    return str(fact_id), _canonical_bytes(context)


def _validate_input(
    input_document: Any,
    *,
    pack: dict[str, Any],
    derived_predicates: set[str],
) -> dict[str, Any]:
    if not isinstance(input_document, dict) or set(input_document) != _INPUT_KEYS:
        raise _ValidationError("input_fields_mismatch")
    if input_document.get("schema") != _INPUT_SCHEMA:
        raise _ValidationError("input_schema_mismatch")
    if input_document.get("authority") != "shadow_only":
        raise _ValidationError("input_authority_mismatch")
    if input_document.get("production_consumed") is not False:
        raise _ValidationError("input_production_consumed_forbidden")
    domain = input_document.get("domain")
    if domain != pack.get("domain"):
        raise _ValidationError("input_domain_mismatch")
    if not _nonempty_string(input_document.get("context_ref")):
        raise _ValidationError("input_context_ref_missing")
    facts = input_document.get("facts")
    if not isinstance(facts, list):
        raise _ValidationError("input_facts_invalid")
    if len(facts) > _FROZEN_BOUNDS["max_asserted_facts"]:
        raise _ValidationError("max_asserted_facts_exceeded")
    ids: set[str] = set()
    contexts: set[bytes] = set()
    for fact in facts:
        fact_id, context_wire = _validate_fact(
            fact,
            domain=str(domain),
            derived_predicates=derived_predicates,
        )
        if fact_id in ids:
            raise _ValidationError("duplicate_fact_id")
        ids.add(fact_id)
        contexts.add(context_wire)
    if len(contexts) > _FROZEN_BOUNDS["max_contexts"]:
        raise _ValidationError("max_contexts_exceeded")
    return input_document


def _index_facts(facts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        predicate = str(fact["predicate"])
        index.setdefault(predicate, []).append(fact)
    for values in index.values():
        values.sort(key=lambda fact: str(fact["fact_id"]))
    return index


def _collect_rule_inputs(
    rule: dict[str, Any],
    index: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]] | None:
    evaluator_op = str(rule["evaluator_op"])
    required = _EVALUATOR_REQUIRED_INPUTS.get(evaluator_op)
    if required is not None:
        if not all(index.get(predicate) for predicate in required):
            return None
        collected: list[dict[str, Any]] = []
        for predicate in rule["input_predicates"]:
            collected.extend(index.get(str(predicate)) or [])
        return collected
    collected: list[dict[str, Any]] = []
    for predicate in rule["input_predicates"]:
        facts = index.get(str(predicate))
        if not facts:
            return None
        collected.extend(facts)
    return collected


def _single_value(
    index: dict[str, list[dict[str, Any]]], predicate: str
) -> tuple[bool, Any]:
    facts = index.get(predicate) or []
    if len(facts) != 1:
        return False, None
    return True, facts[0].get("value")


def _first_context(input_facts: list[dict[str, Any]]) -> dict[str, Any]:
    for fact in input_facts:
        raw = fact.get("context")
        if isinstance(raw, dict):
            return {
                "domain": raw.get("domain"),
                "scope_ref": raw.get("scope_ref"),
                "observed_version": raw.get("observed_version"),
                "snapshot_id": raw.get("snapshot_id"),
                "sensor_contract_ref": raw.get("sensor_contract_ref"),
            }
    return {
        "domain": "browser",
        "scope_ref": None,
        "observed_version": None,
        "snapshot_id": None,
        "sensor_contract_ref": None,
    }


def _derived_context(
    input_facts: list[dict[str, Any]], outputs: dict[str, Any]
) -> dict[str, Any]:
    context = _first_context(input_facts)
    scope = outputs.get("binding.scope_ref", outputs.get("action.scope_ref"))
    version = outputs.get(
        "binding.observed_version", outputs.get("action.expected_version")
    )
    if _nonempty_string(scope):
        context["scope_ref"] = scope
    if _nonempty_string(version):
        context["observed_version"] = version
        context["snapshot_id"] = version
    return context


def _derived_completeness(input_facts: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: set[str] = set()
    complete = True
    for fact in input_facts:
        coverage = fact.get("observation_completeness")
        if not isinstance(coverage, dict):
            continue
        complete = complete and coverage.get("complete") is True
        raw_reasons = coverage.get("reasons")
        if isinstance(raw_reasons, list):
            reasons.update(str(reason) for reason in raw_reasons)
    return {"complete": complete, "reasons": sorted(reasons)}


def _derived_projection_complete(input_facts: list[dict[str, Any]]) -> bool | None:
    observed = [fact.get("projection_complete") for fact in input_facts]
    if any(value is False for value in observed):
        return False
    if observed and all(value is True for value in observed):
        return True
    return None


def _make_derivation_bundle(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    outputs: dict[str, Any],
    result: Literal["derived", "indeterminate", "conflict", "not_applicable", "rejected"],
    reason: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output_order = [
        predicate for predicate in rule["output_predicates"] if predicate in outputs
    ]
    if not output_order:
        raise _ValidationError("evaluator_returned_no_declared_outputs")
    if len(output_order) > _FROZEN_BOUNDS["max_output_facts_per_rule_context"]:
        raise _ValidationError("max_output_facts_per_rule_context_exceeded")
    input_refs = sorted({str(fact["fact_id"]) for fact in input_facts})
    if len(input_refs) > _FROZEN_BOUNDS["max_input_fact_refs_per_derivation"]:
        raise _ValidationError("max_input_fact_refs_per_derivation_exceeded")
    context_ref = str(input_document["context_ref"])
    derivation_seed = {
        "rule_ref": str(rule["rule_id"]),
        "rule_hash": str(rule["rule_hash"]),
        "input_fact_refs": input_refs,
        "context_refs": [context_ref],
        "outputs": [[predicate, outputs[predicate]] for predicate in output_order],
        "result": result,
        "reason": reason,
    }
    derivation_id = f"deriv-{_sha256(derivation_seed)[:24]}"
    context = _derived_context(input_facts, outputs)
    completeness = _derived_completeness(input_facts)
    projection_complete = _derived_projection_complete(input_facts)
    rule_ref = f"{rule['rule_id']}@{rule['rule_version']}"

    derived: list[dict[str, Any]] = []
    for predicate in output_order:
        value = outputs[predicate]
        fact_seed = {
            "derivation_id": derivation_id,
            "predicate": predicate,
            "value": value,
            "subject": f"rule:{rule['rule_id']}",
        }
        fact_id = f"dfact-{_sha256(fact_seed)[:24]}"
        derived.append(
            {
                "kind": "fact",
                "schema": _FACT_SCHEMA,
                "fact_id": fact_id,
                "domain": str(rule["domain"]),
                "subject": f"rule:{rule['rule_id']}",
                "predicate": predicate,
                "value": value,
                "value_type": _value_type(value),
                "truth_state": "asserted",
                "context": dict(context),
                "observation_completeness": dict(completeness),
                "projection_complete": projection_complete,
                "provenance": {
                    "kind": "mechanically_derived",
                    "source": f"rule:{rule_ref}",
                    "grounding_ref": None,
                    "observed_version": context.get("observed_version"),
                    "derivation_ref": derivation_id,
                    "rule_ref": rule_ref,
                    "input_fact_refs": input_refs,
                },
            }
        )
    derivation = {
        "kind": "derivation",
        "schema": "smc.derivation_record.v0.1",
        "derivation_id": derivation_id,
        "rule_ref": rule_ref,
        "rule_hash": str(rule["rule_hash"]),
        "input_fact_refs": input_refs,
        "output_fact_refs": [str(fact["fact_id"]) for fact in derived],
        "context_refs": [context_ref],
        "result": result,
        "reason": reason,
    }
    return derived, derivation


def _topological_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    remaining = list(rules)
    ordered: list[dict[str, Any]] = []
    complete: set[str] = set()
    while remaining:
        next_index = next(
            (
                index
                for index, rule in enumerate(remaining)
                if set(rule["dependencies"]) <= complete
            ),
            None,
        )
        if next_index is None:
            raise _ValidationError("rule_dependency_topology_unresolved")
        rule = remaining.pop(next_index)
        ordered.append(rule)
        complete.add(str(rule["rule_id"]))
    return ordered


def _grounding_indeterminate(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    reason: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return _make_derivation_bundle(
        rule=rule,
        input_document=input_document,
        input_facts=input_facts,
        outputs={"binding.status": "indeterminate", "binding.reason": reason},
        result="indeterminate",
        reason=reason,
    )


def _evaluate_grounding_exact_binding(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    index: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required = {
        predicate: _single_value(index, predicate)
        for predicate in rule["input_predicates"]
    }
    if not all(ok for ok, _ in required.values()):
        return _grounding_indeterminate(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            reason="grounding_input_ambiguous",
        )
    values = {predicate: value for predicate, (_, value) in required.items()}
    target_ref = values["request.target_ref"]
    verb = values["request.verb"]
    availability = values["grounding.availability"]
    grounding_ref = values["grounding.ref"]
    grounding_kind = values["grounding.kind"]
    projection_ref = values["grounding.projection_ref"]
    target_id = values["grounding.target_id"]
    scope_ref = values["grounding.scope_ref"]
    observed_version = values["grounding.observed_version"]

    if availability != "available":
        return _grounding_indeterminate(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            reason=f"target_ref_{availability}",
        )
    if not _nonempty_string(target_ref) or target_ref != grounding_ref or target_ref != projection_ref:
        return _grounding_indeterminate(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            reason="target_ref_identity_mismatch",
        )
    object_verbs = {"click", "fill", "select", "scroll"}
    if verb in object_verbs:
        expected_kind = "object"
        version_scope = "object"
    elif verb == "navigate":
        expected_kind = "resource"
        version_scope = "resource"
    else:
        return _grounding_indeterminate(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            reason="verb_not_in_browser_mutation_profile",
        )
    if grounding_kind != expected_kind:
        return _grounding_indeterminate(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            reason="target_ref_projection_mismatch",
        )
    if not all(_nonempty_string(value) for value in (target_id, scope_ref, observed_version)):
        return _grounding_indeterminate(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            reason="target_ref_incomplete",
        )
    if version_scope == "resource" and target_id != scope_ref:
        return _grounding_indeterminate(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            reason="resource_target_scope_mismatch",
        )
    return _make_derivation_bundle(
        rule=rule,
        input_document=input_document,
        input_facts=input_facts,
        outputs={
            "binding.status": "bound",
            "binding.reason": None,
            "binding.target_id": target_id,
            "binding.scope_ref": scope_ref,
            "binding.observed_version": observed_version,
            "binding.version_scope": version_scope,
        },
        result="derived",
        reason=None,
    )


def _semantic_action_id(*, verb: str, target_ref: str, args: dict[str, Any]) -> str:
    wire = json.dumps(
        {"verb": verb, "target_ref": target_ref, "args": args},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sact-{hashlib.sha256(wire).hexdigest()[:24]}"


def _scope_graph(
    input_facts: list[dict[str, Any]],
) -> tuple[dict[str, str | None], dict[str, str]]:
    by_subject: dict[str, dict[str, list[Any]]] = {}
    for fact in input_facts:
        predicate = str(fact["predicate"])
        if predicate not in {
            "scope.node.scope_ref",
            "scope.node.parent_scope_ref",
            "scope.node.kind",
        }:
            continue
        subject = str(fact["subject"])
        by_subject.setdefault(subject, {}).setdefault(predicate, []).append(fact.get("value"))
    if not by_subject:
        raise _ValidationError("scope_graph_missing")

    parents: dict[str, str | None] = {}
    kinds: dict[str, str] = {}
    for fields in by_subject.values():
        scope_values = fields.get("scope.node.scope_ref") or []
        parent_values = fields.get("scope.node.parent_scope_ref") or []
        kind_values = fields.get("scope.node.kind") or []
        if len(scope_values) != 1 or len(parent_values) != 1 or len(kind_values) != 1:
            raise _ValidationError("scope_node_fields_ambiguous")
        scope_ref = scope_values[0]
        parent_ref = parent_values[0]
        kind = kind_values[0]
        if not _nonempty_string(scope_ref) or not _nonempty_string(kind):
            raise _ValidationError("scope_node_identity_invalid")
        if parent_ref is not None and not _nonempty_string(parent_ref):
            raise _ValidationError("scope_parent_ref_invalid")
        if scope_ref in parents:
            raise _ValidationError("duplicate_scope_ref")
        parents[str(scope_ref)] = str(parent_ref) if parent_ref is not None else None
        kinds[str(scope_ref)] = str(kind)

    if len(parents) > _FROZEN_BOUNDS["max_scope_nodes"]:
        raise _ValidationError("max_scope_nodes_exceeded")
    for start in parents:
        seen = {start}
        current = start
        depth = 0
        while True:
            parent = parents.get(current)
            if parent is None or parent not in parents:
                break
            depth += 1
            if depth > _FROZEN_BOUNDS["max_scope_depth"]:
                raise _ValidationError("max_scope_depth_exceeded")
            if parent in seen:
                raise _ValidationError("scope_graph_cycle")
            seen.add(parent)
            current = parent
    return parents, kinds


def _scope_edges(parents: dict[str, str | None]) -> list[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for child in parents:
        current = child
        while True:
            parent = parents.get(current)
            if parent is None:
                break
            edges.add((child, parent))
            if parent not in parents:
                break
            current = parent
    return sorted(edges)


def _make_scope_closure_bundle(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    edges: list[tuple[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    input_refs = sorted({str(fact["fact_id"]) for fact in input_facts})
    if len(input_refs) > _FROZEN_BOUNDS["max_input_fact_refs_per_derivation"]:
        raise _ValidationError("max_input_fact_refs_per_derivation_exceeded")
    if len(edges) > _FROZEN_BOUNDS["max_output_facts_per_rule_context"]:
        raise _ValidationError("max_output_facts_per_rule_context_exceeded")
    if not edges:
        raise _ValidationError("scope_closure_has_no_positive_edge")
    context_ref = str(input_document["context_ref"])
    derivation_seed = {
        "rule_ref": str(rule["rule_id"]),
        "rule_hash": str(rule["rule_hash"]),
        "input_fact_refs": input_refs,
        "context_refs": [context_ref],
        "edges": edges,
        "result": "derived",
    }
    derivation_id = f"deriv-{_sha256(derivation_seed)[:24]}"
    rule_ref = f"{rule['rule_id']}@{rule['rule_version']}"
    completeness = _derived_completeness(input_facts)
    projection_complete = _derived_projection_complete(input_facts)
    derived: list[dict[str, Any]] = []
    for child, ancestor in edges:
        fact_seed = {
            "derivation_id": derivation_id,
            "predicate": "scope.descendant_of",
            "subject": child,
            "ancestor": ancestor,
        }
        fact_id = f"dfact-{_sha256(fact_seed)[:24]}"
        derived.append(
            {
                "kind": "fact",
                "schema": _FACT_SCHEMA,
                "fact_id": fact_id,
                "domain": str(rule["domain"]),
                "subject": child,
                "predicate": "scope.descendant_of",
                "value": "asserted",
                "value_type": "string",
                "truth_state": "asserted",
                "context": {
                    "domain": str(rule["domain"]),
                    "scope_ref": ancestor,
                    "observed_version": None,
                    "snapshot_id": None,
                    "sensor_contract_ref": None,
                },
                "observation_completeness": dict(completeness),
                "projection_complete": projection_complete,
                "provenance": {
                    "kind": "mechanically_derived",
                    "source": f"rule:{rule_ref}",
                    "grounding_ref": None,
                    "observed_version": None,
                    "derivation_ref": derivation_id,
                    "rule_ref": rule_ref,
                    "input_fact_refs": input_refs,
                },
            }
        )
    derivation = {
        "kind": "derivation",
        "schema": "smc.derivation_record.v0.1",
        "derivation_id": derivation_id,
        "rule_ref": rule_ref,
        "rule_hash": str(rule["rule_hash"]),
        "input_fact_refs": input_refs,
        "output_fact_refs": [str(fact["fact_id"]) for fact in derived],
        "context_refs": [context_ref],
        "result": "derived",
        "reason": None,
    }
    return derived, derivation


def _evaluate_scope_descendant_closure(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    index: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    del index
    parents, _ = _scope_graph(input_facts)
    return _make_scope_closure_bundle(
        rule=rule,
        input_document=input_document,
        input_facts=input_facts,
        edges=_scope_edges(parents),
    )


def _evaluate_scope_target_relation(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    index: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    request_ok, request_scope = _single_value(index, "request.scope_ref")
    target_ok, target_scope = _single_value(index, "target.scope_ref")
    observed = {
        str(fact.get("value"))
        for fact in index.get("scope.node.scope_ref", [])
        if _nonempty_string(fact.get("value"))
    }
    if (
        not request_ok
        or not target_ok
        or not _nonempty_string(request_scope)
        or not _nonempty_string(target_scope)
        or request_scope not in observed
        or target_scope not in observed
    ):
        relation = "indeterminate"
        reason = "scope_unobserved"
        result: Literal["derived", "indeterminate"] = "indeterminate"
    elif request_scope == target_scope:
        relation = "match"
        reason = "exact_scope"
        result = "derived"
    else:
        relation = "mismatch"
        reason = "target_scope_mismatch"
        result = "derived"
    return _make_derivation_bundle(
        rule=rule,
        input_document=input_document,
        input_facts=input_facts,
        outputs={"scope.relation": relation, "scope.reason": reason},
        result=result,
        reason=reason,
    )


def _evaluate_canonicalize_source_conflict(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    index: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    del index
    grouped: dict[str, dict[str, Any]] = {}
    for fact in input_facts:
        predicate = str(fact["predicate"])
        if predicate not in {
            "observation.subject",
            "observation.property",
            "observation.source",
            "observation.value",
            "observation.grounding_ref",
        }:
            continue
        grouped.setdefault(str(fact["subject"]), {})[predicate] = fact.get("value")

    observations: list[dict[str, Any]] = []
    logical_subject: str | None = None
    logical_property: str | None = None
    for fields in grouped.values():
        required = {
            key: fields.get(key)
            for key in (
                "observation.subject",
                "observation.property",
                "observation.source",
                "observation.value",
                "observation.grounding_ref",
            )
        }
        if any(key not in fields for key in required):
            raise _ValidationError("source_observation_fields_incomplete")
        subject = required["observation.subject"]
        property_name = required["observation.property"]
        source = required["observation.source"]
        grounding_ref = required["observation.grounding_ref"]
        if not all(
            _nonempty_string(value)
            for value in (subject, property_name, source, grounding_ref)
        ):
            raise _ValidationError("source_observation_identity_invalid")
        if logical_subject is None:
            logical_subject = str(subject)
            logical_property = str(property_name)
        elif subject != logical_subject or property_name != logical_property:
            raise _ValidationError("source_observation_target_mismatch")
        observations.append(
            {
                "source": str(source),
                "value": required["observation.value"],
                "grounding_ref": str(grounding_ref),
            }
        )
    if not observations:
        raise _ValidationError("source_observations_missing")
    observations.sort(
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    values = [item["value"] for item in observations]
    first = values[0]
    conflict = any(value != first for value in values[1:])
    if conflict:
        outputs = {
            "canonical.value": None,
            "canonical.truth_state": "conflict",
            "conflict.resolution": "unresolved",
            "conflict.source_observations": observations,
        }
        result: Literal["derived", "indeterminate", "conflict", "not_applicable", "rejected"] = "conflict"
        reason = "qualified_sources_disagree"
    else:
        outputs = {
            "canonical.value": first,
            "canonical.truth_state": "asserted",
            "conflict.resolution": "none",
            "conflict.source_observations": observations,
        }
        result = "derived"
        reason = None
    return _make_derivation_bundle(
        rule=rule,
        input_document=input_document,
        input_facts=input_facts,
        outputs=outputs,
        result=result,
        reason=reason,
    )


def _evaluate_derive_coverage_status(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    index: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required = {
        predicate: _single_value(index, predicate)
        for predicate in rule["input_predicates"]
    }
    if not all(ok for ok, _ in required.values()):
        raise _ValidationError("coverage_input_ambiguous")
    values = {predicate: value for predicate, (_, value) in required.items()}
    expected = values["coverage.expected_sources"]
    observed = values["coverage.observed_sources"]
    blind_spots = values["coverage.blind_spots"]
    truncated = values["coverage.sensor_truncated"]
    if (
        not isinstance(expected, list)
        or not expected
        or not all(_nonempty_string(item) for item in expected)
        or len(set(expected)) != len(expected)
        or not isinstance(observed, list)
        or not all(_nonempty_string(item) for item in observed)
        or len(set(observed)) != len(observed)
        or not isinstance(blind_spots, list)
        or not all(_nonempty_string(item) for item in blind_spots)
        or not isinstance(truncated, bool)
    ):
        raise _ValidationError("coverage_input_invalid")
    expected_set = {str(item) for item in expected}
    observed_set = {str(item) for item in observed}
    missing = sorted(expected_set - observed_set)
    reasons = sorted(
        {str(item) for item in blind_spots}
        | ({"sensor_truncated"} if truncated else set())
        | {f"source_unobserved:{source}" for source in missing}
    )
    if not observed_set:
        status = "unknown"
        result: Literal["derived", "indeterminate", "conflict", "not_applicable", "rejected"] = "indeterminate"
        outputs: dict[str, Any] = {
            "coverage.status": status,
            "coverage.reasons": reasons or ["no_qualified_source_observed"],
        }
        reason = "no_qualified_source_observed"
    else:
        complete = not missing and observed_set <= expected_set and not blind_spots and not truncated
        status = "complete" if complete else "partial"
        outputs = {
            "coverage.status": status,
            "coverage.complete": complete,
            "coverage.reasons": reasons,
        }
        result = "derived"
        reason = None if complete else "coverage_partial"
    return _make_derivation_bundle(
        rule=rule,
        input_document=input_document,
        input_facts=input_facts,
        outputs=outputs,
        result=result,
        reason=reason,
    )


def _evaluate_separate_completeness(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    index: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required = {
        predicate: _single_value(index, predicate)
        for predicate in rule["input_predicates"]
    }
    if not all(ok for ok, _ in required.values()):
        raise _ValidationError("completeness_input_ambiguous")
    values = {predicate: value for predicate, (_, value) in required.items()}
    observation_complete = values["observation.complete"]
    observation_reasons = values["observation.reasons"]
    projection_complete = values["projection.complete"]
    projection_reasons = values["projection.reasons"]
    if (
        not isinstance(observation_complete, bool)
        or not isinstance(projection_complete, bool)
        or not isinstance(observation_reasons, list)
        or not all(_nonempty_string(item) for item in observation_reasons)
        or not isinstance(projection_reasons, list)
        or not all(_nonempty_string(item) for item in projection_reasons)
    ):
        raise _ValidationError("completeness_input_invalid")
    return _make_derivation_bundle(
        rule=rule,
        input_document=input_document,
        input_facts=input_facts,
        outputs={
            "semantic_evidence.observation_complete": observation_complete,
            "semantic_evidence.projection_complete": projection_complete,
            "semantic_evidence.projection_can_upgrade_observation": False,
        },
        result="derived",
        reason=None,
    )


def _evaluate_identity_ambiguity_no_fusion(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    index: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mapping_ok, mapping_status = _single_value(index, "identity.mapping_status")
    candidates_ok, candidates = _single_value(index, "identity.source_candidates")
    if (
        not mapping_ok
        or not candidates_ok
        or not _nonempty_string(mapping_status)
        or not isinstance(candidates, list)
        or not all(_nonempty_string(item) for item in candidates)
    ):
        raise _ValidationError("identity_mapping_input_invalid")
    if mapping_status == "ambiguous":
        binding_status = "unresolved"
        reason = "ambiguous_physical_identity"
        result: Literal["derived", "indeterminate", "conflict", "not_applicable", "rejected"] = "indeterminate"
    else:
        binding_status = "indeterminate"
        reason = "identity_mapping_not_proven_unique"
        result = "indeterminate"
    return _make_derivation_bundle(
        rule=rule,
        input_document=input_document,
        input_facts=input_facts,
        outputs={
            "identity.binding_status": binding_status,
            "identity.fusion_performed": False,
            "identity.reason": reason,
        },
        result=result,
        reason=reason,
    )


def _predicate_type_ok(value: Any, value_type: str) -> bool:
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "string":
        return isinstance(value, str)
    if value_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return False


def _semantic_object_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 23
        and value.startswith("el_")
        and all(char in "0123456789abcdef" for char in value[3:])
    )


def _predicate_compare(observed: Any, operator: str, expected: Any) -> bool:
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
    raise _ValidationError("predicate_operator_unsupported")


def _evaluate_predicate_bind_selected_condition(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    index: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required_names = _EVALUATOR_REQUIRED_INPUTS["predicate_bind_selected_condition"]
    required = {predicate: _single_value(index, predicate) for predicate in required_names}
    if not all(ok for ok, _ in required.values()):
        raise _ValidationError("predicate_condition_input_ambiguous")
    values = {predicate: value for predicate, (_, value) in required.items()}
    scope_ref = values["model_condition.scope_ref"]
    target_ref = values["model_condition.target_ref"]
    property_name = values["model_condition.property"]
    operator = values["model_condition.operator"]
    expected = values["model_condition.value"]
    if not _nonempty_string(scope_ref) or not _nonempty_string(target_ref):
        raise _ValidationError("predicate_reference_invalid")
    if not _nonempty_string(property_name) or property_name not in _PREDICATE_SPECS:
        raise _ValidationError("predicate_property_unknown")
    spec = _PREDICATE_SPECS[str(property_name)]
    if operator not in spec["operators"]:
        raise _ValidationError("predicate_operator_mismatch")
    if not _predicate_type_ok(expected, str(spec["value_type"])):
        raise _ValidationError("predicate_value_type_mismatch")
    if "value_enum" in spec and expected not in spec["value_enum"]:
        raise _ValidationError("predicate_value_enum_mismatch")

    if spec["target_kind"] == "scope":
        if target_ref != scope_ref:
            raise _ValidationError("scope_predicate_target_mismatch")
        target = str(scope_ref)
    else:
        target_ok, target = _single_value(index, "binding.target_id")
        binding_scope_ok, binding_scope = _single_value(index, "binding.scope_ref")
        if not target_ok or not binding_scope_ok:
            raise _ValidationError("object_predicate_binding_missing")
        if not _semantic_object_id(target) or binding_scope != scope_ref:
            raise _ValidationError("object_predicate_binding_mismatch")

    return _make_derivation_bundle(
        rule=rule,
        input_document=input_document,
        input_facts=input_facts,
        outputs={
            "predicate.schema": "smc.predicate.v0.1",
            "predicate.domain": "browser",
            "predicate.scope_ref": scope_ref,
            "predicate.target": target,
            "predicate.property": property_name,
            "predicate.operator": operator,
            "predicate.value": expected,
        },
        result="derived",
        reason=None,
    )


def _predicate_indeterminate(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    coverage_complete: bool,
    reason: str,
    observed_value: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return _make_derivation_bundle(
        rule=rule,
        input_document=input_document,
        input_facts=input_facts,
        outputs={
            "predicate.result": "indeterminate",
            "predicate.observed_value": observed_value,
            "predicate.coverage_complete": coverage_complete,
            "predicate.reason": reason,
        },
        result="indeterminate",
        reason=reason,
    )


def _evaluate_predicate_evaluate(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    index: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required_names = _EVALUATOR_REQUIRED_INPUTS["predicate_evaluate"]
    required = {predicate: _single_value(index, predicate) for predicate in required_names}
    if not all(ok for ok, _ in required.values()):
        raise _ValidationError("predicate_evaluation_input_ambiguous")
    values = {predicate: value for predicate, (_, value) in required.items()}
    if values["predicate.schema"] != "smc.predicate.v0.1" or values["predicate.domain"] != "browser":
        raise _ValidationError("predicate_contract_invalid")
    scope_ref = values["predicate.scope_ref"]
    target = values["predicate.target"]
    property_name = values["predicate.property"]
    operator = values["predicate.operator"]
    expected = values["predicate.value"]
    if property_name not in _PREDICATE_SPECS:
        raise _ValidationError("predicate_property_unknown")
    spec = _PREDICATE_SPECS[str(property_name)]
    if operator not in spec["operators"] or not _predicate_type_ok(expected, str(spec["value_type"])):
        raise _ValidationError("predicate_contract_invalid")

    coverage_ok, coverage_value = _single_value(index, "coverage.complete")
    coverage_complete = coverage_ok and coverage_value is True
    scope_relation = values["scope.relation"]
    if scope_relation != "match":
        return _predicate_indeterminate(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            coverage_complete=coverage_complete,
            reason="scope_not_observed" if scope_relation == "indeterminate" else "target_scope_mismatch",
        )

    if spec["target_kind"] == "semantic_object":
        present_ok, target_present = _single_value(index, "observation.target_present")
        if not present_ok or not isinstance(target_present, bool):
            return _predicate_indeterminate(
                rule=rule,
                input_document=input_document,
                input_facts=input_facts,
                coverage_complete=coverage_complete,
                reason="target_presence_unobserved",
            )
        if property_name == "exists":
            if target_present:
                observed: Any = True
            else:
                stable_ok, stable_scope = _single_value(index, "identity.stable_scope")
                if not stable_ok or stable_scope != scope_ref:
                    return _predicate_indeterminate(
                        rule=rule,
                        input_document=input_document,
                        input_facts=input_facts,
                        coverage_complete=coverage_complete,
                        reason="target_identity_unknown_or_identity_unstable",
                    )
                if not coverage_complete:
                    return _predicate_indeterminate(
                        rule=rule,
                        input_document=input_document,
                        input_facts=input_facts,
                        coverage_complete=False,
                        reason="coverage_incomplete_for_absence",
                    )
                observed = False
        else:
            if not target_present:
                return _predicate_indeterminate(
                    rule=rule,
                    input_document=input_document,
                    input_facts=input_facts,
                    coverage_complete=coverage_complete,
                    reason="target_not_observed",
                )
            property_ok, observed = _single_value(index, "observation.property_value")
            if not property_ok:
                return _predicate_indeterminate(
                    rule=rule,
                    input_document=input_document,
                    input_facts=input_facts,
                    coverage_complete=coverage_complete,
                    reason="property_unobserved",
                )
        decisive = _predicate_compare(observed, str(operator), expected)
        return _make_derivation_bundle(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            outputs={
                "predicate.result": "satisfied" if decisive else "unsatisfied",
                "predicate.observed_value": observed,
                "predicate.coverage_complete": coverage_complete,
                "predicate.reason": None,
            },
            result="derived",
            reason=None,
        )

    if target != scope_ref:
        raise _ValidationError("scope_predicate_target_mismatch")
    if property_name == "object_count":
        count_ok, observed_count = _single_value(index, "observation.object_count")
        if not count_ok or not isinstance(observed_count, int) or isinstance(observed_count, bool) or observed_count < 0:
            return _predicate_indeterminate(
                rule=rule,
                input_document=input_document,
                input_facts=input_facts,
                coverage_complete=coverage_complete,
                reason="object_count_unobserved",
            )
        if coverage_complete:
            decisive = _predicate_compare(observed_count, str(operator), expected)
            reason = None
        elif operator == "ge" and observed_count >= expected:
            decisive = True
            reason = "coverage_incomplete_but_lower_bound_is_decisive"
        elif operator in {"eq", "le"} and observed_count > expected:
            decisive = False
            reason = "coverage_incomplete_but_lower_bound_is_decisive"
        else:
            return _predicate_indeterminate(
                rule=rule,
                input_document=input_document,
                input_facts=input_facts,
                coverage_complete=False,
                reason="coverage_incomplete_lower_bound_only",
                observed_value=observed_count,
            )
        return _make_derivation_bundle(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            outputs={
                "predicate.result": "satisfied" if decisive else "unsatisfied",
                "predicate.observed_value": observed_count,
                "predicate.coverage_complete": coverage_complete,
                "predicate.reason": reason,
            },
            result="derived",
            reason=reason,
        )

    property_ok, observed = _single_value(index, "observation.property_value")
    if not property_ok:
        return _predicate_indeterminate(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            coverage_complete=coverage_complete,
            reason="property_unobserved",
        )
    decisive = _predicate_compare(observed, str(operator), expected)
    return _make_derivation_bundle(
        rule=rule,
        input_document=input_document,
        input_facts=input_facts,
        outputs={
            "predicate.result": "satisfied" if decisive else "unsatisfied",
            "predicate.observed_value": observed,
            "predicate.coverage_complete": coverage_complete,
            "predicate.reason": None,
        },
        result="derived",
        reason=None,
    )


def _version_result(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    result_value: str,
    reason: str,
    comparable: bool | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    semantic_result: Literal[
        "derived", "indeterminate", "conflict", "not_applicable", "rejected"
    ] = "indeterminate" if result_value == "indeterminate" else "derived"
    return _make_derivation_bundle(
        rule=rule,
        input_document=input_document,
        input_facts=input_facts,
        outputs={
            "version.result": result_value,
            "version.reason": reason,
            "version.comparable": comparable,
            "version.automatic_refresh_performed": False,
            "version.silent_rebind_performed": False,
        },
        result=semantic_result,
        reason=reason,
    )


def _evaluate_version_assess(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    index: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required = {
        predicate: _single_value(index, predicate)
        for predicate in rule["input_predicates"]
    }
    if not all(ok for ok, _ in required.values()):
        raise _ValidationError("version_assessment_input_ambiguous")
    values = {predicate: value for predicate, (_, value) in required.items()}

    version_scope = values["version.scope"]
    expected = values["version.expected"]
    observed = values["version.observed"]
    expected_availability = values["version.expected_availability"]
    observed_availability = values["version.observed_availability"]
    scope_relation = values["scope.relation"]
    page_same = values["lineage.page_same"]
    document_same = values["lineage.document_same"]
    identity_stable = values["identity.stable"]
    target_present = values["observation.target_present"]
    coverage_complete = values["coverage.complete"]
    object_changed = values["object.changed_fields"]
    resource_changed = values["resource.changed_fields"]

    if version_scope not in {"object", "resource", "snapshot"}:
        raise _ValidationError("version_scope_invalid")
    if not _nonempty_string(expected) or not _nonempty_string(observed):
        raise _ValidationError("version_reference_invalid")
    if not _nonempty_string(expected_availability) or not _nonempty_string(
        observed_availability
    ):
        raise _ValidationError("version_availability_invalid")
    if scope_relation not in {"match", "mismatch", "indeterminate"}:
        raise _ValidationError("version_scope_relation_invalid")
    if not all(
        isinstance(value, bool)
        for value in (
            page_same,
            document_same,
            identity_stable,
            target_present,
            coverage_complete,
        )
    ):
        raise _ValidationError("version_boolean_fact_invalid")
    if (
        not isinstance(object_changed, list)
        or not all(_nonempty_string(item) for item in object_changed)
        or not isinstance(resource_changed, list)
        or not all(_nonempty_string(item) for item in resource_changed)
    ):
        raise _ValidationError("version_changed_fields_invalid")

    if expected_availability != "available":
        return _version_result(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            result_value="indeterminate",
            reason=f"expected_version_{expected_availability}",
            comparable=None,
        )
    if observed_availability != "available":
        return _version_result(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            result_value="indeterminate",
            reason=f"observed_version_{observed_availability}",
            comparable=None,
        )
    if scope_relation != "match":
        return _version_result(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            result_value="indeterminate",
            reason=(
                "scope_not_observed"
                if scope_relation == "indeterminate"
                else "target_scope_mismatch"
            ),
            comparable=None,
        )
    if version_scope == "object" and not identity_stable:
        return _version_result(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            result_value="indeterminate",
            reason="target_identity_unstable",
            comparable=None,
        )
    if expected == observed:
        return _version_result(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            result_value="match",
            reason="exact_version",
            comparable=True,
        )
    if not page_same:
        return _version_result(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            result_value="stale",
            reason="page_generation_changed",
            comparable=False,
        )
    if not document_same:
        return _version_result(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            result_value="stale",
            reason="document_generation_changed",
            comparable=False,
        )

    if version_scope == "object":
        if not target_present:
            if not coverage_complete:
                return _version_result(
                    rule=rule,
                    input_document=input_document,
                    input_facts=input_facts,
                    result_value="indeterminate",
                    reason="target_not_observed_incomplete",
                    comparable=True,
                )
            return _version_result(
                rule=rule,
                input_document=input_document,
                input_facts=input_facts,
                result_value="stale",
                reason="target_absent_in_observed_version",
                comparable=True,
            )
        if object_changed:
            return _version_result(
                rule=rule,
                input_document=input_document,
                input_facts=input_facts,
                result_value="stale",
                reason="object_changed_same_generation",
                comparable=True,
            )
        return _version_result(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            result_value="match",
            reason="object_unchanged_new_observation",
            comparable=True,
        )

    if version_scope == "resource":
        if resource_changed:
            return _version_result(
                rule=rule,
                input_document=input_document,
                input_facts=input_facts,
                result_value="stale",
                reason="resource_changed_same_generation",
                comparable=True,
            )
        return _version_result(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            result_value="match",
            reason="resource_unchanged_new_observation",
            comparable=True,
        )

    return _version_result(
        rule=rule,
        input_document=input_document,
        input_facts=input_facts,
        result_value="stale",
        reason="different_snapshot_same_generation",
        comparable=True,
    )


def _receipt_rows_in_observed_order(
    *,
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    allowed = {
        "receipt.action_id",
        "receipt.seq",
        "receipt.status",
        "receipt.history_watermark",
    }
    fact_ids = {str(fact["fact_id"]) for fact in input_facts}
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for fact in input_document["facts"]:
        if str(fact.get("fact_id")) not in fact_ids:
            continue
        predicate = str(fact["predicate"])
        if predicate not in allowed:
            continue
        subject = str(fact["subject"])
        if subject not in grouped:
            grouped[subject] = {"subject": subject}
            order.append(subject)
        if predicate in grouped[subject]:
            raise _ValidationError("receipt_sequence_duplicate_field")
        grouped[subject][predicate] = fact.get("value")
    rows = [grouped[subject] for subject in order]
    if not rows:
        raise _ValidationError("receipt_sequence_missing")
    if any(set(row) != allowed | {"subject"} for row in rows):
        raise _ValidationError("receipt_sequence_fields_incomplete")
    return rows


def _evaluate_receipt_sequence_validate(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    index: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    del index
    rows = _receipt_rows_in_observed_order(
        input_document=input_document,
        input_facts=input_facts,
    )
    action_ids = [row["receipt.action_id"] for row in rows]
    seqs = [row["receipt.seq"] for row in rows]
    statuses = [row["receipt.status"] for row in rows]
    watermarks = [row["receipt.history_watermark"] for row in rows]
    if not all(_nonempty_string(value) for value in action_ids):
        raise _ValidationError("receipt_action_id_invalid")
    if not all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0
        for value in seqs + watermarks
    ):
        raise _ValidationError("receipt_sequence_number_invalid")
    if not all(status in {"running", "ok", "failed", "rejected"} for status in statuses):
        raise _ValidationError("receipt_status_invalid")

    same_action = len(set(str(value) for value in action_ids)) == 1
    strictly_increasing = all(
        left < right for left, right in zip(seqs, seqs[1:], strict=False)
    )
    watermark_complete = all(
        seq <= watermark for seq, watermark in zip(seqs, watermarks, strict=True)
    ) and (max(seqs) == max(watermarks))
    sequence_monotonic = same_action and strictly_increasing and watermark_complete

    transition_valid = True
    previous: str | None = None
    for status in statuses:
        if previous is None:
            previous = status
            continue
        if previous == "running":
            if status not in {"ok", "failed", "rejected"}:
                transition_valid = False
                break
        elif status != "rejected":
            # Once a physical attempt is terminal, production may append only a
            # duplicate/precondition rejection for the same reserved action id.
            transition_valid = False
            break
        previous = status
    terminal_status = statuses[-1] if statuses[-1] in {"ok", "failed", "rejected"} else None
    reason = None
    if not sequence_monotonic:
        reason = "receipt_sequence_nonmonotonic"
    elif not transition_valid:
        reason = "receipt_transition_invalid"
    return _make_derivation_bundle(
        rule=rule,
        input_document=input_document,
        input_facts=input_facts,
        outputs={
            "receipt.sequence_monotonic": sequence_monotonic,
            "receipt.transition_valid": transition_valid,
            "receipt.terminal_status": terminal_status,
        },
        result="derived",
        reason=reason,
    )


def _evaluate_receipt_dispatch_invariants(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    index: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scalar_predicates = {
        "runtime.reservation_result",
        "runtime.dispatch_count",
        "receipt.retry.automatic_retry_performed",
        "receipt.observed_effects.provisional",
        "receipt.sequence_monotonic",
        "receipt.transition_valid",
    }
    scalar_values = {
        predicate: _single_value(index, predicate) for predicate in scalar_predicates
    }
    if not all(ok for ok, _ in scalar_values.values()):
        raise _ValidationError("receipt_dispatch_input_ambiguous")
    values = {predicate: value for predicate, (_, value) in scalar_values.items()}
    reservation_result = values["runtime.reservation_result"]
    dispatch_count = values["runtime.dispatch_count"]
    automatic_retry = values["receipt.retry.automatic_retry_performed"]
    provisional = values["receipt.observed_effects.provisional"]
    sequence_monotonic = values["receipt.sequence_monotonic"]
    transition_valid = values["receipt.transition_valid"]
    statuses = [fact.get("value") for fact in index.get("receipt.status") or []]
    retry_reasons = [fact.get("value") for fact in index.get("receipt.retry.reason") or []]

    if not isinstance(reservation_result, bool):
        raise _ValidationError("receipt_reservation_result_invalid")
    if (
        not isinstance(dispatch_count, int)
        or isinstance(dispatch_count, bool)
        or dispatch_count < 0
    ):
        raise _ValidationError("receipt_dispatch_count_invalid")
    if not isinstance(automatic_retry, bool) or not isinstance(provisional, bool):
        raise _ValidationError("receipt_dispatch_boolean_invalid")
    if not retry_reasons or not all(
        reason is None or _nonempty_string(reason) for reason in retry_reasons
    ):
        raise _ValidationError("receipt_retry_reason_invalid")
    if not isinstance(sequence_monotonic, bool) or not isinstance(transition_valid, bool):
        raise _ValidationError("receipt_sequence_fact_invalid")
    if not statuses or not all(
        status in {"running", "ok", "failed", "rejected"} for status in statuses
    ):
        raise _ValidationError("receipt_status_invalid")

    single_dispatch_preserved = dispatch_count <= 1
    no_automatic_retry = not automatic_retry
    reservation_consistent = reservation_result or "rejected" in statuses
    invariant_ok = (
        sequence_monotonic
        and transition_valid
        and single_dispatch_preserved
        and no_automatic_retry
        and reservation_consistent
    )
    return _make_derivation_bundle(
        rule=rule,
        input_document=input_document,
        input_facts=input_facts,
        outputs={
            "receipt.single_dispatch_preserved": single_dispatch_preserved,
            "receipt.no_automatic_retry": no_automatic_retry,
            "receipt.effect_evidence_status": (
                "provisional" if provisional else "non_provisional"
            ),
            "receipt.invariant_status": "ok" if invariant_ok else "violation",
        },
        result="derived",
        reason=None if invariant_ok else "receipt_invariant_violation",
    )


def _evaluate_action_fixed_contract(
    *,
    rule: dict[str, Any],
    input_document: dict[str, Any],
    input_facts: list[dict[str, Any]],
    index: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required = {
        predicate: _single_value(index, predicate)
        for predicate in rule["input_predicates"]
    }
    if not all(ok for ok, _ in required.values()):
        raise _ValidationError("action_fixed_contract_input_ambiguous")
    values = {predicate: value for predicate, (_, value) in required.items()}
    if values["binding.status"] != "bound":
        raise _ValidationError("action_fixed_contract_requires_bound_target")
    verb = values["request.verb"]
    target_ref = values["request.target_ref"]
    args = values["request.args"]
    if verb not in {"click", "fill", "select", "scroll", "navigate"}:
        raise _ValidationError("verb_not_in_browser_mutation_profile")
    if not _nonempty_string(target_ref) or not isinstance(args, dict):
        raise _ValidationError("semantic_action_request_invalid")
    return _make_derivation_bundle(
        rule=rule,
        input_document=input_document,
        input_facts=input_facts,
        outputs={
            "action.schema": "smc.semantic_action.v0.1",
            "action.domain": "browser",
            "action.scope_ref": values["binding.scope_ref"],
            "action.action_id": _semantic_action_id(
                verb=str(verb), target_ref=str(target_ref), args=args
            ),
            "action.verb": verb,
            "action.target_id": values["binding.target_id"],
            "action.operation_class": "mutate",
            "action.idempotency_class": "unknown",
            "action.atomicity_class": "single_dispatch",
            "action.expected_version": values["binding.observed_version"],
            "action.version_scope": values["binding.version_scope"],
            "action.version_precondition": "required",
        },
        result="derived",
        reason=None,
    )


_IMPLEMENTED_EVALUATORS: Final = {
    "grounding_exact_binding": _evaluate_grounding_exact_binding,
    "action_fixed_contract": _evaluate_action_fixed_contract,
    "scope_descendant_closure": _evaluate_scope_descendant_closure,
    "scope_target_relation": _evaluate_scope_target_relation,
    "canonicalize_source_conflict": _evaluate_canonicalize_source_conflict,
    "derive_coverage_status": _evaluate_derive_coverage_status,
    "separate_completeness": _evaluate_separate_completeness,
    "identity_ambiguity_no_fusion": _evaluate_identity_ambiguity_no_fusion,
    "predicate_bind_selected_condition": _evaluate_predicate_bind_selected_condition,
    "predicate_evaluate": _evaluate_predicate_evaluate,
    "version_assess": _evaluate_version_assess,
    "receipt_sequence_validate": _evaluate_receipt_sequence_validate,
    "receipt_dispatch_invariants": _evaluate_receipt_dispatch_invariants,
}


def _evaluate_validated(
    *,
    pack: dict[str, Any],
    input_document: dict[str, Any],
) -> dict[str, Any]:
    all_facts = list(input_document["facts"])
    index = _index_facts(all_facts)
    derived_facts: list[dict[str, Any]] = []
    derivations: list[dict[str, Any]] = []
    unimplemented_applicable = False

    for rule in _topological_rules(list(pack["rules"])):
        input_facts = _collect_rule_inputs(rule, index)
        if input_facts is None:
            continue
        evaluator = _IMPLEMENTED_EVALUATORS.get(str(rule["evaluator_op"]))
        if evaluator is None:
            unimplemented_applicable = True
            continue
        new_facts, derivation = evaluator(
            rule=rule,
            input_document=input_document,
            input_facts=input_facts,
            index=index,
        )
        if len(derived_facts) + len(new_facts) > _FROZEN_BOUNDS["max_derived_facts"]:
            raise _ValidationError("max_derived_facts_exceeded")
        if len(derivations) + 1 > _FROZEN_BOUNDS["max_derivations"]:
            raise _ValidationError("max_derivations_exceeded")
        derived_facts.extend(new_facts)
        derivations.append(derivation)
        all_facts.extend(new_facts)
        for fact in new_facts:
            predicate = str(fact["predicate"])
            index.setdefault(predicate, []).append(fact)
            index[predicate].sort(key=lambda value: str(value["fact_id"]))

    if unimplemented_applicable:
        return _result(
            status="unimplemented",
            reason="applicable_semantic_evaluator_not_implemented",
            pack=pack,
            input_document=input_document,
            derived_facts=derived_facts,
            derivations=derivations,
        )
    if not derivations:
        return _result(
            status="unimplemented",
            reason="no_implemented_rule_applicable",
            pack=pack,
            input_document=input_document,
        )
    return _result(
        status="complete",
        reason="closure_complete_for_available_facts",
        pack=pack,
        input_document=input_document,
        derived_facts=derived_facts,
        derivations=derivations,
    )


def evaluate_rulepack(
    *,
    rulepack_document: dict[str, Any],
    input_document: dict[str, Any],
) -> dict[str, Any]:
    """Validate P2 inputs without performing semantic closure yet.

    Rejections are returned as deterministic data so qualification can prove that a
    malformed pack/input never leaks a partially-derived result.  A valid request is
    explicitly ``unimplemented`` until the group evaluators are added by later TDD
    slices.
    """

    pack: dict[str, Any] | None = rulepack_document if isinstance(rulepack_document, dict) else None
    source_input: dict[str, Any] | None = input_document if isinstance(input_document, dict) else None
    try:
        validated_pack, derived_predicates = _validate_pack(rulepack_document)
        _validate_input(
            input_document,
            pack=validated_pack,
            derived_predicates=derived_predicates,
        )
        return _evaluate_validated(pack=validated_pack, input_document=input_document)
    except _ValidationError as exc:
        return _result(
            status="rejected",
            reason=str(exc),
            pack=pack,
            input_document=source_input,
        )

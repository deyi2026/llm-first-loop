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
    status: Literal["rejected", "unimplemented"],
    reason: str,
    pack: dict[str, Any] | None,
    input_document: dict[str, Any] | None,
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
        "derived_facts": [],
        "derivations": [],
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
    except _ValidationError as exc:
        return _result(
            status="rejected",
            reason=str(exc),
            pack=pack,
            input_document=source_input,
        )
    return _result(
        status="unimplemented",
        reason="semantic_evaluators_not_implemented",
        pack=validated_pack,
        input_document=input_document,
    )

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "docs/SMC-EXECUTION-BINDING-SCHEMA-v0.1.json"
FIXTURE_PATH = ROOT / "tests/fixtures/smc_execution_binding_v01.json"

SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _decision(decision: str, reason: str | None = None) -> dict[str, Any]:
    return {"decision": decision, "reason": reason}


def _evaluate(case: dict[str, Any]) -> dict[str, Any]:
    kind = case["kind"]
    inp = case["input"]

    if kind == "action_ref_admission":
        if not inp["session_match"]:
            return _decision("reject", "unauthorized")
        if not inp["integrity_ok"]:
            return _decision("reject", "integrity_error")
        if not inp["retained"]:
            return _decision("reject", "expired")
        if not inp["version_match"]:
            return _decision("reject", "stale")
        if not inp["identity_resolved"]:
            return _decision("reject", "identity_unresolved")
        return _decision("allow")

    if kind == "manifest_cursor":
        if inp["cursor_revision"] != inp["current_revision"]:
            return _decision("reject", "manifest_revision_changed")
        if not inp["projection_complete"] and inp["next_cursor_present"]:
            return _decision("continue")
        return _decision("allow")

    if kind == "manifest_projection":
        if inp["task_relevance_ranking"]:
            return _decision("reject", "semantic_ranking_forbidden")
        if inp["ordering"] != "provider_target_verb_capability_v0.1":
            return _decision("reject", "nondeterministic_ordering")
        if not inp["projection_complete"] and not inp["next_cursor_present"]:
            return _decision("reject", "partial_projection_without_cursor")
        return _decision("allow")

    if kind == "binding_equivalence":
        required = (
            "same_semantic_verb",
            "same_target_contract",
            "same_arg_contract",
            "same_effect_class",
            "same_idempotency",
            "same_atomicity",
            "same_confirmation",
            "same_permission_class",
        )
        if not all(inp[field] for field in required):
            return _decision("reject", "binding_not_equivalent")
        return _decision("allow")

    if kind == "authority":
        if inp["protected_human_only"]:
            return _decision("human_required", "protected_interaction")
        if not inp["runtime_allowed"] or not inp["platform_allowed"]:
            return _decision("reject", "permission_denied")
        return _decision("allow")

    if kind == "context":
        if (
            inp["requires_context"]
            and inp["expected_context_version"] != inp["current_context_version"]
        ):
            return _decision("reject", "context_changed")
        return _decision("allow")

    if kind == "human_preemption":
        if inp["dispatched"]:
            return _decision("settle_receipt", "effect_may_have_occurred")
        if inp["context_sensitive"] and inp["human_interaction_after_prepare"]:
            return _decision("reject", "context_changed")
        return _decision("allow")

    if kind == "receipt_semantic_delta":
        if inp["requested_args"] == inp["effective_args"]:
            return _decision("allow")
        if inp["confirmation_allows_parameter_edit"] and inp["user_confirmed"]:
            return _decision("allow_user_modified")
        return _decision("reject", "semantic_rewrite_forbidden")

    if kind == "cross_device_identity":
        left = inp["left"]
        right = inp["right"]
        portable_fields = ("entity_namespace", "entity_id", "issuer")
        if (
            inp["authoritative_provider_assertion"]
            and all(field in left and field in right for field in portable_fields)
            and all(left[field] == right[field] for field in portable_fields)
        ):
            return _decision("link_allowed")
        return _decision("reject", "portable_identity_unproven")

    raise AssertionError(f"unknown deterministic fixture kind: {kind}")


def _resolve_internal_ref(ref: str) -> Any:
    assert ref.startswith("#/"), ref
    node: Any = SCHEMA
    for segment in ref[2:].split("/"):
        node = node[segment]
    return node


def _walk_refs(node: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                refs.append(value)
            else:
                refs.extend(_walk_refs(value))
    elif isinstance(node, list):
        for value in node:
            refs.extend(_walk_refs(value))
    return refs


def test_schema_is_closed_six_envelope_contract() -> None:
    assert SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    root_refs = [item["$ref"] for item in SCHEMA["oneOf"]]
    assert root_refs == [
        "#/$defs/capability_manifest_page",
        "#/$defs/action_ref_record",
        "#/$defs/execution_binding",
        "#/$defs/interaction_context",
        "#/$defs/binding_dispatch",
        "#/$defs/binding_receipt",
    ]
    for name in (
        "capability_manifest_page",
        "action_ref_record",
        "execution_binding",
        "interaction_context",
        "binding_dispatch",
        "binding_receipt",
    ):
        assert SCHEMA["$defs"][name]["additionalProperties"] is False


def test_all_internal_schema_refs_resolve() -> None:
    refs = _walk_refs(SCHEMA)
    assert refs
    for ref in refs:
        assert _resolve_internal_ref(ref) is not None


def test_action_ref_is_observation_exact_and_ttl_is_not_freshness() -> None:
    action_ref = SCHEMA["$defs"]["action_ref_record"]
    assert action_ref["properties"]["validity_class"]["const"] == "observation_exact"
    required = set(action_ref["required"])
    assert {
        "session_id",
        "scope_ref",
        "semantic_object_id",
        "observation_ref",
        "observed_version",
        "authority_scope",
        "expires_at",
        "integrity",
    } <= required

    stale_case = next(case for case in FIXTURES["cases"] if case["case_id"] == "EB1-01")
    assert stale_case["input"]["retained"] is True
    assert stale_case["input"]["version_match"] is False
    assert _evaluate(stale_case) == {"decision": "reject", "reason": "stale"}


def test_manifest_contract_forbids_hidden_relevance_ranking() -> None:
    manifest = SCHEMA["$defs"]["capability_manifest_page"]
    assert manifest["properties"]["ordering"]["const"] == "provider_target_verb_capability_v0.1"
    assert "task_relevance" not in manifest["properties"]
    assert "priority" not in manifest["properties"]
    assert "recommended" not in manifest["properties"]

    bad = next(case for case in FIXTURES["cases"] if case["case_id"] == "EB2-04")
    assert _evaluate(bad) == {
        "decision": "reject",
        "reason": "semantic_ranking_forbidden",
    }


def test_binding_contract_has_equivalent_only_fallback() -> None:
    binding = SCHEMA["$defs"]["execution_binding"]
    assert binding["properties"]["fallback_policy"]["const"] == "equivalent_only"
    required = set(binding["required"])
    assert {
        "semantic_verb",
        "target_kind",
        "effect_class",
        "idempotency_class",
        "atomicity_class",
        "permission_requirements",
        "confirmation_requirement",
        "context_preconditions",
    } <= required


def test_provider_allow_never_overrides_runtime_or_platform_deny() -> None:
    for case_id in ("EB4-01", "EB4-02"):
        case = next(case for case in FIXTURES["cases"] if case["case_id"] == case_id)
        assert case["input"]["provider_declares_allowed"] is True
        assert _evaluate(case) == {
            "decision": "reject",
            "reason": "permission_denied",
        }


def test_protected_interaction_stays_human_required() -> None:
    case = next(case for case in FIXTURES["cases"] if case["case_id"] == "EB4-03")
    assert _evaluate(case) == {
        "decision": "human_required",
        "reason": "protected_interaction",
    }


def test_context_is_binding_specific_not_global_action_ref_state() -> None:
    shortcut = next(case for case in FIXTURES["cases"] if case["case_id"] == "EB5-01")
    direct = next(case for case in FIXTURES["cases"] if case["case_id"] == "EB5-02")
    assert _evaluate(shortcut) == {
        "decision": "reject",
        "reason": "context_changed",
    }
    assert _evaluate(direct) == {"decision": "allow", "reason": None}


def test_human_preempts_pending_dispatch_but_does_not_erase_dispatched_effect() -> None:
    pending = next(case for case in FIXTURES["cases"] if case["case_id"] == "EB6-01")
    dispatched = next(case for case in FIXTURES["cases"] if case["case_id"] == "EB6-02")
    assert _evaluate(pending) == {
        "decision": "reject",
        "reason": "context_changed",
    }
    assert _evaluate(dispatched) == {
        "decision": "settle_receipt",
        "reason": "effect_may_have_occurred",
    }


def test_semantic_delta_requires_explicit_user_confirmation_authority() -> None:
    unchanged = next(case for case in FIXTURES["cases"] if case["case_id"] == "EB7-01")
    user_edit = next(case for case in FIXTURES["cases"] if case["case_id"] == "EB7-02")
    hidden_rewrite = next(case for case in FIXTURES["cases"] if case["case_id"] == "EB7-03")
    assert _evaluate(unchanged) == {"decision": "allow", "reason": None}
    assert _evaluate(user_edit) == {
        "decision": "allow_user_modified",
        "reason": None,
    }
    assert _evaluate(hidden_rewrite) == {
        "decision": "reject",
        "reason": "semantic_rewrite_forbidden",
    }

    receipt = SCHEMA["$defs"]["binding_receipt"]
    assert {
        "requested_action",
        "effective_action",
        "user_modified_parameters",
        "confirmation_ref",
    } <= set(receipt["required"])


def test_cross_device_identity_requires_authoritative_portable_identity() -> None:
    authoritative = next(case for case in FIXTURES["cases"] if case["case_id"] == "EB8-01")
    similarity = next(case for case in FIXTURES["cases"] if case["case_id"] == "EB8-02")
    assert _evaluate(authoritative) == {
        "decision": "link_allowed",
        "reason": None,
    }
    assert _evaluate(similarity) == {
        "decision": "reject",
        "reason": "portable_identity_unproven",
    }


def test_all_frozen_fixture_oracles_match() -> None:
    cases = FIXTURES["cases"]
    assert len(cases) == 24
    ids = [case["case_id"] for case in cases]
    assert len(ids) == len(set(ids))
    assert set(case["gate"] for case in cases) == {
        "EB1",
        "EB2",
        "EB3",
        "EB4",
        "EB5",
        "EB6",
        "EB7",
        "EB8",
    }
    for case in cases:
        assert _evaluate(case) == case["expected"], case["case_id"]
        assert case["invariant"]


def test_no_fixture_grants_model_or_provider_semantic_rewrite_authority() -> None:
    forbidden_words = (
        "choose best target",
        "fuzzy rebind",
        "silent semantic fallback",
        "provider grants permission",
    )
    payload = json.dumps(FIXTURES, sort_keys=True).lower()
    for phrase in forbidden_words:
        assert phrase not in payload

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from evals.smc_execution_binding_p1.reference import (
    ContractViolationError,
    ExecutionBindingP1Harness,
    canonical_sha256,
    load_p1_fixture,
    run_case_matrix,
)
from evals.smc_execution_binding_p1.schema_validator import (
    FrozenSchemaValidator,
    SchemaValidationError,
    UnsupportedSchemaKeywordError,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "docs/SMC-EXECUTION-BINDING-SCHEMA-v0.1.json"
P1_FIXTURE_PATH = ROOT / "evals/smc_execution_binding_p1/P1-FIXTURES.v0.1.json"


@pytest.fixture(scope="module")
def fixture() -> dict:
    return load_p1_fixture(P1_FIXTURE_PATH)


@pytest.fixture(scope="module")
def validator() -> FrozenSchemaValidator:
    return FrozenSchemaValidator.from_path(SCHEMA_PATH)


@pytest.fixture()
def harness(fixture: dict) -> ExecutionBindingP1Harness:
    return ExecutionBindingP1Harness(fixture)


def test_frozen_schema_keyword_subset_is_explicit_and_supported(
    validator: FrozenSchemaValidator,
) -> None:
    validator.assert_supported_schema()


def test_schema_validator_fails_closed_on_unknown_keyword(
    validator: FrozenSchemaValidator,
) -> None:
    mutated = copy.deepcopy(validator.schema)
    mutated["x-unknown-keyword"] = True
    with pytest.raises(UnsupportedSchemaKeywordError, match="x-unknown-keyword"):
        FrozenSchemaValidator(mutated).assert_supported_schema()


def test_all_positive_envelopes_validate_against_frozen_schema(
    fixture: dict,
    validator: FrozenSchemaValidator,
) -> None:
    envelopes = fixture["positive_envelopes"]
    assert set(envelopes) == {
        "capability_manifest_page",
        "action_ref_record",
        "execution_binding",
        "interaction_context",
        "binding_dispatch",
        "binding_receipt",
    }
    for envelope in envelopes.values():
        validator.validate(envelope)


def test_structural_negative_instances_fail_for_the_intended_schema_reason(
    fixture: dict,
    validator: FrozenSchemaValidator,
) -> None:
    for case in fixture["schema_negative_cases"]:
        with pytest.raises(SchemaValidationError, match=case["error_contains"]):
            validator.validate(case["instance"])


def test_manifest_paging_is_revision_bound_complete_and_deterministic(
    harness: ExecutionBindingP1Harness,
) -> None:
    first = harness.enumerate_capabilities("desktop", page_size=2)
    assert first["manifest_revision"] == 7
    assert first["projection"] == {
        "complete": False,
        "returned_count": 2,
        "total_count": 4,
        "next_cursor": "manifest:desktop:7:2",
    }
    second = harness.enumerate_capabilities(
        "desktop", page_size=2, cursor=first["projection"]["next_cursor"]
    )
    assert second["manifest_revision"] == 7
    assert second["projection"]["complete"] is True
    assert second["projection"]["next_cursor"] is None
    ids = [item["capability_id"] for item in first["items"] + second["items"]]
    assert ids == sorted(ids)


def test_manifest_consumer_rejects_wrong_order_instead_of_silently_sorting(
    harness: ExecutionBindingP1Harness,
) -> None:
    page = harness.enumerate_capabilities("desktop", page_size=4)
    bad = copy.deepcopy(page)
    bad["items"][0], bad["items"][1] = bad["items"][1], bad["items"][0]
    with pytest.raises(ContractViolationError, match="p1_manifest_order_invalid"):
        harness.validate_manifest_page(bad)


def test_manifest_cursor_and_capability_ref_are_provider_revision_bound(
    harness: ExecutionBindingP1Harness,
) -> None:
    first = harness.enumerate_capabilities("desktop", page_size=2)
    with pytest.raises(ContractViolationError, match="manifest_revision_changed"):
        harness.enumerate_capabilities(
            "desktop",
            page_size=2,
            cursor=first["projection"]["next_cursor"],
            current_revision=8,
        )
    cap_ref = first["items"][0]["capability_ref"]
    harness.resolve_capability_ref("desktop", cap_ref, manifest_revision=7)
    with pytest.raises(ContractViolationError, match="capability_ref_invalid"):
        harness.resolve_capability_ref("desktop", cap_ref, manifest_revision=8)
    with pytest.raises(ContractViolationError, match="capability_ref_invalid"):
        harness.resolve_capability_ref("mobile", cap_ref, manifest_revision=7)


def test_mobile_profile_uses_same_contract_with_mobile_context_facts(
    harness: ExecutionBindingP1Harness,
    validator: FrozenSchemaValidator,
) -> None:
    page = harness.enumerate_capabilities("mobile", page_size=10)
    validator.validate(page)
    assert page["domain"] == "mobile"
    assert page["manifest_revision"] == 3
    assert page["projection"]["complete"] is True
    assert any(item["control_capability_class"] == "HUMAN_REQUIRED" for item in page["items"])

    mobile_context = harness.context("mobile")
    validator.validate(mobile_context)
    assert mobile_context["orientation"] == "portrait"
    assert mobile_context["virtual_keyboard"] == "visible"
    share = harness.binding("mobile", "binding.mobile.photo.share.system")
    assert share["binding_class"] == "system_command"
    assert share["context_preconditions"] == ["foreground_scene", "orientation"]


def test_action_ref_ttl_is_retention_only_and_six_single_faults_fail_closed(
    harness: ExecutionBindingP1Harness,
) -> None:
    ref = harness.issue_action_ref("desktop", "doc_17")
    base = harness.current_action_ref_facts("desktop", "doc_17")
    assert harness.admit_action_ref(ref, base)["decision"] == "allow"

    cases = [
        ({"session_id": "other-session"}, "unauthorized"),
        ({"authority_scope": "other-authority"}, "unauthorized"),
        ({"integrity_ok": False}, "integrity_error"),
        ({"now": "2026-09-19T22:00:00Z"}, "expired"),
        ({"observed_version": "doc-v2"}, "stale"),
        ({"identity_resolved": False}, "identity_unresolved"),
    ]
    for delta, reason in cases:
        facts = {**base, **delta}
        assert harness.admit_action_ref(ref, facts) == {
            "decision": "reject",
            "reason": reason,
        }


def test_action_ref_never_silently_refreshes_or_rebinds(
    harness: ExecutionBindingP1Harness,
) -> None:
    ref = harness.issue_action_ref("desktop", "doc_17")
    facts = harness.current_action_ref_facts("desktop", "doc_17")
    facts["observed_version"] = "doc-v2"
    before = canonical_sha256(harness.snapshot_runtime_state())
    assert harness.admit_action_ref(ref, facts)["reason"] == "stale"
    assert canonical_sha256(harness.snapshot_runtime_state()) == before


def test_equivalent_binding_selection_is_stable_and_non_semantic(
    harness: ExecutionBindingP1Harness,
) -> None:
    candidates = harness.bindings_for("desktop", "cap.document.save")
    selected = harness.select_equivalent_binding(candidates)
    assert selected["binding_id"] == "binding.desktop.save.native"
    reversed_selected = harness.select_equivalent_binding(list(reversed(candidates)))
    assert reversed_selected["binding_id"] == selected["binding_id"]

    mixed = candidates + harness.bindings_for("desktop", "cap.document.export")
    with pytest.raises(ContractViolationError, match="binding_not_equivalent"):
        harness.select_equivalent_binding(mixed)


def test_context_sensitive_binding_rejects_race_but_direct_binding_does_not(
    harness: ExecutionBindingP1Harness,
) -> None:
    shortcut = harness.binding("desktop", "binding.desktop.save.shortcut")
    direct = harness.binding("desktop", "binding.desktop.save.native")
    expected = harness.context("desktop")
    changed = {**expected, "context_version": "ctx-desktop-2", "active_window": "win_browser"}
    assert harness.check_context(shortcut, expected, changed) == {
        "decision": "reject",
        "reason": "context_changed",
    }
    assert harness.check_context(direct, expected, changed) == {
        "decision": "allow",
        "reason": None,
    }


def test_authority_composition_is_monotonic_and_protected_stays_human_required(
    harness: ExecutionBindingP1Harness,
) -> None:
    assert harness.compose_authority(
        provider_allowed=True,
        runtime_allowed=False,
        platform_allowed=True,
        enterprise_allowed=True,
        protected_human_only=False,
    ) == {"decision": "reject", "reason": "permission_denied"}
    assert harness.compose_authority(
        provider_allowed=True,
        runtime_allowed=True,
        platform_allowed=True,
        enterprise_allowed=True,
        protected_human_only=True,
    ) == {"decision": "human_required", "reason": "protected_interaction"}


def test_user_confirmed_parameter_edit_is_revalidated_before_effective_action(
    harness: ExecutionBindingP1Harness,
) -> None:
    requested = {
        "target_id": "doc_17",
        "semantic_verb": "export",
        "args": {"destination": "folder_A"},
    }
    effective = {
        "target_id": "doc_17",
        "semantic_verb": "export",
        "args": {"destination": "folder_B"},
    }
    allowed = harness.validate_user_modified_action(
        requested,
        effective,
        confirmation_allows_parameter_edit=True,
        user_confirmed=True,
        schema_valid=True,
        identity_version_valid=True,
        capability_revision_valid=True,
        authority_allowed=True,
        context_valid=True,
    )
    assert allowed["decision"] == "allow_user_modified"
    assert allowed["user_modified_parameters"] == ["destination"]

    rejected = harness.validate_user_modified_action(
        requested,
        effective,
        confirmation_allows_parameter_edit=True,
        user_confirmed=True,
        schema_valid=True,
        identity_version_valid=True,
        capability_revision_valid=True,
        authority_allowed=False,
        context_valid=True,
    )
    assert rejected == {"decision": "reject", "reason": "permission_denied"}


def test_human_preemption_rejects_pending_and_settles_dispatched_without_replay(
    harness: ExecutionBindingP1Harness,
) -> None:
    pending = harness.human_preemption(
        dispatched=False, context_sensitive=True, human_interaction=True
    )
    assert pending["decision"] == "reject"
    assert pending["reason"] == "context_changed"
    assert pending["automatic_replay"] is False
    assert "human_interaction_observed" in pending["boundary_events"]

    dispatched = harness.human_preemption(
        dispatched=True, context_sensitive=True, human_interaction=True
    )
    assert dispatched["decision"] == "settle_receipt"
    assert dispatched["reason"] == "effect_may_have_occurred"
    assert dispatched["automatic_replay"] is False


def test_effect_reservation_rejects_second_programmatic_writer_without_queue(
    harness: ExecutionBindingP1Harness,
) -> None:
    first = harness.reserve_effect("document:doc_17", "action_1")
    second = harness.reserve_effect("document:doc_17", "action_2")
    assert first == {"decision": "allow", "reason": None}
    assert second == {"decision": "reject", "reason": "p1_effect_reserved"}
    assert harness.queued_effects() == []


def test_cross_device_identity_requires_issuer_backed_assertion(
    harness: ExecutionBindingP1Harness,
) -> None:
    left = {
        "entity_namespace": "com.example.documents",
        "entity_id": "doc_123",
        "issuer": "provider_xyz",
    }
    right = dict(left)
    assert harness.link_portable_identity(left, right, authoritative_provider_assertion=True) == {
        "decision": "link_allowed",
        "reason": None,
    }
    similarity_only = {"display_name": "Report.docx", "content_hash": "same"}
    assert harness.link_portable_identity(
        similarity_only, similarity_only, authoritative_provider_assertion=False
    ) == {"decision": "reject", "reason": "portable_identity_unproven"}


def test_case_matrix_covers_all_p1_gates_and_is_byte_stable(fixture: dict) -> None:
    first = run_case_matrix(fixture)
    second = run_case_matrix(fixture)
    assert first == second
    assert canonical_sha256(first) == canonical_sha256(second)
    assert first["intrinsic_gates"] == {
        **{f"P1-G{i}": "pass" for i in range(1, 10)},
        "P1-G11": "pass",
    }
    assert first["external_gates"] == {
        "P1-G10": "pending_full_ci",
        "P1-G12": "pending_double_run_qualification",
    }
    assert first["real_os_dispatch_count"] == 0
    assert first["queued_effect_count"] == 0
    assert first["canonical_evidence_sha256"] == canonical_sha256(first["evidence"])


def test_fixture_and_runner_do_not_depend_on_wall_clock_random_or_network(fixture: dict) -> None:
    assert fixture["determinism"] == {
        "logical_now": "2026-09-19T20:00:00Z",
        "opaque_id_seed": "smc-execution-binding-p1-v0.1",
        "network": "forbidden",
    }

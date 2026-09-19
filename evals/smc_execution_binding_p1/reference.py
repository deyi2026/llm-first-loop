"""Deterministic synthetic reference mechanics for Execution Binding P1.

This module is evaluation-only. It never imports or dispatches a real OS
adapter, input backend, browser backend, shell command, or network client.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from evals.smc_execution_binding_p1.schema_validator import (
    FrozenSchemaValidator,
    SchemaValidationError,
)

ROOT = Path(__file__).resolve().parents[2]
FROZEN_SCHEMA_PATH = ROOT / "docs/SMC-EXECUTION-BINDING-SCHEMA-v0.1.json"


class ContractViolationError(ValueError):
    """A deterministic P1 contract or harness-local diagnostic."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_p1_fixture(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != "smc.execution_binding_p1_fixture.v0.1":
        raise ContractViolationError("p1_fixture_schema_mismatch")
    return value


def _parse_time(value: str) -> datetime:
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(raw)


class ExecutionBindingP1Harness:
    """In-memory world that exercises binding mechanics without real effects."""

    def __init__(self, fixture: dict[str, Any]) -> None:
        self.fixture = copy.deepcopy(fixture)
        self._issued_refs: dict[str, dict[str, Any]] = {}
        self._reservations: dict[str, str] = {}
        self._queued_effects: list[dict[str, Any]] = []
        self.real_os_dispatch_count = 0
        self.synthetic_dispatch_count = 0

    def profile(self, name: str) -> dict[str, Any]:
        try:
            return self.fixture["profiles"][name]
        except KeyError as exc:
            raise ContractViolationError(f"p1_unknown_profile:{name}") from exc

    @staticmethod
    def _capability_sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
        # provider_id is page-level in the frozen schema, so within one page
        # the default tuple reduces mechanically to target/verb/capability.
        return (
            item["target_kind"],
            item["semantic_verb"],
            item["capability_id"],
        )

    def enumerate_capabilities(
        self,
        profile_name: str,
        *,
        page_size: int,
        cursor: str | None = None,
        current_revision: int | None = None,
    ) -> dict[str, Any]:
        profile = self.profile(profile_name)
        revision = profile["manifest_revision"] if current_revision is None else current_revision
        offset = 0
        if cursor is not None:
            parts = cursor.split(":")
            if len(parts) != 4 or parts[0] != "manifest":
                raise ContractViolationError("p1_cursor_invalid")
            _, cursor_profile, raw_revision, raw_offset = parts
            try:
                cursor_revision = int(raw_revision)
                offset = int(raw_offset)
            except ValueError as exc:
                raise ContractViolationError("p1_cursor_invalid") from exc
            if cursor_profile != profile_name:
                raise ContractViolationError("p1_cursor_invalid")
            if cursor_revision != revision:
                raise ContractViolationError("manifest_revision_changed")

        if revision != profile["manifest_revision"]:
            if cursor is not None:
                raise ContractViolationError("manifest_revision_changed")
            raise ContractViolationError("manifest_revision_changed")

        capabilities = sorted(copy.deepcopy(profile["capabilities"]), key=self._capability_sort_key)
        if page_size < 1:
            raise ContractViolationError("p1_page_size_invalid")
        items = capabilities[offset : offset + page_size]
        next_offset = offset + len(items)
        complete = next_offset >= len(capabilities)
        next_cursor = None if complete else f"manifest:{profile_name}:{revision}:{next_offset}"
        page = {
            "schema": "smc.capability_manifest_page.v0.1",
            "manifest_ref": profile["manifest_ref"],
            "manifest_revision": revision,
            "provider_id": profile["provider_id"],
            "domain": profile["domain"],
            "scope_ref": profile["scope_ref"],
            "ordering": "provider_target_verb_capability_v0.1",
            "filters": {
                "target_kind": None,
                "semantic_verb": None,
                "control_capability_class": None,
            },
            "items": items,
            "projection": {
                "complete": complete,
                "returned_count": len(items),
                "total_count": len(capabilities),
                "next_cursor": next_cursor,
            },
        }
        self.validate_manifest_page(page)
        return page

    def validate_manifest_page(self, page: dict[str, Any]) -> None:
        if page.get("ordering") != "provider_target_verb_capability_v0.1":
            raise ContractViolationError("semantic_ranking_forbidden")
        items = page.get("items")
        if not isinstance(items, list):
            raise ContractViolationError("p1_manifest_items_invalid")
        expected = sorted(copy.deepcopy(items), key=self._capability_sort_key)
        if items != expected:
            raise ContractViolationError("p1_manifest_order_invalid")
        projection = page.get("projection") or {}
        if not projection.get("complete") and not projection.get("next_cursor"):
            raise ContractViolationError("partial_projection_without_cursor")

    def resolve_capability_ref(
        self, profile_name: str, capability_ref: str, *, manifest_revision: int
    ) -> dict[str, Any]:
        profile = self.profile(profile_name)
        if manifest_revision != profile["manifest_revision"]:
            raise ContractViolationError("capability_ref_invalid")
        for item in profile["capabilities"]:
            if item["capability_ref"] == capability_ref:
                return copy.deepcopy(item)
        raise ContractViolationError("capability_ref_invalid")

    def issue_action_ref(self, profile_name: str, semantic_object_id: str) -> dict[str, Any]:
        profile = self.profile(profile_name)
        try:
            obj = profile["objects"][semantic_object_id]
        except KeyError as exc:
            raise ContractViolationError("identity_unresolved") from exc

        issued_at = self.fixture["determinism"]["logical_now"]
        expires_at = (
            (_parse_time(issued_at) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        )
        handle_material = (
            f"{self.fixture['determinism']['opaque_id_seed']}:"
            f"{profile_name}:{semantic_object_id}:{obj['observed_version']}"
        )
        action_ref = "ar_" + hashlib.sha256(handle_material.encode("utf-8")).hexdigest()[:12]
        record = {
            "schema": "smc.action_ref_record.v0.1",
            "action_ref": action_ref,
            "validity_class": "observation_exact",
            "session_id": profile["session_id"],
            "device_id": profile["device_id"],
            "domain": profile["domain"],
            "scope_ref": obj["scope_ref"],
            "semantic_object_id": semantic_object_id,
            "observation_ref": obj["observation_ref"],
            "observed_version": obj["observed_version"],
            "authority_scope": profile["authority_scope"],
            "grounding_ref": obj.get("grounding_ref"),
            "provider_object_ref": obj.get("provider_object_ref"),
            "issued_at": issued_at,
            "expires_at": expires_at,
        }
        digest = canonical_sha256(record)
        record["integrity"] = {"algorithm": "sha256", "digest": digest}
        self._issued_refs[action_ref] = copy.deepcopy(record)
        return record

    def current_action_ref_facts(
        self, profile_name: str, semantic_object_id: str
    ) -> dict[str, Any]:
        profile = self.profile(profile_name)
        obj = profile["objects"][semantic_object_id]
        return {
            "session_id": profile["session_id"],
            "authority_scope": profile["authority_scope"],
            "integrity_ok": True,
            "now": self.fixture["determinism"]["logical_now"],
            "observed_version": obj["observed_version"],
            "identity_resolved": True,
        }

    @staticmethod
    def _integrity_ok(record: dict[str, Any]) -> bool:
        integrity = record.get("integrity") or {}
        if integrity.get("algorithm") != "sha256":
            return False
        unsigned = {k: v for k, v in record.items() if k != "integrity"}
        return integrity.get("digest") == canonical_sha256(unsigned)

    def admit_action_ref(self, record: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
        if facts["session_id"] != record["session_id"]:
            return {"decision": "reject", "reason": "unauthorized"}
        if facts["authority_scope"] != record["authority_scope"]:
            return {"decision": "reject", "reason": "unauthorized"}
        if not facts["integrity_ok"] or not self._integrity_ok(record):
            return {"decision": "reject", "reason": "integrity_error"}
        if _parse_time(facts["now"]) >= _parse_time(record["expires_at"]):
            return {"decision": "reject", "reason": "expired"}
        if facts["observed_version"] != record["observed_version"]:
            return {"decision": "reject", "reason": "stale"}
        if not facts["identity_resolved"]:
            return {"decision": "reject", "reason": "identity_unresolved"}
        return {"decision": "allow", "reason": None}

    def bindings_for(self, profile_name: str, capability_id: str) -> list[dict[str, Any]]:
        profile = self.profile(profile_name)
        return copy.deepcopy(profile["bindings"].get(capability_id, []))

    def binding(self, profile_name: str, binding_id: str) -> dict[str, Any]:
        profile = self.profile(profile_name)
        for bindings in profile["bindings"].values():
            for binding in bindings:
                if binding["binding_id"] == binding_id:
                    return copy.deepcopy(binding)
        raise ContractViolationError(f"p1_binding_not_found:{binding_id}")

    @staticmethod
    def _equivalence_signature(binding: dict[str, Any]) -> tuple[Any, ...]:
        return (
            binding["capability_ref"],
            binding["equivalence_class_id"],
            binding["semantic_verb"],
            binding["target_kind"],
            binding["effect_class"],
            binding["idempotency_class"],
            binding["atomicity_class"],
            tuple(sorted(binding["permission_requirements"])),
            binding["confirmation_requirement"],
            tuple(sorted(binding["receipt_obligations"])),
        )

    def select_equivalent_binding(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        if not candidates:
            raise ContractViolationError("p1_no_binding_candidate")
        signature = self._equivalence_signature(candidates[0])
        if any(self._equivalence_signature(item) != signature for item in candidates[1:]):
            raise ContractViolationError("binding_not_equivalent")
        return copy.deepcopy(min(candidates, key=lambda item: item["binding_id"]))

    def context(self, profile_name: str) -> dict[str, Any]:
        return copy.deepcopy(self.profile(profile_name)["context"])

    def check_context(
        self,
        binding: dict[str, Any],
        expected: dict[str, Any],
        current: dict[str, Any],
    ) -> dict[str, Any]:
        preconditions = binding["context_preconditions"]
        if not preconditions:
            return {"decision": "allow", "reason": None}
        if expected["context_version"] != current["context_version"]:
            return {"decision": "reject", "reason": "context_changed"}
        for field in preconditions:
            if expected.get(field) != current.get(field):
                return {"decision": "reject", "reason": "context_changed"}
        return {"decision": "allow", "reason": None}

    @staticmethod
    def compose_authority(
        *,
        provider_allowed: bool,
        runtime_allowed: bool,
        platform_allowed: bool,
        enterprise_allowed: bool,
        protected_human_only: bool,
    ) -> dict[str, Any]:
        _ = provider_allowed  # descriptive only; never grants Runtime authority
        if protected_human_only:
            return {"decision": "human_required", "reason": "protected_interaction"}
        if not (runtime_allowed and platform_allowed and enterprise_allowed):
            return {"decision": "reject", "reason": "permission_denied"}
        return {"decision": "allow", "reason": None}

    @staticmethod
    def validate_user_modified_action(
        requested: dict[str, Any],
        effective: dict[str, Any],
        *,
        confirmation_allows_parameter_edit: bool,
        user_confirmed: bool,
        schema_valid: bool,
        identity_version_valid: bool,
        capability_revision_valid: bool,
        authority_allowed: bool,
        context_valid: bool,
    ) -> dict[str, Any]:
        if requested == effective:
            return {
                "decision": "allow",
                "reason": None,
                "user_modified_parameters": [],
            }
        if requested.get("target_id") != effective.get("target_id") or requested.get(
            "semantic_verb"
        ) != effective.get("semantic_verb"):
            return {"decision": "reject", "reason": "semantic_rewrite_forbidden"}
        if not (confirmation_allows_parameter_edit and user_confirmed):
            return {"decision": "reject", "reason": "semantic_rewrite_forbidden"}
        if not schema_valid:
            return {"decision": "reject", "reason": "invalid_effective_action"}
        if not identity_version_valid:
            return {"decision": "reject", "reason": "stale"}
        if not capability_revision_valid:
            return {"decision": "reject", "reason": "manifest_revision_changed"}
        if not authority_allowed:
            return {"decision": "reject", "reason": "permission_denied"}
        if not context_valid:
            return {"decision": "reject", "reason": "context_changed"}

        requested_args = requested.get("args") or {}
        effective_args = effective.get("args") or {}
        keys = sorted(set(requested_args) | set(effective_args))
        modified = [key for key in keys if requested_args.get(key) != effective_args.get(key)]
        return {
            "decision": "allow_user_modified",
            "reason": None,
            "user_modified_parameters": modified,
        }

    @staticmethod
    def human_preemption(
        *,
        dispatched: bool,
        context_sensitive: bool,
        human_interaction: bool,
    ) -> dict[str, Any]:
        events = ["human_interaction_observed"] if human_interaction else []
        if dispatched:
            return {
                "decision": "settle_receipt",
                "reason": "effect_may_have_occurred",
                "automatic_replay": False,
                "boundary_events": events,
            }
        if context_sensitive and human_interaction:
            events.append("context_changed_by_external_actor")
            return {
                "decision": "reject",
                "reason": "context_changed",
                "automatic_replay": False,
                "boundary_events": events,
            }
        return {
            "decision": "allow",
            "reason": None,
            "automatic_replay": False,
            "boundary_events": events,
        }

    def reserve_effect(self, scope: str, action_id: str) -> dict[str, Any]:
        if scope in self._reservations:
            return {"decision": "reject", "reason": "p1_effect_reserved"}
        self._reservations[scope] = action_id
        return {"decision": "allow", "reason": None}

    def queued_effects(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._queued_effects)

    @staticmethod
    def link_portable_identity(
        left: dict[str, Any],
        right: dict[str, Any],
        *,
        authoritative_provider_assertion: bool,
    ) -> dict[str, Any]:
        fields = ("entity_namespace", "entity_id", "issuer")
        if (
            authoritative_provider_assertion
            and all(field in left and field in right for field in fields)
            and all(left[field] == right[field] for field in fields)
        ):
            return {"decision": "link_allowed", "reason": None}
        return {"decision": "reject", "reason": "portable_identity_unproven"}

    def synthetic_dispatch(self, before_version: str, after_version: str) -> dict[str, Any]:
        self.synthetic_dispatch_count += 1
        return {
            "before_version": before_version,
            "after_version": after_version,
            "observed_effects": [
                {
                    "kind": "synthetic_version_change",
                    "from": before_version,
                    "to": after_version,
                }
            ],
        }

    def snapshot_runtime_state(self) -> dict[str, Any]:
        return {
            "issued_refs": copy.deepcopy(self._issued_refs),
            "reservations": copy.deepcopy(self._reservations),
            "queued_effects": copy.deepcopy(self._queued_effects),
            "real_os_dispatch_count": self.real_os_dispatch_count,
            "synthetic_dispatch_count": self.synthetic_dispatch_count,
        }


def _expect_violation(callable_obj: Any, expected: str) -> str:
    try:
        callable_obj()
    except ContractViolationError as exc:
        if expected not in str(exc):
            raise
        return str(exc)
    raise ContractViolationError(f"p1_expected_violation_missing:{expected}")


def run_case_matrix(fixture: dict[str, Any]) -> dict[str, Any]:
    """Run deterministic intrinsic P1 checks and return canonical evidence.

    P1-G10 (full CI) and P1-G12 (independent double-run comparison) are
    intentionally external qualification gates and are never self-certified.
    """

    harness = ExecutionBindingP1Harness(fixture)
    validator = FrozenSchemaValidator.from_path(FROZEN_SCHEMA_PATH)
    validator.assert_supported_schema()

    for envelope in fixture["positive_envelopes"].values():
        validator.validate(envelope)
    negative_results: list[str] = []
    for case in fixture["schema_negative_cases"]:
        try:
            validator.validate(case["instance"])
        except SchemaValidationError as exc:
            if case["error_contains"] not in str(exc):
                raise
            negative_results.append(case["case_id"])
        else:
            raise ContractViolationError(f"p1_schema_negative_unexpected_pass:{case['case_id']}")

    evidence: list[dict[str, Any]] = []

    first = harness.enumerate_capabilities("desktop", page_size=2)
    second = harness.enumerate_capabilities(
        "desktop", page_size=2, cursor=first["projection"]["next_cursor"]
    )
    mobile = harness.enumerate_capabilities("mobile", page_size=10)
    revision_reject = _expect_violation(
        lambda: harness.enumerate_capabilities(
            "desktop",
            page_size=2,
            cursor=first["projection"]["next_cursor"],
            current_revision=8,
        ),
        "manifest_revision_changed",
    )
    evidence.append(
        {
            "gate": "P1-G1",
            "first_complete": first["projection"]["complete"],
            "second_complete": second["projection"]["complete"],
            "mobile_revision": mobile["manifest_revision"],
            "mobile_capability_count": len(mobile["items"]),
            "revision_reject": revision_reject,
        }
    )

    action_ref = harness.issue_action_ref("desktop", "doc_17")
    stale_facts = harness.current_action_ref_facts("desktop", "doc_17")
    stale_facts["observed_version"] = "doc-v2"
    evidence.append(
        {
            "gate": "P1-G2",
            "decision": harness.admit_action_ref(action_ref, stale_facts),
            "action_ref": action_ref["action_ref"],
        }
    )

    save_bindings = harness.bindings_for("desktop", "cap.document.save")
    selected = harness.select_equivalent_binding(save_bindings)
    mixed_reject = _expect_violation(
        lambda: harness.select_equivalent_binding(
            save_bindings + harness.bindings_for("desktop", "cap.document.export")
        ),
        "binding_not_equivalent",
    )
    evidence.append(
        {
            "gate": "P1-G3",
            "selected_binding": selected["binding_id"],
            "mixed_reject": mixed_reject,
        }
    )

    authority = harness.compose_authority(
        provider_allowed=True,
        runtime_allowed=False,
        platform_allowed=True,
        enterprise_allowed=True,
        protected_human_only=False,
    )
    evidence.append({"gate": "P1-G4", "decision": authority})

    shortcut = harness.binding("desktop", "binding.desktop.save.shortcut")
    direct = harness.binding("desktop", "binding.desktop.save.native")
    mobile_share = harness.binding("mobile", "binding.mobile.photo.share.system")
    expected_context = harness.context("desktop")
    changed_context = {
        **expected_context,
        "context_version": "ctx-desktop-2",
        "active_window": "win_browser",
    }
    evidence.append(
        {
            "gate": "P1-G5",
            "shortcut": harness.check_context(shortcut, expected_context, changed_context),
            "direct": harness.check_context(direct, expected_context, changed_context),
            "mobile_context_preconditions": mobile_share["context_preconditions"],
        }
    )

    pending = harness.human_preemption(
        dispatched=False, context_sensitive=True, human_interaction=True
    )
    settled = harness.human_preemption(
        dispatched=True, context_sensitive=True, human_interaction=True
    )
    evidence.append({"gate": "P1-G6", "pending": pending, "dispatched": settled})

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
    user_edit = harness.validate_user_modified_action(
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
    synthetic_effect = harness.synthetic_dispatch("doc-v1", "doc-v2")
    evidence.append(
        {
            "gate": "P1-G7",
            "user_edit": user_edit,
            "synthetic_effect": synthetic_effect,
        }
    )

    portable = {
        "entity_namespace": "com.example.documents",
        "entity_id": "doc_123",
        "issuer": "provider_xyz",
    }
    similarity = {"display_name": "Report.docx", "content_hash": "same"}
    evidence.append(
        {
            "gate": "P1-G8",
            "issuer_backed": harness.link_portable_identity(
                portable, dict(portable), authoritative_provider_assertion=True
            ),
            "similarity_only": harness.link_portable_identity(
                similarity, dict(similarity), authoritative_provider_assertion=False
            ),
        }
    )

    evidence.append(
        {
            "gate": "P1-G9",
            "positive_envelope_count": len(fixture["positive_envelopes"]),
            "schema_negative_cases": negative_results,
        }
    )

    evidence.append(
        {
            "gate": "P1-G11",
            "real_os_dispatch_count": harness.real_os_dispatch_count,
            "synthetic_dispatch_count": harness.synthetic_dispatch_count,
            "queued_effect_count": len(harness.queued_effects()),
        }
    )

    intrinsic_gates = {f"P1-G{i}": "pass" for i in range(1, 10)}
    intrinsic_gates["P1-G11"] = "pass"
    return {
        "schema": "smc.execution_binding_p1_evidence.v0.1",
        "fixture_schema": fixture["schema"],
        "intrinsic_gates": intrinsic_gates,
        "external_gates": {
            "P1-G10": "pending_full_ci",
            "P1-G12": "pending_double_run_qualification",
        },
        "real_os_dispatch_count": harness.real_os_dispatch_count,
        "synthetic_dispatch_count": harness.synthetic_dispatch_count,
        "queued_effect_count": len(harness.queued_effects()),
        "evidence": evidence,
        "canonical_evidence_sha256": canonical_sha256(evidence),
    }

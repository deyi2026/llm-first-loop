"""Deterministic P1.1 follow-up mechanics.

This module remains evaluation-only. It adds sequence, scale and interleaving
evidence on top of the qualified P1 reference harness without importing any
real OS, network, browser or input backend.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from evals.smc_execution_binding_p1.reference import (
    ExecutionBindingP1Harness,
)
from evals.smc_execution_binding_p1.schema_validator import FrozenSchemaValidator

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_FIXTURE = ROOT / "tests/fixtures/smc_execution_binding_v01.json"
FROZEN_SCHEMA = ROOT / "docs/SMC-EXECUTION-BINDING-SCHEMA-v0.1.json"


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _parse_time(value: str) -> datetime:
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(raw)


def _format_time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def run_action_ref_lifecycle(fixture: dict[str, Any]) -> dict[str, Any]:
    """Run a full ActionRef lifecycle using only the synthetic P1 world."""

    harness = ExecutionBindingP1Harness(copy.deepcopy(fixture))
    profile = harness.fixture["profiles"]["desktop"]
    obj = profile["objects"]["doc_17"]
    steps: list[dict[str, Any]] = []

    def facts() -> dict[str, Any]:
        return harness.current_action_ref_facts("desktop", "doc_17")

    steps.append(
        {
            "event": "observe_v1",
            "observation_ref": obj["observation_ref"],
            "version": obj["observed_version"],
        }
    )

    ar1 = harness.issue_action_ref("desktop", "doc_17")
    steps.append(
        {
            "event": "issue_ar1",
            "action_ref": ar1["action_ref"],
            "version": ar1["observed_version"],
            "issued_at": ar1["issued_at"],
            "expires_at": ar1["expires_at"],
        }
    )
    steps.append(
        {
            "event": "admit_ar1_v1",
            "result": harness.admit_action_ref(ar1, facts()),
        }
    )

    obj["observed_version"] = "doc-v2"
    obj["observation_ref"] = "obs:desktop:2"
    steps.append(
        {
            "event": "mutate_v2",
            "observation_ref": obj["observation_ref"],
            "version": obj["observed_version"],
        }
    )

    stale_ar1 = harness.admit_action_ref(ar1, facts())
    steps.append({"event": "reject_ar1_stale", "result": stale_ar1})
    if stale_ar1 != {"decision": "reject", "reason": "stale"}:
        raise AssertionError("ar1 must become stale after version mutation")

    steps.append(
        {
            "event": "reobserve_v2",
            "observation_ref": obj["observation_ref"],
            "version": obj["observed_version"],
        }
    )

    current = _parse_time(harness.fixture["determinism"]["logical_now"])
    harness.fixture["determinism"]["logical_now"] = _format_time(current + timedelta(minutes=10))
    ar2 = harness.issue_action_ref("desktop", "doc_17")
    steps.append(
        {
            "event": "issue_ar2",
            "action_ref": ar2["action_ref"],
            "version": ar2["observed_version"],
            "issued_at": ar2["issued_at"],
            "expires_at": ar2["expires_at"],
        }
    )

    still_stale = harness.admit_action_ref(ar1, facts())
    steps.append({"event": "reject_ar1_still_stale", "result": still_stale})
    if still_stale != {"decision": "reject", "reason": "stale"}:
        raise AssertionError("issuing ar2 must not revive ar1")

    ar2_admit = harness.admit_action_ref(ar2, facts())
    steps.append({"event": "admit_ar2_v2", "result": ar2_admit})
    if ar2_admit != {"decision": "allow", "reason": None}:
        raise AssertionError("ar2 must be valid for v2 before expiry")

    after_expiry = _parse_time(ar2["expires_at"]) + timedelta(seconds=1)
    harness.fixture["determinism"]["logical_now"] = _format_time(after_expiry)
    steps.append(
        {
            "event": "advance_past_ar2_expiry",
            "logical_now": harness.fixture["determinism"]["logical_now"],
        }
    )
    expired = harness.admit_action_ref(ar2, facts())
    steps.append({"event": "reject_ar2_expired", "result": expired})
    if expired != {"decision": "reject", "reason": "expired"}:
        raise AssertionError("ar2 must expire after its retention deadline")

    return {
        "schema": "smc.execution_binding_p11_actionref_lifecycle.v0.1",
        "steps": steps,
        "ar1": ar1["action_ref"],
        "ar2": ar2["action_ref"],
        "old_ref_revalidated": False,
        "silent_successor_used": False,
        "real_os_dispatch_count": harness.real_os_dispatch_count,
        "synthetic_dispatch_count": harness.synthetic_dispatch_count,
    }


def _synthetic_capability(index: int) -> dict[str, Any]:
    target_kinds = ("document", "window", "file", "photo")
    verbs = ("open", "save", "export", "share")
    classes = ("DIRECT_SEMANTIC", "ACCESSIBILITY_CONTROL", "SYSTEM_COMMAND")
    target_kind = target_kinds[index % len(target_kinds)]
    semantic_verb = verbs[(index // len(target_kinds)) % len(verbs)]
    capability_class = classes[(index // (len(target_kinds) * len(verbs))) % len(classes)]
    capability_id = f"cap.synthetic.{index:04d}"
    return {
        "schema": "smc.capability.v0.1",
        "capability_id": capability_id,
        "capability_ref": f"capref:scale:1:{capability_id}",
        "target_kind": target_kind,
        "semantic_verb": semantic_verb,
        "parameter_schema_ref": f"params:{capability_id}:v0.1",
        "control_capability_class": capability_class,
        "effect_class": f"effect.{semantic_verb}",
        "idempotency_class": "idempotent",
        "atomicity_class": "single_dispatch",
        "permission_requirements": [f"{target_kind}.read"],
        "confirmation_requirement": "none",
        "binding_equivalence_class_id": f"eq.{target_kind}.{semantic_verb}",
    }


def _capability_sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        item["target_kind"],
        item["semantic_verb"],
        item["capability_id"],
    )


def _filter_capabilities(
    items: list[dict[str, Any]],
    filters: dict[str, str],
) -> list[dict[str, Any]]:
    allowed = {"target_kind", "semantic_verb", "control_capability_class"}
    if set(filters) - allowed:
        raise ValueError("P1.1 scale filters must be mechanical and enumerated")
    return [
        item for item in items if all(item.get(field) == value for field, value in filters.items())
    ]


def _manifest_pages(
    items: list[dict[str, Any]],
    *,
    page_size: int,
    filters: dict[str, str],
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    total = len(items)
    for offset in range(0, total, page_size):
        page_items = items[offset : offset + page_size]
        next_offset = offset + len(page_items)
        complete = next_offset >= total
        pages.append(
            {
                "schema": "smc.capability_manifest_page.v0.1",
                "manifest_ref": "manifest:scale:1",
                "manifest_revision": 1,
                "provider_id": "scale.synthetic",
                "domain": "synthetic",
                "scope_ref": "scope:scale",
                "ordering": "provider_target_verb_capability_v0.1",
                "filters": {
                    "target_kind": filters.get("target_kind"),
                    "semantic_verb": filters.get("semantic_verb"),
                    "control_capability_class": filters.get("control_capability_class"),
                },
                "items": page_items,
                "projection": {
                    "complete": complete,
                    "returned_count": len(page_items),
                    "total_count": total,
                    "next_cursor": (None if complete else f"manifest:scale:1:{next_offset}"),
                },
            }
        )
    if total == 0:
        pages.append(
            {
                "schema": "smc.capability_manifest_page.v0.1",
                "manifest_ref": "manifest:scale:1",
                "manifest_revision": 1,
                "provider_id": "scale.synthetic",
                "domain": "synthetic",
                "scope_ref": "scope:scale",
                "ordering": "provider_target_verb_capability_v0.1",
                "filters": {
                    "target_kind": filters.get("target_kind"),
                    "semantic_verb": filters.get("semantic_verb"),
                    "control_capability_class": filters.get("control_capability_class"),
                },
                "items": [],
                "projection": {
                    "complete": True,
                    "returned_count": 0,
                    "total_count": 0,
                    "next_cursor": None,
                },
            }
        )
    return pages


def _wire_metrics(pages: list[dict[str, Any]]) -> tuple[int, int]:
    lengths = [len(canonical_json(page)) for page in pages]
    return sum(lengths), max(lengths)


def run_scale_matrix() -> list[dict[str, Any]]:
    """Measure deterministic surface size without semantic ranking."""

    validator = FrozenSchemaValidator.from_path(FROZEN_SCHEMA)
    validator.assert_supported_schema()
    mechanical_filter = {
        "target_kind": "document",
        "semantic_verb": "save",
        "control_capability_class": "DIRECT_SEMANTIC",
    }
    rows: list[dict[str, Any]] = []
    for capability_count in (32, 128, 512, 1024):
        capabilities = sorted(
            [_synthetic_capability(index) for index in range(capability_count)],
            key=_capability_sort_key,
        )
        filtered = _filter_capabilities(capabilities, mechanical_filter)
        individual_filter_counts = {
            "target_kind=document": len(
                _filter_capabilities(capabilities, {"target_kind": "document"})
            ),
            "semantic_verb=save": len(
                _filter_capabilities(capabilities, {"semantic_verb": "save"})
            ),
            "control_capability_class=DIRECT_SEMANTIC": len(
                _filter_capabilities(
                    capabilities,
                    {"control_capability_class": "DIRECT_SEMANTIC"},
                )
            ),
            "combined": len(filtered),
        }
        for page_size in (16, 32, 64):
            full_pages = _manifest_pages(
                capabilities,
                page_size=page_size,
                filters={},
            )
            filtered_pages = _manifest_pages(
                filtered,
                page_size=page_size,
                filters=mechanical_filter,
            )
            for page in [*full_pages, *filtered_pages]:
                validator.validate(page)
            full_wire_chars, largest_page_wire_chars = _wire_metrics(full_pages)
            filtered_wire_chars, _ = _wire_metrics(filtered_pages)
            rows.append(
                {
                    "capability_count": capability_count,
                    "page_size": page_size,
                    "page_count": len(full_pages),
                    "full_wire_chars": full_wire_chars,
                    "largest_page_wire_chars": largest_page_wire_chars,
                    "approx_tokens_char4": (full_wire_chars + 3) // 4,
                    "filter": dict(mechanical_filter),
                    "filtered_count": len(filtered),
                    "filtered_page_count": len(filtered_pages),
                    "filtered_wire_chars": filtered_wire_chars,
                    "individual_filter_counts": individual_filter_counts,
                    "schema_validated": True,
                    "semantic_ranking_used": False,
                    "token_estimate_note": "mechanical char/4 heuristic; not provider tokenizer",
                }
            )
    return rows


def _receipt(
    *,
    status: str,
    reason: str | None,
    automatic_replay: bool,
    observed_effects: list[dict[str, Any]],
    boundary_events: list[str],
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "automatic_replay": automatic_replay,
        "rollback_claimed": False,
        "observed_effects": observed_effects,
        "boundary_events": boundary_events,
    }


def run_interleaving_matrix() -> dict[str, Any]:
    """Exercise deterministic human-interaction positions around dispatch."""

    rows: list[dict[str, Any]] = []
    synthetic_dispatch_count = 0

    for injection_point in (
        "before_prepare",
        "after_prepare_before_revalidate",
        "after_revalidate_before_dispatch",
        "after_dispatch",
    ):
        expected_context = "ctx-v1"
        current_context = "ctx-v1"
        timeline: list[str] = []

        if injection_point == "before_prepare":
            current_context = "ctx-v2"
            timeline.append("human_context_change")
            timeline.append("prepare")
            row = {
                "injection_point": injection_point,
                "classification": "prevented_before_dispatch",
                "timeline": timeline,
                "dispatch_occurred": False,
                "zero_race_claimed": False,
                "receipt": _receipt(
                    status="rejected",
                    reason="context_changed",
                    automatic_replay=False,
                    observed_effects=[],
                    boundary_events=["human_interaction_observed"],
                ),
            }
            rows.append(row)
            continue

        timeline.append("prepare")

        if injection_point == "after_prepare_before_revalidate":
            current_context = "ctx-v2"
            timeline.append("human_context_change")
            timeline.append("revalidate")
            row = {
                "injection_point": injection_point,
                "classification": "prevented_before_dispatch",
                "timeline": timeline,
                "dispatch_occurred": False,
                "zero_race_claimed": False,
                "receipt": _receipt(
                    status="rejected",
                    reason="context_changed",
                    automatic_replay=False,
                    observed_effects=[],
                    boundary_events=["human_interaction_observed"],
                ),
            }
            rows.append(row)
            continue

        timeline.append("revalidate")
        if current_context != expected_context:
            raise AssertionError("unexpected pre-dispatch context mismatch")

        if injection_point == "after_revalidate_before_dispatch":
            current_context = "ctx-v2"
            timeline.append("human_context_change")
            timeline.append("dispatch")
            synthetic_dispatch_count += 1
            rows.append(
                {
                    "injection_point": injection_point,
                    "classification": "residual_toctou_window",
                    "timeline": timeline,
                    "dispatch_occurred": True,
                    "zero_race_claimed": False,
                    "receipt": _receipt(
                        status="ambiguous",
                        reason="context_changed_after_revalidate",
                        automatic_replay=False,
                        observed_effects=[
                            {
                                "kind": "synthetic_dispatch_under_changed_context",
                                "expected_context": expected_context,
                                "actual_context": current_context,
                            }
                        ],
                        boundary_events=[
                            "human_interaction_observed",
                            "context_changed_by_external_actor",
                        ],
                    ),
                }
            )
            continue

        timeline.append("dispatch")
        synthetic_dispatch_count += 1
        current_context = "ctx-v2"
        timeline.append("human_context_change")
        rows.append(
            {
                "injection_point": injection_point,
                "classification": "post_dispatch_settlement",
                "timeline": timeline,
                "dispatch_occurred": True,
                "zero_race_claimed": False,
                "receipt": _receipt(
                    status="ok",
                    reason=None,
                    automatic_replay=False,
                    observed_effects=[
                        {
                            "kind": "synthetic_effect_committed",
                            "context_at_dispatch": expected_context,
                        }
                    ],
                    boundary_events=["human_interaction_observed_after_dispatch"],
                ),
            }
        )

    return {
        "schema": "smc.execution_binding_p11_interleaving.v0.1",
        "rows": rows,
        "prevented_before_dispatch_count": sum(
            row["classification"] == "prevented_before_dispatch" for row in rows
        ),
        "residual_window_count": sum(
            row["classification"] == "residual_toctou_window" for row in rows
        ),
        "post_dispatch_settlement_count": sum(
            row["classification"] == "post_dispatch_settlement" for row in rows
        ),
        "automatic_replay_count": sum(bool(row["receipt"]["automatic_replay"]) for row in rows),
        "real_os_dispatch_count": 0,
        "synthetic_dispatch_count": synthetic_dispatch_count,
        "probability_claim": None,
        "note": "counts enumerate deterministic interleavings; they are not real-world probabilities",
    }


def _contract_oracle_receipt_parity() -> dict[str, Any]:
    payload = json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))
    cases = [case for case in payload["cases"] if case.get("kind") == "binding_equivalence"]
    complete = all("same_receipt_obligations" in case["input"] for case in cases)
    receipt_only = [
        case
        for case in cases
        if case["input"].get("same_receipt_obligations") is False
        and all(
            case["input"].get(field) is True
            for field in (
                "same_semantic_verb",
                "same_target_contract",
                "same_arg_contract",
                "same_effect_class",
                "same_idempotency",
                "same_atomicity",
                "same_confirmation",
                "same_permission_class",
            )
        )
    ]
    return {
        "binding_equivalence_case_count": len(cases),
        "all_cases_include_receipt_obligations": complete,
        "receipt_only_reject_case_count": len(receipt_only),
    }


def run_p11_evidence(fixture: dict[str, Any]) -> dict[str, Any]:
    parity = _contract_oracle_receipt_parity()
    lifecycle = run_action_ref_lifecycle(fixture)
    scale = run_scale_matrix()
    interleaving = run_interleaving_matrix()

    if not parity["all_cases_include_receipt_obligations"]:
        raise AssertionError("contract oracle parity incomplete")
    if parity["receipt_only_reject_case_count"] != 1:
        raise AssertionError("receipt-obligations-only reject case missing")
    if lifecycle["real_os_dispatch_count"] != 0:
        raise AssertionError("lifecycle touched real OS")
    if len(scale) != 12:
        raise AssertionError("scale matrix incomplete")
    if interleaving["residual_window_count"] != 1:
        raise AssertionError("residual TOCTOU window must be represented")
    if interleaving["automatic_replay_count"] != 0:
        raise AssertionError("automatic replay is forbidden")

    evidence = {
        "oracle_parity": parity,
        "lifecycle": lifecycle,
        "scale": scale,
        "interleaving": interleaving,
    }
    return {
        "schema": "smc.execution_binding_p11_evidence.v0.1",
        "intrinsic_gates": {
            "P1.1-G1": "pass",
            "P1.1-G2": "pass",
            "P1.1-G3": "pass",
            "P1.1-G4": "pass",
            "P1.1-G5": "pass",
            "P1.1-G6": "pass",
            "P1.1-G7": "pass",
            "P1.1-G8": "pass",
        },
        "external_gates": {
            "P1.1-G9": "pending_double_run_qualification",
            "P1.1-G10": "pending_focused_adjacency",
            "P1.1-G11": "pending_full_ci",
            "P1.1-G12": "pending_boundary_audit",
        },
        "real_os_dispatch_count": (
            lifecycle["real_os_dispatch_count"] + interleaving["real_os_dispatch_count"]
        ),
        "synthetic_dispatch_count": (
            lifecycle["synthetic_dispatch_count"] + interleaving["synthetic_dispatch_count"]
        ),
        "evidence": evidence,
        "canonical_evidence_sha256": canonical_sha256(evidence),
    }

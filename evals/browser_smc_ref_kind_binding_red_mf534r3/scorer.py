from __future__ import annotations

from typing import Any


def _call(record: dict[str, Any], index: int) -> dict[str, Any]:
    for row in record.get("tool_calls") or []:
        if int(row.get("index") or 0) == index:
            return dict(row)
    raise KeyError(index)


def score_frozen_binding_incident(record: dict[str, Any]) -> dict[str, Any]:
    """Mechanically score the frozen MF534-R2 B Row3 binding incident."""
    set_text = _call(record, 4)
    first_verify = _call(record, 5)
    hydrate_diff = _call(record, 6)
    mixed_hydrate = _call(record, 7)
    waits = [_call(record, index) for index in (8, 9, 10)]
    fresh_hydrate = _call(record, 12)

    diff_hash = str(set_text.get("result_diff_ref_sha256") or "")
    misbound_first_verify = (
        str(first_verify.get("grounding_ref_kind") or "") == "diff"
        and str(first_verify.get("grounding_ref_sha256") or "") == diff_hash
    )
    generic_hydrate_reinforced = (
        hydrate_diff.get("status") == "success"
        and hydrate_diff.get("grounding_ref_kind") == "diff"
        and hydrate_diff.get("grounding_ref_sha256") == diff_hash
        and hydrate_diff.get("hydration_projection_schema") == "smc.semantic_diff.v0.1"
        and hydrate_diff.get("hydration_has_semantic_object") is False
    )
    repeated_object_wait_mismatch = all(
        row.get("status") == "failure"
        and row.get("failure_kind") == "object_ref_projection_mismatch"
        and row.get("grounding_ref_kind") == "diff"
        and row.get("grounding_ref_sha256") == diff_hash
        for row in waits
    )
    visible_intent_corrected = all(
        "original input object's grounding ref" in str(row.get("visible_intent") or "")
        for row in waits[1:]
    )
    args_stuck_after_visible_correction = visible_intent_corrected and all(
        row.get("grounding_ref_sha256") == diff_hash for row in waits[1:]
    )
    branch_fusion = (
        first_verify.get("has_action2") is True
        and first_verify.get("failure_kind") == "fields_mismatch_action2"
        and mixed_hydrate.get("failure_kind") == "hydrate_with_wait_fields"
    )
    fresh_object_recovered_at_budget_edge = (
        fresh_hydrate.get("status") == "success"
        and fresh_hydrate.get("grounding_ref_kind") == "object"
        and fresh_hydrate.get("hydration_projection_schema") == "smc.semantic_object.v0.1"
        and fresh_hydrate.get("hydration_has_semantic_object") is True
        and int((record.get("task") or {}).get("rounds") or 0)
        == int((record.get("task") or {}).get("max_iterations") or -1)
        and (record.get("task") or {}).get("run_end_reason") == "max_iterations"
    )

    controls = list(record.get("controls") or [])
    a_r1 = next(row for row in controls if int(row.get("row") or 0) == 4)
    b_r2 = next(row for row in controls if int(row.get("row") or 0) == 10)
    controls_disprove_systematic_treatment_failure = (
        a_r1.get("wait_grounding_ref_kind") == "object"
        and a_r1.get("task_oracle_pass") is True
        and int(a_r1.get("protocol_repair_episodes") or 0) == 0
        and b_r2.get("task_oracle_pass") is True
        and int(b_r2.get("protocol_repair_episodes") or 0) == 0
    )

    checks = {
        "diff_ref_bound_into_object_wait": misbound_first_verify,
        "generic_hydrate_accepts_same_diff_ref": generic_hydrate_reinforced,
        "branch_fusion_present": branch_fusion,
        "object_wait_repeats_projection_mismatch": repeated_object_wait_mismatch,
        "visible_intent_correct_but_tool_args_stuck": args_stuck_after_visible_correction,
        "fresh_object_ref_recovered_only_at_budget_edge": fresh_object_recovered_at_budget_edge,
        "same_treatment_has_clean_control": controls_disprove_systematic_treatment_failure,
    }
    return {
        "verdict": "RED" if all(checks.values()) else "NOT_RED",
        "failure_class": "intent_to_tool_json_ref_binding",
        "direct_ref_kind_error": "diff_as_object_grounding_ref",
        "checks": checks,
        "failed_checks": sorted(key for key, value in checks.items() if not value),
        "treatment_causality": str((record.get("treatment") or {}).get("causality_from_single_row")),
        "task_success_overrides_binding_failure": False,
    }


def _wait_branch(parameters: dict[str, Any], kind: str) -> dict[str, Any]:
    for branch in parameters.get("oneOf") or []:
        props = branch.get("properties") or {}
        if ((props.get("action") or {}).get("enum") or []) != ["wait"]:
            continue
        if ((props.get("kind") or {}).get("enum") or []) == [kind]:
            return dict(branch)
    raise KeyError(kind)


def score_provider_ref_kind_visibility(
    parameters: dict[str, Any], compact_description: str
) -> dict[str, Any]:
    """Score only machine-visible ref-kind discrimination; do not judge model quality."""
    object_text = _wait_branch(parameters, "object_text")
    object_state = _wait_branch(parameters, "object_state")

    def field_schema(branch: dict[str, Any]) -> dict[str, Any]:
        return dict((branch.get("properties") or {}).get("grounding_ref") or {})

    text_ref = field_schema(object_text)
    state_ref = field_schema(object_state)

    def has_kind_discriminator(schema: dict[str, Any]) -> bool:
        return any(key in schema for key in ("pattern", "format", "enum", "const")) or (
            "semanticobject" in str(schema.get("description") or "").replace(" ", "").lower()
        )

    checks = {
        "object_text_ref_kind_discriminated": has_kind_discriminator(text_ref),
        "object_state_ref_kind_discriminated": has_kind_discriminator(state_ref),
        "compact_names_semantic_object_ref": (
            "semanticobject" in str(compact_description).replace(" ", "").lower()
            or "对象grounding_ref" in str(compact_description).replace(" ", "")
        ),
    }
    return {
        "verdict": "GREEN" if all(checks.values()) else "RED",
        "checks": checks,
        "failed_checks": sorted(key for key, value in checks.items() if not value),
    }

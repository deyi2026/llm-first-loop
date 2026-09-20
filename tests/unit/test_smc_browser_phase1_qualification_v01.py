from __future__ import annotations

import ast
import json
from pathlib import Path

from llm_loop.browser.action import _MUTATION_CONTRACT
from llm_loop.tools.builtin.browser_action import BrowserActionTool
from llm_loop.tools.registry import _COMPACT_TOOL_DESCRIPTIONS

ROOT = Path(__file__).resolve().parents[2]


R3_PHASE1_EVIDENCE: dict[str, tuple[str, ...]] = {
    "R3-01": ("tests/unit/test_smc_browser_perception_v01.py::test_reorder_preserves_id_but_replacement_and_duplicates_never_reuse_old_id",),
    "R3-02": ("tests/unit/test_smc_browser_perception_v01.py::test_reorder_preserves_id_but_replacement_and_duplicates_never_reuse_old_id",),
    "R3-03": ("tests/unit/test_smc_browser_perception_v01.py::test_reorder_preserves_id_but_replacement_and_duplicates_never_reuse_old_id",),
    "R3-04": ("tests/unit/test_smc_browser_perception_v01.py::test_identity_api_has_no_task_relevance_input",),
    "R3-05": ("tests/unit/test_smc_browser_perception_v01.py::test_identical_content_in_two_pages_never_aliases_semantic_ids",),
    "R3-06": ("tests/unit/test_smc_browser_perception_v01.py::test_document_and_frame_generation_changes_invalidate_old_identity",),
    "R3-07": ("tests/unit/test_smc_browser_semantic_diff_v01.py::test_full_document_generation_change_is_incomparable_not_mass_create_remove",),
    "R3-08": ("tests/unit/test_smc_browser_perception_v01.py::test_adapter_restart_increments_runtime_generation_and_rekeys_ids",),
    "R3-09": ("tests/unit/test_smc_browser_perception_v01.py::test_dom_ax_field_conflict_becomes_null_with_source_grounding",),
    "R3-10": ("tests/unit/test_smc_browser_perception_v01.py::test_dom_ax_identity_mapping_ambiguity_never_force_fuses",),
    "R3-11": ("tests/unit/test_smc_browser_perception_v01.py::test_dom_present_ax_absent_is_source_qualified_not_ax_failure",),
    "R3-12": ("tests/unit/test_smc_browser_perception_v01.py::test_structural_blindspots_and_cross_origin_frame_are_explicit",),
    "R3-13": ("tests/unit/test_smc_browser_perception_v01.py::test_structural_blindspots_and_cross_origin_frame_are_explicit",),
    "R3-15": ("tests/unit/test_smc_browser_perception_v01.py::test_relations_are_structural_only",),
    "R3-16": ("tests/unit/test_smc_browser_perception_v01.py::test_projection_cap_does_not_corrupt_observation_completeness_and_full_hydrates",),
    "R3-17": (
        "tests/unit/test_smc_browser_action_v01.py::test_stale_precondition_rejects_before_dispatch",
        "tests/unit/test_smc_browser_action_v01.py::test_all_mutation_snapshot_scopes_rejected_before_capture",
    ),
    "R3-18": (
        "tests/unit/test_smc_browser_version_pressure_v01.py::test_object_scope_ignores_unrelated_same_document_change_but_pressure_is_visible",
        "tests/unit/test_smc_browser_version_pressure_v01.py::test_resource_scope_uses_document_resource_facts",
        "tests/unit/test_smc_browser_version_pressure_v01.py::test_snapshot_scope_treats_distinct_observation_as_stale",
    ),
    "R3-19": ("tests/unit/test_smc_browser_action_v01.py::test_actuator_error_is_failed_never_retried_and_post_observation_still_attempted",),
    "R3-20": ("tests/unit/test_smc_browser_action_v01.py::test_transport_ambiguity_after_partial_effect_reports_observed_side_effect_without_replay",),
    "R3-21": ("tests/unit/test_smc_browser_cdp_action_host_v01.py::test_page_boundary_events_are_mechanical_and_non_exhaustive",),
    "R3-22": ("tests/unit/test_smc_browser_action_v01.py::test_fresh_exact_guard_dispatches_once_and_appends_running_terminal_receipts",),
    "R3-23": ("tests/unit/test_smc_browser_predicate_wait_v01.py::test_missing_stable_object_can_prove_absence_only_with_complete_coverage",),
    "R3-24": ("tests/unit/test_smc_browser_predicate_wait_v01.py::test_wait_timeout_unsatisfied_is_successful_observation_not_tool_failure",),
    "R3-25": ("tests/unit/test_smc_browser_semantic_diff_v01.py::test_reorder_is_empty_net_diff_and_full_list_ref_hydrates_exactly",),
    "R3-26": ("tests/unit/test_smc_browser_semantic_diff_v01.py::test_sensor_contract_change_makes_snapshot_pair_incomparable",),
    "R3-27": ("tests/unit/test_smc_browser_perception_v01.py::test_push_state_keeps_document_generation_and_identity",),
    "R3-28": ("tests/unit/test_smc_browser_perception_v01.py::test_structural_blindspots_and_cross_origin_frame_are_explicit",),
    "R3-30": ("tests/unit/test_smc_browser_live_perception_v01.py::test_bqual_ptc_experiment_arm_exposes_smc_browser_without_legacy_playwright",),
    "R3-31": ("tests/unit/test_smc_browser_perception_v01.py::test_model_surface_is_read_only_and_has_no_backend_locator_parameters",),
    "R3-32": ("tests/unit/test_smc_browser_perception_v01.py::test_snapshot_and_objects_contain_no_ephemeral_locator_or_strategy_fields",),
}


LIVE_EVIDENCE = {
    "R3-07": "scripts/qualification/smc_browser_live_navigation.py",
    "R3-17": "scripts/qualification/smc_browser_live_action_receipt.py::stale_object_rejected_before_click",
    "R3-19": "scripts/qualification/smc_browser_live_action_receipt.py::real_transport_ambiguity_dispatch_applied_once",
    "R3-20": "scripts/qualification/smc_browser_live_action_receipt.py::real_transport_ambiguity_reports_post_effect_without_replay",
    "R3-21": "scripts/qualification/smc_browser_live_action_receipt.py::popup_boundary_event_visible_without_target_rebind",
    "R3-22": "scripts/qualification/smc_browser_live_action_receipt.py::receipt_running_terminal_append_only",
    "R3-24": "scripts/qualification/smc_browser_live_predicate_wait.py",
    "R3-25": "scripts/qualification/smc_browser_live_semantic_diff.py",
}


B0_B13_EVIDENCE: dict[str, tuple[str, ...]] = {
    "B0": (
        "tests/unit/test_smc_browser_live_perception_v01.py::test_bqual_ptc_experiment_arm_exposes_smc_browser_without_legacy_playwright",
    ),
    "B1": (
        "tests/unit/test_smc_browser_perception_v01.py::test_scope_facts_expose_page_document_nested_frame_parentage_and_hydrate",
    ),
    "B2": (
        "tests/unit/test_smc_browser_perception_v01.py::test_grounding_is_integrity_bound_session_scoped_and_expires",
    ),
    "B3": (
        "tests/unit/test_smc_browser_perception_v01.py::test_reorder_preserves_id_but_replacement_and_duplicates_never_reuse_old_id",
    ),
    "B4": (
        "tests/unit/test_smc_browser_perception_v01.py::test_dom_ax_field_conflict_becomes_null_with_source_grounding",
        "tests/unit/test_smc_browser_perception_v01.py::test_dom_ax_identity_mapping_ambiguity_never_force_fuses",
    ),
    "B5": (
        "tests/unit/test_smc_browser_semantic_diff_v01.py::test_reorder_is_empty_net_diff_and_full_list_ref_hydrates_exactly",
        "tests/unit/test_smc_browser_semantic_diff_v01.py::test_sensor_contract_change_makes_snapshot_pair_incomparable",
    ),
    "B6": (
        "tests/unit/test_smc_browser_action_v01.py::test_all_five_frozen_verbs_accept_only_profile_version_scopes",
        "tests/unit/test_smc_browser_action_v01.py::test_all_mutation_snapshot_scopes_rejected_before_capture",
        "tests/unit/test_smc_browser_cdp_action_host_v01.py::test_click_fill_select_scroll_are_fixed_internal_calls_not_model_scripts",
    ),
    "B7": (
        "tests/unit/test_smc_browser_action_v01.py::test_stale_precondition_rejects_before_dispatch",
    ),
    "B8": (
        "tests/unit/test_smc_browser_action_v01.py::test_actuator_error_is_failed_never_retried_and_post_observation_still_attempted",
        "tests/unit/test_smc_browser_action_v01.py::test_transport_ambiguity_after_partial_effect_reports_observed_side_effect_without_replay",
    ),
    "B9": (
        "tests/unit/test_smc_browser_action_v01.py::test_fresh_exact_guard_dispatches_once_and_appends_running_terminal_receipts",
    ),
    "B10": (
        "tests/unit/test_smc_browser_predicate_wait_v01.py::test_grounded_boolean_predicate_is_three_state_mechanical",
        "tests/unit/test_smc_browser_predicate_wait_v01.py::test_wait_timeout_unsatisfied_is_successful_observation_not_tool_failure",
    ),
    "B11": (
        "tests/unit/test_smc_browser_perception_v01.py::test_structural_blindspots_and_cross_origin_frame_are_explicit",
        "tests/unit/test_smc_browser_cdp_action_host_v01.py::test_page_boundary_events_are_mechanical_and_non_exhaustive",
    ),
    "B12": (
        "tests/unit/test_smc_browser_perception_v01.py::test_snapshot_and_objects_contain_no_ephemeral_locator_or_strategy_fields",
        "tests/unit/test_smc_browser_semantic_diff_v01.py::test_diff_api_has_no_task_semantic_input",
    ),
    "B13": (
        "tests/unit/test_smc_browser_phase1_qualification_v01.py::test_bqual_r3_phase1_has_exactly_30_deterministic_ground_truth_fixtures",
    ),
}


def _test_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    }


def test_bqual_r3_phase1_has_exactly_30_deterministic_ground_truth_fixtures() -> None:
    expected = {f"R3-{index:02d}" for index in range(1, 33)} - {"R3-14", "R3-29"}
    assert set(R3_PHASE1_EVIDENCE) == expected
    assert len(R3_PHASE1_EVIDENCE) == 30

    for scenario, nodeids in R3_PHASE1_EVIDENCE.items():
        assert nodeids, scenario
        for nodeid in nodeids:
            relpath, function_name = nodeid.split("::", 1)
            path = ROOT / relpath
            assert path.is_file(), (scenario, relpath)
            assert function_name in _test_functions(path), (scenario, nodeid)


def test_bqual_deferred_r3_cases_are_not_smuggled_into_phase1_evidence() -> None:
    assert "R3-14" not in R3_PHASE1_EVIDENCE
    assert "R3-29" not in R3_PHASE1_EVIDENCE


def test_bqual_live_evidence_only_supplements_deterministic_fixtures() -> None:
    assert set(LIVE_EVIDENCE).issubset(R3_PHASE1_EVIDENCE)
    for evidence in LIVE_EVIDENCE.values():
        relpath = evidence.split("::", 1)[0]
        assert (ROOT / relpath).is_file()


def test_bqual_b0_b13_each_have_deterministic_implementation_evidence() -> None:
    assert set(B0_B13_EVIDENCE) == {f"B{index}" for index in range(14)}
    for gate, nodeids in B0_B13_EVIDENCE.items():
        assert nodeids, gate
        for nodeid in nodeids:
            relpath, function_name = nodeid.split("::", 1)
            path = ROOT / relpath
            assert path.is_file(), (gate, relpath)
            assert function_name in _test_functions(path), (gate, nodeid)


def test_bqual_lazy_provider_surface_describes_full_qualified_browser_contract() -> None:
    perceive = _COMPACT_TOOL_DESCRIPTIONS["browser_perceive"]
    for action in ("snapshot", "hydrate", "diff", "wait"):
        assert action in perceive
    # v02-20260920：grounding-ref 统一后对象等待引用为 grounding_ref（原 object_ref 退出）
    for boundary in ("不导航", "不mutation", "不fuzzy", "grounding_ref"):
        assert boundary in perceive
    assert "host-bound page" in perceive
    # Qualified typed waits remain available as internal mechanical primitives.
    assert "target=scope_ref" in _COMPACT_TOOL_DESCRIPTIONS["browser_wait_scope_url"]
    assert "boolean value" in _COMPACT_TOOL_DESCRIPTIONS["browser_wait_object_state"]

    mutate = _COMPACT_TOOL_DESCRIPTIONS["browser_action"]
    for verb in ("click", "fill", "select", "navigate", "scroll"):
        assert verb in mutate
    for boundary in (
        "exact Semantic ID",
        "expected_version",
        "object mutation=object",
        "navigate=resource",
        "单次 dispatch",
        "不自动 retry/rebind",
        "不等于任务完成",
    ):
        assert boundary in mutate


def test_mutation_version_scope_contract_is_aligned_across_runtime_profile_and_model_surface() -> None:
    expected = {
        "click": {"object"},
        "fill": {"object"},
        "select": {"object"},
        "navigate": {"resource"},
        "scroll": {"object"},
    }
    runtime = {
        verb: set(_MUTATION_CONTRACT[verb]["version_scopes"])
        for verb in expected
    }
    profile_doc = json.loads(
        (ROOT / "docs/SMC-BROWSER-PHASE1-PROFILE-v0.1.json").read_text(encoding="utf-8")
    )
    profile = {
        verb: set(profile_doc["verb_contracts"][verb]["version_scopes"])
        for verb in expected
    }
    model_surface = set(
        BrowserActionTool.parameters["properties"]["version_scope"]["enum"]
    )

    assert runtime == expected
    assert profile == expected
    assert model_surface == {"object", "resource"}
    assert "snapshot" not in model_surface

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.browser_smc_ref_kind_binding_red_mf534r3.scorer import (
    score_frozen_binding_incident,
    score_provider_ref_kind_visibility,
)
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool
from llm_loop.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "evals/browser_smc_ref_kind_binding_red_mf534r3/row3-binding-frozen.json"


def _lazy_perceive() -> dict[str, Any]:
    registry = ToolRegistry()
    registry.register(BrowserPerceiveTool.__new__(BrowserPerceiveTool))
    row = registry.schemas(lazy=True)[0]
    assert row["name"] == "browser_perceive"
    return row


def test_frozen_row3_is_ref_kind_and_intent_to_json_binding_red() -> None:
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))

    scored = score_frozen_binding_incident(record)

    assert scored["verdict"] == "RED"
    assert scored["failure_class"] == "intent_to_tool_json_ref_binding"
    assert scored["direct_ref_kind_error"] == "diff_as_object_grounding_ref"
    assert scored["failed_checks"] == []
    assert scored["checks"]["visible_intent_correct_but_tool_args_stuck"] is True
    assert scored["checks"]["fresh_object_ref_recovered_only_at_budget_edge"] is True
    assert scored["treatment_causality"] == "NOT_ESTABLISHED"
    assert scored["task_success_overrides_binding_failure"] is False


def test_current_provider_contract_does_not_machine_discriminate_object_ref_kind() -> None:
    perceive = _lazy_perceive()

    scored = score_provider_ref_kind_visibility(
        dict(perceive["parameters"]), str(perceive["description"])
    )

    assert scored["verdict"] == "RED"
    assert "object_text_ref_kind_discriminated" in scored["failed_checks"]
    assert "object_state_ref_kind_discriminated" in scored["failed_checks"]


def test_red_fixture_keeps_controls_separate_from_treatment_causality() -> None:
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))
    controls = {int(row["row"]): row for row in record["controls"]}

    assert controls[4]["post_set_text_path"] == "object_text_wait"
    assert controls[4]["wait_grounding_ref_kind"] == "object"
    assert controls[4]["task_oracle_pass"] is True
    assert controls[9]["post_set_text_path"] == "direct_save_click"
    assert controls[10]["arm"] == "B"
    assert controls[10]["post_set_text_path"] == "direct_save_click"
    assert controls[10]["task_oracle_pass"] is True
    assert record["treatment"]["changes_ref_semantics"] is False
    assert record["treatment"]["causality_from_single_row"] == "NOT_ESTABLISHED"

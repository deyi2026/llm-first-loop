from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from evals.browser_smc_peer_capability_routing_red_mf534r1.scorer import (
    compact_description_treatment,
    score_compact_boundary,
    score_historical_trace,
)
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool
from llm_loop.tools.builtin.browser_semantic_operation import BrowserSemanticOperationTool
from llm_loop.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (
    ROOT
    / "evals"
    / "browser_smc_peer_capability_routing_red_mf534r1"
    / "row3-frozen.json"
)


def _lazy_rows() -> dict[str, dict[str, Any]]:
    registry = ToolRegistry()
    registry.register(BrowserPerceiveTool.__new__(BrowserPerceiveTool))
    registry.register(BrowserSemanticOperationTool.__new__(BrowserSemanticOperationTool))
    return {str(row["name"]): row for row in registry.schemas(lazy=True)}


def test_frozen_row3_first_call_routing_failure_survives_later_recovery() -> None:
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))

    scored = score_historical_trace(record)

    assert scored["routing_verdict"] == "FAIL"
    assert scored["first_call_routing_valid"] is False
    assert scored["failure_kind"] == "cross_capability_routing"
    assert scored["cross_bound_action"] == "navigate"
    assert scored["expected_peer"] == "browser_operate"
    assert scored["recovered_later"] is True
    assert scored["recovery_call_index"] == 2
    assert scored["task_pass"] is True
    assert scored["task_success_overrides_routing"] is False


def test_compact_description_only_ab_freezes_red_to_green_visibility_hypothesis() -> None:
    rows = _lazy_rows()
    perceive = str(rows["browser_perceive"]["description"])
    operate = str(rows["browser_operate"]["description"])

    arm_a = score_compact_boundary(perceive, operate)
    treated_perceive, treated_operate = compact_description_treatment(perceive, operate)
    arm_b = score_compact_boundary(treated_perceive, treated_operate)

    assert arm_a["pass"] is False
    assert "perceive_routes_navigation_to_peer" in arm_a["failed_checks"]
    assert "operate_names_navigation_binding" in arm_a["failed_checks"]
    assert arm_b["pass"] is True
    assert arm_b["failed_checks"] == []


def test_compact_description_only_ab_does_not_change_tool_names_or_parameters() -> None:
    rows = _lazy_rows()
    arm_a = copy.deepcopy(rows)
    arm_b = copy.deepcopy(rows)
    p_desc, o_desc = compact_description_treatment(
        str(arm_a["browser_perceive"]["description"]),
        str(arm_a["browser_operate"]["description"]),
    )
    arm_b["browser_perceive"]["description"] = p_desc
    arm_b["browser_operate"]["description"] = o_desc

    for name in ("browser_perceive", "browser_operate"):
        assert arm_b[name]["name"] == arm_a[name]["name"]
        assert arm_b[name]["parameters"] == arm_a[name]["parameters"]
        assert arm_b[name]["description"] != arm_a[name]["description"]

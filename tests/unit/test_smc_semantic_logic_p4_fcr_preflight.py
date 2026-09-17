from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "evals/smc_semantic_logic_p4_fcr"
PROTOCOL = runpy.run_path(str(HERE / "protocol.py"))


def _plan() -> list[dict[str, Any]]:
    return PROTOCOL["build_plan"]()


def test_p4_fcr_plan_is_exact_40_row_paired_rotation() -> None:
    plan = _plan()
    assert len(plan) == 40
    assert [row["index"] for row in plan] == list(range(1, 41))
    assert {row["arm"] for row in plan} == {"A", "B"}
    assert sum(row["arm"] == "A" for row in plan) == 20
    assert sum(row["arm"] == "B" for row in plan) == 20
    assert {task: sum(row["task_id"] == task for row in plan) for task in PROTOCOL["TASKS"]} == {
        task: 8 for task in PROTOCOL["TASKS"]
    }
    rotations = PROTOCOL["TASK_ROTATION"]
    orders = PROTOCOL["ARM_ORDER"]
    for block in range(20):
        left, right = plan[block * 2 : block * 2 + 2]
        assert left["pair_block"] == right["pair_block"] == block + 1
        assert left["task_id"] == right["task_id"]
        assert left["repeat"] == right["repeat"]
        assert (left["arm"], right["arm"]) == orders[left["repeat"]]
    for repeat in range(1, 5):
        observed = [
            plan[index]["task_id"]
            for index in range((repeat - 1) * 10, repeat * 10, 2)
        ]
        assert tuple(observed) == rotations[repeat]


def test_p4_fcr_arm_b_schema_matches_frozen_parent_protocol() -> None:
    parent = json.loads(
        (ROOT / "docs/SMC-SEMANTIC-LOGIC-P4-AB-PROTOCOL-v0.1.json").read_text(
            encoding="utf-8"
        )
    )
    frozen = parent["arm_b"]["mutation_tools"]
    logical = PROTOCOL["ARM_B_TOOLS"]
    assert set(logical) == set(frozen)
    for name, parent_spec in frozen.items():
        params = logical[name]["parameters"]
        assert params["required"] == parent_spec["required_fields"]
        assert params["properties"] == parent_spec["properties"]
        assert params["additionalProperties"] is False


def test_p4_fcr_good_a_and_b_first_declarations_score_exact() -> None:
    score = PROTOCOL["score_first_response"]
    for task_id, task in PROTOCOL["TASKS"].items():
        a = score(
            task_id=task_id,
            arm="A",
            calls=[{"name": "browser_semantic_execute", "arguments": task.expected_a}],
        )
        assert a["first_call_structural_valid"] is True
        assert a["first_call_mechanical_valid"] is True
        assert a["cross_binding_errors"] == []
        b = score(
            task_id=task_id,
            arm="B",
            calls=[{"name": task.expected_b_tool, "arguments": task.expected_b_args}],
        )
        assert b["first_call_structural_valid"] is True
        assert b["first_call_mechanical_valid"] is True
        assert b["cross_binding_errors"] == []


def test_p4_fcr_scorer_does_not_normalize_targeted_cross_binding_errors() -> None:
    score = PROTOCOL["score_first_response"]
    resource = PROTOCOL["RESOURCE_REF"]
    object_ref = PROTOCOL["OBJECT_REFS"]["click"]
    x01 = score(
        task_id="navigate",
        arm="A",
        calls=[
            {
                "name": "browser_semantic_execute",
                "arguments": {
                    "verb": "navigate",
                    "target_ref": "https://example.test/p4-fcr-destination",
                    "args": {"url": "https://example.test/p4-fcr-destination"},
                },
            }
        ],
    )
    assert "P4-X01" in x01["cross_binding_errors"]
    x02 = score(
        task_id="click",
        arm="B",
        calls=[{"name": "browser_semantic_click", "arguments": {"object_ref": resource}}],
    )
    assert "P4-X02" in x02["cross_binding_errors"]
    x06 = score(
        task_id="fill",
        arm="A",
        calls=[
            {
                "name": "browser_semantic_execute",
                "arguments": {
                    "verb": "fill",
                    "target_ref": PROTOCOL["OBJECT_REFS"]["fill"],
                    "args": {"fill": {"text": "AB-7319", "mode": "replace"}},
                },
            }
        ],
    )
    assert "P4-X06" in x06["cross_binding_errors"]
    x07 = score(
        task_id="click",
        arm="B",
        calls=[
            {
                "name": "browser_semantic_click",
                "arguments": {"object_ref": object_ref, "name": "Commit choice"},
            }
        ],
    )
    assert x07["first_call_structural_valid"] is False
    assert "P4-X07" in x07["cross_binding_errors"]


def test_p4_fcr_schema_reread_is_observed_not_executed_or_erased() -> None:
    task = PROTOCOL["TASKS"]["click"]
    scored = PROTOCOL["score_first_response"](
        task_id="click",
        arm="B",
        calls=[
            {"name": "get_tool_schema", "arguments": {"tool_name": "browser_semantic_click"}},
            {"name": task.expected_b_tool, "arguments": task.expected_b_args},
        ],
    )
    assert scored["schema_reread_intent_or_request"] == 1
    assert scored["first_call_mechanical_valid"] is True


def test_p4_fcr_runner_has_preflight_before_any_model_request() -> None:
    source = (HERE / "run_fcr.py").read_text(encoding="utf-8")
    assert "if args.preflight:" in source
    assert source.index("if args.preflight:") < source.index("run_row(row, manifest)")
    assert '"model_requests": 0' in source
    assert '"tool_execution_total": 0' in source
    assert "BrowserActionAdapter" not in source
    assert "execute_request(" not in source
    assert "Factory" not in source


def test_p4_fcr_harness_adds_no_production_wiring() -> None:
    factory = (ROOT / "src/llm_loop/factory.py").read_text(encoding="utf-8")
    assert "smc_semantic_logic_p4_fcr" not in factory
    for name in PROTOCOL["ARM_B_TOOLS"]:
        assert name not in factory

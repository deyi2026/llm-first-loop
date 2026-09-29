from __future__ import annotations

import copy

from evals.execution_efficiency_v2.scorer import score_row
from evals.execution_efficiency_v2.surfaces_v0_1 import ARMS_V0_1, PORTABILITY_FACT
from evals.execution_efficiency_v2.tasks_v0_1 import TASKS_V0_1, schedule_v0_1, validate_v0_1


def test_schedule_is_balanced_and_frozen():
    assert validate_v0_1() == []
    rows = schedule_v0_1()
    assert len(rows) == 36
    for task in TASKS_V0_1:
        for arm in ARMS_V0_1:
            assert sum(1 for t, a, _ in rows if t["id"] == task["id"] and a == arm) == 3


def test_treatment_fact_is_generic_not_holdout_specific():
    assert "GNU-only" in PORTABILITY_FACT
    for leaked in ("cat -A", "stat -c", "grep -P", "find -printf", "Darwin"):
        assert leaked not in PORTABILITY_FACT


def test_exact_tool_and_argument_oracle_for_holdout():
    task = next(t for t in TASKS_V0_1 if t["id"] == "e21_wrong_get_schema")
    row = {
        "row_id": "x",
        "task_id": task["id"],
        "family": task["family"],
        "arm": "A-current",
        "external_pass": True,
        "fcr_events": {
            "calls": [
                {
                    "name": "get_tool_schema",
                    "classes": ["read"],
                    "args": '{"tool_name":"service_control"}',
                    "ok": True,
                    "turn": 1,
                }
            ]
        },
    }
    scored = score_row(copy.deepcopy(row), task=task)
    assert scored["first_tool_selection_correct"] is True
    assert scored["first_action_oracle_args_match"] is True
    assert scored["first_call_ready"] is True

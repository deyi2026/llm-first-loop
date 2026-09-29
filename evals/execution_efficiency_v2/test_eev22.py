from __future__ import annotations

from evals.execution_efficiency_v2.scorer_v0_2 import score_row_v0_2
from evals.execution_efficiency_v2.surfaces_v0_1 import PORTABILITY_FACT as V21_FACT
from evals.execution_efficiency_v2.surfaces_v0_2 import (
    ARMS_V0_2,
    PORTABILITY_FACT,
)
from evals.execution_efficiency_v2.tasks_v0_2 import (
    TASKS_V0_2,
    schedule_v0_2,
    validate_v0_2,
)


def test_protocol_shape_and_same_treatment():
    assert validate_v0_2() == []
    assert PORTABILITY_FACT == V21_FACT
    rows = schedule_v0_2()
    assert len(rows) == 36
    for task in TASKS_V0_2:
        for arm in ARMS_V0_2:
            assert sum(1 for t, a, _ in rows if t["id"] == task["id"] and a == arm) == 3


def test_wrong_tool_prompts_do_not_name_target_tool():
    for task in TASKS_V0_2:
        if task["family"] != "wrong_tool":
            continue
        for tool in task["decision_acceptable_tools_v22"]:
            assert tool not in task["prompt"]


def test_locator_side_step_is_neutral_but_still_counted():
    task = next(t for t in TASKS_V0_2 if t["id"] == "e22_edit_snapshot_control")
    row = {
        "row_id": "r",
        "task_id": task["id"],
        "family": task["family"],
        "arm": "A-current",
        "external_pass": True,
        "fcr_events": {
            "calls": [
                {
                    "name": "search_files",
                    "classes": ["search"],
                    "args": '{"name":"settings.ini"}',
                    "ok": True,
                    "turn": 1,
                },
                {
                    "name": "read_file",
                    "classes": ["read"],
                    "args": '{"path":"settings.ini","snapshot":true}',
                    "ok": True,
                    "turn": 2,
                },
            ]
        },
    }
    scored = score_row_v0_2(row, task)
    assert scored["neutral_prefix_count"] == 1
    assert scored["neutral_prefix_policy_ok"] is True
    assert scored["decision_call_index"] == 1
    assert scored["decision_tool_name"] == "read_file"
    assert scored["first_call_ready"] is True
    assert scored["serial_tool_barrier_count"] == 1


def test_excess_neutral_side_steps_fail_fcr_without_becoming_wrong_tool():
    task = next(t for t in TASKS_V0_2 if t["id"] == "e22_edit_snapshot_control")
    row = {
        "row_id": "r",
        "task_id": task["id"],
        "family": task["family"],
        "arm": "A-current",
        "external_pass": True,
        "fcr_events": {
            "calls": [
                {"name": "search_files", "args": "{}", "ok": True, "turn": 1},
                {"name": "search_files", "args": "{}", "ok": True, "turn": 2},
                {
                    "name": "read_file",
                    "args": '{"path":"settings.ini","snapshot":true}',
                    "ok": True,
                    "turn": 3,
                },
            ]
        },
    }
    scored = score_row_v0_2(row, task)
    assert scored["neutral_prefix_count"] == 2
    assert scored["neutral_prefix_policy_ok"] is False
    assert scored["first_tool_selection_correct"] is True
    assert scored["wrong_tool_first_call_count"] == 0
    assert scored["first_call_ready"] is False

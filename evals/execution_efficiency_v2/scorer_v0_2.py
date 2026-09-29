"""EEv2.2 scorer with a pre-registered neutral-prefix policy.

The frozen EEv2.1 scorer remains untouched for provenance.  EEv2.2 permits a bounded
prefix of explicitly neutral locator/search calls before evaluating the first decisive
tool action.  Neutral calls still count toward rounds, barriers, failures and wall time;
they are merely not mislabeled as wrong-tool selection.
"""

from __future__ import annotations

from typing import Any

from evals.execution_efficiency_v2.scorer import (
    _json_args,
    _mechanical_contract_rejection,
    score_row,
)


def _oracle(row: dict[str, Any], task: dict[str, Any] | None, key: str, default: Any):
    if isinstance(task, dict) and key in task:
        return task.get(key)
    return row.get(key, default)


def _decision_call(
    calls: list[dict[str, Any]], row: dict[str, Any], task: dict[str, Any] | None
) -> tuple[int | None, int, bool]:
    neutral = {
        str(name)
        for name in (_oracle(row, task, "neutral_prefix_tools_v22", []) or [])
    }
    max_neutral = int(_oracle(row, task, "neutral_prefix_max_v22", 0) or 0)
    prefix = 0
    while prefix < len(calls) and str(calls[prefix].get("name") or "") in neutral:
        prefix += 1
    policy_ok = prefix <= max_neutral
    return (prefix if prefix < len(calls) else None), prefix, policy_ok


def score_row_v0_2(
    row: dict[str, Any], task: dict[str, Any] | None = None
) -> dict[str, Any]:
    scored = score_row(row, task=None)
    calls = list((row.get("fcr_events") or {}).get("calls") or [])
    decision_index, neutral_count, neutral_policy_ok = _decision_call(calls, row, task)
    decision = calls[decision_index] if decision_index is not None else None

    acceptable = {
        str(name)
        for name in (_oracle(row, task, "decision_acceptable_tools_v22", []) or [])
    }
    required_args = _oracle(row, task, "decision_required_arguments_v22", None)

    if decision is None:
        selection = False if calls else None
        args_match = None
        dispatchable = None
    else:
        selection = str(decision.get("name") or "") in acceptable if acceptable else None
        actual = _json_args(decision.get("args"))
        if not isinstance(required_args, dict) or not required_args:
            args_match = True
        elif actual is None:
            args_match = False
        else:
            args_match = all(actual.get(key) == value for key, value in required_args.items())
        dispatchable = (
            None
            if decision.get("ok") is None
            else not _mechanical_contract_rejection(decision)
        )

    fcr = (
        None
        if selection is None or args_match is None or dispatchable is None
        else bool(selection and args_match and dispatchable and neutral_policy_ok)
    )

    scored.update(
        {
            "schema": "lfl-execution-efficiency-v2.2-row/v0.2",
            "raw_first_call_ready_v21": scored.get("first_call_ready"),
            "raw_first_tool_selection_correct_v21": scored.get(
                "first_tool_selection_correct"
            ),
            "neutral_prefix_count": neutral_count,
            "neutral_prefix_policy_ok": neutral_policy_ok,
            "neutral_prefix_policy_violation_count": int(not neutral_policy_ok),
            "decision_call_index": decision_index,
            "decision_tool_name": str(decision.get("name") or "") if decision else None,
            "first_call_ready": fcr,
            "first_tool_selection_correct": selection,
            "first_action_oracle_args_match": args_match,
            "first_call_mechanically_dispatchable": dispatchable,
            "wrong_tool_first_call_count": (
                None if selection is None else int(selection is False)
            ),
            "first_action_oracle_arg_mismatch_count": (
                None if args_match is None else int(args_match is False)
            ),
        }
    )
    return scored

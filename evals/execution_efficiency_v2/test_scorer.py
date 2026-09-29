from __future__ import annotations

from evals.execution_efficiency_v2.oracles import FIRST_ACTION_ACCEPTABLE_CLASSES
from evals.execution_efficiency_v2.scorer import score_row, summarize


def _row(calls, *, selection=True, passed=True, workspace="ws-1"):
    return {
        "row_id": "r1",
        "task_id": "t01_read_first_line",
        "arm": "A-current",
        "workspace": workspace,
        "external_pass": passed,
        "rounds": 3,
        "elapsed_s": 12.5,
        "tokens_in": 1000,
        "cache_hit_tokens": 700,
        "new_prefill_tokens": 300,
        "tokens_out": 100,
        "fcr_scored": {
            "first_call_ready": selection,
            "first_tool_selection_correct": selection,
            "unexpected_failure_count": 0,
            "expected_failure_count": 0,
            "failure_to_repair_count": 0,
            "confirmed_repair_count": 0,
        },
        "fcr_events": {"calls": calls},
    }


def test_wrong_first_tool_is_a_conservative_lower_bound():
    row = _row(
        [{"name": "execute_command", "args": "{}", "ok": True, "turn": 1}],
        selection=False,
    )
    scored = score_row(row, task={"first_action_acceptable_classes_v2": ["read"]})
    assert scored["wrong_tool_first_call_count"] == 1
    assert scored["first_call_ready"] is False


def test_expected_runtime_failure_can_still_be_first_call_ready():
    row = _row(
        [{"name": "execute_command", "classes": ["command"], "args": '{"command":"python3 gen.py"}',
          "ok": False, "result": "[状态: failure] [退出码 1] transient", "turn": 1}],
        selection=False,
    )
    row["task_id"] = "t02_retry_transient"
    scored = score_row(row)
    assert scored["legacy_first_call_ready"] is False
    assert scored["first_tool_selection_correct"] is True
    assert scored["first_call_mechanically_dispatchable"] is True
    assert scored["first_call_ready"] is True
    assert scored["runtime_failure_count"] == 1


def test_tool_contract_rejection_is_not_mechanically_ready():
    row = _row(
        [{"name": "edit_file", "classes": ["edit"], "args": '{"path":"x"}', "ok": False,
          "result": "[修改失败] 当前 edit_file 实例要求 expected_snapshot_ref 版本前置条件", "turn": 1}]
    )
    scored = score_row(row, task={"first_action_acceptable_classes_v2": ["edit"]})
    assert scored["first_call_mechanically_dispatchable"] is False
    assert scored["first_call_ready"] is False
    assert scored["mechanical_contract_rejection_count"] == 1
    assert scored["runtime_failure_count"] == 0


def test_argument_rejection_and_repair_are_separate_signals():
    row = _row(
        [
            {"name": "read_file", "args": '{"path":"x"}', "ok": False,
             "result": "[参数错误] missing required field start_line", "turn": 1},
            {"name": "read_file", "args": '{"path":"x","start_line":1}', "ok": True,
             "result": "ok", "turn": 2},
        ]
    )
    row["fcr_scored"]["failure_to_repair_count"] = 1
    scored = score_row(row)
    assert scored["invalid_argument_rejection_count"] == 1
    assert scored["rejected_call_count"] == 1
    assert scored["failure_to_repair_count"] == 1


def test_schema_reread_is_unknown_not_wrong_without_oracle():
    calls = [{"name": "get_tool_schema", "args": '{"tool_name":"edit_file"}', "ok": True, "turn": 1}]
    scored = score_row(_row(calls), task={})
    assert scored["schema_reread_count"] == 1
    assert scored["avoidable_schema_reread_count"] is None
    forbidden = score_row(_row(calls), task={"schema_reread_policy": "forbidden"})
    assert forbidden["avoidable_schema_reread_count"] == 1


def test_canonical_resource_reread_handles_absolute_relative_paths_but_not_new_page():
    calls = [
        {"name": "read_file", "args": '{"path":"/tmp/run/ws-1/a.txt","start_line":1,"end_line":20}',
         "ok": True, "turn": 1},
        {"name": "read_file", "args": '{"path":"a.txt","start_line":1,"end_line":20}',
         "ok": True, "turn": 2},
        {"name": "read_file", "args": '{"path":"a.txt","start_line":21,"end_line":40}',
         "ok": True, "turn": 3},
    ]
    scored = score_row(_row(calls))
    assert scored["redundant_reacquisition_count"] == 1
    assert scored["exact_duplicate_success_count"] == 0


def test_serial_barrier_counts_tool_rounds_not_total_calls():
    calls = [
        {"name": "read_file", "args": '{"path":"a"}', "ok": True, "turn": 1},
        {"name": "read_file", "args": '{"path":"b"}', "ok": True, "turn": 1},
        {"name": "execute_command", "args": '{"command":"x"}', "ok": True, "turn": 2},
    ]
    scored = score_row(_row(calls))
    assert scored["tool_call_count"] == 3
    assert scored["tool_call_round_count"] == 2
    assert scored["serial_tool_barrier_count"] == 1
    assert scored["max_parallel_tool_width"] == 2


def test_summary_has_correctness_gate_and_no_weighted_score():
    good = score_row(_row([{"name": "read_file", "args": "{}", "ok": True, "turn": 1}]))
    bad = score_row(_row([{"name": "read_file", "args": "{}", "ok": True, "turn": 1}], passed=False))
    summary = summarize([good, bad], dataset="fixture")
    assert summary["overall"]["correctness_gate"] is False
    assert summary["weighted_score"] is None
    assert summary["tool_count_is_not_an_optimization_target"] is True


def test_p1a_whole_oracle_coverage_is_explicit():
    expected = {
        "t01_read_first_line",
        "t02_retry_transient",
        "t04_fix_bug",
        "t05_multi_file_sum",
        "t09_big_file_line",
        "t11_env_facts",
    }
    assert set(FIRST_ACTION_ACCEPTABLE_CLASSES) == expected
    assert FIRST_ACTION_ACCEPTABLE_CLASSES["t02_retry_transient"] == frozenset({"command"})
    assert FIRST_ACTION_ACCEPTABLE_CLASSES["t11_env_facts"] == frozenset({"command"})

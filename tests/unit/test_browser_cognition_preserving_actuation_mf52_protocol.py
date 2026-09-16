from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = ROOT / "evals/browser_smc_cognition_preserving_actuation_mf52/protocol.py"
_spec = importlib.util.spec_from_file_location("mf52_protocol", PROTOCOL_PATH)
assert _spec is not None and _spec.loader is not None
protocol = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = protocol
_spec.loader.exec_module(protocol)


def _record(index: int, task_id: str, repeat: int) -> dict[str, Any]:
    object_ok = 2 if task_id == "fill_submit" else 1
    return {
        "index": index,
        "task_id": task_id,
        "repeat": repeat,
        "status": "PASS",
        "oracle": {"pass": True},
        "security_agent_spawned": False,
        "worker": {
            "surface_exact": True,
            "fallback_used": False,
            "first_operation_contract_valid": True,
            "operation_tool_failure_count": 0,
            "operation_tool_error_count": 0,
            "get_tool_schema_count": 0,
            "read_evidence_count": 0,
            "protocol_repair_episode_count": 0,
            "direct_atomic_browser_call_count": 0,
            "task_completion_violation_count": 0,
            "undeclared_boundary_continuation_count": 0,
            "operation_unparsed_result_count": 0,
            "operation_automatic_retry_true_count": 0,
            "operation_call_count": 3,
            "operation_arg_chars_total": 300,
            "operation_result_chars_total": 900,
            "single_action_operation_count": 3,
            "multi_action_operation_count": 0,
            "rounds": 4,
            "tokens_in": 1000,
            "tokens_out": 100,
            "cache_hit_tokens": 800,
            "action_receipt_facts": {
                "automatic_retry_true_count": 0,
                "navigate_ok_count": 1,
                "object_ok_count": object_ok,
            },
        },
    }


def _passing_records() -> list[dict[str, Any]]:
    return [
        _record(index, task_id, repeat)
        for index, (task_id, repeat) in enumerate(protocol.ROWS, start=1)
    ]


def test_mf52_gate_accepts_clean_six_row_treatment() -> None:
    gate = protocol.qualification_gate(_passing_records())
    assert gate["pass"] is True
    assert gate["task_pass"] == 6
    assert gate["first_operation_contract_valid"] == 6
    assert gate["protocol_repair_episodes"] == 0


def test_mf52_gate_rejects_schema_repair() -> None:
    rows = _passing_records()
    rows[0]["worker"]["get_tool_schema_count"] = 1
    rows[0]["worker"]["protocol_repair_episode_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False


def test_mf52_gate_rejects_contract_failure() -> None:
    rows = _passing_records()
    rows[1]["worker"]["operation_tool_failure_count"] = 1
    rows[1]["worker"]["protocol_repair_episode_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False


def test_mf52_gate_rejects_invalid_first_operation() -> None:
    rows = _passing_records()
    rows[2]["worker"]["first_operation_contract_valid"] = False
    assert protocol.qualification_gate(rows)["pass"] is False


def test_mf52_gate_rejects_security_agent_spawn() -> None:
    rows = _passing_records()
    rows[3]["security_agent_spawned"] = True
    assert protocol.qualification_gate(rows)["pass"] is False


def test_mf52_gate_rejects_undeclared_boundary_continuation() -> None:
    rows = _passing_records()
    rows[4]["worker"]["undeclared_boundary_continuation_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False


def test_mf52_gate_rejects_unparsed_or_automatic_retry() -> None:
    rows = _passing_records()
    rows[5]["worker"]["operation_unparsed_result_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False
    rows = _passing_records()
    rows[5]["worker"]["operation_automatic_retry_true_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False

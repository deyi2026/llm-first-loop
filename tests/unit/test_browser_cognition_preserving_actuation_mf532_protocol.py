from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = ROOT / "evals/browser_smc_cognition_preserving_actuation_mf532/protocol.py"
_spec = importlib.util.spec_from_file_location("mf532_protocol", PROTOCOL_PATH)
assert _spec is not None and _spec.loader is not None
protocol = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = protocol
_spec.loader.exec_module(protocol)



def test_mf532_identity_and_plan_are_frozen() -> None:
    assert protocol.SCHEMA == "smc.browser_cognition_preserving_actuation_mf532.v0.1"
    assert protocol.IMPLEMENTATION_COMMIT == "05d0f36c7202a8c183a517813815f6ef83f2cfe4"
    plan = protocol.build_plan()
    assert len(plan) == 6
    assert [row["index"] for row in plan] == [1, 2, 3, 4, 5, 6]
    assert all(row["arm"] == "peer_capability_quality_projection" for row in plan)
    assert [(row["task_id"], row["repeat"]) for row in plan] == list(protocol.ROWS)
    assert {row["task_id"]: row["prompt_template_sha256"] for row in plan} == {
        "click_commit": "823e7cb25a1f2f234412564a93ed221956bdbcb4214aff1d67a78fd9296c6f2d",
        "fill_submit": "d80607ace4193874d8b7deddc2988f8b6562443b99b54455e48163cc4a6ff9e2",
        "delayed_wait": "eb99aac9458104ca12770d07ce1886f9d3bd76f8955ce9b5135de33b476ae694",
    }

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
            "first_browser_call_contract_valid": True,
            "perceive_tool_failure_count": 0,
            "perceive_tool_error_count": 0,
            "operation_tool_failure_count": 0,
            "operation_tool_error_count": 0,
            "get_tool_schema_count": 0,
            "read_evidence_count": 0,
            "protocol_repair_episode_count": 0,
            "ground_probe_amplification_count": 0,
            "duplicate_successful_mutation_count": 0,
            "direct_atomic_browser_call_count": 0,
            "task_completion_violation_count": 0,
            "undeclared_boundary_continuation_count": 0,
            "operation_unparsed_result_count": 0,
            "operation_automatic_retry_true_count": 0,
            "perceive_call_count": 2,
            "perceive_snapshot_count": 1,
            "perceive_hydrate_count": 0,
            "perceive_diff_count": 0,
            "perceive_wait_count": 1 if task_id == "delayed_wait" else 0,
            "operation_call_count": 3,
            "browser_arg_chars_total": 300,
            "browser_result_chars_total": 900,
            "delta_only_count": 2,
            "delta_to_hydrate_count": 0,
            "delta_to_snapshot_count": 1,
            "delta_to_hydrate_then_snapshot_count": 0,
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


def test_mf532_gate_accepts_clean_six_row_perceive_operate_treatment() -> None:
    gate = protocol.qualification_gate(_passing_records())
    assert gate["pass"] is True
    assert gate["task_pass"] == 6
    assert gate["first_browser_call_contract_valid"] == 6
    assert gate["protocol_repair_episodes"] == 0
    assert gate["ground_probe_amplification"] == 0
    assert gate["duplicate_successful_mutations"] == 0


def test_mf532_gate_rejects_perceive_contract_failure_or_error() -> None:
    rows = _passing_records()
    rows[0]["worker"]["perceive_tool_failure_count"] = 1
    rows[0]["worker"]["protocol_repair_episode_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False
    rows = _passing_records()
    rows[0]["worker"]["perceive_tool_error_count"] = 1
    rows[0]["worker"]["protocol_repair_episode_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False


def test_mf532_gate_rejects_operate_contract_failure_or_error() -> None:
    rows = _passing_records()
    rows[1]["worker"]["operation_tool_failure_count"] = 1
    rows[1]["worker"]["protocol_repair_episode_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False
    rows = _passing_records()
    rows[1]["worker"]["operation_tool_error_count"] = 1
    rows[1]["worker"]["protocol_repair_episode_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False


def test_mf532_gate_rejects_schema_repair() -> None:
    rows = _passing_records()
    rows[2]["worker"]["get_tool_schema_count"] = 1
    rows[2]["worker"]["protocol_repair_episode_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False


def test_mf532_gate_rejects_ground_probe_amplification() -> None:
    rows = _passing_records()
    rows[3]["worker"]["ground_probe_amplification_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False


def test_mf532_gate_rejects_duplicate_successful_mutation() -> None:
    rows = _passing_records()
    rows[4]["worker"]["duplicate_successful_mutation_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False


def test_mf532_gate_rejects_invalid_first_browser_call_or_security_agent() -> None:
    rows = _passing_records()
    rows[0]["worker"]["first_browser_call_contract_valid"] = False
    assert protocol.qualification_gate(rows)["pass"] is False
    rows = _passing_records()
    rows[0]["security_agent_spawned"] = True
    assert protocol.qualification_gate(rows)["pass"] is False


def test_mf532_gate_rejects_hidden_atomic_or_boundary_authority() -> None:
    rows = _passing_records()
    rows[5]["worker"]["direct_atomic_browser_call_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False
    rows = _passing_records()
    rows[5]["worker"]["undeclared_boundary_continuation_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False
    rows = _passing_records()
    rows[5]["worker"]["task_completion_violation_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False


def test_mf532_gate_rejects_unparsed_or_automatic_retry() -> None:
    rows = _passing_records()
    rows[5]["worker"]["operation_unparsed_result_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False
    rows = _passing_records()
    rows[5]["worker"]["operation_automatic_retry_true_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False
    rows = _passing_records()
    rows[5]["worker"]["action_receipt_facts"]["automatic_retry_true_count"] = 1
    assert protocol.qualification_gate(rows)["pass"] is False


def test_mf532_browser_capability_pair_is_frozen() -> None:
    assert protocol.BROWSER_CAPABILITIES == ("browser_perceive", "browser_operate")
    assert set(protocol.ALLOWED_TOOLS) == {
        "browser_perceive", "browser_operate", "get_tool_schema", "read_evidence"
    }


def test_mf532_fixture_is_byte_identical_to_mf531() -> None:
    import hashlib
    old = ROOT / "evals/browser_smc_cognition_preserving_actuation_mf531/fixture_server.py"
    new = ROOT / "evals/browser_smc_cognition_preserving_actuation_mf532/fixture_server.py"
    assert hashlib.sha256(old.read_bytes()).hexdigest() == hashlib.sha256(new.read_bytes()).hexdigest()
    assert hashlib.sha256(new.read_bytes()).hexdigest() == "87696076cea84d4e93f172d07a1499755dbc647f396ff115a9d64571740b72a3"

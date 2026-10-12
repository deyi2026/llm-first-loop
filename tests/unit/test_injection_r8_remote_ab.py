from __future__ import annotations

import importlib.util
from pathlib import Path

from llm_loop.llm.errors import LLMEmptyResponseError, LLMHTTPError

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("r8_remote", ROOT / "scripts/injection_r8_remote_ab.py")
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _row(kind: str, *, completion: bool, dominance=None):
    return {
        "response": {"result_kind": kind},
        "score": {"completion": completion, "drift": False, "dominance": dominance},
        "structure": {"injection_share": 0.1, "hard_gate_pass": True},
    }


def test_empty_response_is_behavior_failure_not_transport() -> None:
    rec = mod._safe_error_record(LLMEmptyResponseError("empty"), 0.1)
    assert rec["result_kind"] == "empty_response"
    assert "status_code" not in rec


def test_http_error_is_sanitized_to_status_only() -> None:
    rec = mod._safe_error_record(
        LLMHTTPError("secret body", status_code=502, body="sensitive", provider="x"), 0.1
    )
    assert rec == {
        "result_kind": "http_error",
        "error_type": "LLMHTTPError",
        "status_code": 502,
        "elapsed_s": 0.1,
    }


def test_transport_failure_forces_unknown() -> None:
    rows = [_row("answer", completion=True, dominance=True) for _ in range(5)]
    rows.append(_row("http_error", completion=False, dominance=None))
    result = {
        "A": rows,
        "aggregate_A": {
            "completion_rate": 0.8333,
            "drift_rate": 0.0,
            "user_dominance_rate": 1.0,
        },
    }
    assert mod._classification(result)["tier"] == "unknown"


def test_behavioral_a_arm_never_classifies_weak() -> None:
    rows = [
        _row("answer", completion=True, dominance=True),
        _row("answer", completion=True, dominance=None),
        _row("empty_response", completion=False, dominance=False),
        _row("answer", completion=True, dominance=False),
        _row("answer", completion=True, dominance=None),
        _row("answer", completion=True, dominance=None),
    ]
    result = {
        "A": rows,
        "aggregate_A": {
            "completion_rate": 0.8333,
            "drift_rate": 0.0,
            "user_dominance_rate": 0.5,
        },
    }
    classified = mod._classification(result)
    assert classified["tier"] == "unknown"
    assert classified["reason"] == "legacy_r7_not_capability_authority"
    assert classified["legacy_resilience"]["completion_rate"] == 0.8333


def test_perfect_a_arm_never_classifies_strong() -> None:
    rows = [_row("answer", completion=True, dominance=True) for _ in range(6)]
    result = {
        "A": rows,
        "aggregate_A": {
            "completion_rate": 1.0,
            "drift_rate": 0.0,
            "user_dominance_rate": 1.0,
        },
    }
    classified = mod._classification(result)
    assert classified["tier"] == "unknown"
    assert classified["reason"] == "legacy_r7_not_capability_authority"

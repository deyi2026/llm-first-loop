"""M1 paired USD gate: no grant, unknown bill or exceeded reserve => HOLD."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from llm_loop.embodied_sim.paired_budget import (
    BATCH_USD_LIMIT,
    CALL_RESERVE_USD_LIMIT,
    PairedCostGate,
    PairedCostHold,
    validate_plan,
)
from llm_loop.embodied_sim.usage import extract_usage


def _plan(tmp_path: Path) -> dict:
    now = datetime.now(UTC)
    return {
        "schema": "lfl.m1-paired-cost-grant/v1",
        "batch_id": "a" * 32,
        "experiment_id": "M1-SIM-003",
        "prereg_sha256": "b" * 64,
        "candidate_sha": "c" * 40,
        "model": "deepseek/deepseek-v4-flash",
        "currency": "USD",
        "max_episodes": 60,
        "max_provider_attempts": 360,
        "max_tool_actions": 480,
        "max_total_usd": "0.01000000",
        "reserve_per_call_usd": "0.00400000",
        "input_per_million_usd": "1",
        "output_per_million_usd": "2",
        "pricing_source": "operator-approved provider contract ref",
        "pricing_checked_at_utc": (now - timedelta(minutes=1)).isoformat(),
        "expires_at_utc": (now + timedelta(hours=1)).isoformat(),
        "ledger_path": str(tmp_path / "m1-paired-cost-ledger.jsonl"),
    }


def _usage() -> dict:
    return extract_usage({"prompt_tokens": 1000, "completion_tokens": 500,
                          "total_tokens": 1500})


def test_valid_plan_requires_exact_frozen_limits_and_tariff(tmp_path):
    plan = _plan(tmp_path)
    assert validate_plan(plan, prereg_sha="b" * 64, candidate_sha="c" * 40) == plan
    assert BATCH_USD_LIMIT == 20
    assert Decimal("0.05") == CALL_RESERVE_USD_LIMIT
    assert validate_plan(
        {**plan, "max_total_usd": "20.00", "reserve_per_call_usd": "0.05",
         "input_per_million_usd": "0.30", "output_per_million_usd": "1.20"},
        prereg_sha="b" * 64, candidate_sha="c" * 40,
    )
    for key, bad in (("model", "another"), ("max_episodes", 61),
                     ("max_provider_attempts", 361), ("max_tool_actions", 481),
                     ("max_total_usd", "NaN"), ("input_per_million_usd", "NaN"),
                     ("max_total_usd", "20.01"), ("reserve_per_call_usd", "0.05000001"),
                     ("input_per_million_usd", "0.299"),
                     ("output_per_million_usd", "1.199"),
                     ("pricing_source", ""), ("candidate_sha", "d" * 40)):
        changed = {**plan, key: bad}
        with pytest.raises(PairedCostHold):
            validate_plan(changed, prereg_sha="b" * 64, candidate_sha="c" * 40)
    with pytest.raises(PairedCostHold):
        validate_plan({**plan, "extra": 1}, prereg_sha="b" * 64,
                      candidate_sha="c" * 40)


def test_expired_or_unqualified_tariff_cannot_authorize(tmp_path):
    plan = _plan(tmp_path)
    with pytest.raises(PairedCostHold, match="GRANT_EXPIRED"):
        validate_plan(plan, prereg_sha="b" * 64, candidate_sha="c" * 40,
                      now=datetime.now(UTC) + timedelta(days=2))


def test_reservation_and_usd_stop_are_durable(tmp_path):
    plan = _plan(tmp_path)
    ledger = Path(plan["ledger_path"])
    trial = {"phase": "paired", "arm": "B2", "trial_index": 0, "seed": 20261117}
    gate = PairedCostGate(plan, ledger, "d" * 64, run_id="f" * 32, trial=trial)
    for _ in range(4):
        call_id = gate.reserve()
        gate.settle(call_id, _usage())
    assert len(ledger.read_text().splitlines()) == 8
    first = json.loads(ledger.read_text().splitlines()[0])
    assert first["run_id"] == "f" * 32 and first["trial"] == trial
    with pytest.raises(PairedCostHold, match="TOTAL_USD_STOP_THRESHOLD"):
        gate.reserve()
    assert "public observation" not in ledger.read_text()


def test_pending_or_unknown_attempt_prevents_next_provider_call(tmp_path):
    plan = _plan(tmp_path)
    gate = PairedCostGate(plan, Path(plan["ledger_path"]), "d" * 64)
    call_id = gate.reserve()
    with pytest.raises(PairedCostHold, match="UNSETTLED_PROVIDER_ATTEMPT"):
        gate.reserve()
    gate.mark_unknown(call_id)
    with pytest.raises(PairedCostHold, match="UNRECONCILED_PROVIDER_BILLING"):
        gate.reserve()


def test_missing_usage_and_over_reserve_fail_closed(tmp_path):
    plan = _plan(tmp_path)
    gate = PairedCostGate(plan, Path(plan["ledger_path"]), "d" * 64)
    call_id = gate.reserve()
    with pytest.raises(PairedCostHold, match="PROVIDER_COST_UNKNOWN"):
        gate.settle(call_id, extract_usage(None))
    with pytest.raises(PairedCostHold, match="UNRECONCILED"):
        gate.reserve()

    other = _plan(tmp_path / "other")
    other["reserve_per_call_usd"] = "0.001"
    second = PairedCostGate(other, Path(other["ledger_path"]), "e" * 64)
    call_id = second.reserve()
    with pytest.raises(PairedCostHold, match="PROVIDER_COST_UNKNOWN"):
        second.settle(call_id, _usage())


def test_attempt_cap_and_corrupt_ledger_are_hard_stops(tmp_path):
    plan = _plan(tmp_path)
    plan["max_provider_attempts"] = 1
    ledger = Path(plan["ledger_path"])
    gate = PairedCostGate(plan, ledger, "d" * 64)
    gate.settle(gate.reserve(), _usage())
    with pytest.raises(PairedCostHold, match="PROVIDER_ATTEMPT_CAP"):
        gate.reserve()
    different_grant = PairedCostGate(plan, ledger, "e" * 64)
    with pytest.raises(PairedCostHold, match="COST_LEDGER_CORRUPT"):
        different_grant.reserve()
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    events[1]["estimated_usd"] = "0.00000000"
    ledger.write_text("".join(json.dumps(event) + "\n" for event in events))
    with pytest.raises(PairedCostHold, match="COST_LEDGER_CORRUPT"):
        gate.reserve()

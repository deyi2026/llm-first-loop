"""Frozen P4-LIVE ActionRef RED-only qualification tests.

These tests are intentionally RED on protocol base e946eab26032.  The first
assertion in each case guarantees that the failure is the frozen production-gap
taxonomy rather than an import/setup/harness failure.  The second assertion is the
actual RED contract and must fail until a later, separately authorized production
GREEN phase implements that specific capability.
"""

from __future__ import annotations

import pytest

from evals.smc_semantic_logic_p4_live.red_contracts import (
    RED_IDS,
    load_expected_failures,
    run_probe,
)

EXPECTED = load_expected_failures()


@pytest.mark.parametrize("row_id", RED_IDS, ids=RED_IDS)
def test_p4_live_actionref_contract_red(row_id: str) -> None:
    probe = run_probe(row_id)
    expected = EXPECTED[row_id]

    assert probe.failure_code == expected["code"], (
        f"{row_id} RED taxonomy mismatch: expected={expected['code']} "
        f"observed={probe.failure_code}; detail={probe.detail}; facts={probe.facts}"
    )
    assert probe.contract_satisfied, (
        f"{row_id}|{probe.failure_code}|EXPECTED_PRODUCTION_CAPABILITY_MISSING|"
        f"{probe.detail}|facts={probe.facts}"
    )

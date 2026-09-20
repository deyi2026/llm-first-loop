"""Expected-RED qualification for P4-LIVE GREEN-2 slice G2-S2."""

from __future__ import annotations

import pytest

from evals.smc_semantic_logic_p4_live.green2_s2_red_contracts import (
    S2_RED_IDS,
    load_expected_failures,
    run_probe,
)

EXPECTED = load_expected_failures()


@pytest.mark.parametrize("row_id", S2_RED_IDS, ids=S2_RED_IDS)
def test_p4_live_g2_s2_contract_is_exact_expected_red(row_id: str) -> None:
    probe = run_probe(row_id)
    expected = EXPECTED[row_id]
    assert probe.failure_code != "harness_error", (
        f"{row_id} harness failure cannot qualify RED: {probe.detail}; facts={probe.facts}"
    )
    assert probe.failure_code == expected["code"], (
        f"{row_id} RED taxonomy mismatch: expected={expected['code']} "
        f"observed={probe.failure_code}; detail={probe.detail}; facts={probe.facts}"
    )
    assert not probe.contract_satisfied, (
        f"{row_id} unexpectedly GREEN before authorized S2 production implementation; "
        f"facts={probe.facts}"
    )

"""P4-LIVE ActionRef staged qualification over the frozen RED matrix.

GREEN Phase 1 is deliberately narrow: R01-R09/R20 must be satisfied by a
non-dispatching production core, while R10-R19 must remain RED for the exact frozen
production-gap taxonomy.  This makes accidental execution-bridge/provider-surface
scope creep visible immediately.
"""

from __future__ import annotations

import pytest

from evals.smc_semantic_logic_p4_live.red_contracts import (
    PHASE1_GREEN_IDS,
    RED_IDS,
    load_expected_failures,
    run_probe,
)

EXPECTED = load_expected_failures()


@pytest.mark.parametrize("row_id", RED_IDS, ids=RED_IDS)
def test_p4_live_actionref_contract_red(row_id: str) -> None:
    probe = run_probe(row_id)
    expected = EXPECTED[row_id]

    if row_id in PHASE1_GREEN_IDS:
        assert probe.failure_code == "contract_present", (
            f"{row_id} Phase-1 GREEN missing: observed={probe.failure_code}; "
            f"detail={probe.detail}; facts={probe.facts}"
        )
        assert probe.contract_satisfied, (
            f"{row_id}|{probe.failure_code}|EXPECTED_PHASE1_GREEN|"
            f"{probe.detail}|facts={probe.facts}"
        )
        return

    assert probe.failure_code == expected["code"], (
        f"{row_id} RED taxonomy mismatch: expected={expected['code']} "
        f"observed={probe.failure_code}; detail={probe.detail}; facts={probe.facts}"
    )
    assert not probe.contract_satisfied, (
        f"{row_id}|UNEXPECTED_GREEN_BEYOND_PHASE1|{probe.detail}|facts={probe.facts}"
    )

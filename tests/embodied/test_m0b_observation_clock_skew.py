"""Reviewer P1 closure: observation TTL must fail closed on clock rollback."""

from __future__ import annotations

import pytest
from stubs import DeniedError, SimClock, StubExecutor, StubOracle


@pytest.mark.parametrize("untrusted_now", [99.0, float("nan"), float("inf")])
def test_observation_clock_rollback_and_nonfinite_fail_closed(
    side_effect_sentinel, untrusted_now,
):
    """M0-G5/AT-05: negative or nonfinite observation age is never fresh."""
    clock, oracle = SimClock(now_ms=100), StubOracle()
    ex = StubExecutor(clock, oracle)
    grant, obs = ex.issue_grant(), ex.observe()
    clock.now_ms = untrusted_now
    with pytest.raises(DeniedError, match="OBSERVATION_CLOCK_SKEW"):
        ex.execute_skill(
            grant_version=grant, scene_epoch=oracle.scene_epoch,
            observation_ref=obs.observation_ref, intent_key="skewed",
            semantic_fingerprint="pick-red", skill="pick", params={"target_id": "cube-red"},
        )
    assert ex.executed_count == 0
    assert oracle.verify() is False

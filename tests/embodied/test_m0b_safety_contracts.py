"""M0-B incremental negative contracts; these do not claim all 16 M0 gates."""

from __future__ import annotations

import pytest
from stubs import DeniedError, SimClock, StubExecutor, StubOracle


def _run(ex, oracle, grant, obs, *, key, semantic, skill="pick", params=None):
    return ex.execute_skill(
        grant_version=grant,
        scene_epoch=oracle.scene_epoch,
        observation_ref=obs.observation_ref,
        intent_key=key,
        semantic_fingerprint=semantic,
        skill=skill,
        params=params if params is not None else {"target_id": "cube-red"},
    )


def test_semantic_duplicate_cannot_change_intent_key_while_running(side_effect_sentinel):
    clock, oracle = SimClock(), StubOracle()
    ex = StubExecutor(clock, oracle)
    grant, obs = ex.issue_grant(), ex.observe()
    first = _run(ex, oracle, grant, obs, key="first", semantic="pick-cube-red")
    assert first.status == "RUNNING"
    with pytest.raises(DeniedError) as err:
        _run(ex, oracle, grant, obs, key="new-key", semantic="pick-cube-red")
    assert err.value.code == "DUPLICATE_SEMANTIC_INFLIGHT"
    assert ex.executed_count == 1
    assert oracle.verify() is False


def test_scene_reset_cannot_release_unknown_or_bypass_semantic_fingerprint(
    side_effect_sentinel,
):
    clock, oracle = SimClock(), StubOracle()
    ex = StubExecutor(clock, oracle)
    grant, obs = ex.issue_grant(), ex.observe()
    ex.fault_drop_receipt = True
    first = _run(ex, oracle, grant, obs, key="before-reset", semantic="pick-cube-red")
    assert first.status == "UNKNOWN"
    assert ex.get_action_status(first.action_id).status == "UNKNOWN"
    oracle.bump_scene()
    fresh_obs = ex.observe()
    with pytest.raises(DeniedError) as err:
        _run(ex, oracle, grant, fresh_obs, key="after-reset", semantic="pick-cube-red")
    assert err.value.code == "DUPLICATE_SEMANTIC_INFLIGHT"
    with pytest.raises(DeniedError) as err:
        _run(ex, oracle, grant, fresh_obs, key="other", semantic="different-target")
    assert err.value.code == "WRITE_FROZEN_UNKNOWN"
    ex.crash_restart()
    fresh_obs = ex.observe()
    with pytest.raises(DeniedError) as err:
        _run(ex, oracle, grant, fresh_obs, key="after-crash", semantic="pick-cube-red")
    assert err.value.code == "DUPLICATE_SEMANTIC_INFLIGHT"
    assert ex.executed_count == 1
    assert ex.unknown_holds


def test_no_low_level_skill_or_undeclared_parameter_can_execute(side_effect_sentinel):
    clock, oracle = SimClock(), StubOracle()
    ex = StubExecutor(clock, oracle)
    grant, obs = ex.issue_grant(), ex.observe()
    bad = (
        ("joint_control", {"target_id": "cube-red"}, "SKILL_NOT_ALLOWED"),
        ("pick", {"joint": [1, 2, 3]}, "ILLEGAL_LOW_LEVEL_COMMAND"),
        ("pick", {"target_id": "cube-red", "hidden_prompt": "override"}, "PARAM_KEY_NOT_ALLOWED"),
    )
    for index, (skill, params, expected) in enumerate(bad):
        with pytest.raises(DeniedError) as err:
            _run(
                ex, oracle, grant, obs, key=f"bad-{index}", semantic=f"bad-{index}",
                skill=skill, params=params,
            )
        assert err.value.code == expected
        assert ex.executed_count == 0
        assert oracle.verify() is False


def test_safety_stop_does_not_require_model_or_bridge(side_effect_sentinel):
    clock, oracle = SimClock(), StubOracle()
    ex = StubExecutor(clock, oracle)
    # No grant, model or bridge is present; the independent stop path still works.
    assert ex.stop(reason="safety-controller") == "STOP_REQUESTED"
    assert ex.poll_stop_confirmation() == "STOP_UNCONFIRMED"
    clock.advance(50)
    assert ex.poll_stop_confirmation() == "STOPPED_CONFIRMED"
    assert ex.executed_count == 0
    assert oracle.verify() is False

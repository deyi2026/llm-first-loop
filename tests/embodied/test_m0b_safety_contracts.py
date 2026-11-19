"""M0-B incremental negative contracts; these do not claim all 16 M0 gates."""

from __future__ import annotations

import pytest
from stubs import (
    DeniedError,
    ReconcileProof,
    SimClock,
    StubExecutor,
    StubOracle,
    TrustedReconcileAuthority,
)


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
    assert ex.poll_stop_confirmation(motion_mm_s=0.0, pose_delta_mm=0.0) == "STOP_UNCONFIRMED"
    clock.advance(50)
    assert ex.poll_stop_confirmation(motion_mm_s=0.0, pose_delta_mm=0.0) == "STOPPED_CONFIRMED"
    assert ex.executed_count == 0
    assert oracle.verify() is False


def test_grant_freshness_half_open_partition_and_reconfirmation(side_effect_sentinel):
    """AT-21c: local monotonic age at max-1 passes, at max fails closed."""
    clock, oracle = SimClock(), StubOracle()
    ex = StubExecutor(clock, oracle, max_grant_epoch_age_ms=1000)
    grant = ex.issue_grant()
    ex.set_host_connected(False)
    clock.advance(999)
    obs = ex.observe()
    first = _run(ex, oracle, grant, obs, key="fresh", semantic="pick-red")
    assert first.status == "RUNNING"
    assert ex.executed_count == 1

    clock.advance(1)
    obs2 = ex.observe()
    with pytest.raises(DeniedError) as err:
        _run(ex, oracle, grant, obs2, key="expired", semantic="place-goal", skill="place", params={"tray_id": "tray-A"})
    assert err.value.code == "GRANT_EPOCH_UNVERIFIED"
    assert ex.executed_count == 1
    with pytest.raises(DeniedError) as err:
        ex.refresh_grant_epoch(grant, host_verified=True)  # disconnected
    assert err.value.code == "GRANT_REFRESH_UNVERIFIED"

    ex.set_host_connected(True)
    with pytest.raises(DeniedError) as err:
        _run(ex, oracle, grant, obs2, key="reconnect-not-enough", semantic="place-goal", skill="place", params={"tray_id": "tray-A"})
    assert err.value.code == "GRANT_EPOCH_UNVERIFIED"
    with pytest.raises(DeniedError) as err:
        ex.refresh_grant_epoch(grant, host_verified=False)
    assert err.value.code == "GRANT_REFRESH_UNVERIFIED"
    ex.refresh_grant_epoch(grant, host_verified=True)
    accepted = _run(ex, oracle, grant, obs2, key="reconfirmed", semantic="place-goal", skill="place", params={"tray_id": "tray-A"})
    assert accepted.status == "RUNNING"
    assert ex.executed_count == 2


def test_grant_negative_age_wake_and_restart_fail_closed(side_effect_sentinel):
    clock, oracle = SimClock(now_ms=100), StubOracle()
    ex = StubExecutor(clock, oracle, max_grant_epoch_age_ms=1000)
    grant = ex.issue_grant()
    clock.now_ms = 99  # injected clock rollback; no wall-clock dependence
    obs = ex.observe()
    with pytest.raises(DeniedError) as err:
        _run(ex, oracle, grant, obs, key="rollback", semantic="pick-red")
    assert err.value.code == "GRANT_EPOCH_UNVERIFIED"
    assert ex.executed_count == 0
    ex.refresh_grant_epoch(grant, host_verified=True)
    ex.mark_wake_clock_untrusted()  # simulated sleep/wake: age may look fresh
    with pytest.raises(DeniedError) as err:
        _run(ex, oracle, grant, obs, key="woke", semantic="pick-red")
    assert err.value.code == "GRANT_EPOCH_UNVERIFIED"
    ex.refresh_grant_epoch(grant, host_verified=True)
    first = _run(ex, oracle, grant, obs, key="new", semantic="pick-red")
    assert first.status == "RUNNING"
    ex.crash_restart()
    assert ex.get_action_status(first.action_id).status == "INTERRUPTED"
    obs2 = ex.observe()
    with pytest.raises(DeniedError) as err:
        _run(ex, oracle, grant, obs2, key="old-after-restart", semantic="place-goal", skill="place", params={"tray_id": "tray-A"})
    assert err.value.code == "GRANT_STALE"
    assert ex.executed_count == 1


def test_stop_requires_zero_motion_evidence_not_only_elapsed_time(side_effect_sentinel):
    """AT-09d: moving, NaN and insufficient samples cannot confirm physical stop."""
    clock, oracle = SimClock(), StubOracle()
    ex = StubExecutor(clock, oracle)
    assert ex.stop(reason="safety-controller") == "STOP_REQUESTED"
    assert ex.stop_boundary_at_ms == ex.stop_requested_at_ms == 0.0
    assert ex.poll_stop_confirmation() == "STOP_UNCONFIRMED"
    clock.advance(50)
    assert ex.poll_stop_confirmation() == "STOP_UNCONFIRMED"
    assert ex.stop_evidence_ref is None
    assert ex.poll_stop_confirmation(motion_mm_s=5.0) == "STOP_UNCONFIRMED"
    clock.advance(50)
    assert ex.poll_stop_confirmation(pose_delta_mm=2.0) == "STOP_UNCONFIRMED"
    clock.advance(50)
    assert ex.poll_stop_confirmation(motion_mm_s=float("nan")) == "STOP_UNCONFIRMED"
    clock.advance(50)
    assert ex.poll_stop_confirmation(motion_mm_s=0.0, pose_delta_mm=0.0) == "STOP_UNCONFIRMED"
    assert ex.stop_evidence_ref is None
    clock.advance(50)
    assert ex.poll_stop_confirmation(motion_mm_s=0.0, pose_delta_mm=0.0) == "STOPPED_CONFIRMED"
    assert ex.stop_confirmed_at_ms == 250.0
    assert ex.stop_evidence_ref == "ev:stop:250.0:zero_motion"
    assert ex.executed_count == 0
    assert oracle.verify() is False


def test_stop_timeout_stays_unconfirmed_even_if_late_motion_zero(side_effect_sentinel):
    clock, oracle = SimClock(), StubOracle()
    ex = StubExecutor(clock, oracle)
    ex.stop()
    assert ex.poll_stop_confirmation(motion_mm_s=3.0) == "STOP_UNCONFIRMED"
    clock.advance(600)
    assert ex.poll_stop_confirmation(motion_mm_s=0.0) == "STOP_UNCONFIRMED"
    clock.advance(50)
    assert ex.poll_stop_confirmation(motion_mm_s=0.0) == "STOP_UNCONFIRMED"
    assert ex.stop_confirmed_at_ms is None
    assert ex.stop_evidence_ref is None
    assert ex.executed_count == 0


def test_unknown_reconcile_poll_limit_expiry_scope_and_replay(side_effect_sentinel):
    """AT-07: N=3 escalates; expired/cross-scope/replayed tokens cannot release."""
    clock, oracle = SimClock(), StubOracle()
    authority = TrustedReconcileAuthority()
    ex = StubExecutor(clock, oracle, reconcile_authority=authority)
    grant, obs = ex.issue_grant(), ex.observe()
    ex.fault_drop_receipt = True
    receipt = _run(ex, oracle, grant, obs, key="unknown", semantic="pick-red")
    assert receipt.status == "UNKNOWN"
    assert ex.get_action_status(receipt.action_id).status == "UNKNOWN"
    assert [ex.poll_reconcile_status("unknown") for _ in range(4)] == [
        "UNKNOWN", "UNKNOWN", "HUMAN_REQUIRED", "HUMAN_REQUIRED",
    ]
    entry = ex.ledger[receipt.action_id]
    expired = authority.attest(
        entry, resolved_by="trusted_ledger", terminal_status="SUCCEEDED",
        evidence_ref="trusted_ledger:expired", now_ms=clock.now_ms, ttl_ms=100,
    )
    clock.advance(100)
    with pytest.raises(DeniedError) as err:
        ex.reconcile_unknown("unknown", proof=expired, release=True)
    assert err.value.code == "RECONCILE_PROOF_INVALID"
    assert ex.unknown_holds and ex.executed_count == 1
    valid = authority.attest(
        entry, resolved_by="human", terminal_status="SUCCEEDED",
        evidence_ref="human:operator-confirmed", now_ms=clock.now_ms,
    )
    forged_cross_epoch = ReconcileProof(
        valid.action_id, valid.intent_key, valid.resolved_by, valid.terminal_status,
        valid.evidence_ref, valid.scene_epoch + 1, valid.grant_version,
        valid.expires_at_ms,
    )
    with pytest.raises(DeniedError) as err:
        ex.reconcile_unknown("unknown", proof=forged_cross_epoch, release=True)
    assert err.value.code == "RECONCILE_PROOF_INVALID"
    with pytest.raises(DeniedError) as err:
        ex.reconcile_unknown("unknown", proof=valid, release=False)
    assert err.value.code == "RECONCILE_HOLD_REQUIRED"
    ex.reconcile_unknown("unknown", proof=valid, release=True)
    assert ex.ledger[receipt.action_id].resolved_by == "human"
    assert not ex.unknown_holds
    with pytest.raises(DeniedError):
        ex.reconcile_unknown("unknown", proof=valid, release=True)
    assert ex.executed_count == 1

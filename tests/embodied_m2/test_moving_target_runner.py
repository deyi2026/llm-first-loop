"""M2: run_episode must bind claims to the CURRENT target, never a cached one.

Every scenario is a deterministic fault injection over a scripted world. On the
pre-M2 runner each test failed: `tray_pos` was cached once before the loop and
every later claim was judged against that first pose.
"""
from __future__ import annotations

import pytest

from embodied_m2.harness import FakeIface, FakeScene, ScriptedProvider, decision
from llm_loop.embodied_sim.episode import EpisodeBudget, run_episode

BUDGET = EpisodeBudget(max_provider_attempts=8, max_tool_actions=8, deadline_s=60.0)


def _events(result: dict) -> list[str]:
    return [e["event"] for e in result["trace"]]


def _move_to_tray(scene: FakeScene, *, z: float = 0.12) -> str:
    return decision("move_to", "move-tray", x=scene.tray[0], y=scene.tray[1], z=z)


def test_target_moving_while_the_model_decides_binds_the_claim_to_the_new_pose() -> None:
    scene = FakeScene()
    iface = FakeIface(scene)

    def move_world(_state: str) -> str:
        scene.move_tray(0.08)  # external agent moves the target between decisions
        return _move_to_tray(scene)

    provider = ScriptedProvider([("grasp", {}), move_world, ("release", {})])
    result = run_episode(iface, provider, BUDGET)

    assert "GOAL_CHANGED_MID_ACTION" in _events(result)
    assert result["goal_rebinds"] == 1
    assert result["terminated_by"] == "place_verified_locally_pending_oracle"
    assert result["local_verdict"]["ok"] is True
    assert result["oracle_receipt"]["goal"]["pos"][0] == pytest.approx(0.08)
    assert result["oracle_receipt"]["goal"]["digest"] == result["goal"]["digest"]


def test_target_moving_during_an_action_invalidates_that_actions_evidence() -> None:
    scene = FakeScene()
    iface = FakeIface(scene)
    fired = {"done": False}

    def on_advance(_iface: FakeIface) -> None:
        if not fired["done"] and _iface.advance_calls == 2:
            fired["done"] = True
            scene.move_tray(0.07)  # target moves while the 2nd action executes

    iface.on_advance = on_advance
    provider = ScriptedProvider([("grasp", {}),
                                 ("move_to", {"x": 0.0, "y": 0.18, "z": 0.12}),
                                 ("release", {})])
    result = run_episode(iface, provider, BUDGET)

    assert "GOAL_CHANGED_MID_ACTION" in _events(result)
    assert result["stale_evidence_invalidated"] >= 1
    assert result["terminated_by"] == "place_verified_locally_pending_oracle"
    assert result["oracle_receipt"]["goal"]["pos"][0] == pytest.approx(0.07)
    # The voided action stays visible, but is attributed to the goal it RAN
    # against — never to the rebound goal whose evidence it cannot support.
    voided = [e for e in result["trace"]
              if e.get("event") == "tool_action" and e.get("stale_goal")]
    assert voided, "the action voided by the mid-action move must stay visible"
    assert all(e["goal_version"] < result["goal_version"] for e in voided)
    assert all(e["goal_digest"] != result["goal"]["digest"] for e in voided)


def test_target_moving_while_the_release_settles_replans_before_verification() -> None:
    """The settle window after `release` belongs to no action: only `verify()`
    re-observes there. Before the fix this path crashed instead of replanning.
    """
    scene = FakeScene()
    iface = FakeIface(scene)
    fired = {"done": False}

    def on_step(step_scene: FakeScene, _n: int) -> None:
        if not fired["done"] and step_scene.placed:
            fired["done"] = True
            step_scene.move_tray(0.06)  # external actor moves the target while the object settles

    scene.on_step = on_step
    moves = {"n": 0}

    def move_to_now(_state: str) -> str:
        moves["n"] += 1
        return decision("move_to", f"move-{moves['n']}", x=scene.tray[0], y=scene.tray[1], z=0.12)

    provider = ScriptedProvider([("grasp", {}), move_to_now, ("release", {}),
                                 move_to_now, ("release", {})])
    result = run_episode(iface, provider, BUDGET)

    assert "GOAL_CHANGED_BEFORE_VERIFICATION" in _events(result)
    assert result["goal_rebinds"] == 1
    assert result["terminated_by"] == "place_verified_locally_pending_oracle"
    assert result["oracle_receipt"]["goal"]["pos"][0] == pytest.approx(0.06)


def test_tool_action_trace_keeps_execution_timing() -> None:
    """M1 emitted `t_s` on every tool_action trace event; M2 must not drop it."""
    scene = FakeScene()
    iface = FakeIface(scene)
    provider = ScriptedProvider([("grasp", {}), lambda _s: _move_to_tray(scene),
                                 ("release", {})])
    result = run_episode(iface, provider, BUDGET)

    actions = [e for e in result["trace"] if e.get("event") == "tool_action"]
    assert actions
    assert all("t_s" in e and e["t_s"] >= 0 for e in actions)


def test_target_moving_out_of_band_between_actions_is_detected_before_planning() -> None:
    scene = FakeScene()
    iface = FakeIface(scene)

    def arm(_state: str) -> str:
        # the world moves 3 observations later: the loop-top check of the next
        # decision, i.e. after the previous action was verified and before the
        # model is asked to plan again.
        scene.arm_move_after(3, 0.05)
        return decision("grasp", "grasp-1")

    provider = ScriptedProvider([arm, lambda _s: _move_to_tray(scene), ("release", {})])
    result = run_episode(iface, provider, BUDGET)

    assert "GOAL_CHANGED_BETWEEN_ACTIONS" in _events(result)
    assert result["goal_rebinds"] == 1
    assert result["terminated_by"] == "place_verified_locally_pending_oracle"
    assert result["oracle_receipt"]["goal"]["pos"][0] == pytest.approx(0.05)


def test_scene_reset_mid_episode_voids_prior_evidence_and_rebinds() -> None:
    scene = FakeScene()
    iface = FakeIface(scene)
    fired = {"done": False}

    def on_advance(_iface: FakeIface) -> None:
        if not fired["done"] and _iface.advance_calls == 2:
            fired["done"] = True
            scene.reset()  # epoch bump: every earlier observation is gone

    iface.on_advance = on_advance
    provider = ScriptedProvider([("grasp", {}), ("release", {}), ("grasp", {})])
    result = run_episode(iface, provider, BUDGET)

    assert "SCENE_RESET" in _events(result)
    assert result["goal_version"] >= 2
    assert result["stale_evidence_invalidated"] >= 1
    assert result["claim_state"] != "pending_oracle"
    assert result["oracle_receipt"]["scene_epoch"] == scene.scene_epoch


def test_duplicate_intent_after_target_moved_is_not_replayed_as_fresh() -> None:
    scene = FakeScene()
    iface = FakeIface(scene)
    iface.on_duplicate = lambda _iface: scene.move_tray(0.09)
    def dup(_state: str) -> str:
        return decision("move_to", "dup-key", x=0.0, y=0.18, z=0.12)

    provider = ScriptedProvider([("grasp", {}), dup, dup])
    result = run_episode(iface, provider, BUDGET)

    assert "DUPLICATE_INTENT_STALE_GOAL" in _events(result)
    assert result["stale_evidence_invalidated"] >= 1
    assert result["claim_state"] == "hold_unknown"
    assert (result["oracle_receipt"] or {}).get("verdict") != "success"


def test_indeterminate_execution_holds_unknown_instead_of_claiming() -> None:
    scene = FakeScene()
    fake_now = [0.0]
    iface = FakeIface(scene, clock=lambda: fake_now[0])
    iface.hold_actions = True
    iface.on_advance = lambda _iface: fake_now.__setitem__(0, fake_now[0] + 1000.0)
    provider = ScriptedProvider([("grasp", {})])
    result = run_episode(iface, provider, EpisodeBudget(deadline_s=1.0))

    assert result["terminated_by"] == "hold_unknown_pending_reconciliation"
    assert result["claim_state"] == "hold_unknown"
    assert result["oracle_receipt"] is None
    assert "HOLD_UNKNOWN" in _events(result)


def test_indeterminate_execution_dominates_a_concurrent_target_move() -> None:
    """Both faults in the same settle window: HOLD wins. An unreconciled action
    must never be replanned away and then covered by a later claim."""
    scene = FakeScene()
    fake_now = [0.0]
    iface = FakeIface(scene, clock=lambda: fake_now[0])
    iface.hold_actions = True

    def on_advance(_iface: FakeIface) -> None:
        scene.move_tray(0.05)      # the target moves...
        fake_now[0] += 1000.0      # ...and the settle window expires

    iface.on_advance = on_advance
    provider = ScriptedProvider([("grasp", {})])
    result = run_episode(iface, provider, EpisodeBudget(deadline_s=1.0))

    assert result["terminated_by"] == "hold_unknown_pending_reconciliation"
    assert result["claim_state"] == "hold_unknown"
    assert result["oracle_receipt"] is None
    assert result["goal_rebinds"] == 0, "an unresolved action must not be replanned away"


def test_replaying_a_voided_action_is_detected_as_stale_not_absorbed() -> None:
    """A voided action still binds to the goal it ran against, so replaying the
    same intent surfaces DUPLICATE_INTENT_STALE_GOAL instead of being absorbed."""
    scene = FakeScene()
    iface = FakeIface(scene)
    moved = {"done": False}

    def on_advance(_iface: FakeIface) -> None:
        if not moved["done"]:
            moved["done"] = True
            scene.move_tray(0.02)

    iface.on_advance = on_advance
    replay = decision("move_to", "move-once", x=0.0, y=0.18, z=0.12)
    provider = ScriptedProvider([lambda _s: replay, lambda _s: replay])
    result = run_episode(iface, provider, BUDGET)

    assert "GOAL_CHANGED_MID_ACTION" in _events(result)
    assert "DUPLICATE_INTENT_STALE_GOAL" in _events(result)
    assert result["goal_rebinds"] == 2


def test_goal_rebind_budget_bounds_a_continuously_moving_target() -> None:
    scene = FakeScene()
    iface = FakeIface(scene)
    iface.on_advance = lambda _iface: scene.move_tray(0.01)
    provider = ScriptedProvider([("move_to", {"x": 0.0, "y": 0.18, "z": 0.12})] * 10)
    result = run_episode(iface, provider, EpisodeBudget(
        max_provider_attempts=12, max_tool_actions=10, deadline_s=60.0, max_goal_rebinds=2))

    assert result["terminated_by"] == "goal_rebind_budget_exhausted"
    assert result["claim_state"] == "hold_unknown"
    assert result["goal_rebinds"] == 2
    assert result["oracle_receipt"] is None


def test_same_pose_after_a_scene_reset_cannot_replay_a_prior_intent() -> None:
    """The pose can survive a reset; the goal cannot. Replaying an intent recorded
    in the previous epoch must surface as stale — a digest-only duplicate key misses
    it because the pose, and therefore the digest, is unchanged."""
    scene = FakeScene()
    iface = FakeIface(scene)
    reset = {"done": False}

    def on_advance(_iface: FakeIface) -> None:
        if not reset["done"]:
            reset["done"] = True
            scene.reset()  # same tray pose, new scene epoch

    iface.on_advance = on_advance
    replay = decision("move_to", "replay-key", x=0.0, y=0.18, z=0.12)
    provider = ScriptedProvider([lambda _s: replay, lambda _s: replay])
    result = run_episode(iface, provider, BUDGET)

    assert "SCENE_RESET" in _events(result)
    assert "DUPLICATE_INTENT_STALE_GOAL" in _events(result)
    assert result["goal_rebinds"] >= 1
    assert result["claim_state"] != "pending_oracle"

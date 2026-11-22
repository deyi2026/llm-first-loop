"""M2 goal binding: a claim is only valid for the goal it was observed against."""
from __future__ import annotations

import pytest

from embodied_m2.harness import FakeScene
from llm_loop.embodied_sim.contract import VerificationStatus
from llm_loop.embodied_sim.goal_binding import GOAL_KIND, bind_goal, goal_digest, same_goal
from llm_loop.embodied_sim.oracle import make_receipt, verify_receipt


def _receipt(scene: FakeScene, *, goal_pos: list[float] | None = None,
             epoch: int | None = None) -> dict:
    scene.placed = True
    snap = scene.oracle_snapshot()
    binding = bind_goal(scene, version=1)
    if goal_pos is not None:
        binding = bind_goal(scene, version=1)
        fields = binding.receipt_fields()
        fields["pos"] = list(goal_pos)
        fields["digest"] = goal_digest(GOAL_KIND, goal_pos)
        binding_fields = fields
    else:
        binding_fields = binding.receipt_fields()
    return make_receipt(snap, "place", True, {"inside_tray_xy": True}, "M2-T-001",
                        scene.scene_epoch if epoch is None else epoch,
                        goal_binding=binding_fields)


def test_goal_digest_changes_for_a_centimetre_move() -> None:
    old = goal_digest(GOAL_KIND, [0.0, 0.18, 0.01])
    new = goal_digest(GOAL_KIND, [0.08, 0.18, 0.01])
    assert old != new


def test_goal_digest_ignores_sub_micrometre_float_noise() -> None:
    a = goal_digest(GOAL_KIND, [0.0, 0.18, 0.01])
    b = goal_digest(GOAL_KIND, [1e-12, 0.18 + 1e-12, 0.01])
    assert a == b


def test_bind_goal_carries_epoch_and_version() -> None:
    scene = FakeScene()
    scene.scene_epoch = 4
    binding = bind_goal(scene, version=2)
    assert binding.scene_epoch == 4
    assert binding.version == 2
    assert binding.digest == goal_digest(GOAL_KIND, scene.tray)
    assert binding.receipt_fields()["digest"] == binding.digest


def test_same_goal_requires_matching_digest_and_epoch() -> None:
    scene = FakeScene()
    a = bind_goal(scene, version=1)
    b = bind_goal(scene, version=1)
    assert same_goal(a, b)
    scene.move_tray(0.08)
    c = bind_goal(scene, version=1)
    assert not same_goal(a, c)
    scene2 = FakeScene()
    d = bind_goal(scene2, version=1)
    scene2.scene_epoch += 1
    e = bind_goal(scene2, version=1)
    assert not same_goal(d, e)


def test_receipt_verifies_against_the_goal_it_was_observed_with() -> None:
    scene = FakeScene()
    receipt = _receipt(scene)
    digest = receipt["goal"]["digest"]
    assert verify_receipt(receipt, scene.scene_epoch, expected_goal_digest=digest) is VerificationStatus.PENDING_ORACLE


def test_receipt_bound_to_a_stale_goal_is_a_failed_claim() -> None:
    scene = FakeScene()
    receipt = _receipt(scene)
    scene.move_tray(0.08)
    current = goal_digest(GOAL_KIND, scene.tray)
    assert verify_receipt(receipt, scene.scene_epoch, expected_goal_digest=current) is VerificationStatus.FAILED_CLAIM


def test_receipt_without_goal_binding_is_failed_when_a_digest_is_required() -> None:
    scene = FakeScene()
    scene.placed = True
    snap = scene.oracle_snapshot()
    receipt = make_receipt(snap, "place", True, {}, "M2-T-002", scene.scene_epoch)
    assert verify_receipt(receipt, scene.scene_epoch,
                          expected_goal_digest=goal_digest(GOAL_KIND, scene.tray)) is VerificationStatus.FAILED_CLAIM


def test_tampered_goal_block_is_a_failed_claim() -> None:
    scene = FakeScene()
    receipt = _receipt(scene)
    receipt["goal"]["pos"] = [0.5, 0.5, 0.01]  # digest no longer matches pos
    assert verify_receipt(receipt, scene.scene_epoch,
                          expected_goal_digest=receipt["goal"]["digest"]) is VerificationStatus.FAILED_CLAIM


def test_stale_scene_epoch_still_trumps_goal_binding() -> None:
    scene = FakeScene()
    receipt = _receipt(scene)
    assert verify_receipt(receipt, scene.scene_epoch + 1,
                          expected_goal_digest=receipt["goal"]["digest"]) is VerificationStatus.FAILED_CLAIM


@pytest.mark.parametrize("bad", [{}, {"digest": "x"}, {"pos": [0.0, 0.18, 0.01]}])
def test_malformed_goal_block_is_failed_claim(bad: dict) -> None:
    scene = FakeScene()
    receipt = _receipt(scene)
    receipt["goal"] = bad
    assert verify_receipt(receipt, scene.scene_epoch, expected_goal_digest="anything") is VerificationStatus.FAILED_CLAIM


def test_tampered_goal_block_fails_even_without_an_expected_digest() -> None:
    """A caller that passes no expectation must not become a fail-open bypass."""
    scene = FakeScene()
    receipt = _receipt(scene)
    receipt["goal"]["pos"] = [0.5, 0.5, 0.01]  # digest no longer matches pos
    assert verify_receipt(receipt, scene.scene_epoch) is VerificationStatus.FAILED_CLAIM


def test_self_consistent_goal_block_without_expectation_stays_pending_oracle() -> None:
    scene = FakeScene()
    receipt = _receipt(scene)
    assert verify_receipt(receipt, scene.scene_epoch) is VerificationStatus.PENDING_ORACLE


def test_goal_block_epoch_must_agree_with_the_receipt() -> None:
    scene = FakeScene()
    receipt = _receipt(scene)
    receipt["goal"]["scene_epoch"] = scene.scene_epoch + 1
    assert verify_receipt(receipt, scene.scene_epoch) is VerificationStatus.FAILED_CLAIM


def test_judge_place_holds_when_the_receipt_names_another_actions_goal() -> None:
    """The self-check is not tautological: `executed` is the goal captured before
    the action completed, so a later rebind cannot lend its goal to older evidence."""
    from llm_loop.embodied_sim.episode import CLAIM_PENDING, EpisodeBudget, _GoalState

    scene = FakeScene()
    scene.placed = True  # a genuinely placed cube, so the judgement itself passes
    state = _GoalState(scene, EpisodeBudget())
    binding = state.goal

    state.judge_place(binding, "exp", executed=(binding.digest, binding.scene_epoch))
    assert state.claim_state == CLAIM_PENDING

    state.claim_state = "none"
    state.trace.clear()
    state.judge_place(binding, "exp", executed=("some-other-goal", binding.scene_epoch))
    assert state.claim_state != CLAIM_PENDING
    assert any(e.get("event") == "RECEIPT_GOAL_MISMATCH" for e in state.trace)

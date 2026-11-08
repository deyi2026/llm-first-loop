"""B1：awaiting_supervision 是只增边，且不能跳过执行直接成功。"""

from __future__ import annotations

from llm_loop.peer.models import SLOT_STATES
from llm_loop.peer.state import TASK_STATES, can_transition, is_terminal


def test_state_enum_includes_awaiting_supervision() -> None:
    assert "awaiting_supervision" in TASK_STATES
    assert not is_terminal("awaiting_supervision")


def test_submitted_can_pause_then_admit() -> None:
    assert can_transition("submitted", "awaiting_supervision")
    assert can_transition("awaiting_supervision", "admitted")


def test_waiting_cannot_jump_to_execution_or_success() -> None:
    assert not can_transition("awaiting_supervision", "running")
    assert not can_transition("awaiting_supervision", "succeeded")


def test_waiting_releases_executor_slot() -> None:
    """等待确认不占执行器并发名额；确认后 admit 会在副作用前重判一次。"""
    assert "awaiting_supervision" not in SLOT_STATES


def test_existing_edges_are_preserved() -> None:
    """只增边：改动前存在的迁移必须仍然合法（防退化）。"""
    preserved = [
        ("submitted", "admitted"),
        ("admitted", "queued"),
        ("queued", "running"),
        ("running", "succeeded"),
        ("running", "blocked"),
        ("blocked", "running"),
        ("running", "unknown_outcome"),
        ("unknown_outcome", "failed"),
        ("running", "cancelled"),
        ("submitted", "denied"),
    ]
    for src, dst in preserved:
        assert can_transition(src, dst), (src, dst)

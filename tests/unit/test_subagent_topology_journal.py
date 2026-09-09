from __future__ import annotations

from llm_loop.core.subagent_topology import SubAgentTopologyJournal
from llm_loop.event_log.store import EventStore


def test_latest_generation_fences_late_old_terminal(tmp_path) -> None:
    store = EventStore(tmp_path / "events", enabled=True)
    journal = SubAgentTopologyJournal(store)
    child = "subagent-fence"
    parent = "parent-fence"

    assert journal.linked(child_id=child, parent_id=parent, generation="g1", depth=0)
    assert journal.generation_started(
        child_id=child, parent_id=parent, generation="g1", owner_id="owner-1", depth=0
    )
    assert journal.generation_started(
        child_id=child, parent_id=parent, generation="g2", owner_id="owner-2", depth=0
    )
    assert (
        journal.terminal(
            child_id=child, parent_id=parent, generation="g1", depth=0, outcome="failed"
        )
        is False
    )
    state = journal.recover(child)
    assert state is not None
    assert state.generation == "g2"
    assert state.terminal is False

    assert (
        journal.terminal(
            child_id=child, parent_id=parent, generation="g2", depth=0, outcome="completed"
        )
        is True
    )
    state = journal.recover(child)
    assert state is not None
    assert state.generation == "g2"
    assert state.terminal is True
    assert state.outcome == "completed"


def test_generation_release_rejects_foreign_owner_and_is_idempotent(tmp_path) -> None:
    store = EventStore(tmp_path / "events", enabled=True)
    journal = SubAgentTopologyJournal(store)
    child = "subagent-owner"
    parent = "parent-owner"

    assert journal.linked(child_id=child, parent_id=parent, generation="g1", depth=1)
    assert journal.generation_started(
        child_id=child, parent_id=parent, generation="g1", owner_id="owner-a", depth=1
    )
    assert (
        journal.generation_released(
            child_id=child,
            parent_id=parent,
            generation="g1",
            owner_id="owner-b",
            depth=1,
            reason="worker_exit",
        )
        is False
    )
    assert (
        journal.generation_released(
            child_id=child,
            parent_id=parent,
            generation="g1",
            owner_id="owner-a",
            depth=1,
            reason="worker_exit",
        )
        is True
    )
    before = len(store.read(child))
    assert (
        journal.generation_released(
            child_id=child,
            parent_id=parent,
            generation="g1",
            owner_id="owner-a",
            depth=1,
            reason="worker_exit",
        )
        is True
    )
    assert len(store.read(child)) == before
    state = journal.recover(child)
    assert state is not None
    assert state.generation_released is True


def test_terminal_generation_cannot_restart_or_change_outcome(tmp_path) -> None:
    store = EventStore(tmp_path / "events", enabled=True)
    journal = SubAgentTopologyJournal(store)
    child = "subagent-terminal-fence"
    parent = "parent-terminal-fence"

    assert journal.linked(child_id=child, parent_id=parent, generation="g1", depth=0)
    assert journal.generation_started(
        child_id=child, parent_id=parent, generation="g1", owner_id="owner-a", depth=0
    )
    assert journal.terminal(
        child_id=child, parent_id=parent, generation="g1", depth=0, outcome="completed"
    )
    before = len(store.read(child))
    assert (
        journal.terminal(
            child_id=child, parent_id=parent, generation="g1", depth=0, outcome="completed"
        )
        is True
    )
    assert len(store.read(child)) == before
    assert (
        journal.terminal(
            child_id=child, parent_id=parent, generation="g1", depth=0, outcome="failed"
        )
        is False
    )
    assert (
        journal.generation_started(
            child_id=child, parent_id=parent, generation="g1", owner_id="owner-a", depth=0
        )
        is False
    )

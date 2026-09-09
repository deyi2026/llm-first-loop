from __future__ import annotations

import threading
import time

import pytest

from llm_loop.core.run_context import current_session_id
from llm_loop.core.session import SessionStore
from llm_loop.event_log.store import EventStore
from llm_loop.llm.client import LLMResponse
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.registry import ToolRegistry


class _BlockingLLM:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        self.entered.set()
        assert self.release.wait(timeout=5.0)
        return LLMResponse(content="child-done", tool_calls=[], provider="fake")


class _FinalLLM:
    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        return LLMResponse(content="child-done", tool_calls=[], provider="fake")


def _store(tmp_path) -> SessionStore:
    events = EventStore(tmp_path / "events", enabled=True)
    return SessionStore(tmp_path / "sessions", event_store=events)


def _runner(llm, store: SessionStore) -> SubAgentRunner:  # noqa: ANN001
    return SubAgentRunner(llm=llm, registry=ToolRegistry(), session_store=store)  # type: ignore[arg-type]


def _spawn(runner: SubAgentRunner, parent_id: str) -> dict:
    token = current_session_id.set(parent_id)
    try:
        return runner.start("inspect durable topology", depth=0)
    finally:
        current_session_id.reset(token)


def _wait_terminal(runner: SubAgentRunner, parent_id: str, child_id: str) -> dict:
    deadline = time.monotonic() + 5.0
    token = current_session_id.set(parent_id)
    try:
        while time.monotonic() < deadline:
            ok, _detail, snapshot = runner.result_current(child_id, wait_seconds=0.05)
            assert ok
            if snapshot.get("state") != "running":
                return snapshot
        raise AssertionError("child did not reach terminal state")
    finally:
        current_session_id.reset(token)


def test_restart_recovers_parent_edge_without_marking_orphan_active(tmp_path) -> None:
    store = _store(tmp_path)
    llm = _BlockingLLM()
    original = _runner(llm, store)
    started = _spawn(original, "parent-r1")
    assert started["accepted"] is True
    child_id = str(started["child_id"])
    assert llm.entered.wait(timeout=2.0)

    try:
        recovered = _runner(_FinalLLM(), store)
        assert recovered.parent_of(child_id) == "parent-r1"
        # Restart recovery is topology knowledge only: no Thread/Future/Event is fabricated.
        assert recovered.active_children("parent-r1") == []
        snapshot = recovered.topology_snapshot(child_id)
        assert snapshot is not None
        assert snapshot["child_id"] == child_id
        assert snapshot["parent_id"] == "parent-r1"
        assert snapshot["generation"]
        assert snapshot["owner_state"] == "orphaned"
        assert snapshot["local_active"] is False
        assert snapshot["terminal"] is False
        assert snapshot["settlement_state"] == "unknown"
        token = current_session_id.set("parent-r1")
        try:
            ok, detail, _target = recovered.send_current_message(child_id, "do not revive")
        finally:
            current_session_id.reset(token)
        assert ok is False
        assert "仍活跃" in detail
    finally:
        llm.release.set()
        _wait_terminal(original, "parent-r1", child_id)


def test_restart_recovers_terminal_known_without_fabricating_collection(tmp_path) -> None:
    store = _store(tmp_path)
    original = _runner(_FinalLLM(), store)
    started = _spawn(original, "parent-r2")
    assert started["accepted"] is True
    child_id = str(started["child_id"])
    terminal = _wait_terminal(original, "parent-r2", child_id)
    assert terminal["state"] == "completed"
    token = current_session_id.set("parent-r2")
    try:
        assert original.settle_current(child_id) is True
    finally:
        current_session_id.reset(token)

    recovered = _runner(_FinalLLM(), store)
    assert recovered.parent_of(child_id) == "parent-r2"
    assert recovered.active_children("parent-r2") == []
    snapshot = recovered.topology_snapshot(child_id)
    assert snapshot is not None
    assert snapshot["owner_state"] == "terminal_known"
    assert snapshot["terminal"] is True
    assert snapshot["outcome"] == "completed"
    # ST2-B knows topology/outcome only; parent settlement is ST2-C and remains unknown.
    assert snapshot["settlement_state"] == "unknown"


def test_spawn_persists_nonempty_generation_fact(tmp_path) -> None:
    store = _store(tmp_path)
    llm = _BlockingLLM()
    runner = _runner(llm, store)
    started = _spawn(runner, "parent-r3")
    assert started["accepted"] is True
    child_id = str(started["child_id"])
    assert llm.entered.wait(timeout=2.0)
    try:
        events = store.event_store.read(child_id) if store.event_store is not None else []
        started_events = [e for e in events if e.type == "subagent.generation.started"]
        assert len(started_events) == 1
        payload = started_events[0].payload
        assert payload["child_id"] == child_id
        assert payload["parent_id"] == "parent-r3"
        assert isinstance(payload["generation"], str) and payload["generation"]
    finally:
        llm.release.set()
        _wait_terminal(runner, "parent-r3", child_id)


def test_restart_ignores_stale_terminal_from_older_generation(tmp_path) -> None:
    store = _store(tmp_path)
    child_id = "subagent_manual_fence"
    parent_id = "parent-r4"
    sess = store.load(child_id)
    sess.parent_id = parent_id
    store.save(sess)
    events = store.event_store
    assert events is not None
    events.append(
        child_id,
        "subagent.linked",
        {"child_id": child_id, "parent_id": parent_id, "generation": "g1", "depth": 0},
    )
    events.append(
        child_id,
        "subagent.generation.started",
        {"child_id": child_id, "parent_id": parent_id, "generation": "g1", "depth": 0},
    )
    # A future owner/reclaim may create a newer generation for the same child id.
    events.append(
        child_id,
        "subagent.generation.started",
        {"child_id": child_id, "parent_id": parent_id, "generation": "g2", "depth": 0},
    )
    # Delayed old worker terminal must be fenced out by generation mismatch.
    events.append(
        child_id,
        "subagent.terminal",
        {
            "child_id": child_id,
            "parent_id": parent_id,
            "generation": "g1",
            "outcome": "failed",
            "depth": 0,
        },
    )

    recovered = _runner(_FinalLLM(), store)
    snapshot = recovered.topology_snapshot(child_id)
    assert snapshot is not None
    assert snapshot["parent_id"] == parent_id
    assert snapshot["generation"] == "g2"
    assert snapshot["owner_state"] == "orphaned"
    assert snapshot["terminal"] is False
    assert snapshot["outcome"] == ""


class _CountingLLM:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        self.calls += 1
        return LLMResponse(content="must-not-run", tool_calls=[], provider="fake")


class _FailTopologyEventStore(EventStore):
    def __init__(self, path, fail_type: str) -> None:  # noqa: ANN001
        super().__init__(path, enabled=True)
        self.fail_type = fail_type

    def append(self, session_id: str, event_type: str, payload: dict):  # noqa: ANN201
        if event_type == self.fail_type:
            return None
        return super().append(session_id, event_type, payload)


@pytest.mark.parametrize("fail_type", ["subagent.linked", "subagent.generation.started"])
def test_topology_start_wal_failure_prevents_provider_execution(tmp_path, fail_type: str) -> None:
    events = _FailTopologyEventStore(tmp_path / "events", fail_type)
    store = SessionStore(tmp_path / "sessions", event_store=events)
    llm = _CountingLLM()
    runner = _runner(llm, store)

    started = _spawn(runner, "parent-fail")

    assert started["accepted"] is False
    assert llm.calls == 0


def test_generation_release_and_terminal_share_spawn_generation(tmp_path) -> None:
    store = _store(tmp_path)
    runner = _runner(_FinalLLM(), store)
    started = _spawn(runner, "parent-seq")
    assert started["accepted"] is True
    child_id = str(started["child_id"])
    _wait_terminal(runner, "parent-seq", child_id)
    events = store.event_store
    assert events is not None
    topology = [event for event in events.read(child_id) if event.type.startswith("subagent.")]
    assert [event.type for event in topology] == [
        "subagent.linked",
        "subagent.generation.started",
        "subagent.result.available",
        "subagent.generation.released",
        "subagent.terminal",
    ]
    generations = {str(event.payload.get("generation") or "") for event in topology}
    assert len(generations) == 1
    assert next(iter(generations))


def test_legacy_parent_id_without_topology_events_is_not_guessed_as_recoverable(tmp_path) -> None:
    store = _store(tmp_path)
    child_id = "subagent_legacy_only"
    sess = store.load(child_id)
    sess.parent_id = "parent-legacy"
    store.save(sess)

    recovered = _runner(_FinalLLM(), store)

    assert recovered.parent_of(child_id) == ""
    assert recovered.topology_snapshot(child_id) is None


def test_restart_topology_rebuild_is_read_only(tmp_path) -> None:
    store = _store(tmp_path)
    original = _runner(_FinalLLM(), store)
    started = _spawn(original, "parent-readonly")
    child_id = str(started["child_id"])
    _wait_terminal(original, "parent-readonly", child_id)
    events = store.event_store
    assert events is not None
    before = [(e.seq, e.type, dict(e.payload)) for e in events.read(child_id)]

    first = _runner(_FinalLLM(), store)
    second = _runner(_FinalLLM(), store)

    assert first.parent_of(child_id) == "parent-readonly"
    assert second.parent_of(child_id) == "parent-readonly"
    after = [(e.seq, e.type, dict(e.payload)) for e in events.read(child_id)]
    assert after == before


def test_restart_parent_authority_requires_session_and_event_agreement(tmp_path) -> None:
    store = _store(tmp_path)
    child_id = "subagent_parent_mismatch"
    sess = store.load(child_id)
    sess.parent_id = "parent-session"
    store.save(sess)
    events = store.event_store
    assert events is not None
    events.append(
        child_id,
        "subagent.linked",
        {
            "child_id": child_id,
            "parent_id": "parent-event",
            "generation": "g1",
            "depth": 0,
        },
    )
    events.append(
        child_id,
        "subagent.generation.started",
        {
            "child_id": child_id,
            "parent_id": "parent-event",
            "generation": "g1",
            "owner_id": "owner",
            "depth": 0,
        },
    )

    recovered = _runner(_FinalLLM(), store)

    assert recovered.parent_of(child_id) == ""
    assert recovered.topology_snapshot(child_id) is None


def test_reserve_save_loss_fails_closed_before_provider_execution(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    original_save = store.save
    calls = 0

    def _lose_first_reserve_save(session):  # noqa: ANN001, ANN202
        nonlocal calls
        calls += 1
        if calls == 1 and not session.messages:
            raise OSError("synthetic reserve save loss")
        return original_save(session)

    monkeypatch.setattr(store, "save", _lose_first_reserve_save)
    llm = _CountingLLM()
    runner = _runner(llm, store)
    started = _spawn(runner, "parent-reserve-loss")

    assert started["accepted"] is False
    assert llm.calls == 0

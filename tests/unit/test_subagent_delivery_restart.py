from __future__ import annotations

import threading
import time

import pytest

from llm_loop.core.run_context import current_session_id
from llm_loop.core.session import SessionStore
from llm_loop.event_log.model import (
    EVENT_SUBAGENT_CANCEL_REQUESTED,
    EVENT_SUBAGENT_MAILBOX_QUEUED,
    EVENT_SUBAGENT_REPORT_QUEUED,
    EVENT_SUBAGENT_RESULT_AVAILABLE,
)
from llm_loop.event_log.store import EventStore
from llm_loop.llm.client import LLMResponse
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.builtin.subagent_result import SubAgentResultTool
from llm_loop.tools.registry import ToolRegistry


class _BlockingLLM:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        self.entered.set()
        assert self.release.wait(timeout=5.0)
        return LLMResponse(content="CHILD-FINAL", tool_calls=[], provider="fake")


class _FinalLLM:
    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        return LLMResponse(content="CHILD-FINAL", tool_calls=[], provider="fake")


def _store(tmp_path) -> tuple[SessionStore, EventStore]:
    events = EventStore(tmp_path / "events", enabled=True)
    return SessionStore(tmp_path / "sessions", event_store=events), events


def _runner(llm, store: SessionStore) -> SubAgentRunner:  # noqa: ANN001
    return SubAgentRunner(llm=llm, registry=ToolRegistry(), session_store=store)  # type: ignore[arg-type]


def _spawn(runner: SubAgentRunner, parent_id: str) -> dict:
    token = current_session_id.set(parent_id)
    try:
        return runner.start("durable delivery probe", depth=0)
    finally:
        current_session_id.reset(token)


def _wait_terminal(runner: SubAgentRunner, parent_id: str, child_id: str) -> dict:
    deadline = time.monotonic() + 5.0
    token = current_session_id.set(parent_id)
    try:
        while time.monotonic() < deadline:
            ok, _detail, snapshot = runner.result_current(child_id, wait_seconds=0.05)
            assert ok
            if snapshot.get("state") not in {"running", "orphaned"}:
                return snapshot
        raise AssertionError("child did not reach terminal state")
    finally:
        current_session_id.reset(token)


def test_parent_steer_success_requires_durable_queue_and_restart_sees_pending(tmp_path) -> None:
    store, events = _store(tmp_path)
    llm = _BlockingLLM()
    runner = _runner(llm, store)
    parent = "parent-mailbox-durable"
    started = _spawn(runner, parent)
    child = str(started["child_id"])
    assert started["accepted"] is True
    assert llm.entered.wait(timeout=2.0)
    try:
        token = current_session_id.set(parent)
        try:
            ok, _detail, _target = runner.send_current_message(child, "STEER-DURABLE")
        finally:
            current_session_id.reset(token)
        assert ok is True
        queued = [e for e in events.read(child) if e.type == EVENT_SUBAGENT_MAILBOX_QUEUED]
        assert len(queued) == 1
        assert queued[0].payload["content"] == "STEER-DURABLE"
        assert queued[0].payload["message_id"]
        assert queued[0].payload["generation"]

        recovered = _runner(_FinalLLM(), store)
        snapshot = recovered.delivery_snapshot(child)
        assert snapshot is not None
        assert snapshot["pending_mailbox_count"] == 1
        assert snapshot["pending_mailbox"][0]["content"] == "STEER-DURABLE"
        assert recovered.active_children(parent) == []
    finally:
        llm.release.set()
        _wait_terminal(runner, parent, child)


def test_mailbox_event_write_failure_never_returns_false_success_or_queues_memory_only(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, events = _store(tmp_path)
    llm = _BlockingLLM()
    runner = _runner(llm, store)
    parent = "parent-mailbox-fail"
    started = _spawn(runner, parent)
    child = str(started["child_id"])
    assert llm.entered.wait(timeout=2.0)
    original_append = events.append

    def _fail_mailbox(session_id, event_type, payload):  # noqa: ANN001, ANN202
        if event_type == EVENT_SUBAGENT_MAILBOX_QUEUED:
            return None
        return original_append(session_id, event_type, payload)

    monkeypatch.setattr(events, "append", _fail_mailbox)
    try:
        token = current_session_id.set(parent)
        try:
            ok, _detail, _target = runner.send_current_message(child, "MUST-NOT-QUEUE")
        finally:
            current_session_id.reset(token)
        assert ok is False
        with runner._children_guard:  # noqa: SLF001
            assert runner._agent_inbox.get(child, []) == []  # noqa: SLF001
    finally:
        llm.release.set()
        _wait_terminal(runner, parent, child)


def test_step_boundary_durably_marks_message_ids_and_never_duplicates(tmp_path) -> None:
    store, events = _store(tmp_path)
    runner = _runner(_FinalLLM(), store)
    parent = "parent-mailbox-once"
    child, _cancel, sess = runner._reserve_child(parent)  # noqa: SLF001
    token = current_session_id.set(parent)
    try:
        assert runner.send_current_message(child, "DELIVER-ONCE")[0]
        assert runner._inject_pending_agent_messages(sess, child) == 1  # noqa: SLF001
        assert runner._inject_pending_agent_messages(sess, child) == 0  # noqa: SLF001
    finally:
        current_session_id.reset(token)
        runner._finalize_child(child, parent, None)  # noqa: SLF001

    durable = store.load(child)
    frames = [m for m in durable.messages if m.metadata.get("injection_kind") == "agent_message"]
    assert len(frames) == 1
    ids = frames[0].metadata.get("subagent_mailbox_message_ids")
    assert isinstance(ids, list) and len(ids) == 1
    assert frames[0].metadata.get("subagent_generation")
    assert "DELIVER-ONCE" in frames[0].content
    queued = [e for e in events.read(child) if e.type == EVENT_SUBAGENT_MAILBOX_QUEUED]
    assert ids == [queued[0].payload["message_id"]]


def test_child_report_is_durable_and_fresh_direct_parent_can_read_it(tmp_path) -> None:
    store, events = _store(tmp_path)
    llm = _BlockingLLM()
    runner = _runner(llm, store)
    parent = "parent-report-durable"
    started = _spawn(runner, parent)
    child = str(started["child_id"])
    assert llm.entered.wait(timeout=2.0)
    try:
        token = current_session_id.set(child)
        try:
            ok, _detail, _target = runner.send_current_message("parent", "REPORT-DURABLE")
        finally:
            current_session_id.reset(token)
        assert ok is True
        report_events = [e for e in events.read(child) if e.type == EVENT_SUBAGENT_REPORT_QUEUED]
        assert len(report_events) == 1
        assert report_events[0].payload["content"] == "REPORT-DURABLE"

        recovered = _runner(_FinalLLM(), store)
        token = current_session_id.set(parent)
        try:
            ok, _detail, snapshot = recovered.result_current(child, wait_seconds=0)
        finally:
            current_session_id.reset(token)
        assert ok is True
        assert snapshot["state"] == "orphaned"
        assert snapshot["reports"] == ["REPORT-DURABLE"]
        assert snapshot["result"] is None

        token = current_session_id.set(parent)
        try:
            receipt = SubAgentResultTool(recovered).execute(child_id=child, wait_seconds=0)
        finally:
            current_session_id.reset(token)
        assert receipt.status.value == "success"
        assert "child_state=orphaned" in receipt.content
        assert "REPORT-DURABLE" in receipt.content
        assert "不会自动恢复执行" in receipt.content

        token = current_session_id.set("not-the-parent")
        try:
            denied, _detail, _snapshot = recovered.result_current(child, wait_seconds=0)
        finally:
            current_session_id.reset(token)
        assert denied is False
    finally:
        llm.release.set()
        _wait_terminal(runner, parent, child)


def test_exact_terminal_result_is_queryable_after_restart_without_handle(tmp_path) -> None:
    store, events = _store(tmp_path)
    runner = _runner(_FinalLLM(), store)
    parent = "parent-result-durable"
    started = _spawn(runner, parent)
    child = str(started["child_id"])
    local = _wait_terminal(runner, parent, child)
    assert local["state"] == "completed"
    result_events = [e for e in events.read(child) if e.type == EVENT_SUBAGENT_RESULT_AVAILABLE]
    assert len(result_events) == 1

    recovered = _runner(_FinalLLM(), store)
    token = current_session_id.set(parent)
    try:
        ok, _detail, snapshot = recovered.result_current(child, wait_seconds=0)
    finally:
        current_session_id.reset(token)
    assert ok is True
    assert snapshot["state"] == "completed"
    result = snapshot["result"]
    assert result is not None
    assert result.final_answer == "CHILD-FINAL"
    assert result.outcome == "completed"
    assert result.rounds == 1
    assert result.depth == 0


def test_terminal_result_survives_local_handle_pruning(tmp_path) -> None:
    store, _events = _store(tmp_path)
    runner = _runner(_FinalLLM(), store)
    runner._max_handles = 1  # noqa: SLF001
    parent = "parent-result-prune"
    first = _spawn(runner, parent)
    first_id = str(first["child_id"])
    _wait_terminal(runner, parent, first_id)
    second = _spawn(runner, parent)
    second_id = str(second["child_id"])
    _wait_terminal(runner, parent, second_id)
    with runner._children_guard:  # noqa: SLF001
        assert first_id not in runner._handles  # noqa: SLF001

    token = current_session_id.set(parent)
    try:
        ok, _detail, snapshot = runner.result_current(first_id, wait_seconds=0)
    finally:
        current_session_id.reset(token)
    assert ok is True
    assert snapshot["result"].final_answer == "CHILD-FINAL"


def test_cancel_fact_is_attempted_before_local_signal_and_restart_exposes_it(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, events = _store(tmp_path)
    llm = _BlockingLLM()
    runner = _runner(llm, store)
    parent = "parent-cancel-durable"
    started = _spawn(runner, parent)
    child = str(started["child_id"])
    assert llm.entered.wait(timeout=2.0)
    original_append = events.append
    observed_signal_state: list[bool] = []

    def _observe_cancel(session_id, event_type, payload):  # noqa: ANN001, ANN202
        if event_type == EVENT_SUBAGENT_CANCEL_REQUESTED:
            with runner._children_guard:  # noqa: SLF001
                observed_signal_state.append(runner._cancel_events[child].is_set())  # noqa: SLF001
        return original_append(session_id, event_type, payload)

    monkeypatch.setattr(events, "append", _observe_cancel)
    assert runner.cancel_parent(parent) == 1
    assert observed_signal_state == [False]
    cancel_events = [e for e in events.read(child) if e.type == EVENT_SUBAGENT_CANCEL_REQUESTED]
    assert len(cancel_events) == 1
    assert cancel_events[0].payload["reason"] == "parent_lifecycle_cancel"

    recovered = _runner(_FinalLLM(), store)
    snapshot = recovered.delivery_snapshot(child)
    assert snapshot is not None
    assert snapshot["cancel_requested"] is True
    assert snapshot["cancel_reason"] == "parent_lifecycle_cancel"
    assert recovered.active_children(parent) == []
    llm.release.set()
    _wait_terminal(runner, parent, child)


def test_c1_keeps_existing_local_settlement_semantics_for_st2_c2(tmp_path) -> None:
    store, _events = _store(tmp_path)
    runner = _runner(_FinalLLM(), store)
    parent = "parent-settlement-deferred"
    started = _spawn(runner, parent)
    child = str(started["child_id"])
    _wait_terminal(runner, parent, child)
    assert runner.topology_snapshot(child)["settlement_state"] == "uncollected"

    token = current_session_id.set(parent)
    try:
        receipt = SubAgentResultTool(runner).execute(child_id=child, wait_seconds=0)
    finally:
        current_session_id.reset(token)
    assert receipt.status.value == "success"
    # Deliberately unchanged in ST2-C1; ST2-C2 will bind this ACK to parent receipt commit.
    assert runner.topology_snapshot(child)["settlement_state"] == "collected"


class _FailLLM:
    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        raise RuntimeError("synthetic-child-llm-failure")


class _ToolForeverLLM:
    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        from llm_loop.core.message import ToolCall

        return LLMResponse(
            content="",
            tool_calls=[ToolCall(id="missing-1", name="missing_tool", arguments={})],
            provider="fake",
        )


def test_result_available_precedes_generation_release_and_terminal(tmp_path) -> None:
    from llm_loop.event_log.model import (
        EVENT_SUBAGENT_GENERATION_RELEASED,
        EVENT_SUBAGENT_TERMINAL,
    )

    store, events = _store(tmp_path)
    runner = _runner(_FinalLLM(), store)
    parent = "parent-result-order"
    started = _spawn(runner, parent)
    child = str(started["child_id"])
    _wait_terminal(runner, parent, child)
    types = [e.type for e in events.read(child)]
    assert types.index(EVENT_SUBAGENT_RESULT_AVAILABLE) < types.index(
        EVENT_SUBAGENT_GENERATION_RELEASED
    )
    assert types.index(EVENT_SUBAGENT_GENERATION_RELEASED) < types.index(EVENT_SUBAGENT_TERMINAL)


def test_result_event_write_failure_never_creates_false_durable_terminal(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from llm_loop.event_log.model import EVENT_SUBAGENT_TERMINAL

    store, events = _store(tmp_path)
    llm = _BlockingLLM()
    runner = _runner(llm, store)
    parent = "parent-result-write-fail"
    started = _spawn(runner, parent)
    child = str(started["child_id"])
    assert llm.entered.wait(timeout=2.0)
    original_append = events.append

    def _fail_result(session_id, event_type, payload):  # noqa: ANN001, ANN202
        if event_type == EVENT_SUBAGENT_RESULT_AVAILABLE:
            return None
        return original_append(session_id, event_type, payload)

    monkeypatch.setattr(events, "append", _fail_result)
    llm.release.set()
    local = _wait_terminal(runner, parent, child)
    assert local["state"] == "completed"
    types = [e.type for e in events.read(child)]
    assert EVENT_SUBAGENT_RESULT_AVAILABLE not in types
    assert EVENT_SUBAGENT_TERMINAL not in types

    recovered = _runner(_FinalLLM(), store)
    snapshot = recovered.topology_snapshot(child)
    assert snapshot is not None
    assert snapshot["owner_state"] == "orphaned"
    assert snapshot["terminal"] is False
    token = current_session_id.set(parent)
    try:
        ok, _detail, recovered_result = recovered.result_current(child, 0)
    finally:
        current_session_id.reset(token)
    assert ok is True
    assert recovered_result["state"] == "orphaned"
    assert recovered_result["result"] is None


@pytest.mark.parametrize(
    ("llm", "max_rounds", "expected_outcome"),
    [
        (_FailLLM(), 1, "failed"),
        (_ToolForeverLLM(), 1, "truncated"),
    ],
)
def test_noncompleted_exact_terminal_result_survives_restart(
    tmp_path, llm, max_rounds: int, expected_outcome: str  # noqa: ANN001
) -> None:
    store, _events = _store(tmp_path)
    runner = _runner(llm, store)
    parent = f"parent-result-{expected_outcome}"
    token = current_session_id.set(parent)
    try:
        started = runner.start("noncompleted result", depth=0, max_rounds=max_rounds)
    finally:
        current_session_id.reset(token)
    child = str(started["child_id"])
    local = _wait_terminal(runner, parent, child)
    assert local["state"] == expected_outcome

    recovered = _runner(_FinalLLM(), store)
    token = current_session_id.set(parent)
    try:
        ok, _detail, snapshot = recovered.result_current(child, 0)
    finally:
        current_session_id.reset(token)
    assert ok is True
    assert snapshot["state"] == expected_outcome
    assert snapshot["result"] is not None
    assert snapshot["result"].outcome == expected_outcome
    assert snapshot["result"].final_answer


def test_cancelled_exact_terminal_result_survives_restart(tmp_path) -> None:
    store, _events = _store(tmp_path)
    llm = _BlockingLLM()
    runner = _runner(llm, store)
    parent = "parent-result-cancelled"
    started = _spawn(runner, parent)
    child = str(started["child_id"])
    assert llm.entered.wait(timeout=2.0)
    assert runner.cancel_parent(parent) == 1
    llm.release.set()
    local = _wait_terminal(runner, parent, child)
    assert local["state"] == "cancelled"

    recovered = _runner(_FinalLLM(), store)
    token = current_session_id.set(parent)
    try:
        ok, _detail, snapshot = recovered.result_current(child, 0)
    finally:
        current_session_id.reset(token)
    assert ok is True
    assert snapshot["state"] == "cancelled"
    assert snapshot["cancel_requested"] is True
    assert snapshot["result"].outcome == "cancelled"


def test_cancel_event_write_failure_still_stops_local_worker_without_false_recovery_fact(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, events = _store(tmp_path)
    llm = _BlockingLLM()
    runner = _runner(llm, store)
    parent = "parent-cancel-write-fail"
    started = _spawn(runner, parent)
    child = str(started["child_id"])
    assert llm.entered.wait(timeout=2.0)
    original_append = events.append

    def _fail_cancel(session_id, event_type, payload):  # noqa: ANN001, ANN202
        if event_type == EVENT_SUBAGENT_CANCEL_REQUESTED:
            return None
        return original_append(session_id, event_type, payload)

    monkeypatch.setattr(events, "append", _fail_cancel)
    assert runner.cancel_parent(parent) == 1
    with runner._children_guard:  # noqa: SLF001
        assert runner._cancel_events[child].is_set()  # noqa: SLF001
    llm.release.set()
    _wait_terminal(runner, parent, child)
    assert not any(e.type == EVENT_SUBAGENT_CANCEL_REQUESTED for e in events.read(child))

    recovered = _runner(_FinalLLM(), store)
    snapshot = recovered.delivery_snapshot(child)
    assert snapshot is not None
    assert snapshot["cancel_requested"] is False


def test_fresh_subagent_result_tool_can_render_exact_durable_terminal(tmp_path) -> None:
    store, _events = _store(tmp_path)
    runner = _runner(_FinalLLM(), store)
    parent = "parent-fresh-result-tool"
    started = _spawn(runner, parent)
    child = str(started["child_id"])
    _wait_terminal(runner, parent, child)

    recovered = _runner(_FinalLLM(), store)
    token = current_session_id.set(parent)
    try:
        receipt = SubAgentResultTool(recovered).execute(child_id=child, wait_seconds=0)
    finally:
        current_session_id.reset(token)
    assert receipt.status.value == "success"
    assert "child_outcome=completed" in receipt.content
    assert "CHILD-FINAL" in receipt.content
    # C1 has no durable settlement hook yet; rendering a recovered result must not
    # fabricate a local handle/collected state.
    assert recovered.topology_snapshot(child)["settlement_state"] == "unknown"


def test_eventstore_disabled_runner_keeps_legacy_same_process_mailbox(tmp_path) -> None:
    events = EventStore(tmp_path / "events-disabled", enabled=False)
    store = SessionStore(tmp_path / "sessions-disabled", event_store=events)
    runner = _runner(_FinalLLM(), store)
    parent = "parent-disabled-mailbox"
    child, _cancel, sess = runner._reserve_child(parent)  # noqa: SLF001
    token = current_session_id.set(parent)
    try:
        assert runner.send_current_message(child, "LOCAL-ONLY")[0]
        assert runner._inject_pending_agent_messages(sess, child) == 1  # noqa: SLF001
    finally:
        current_session_id.reset(token)
        runner._finalize_child(child, parent, None)  # noqa: SLF001
    assert any("LOCAL-ONLY" in message.content for message in sess.messages)

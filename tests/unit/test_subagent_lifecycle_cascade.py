"""Deterministic three-level cancellation/cleanup contract (provider-free)."""

from __future__ import annotations

import threading

from llm_loop.core.run_context import current_run_generation, current_session_id
from llm_loop.core.session import SessionStore
from llm_loop.event_log.model import (
    EVENT_SUBAGENT_CANCEL_REQUESTED,
    EVENT_SUBAGENT_RESULT_AVAILABLE,
)
from llm_loop.event_log.store import EventStore
from llm_loop.llm.client import LLMResponse
from llm_loop.subagent.runner import _CURRENT_SUBAGENT_DEPTH, SubAgentRunner
from llm_loop.tools.builtin.subagent_result import SubAgentResultTool
from llm_loop.tools.registry import ToolRegistry


class _NestedAgentLLM:
    def __init__(self, *, hold_child: bool) -> None:
        self.runner: SubAgentRunner | None = None
        self.hold_child = hold_child
        self.grandchild_id = ""
        self.grandchild_spawned = threading.Event()
        self.grandchild_entered = threading.Event()
        self.child_release = threading.Event()
        self.grandchild_release = threading.Event()

    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        assert self.runner is not None
        depth = _CURRENT_SUBAGENT_DEPTH.get()
        if depth == 0:
            # A real nested tool invocation clears the inherited parent run
            # generation before dispatch. Reproduce that current runtime fact.
            generation_token = current_run_generation.set("")
            try:
                grandchild = self.runner.start("grandchild awaits", depth=1)
            finally:
                current_run_generation.reset(generation_token)
            assert grandchild["accepted"] is True, grandchild
            self.grandchild_id = str(grandchild["child_id"])
            self.grandchild_spawned.set()
            if self.hold_child:
                assert self.child_release.wait(timeout=5.0)
            return LLMResponse(content="child completed", tool_calls=[], provider="fake")
        if depth == 1:
            self.grandchild_entered.set()
            assert self.grandchild_release.wait(timeout=5.0)
            return LLMResponse(content="grandchild completed", tool_calls=[], provider="fake")
        raise AssertionError(f"unexpected depth: {depth}")


def _setup(tmp_path, *, hold_child: bool):  # noqa: ANN001, ANN202
    events = EventStore(tmp_path / "events", enabled=True)
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    registry = ToolRegistry()
    llm = _NestedAgentLLM(hold_child=hold_child)
    runner = SubAgentRunner(llm=llm, registry=registry, session_store=sessions)  # type: ignore[arg-type]
    registry.add_session_cancel_hook(runner.cancel_parent)
    llm.runner = runner
    parent = "lifecycle-root-parent"
    sid_token = current_session_id.set(parent)
    gen_token = current_run_generation.set("root-generation-A")
    try:
        started = runner.start("child spawns grandchild", depth=0)
    finally:
        current_run_generation.reset(gen_token)
        current_session_id.reset(sid_token)
    assert started["accepted"] is True, started
    assert llm.grandchild_spawned.wait(timeout=3.0)
    assert llm.grandchild_entered.wait(timeout=3.0)
    return runner, llm, parent, str(started["child_id"])


def _release_and_join(runner: SubAgentRunner, llm: _NestedAgentLLM, child_id: str) -> None:
    llm.child_release.set()
    llm.grandchild_release.set()
    with runner._children_guard:  # noqa: SLF001 - deterministic thread cleanup
        threads = [
            handle.thread
            for sid, handle in runner._handles.items()  # noqa: SLF001
            if sid in {child_id, llm.grandchild_id}
        ]
    for thread in threads:
        assert thread is not None
        thread.join(timeout=4.0)
        assert not thread.is_alive(), "test child worker did not terminate"


def test_completed_child_cancels_still_running_grandchild(tmp_path) -> None:
    """A child's normal terminal cannot leave a descendant doing late effects."""
    runner, llm, _parent, child = _setup(tmp_path, hold_child=False)
    try:
        with runner._children_guard:  # noqa: SLF001
            child_done = runner._handles[child].done_event  # noqa: SLF001
        assert child_done.wait(timeout=3.0)
        with runner._children_guard:  # noqa: SLF001
            assert runner._handles[child].state == "completed"  # noqa: SLF001
            descendant_cancelled = runner._cancel_events[llm.grandchild_id].is_set()  # noqa: SLF001
        assert descendant_cancelled, "normal child exit did not cancel its active descendant"
    finally:
        _release_and_join(runner, llm, child)
    with runner._children_guard:  # noqa: SLF001 - resource disposal is part of the contract
        assert runner._handles[llm.grandchild_id].state == "cancelled"  # noqa: SLF001
        assert llm.grandchild_id not in runner._cancel_events  # noqa: SLF001
    assert runner.active_children(child) == []


def test_root_cancel_cascades_even_when_grandchild_has_no_parent_run_generation(tmp_path) -> None:
    """A root-generation cancel must not miss a descendant with its own scope."""
    runner, llm, parent, child = _setup(tmp_path, hold_child=True)
    try:
        gen_token = current_run_generation.set("root-generation-A")
        try:
            assert runner.cancel_parent(parent, run_generation="root-generation-A") == 1
        finally:
            current_run_generation.reset(gen_token)
        with runner._children_guard:  # noqa: SLF001
            direct_cancelled = runner._cancel_events[child].is_set()  # noqa: SLF001
            descendant_cancelled = runner._cancel_events[llm.grandchild_id].is_set()  # noqa: SLF001
        assert direct_cancelled
        assert descendant_cancelled, "root cancel did not reach third-level agent"
    finally:
        _release_and_join(runner, llm, child)
    assert runner.active_children(child) == []
    events = runner.session_store.event_store
    assert events is not None
    assert any(
        row.type == EVENT_SUBAGENT_CANCEL_REQUESTED
        for row in events.read(llm.grandchild_id)
    ), "third-level cancellation must have a durable request before local signal"


def test_later_root_generation_cannot_cancel_earlier_root_subtree(tmp_path) -> None:
    """Transitive cancellation must not bypass the ROOT generation fence."""
    runner, llm, parent, child = _setup(tmp_path, hold_child=True)
    try:
        assert runner.cancel_parent(parent, run_generation="root-generation-B") == 0
        with runner._children_guard:  # noqa: SLF001
            assert not runner._cancel_events[child].is_set()  # noqa: SLF001
            assert not runner._cancel_events[llm.grandchild_id].is_set()  # noqa: SLF001
        assert runner.cancel_parent(parent, run_generation="root-generation-A") == 1
        with runner._children_guard:  # noqa: SLF001
            assert runner._cancel_events[child].is_set()  # noqa: SLF001
            assert runner._cancel_events[llm.grandchild_id].is_set()  # noqa: SLF001
    finally:
        _release_and_join(runner, llm, child)


class _HoldingFinalLLM:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        self.entered.set()
        assert self.release.wait(timeout=5.0)
        return LLMResponse(content="child final answer", tool_calls=[], provider="fake")


def _single_child(tmp_path):  # noqa: ANN001, ANN202
    events = EventStore(tmp_path / "events", enabled=True)
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    llm = _HoldingFinalLLM()
    runner = SubAgentRunner(llm=llm, registry=ToolRegistry(), session_store=sessions)  # type: ignore[arg-type]
    parent = "lifecycle-wait-parent"
    sid_token = current_session_id.set(parent)
    try:
        started = runner.start("blocking child task", depth=0)
    finally:
        current_session_id.reset(sid_token)
    assert started["accepted"] is True
    assert llm.entered.wait(timeout=3.0)
    return runner, llm, events, sessions, parent, str(started["child_id"])


def test_wait_wakes_on_intermediate_report_then_terminal_without_lost_event(tmp_path) -> None:
    """Event-driven read must not spin or lose a report/terminal wake-up."""
    runner, llm, _events, _sessions, parent, child = _single_child(tmp_path)
    with runner._children_guard:  # noqa: SLF001
        handle = runner._handles[child]  # noqa: SLF001
    original_wait = handle.activity_event.wait

    def _read_in_thread(result: dict) -> None:
        token = current_session_id.set(parent)
        try:
            result["response"] = runner.result_current(child, wait_seconds=2.0)
        finally:
            current_session_id.reset(token)

    try:
        for wake_kind in ("report", "terminal"):
            entered_wait = threading.Event()

            def _observed_wait(timeout, signal=entered_wait):  # noqa: ANN001, ANN202
                signal.set()
                return original_wait(timeout)

            handle.activity_event.wait = _observed_wait
            read: dict = {}
            worker = threading.Thread(target=_read_in_thread, args=(read,))
            worker.start()
            assert entered_wait.wait(timeout=1.0), "parent never entered the event wait"
            if wake_kind == "report":
                token = current_session_id.set(child)
                try:
                    assert runner.send_current_message("parent", "middle progress report")[0]
                finally:
                    current_session_id.reset(token)
            else:
                llm.release.set()
            worker.join(timeout=1.5)
            assert not worker.is_alive(), f"{wake_kind} did not wake awaiting parent"
            ok, _detail, response = read["response"]
            assert ok
            assert "middle progress report" in response["reports"]
            if wake_kind == "report":
                assert response["state"] == "running"
            else:
                assert response["state"] == "completed"
                assert response["result"].final_answer == "child final answer"
    finally:
        llm.release.set()
        handle.activity_event.wait = original_wait
        assert handle.thread is not None
        handle.thread.join(timeout=4.0)
        assert not handle.thread.is_alive()


def test_local_success_without_durable_result_is_explicitly_labeled(tmp_path, monkeypatch) -> None:
    """A local terminal cannot masquerade as a crash-recoverable result."""
    runner, llm, events, sessions, parent, child = _single_child(tmp_path)
    original_append = events.append

    def _drop_result(session_id, event_type, payload):  # noqa: ANN001, ANN202
        if event_type == EVENT_SUBAGENT_RESULT_AVAILABLE:
            return None
        return original_append(session_id, event_type, payload)

    monkeypatch.setattr(events, "append", _drop_result)
    try:
        llm.release.set()
        with runner._children_guard:  # noqa: SLF001
            done_event = runner._handles[child].done_event  # noqa: SLF001
        assert done_event.wait(timeout=3.0)
        parent_token = current_session_id.set(parent)
        try:
            local = SubAgentResultTool(runner).execute(child_id=child)
        finally:
            current_session_id.reset(parent_token)
        assert local.status.value == "success"
        assert "child_outcome=completed" in local.content
        assert local.subagent_settlement is None
        assert "result_durability=local_only" in local.content

        # Restart must report what the journal actually knows, not replay a
        # successful local handle or silently run the provider again.
        recovered = SubAgentRunner(
            llm=_HoldingFinalLLM(),
            registry=ToolRegistry(),
            session_store=sessions,  # type: ignore[arg-type]
        )
        parent_token = current_session_id.set(parent)
        try:
            ok, _detail, snapshot = recovered.result_current(child, wait_seconds=2.0)
        finally:
            current_session_id.reset(parent_token)
        assert ok
        assert snapshot["state"] == "orphaned"
        assert snapshot["result"] is None
    finally:
        llm.release.set()

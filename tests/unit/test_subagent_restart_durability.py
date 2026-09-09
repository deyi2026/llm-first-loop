from __future__ import annotations

import multiprocessing
import sys
import threading
import time
from pathlib import Path

import pytest

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.core.session import SessionStore
from llm_loop.event_log.store import EventStore
from llm_loop.llm.client import LLMResponse
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.registry import ToolRegistry


class _BlockingFirstLLM:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        self.entered.set()
        assert self.release.wait(5.0)
        return LLMResponse(content="child-final", tool_calls=[], provider="fake")


class _TwoRoundLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.second_entered = threading.Event()
        self.release = threading.Event()

    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="effect-1", name="probe_effect", arguments={})],
                provider="fake",
            )
        self.second_entered.set()
        assert self.release.wait(5.0)
        return LLMResponse(content="child-final", tool_calls=[], provider="fake")


class _BlockingToolLLM:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="block-1", name="blocking_effect", arguments={})],
                provider="fake",
            )
        return LLMResponse(content="child-final", tool_calls=[], provider="fake")


class _ProbeEffectTool:
    name = "probe_effect"
    description = "local restart durability probe"
    parameters = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.executed = threading.Event()
        self.count = 0

    def execute(self, **kwargs) -> ToolResult:  # noqa: ANN003, ARG002
        self.count += 1
        self.executed.set()
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="EFFECT_DONE",
            tool_call_id="",
            tool_name=self.name,
        )


class _BlockingEffectTool:
    name = "blocking_effect"
    description = "local started-before-effect durability probe"
    parameters = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def execute(self, **kwargs) -> ToolResult:  # noqa: ANN003, ARG002
        self.entered.set()
        assert self.release.wait(5.0)
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="BLOCKING_EFFECT_DONE",
            tool_call_id="",
            tool_name=self.name,
        )


def _probe_lease_from_process(sessions_dir: str, child_id: str, queue) -> None:  # noqa: ANN001
    store = SessionStore(sessions_dir)
    with store.run_lease(child_id) as acquired:
        queue.put(bool(acquired))


def _store(tmp_path: Path) -> tuple[SessionStore, EventStore]:
    events = EventStore(tmp_path / "events", enabled=True)
    return SessionStore(tmp_path / "sessions", event_store=events), events


def _wait_terminal(runner: SubAgentRunner, child_id: str, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with runner._children_guard:  # noqa: SLF001 - deterministic lifecycle probe
            handle = runner._handles.get(child_id)  # noqa: SLF001
            if handle is not None and handle.state != "running":
                return
        time.sleep(0.01)
    raise AssertionError(f"child did not settle: {child_id}")


def test_background_child_task_is_durable_before_first_llm_and_lease_is_exclusive(
    tmp_path: Path,
) -> None:
    store, _events = _store(tmp_path)
    llm = _BlockingFirstLLM()
    runner = SubAgentRunner(llm=llm, registry=ToolRegistry(), session_store=store)  # type: ignore[arg-type]
    token = current_session_id.set("parent-st2a-task")
    child_id = ""
    try:
        started = runner.start(task="DURABLE-DELEGATED-TASK")
        assert started["accepted"] is True
        child_id = str(started["child_id"])
        # Successful spawn acknowledgement itself is now a durable-start boundary.
        durable = store.load(child_id)
        assert durable.parent_id == "parent-st2a-task"
        assert [m.role for m in durable.messages] == ["user"]
        assert "DURABLE-DELEGATED-TASK" in durable.messages[0].content
        assert durable.messages[0].metadata.get("injection_kind") == "subagent_task"

        with store.run_lease(child_id) as acquired_by_second_owner:
            assert acquired_by_second_owner is False
        assert llm.entered.wait(2.0)
    finally:
        current_session_id.reset(token)
        llm.release.set()
        if child_id:
            _wait_terminal(runner, child_id)


def test_tool_effect_has_durable_protocol_and_wal_before_next_llm(tmp_path: Path) -> None:
    store, events = _store(tmp_path)
    registry = ToolRegistry()
    effect = _ProbeEffectTool()
    registry.register(effect)
    llm = _TwoRoundLLM()
    runner = SubAgentRunner(llm=llm, registry=registry, session_store=store)  # type: ignore[arg-type]
    token = current_session_id.set("parent-st2a-effect")
    child_id = ""
    try:
        started = runner.start(task="perform probe exactly once")
        child_id = str(started["child_id"])
        assert effect.executed.wait(2.0)
        assert llm.second_entered.wait(2.0)

        assert effect.count == 1
        durable = store.load(child_id)
        assert [m.role for m in durable.messages[:3]] == ["user", "assistant", "tool"]
        declaration = durable.messages[1]
        receipt = durable.messages[2]
        assert declaration.tool_calls is not None
        assert declaration.tool_calls[0]["id"] == "effect-1"
        assert receipt.tool_call_id == "effect-1"
        assert "EFFECT_DONE" in receipt.content

        wal_types = [e.type for e in events.read(child_id) if e.type.startswith("tool.execution.")]
        assert wal_types == [
            "tool.execution.declared",
            "tool.execution.started",
            "tool.execution.finished",
            "tool.execution.receipt_committed",
        ]
    finally:
        current_session_id.reset(token)
        llm.release.set()
        if child_id:
            _wait_terminal(runner, child_id)


def test_tool_declaration_and_started_wal_are_durable_before_tool_returns(tmp_path: Path) -> None:
    store, events = _store(tmp_path)
    registry = ToolRegistry()
    effect = _BlockingEffectTool()
    registry.register(effect)
    llm = _BlockingToolLLM()
    runner = SubAgentRunner(llm=llm, registry=registry, session_store=store)  # type: ignore[arg-type]
    token = current_session_id.set("parent-st2a-started")
    child_id = ""
    try:
        started = runner.start(task="begin one blocking effect")
        child_id = str(started["child_id"])
        assert effect.entered.wait(2.0)

        durable = store.load(child_id)
        assert [m.role for m in durable.messages] == ["user", "assistant"]
        assert durable.messages[-1].tool_calls is not None
        assert durable.messages[-1].tool_calls[0]["id"] == "block-1"

        wal_types = [e.type for e in events.read(child_id) if e.type.startswith("tool.execution.")]
        assert wal_types == ["tool.execution.declared", "tool.execution.started"]
        with store.run_lease(child_id) as acquired_by_second_owner:
            assert acquired_by_second_owner is False
    finally:
        current_session_id.reset(token)
        effect.release.set()
        if child_id:
            _wait_terminal(runner, child_id)


@pytest.mark.parametrize(
    ("failed_event", "reason_code"),
    [
        ("tool.execution.declared", "wal_declaration_unavailable"),
        ("tool.execution.started", "wal_start_not_durable"),
    ],
)
def test_subagent_wal_gate_failure_prevents_tool_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_event: str, reason_code: str
) -> None:
    store, events = _store(tmp_path)
    original_append = events.append

    def _flaky_append(session_id, event_type, payload):  # noqa: ANN001, ANN202
        if event_type == failed_event:
            return None
        return original_append(session_id, event_type, payload)

    monkeypatch.setattr(events, "append", _flaky_append)
    registry = ToolRegistry()
    effect = _ProbeEffectTool()
    registry.register(effect)
    llm = _TwoRoundLLM()
    llm.release.set()
    runner = SubAgentRunner(llm=llm, registry=registry, session_store=store)  # type: ignore[arg-type]
    token = current_session_id.set(f"parent-{reason_code}")
    child_id = ""
    try:
        started = runner.start(task="do not execute when WAL gate is unavailable")
        child_id = str(started["child_id"])
        _wait_terminal(runner, child_id)
        durable = store.load(child_id)

        assert effect.count == 0
        receipts = [
            m for m in durable.messages if m.role == "tool" and m.tool_call_id == "effect-1"
        ]
        assert len(receipts) == 1
        assert reason_code in receipts[0].content
        assert "auto_reexecuted=false" in receipts[0].content
    finally:
        current_session_id.reset(token)
        llm.release.set()


def test_shared_journal_recovers_started_unknown_without_reexecution(tmp_path: Path) -> None:
    store, _events = _store(tmp_path)
    registry = ToolRegistry()
    effect = _ProbeEffectTool()
    registry.register(effect)
    runner = SubAgentRunner(llm=_BlockingFirstLLM(), registry=registry, session_store=store)  # type: ignore[arg-type]
    child_id = "subagent_started_unknown"
    call = ToolCall(id="unknown-1", name=effect.name, arguments={})

    with store.run_owned_session(child_id) as sess:
        assert sess is not None
        sess.parent_id = "parent-recovery"
        from llm_loop.core.message import Message, MessageSource

        sess.messages.append(Message(role="user", content="delegated", source=MessageSource.USER))
        sess.messages.append(
            Message(
                role="assistant",
                content="",
                source=MessageSource.USER,
                tool_calls=[
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": "{}"},
                    }
                ],
            )
        )
        store.save(sess)
        execution_id = runner._tool_journal.declared(sess, call, round_no=1)  # noqa: SLF001
        assert execution_id
        assert runner._tool_journal.started(  # noqa: SLF001
            child_id, execution_id=execution_id, round_no=1, call=call
        )

        recovered = runner._tool_journal.recover(child_id, sess)  # noqa: SLF001
        assert recovered == 1
        receipt = sess.messages[-1]
        assert receipt.role == "tool"
        assert receipt.tool_call_id == call.id
        assert "execution_outcome=unknown_after_restart" in receipt.content
        assert "auto_reexecuted=false" in receipt.content
        assert receipt.metadata["tool_execution_recovery"]["state"] == "started_outcome_unknown"
        assert effect.count == 0

    durable = store.load(child_id)
    assert durable.messages[-1].tool_call_id == call.id
    assert durable.messages[-1].metadata["tool_execution_recovery"]["auto_reexecuted"] is False


@pytest.mark.skipif(
    sys.platform == "win32", reason="cross-process flock contract is POSIX-specific"
)
def test_running_child_lease_is_exclusive_across_processes(tmp_path: Path) -> None:
    store, _events = _store(tmp_path)
    llm = _BlockingFirstLLM()
    runner = SubAgentRunner(llm=llm, registry=ToolRegistry(), session_store=store)  # type: ignore[arg-type]
    token = current_session_id.set("parent-st2a-process-lease")
    child_id = ""
    process = None
    try:
        started = runner.start(task="hold the child lease while provider is blocked")
        child_id = str(started["child_id"])
        assert llm.entered.wait(2.0)

        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        process = ctx.Process(
            target=_probe_lease_from_process,
            args=(str(store.root), child_id, queue),
        )
        process.start()
        acquired = queue.get(timeout=5.0)
        process.join(timeout=5.0)
        assert process.exitcode == 0
        assert acquired is False
    finally:
        current_session_id.reset(token)
        llm.release.set()
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=2.0)
        if child_id:
            _wait_terminal(runner, child_id)


def test_spawn_failure_to_persist_delegated_task_never_reaches_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _events = _store(tmp_path)
    original_save = store.save

    def _fail_delegated_task(session):  # noqa: ANN001, ANN202
        if any(m.metadata.get("injection_kind") == "subagent_task" for m in session.messages):
            raise OSError("synthetic durable-start failure")
        return original_save(session)

    monkeypatch.setattr(store, "save", _fail_delegated_task)
    llm = _BlockingFirstLLM()
    runner = SubAgentRunner(llm=llm, registry=ToolRegistry(), session_store=store)  # type: ignore[arg-type]
    token = current_session_id.set("parent-st2a-save-fail")
    try:
        started = runner.start(task="must not reach provider without durable task")
        assert started["accepted"] is False
        assert started["state"] == "failed"
        assert "durable_start_failed:OSError" in str(started["detail"])
        assert llm.entered.is_set() is False
        child_id = str(started["child_id"])
        _wait_terminal(runner, child_id)
        durable = store.load(child_id)
        assert durable.messages == []
    finally:
        current_session_id.reset(token)
        llm.release.set()

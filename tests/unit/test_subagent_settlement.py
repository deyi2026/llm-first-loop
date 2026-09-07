from __future__ import annotations

from llm_loop.core.message import Message, MessageSource, ToolCall, ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.core.session import SessionStore
from llm_loop.core.tool_execution_journal import ToolExecutionJournal
from llm_loop.event_log.store import EventStore
from llm_loop.subagent.runner import SubAgentResult, SubAgentRunner
from llm_loop.tools.builtin.subagent_result import SubAgentResultTool
from llm_loop.tools.registry import ToolRegistry


class _NoopLLM:
    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        raise AssertionError("settlement tests must not execute a child provider call")


def _terminal_child(runner: SubAgentRunner, parent_id: str) -> tuple[str, str, str]:
    child_id, _cancel, _sess, handle = runner._reserve_background_child(parent_id, 0)  # noqa: SLF001
    generation = handle.generation
    assert runner._topology_journal.linked(  # noqa: SLF001
        child_id=child_id,
        parent_id=parent_id,
        generation=generation,
        depth=0,
    )
    assert runner._topology_journal.generation_started(  # noqa: SLF001
        child_id=child_id,
        parent_id=parent_id,
        generation=generation,
        owner_id=runner._runner_owner_id,  # noqa: SLF001
        depth=0,
    )
    result = SubAgentResult(final_answer="CHILD-RESULT", outcome="completed", rounds=1, depth=0)
    assert runner._persist_terminal_result(  # noqa: SLF001
        child_id=child_id,
        parent_id=parent_id,
        generation=generation,
        result=result,
    )
    runner._finalize_child(child_id, parent_id, result)  # noqa: SLF001
    snapshot = runner.delivery_snapshot(child_id)
    assert snapshot is not None
    result_id = str(snapshot["result_id"])
    assert result_id
    return child_id, generation, result_id


def test_subagent_result_tool_only_builds_receipt_and_does_not_settle(tmp_path) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    store = SessionStore(tmp_path / "sessions", event_store=events)
    runner = SubAgentRunner(llm=_NoopLLM(), registry=ToolRegistry(), session_store=store)  # type: ignore[arg-type]
    parent = "parent-direct-receipt"
    child, generation, result_id = _terminal_child(runner, parent)
    assert runner.topology_snapshot(child)["settlement_state"] == "uncollected"

    token = current_session_id.set(parent)
    try:
        receipt = SubAgentResultTool(runner).execute(child_id=child, wait_seconds=0)
    finally:
        current_session_id.reset(token)

    assert receipt.status is ToolResultStatus.SUCCESS
    assert runner.topology_snapshot(child)["settlement_state"] == "uncollected"
    assert receipt.subagent_settlement == {
        "child_id": child,
        "parent_id": parent,
        "generation": generation,
        "result_id": result_id,
    }
    message = receipt.to_message()
    assert message.metadata["subagent_settlement"] == receipt.subagent_settlement
    assert "subagent_settlement" not in message.to_llm_dict()


def test_tool_execution_finished_alone_never_runs_receipt_commit_hook(tmp_path) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    store = SessionStore(tmp_path / "sessions", event_store=events)
    committed: list[tuple[str, str]] = []

    journal = ToolExecutionJournal(
        event_store=events,
        result_root=tmp_path / "tool-results",
        session_store=store,
        receipt_committed_hook=lambda sid, msg: committed.append((sid, msg.tool_call_id or "")),
    )
    sid = store.create()
    sess = store.load(sid)
    call = ToolCall(id="collect-finished-only", name="subagent_result", arguments={})
    execution_id = journal.declared(sess, call, round_no=1)
    assert journal.started(sid, execution_id=execution_id, round_no=1, call=call)
    message = Message(
        role="tool",
        content="[状态: success] TERMINAL",
        source=MessageSource.TOOL,
        tool_call_id=call.id,
        tool_name=call.name,
        status=ToolResultStatus.SUCCESS,
        metadata={
            "subagent_settlement": {
                "child_id": "subagent_x",
                "parent_id": sid,
                "generation": "g1",
                "result_id": "r1",
            }
        },
    )
    result_sha = journal.finished(
        sid,
        execution_id=execution_id,
        round_no=1,
        call=call,
        tool_message=message,
    )
    assert result_sha
    assert committed == []

    journal.receipt_committed(
        sid,
        execution_id=execution_id,
        round_no=1,
        tool_call_id=call.id,
        tool_name=call.name,
        result_state_sha256=result_sha,
        tool_message=message,
    )
    assert committed == [(sid, call.id)]


def test_wal_recovery_runs_same_hook_only_after_recovered_commit(tmp_path) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    store = SessionStore(tmp_path / "sessions", event_store=events)
    committed: list[tuple[str, str]] = []
    journal = ToolExecutionJournal(
        event_store=events,
        result_root=tmp_path / "tool-results",
        session_store=store,
        receipt_committed_hook=lambda sid, msg: committed.append((sid, msg.tool_call_id or "")),
    )
    sid = store.create()
    sess = store.load(sid)
    call = ToolCall(id="collect-recover", name="subagent_result", arguments={})
    decl = Message(
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
    sess.messages.append(decl)
    store.save(sess)
    events.append(
        sid,
        "message.appended",
        {
            "index": 0,
            "role": "assistant",
            "content": "",
            "source": "user",
            "tool_call_id": None,
            "status": None,
            "tool_name": None,
            "error_detail": None,
            "tool_calls": decl.tool_calls,
            "reasoning_content": None,
            "metadata": {},
        },
    )
    execution_id = journal.declared(sess, call, round_no=1)
    assert journal.started(sid, execution_id=execution_id, round_no=1, call=call)
    message = Message(
        role="tool",
        content="[状态: success] RECOVERED-TERMINAL",
        source=MessageSource.TOOL,
        tool_call_id=call.id,
        tool_name=call.name,
        status=ToolResultStatus.SUCCESS,
        metadata={
            "subagent_settlement": {
                "child_id": "subagent_y",
                "parent_id": sid,
                "generation": "g1",
                "result_id": "r1",
            }
        },
    )
    journal.finished(
        sid,
        execution_id=execution_id,
        round_no=1,
        call=call,
        tool_message=message,
    )
    assert committed == []

    assert journal.recover(sid, sess) == 1
    assert committed == [(sid, call.id)]
    committed_events = [e for e in events.read(sid) if e.type == "tool.execution.receipt_committed"]
    assert committed_events[-1].payload["recovered"] is True


def test_committed_binding_settles_local_handle_and_is_restart_derived(tmp_path) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    store = SessionStore(tmp_path / "sessions", event_store=events)
    runner = SubAgentRunner(llm=_NoopLLM(), registry=ToolRegistry(), session_store=store)  # type: ignore[arg-type]
    parent = store.create()
    child, generation, result_id = _terminal_child(runner, parent)
    binding = {
        "child_id": child,
        "parent_id": parent,
        "generation": generation,
        "result_id": result_id,
    }
    message = Message(
        role="tool",
        content="[状态: success] CHILD-RESULT",
        source=MessageSource.TOOL,
        tool_call_id="collect-commit",
        tool_name="subagent_result",
        status=ToolResultStatus.SUCCESS,
        metadata={"subagent_settlement": binding},
    )
    parent_sess = store.load(parent)
    parent_sess.messages.append(message)
    store.save(parent_sess)
    events.append(
        parent,
        "message.appended",
        {
            "index": len(parent_sess.messages) - 1,
            "role": "tool",
            "content": message.content,
            "source": message.source.value,
            "tool_call_id": message.tool_call_id,
            "status": message.status.value,
            "tool_name": message.tool_name,
            "error_detail": None,
            "tool_calls": None,
            "reasoning_content": None,
            "metadata": message.metadata,
        },
    )
    events.append(
        parent,
        "tool.execution.receipt_committed",
        {
            "execution_id": "exec-commit",
            "round": 1,
            "tool_call_id": message.tool_call_id,
            "tool_name": message.tool_name,
            "result_state_sha256": "sha",
            "recovered": False,
        },
    )

    assert runner.settle_committed_receipt(parent, message) is True
    assert runner.topology_snapshot(child)["settlement_state"] == "collected"

    recovered = SubAgentRunner(llm=_NoopLLM(), registry=ToolRegistry(), session_store=store)  # type: ignore[arg-type]
    assert recovered.topology_snapshot(child)["settlement_state"] == "collected"


def test_stale_generation_or_wrong_parent_binding_never_settles(tmp_path) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    store = SessionStore(tmp_path / "sessions", event_store=events)
    runner = SubAgentRunner(llm=_NoopLLM(), registry=ToolRegistry(), session_store=store)  # type: ignore[arg-type]
    parent = "parent-fence"
    child, generation, result_id = _terminal_child(runner, parent)

    def _message(parent_id: str, gen: str) -> Message:
        return Message(
            role="tool",
            content="[状态: success] CHILD-RESULT",
            source=MessageSource.TOOL,
            tool_call_id="collect-fence",
            tool_name="subagent_result",
            status=ToolResultStatus.SUCCESS,
            metadata={
                "subagent_settlement": {
                    "child_id": child,
                    "parent_id": parent_id,
                    "generation": gen,
                    "result_id": result_id,
                }
            },
        )

    assert runner.settle_committed_receipt(parent, _message(parent, "stale-generation")) is False
    assert runner.settle_committed_receipt(parent, _message("different-parent", generation)) is False
    assert runner.topology_snapshot(child)["settlement_state"] == "uncollected"


def _attach_shared_events(engine, runner: SubAgentRunner, events: EventStore) -> None:  # noqa: ANN001
    engine._event_store = events  # noqa: SLF001
    engine.session._event_store = events  # noqa: SLF001
    runner._delivery_journal.event_store = events  # noqa: SLF001
    runner._topology_journal.event_store = events  # noqa: SLF001
    runner._tool_journal.event_store = events  # noqa: SLF001
    engine._tool_receipt_committed_hook = runner.settle_committed_receipt  # noqa: SLF001


def test_real_tool_cycle_settles_only_after_parent_receipt_commit(build_test_engine, tmp_path) -> None:
    from llm_loop.llm.client import LLMResponse

    child_box: dict[str, str] = {}

    def _collect(_calls):  # noqa: ANN001, ANN202
        return LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="parent-collect",
                    name="subagent_result",
                    arguments={"child_id": child_box["id"], "wait_seconds": 0},
                )
            ],
            provider="fake",
        )

    engine, _fake = build_test_engine([_collect, {"content": "PARENT-DONE"}])
    events = EventStore(tmp_path / "engine-events", enabled=True)
    runner = engine.registry.get("spawn_subagent")._runner
    _attach_shared_events(engine, runner, events)
    parent = engine.session.create()
    child, _generation, _result_id = _terminal_child(runner, parent)
    child_box["id"] = child
    assert runner.topology_snapshot(child)["settlement_state"] == "uncollected"

    result = engine.run(parent, "collect child")
    assert result.final_answer == "PARENT-DONE"
    assert runner.topology_snapshot(child)["settlement_state"] == "collected"

    relevant = [
        event
        for event in events.read(parent)
        if (
            event.type == "message.appended"
            and event.payload.get("tool_name") == "subagent_result"
        )
        or (
            event.type == "tool.execution.receipt_committed"
            and event.payload.get("tool_name") == "subagent_result"
        )
    ]
    assert [event.type for event in relevant] == [
        "message.appended",
        "tool.execution.receipt_committed",
    ]
    assert relevant[0].payload["metadata"]["subagent_settlement"]["child_id"] == child

    recovered = SubAgentRunner(llm=_NoopLLM(), registry=ToolRegistry(), session_store=engine.session)  # type: ignore[arg-type]
    assert recovered.topology_snapshot(child)["settlement_state"] == "collected"


def test_parent_receipt_commit_failure_never_settles(build_test_engine, tmp_path, monkeypatch) -> None:
    from llm_loop.llm.client import LLMResponse

    child_box: dict[str, str] = {}

    def _collect(_calls):  # noqa: ANN001, ANN202
        return LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="parent-collect-fail",
                    name="subagent_result",
                    arguments={"child_id": child_box["id"], "wait_seconds": 0},
                )
            ],
            provider="fake",
        )

    engine, _fake = build_test_engine([_collect, {"content": "PARENT-DONE"}])
    events = EventStore(tmp_path / "engine-events-fail", enabled=True)
    runner = engine.registry.get("spawn_subagent")._runner
    _attach_shared_events(engine, runner, events)
    parent = engine.session.create()
    child, _generation, _result_id = _terminal_child(runner, parent)
    child_box["id"] = child

    original_append = events.append

    def _drop_commit(session_id, event_type, payload):  # noqa: ANN001, ANN202
        if session_id == parent and event_type == "tool.execution.receipt_committed":
            return None
        return original_append(session_id, event_type, payload)

    monkeypatch.setattr(events, "append", _drop_commit)
    result = engine.run(parent, "collect child")
    assert result.final_answer == "PARENT-DONE"
    assert runner.topology_snapshot(child)["settlement_state"] == "uncollected"
    commits = [
        e
        for e in events.read(parent)
        if e.type == "tool.execution.receipt_committed"
        and e.payload.get("tool_name") == "subagent_result"
    ]
    assert commits == []


def test_wal_recovery_settles_actual_runner_exactly_once(tmp_path) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    store = SessionStore(tmp_path / "sessions", event_store=events)
    runner = SubAgentRunner(llm=_NoopLLM(), registry=ToolRegistry(), session_store=store)  # type: ignore[arg-type]
    parent = store.create()
    child, generation, result_id = _terminal_child(runner, parent)
    call = ToolCall(
        id="collect-recover-runner",
        name="subagent_result",
        arguments={"child_id": child, "wait_seconds": 0},
    )
    sess = store.load(parent)
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
    journal = ToolExecutionJournal(
        event_store=events,
        result_root=tmp_path / "tool-results",
        session_store=store,
        receipt_committed_hook=runner.settle_committed_receipt,
    )
    execution_id = journal.declared(sess, call, round_no=1)
    assert execution_id
    assert journal.started(parent, execution_id=execution_id, round_no=1, call=call)
    receipt = Message(
        role="tool",
        content="[状态: success] CHILD-RESULT",
        source=MessageSource.TOOL,
        tool_call_id=call.id,
        tool_name=call.name,
        status=ToolResultStatus.SUCCESS,
        metadata={
            "subagent_settlement": {
                "child_id": child,
                "parent_id": parent,
                "generation": generation,
                "result_id": result_id,
            }
        },
    )
    result_sha = journal.finished(
        parent,
        execution_id=execution_id,
        round_no=1,
        call=call,
        tool_message=receipt,
    )
    assert result_sha
    assert runner.topology_snapshot(child)["settlement_state"] == "uncollected"

    assert journal.recover(parent, sess) == 1
    assert runner.topology_snapshot(child)["settlement_state"] == "collected"
    assert journal.recover(parent, sess) == 0
    assert runner.topology_snapshot(child)["settlement_state"] == "collected"
    commits = [
        event
        for event in events.read(parent)
        if event.type == "tool.execution.receipt_committed"
        and event.payload.get("tool_call_id") == call.id
    ]
    assert len(commits) == 1
    assert commits[0].payload["recovered"] is True


def test_commit_event_without_durable_parent_receipt_message_does_not_settle(tmp_path) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    store = SessionStore(tmp_path / "sessions", event_store=events)
    runner = SubAgentRunner(llm=_NoopLLM(), registry=ToolRegistry(), session_store=store)  # type: ignore[arg-type]
    parent = store.create()
    child, generation, result_id = _terminal_child(runner, parent)
    receipt = Message(
        role="tool",
        content="[状态: success] CHILD-RESULT",
        source=MessageSource.TOOL,
        tool_call_id="collect-no-message-event",
        tool_name="subagent_result",
        status=ToolResultStatus.SUCCESS,
        metadata={
            "subagent_settlement": {
                "child_id": child,
                "parent_id": parent,
                "generation": generation,
                "result_id": result_id,
            }
        },
    )
    journal = ToolExecutionJournal(
        event_store=events,
        result_root=tmp_path / "tool-results",
        session_store=store,
        receipt_committed_hook=runner.settle_committed_receipt,
    )
    assert journal.receipt_committed(
        parent,
        execution_id="exec-without-message-event",
        round_no=1,
        tool_call_id=receipt.tool_call_id or "",
        tool_name=receipt.tool_name or "",
        tool_message=receipt,
    )
    assert runner.topology_snapshot(child)["settlement_state"] == "uncollected"

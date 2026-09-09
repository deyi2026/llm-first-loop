from __future__ import annotations

from types import SimpleNamespace

from llm_loop.core.loop.events import _EventsMixin
from llm_loop.core.message import Message, MessageSource, ToolCall, ToolResultStatus
from llm_loop.core.session import SessionStore
from llm_loop.event_log.store import EventStore


class _Harness(_EventsMixin):
    def __init__(self, tmp_path) -> None:
        self.settings = SimpleNamespace(data_dir=str(tmp_path))
        self._event_store = EventStore(tmp_path / "events", enabled=True)
        self.session = SessionStore(tmp_path / "sessions")
        self.actions: list[tuple[str, str, str]] = []
        self.status = None

    def _record_action(self, stage: str, action: str, detail: str = "") -> None:
        self.actions.append((stage, action, detail))


def _assistant_decl(call: ToolCall) -> Message:
    return Message(
        role="assistant",
        content="",
        source=MessageSource.USER,
        tool_calls=[
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": '{"path":"x"}'},
            }
        ],
    )


def _session_with_decl(h: _Harness, call: ToolCall):
    sid = h.session.create()
    sess = h.session.load(sid)
    sess.messages.append(Message(role="user", content="Q", source=MessageSource.USER))
    decl = _assistant_decl(call)
    sess.messages.append(decl)
    h.session.save(sess)
    h._append_message_event(sess, decl)
    execution_id = h._tool_execution_declared(sess, call, round_no=1)
    return sess, execution_id


def _receipts(sess, call_id: str) -> list[Message]:
    return [m for m in sess.messages if m.role == "tool" and m.tool_call_id == call_id]


def test_declared_not_started_recovers_as_not_executed_without_reexecution(tmp_path) -> None:
    h = _Harness(tmp_path)
    call = ToolCall(id="call-declared", name="read_file", arguments={"path": "x"})
    sess, _execution_id = _session_with_decl(h, call)

    assert h._recover_inflight_tool_executions(sess.session_id, sess) == 1
    receipt = _receipts(sess, call.id)[0]
    assert "executed=false" in receipt.content
    assert "restart_before_execution" in receipt.content
    assert receipt.metadata["tool_execution_recovery"]["auto_reexecuted"] is False


def test_started_not_finished_recovers_as_unknown_and_never_reexecutes(tmp_path) -> None:
    h = _Harness(tmp_path)
    call = ToolCall(id="call-started", name="execute_command", arguments={"command": "echo x"})
    sess, execution_id = _session_with_decl(h, call)
    h._tool_execution_started(sess.session_id, execution_id=execution_id, round_no=1, call=call)

    assert h._recover_inflight_tool_executions(sess.session_id, sess) == 1
    receipt = _receipts(sess, call.id)[0]
    assert "execution_outcome=unknown_after_restart" in receipt.content
    assert "auto_reexecuted=false" in receipt.content
    assert receipt.metadata["tool_execution_recovery"]["state"] == "started_outcome_unknown"


def test_finished_without_receipt_restores_exact_tool_message_from_sidecar(tmp_path) -> None:
    h = _Harness(tmp_path)
    call = ToolCall(id="call-finished", name="read_file", arguments={"path": "x"})
    sess, execution_id = _session_with_decl(h, call)
    h._tool_execution_started(sess.session_id, execution_id=execution_id, round_no=1, call=call)
    expected = Message(
        role="tool",
        content="[状态: success] EXACT-RESULT",
        source=MessageSource.TOOL,
        tool_call_id=call.id,
        tool_name=call.name,
        status=ToolResultStatus.SUCCESS,
        duration_ms=12.5,
        metadata={"exact": {"value": 1}},
    )
    result_sha = h._tool_execution_finished(
        sess.session_id,
        execution_id=execution_id,
        round_no=1,
        call=call,
        tool_message=expected,
    )
    sidecar = h._tool_execution_result_path(sess.session_id, execution_id)
    assert sidecar.exists()

    assert h._recover_inflight_tool_executions(sess.session_id, sess) == 1
    receipt = _receipts(sess, call.id)[0]
    assert receipt.content == expected.content
    assert receipt.source is MessageSource.TOOL
    assert receipt.status is ToolResultStatus.SUCCESS
    assert receipt.duration_ms == 12.5
    assert receipt.metadata == expected.metadata
    assert not sidecar.exists()
    committed = [
        e
        for e in h._event_store.read(sess.session_id)
        if e.type == "tool.execution.receipt_committed"
    ]
    assert committed and committed[-1].payload["result_state_sha256"] == result_sha
    assert committed[-1].payload["recovered"] is True


def test_existing_receipt_only_settles_wal_and_is_not_duplicated(tmp_path) -> None:
    h = _Harness(tmp_path)
    call = ToolCall(id="call-existing", name="read_file", arguments={"path": "x"})
    sess, execution_id = _session_with_decl(h, call)
    h._tool_execution_started(sess.session_id, execution_id=execution_id, round_no=1, call=call)
    receipt = Message(
        role="tool",
        content="[状态: success] ALREADY-DURABLE",
        source=MessageSource.TOOL,
        tool_call_id=call.id,
        tool_name=call.name,
        status=ToolResultStatus.SUCCESS,
    )
    result_sha = h._tool_execution_finished(
        sess.session_id,
        execution_id=execution_id,
        round_no=1,
        call=call,
        tool_message=receipt,
    )
    sess.messages.append(receipt)
    h._append_message_event(sess, receipt)
    h.session.save(sess)

    assert h._recover_inflight_tool_executions(sess.session_id, sess) == 0
    assert len(_receipts(sess, call.id)) == 1
    committed = [
        e
        for e in h._event_store.read(sess.session_id)
        if e.type == "tool.execution.receipt_committed"
    ]
    assert committed[-1].payload["result_state_sha256"] == result_sha
    assert committed[-1].payload["recovered"] is True


def test_real_engine_wal_normal_path_is_declared_started_finished_committed(
    build_test_engine, tmp_path
) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("WAL-RESULT", encoding="utf-8")
    call = ToolCall(id="call-normal", name="read_file", arguments={"path": str(target)})
    engine, _fake = build_test_engine(
        [
            {"content": "", "tool_calls": [call]},
            {"content": "DONE"},
        ]
    )
    es = EventStore(tmp_path / "normal-events", enabled=True)
    engine._event_store = es  # noqa: SLF001 — integration WAL source
    sid = engine.session.create()

    result = engine.run(sid, "读取 sample")
    assert result.final_answer == "DONE"
    wal = [e for e in es.read(sid) if e.type.startswith("tool.execution.")]
    assert [e.type for e in wal] == [
        "tool.execution.declared",
        "tool.execution.started",
        "tool.execution.finished",
        "tool.execution.receipt_committed",
    ]
    execution_ids = {e.payload["execution_id"] for e in wal}
    assert len(execution_ids) == 1
    execution_id = next(iter(execution_ids))
    assert not engine._tool_execution_result_path(sid, execution_id).exists()  # noqa: SLF001


def test_real_engine_recovers_unknown_execution_before_new_user_message(
    build_test_engine, tmp_path
) -> None:
    engine, fake = build_test_engine([{"content": "CONTINUED"}])
    es = EventStore(tmp_path / "restart-order-events", enabled=True)
    engine._event_store = es  # noqa: SLF001
    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.messages.append(Message(role="user", content="OLD", source=MessageSource.USER))
    call = ToolCall(id="call-crash", name="execute_command", arguments={"command": "side-effect"})
    sess.messages.append(_assistant_decl(call))
    engine.session.save(sess)
    execution_id = engine._tool_execution_declared(sess, call, round_no=1)  # noqa: SLF001
    engine._tool_execution_started(  # noqa: SLF001
        sid, execution_id=execution_id, round_no=1, call=call
    )

    result = engine.run(sid, "继续，但不要重复执行")
    assert result.final_answer == "CONTINUED"
    wire = fake.calls[-1]["messages"]
    decl_index = next(
        i
        for i, message in enumerate(wire)
        if message.get("role") == "assistant"
        and any(tc.get("id") == call.id for tc in (message.get("tool_calls") or []))
    )
    receipt_index = next(
        i
        for i, message in enumerate(wire)
        if message.get("role") == "tool" and message.get("tool_call_id") == call.id
    )
    current_index = next(
        i
        for i, message in enumerate(wire)
        if message.get("role") == "user" and message.get("content") == "继续，但不要重复执行"
    )
    assert decl_index < receipt_index < current_index
    assert "execution_outcome=unknown_after_restart" in wire[receipt_index]["content"]
    assert "auto_reexecuted=false" in wire[receipt_index]["content"]


def test_wal_started_write_failure_prevents_tool_execution(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    class _MutatingProbe:
        name = "mutating_probe"
        description = "mutating probe"
        parameters = {"type": "object", "properties": {}}

        def __init__(self) -> None:
            self.count = 0

        def execute(self, **_kwargs):
            self.count += 1
            return "MUTATED"

    call = ToolCall(id="call-wal-fail", name="mutating_probe", arguments={})
    engine, fake = build_test_engine(
        [
            {"content": "", "tool_calls": [call]},
            {"content": "SAFE-FINAL"},
        ]
    )
    probe = _MutatingProbe()
    engine.registry.register(probe)
    es = EventStore(tmp_path / "wal-fail-events", enabled=True)
    engine._event_store = es  # noqa: SLF001
    original_append = es.append

    def flaky_append(session_id, event_type, payload):
        if event_type == "tool.execution.started":
            return None
        return original_append(session_id, event_type, payload)

    monkeypatch.setattr(es, "append", flaky_append)
    sid = engine.session.create()
    result = engine.run(sid, "执行 probe")

    assert result.final_answer == "SAFE-FINAL"
    assert probe.count == 0
    tool_messages = [m for m in fake.calls[-1]["messages"] if m.get("role") == "tool"]
    assert tool_messages
    assert "wal_start_not_durable" in tool_messages[-1]["content"]


def test_wal_declaration_write_failure_prevents_tool_execution(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    class _MutatingProbe:
        name = "mutating_probe_decl"
        description = "mutating probe declaration"
        parameters = {"type": "object", "properties": {}}

        def __init__(self) -> None:
            self.count = 0

        def execute(self, **_kwargs):
            self.count += 1
            return "MUTATED"

    call = ToolCall(id="call-wal-decl-fail", name="mutating_probe_decl", arguments={})
    engine, fake = build_test_engine(
        [
            {"content": "", "tool_calls": [call]},
            {"content": "SAFE-FINAL"},
        ]
    )
    probe = _MutatingProbe()
    engine.registry.register(probe)
    es = EventStore(tmp_path / "wal-decl-fail-events", enabled=True)
    engine._event_store = es  # noqa: SLF001
    original_append = es.append

    def flaky_append(session_id, event_type, payload):
        if event_type == "tool.execution.declared":
            return None
        return original_append(session_id, event_type, payload)

    monkeypatch.setattr(es, "append", flaky_append)
    sid = engine.session.create()
    result = engine.run(sid, "执行 declaration probe")

    assert result.final_answer == "SAFE-FINAL"
    assert probe.count == 0
    tool_messages = [m for m in fake.calls[-1]["messages"] if m.get("role") == "tool"]
    assert tool_messages
    assert "wal_declaration_unavailable" in tool_messages[-1]["content"]


def test_assistant_tool_declaration_event_failure_prevents_tool_execution(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    class _MutatingProbe:
        name = "mutating_probe_assistant_decl"
        description = "mutating probe assistant declaration"
        parameters = {"type": "object", "properties": {}}

        def __init__(self) -> None:
            self.count = 0

        def execute(self, **_kwargs):
            self.count += 1
            return "MUTATED"

    call = ToolCall(
        id="call-assistant-decl-fail", name="mutating_probe_assistant_decl", arguments={}
    )
    engine, fake = build_test_engine(
        [
            {"content": "", "tool_calls": [call]},
            {"content": "SAFE-FINAL"},
        ]
    )
    probe = _MutatingProbe()
    engine.registry.register(probe)
    es = EventStore(tmp_path / "assistant-decl-fail-events", enabled=True)
    engine._event_store = es  # noqa: SLF001
    original_append = es.append

    def flaky_append(session_id, event_type, payload):
        if (
            event_type == "message.appended"
            and payload.get("role") == "assistant"
            and payload.get("tool_calls")
        ):
            return None
        return original_append(session_id, event_type, payload)

    monkeypatch.setattr(es, "append", flaky_append)
    sid = engine.session.create()
    result = engine.run(sid, "执行 assistant declaration probe")

    assert result.final_answer == "SAFE-FINAL"
    assert probe.count == 0
    tool_messages = [m for m in fake.calls[-1]["messages"] if m.get("role") == "tool"]
    assert tool_messages
    assert "wal_declaration_unavailable" in tool_messages[-1]["content"]

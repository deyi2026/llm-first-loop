from __future__ import annotations

import threading

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.core.run_context import current_run_generation, current_session_id
from llm_loop.core.session import SessionStore
from llm_loop.core.tool_execution_journal import ToolExecutionJournal
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
        return LLMResponse(content="done", tool_calls=[], provider="fake")


class _LateTool:
    name = "late_tool"
    description = "P3 deterministic late-result probe"
    parameters = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.observed_generations: list[str] = []

    def execute(self):  # noqa: ANN201
        self.observed_generations.append(current_run_generation.get())
        self.entered.set()
        assert self.release.wait(timeout=5.0)
        self.finished.set()
        return "A1-LATE-SUCCESS"


def _subagent_runner(tmp_path, llm):  # noqa: ANN001
    events = EventStore(tmp_path / "events", enabled=True)
    store = SessionStore(tmp_path / "sessions", event_store=events)
    return SubAgentRunner(llm=llm, registry=ToolRegistry(), session_store=store)  # type: ignore[arg-type]


def test_late_parent_cancel_is_fenced_by_origin_run_generation(tmp_path) -> None:
    llm = _BlockingLLM()
    runner = _subagent_runner(tmp_path, llm)
    parent = "parent-cross-run"

    sid_tok = current_session_id.set(parent)
    g1_tok = current_run_generation.set("run-g1")
    try:
        started = runner.start("long child", depth=0)
    finally:
        current_run_generation.reset(g1_tok)
        current_session_id.reset(sid_tok)
    assert started["accepted"] is True
    child = str(started["child_id"])
    assert llm.entered.wait(timeout=2.0)

    sid_tok = current_session_id.set(parent)
    g2_tok = current_run_generation.set("run-g2")
    try:
        assert runner.cancel_parent(parent) == 0
    finally:
        current_run_generation.reset(g2_tok)
        current_session_id.reset(sid_tok)
    with runner._children_guard:  # noqa: SLF001
        assert runner._cancel_events[child].is_set() is False  # noqa: SLF001

    sid_tok = current_session_id.set(parent)
    g1_tok = current_run_generation.set("run-g1")
    try:
        assert runner.cancel_parent(parent) == 1
    finally:
        current_run_generation.reset(g1_tok)
        current_session_id.reset(sid_tok)

    llm.release.set()


def test_tool_wal_generation_is_part_of_identity_and_durable_payload(tmp_path) -> None:
    events = EventStore(tmp_path / "events", enabled=True)
    store = SessionStore(tmp_path / "sessions", event_store=events)
    journal = ToolExecutionJournal(
        event_store=events,
        result_root=tmp_path / "tool-results",
        session_store=store,
    )
    sid = store.create()
    sess = store.load(sid)
    call = ToolCall(id="same-call", name="read_file", arguments={"path": "x"})

    tok = current_run_generation.set("run-g1")
    try:
        first = journal.declared(sess, call, round_no=1)
    finally:
        current_run_generation.reset(tok)
    tok = current_run_generation.set("run-g2")
    try:
        second = journal.declared(sess, call, round_no=1)
    finally:
        current_run_generation.reset(tok)

    assert first != second
    declared = [e for e in events.read(sid) if e.type == "tool.execution.declared"]
    assert [e.payload["origin_run_generation"] for e in declared[-2:]] == ["run-g1", "run-g2"]


def test_a1_timeout_then_a2_start_discards_a1_late_tool_result() -> None:
    """P3 Gate1: timeout returns A1 receipt; its worker may finish late but cannot become A2 truth."""
    reg = ToolRegistry(tool_timeout_s=0.02)
    tool = _LateTool()
    reg.register(tool)
    captured: list[str] = []
    reg.set_evidence_shadow_hook(lambda _call, result: captured.append(result.content))

    sid_tok = current_session_id.set("same-session")
    g1_tok = current_run_generation.set("run-A1")
    try:
        result = reg.execute(ToolCall(id="late-call", name=tool.name, arguments={}))
    finally:
        current_run_generation.reset(g1_tok)
        current_session_id.reset(sid_tok)

    assert result.status is ToolResultStatus.TIMEOUT
    assert tool.entered.is_set()
    assert captured == []

    # A2 has already become the active same-session run when A1's uncooperative worker exits.
    sid_tok = current_session_id.set("same-session")
    g2_tok = current_run_generation.set("run-A2")
    try:
        tool.release.set()
        assert tool.finished.wait(timeout=2.0)
        # No post-timeout completion callback exists: A1's late success is not captured/projected
        # as an A2 tool result.  The worker also retained its exact origin ContextVar.
        assert captured == []
        assert current_run_generation.get() == "run-A2"
    finally:
        current_run_generation.reset(g2_tok)
        current_session_id.reset(sid_tok)

    assert tool.observed_generations == ["run-A1"]


def test_timed_out_a1_edit_worker_cannot_commit_after_a2_generation_starts(tmp_path) -> None:
    """P3: TIMEOUT returns control, but the still-running worker must lose mutation authority."""
    from llm_loop.core.message import ToolResultStatus
    from llm_loop.tools.builtin.edit_file import EditFileTool

    class _DelayedEdit(EditFileTool):
        registry_timeout_s = 0.05

        def __init__(self) -> None:
            super().__init__()
            self.entered = threading.Event()
            self.release = threading.Event()
            self.finished = threading.Event()

        def execute(self, **kwargs):  # noqa: ANN003, ANN201
            self.entered.set()
            assert self.release.wait(timeout=3.0)
            try:
                return super().execute(**kwargs)
            finally:
                self.finished.set()

    events = EventStore(tmp_path / "events-timeout", enabled=True)
    sessions = SessionStore(tmp_path / "sessions-timeout", event_store=events)
    sid = sessions.create()
    journal = ToolExecutionJournal(
        event_store=events,
        result_root=tmp_path / "tool-results-timeout",
        session_store=sessions,
    )
    target = tmp_path / "target.txt"
    target.write_text("BEFORE\n", encoding="utf-8")
    call = ToolCall(
        id="late-edit-call",
        name="edit_file",
        arguments={
            "path": str(target),
            "old_string": "BEFORE",
            "new_string": "AFTER",
        },
    )
    tool = _DelayedEdit()
    registry = ToolRegistry(tool_timeout_s=0.05)
    registry.register(tool)

    sid_tok = current_session_id.set(sid)
    g1_tok = current_run_generation.set("run-g1")
    run1_token = sessions._activate_run_save_token(sid, run_generation="run-g1")  # noqa: SLF001
    try:
        sess = sessions.load(sid)
        execution_id = journal.declared(sess, call, round_no=1)
        assert execution_id
        assert journal.started(sid, execution_id=execution_id, round_no=1, call=call)
        with journal.effect_bindings(
            session_id=sid,
            execution_ids={call.id: execution_id},
            round_no=1,
            calls=[call],
            workspace_root=str(tmp_path),
        ):
            result = registry.execute(call)
        assert result.status is ToolResultStatus.TIMEOUT
        assert tool.entered.is_set()
    finally:
        current_run_generation.reset(g1_tok)
        current_session_id.reset(sid_tok)
        sessions._deactivate_run_save_token(sid, run1_token)  # noqa: SLF001

    run2_token = sessions._activate_run_save_token(sid, run_generation="run-g2")  # noqa: SLF001
    tool.release.set()
    try:
        assert tool.finished.wait(timeout=3.0)
        assert target.read_text(encoding="utf-8") == "BEFORE\n"
    finally:
        sessions._deactivate_run_save_token(sid, run2_token)  # noqa: SLF001

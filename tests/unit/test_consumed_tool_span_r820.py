from __future__ import annotations

from types import SimpleNamespace

from llm_loop.config import Settings
from llm_loop.core.episode_history import (
    CLOSED_TOOL_SPAN_REF_KEY,
    CONSUMED_TOOL_SPAN_REF_KEY,
    backfill_closed_tool_attempts,
    backfill_consumed_tool_spans,
    provider_view_without_resolved_episodes,
)
from llm_loop.core.loop import LoopEngine
from llm_loop.core.message import Message, MessageSource, ToolResultStatus
from llm_loop.core.session import SessionStore
from llm_loop.core.trace_leak.ingress_token import (
    delegate_ingress,
    issue_ingress,
    issue_test_ingress,
)
from llm_loop.event_log.model import Event, build_message_payload
from llm_loop.event_log.store import EventStore
from llm_loop.introspection.search import RecordSearcher
from llm_loop.llm.client import LLMResponse
from llm_loop.memory.episode import (
    EpisodeStore,
    stable_closed_tool_span_ref,
    stable_tool_span_ref,
)
from llm_loop.tools.registry import ToolRegistry


def _user(text: str) -> Message:
    return Message(role="user", content=text, source=MessageSource.USER)


def _decl(call_id: str, *, name: str = "read_file") -> Message:
    return Message(
        role="assistant",
        content="",
        source=MessageSource.USER,
        model_used="fake/model",
        tool_calls=[{"id": call_id, "name": name, "arguments": {"path": "x"}}],
    )


def _tool(call_id: str, text: str = "TOOL-SECRET", *, name: str = "read_file") -> Message:
    return Message(
        role="tool",
        content=text,
        source=MessageSource.TOOL,
        tool_call_id=call_id,
        tool_name=name,
        status=ToolResultStatus.SUCCESS,
    )


def _consumer(text: str = "MODEL-CONSUMER") -> Message:
    return Message(
        role="assistant",
        content=text,
        source=MessageSource.USER,
        model_used="fake/model",
        metadata={"answer_origin": "model"},
    )


def _program_terminal(reason: str = "llm_error") -> Message:
    return Message(
        role="assistant",
        content="",
        source=MessageSource.SYSTEM,
        model_used="fake/model",
        metadata={
            "answer_origin": "program",
            "run_end_reason": reason,
            "program_final_placeholder": True,
        },
    )


def _interrupted(reason: str = "llm_error") -> Message:
    return Message(
        role="assistant",
        content="PARTIAL\n[截断标注] reason=llm_error",
        source=MessageSource.SYSTEM,
        reasoning_content="THINK-TAIL",
        model_used="fake/model",
        metadata={
            "answer_origin": "program",
            "run_end_reason": reason,
            "llm_interrupted": True,
            "interrupted_text_tail": "PARTIAL",
            "interrupted_reasoning_tail": "THINK-TAIL",
        },
    )


def _event(seq: int, typ: str, payload: dict) -> Event:
    return Event(
        event_id=f"e{seq}",
        session_id="sid",
        seq=seq,
        type=typ,
        ts="2026-09-04T00:00:00+00:00",
        payload=payload,
    )


def _message_event(seq: int, index: int, message: Message) -> Event:
    return _event(
        seq,
        "message.appended",
        build_message_payload(
            index=index,
            role=message.role,
            content=message.content,
            source=str(message.source),
            tool_call_id=message.tool_call_id,
            status=str(message.status) if message.status is not None else None,
            tool_name=message.tool_name,
            error_detail=message.error_detail,
            tool_calls=message.tool_calls,
            reasoning_content=message.reasoning_content,
            metadata=message.metadata,
        ),
    )


class _Events:
    last_read_skipped = 0

    def __init__(self, events: list[Event]) -> None:
        self.events = events

    def read(self, _session_id: str) -> list[Event]:
        return list(self.events)


def _closed_events(messages: list[Message], reason: str = "llm_error") -> _Events:
    events = [_message_event(i + 1, i, message) for i, message in enumerate(messages)]
    events.append(
        _event(
            len(events) + 1,
            "run.end",
            {
                "session_id": "sid",
                "reason": reason,
                "rounds": 1,
                "tokens_in": 0,
                "tokens_out": 0,
                "cache_hit": 0,
                "duration_ms": 1,
                "model_used": "fake/model",
                "truncated": False,
                "answer_preview": "",
            },
        )
    )
    return _Events(events)


def _write_closed_event_store(
    store: EventStore,
    session_id: str,
    messages: list[Message],
    reason: str = "llm_error",
) -> None:
    for index, message in enumerate(messages):
        store.append(
            session_id,
            "message.appended",
            build_message_payload(
                index=index,
                role=message.role,
                content=message.content,
                source=str(message.source),
                tool_call_id=message.tool_call_id,
                status=str(message.status) if message.status is not None else None,
                tool_name=message.tool_name,
                error_detail=message.error_detail,
                tool_calls=message.tool_calls,
                reasoning_content=message.reasoning_content,
                metadata=message.metadata,
            ),
        )
    store.append(
        session_id,
        "run.end",
        {
            "session_id": session_id,
            "reason": reason,
            "rounds": 1,
            "tokens_in": 0,
            "tokens_out": 0,
            "cache_hit": 0,
            "duration_ms": 1,
            "model_used": "fake/model",
            "truncated": False,
            "answer_preview": "",
        },
    )


def test_episode_store_indexes_consumed_tool_span_without_claiming_episode_resolution(
    tmp_path,
) -> None:
    store = EpisodeStore(tmp_path / "episodes")
    user, decl, tool, consumer = _user("QUESTION"), _decl("tc-1"), _tool("tc-1"), _consumer()
    ref = stable_tool_span_ref("sid", user, 0, 3, ["tc-1"])

    result = store.index_tool_span(
        "sid",
        ref=ref,
        user_seq=0,
        consumer_seq=3,
        raw_messages=[user, decl, tool, consumer],
    )

    assert result.ref == ref and result.created is True
    entry = store.get("sid", ref)
    assert entry is not None
    assert entry["entry_kind"] == "tool_span"
    assert entry["consumer_seq"] == 3
    hydrated = store.hydrate("sid", ref, max_chars=12000)
    assert hydrated is not None
    assert "QUESTION" in hydrated["content"]
    assert "TOOL-SECRET" in hydrated["content"]
    assert "MODEL-CONSUMER" in hydrated["content"]
    hits = store.search("sid", "TOOL-SECRET", 10)
    assert hits and hits[0]["ref"] == ref
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", episode_store=store)
    record_hits = searcher.search(kind="episode", query="TOOL-SECRET", limit=10, session_id="sid")
    assert record_hits and record_hits[0]["ref"] == ref


def test_consumed_tool_span_retires_only_raw_protocol_after_durable_index(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "episodes")
    user, decl, tool, consumer = _user("QUESTION"), _decl("tc-1"), _tool("tc-1"), _consumer()
    sess = SimpleNamespace(session_id="sid", messages=[user, decl, tool, consumer])

    refs = backfill_consumed_tool_spans(store, sess)

    assert len(refs) == 1 and refs[0].startswith("toolspan:sid:")
    assert not user.metadata.get(CONSUMED_TOOL_SPAN_REF_KEY)
    assert not consumer.metadata.get(CONSUMED_TOOL_SPAN_REF_KEY)
    assert decl.metadata[CONSUMED_TOOL_SPAN_REF_KEY] == refs[0]
    assert tool.metadata[CONSUMED_TOOL_SPAN_REF_KEY] == refs[0]
    projected = provider_view_without_resolved_episodes(sess.messages)
    assert projected == [user, consumer]
    hydrated = store.hydrate("sid", refs[0], max_chars=12000)
    assert hydrated is not None and "TOOL-SECRET" in hydrated["content"]


def test_multiple_tool_rounds_share_one_consumed_span(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "episodes")
    user = _user("QUESTION")
    d1, t1 = _decl("tc-1"), _tool("tc-1", "ONE")
    d2, t2 = _decl("tc-2", name="web_fetch"), _tool("tc-2", "TWO", name="web_fetch")
    consumer = _consumer()
    sess = SimpleNamespace(session_id="sid", messages=[user, d1, t1, d2, t2, consumer])

    refs = backfill_consumed_tool_spans(store, sess)

    assert len(refs) == 1
    assert {m.metadata.get(CONSUMED_TOOL_SPAN_REF_KEY) for m in (d1, t1, d2, t2)} == {refs[0]}
    assert provider_view_without_resolved_episodes(sess.messages) == [user, consumer]
    hydrated = store.hydrate("sid", refs[0], max_chars=12000)
    assert hydrated is not None
    assert "ONE" in hydrated["content"] and "TWO" in hydrated["content"]


def test_current_or_incomplete_tool_followup_remains_provider_visible(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "episodes")
    user, decl, tool = _user("QUESTION"), _decl("tc-1"), _tool("tc-1")
    sess = SimpleNamespace(session_id="sid", messages=[user, decl, tool])

    assert backfill_consumed_tool_spans(store, sess) == []
    assert provider_view_without_resolved_episodes(sess.messages) == sess.messages

    # Missing receipt is also fail-closed even if a later assistant exists.
    broken = SimpleNamespace(
        session_id="sid2",
        messages=[_user("Q"), _decl("tc-missing"), _consumer()],
    )
    assert backfill_consumed_tool_spans(store, broken) == []
    assert provider_view_without_resolved_episodes(broken.messages) == broken.messages


def test_program_final_is_not_a_tool_consumer(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "episodes")
    program = Message(
        role="assistant",
        content="[LLM 调用异常] network down",
        source=MessageSource.SYSTEM,
        model_used="fake/model",
        metadata={"answer_origin": "program", "run_end_reason": "llm_error"},
    )
    sess = SimpleNamespace(
        session_id="sid",
        messages=[_user("QUESTION"), _decl("tc-1"), _tool("tc-1"), program],
    )

    assert backfill_consumed_tool_spans(store, sess) == []
    assert provider_view_without_resolved_episodes(sess.messages) == sess.messages


def test_closed_failed_tool_attempt_retires_raw_protocol_only_after_durable_run_end(
    tmp_path,
) -> None:
    store = EpisodeStore(tmp_path / "episodes")
    user = _user("QUESTION")
    decl = _decl("tc-1")
    decl.reasoning_content = "PRIVATE-REASONING"
    decl.metadata = {
        "provider_replay": {
            "provider": "minimax",
            "fields": {
                "reasoning_details": [
                    {
                        "type": "reasoning.text",
                        "text": "PRIVATE-REASONING",
                        "signature": "SECRET-SIG",
                    }
                ]
            },
        }
    }
    tool = _tool("tc-1", "TOOL-SECRET")
    terminal = _program_terminal("llm_error")
    sess = SimpleNamespace(session_id="sid", messages=[user, decl, tool, terminal])

    refs = backfill_closed_tool_attempts(
        store, sess, event_store=_closed_events(sess.messages, "llm_error")
    )

    assert len(refs) == 1 and refs[0].startswith("closedspan:sid:")
    assert not user.metadata.get(CLOSED_TOOL_SPAN_REF_KEY)
    assert not terminal.metadata.get(CLOSED_TOOL_SPAN_REF_KEY)
    assert decl.metadata[CLOSED_TOOL_SPAN_REF_KEY] == refs[0]
    assert tool.metadata[CLOSED_TOOL_SPAN_REF_KEY] == refs[0]
    assert provider_view_without_resolved_episodes(sess.messages) == [user, terminal]

    entry = store.get("sid", refs[0])
    assert entry is not None
    assert entry["entry_kind"] == "closed_tool_span"
    assert entry["terminal_reason"] == "llm_error"
    assert entry["terminal_seq"] == 3
    assert entry["final_answer"] == ""
    hits = store.search("sid", "llm_error", 10)
    assert hits and hits[0]["ref"] == refs[0]
    assert "type=closed_tool_span" in hits[0]["summary"]
    hydrated = store.hydrate("sid", refs[0], max_chars=12000)
    assert hydrated is not None
    assert "QUESTION" in hydrated["content"]
    assert "TOOL-SECRET" in hydrated["content"]
    assert "PRIVATE-REASONING" not in hydrated["content"]
    assert "SECRET-SIG" not in hydrated["content"]


def test_latest_interrupted_tool_attempt_gets_one_human_resume_window(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "episodes")
    user = _user("QUESTION")
    decl = _decl("tc-1")
    tool = _tool("tc-1", "TOOL-SECRET")
    interrupted = _interrupted("llm_error")
    terminal = _program_terminal("llm_error")
    prior = [user, decl, tool, interrupted, terminal]
    events = _closed_events(prior, "llm_error")
    sess = SimpleNamespace(session_id="sid", messages=list(prior))

    # Before the immediately next genuine human ingress is appended, this is the
    # latest human turn and its interrupted tool state remains available for one
    # continuity attempt.
    assert backfill_closed_tool_attempts(store, sess, event_store=events) == []
    assert not decl.metadata.get(CLOSED_TOOL_SPAN_REF_KEY)
    assert not tool.metadata.get(CLOSED_TOOL_SPAN_REF_KEY)

    # On the following human boundary the old turn is no longer the latest human;
    # if still unconsumed it becomes an ordinary closed attempt and retires.
    sess.messages.append(_user("NEXT"))
    refs = backfill_closed_tool_attempts(store, sess, event_store=events)
    assert len(refs) == 1
    assert decl.metadata[CLOSED_TOOL_SPAN_REF_KEY] == refs[0]
    assert tool.metadata[CLOSED_TOOL_SPAN_REF_KEY] == refs[0]


def test_closed_attempt_without_durable_proof_remains_provider_visible(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "episodes")
    user, decl, tool, terminal = _user("Q"), _decl("tc-1"), _tool("tc-1"), _program_terminal()
    sess = SimpleNamespace(session_id="sid", messages=[user, decl, tool, terminal])

    assert backfill_closed_tool_attempts(store, sess, event_store=None) == []
    assert provider_view_without_resolved_episodes(sess.messages) == sess.messages

    corrupt = _closed_events(sess.messages)
    corrupt.last_read_skipped = 1
    assert backfill_closed_tool_attempts(store, sess, event_store=corrupt) == []
    assert provider_view_without_resolved_episodes(sess.messages) == sess.messages


def test_closed_attempt_requires_complete_receipts_and_matching_terminal(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "episodes")
    missing_tool = [_user("Q"), _decl("tc-missing"), _program_terminal("llm_error")]
    sess_missing = SimpleNamespace(session_id="sid", messages=missing_tool)
    assert (
        backfill_closed_tool_attempts(
            store, sess_missing, event_store=_closed_events(missing_tool, "llm_error")
        )
        == []
    )
    assert provider_view_without_resolved_episodes(sess_missing.messages) == missing_tool

    mismatch = [_user("Q"), _decl("tc-1"), _tool("tc-1"), _program_terminal("stagnation")]
    sess_mismatch = SimpleNamespace(session_id="sid", messages=mismatch)
    assert (
        backfill_closed_tool_attempts(
            store, sess_mismatch, event_store=_closed_events(mismatch, "llm_error")
        )
        == []
    )
    assert provider_view_without_resolved_episodes(sess_mismatch.messages) == mismatch


def test_closed_attempt_index_failure_is_fail_open_and_idempotent(tmp_path) -> None:
    class _FailStore:
        def index_closed_tool_span(self, *args, **kwargs):
            raise OSError("disk full")

    user, decl, tool, terminal = _user("Q"), _decl("tc-1"), _tool("tc-1"), _program_terminal()
    sess = SimpleNamespace(session_id="sid", messages=[user, decl, tool, terminal])
    events = _closed_events(sess.messages)
    assert backfill_closed_tool_attempts(_FailStore(), sess, event_store=events) == []  # type: ignore[arg-type]
    assert provider_view_without_resolved_episodes(sess.messages) == sess.messages

    store = EpisodeStore(tmp_path / "episodes")
    first = backfill_closed_tool_attempts(store, sess, event_store=events)
    second = backfill_closed_tool_attempts(store, sess, event_store=events)
    assert first == second
    assert len(store.search("sid", "llm_error", 10)) == 1


def test_closed_span_ref_is_distinct_from_consumed_span_ref() -> None:
    user = _user("Q")
    closed = stable_closed_tool_span_ref("sid", user, 0, 3, "llm_error", ["tc-1"])
    consumed = stable_tool_span_ref("sid", user, 0, 3, ["tc-1"])
    assert closed.startswith("closedspan:")
    assert consumed.startswith("toolspan:")
    assert closed != consumed


def test_closed_tool_group_is_never_rewritten_as_consumed(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "episodes")
    user = _user("Q")
    decl = _decl("tc-1")
    tool = _tool("tc-1", "TOOL")
    terminal = _program_terminal("llm_error")
    closed_ref = stable_closed_tool_span_ref("sid", user, 0, 3, "llm_error", ["tc-1"])
    decl.metadata[CLOSED_TOOL_SPAN_REF_KEY] = closed_ref
    decl.metadata["tool_span_state"] = "closed"
    tool.metadata[CLOSED_TOOL_SPAN_REF_KEY] = closed_ref
    tool.metadata["tool_span_state"] = "closed"
    # Deliberately omit a new human boundary to model an anomalous merged history;
    # even then a later model answer cannot rewrite closed failure as consumed.
    later_consumer = _consumer("LATER-MODEL-ANSWER")
    sess = SimpleNamespace(
        session_id="sid",
        messages=[user, decl, tool, terminal, later_consumer],
    )

    assert backfill_consumed_tool_spans(store, sess) == []
    assert decl.metadata[CLOSED_TOOL_SPAN_REF_KEY] == closed_ref
    assert tool.metadata[CLOSED_TOOL_SPAN_REF_KEY] == closed_ref
    assert not decl.metadata.get(CONSUMED_TOOL_SPAN_REF_KEY)
    assert not tool.metadata.get(CONSUMED_TOOL_SPAN_REF_KEY)
    assert store.search("sid", "", 10) == []


def test_legacy_program_feedback_prefix_is_not_a_tool_consumer(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "episodes")
    legacy_program = Message(
        role="assistant",
        content="[LLM 调用异常] legacy network down",
        source=MessageSource.USER,
        model_used="legacy/model",
    )
    sess = SimpleNamespace(
        session_id="sid",
        messages=[_user("QUESTION"), _decl("tc-1"), _tool("tc-1"), legacy_program],
    )

    assert backfill_consumed_tool_spans(store, sess) == []


def test_index_failure_never_marks_or_retires_tool_protocol() -> None:
    class _FailStore:
        def index_tool_span(self, *args, **kwargs):
            raise OSError("disk full")

    user, decl, tool, consumer = _user("QUESTION"), _decl("tc-1"), _tool("tc-1"), _consumer()
    sess = SimpleNamespace(session_id="sid", messages=[user, decl, tool, consumer])

    assert backfill_consumed_tool_spans(_FailStore(), sess) == []  # type: ignore[arg-type]
    assert not decl.metadata.get(CONSUMED_TOOL_SPAN_REF_KEY)
    assert not tool.metadata.get(CONSUMED_TOOL_SPAN_REF_KEY)
    assert provider_view_without_resolved_episodes(sess.messages) == sess.messages


def test_backfill_is_idempotent(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "episodes")
    user, decl, tool, consumer = _user("QUESTION"), _decl("tc-1"), _tool("tc-1"), _consumer()
    sess = SimpleNamespace(session_id="sid", messages=[user, decl, tool, consumer])

    first = backfill_consumed_tool_spans(store, sess)
    second = backfill_consumed_tool_spans(store, sess)

    assert first == second
    assert len(store.search("sid", "QUESTION", 10)) == 1


def test_engine_next_human_turn_retires_legacy_consumed_tools_but_keeps_unresolved_qa(
    tmp_path,
) -> None:
    calls: list[list[dict]] = []

    class _Fake:
        def _response(self) -> LLMResponse:
            return LLMResponse(content="NEXT-ANSWER", tool_calls=[], provider="fake")

        def chat(self, messages, tools, **kwargs):
            calls.append([dict(message) for message in messages])
            return self._response()

        def chat_stream(self, messages, tools, **kwargs):
            calls.append([dict(message) for message in messages])

            def _gen():
                yield from ()
                return self._response()

            return _gen()

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    sessions = SessionStore(tmp_path / "sessions")
    episodes = EpisodeStore(tmp_path / "episodes")
    sid = sessions.create()
    stored = sessions.load(sid)
    legacy_user = _user("LEGACY-QUESTION")
    legacy_decl = _decl("tc-legacy")
    legacy_tool = _tool("tc-legacy", "LEGACY-TOOL-SECRET")
    # Legacy model answer: no R8.5 completion-candidate metadata, therefore the
    # whole Q&A must remain provider-visible even though its raw tool evidence has
    # already been consumed.
    legacy_consumer = Message(
        role="assistant",
        content="LEGACY-CONSUMER",
        source=MessageSource.USER,
        model_used="legacy/model",
    )
    stored.messages = [legacy_user, legacy_decl, legacy_tool, legacy_consumer]
    sessions.save(stored)

    engine = LoopEngine(
        llm_client=_Fake(),  # type: ignore[arg-type]
        registry=ToolRegistry(),
        memory=None,  # type: ignore[arg-type]
        session=sessions,
        settings=settings,
        episode_store=episodes,
    )

    result = engine.run(sid, "NEXT-QUESTION")

    assert result.final_answer == "NEXT-ANSWER"
    assert calls
    wire = calls[-1]
    joined = "\n".join(str(message.get("content") or "") for message in wire)
    assert "NEXT-QUESTION" in joined
    assert "LEGACY-QUESTION" in joined, "whole legacy task is not proven resolved"
    assert "LEGACY-CONSUMER" in joined
    assert "LEGACY-TOOL-SECRET" not in joined
    assert not any(
        message.get("role") == "assistant"
        and any(call.get("id") == "tc-legacy" for call in (message.get("tool_calls") or []))
        for message in wire
    )

    after = sessions.load(sid)
    ref = str(after.messages[1].metadata.get(CONSUMED_TOOL_SPAN_REF_KEY) or "")
    assert ref.startswith("toolspan:")
    assert after.messages[2].metadata.get(CONSUMED_TOOL_SPAN_REF_KEY) == ref
    assert not after.messages[0].metadata.get("resolved_episode_ref")
    assert not after.messages[3].metadata.get("resolved_episode_ref")
    hydrated = episodes.hydrate(sid, ref, max_chars=12000)
    assert hydrated is not None
    assert "LEGACY-TOOL-SECRET" in hydrated["content"]


def test_engine_next_human_ingress_closes_prior_failed_tool_protocol(tmp_path) -> None:
    calls: list[list[dict]] = []

    class _Fake:
        model = "m"

        def _response(self) -> LLMResponse:
            return LLMResponse(content="NEXT-ANSWER", tool_calls=[], provider="fake")

        def chat(self, messages, tools, **kwargs):
            calls.append([dict(message) for message in messages])
            return self._response()

        def chat_stream(self, messages, tools, **kwargs):
            calls.append([dict(message) for message in messages])

            def _gen():
                yield from ()
                return self._response()

            return _gen()

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    sessions = SessionStore(tmp_path / "sessions")
    episodes = EpisodeStore(tmp_path / "episodes")
    events = EventStore(tmp_path / "event_logs")
    sid = sessions.create()
    stored = sessions.load(sid)
    failed = [
        _user("FAILED-QUESTION"),
        _decl("tc-failed"),
        _tool("tc-failed", "FAILED-TOOL-SECRET"),
        _program_terminal("llm_error"),
    ]
    stored.messages = failed
    sessions.save(stored)
    _write_closed_event_store(events, sid, failed, "llm_error")

    engine = LoopEngine(
        llm_client=_Fake(),  # type: ignore[arg-type]
        registry=ToolRegistry(),
        memory=None,  # type: ignore[arg-type]
        session=sessions,
        settings=settings,
        episode_store=episodes,
        event_store=events,
    )

    result = engine.run(sid, "NEXT-HUMAN", ingress=issue_test_ingress())

    assert result.final_answer == "NEXT-ANSWER"
    assert calls
    wire = calls[-1]
    joined = "\n".join(str(message.get("content") or "") for message in wire)
    assert "FAILED-QUESTION" in joined
    assert "NEXT-HUMAN" in joined
    assert "FAILED-TOOL-SECRET" not in joined
    assert not any(
        message.get("role") == "assistant"
        and any(call.get("id") == "tc-failed" for call in (message.get("tool_calls") or []))
        for message in wire
    )
    after = sessions.load(sid)
    ref = str(after.messages[1].metadata.get(CLOSED_TOOL_SPAN_REF_KEY) or "")
    assert ref.startswith("closedspan:")
    assert after.messages[2].metadata.get(CLOSED_TOOL_SPAN_REF_KEY) == ref
    assert not after.messages[0].metadata.get(CLOSED_TOOL_SPAN_REF_KEY)
    assert not after.messages[3].metadata.get(CLOSED_TOOL_SPAN_REF_KEY)
    hydrated = episodes.hydrate(sid, ref, max_chars=12000)
    assert hydrated is not None and "FAILED-TOOL-SECRET" in hydrated["content"]


def test_engine_delegated_wake_keeps_prior_failed_tool_protocol_active(tmp_path) -> None:
    calls: list[list[dict]] = []

    class _Fake:
        model = "m"

        def _response(self) -> LLMResponse:
            return LLMResponse(content="WAKE-ANSWER", tool_calls=[], provider="fake")

        def chat(self, messages, tools, **kwargs):
            calls.append([dict(message) for message in messages])
            return self._response()

        def chat_stream(self, messages, tools, **kwargs):
            calls.append([dict(message) for message in messages])

            def _gen():
                yield from ()
                return self._response()

            return _gen()

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    sessions = SessionStore(tmp_path / "sessions")
    episodes = EpisodeStore(tmp_path / "episodes")
    events = EventStore(tmp_path / "event_logs")
    sid = sessions.create()
    stored = sessions.load(sid)
    failed = [
        _user("FAILED-QUESTION"),
        _decl("tc-failed"),
        _tool("tc-failed", "FAILED-TOOL-SECRET"),
        _program_terminal("llm_error"),
    ]
    stored.messages = failed
    sessions.save(stored)
    _write_closed_event_store(events, sid, failed, "llm_error")

    engine = LoopEngine(
        llm_client=_Fake(),  # type: ignore[arg-type]
        registry=ToolRegistry(),
        memory=None,  # type: ignore[arg-type]
        session=sessions,
        settings=settings,
        episode_store=episodes,
        event_store=events,
    )
    delegated = delegate_ingress(issue_ingress("web"), entry="retry-failed-turn")

    result = engine.run(sid, "scheduled continuation", ingress=delegated)

    assert result.final_answer == "WAKE-ANSWER"
    assert calls
    wire = calls[-1]
    joined = "\n".join(str(message.get("content") or "") for message in wire)
    assert "FAILED-TOOL-SECRET" in joined
    assert any(
        message.get("role") == "assistant"
        and any(call.get("id") == "tc-failed" for call in (message.get("tool_calls") or []))
        for message in wire
    )
    after = sessions.load(sid)
    assert not after.messages[1].metadata.get(CLOSED_TOOL_SPAN_REF_KEY)
    assert not after.messages[2].metadata.get(CLOSED_TOOL_SPAN_REF_KEY)
    delegated_users = [
        message
        for message in after.messages
        if message.role == "user" and message.metadata.get("ingress_delegated")
    ]
    assert delegated_users and delegated_users[-1].content == "scheduled continuation"

from __future__ import annotations

from types import SimpleNamespace

from llm_loop.config import Settings
from llm_loop.core.episode_history import (
    CONSUMED_TOOL_SPAN_REF_KEY,
    backfill_consumed_tool_spans,
    provider_view_without_resolved_episodes,
)
from llm_loop.core.loop import LoopEngine
from llm_loop.core.message import Message, MessageSource, ToolResultStatus
from llm_loop.core.session import SessionStore
from llm_loop.introspection.search import RecordSearcher
from llm_loop.llm.client import LLMResponse
from llm_loop.memory.episode import EpisodeStore, stable_tool_span_ref
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


def test_episode_store_indexes_consumed_tool_span_without_claiming_episode_resolution(tmp_path) -> None:
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
    record_hits = searcher.search(
        kind="episode", query="TOOL-SECRET", limit=10, session_id="sid"
    )
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
    assert {m.metadata.get(CONSUMED_TOOL_SPAN_REF_KEY) for m in (d1, t1, d2, t2)} == {
        refs[0]
    }
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

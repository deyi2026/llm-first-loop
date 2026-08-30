from __future__ import annotations

from llm_loop.config import Settings
from llm_loop.core.episode_history import (
    EPISODE_KEEP_PROVIDER_KEY,
    RESOLVED_EPISODE_REF_KEY,
    backfill_completed_episodes,
    filtered_anchor_from_original,
    index_current_completed_episode,
    original_anchor_from_filtered,
    provider_view_without_resolved_episodes,
)
from llm_loop.core.loop.engine import LoopEngine
from llm_loop.core.message import Message, MessageSource, ToolCall, ToolResult, ToolResultStatus
from llm_loop.core.session import Session, SessionStore
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.tools_status import run_search_records
from llm_loop.llm.client import LLMResponse
from llm_loop.memory.episode import EpisodeStore, stable_episode_ref
from llm_loop.tools.registry import ToolRegistry


def _user(text: str, *, ts: float = 1.0) -> Message:
    return Message(
        role="user",
        content=text,
        source=MessageSource.USER,
        ts=ts,
        metadata={"origin_layer": "user_instruction", "program_origin": False},
    )


def _final(text: str, *, completed: bool = True, ts: float = 2.0) -> Message:
    return Message(
        role="assistant",
        content=text,
        source=MessageSource.USER,
        ts=ts,
        metadata={
            "answer_origin": "model",
            "run_end_reason": "completed" if completed else "llm_error",
            "episode_resolution_candidate": bool(completed and text),
        },
    )


def test_episode_store_stable_ref_search_and_bounded_hydration(tmp_path):
    store = EpisodeStore(tmp_path / "episodes")
    user = _user("FIRST-QUESTION exact", ts=10.0)
    ref = stable_episode_ref("sid-a", user, 0)
    tool = Message(
        role="tool",
        content="TOOL-EVIDENCE exact",
        source=MessageSource.TOOL,
        tool_name="read_file",
        tool_call_id="tc-1",
        status=ToolResultStatus.SUCCESS,
        ts=11.0,
    )
    assistant = _final("FIRST-ANSWER exact", ts=12.0)
    assistant.reasoning_content = "PRIVATE-REASONING-MUST-NOT-DUPLICATE"

    first = store.index_episode(
        "sid-a", ref=ref, user_seq=0, raw_messages=[user, tool, assistant]
    )
    second = store.index_episode(
        "sid-a", ref=ref, user_seq=0, raw_messages=[user, tool, assistant]
    )
    assert first.created is True
    assert second.created is False

    hits = store.search("sid-a", query="FIRST-QUESTION", limit=10)
    assert len(hits) == 1
    assert hits[0]["ref"] == ref
    assert "FIRST-QUESTION" in hits[0]["summary"]

    hydrated = store.hydrate("sid-a", ref, max_chars=4096)
    assert hydrated is not None
    assert hydrated["complete"] is True
    assert "FIRST-QUESTION exact" in hydrated["content"]
    assert "TOOL-EVIDENCE exact" in hydrated["content"]
    assert "FIRST-ANSWER exact" in hydrated["content"]
    assert "PRIVATE-REASONING-MUST-NOT-DUPLICATE" not in hydrated["content"]


def test_episode_store_excludes_program_prompt_material_from_hydration(tmp_path):
    store = EpisodeStore(tmp_path / "episodes")
    user = _user("真实问题", ts=20.0)
    program = Message(
        role="user",
        content="STALE-PROGRAM-COMMAND",
        source=MessageSource.USER,
        ts=21.0,
        metadata={"origin_layer": "status", "program_origin": True},
    )
    system = Message(
        role="system",
        content="OBSERVABILITY-NOISE",
        source=MessageSource.SYSTEM,
        ts=22.0,
    )
    answer = _final("真实回答", ts=23.0)
    ref = stable_episode_ref("sid-b", user, 0)
    store.index_episode(
        "sid-b", ref=ref, user_seq=0, raw_messages=[user, program, system, answer]
    )
    hydrated = store.hydrate("sid-b", ref, max_chars=4096)
    assert hydrated is not None
    assert "真实问题" in hydrated["content"]
    assert "真实回答" in hydrated["content"]
    assert "STALE-PROGRAM-COMMAND" not in hydrated["content"]
    assert "OBSERVABILITY-NOISE" not in hydrated["content"]


def test_completed_episode_is_marked_only_after_durable_index(tmp_path):
    store = EpisodeStore(tmp_path / "episodes")
    sess = Session(session_id="sid-c", messages=[_user("Q"), _final("A")])
    ref = index_current_completed_episode(store, sess, turn_ref=0, final_answer_index=1)
    assert ref
    assert store.get("sid-c", ref) is not None
    assert all(m.metadata.get(RESOLVED_EPISODE_REF_KEY) == ref for m in sess.messages)
    assert provider_view_without_resolved_episodes(sess.messages) == []


def test_unresolved_episode_remains_provider_visible(tmp_path):
    store = EpisodeStore(tmp_path / "episodes")
    sess = Session(session_id="sid-d", messages=[_user("Q"), _final("A", completed=False)])
    ref = index_current_completed_episode(store, sess, turn_ref=0, final_answer_index=1)
    assert ref is None
    assert store.search("sid-d", "", 10) == []
    assert provider_view_without_resolved_episodes(sess.messages) == sess.messages


def test_explicit_standing_user_instruction_survives_episode_retirement(tmp_path):
    store = EpisodeStore(tmp_path / "episodes")
    user = _user("以后不要自动 stage 其他 dirty files；这次请检查当前提交。", ts=5.0)
    answer = _final("已检查。", ts=6.0)
    sess = Session(session_id="sid-standing", messages=[user, answer])
    ref = index_current_completed_episode(store, sess, turn_ref=0, final_answer_index=1)
    assert ref
    assert sess.messages[0].metadata.get(EPISODE_KEEP_PROVIDER_KEY) is True
    projected = provider_view_without_resolved_episodes(sess.messages)
    assert projected == [sess.messages[0]]
    hydrated = store.hydrate("sid-standing", ref, max_chars=4096)
    assert hydrated is not None and "已检查" in hydrated["content"]


def test_anchor_translation_across_retired_messages():
    kept = [0, 4, 5, 8]
    assert filtered_anchor_from_original(kept, 0) == 0
    assert filtered_anchor_from_original(kept, 3) == 1
    assert filtered_anchor_from_original(kept, 4) == 1
    assert filtered_anchor_from_original(kept, 6) == 3
    assert original_anchor_from_filtered(kept, 1, original_length=10) == 4
    assert original_anchor_from_filtered(kept, 3, original_length=10) == 8
    assert original_anchor_from_filtered(kept, 4, original_length=10) == 10


def test_index_failure_does_not_mark_or_retire_episode():
    class _FailStore:
        def index_episode(self, *args, **kwargs):
            raise OSError("disk full")

    sess = Session(session_id="sid-fail", messages=[_user("Q"), _final("A")])
    try:
        index_current_completed_episode(
            _FailStore(),  # type: ignore[arg-type]
            sess,
            turn_ref=0,
            final_answer_index=1,
        )
    except OSError:
        pass
    assert all(RESOLVED_EPISODE_REF_KEY not in m.metadata for m in sess.messages)
    assert provider_view_without_resolved_episodes(sess.messages) == sess.messages


def test_backfill_is_conservative_for_legacy_and_completed_for_current_format(tmp_path):
    store = EpisodeStore(tmp_path / "episodes")
    legacy_answer = Message(
        role="assistant",
        content="legacy",
        source=MessageSource.USER,
        ts=2.0,
        metadata={"answer_origin": "model", "run_end_reason": "completed"},
    )
    current_user = _user("current Q", ts=3.0)
    current_answer = _final("current A", ts=4.0)
    sess = Session(
        session_id="sid-e",
        messages=[_user("legacy Q", ts=1.0), legacy_answer, current_user, current_answer],
    )
    refs = backfill_completed_episodes(store, sess)
    assert len(refs) == 1
    assert RESOLVED_EPISODE_REF_KEY not in sess.messages[0].metadata
    assert RESOLVED_EPISODE_REF_KEY not in sess.messages[1].metadata
    assert sess.messages[2].metadata.get(RESOLVED_EPISODE_REF_KEY) == refs[0]
    assert sess.messages[3].metadata.get(RESOLVED_EPISODE_REF_KEY) == refs[0]


def test_engine_truncated_answer_is_not_indexed_or_retired(tmp_path):
    class _Fake:
        def chat(self, messages, tools, **kw):
            return LLMResponse(
                content="PARTIAL-ANSWER",
                tool_calls=[],
                provider="fake",
                truncated=True,
            )

        def chat_stream(self, messages, tools, **kw):
            def _gen():
                yield from ()
                return self.chat(messages, tools, **kw)

            return _gen()

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    sessions = SessionStore(tmp_path / "sessions")
    episodes = EpisodeStore(tmp_path / "episodes")
    engine = LoopEngine(
        llm_client=_Fake(),  # type: ignore[arg-type]
        registry=ToolRegistry(),
        memory=None,  # type: ignore[arg-type]
        session=sessions,
        settings=settings,
        episode_store=episodes,
    )
    sid = sessions.create()
    result = engine.run(sid, "QUESTION-WITH-TRUNCATED-ANSWER")
    assert result.truncated is True
    stored = sessions.load(sid)
    final = stored.messages[-1]
    assert final.metadata.get("episode_resolution_candidate") is False
    assert all(RESOLVED_EPISODE_REF_KEY not in m.metadata for m in stored.messages)
    assert episodes.search(sid, "", 10) == []


def test_search_records_episode_lists_and_hydrates_without_new_tool(tmp_path):
    store = EpisodeStore(tmp_path / "episodes")
    user = _user("缓存命中问题", ts=30.0)
    answer = _final("根因是旧任务回灌", ts=31.0)
    ref = stable_episode_ref("sid-f", user, 0)
    store.index_episode("sid-f", ref=ref, user_seq=0, raw_messages=[user, answer])
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", episode_store=store)

    class _Adapter:
        def __call__(self, **kw):
            return searcher.search(**kw)

        def hydrate_episode(self, **kw):
            return searcher.hydrate_episode(**kw)

    adapter = _Adapter()
    listed = run_search_records(
        object(), adapter, {"kind": "episode", "query": "缓存"}, lambda: "sid-f"
    )
    assert listed.status is ToolResultStatus.SUCCESS
    assert ref in listed.content

    hydrated = run_search_records(
        object(),
        adapter,
        {"kind": "episode", "query": ref},
        lambda: "sid-f",
    )
    assert hydrated.status is ToolResultStatus.SUCCESS
    assert "缓存命中问题" in hydrated.content
    assert "根因是旧任务回灌" in hydrated.content


def test_search_records_episode_hydration_pages_via_query_only(tmp_path):
    store = EpisodeStore(tmp_path / "episodes")
    user = _user("大条目", ts=40.0)
    answer = _final("A" * 7000, ts=41.0)
    ref = stable_episode_ref("sid-page", user, 0)
    store.index_episode("sid-page", ref=ref, user_seq=0, raw_messages=[user, answer])
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", episode_store=store)

    class _Adapter:
        def __call__(self, **kw):
            return searcher.search(**kw)

        def hydrate_episode(self, **kw):
            return searcher.hydrate_episode(**kw)

    first = run_search_records(
        object(), _Adapter(), {"kind": "episode", "query": ref}, lambda: "sid-page"
    )
    assert "complete=false" in first.content
    marker = "next_query="
    next_query = first.content.split(marker, 1)[1].splitlines()[0].strip()
    second = run_search_records(
        object(), _Adapter(), {"kind": "episode", "query": next_query}, lambda: "sid-page"
    )
    assert "offset=" in second.content
    assert "A" in second.content


def test_engine_second_run_retires_first_episode_but_episode_is_retrievable(tmp_path):
    calls: list[list[dict]] = []

    class _Fake:
        def __init__(self) -> None:
            self.n = 0

        def _next(self):
            self.n += 1
            if self.n == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc-1", name="read_file", arguments={"path": "x"})
                    ],
                    provider="fake",
                )
            if self.n == 2:
                return LLMResponse(
                    content="FIRST-ANSWER-SECRET", tool_calls=[], provider="fake"
                )
            return LLMResponse(content="SECOND-ANSWER", tool_calls=[], provider="fake")

        def chat(self, messages, tools, **kw):
            calls.append([dict(m) for m in messages])
            return self._next()

        def chat_stream(self, messages, tools, **kw):
            calls.append([dict(m) for m in messages])

            def _gen():
                yield from ()
                return self._next()

            return _gen()

    class _Reg(ToolRegistry):
        def execute(self, call):
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="FIRST-TOOL-SECRET",
                tool_call_id=call.id,
                tool_name=call.name,
            )

    reg = _Reg()
    reg.register(
        type(
            "RF",
            (),
            {"name": "read_file", "description": "t", "parameters": {"type": "object"}},
        )()
    )
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    sessions = SessionStore(tmp_path / "sessions")
    episodes = EpisodeStore(tmp_path / "episodes")
    engine = LoopEngine(
        llm_client=_Fake(),  # type: ignore[arg-type]
        registry=reg,
        memory=None,  # type: ignore[arg-type]
        session=sessions,
        settings=settings,
        episode_store=episodes,
    )
    sid = sessions.create()
    first = engine.run(sid, "FIRST-QUESTION-SECRET")
    assert first.final_answer == "FIRST-ANSWER-SECRET"
    stored = sessions.load(sid)
    first_ref = str(stored.messages[0].metadata.get(RESOLVED_EPISODE_REF_KEY) or "")
    assert first_ref.startswith("episode:")

    second = engine.run(sid, "SECOND-QUESTION")
    assert second.final_answer == "SECOND-ANSWER"
    assert len(calls) >= 3
    second_run_payload = "\n".join(
        str(m.get("content") or "") for m in calls[-1]
    )
    assert "SECOND-QUESTION" in second_run_payload
    assert "FIRST-QUESTION-SECRET" not in second_run_payload
    assert "FIRST-ANSWER-SECRET" not in second_run_payload
    assert "FIRST-TOOL-SECRET" not in second_run_payload

    hits = episodes.search(sid, "FIRST-QUESTION-SECRET", 10)
    assert hits and hits[0]["ref"] == first_ref
    hydrated = episodes.hydrate(sid, first_ref, max_chars=12000)
    assert hydrated is not None
    assert "FIRST-QUESTION-SECRET" in hydrated["content"]
    assert "FIRST-ANSWER-SECRET" in hydrated["content"]
    assert "FIRST-TOOL-SECRET" in hydrated["content"]


def test_engine_anchor_remap_preserves_current_tool_protocol_after_retirement(tmp_path):
    calls: list[list[dict]] = []

    class _Fake:
        def __init__(self) -> None:
            self.n = 0

        def _next(self):
            self.n += 1
            if self.n == 1:
                return LLMResponse(content="OLD-DONE", tool_calls=[], provider="fake")
            if self.n == 2:
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCall(id="tc-new", name="read_file", arguments={"path": "x"})],
                    provider="fake",
                )
            return LLMResponse(content="NEW-DONE", tool_calls=[], provider="fake")

        def chat(self, messages, tools, **kw):
            calls.append([dict(m) for m in messages])
            return self._next()

        def chat_stream(self, messages, tools, **kw):
            calls.append([dict(m) for m in messages])

            def _gen():
                yield from ()
                return self._next()

            return _gen()

    class _Reg(ToolRegistry):
        def execute(self, call):
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="NEW-TOOL-RESULT",
                tool_call_id=call.id,
                tool_name=call.name,
            )

    reg = _Reg()
    reg.register(
        type(
            "RF",
            (),
            {"name": "read_file", "description": "t", "parameters": {"type": "object"}},
        )()
    )
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    sessions = SessionStore(tmp_path / "sessions")
    episodes = EpisodeStore(tmp_path / "episodes")
    engine = LoopEngine(
        llm_client=_Fake(),  # type: ignore[arg-type]
        registry=reg,
        memory=None,  # type: ignore[arg-type]
        session=sessions,
        settings=settings,
        episode_store=episodes,
    )
    sid = sessions.create()
    assert engine.run(sid, "OLD-QUESTION").final_answer == "OLD-DONE"

    # Persist an anchor at the original end of the now-retired first episode.
    # Without original<->filtered remapping, the second tool-followup build would
    # interpret anchor=2 inside [new user, assistant(tool_calls), tool] and leave
    # an orphan tool result.
    stored = sessions.load(sid)
    stored.history_anchors["m"] = 2
    sessions.save(stored)

    assert engine.run(sid, "NEW-QUESTION").final_answer == "NEW-DONE"
    assert len(calls) == 3
    followup = calls[-1]
    roles = [m.get("role") for m in followup]
    assert "user" in roles
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in followup)
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "tc-new" for m in followup)
    joined = "\n".join(str(m.get("content") or "") for m in followup)
    assert "NEW-QUESTION" in joined
    assert "NEW-TOOL-RESULT" in joined
    assert "OLD-QUESTION" not in joined

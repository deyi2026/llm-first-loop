from __future__ import annotations

import contextlib
from types import SimpleNamespace

from llm_loop.config import Settings
from llm_loop.core.episode_history import (
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




def _legacy_final(text: str, *, ts: float = 2.0) -> Message:
    return Message(
        role="assistant",
        content=text,
        source=MessageSource.USER,
        ts=ts,
        metadata={"answer_origin": "model", "run_end_reason": "completed"},
    )


class _ProofEvents:
    def __init__(self, events, *, skipped: int = 0):
        self._events = events
        self.last_read_skipped = skipped

    def read(self, session_id: str):
        return list(self._events)


def _event(type_: str, seq: int, payload: dict):
    return SimpleNamespace(type=type_, seq=seq, payload=payload)


def _legacy_proof_events(answer: str, *, truncated: bool = False, preview: str | None = None):
    return [
        _event(
            "message.appended",
            1,
            {
                "index": 1,
                "role": "assistant",
                "content": answer,
                "metadata": {"answer_origin": "model", "run_end_reason": "completed"},
            },
        ),
        _event(
            "run.end",
            2,
            {
                "reason": "completed",
                "truncated": truncated,
                "answer_preview": answer[:200] if preview is None else preview,
            },
        ),
    ]

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


def test_explicit_standing_user_instruction_retires_but_remains_retrievable(tmp_path):
    store = EpisodeStore(tmp_path / "episodes")
    user = _user("以后不要自动 stage 其他 dirty files；这次请检查当前提交。", ts=5.0)
    answer = _final("已检查。", ts=6.0)
    sess = Session(session_id="sid-standing", messages=[user, answer])
    ref = index_current_completed_episode(store, sess, turn_ref=0, final_answer_index=1)
    assert ref
    projected = provider_view_without_resolved_episodes(sess.messages)
    assert projected == []
    hydrated = store.hydrate("sid-standing", ref, max_chars=4096)
    assert hydrated is not None
    assert "以后不要自动 stage 其他 dirty files" in hydrated["content"]
    assert "已检查" in hydrated["content"]


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
    with contextlib.suppress(OSError):
        index_current_completed_episode(
            _FailStore(),  # type: ignore[arg-type]
            sess,
            turn_ref=0,
            final_answer_index=1,
        )
    assert all(RESOLVED_EPISODE_REF_KEY not in m.metadata for m in sess.messages)
    assert provider_view_without_resolved_episodes(sess.messages) == sess.messages


def test_backfill_migrates_legacy_only_with_unique_durable_run_end_proof(tmp_path):
    store = EpisodeStore(tmp_path / "episodes")
    answer = _legacy_final("LEGACY-PROVEN-ANSWER")
    sess = Session(session_id="sid-legacy-proof", messages=[_user("legacy Q"), answer])
    events = _ProofEvents(_legacy_proof_events(answer.content))

    refs = backfill_completed_episodes(store, sess, event_store=events)

    assert len(refs) == 1
    assert all(m.metadata.get(RESOLVED_EPISODE_REF_KEY) == refs[0] for m in sess.messages)
    assert provider_view_without_resolved_episodes(sess.messages) == []
    hydrated = store.hydrate("sid-legacy-proof", refs[0], max_chars=4096)
    assert hydrated is not None and "LEGACY-PROVEN-ANSWER" in hydrated["content"]


def test_backfill_legacy_proof_fails_closed_on_truncation_preview_mismatch_or_corruption(tmp_path):
    cases = [
        ("truncated", _ProofEvents(_legacy_proof_events("A", truncated=True))),
        ("preview-mismatch", _ProofEvents(_legacy_proof_events("A", preview="OTHER"))),
        ("corrupt-log", _ProofEvents(_legacy_proof_events("A"), skipped=1)),
    ]
    for name, events in cases:
        store = EpisodeStore(tmp_path / name / "episodes")
        sess = Session(session_id=f"sid-{name}", messages=[_user("Q"), _legacy_final("A")])
        assert backfill_completed_episodes(store, sess, event_store=events) == []
        assert all(RESOLVED_EPISODE_REF_KEY not in m.metadata for m in sess.messages)
        assert provider_view_without_resolved_episodes(sess.messages) == sess.messages


def test_backfill_legacy_proof_requires_exactly_one_final_candidate_per_run(tmp_path):
    store = EpisodeStore(tmp_path / "episodes")
    answer = _legacy_final("A")
    sess = Session(session_id="sid-ambiguous", messages=[_user("Q"), answer])
    events = _legacy_proof_events("A")
    events.insert(
        1,
        _event(
            "message.appended",
            2,
            {
                "index": 1,
                "role": "assistant",
                "content": "A",
                "metadata": {"answer_origin": "model", "run_end_reason": "completed"},
            },
        ),
    )
    for i, event in enumerate(events, start=1):
        event.seq = i
    assert backfill_completed_episodes(store, sess, event_store=_ProofEvents(events)) == []
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
                finish_reason="length",
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
    assert final.content == "PARTIAL-ANSWER"
    assert final.metadata.get("llm_interrupted") is True
    assert final.metadata.get("provider_truncated") is True
    assert final.metadata.get("provider_finish_reason") == "length"
    assert all(RESOLVED_EPISODE_REF_KEY not in m.metadata for m in stored.messages)
    assert episodes.search(sid, "", 10) == []


def test_engine_next_human_turn_receives_truncation_fact_and_exact_partial(tmp_path):
    class _Fake:
        def __init__(self) -> None:
            self.calls: list[list[dict]] = []
            self.responses = [
                LLMResponse(
                    content="PARTIAL-ANSWER",
                    tool_calls=[],
                    provider="fake",
                    truncated=True,
                    finish_reason="length",
                ),
                LLMResponse(
                    content="CONTINUED-ANSWER",
                    tool_calls=[],
                    provider="fake",
                    truncated=False,
                    finish_reason="stop",
                ),
            ]

        def chat(self, messages, tools, **kw):
            self.calls.append([dict(row) for row in messages])
            return self.responses.pop(0)

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
    fake = _Fake()
    engine = LoopEngine(
        llm_client=fake,  # type: ignore[arg-type]
        registry=ToolRegistry(),
        memory=None,  # type: ignore[arg-type]
        session=sessions,
        settings=settings,
        episode_store=episodes,
    )
    sid = sessions.create()

    first = engine.run(sid, "请分析")
    assert first.truncated is True
    second = engine.run(sid, "继续")
    assert second.final_answer == "CONTINUED-ANSWER"

    assert len(fake.calls) == 2
    second_wire = fake.calls[1]
    assert second_wire[0]["role"] == "system"
    assert "runtime_continuity" not in second_wire[0]["content"]
    assert second_wire[-2] == {"role": "assistant", "content": "PARTIAL-ANSWER"}
    assert second_wire[-1]["role"] == "user"
    assert second_wire[-1]["content"].startswith(
        "继续\n\n[provider_runtime_fact—not_human_text]\n[runtime_continuity] "
    )
    assert '"previous_assistant_output_truncated":true' in second_wire[-1]["content"]
    assert '"previous_assistant_output_complete":false' in second_wire[-1]["content"]
    assert '"partial_output_persisted":true' in second_wire[-1]["content"]
    assert '"finish_reason":"length"' in second_wire[-1]["content"]
    stored_after_second = sessions.load(sid)
    genuine_continue = [
        message
        for message in stored_after_second.messages
        if message.role == "user" and message.content == "继续"
    ]
    assert len(genuine_continue) == 1


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
    # Resolved episode retirement removes the old human/tool working set, but the
    # immediately prior real model answer is intentionally rehydrated once as the
    # adjacent continuity pair for the new human ingress.  This keeps a user's reply
    # focused on what the model just said without reopening the retired episode.
    assert "FIRST-QUESTION-SECRET" not in second_run_payload
    assert "FIRST-ANSWER-SECRET" in second_run_payload
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

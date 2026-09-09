from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.config import Settings
from llm_loop.core.episode_history import (
    build_working_state_checkpoint,
    collect_active_evidence_groups,
    project_active_tool_working_set_with_stats,
    resolve_working_state_checkpoint,
)
from llm_loop.core.message import Message, MessageSource, ToolResultStatus
from llm_loop.core.recent_continuity import apply_recent_continuity_suffix
from llm_loop.core.session import Session, SessionStore
from llm_loop.event_log.store import EventStore


def _assistant(call_id: str, *, name: str = "read_file") -> Message:
    return Message(
        role="assistant",
        content="checking",
        source=MessageSource.USER,
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            }
        ],
        model_used="test-model",
        metadata={"answer_origin": "model"},
    )


def _tool(call_id: str, content: str, *, ref: str | None = None) -> Message:
    metadata = {}
    if ref is not None:
        metadata = {"recoverability_status": "recorded", "evidence_ref": ref}
    return Message(
        role="tool",
        content=content,
        source=MessageSource.TOOL,
        tool_call_id=call_id,
        status=ToolResultStatus.SUCCESS,
        tool_name="read_file",
        metadata=metadata,
    )


def _followup(text: str = "continue") -> Message:
    return Message(
        role="assistant",
        content=text,
        source=MessageSource.USER,
        model_used="test-model",
        metadata={"answer_origin": "model"},
    )


def _messages() -> list[Message]:
    return [
        Message(role="user", content="task", source=MessageSource.USER),
        _assistant("c1"),
        _tool("c1", "SELECTED-RAW-" * 500, ref="evidence://v1/selected"),
        _followup(),
        _assistant("c2"),
        _tool("c2", "UNSELECTED-RAW-" * 500, ref="evidence://v1/unselected"),
        _followup(),
        _assistant("c3"),
        _tool("c3", "LATEST-RAW-" * 500, ref="evidence://v1/latest"),
    ]


def _checkpoint(messages: list[Message], *, selected_ids: list[str] | None = None) -> dict:
    return build_working_state_checkpoint(
        session_id="s1",
        messages=messages,
        provider_id="deepseek",
        model="deepseek/model",
        selected_ids=selected_ids or ["e1"],
        state_text='{"verdict":"ready","next":"final"}',
        state_char_limit=1024,
        selected_raw_char_limit=20000,
    )


def test_checkpoint_persists_protocol_digests_not_only_fold_local_ids():
    messages = _messages()
    checkpoint = _checkpoint(messages)
    groups = collect_active_evidence_groups(messages)

    assert checkpoint["selected_ids"] == ["e1"]
    assert checkpoint["selected_group_digests"] == [groups[0].descriptor.protocol_digest]
    assert checkpoint["candidate_set_digest"].startswith("v1:")
    assert checkpoint["boundary_message_count"] == len(messages)
    assert checkpoint["human_anchor_index"] == 0


def test_truncated_selection_is_not_persisted_as_checkpoint():
    with pytest.raises(ValueError, match="finish normally"):
        build_working_state_checkpoint(
            session_id="s1",
            messages=_messages(),
            provider_id="deepseek",
            model="deepseek/model",
            selected_ids=["e1"],
            state_text="partial state",
            state_char_limit=1024,
            selected_raw_char_limit=20000,
            selection_finish_reason="length",
        )


def test_provider_truncation_takes_recovery_ownership_after_s1_boundary_advances():
    messages = _messages()
    checkpoint = _checkpoint(messages)
    initial = resolve_working_state_checkpoint(
        checkpoint,
        session_id="s1",
        messages=messages,
        provider_id="deepseek",
        model="deepseek/model",
    )
    assert initial.eligible is True

    partial = Message(
        role="assistant",
        content="PARTIAL-ANSWER",
        source=MessageSource.USER,
        metadata={
            "answer_origin": "model",
            "llm_interrupted": True,
            "provider_truncated": True,
            "provider_finish_reason": "length",
        },
    )
    current_user = Message(role="user", content="继续", source=MessageSource.USER)
    advanced = [*messages, partial, current_user]

    stale = resolve_working_state_checkpoint(
        checkpoint,
        session_id="s1",
        messages=advanced,
        provider_id="deepseek",
        model="deepseek/model",
    )
    assert stale.eligible is False
    assert stale.reason == "boundary"
    assert stale.state_text == ""
    assert stale.preserve_group_digests == ()

    built, info = apply_recent_continuity_suffix(
        [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "继续"},
        ],
        session_messages=advanced,
        current_turn_ref=len(advanced) - 1,
        interruption_resume={
            "source": "persisted_provider_truncated",
            "text_tail": "PARTIAL-ANSWER",
            "reasoning_tail": "",
            "provider_truncated": True,
            "finish_reason": "length",
        },
    )

    assert info["source"] == "persisted_provider_truncated"
    assert info["runtime_fact"] is True
    assert built[-2] == {"role": "assistant", "content": "PARTIAL-ANSWER"}
    assert built[-1]["role"] == "user"
    assert built[-1]["content"].startswith("继续\n\n[provider_runtime_fact—not_human_text]\n")
    assert checkpoint["state_text"] not in "\n".join(str(row.get("content") or "") for row in built)


def test_checkpoint_rejects_unknown_and_duplicate_selection():
    messages = _messages()
    with pytest.raises(ValueError, match="unknown or duplicate"):
        _checkpoint(messages, selected_ids=["e1", "e1"])
    with pytest.raises(ValueError, match="unknown or duplicate"):
        _checkpoint(messages, selected_ids=["e9"])


def test_selected_raw_session_group_remains_authority_without_evidence_ref(monkeypatch):
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_RECEIPTS", "1")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_BATCH_CHARS", "4096")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_GRACE_GROUPS", "0")
    messages = _messages()
    messages[2].metadata = {}
    checkpoint = _checkpoint(messages, selected_ids=["e1"])
    resolution = resolve_working_state_checkpoint(
        checkpoint,
        session_id="s1",
        messages=messages,
        provider_id="deepseek",
        model="deepseek/model",
    )
    projected, _ = project_active_tool_working_set_with_stats(
        messages, preserve_group_digests=resolution.preserve_group_digests
    )

    assert resolution.eligible is True
    assert projected[2].content == messages[2].content


def test_checkpoint_resolution_invalidates_on_new_human_or_protocol_change():
    messages = _messages()
    checkpoint = _checkpoint(messages)
    ok = resolve_working_state_checkpoint(
        checkpoint,
        session_id="s1",
        messages=messages,
        provider_id="deepseek",
        model="deepseek/model",
    )
    assert ok.eligible is True
    assert ok.reason == "eligible"
    assert len(ok.preserve_group_digests) == 1

    changed = list(messages)
    changed[2] = _tool("c1", "CHANGED", ref="evidence://v1/selected")
    changed_result = resolve_working_state_checkpoint(
        checkpoint,
        session_id="s1",
        messages=changed,
        provider_id="deepseek",
        model="deepseek/model",
    )
    assert changed_result.eligible is False
    assert changed_result.reason == "candidate_digest"

    with_new_human = messages + [
        Message(role="user", content="new task", source=MessageSource.USER)
    ]
    stale = resolve_working_state_checkpoint(
        checkpoint,
        session_id="s1",
        messages=with_new_human,
        provider_id="deepseek",
        model="deepseek/model",
    )
    assert stale.eligible is False
    assert stale.reason == "boundary"


def test_projector_never_partially_applies_unknown_preserve_digest(monkeypatch):
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_RECEIPTS", "1")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_BATCH_CHARS", "4096")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_GRACE_GROUPS", "0")
    messages = _messages()
    checkpoint = _checkpoint(messages)
    resolution = resolve_working_state_checkpoint(
        checkpoint,
        session_id="s1",
        messages=messages,
        provider_id="deepseek",
        model="deepseek/model",
    )

    projected, _ = project_active_tool_working_set_with_stats(
        messages,
        preserve_group_digests=resolution.preserve_group_digests + ("v1:unknown",),
    )

    assert "tool_result_receipt" in projected[2].content
    assert "tool_result_receipt" in projected[5].content
    assert projected[8].content == messages[8].content


def test_selected_group_stays_raw_while_unselected_old_group_uses_receipt(monkeypatch):
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_RECEIPTS", "1")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_BATCH_CHARS", "4096")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_GRACE_GROUPS", "0")
    messages = _messages()
    checkpoint = _checkpoint(messages)
    resolution = resolve_working_state_checkpoint(
        checkpoint,
        session_id="s1",
        messages=messages,
        provider_id="deepseek",
        model="deepseek/model",
    )

    projected, stats = project_active_tool_working_set_with_stats(
        messages, preserve_group_digests=resolution.preserve_group_digests
    )

    assert projected[2].content == messages[2].content
    assert "tool_result_receipt" in projected[5].content
    assert projected[8].content == messages[8].content
    assert stats.folded_groups == 1
    # Storage truth remains byte-identical.
    assert messages[5].content.startswith("UNSELECTED-RAW-")


def test_checkpoint_round_trips_through_json_and_event_log(tmp_path: Path):
    sessions = tmp_path / "sessions"
    logs = tmp_path / "event_logs"
    event_store = EventStore(logs, enabled=True)
    store = SessionStore(sessions, event_store=event_store)
    messages = _messages()
    session = Session(session_id="s1", messages=messages)

    # First save establishes session.created without a checkpoint; second save must
    # persist checkpoint through the meta-change path as well as session JSON.
    store.save(session)
    session.working_state_checkpoint = _checkpoint(messages)
    store.save(session)

    json_loaded = SessionStore(sessions).load("s1")
    assert json_loaded.working_state_checkpoint == session.working_state_checkpoint
    assert len(json_loaded.messages) == len(messages)

    replay_loaded = SessionStore(
        sessions, event_store=event_store, read_path_source="event_log"
    ).load("s1")
    assert replay_loaded.working_state_checkpoint == session.working_state_checkpoint
    assert len(replay_loaded.messages) == len(messages)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "engine"),
        extract_enabled=False,
        evidence_mode="off",
        tool_pipeline_enabled=False,
        history_max_chars=200000,
    )


def test_engine_projects_state_provider_only_and_preserves_selected_raw(
    tmp_path: Path, monkeypatch
):
    from llm_loop.factory import build_engine

    monkeypatch.setenv("LFL_TOOL_WORKING_SET_RECEIPTS", "1")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_BATCH_CHARS", "4096")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_GRACE_GROUPS", "0")
    engine = build_engine(_settings(tmp_path))
    sess = Session(session_id="s1", messages=_messages())
    sess.working_state_checkpoint = _checkpoint(sess.messages)
    original_message_count = len(sess.messages)

    wire = engine._build_llm_messages(sess, [], max_chars=200000, planned_label="deepseek/model")
    texts = [str(row.get("content") or "") for row in wire]

    assert '{"verdict":"ready","next":"final"}' in texts
    assert sum(text == '{"verdict":"ready","next":"final"}' for text in texts) == 1
    assert any("SELECTED-RAW-" in text for text in texts)
    assert any("tool_result_receipt" in text and "unselected" in text for text in texts)
    assert len(sess.messages) == original_message_count
    assert all(m.content != '{"verdict":"ready","next":"final"}' for m in sess.messages)


def test_new_human_task_removes_provider_state_without_mutating_checkpoint(
    tmp_path: Path, monkeypatch
):
    from llm_loop.factory import build_engine

    monkeypatch.setenv("LFL_TOOL_WORKING_SET_RECEIPTS", "1")
    engine = build_engine(_settings(tmp_path))
    sess = Session(session_id="s1", messages=_messages())
    sess.working_state_checkpoint = _checkpoint(sess.messages)
    persisted = dict(sess.working_state_checkpoint)
    sess.messages.append(Message(role="user", content="new task", source=MessageSource.USER))

    wire = engine._build_llm_messages(sess, [], max_chars=200000, planned_label="deepseek/model")

    assert all(row.get("content") != persisted["state_text"] for row in wire)
    assert sess.working_state_checkpoint == persisted


def test_checkpoint_resource_limits_are_mechanical_and_fail_before_persistence():
    messages = _messages()
    with pytest.raises(ValueError, match="state_text exceeds resource limit"):
        build_working_state_checkpoint(
            session_id="s1",
            messages=messages,
            provider_id="deepseek",
            model="deepseek/model",
            selected_ids=["e1"],
            state_text="X" * 33,
            state_char_limit=32,
            selected_raw_char_limit=20000,
        )
    with pytest.raises(ValueError, match="selected raw evidence exceeds resource limit"):
        build_working_state_checkpoint(
            session_id="s1",
            messages=messages,
            provider_id="deepseek",
            model="deepseek/model",
            selected_ids=["e1"],
            state_text="ready",
            state_char_limit=32,
            selected_raw_char_limit=1,
        )


def test_persisted_budget_tampering_invalidates_checkpoint():
    messages = _messages()
    checkpoint = _checkpoint(messages)
    checkpoint["selected_raw_char_limit"] = 1
    resolution = resolve_working_state_checkpoint(
        checkpoint,
        session_id="s1",
        messages=messages,
        provider_id="deepseek",
        model="deepseek/model",
    )
    assert resolution.eligible is False
    assert resolution.reason == "selected_over_budget"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("boundary_message_count", None, "boundary_shape"),
        ("boundary_message_count", "bad", "boundary_shape"),
        ("human_anchor_index", None, "human_anchor_shape"),
        ("human_anchor_index", "bad", "human_anchor_shape"),
        ("selection_complete", False, "selection_incomplete"),
        ("selection_finish_reason", "length", "selection_finish_reason"),
        ("state_text", "", "state_text"),
        ("provider_id", "other", "provider"),
        ("model", "other/model", "model"),
    ],
)
def test_malformed_or_mismatched_checkpoint_fails_closed_to_ordinary_view(field, value, reason):
    messages = _messages()
    checkpoint = _checkpoint(messages)
    checkpoint[field] = value

    resolution = resolve_working_state_checkpoint(
        checkpoint,
        session_id="s1",
        messages=messages,
        provider_id="deepseek",
        model="deepseek/model",
    )

    assert resolution.eligible is False
    assert resolution.reason == reason
    assert resolution.preserve_group_digests == ()
    assert resolution.state_text == ""


def test_multi_tool_selected_group_is_preserved_atomically(monkeypatch):
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_RECEIPTS", "1")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_BATCH_CHARS", "4096")
    monkeypatch.setenv("LFL_TOOL_WORKING_SET_GRACE_GROUPS", "0")
    multi = Message(
        role="assistant",
        content="checking both",
        source=MessageSource.USER,
        tool_calls=[
            {"id": "m1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
            {"id": "m2", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
        ],
        model_used="test-model",
        metadata={"answer_origin": "model"},
    )
    messages = [
        Message(role="user", content="task", source=MessageSource.USER),
        multi,
        _tool("m1", "ONE-" * 1500, ref="evidence://v1/m1"),
        _tool("m2", "TWO-" * 1500, ref="evidence://v1/m2"),
        _followup(),
        _assistant("u1"),
        _tool("u1", "UNSELECTED-" * 1000, ref="evidence://v1/u1"),
        _followup(),
        _assistant("latest"),
        _tool("latest", "LATEST", ref="evidence://v1/latest"),
    ]
    checkpoint = build_working_state_checkpoint(
        session_id="s1",
        messages=messages,
        provider_id="deepseek",
        model="deepseek/model",
        selected_ids=["e1"],
        state_text="multi ready",
        state_char_limit=1024,
        selected_raw_char_limit=20000,
    )
    resolution = resolve_working_state_checkpoint(
        checkpoint,
        session_id="s1",
        messages=messages,
        provider_id="deepseek",
        model="deepseek/model",
    )
    projected, _ = project_active_tool_working_set_with_stats(
        messages, preserve_group_digests=resolution.preserve_group_digests
    )

    assert projected[1].tool_calls == messages[1].tool_calls
    assert projected[2].content == messages[2].content
    assert projected[3].content == messages[3].content
    assert "tool_result_receipt" in projected[6].content


def test_event_log_contains_checkpoint_meta_change(tmp_path: Path):
    sessions = tmp_path / "sessions"
    logs = tmp_path / "event_logs"
    event_store = EventStore(logs, enabled=True)
    store = SessionStore(sessions, event_store=event_store)
    messages = _messages()
    session = Session(session_id="s1", messages=messages)
    store.save(session)
    session.working_state_checkpoint = _checkpoint(messages)
    store.save(session)

    events = event_store.read("s1")
    checkpoint_changes = [
        event.payload.get("changes", {}).get("working_state_checkpoint")
        for event in events
        if event.type == "session.meta_changed"
    ]
    checkpoint_changes = [change for change in checkpoint_changes if change]
    assert len(checkpoint_changes) == 1
    assert checkpoint_changes[0]["from"] is None
    assert checkpoint_changes[0]["to"] == session.working_state_checkpoint


def test_later_persisted_message_clears_checkpoint_in_json_and_event_log(tmp_path: Path):
    sessions = tmp_path / "sessions"
    logs = tmp_path / "event_logs"
    event_store = EventStore(logs, enabled=True)
    store = SessionStore(sessions, event_store=event_store)
    messages = _messages()
    session = Session(session_id="s1", messages=messages)
    store.save(session)
    session.working_state_checkpoint = _checkpoint(messages)
    store.save(session)
    assert store.load("s1").working_state_checkpoint is not None

    session.messages.append(_followup("genuine final"))
    store.save(session)
    assert session.working_state_checkpoint is None
    assert SessionStore(sessions).load("s1").working_state_checkpoint is None
    replayed = SessionStore(sessions, event_store=event_store, read_path_source="event_log").load(
        "s1"
    )
    assert replayed.working_state_checkpoint is None

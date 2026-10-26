"""Long-session saves preserve durable facts without reparsing old event JSON."""

from __future__ import annotations

import json
from types import SimpleNamespace

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore
from llm_loop.event_log.replay import replay_session
from llm_loop.event_log.store import EventStore


def _message(text: str) -> Message:
    return Message(role="user", content=text, source=MessageSource.USER)


def test_repeated_saves_backfill_new_messages_without_reparsing_old_events(
    tmp_path, monkeypatch
) -> None:
    events = EventStore(tmp_path / "events")
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    session = sessions.load(sid)
    events.read_cached(sid)
    original_read = events.read
    full_reads = 0

    def counted_read(session_id: str):
        nonlocal full_reads
        full_reads += 1
        return original_read(session_id)

    monkeypatch.setattr(events, "read", counted_read)
    for index in range(4):
        events.append(sid, "request.meta", {"round": index + 1})
        session.messages.append(_message(f"message {index}"))
        sessions.save(session)

    view = replay_session(original_read(sid))
    assert [m["content"] for m in view["messages"]] == [
        f"message {index}" for index in range(4)
    ]
    saved = json.loads((tmp_path / "sessions" / f"{sid}.json").read_text())
    assert len(saved["messages"]) == 4
    assert full_reads == 0


def test_save_observes_external_backfill_and_summary_changes(tmp_path) -> None:
    root = tmp_path / "events"
    events = EventStore(root)
    external = EventStore(root)
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    session = sessions.load(sid)
    events.read_cached(sid)
    session.messages.append(_message("external message"))
    session.fixed_summary = "current summary"
    external.append(
        sid, "message.appended", {"index": 0, "role": "user", "content": "external message"}
    )
    external.append(
        sid, "session.meta_changed",
        {"changes": {"fixed_summary": {"from": "", "to": "older summary"}}},
    )
    sessions.save(session)
    session.messages.append(_message("missing message"))
    sessions.save(session)

    actual = events.read(sid)
    appended = [e for e in actual if e.type == "message.appended"]
    assert [e.payload["index"] for e in appended] == [0, 1]
    view = replay_session(actual)
    assert [m["content"] for m in view["messages"]] == [
        "external message", "missing message"
    ]
    assert view["fixed_summary"] == "current summary"


def test_save_supports_event_stores_with_only_uncached_read(tmp_path) -> None:
    events = EventStore(tmp_path / "events")
    legacy = SimpleNamespace(
        enabled=True, exists=events.exists, read=events.read, append=events.append
    )
    sessions = SessionStore(tmp_path / "sessions", event_store=legacy)
    sid = sessions.create()
    session = sessions.load(sid)
    session.messages.append(_message("legacy store"))
    sessions.save(session)
    view = replay_session(events.read(sid))
    assert [m["content"] for m in view["messages"]] == ["legacy store"]


def test_save_persists_in_place_summary_chain_updates(tmp_path) -> None:
    events = EventStore(tmp_path / "events")
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    session = sessions.load(sid)
    session.summary_chain.append("first")
    sessions.save(session)
    session.summary_chain.append("second")
    sessions.save(session)
    view = replay_session(events.read(sid))
    assert view["summary_chain"] == ["first", "second"]


def test_save_does_not_apply_replay_projection_to_cached_or_live_metadata(tmp_path) -> None:
    events = EventStore(tmp_path / "events")
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    session = sessions.load(sid)
    message = _message("raw message")
    message.metadata = {"original": True}
    session.messages.append(message)
    sessions.save(session)
    events.read_cached(sid)
    events.append(sid, "message.cache_compacted", {"msg_seq": 0, "provider_id": "p"})
    sessions.save(session)
    cached = next(e for e in events.read_cached(sid) if e.type == "message.appended")
    assert cached.payload["metadata"] == {"original": True}
    assert session.messages[0].metadata == {"original": True}
    assert replay_session(events.read(sid))["messages"][0]["metadata"][
        "cache_compacted_for"
    ] == ["p"]


def test_save_persists_nested_checkpoint_updates(tmp_path) -> None:
    events = EventStore(tmp_path / "events")
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    session = sessions.load(sid)
    checkpoint = {"boundary_message_count": 0, "state": {"steps": [1]}}
    session.working_state_checkpoint = checkpoint
    sessions.save(session)
    checkpoint["state"]["steps"].append(2)
    sessions.save(session)
    assert replay_session(events.read(sid))["working_state_checkpoint"] == checkpoint


def test_save_does_not_reset_cached_or_live_source_metadata(tmp_path) -> None:
    events = EventStore(tmp_path / "events")
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    session = sessions.load(sid)
    message = _message("raw message")
    message.metadata = {"cache_compacted_for": ["p"]}
    session.messages.append(message)
    sessions.save(session)
    events.read_cached(sid)
    events.append(
        sid, "history.compaction_state_reset", {"provider_id": "p", "msg_seqs": [0]}
    )
    sessions.save(session)
    cached = next(e for e in events.read_cached(sid) if e.type == "message.appended")
    assert cached.payload["metadata"] == {"cache_compacted_for": ["p"]}
    assert session.messages[0].metadata == {"cache_compacted_for": ["p"]}
    assert "cache_compacted_for" not in replay_session(events.read(sid))["messages"][0][
        "metadata"
    ]

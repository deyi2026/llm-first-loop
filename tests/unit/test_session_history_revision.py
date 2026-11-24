from __future__ import annotations

import os
from pathlib import Path

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore
from llm_loop.event_log.store import EventStore


def test_revision_probe_does_not_read_messages_or_events(tmp_path, monkeypatch):
    events = EventStore(tmp_path / "events")
    store = SessionStore(tmp_path / "sessions", event_store=events)
    sid = store.create()
    before = store.history_revision(sid)
    assert before

    def unexpected(*args, **kwargs):
        raise AssertionError("revision must not load history")

    monkeypatch.setattr(store, "load", unexpected)
    monkeypatch.setattr(events, "read", unexpected)
    monkeypatch.setattr(events, "read_cached", unexpected)
    assert store.history_revision(sid) == before
    events.append(sid, "session.meta_changed", {"field": "test"})
    assert store.history_revision(sid) != before


def test_revision_changes_on_retraction_without_json_write(tmp_path):
    events = EventStore(tmp_path / "events")
    store = SessionStore(tmp_path / "sessions", event_store=events)
    sid = store.create()
    session = store.load(sid)
    session.messages.append(Message(role="user", content="original", source=MessageSource.USER,
                                    metadata={"human_turn_source_id": "feishu:revision-test"}))
    store.save(session)
    path = Path(store._path(sid))
    original = path.read_bytes()
    before = store.history_revision(sid)
    assert store.retract_message_by_source_id("feishu:revision-test")["status"] == "retracted"
    assert path.read_bytes() == original
    assert store.history_revision(sid) != before


def test_revision_changes_on_same_size_atomic_replacement(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    sid = store.create()
    session = store.load(sid)
    session.messages.append(Message(role="user", content="original", source=MessageSource.USER))
    store.save(session)
    assert store.load(sid).messages[-1].content == "original"
    path = Path(store._path(sid))
    before = store.history_revision(sid)
    old = path.stat()
    replacement = path.with_suffix(".replacement")
    replacement.write_bytes(path.read_bytes().replace(b'"original"', b'"modified"'))
    os.utime(replacement, ns=(old.st_atime_ns, old.st_mtime_ns))
    replacement.replace(path)
    assert store.history_revision(sid) != before
    assert store.load(sid).messages[-1].content == "modified"
    path.unlink()
    assert store.history_revision(sid) is None


def test_revision_declines_unbounded_segment_scan(tmp_path):
    events = EventStore(tmp_path / "events")
    store = SessionStore(tmp_path / "sessions", event_store=events)
    sid = store.create()
    directory = Path(events._segment_dir(sid))
    directory.mkdir()
    for i in range(129):
        (directory / f"{i + 1}.jsonl").touch()
    assert store.history_revision(sid) is None


def test_revision_changes_when_existing_segment_changes(tmp_path):
    events = EventStore(tmp_path / "events")
    store = SessionStore(tmp_path / "sessions", event_store=events)
    sid = store.create()
    directory = Path(events._segment_dir(sid))
    directory.mkdir()
    old_segment = directory / "1.jsonl"
    old_segment.write_text("old\n", encoding="utf-8")
    (directory / "2.jsonl").write_text("tail\n", encoding="utf-8")
    before = store.history_revision(sid)
    assert before
    old_segment.write_text("new\n", encoding="utf-8")
    assert store.history_revision(sid) != before

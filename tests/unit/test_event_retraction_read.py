from __future__ import annotations

import os
from pathlib import Path

from llm_loop.event_log.model import EVENT_MESSAGE_RETRACTED, Event, serialize_event
from llm_loop.event_log.store import EventStore


def _row(sid, seq, kind, payload):
    return serialize_event(Event(f"e-{seq}", sid, seq, kind, "2026-11-24T00:00:00Z", payload))


def test_selective_cold_read_parses_only_relevant_or_escaped_rows(tmp_path, monkeypatch):
    store = EventStore(tmp_path)
    sid = "test-session"
    path = Path(store._path(sid))
    rows = [_row(sid, i, "tool.result", {"text": "x" * 10000}) for i in range(1, 101)]
    rows += [_row(sid, 101, EVENT_MESSAGE_RETRACTED, {"source_id": "a"}),
             _row(sid, 102, EVENT_MESSAGE_RETRACTED, {"source_id": "b"}).replace('"message.retracted"', '"message\\u002eretracted"'),
             _row(sid, 103, "tool.result", {"text": "message.retracted"}),
             "malformed message.retracted"]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    expected = [e for e in store.read(sid) if e.type == EVENT_MESSAGE_RETRACTED]
    parse = store._parse_line
    calls = []

    def counted(line):
        calls.append(len(line))
        return parse(line)

    monkeypatch.setattr(store, "_parse_line", counted)
    assert store.read_message_retractions(sid) == expected
    assert len(calls) == 4
    assert store.read_message_retractions(sid) == expected
    assert len(calls) == 4
    assert not store._read_cache


def test_selective_cache_invalidates_same_size_replacement_and_append(tmp_path):
    reader = EventStore(tmp_path)
    writer = EventStore(tmp_path)
    sid = "test-session"
    path = Path(reader._path(sid))
    path.write_text(_row(sid, 1, EVENT_MESSAGE_RETRACTED, {"source_id": "a"}) + "\n", encoding="utf-8")
    assert reader.read_message_retractions(sid)[0].payload["source_id"] == "a"
    old = path.stat()
    replacement = path.with_suffix(".replacement")
    replacement.write_bytes(path.read_bytes().replace(b'"a"', b'"b"'))
    os.utime(replacement, ns=(old.st_atime_ns, old.st_mtime_ns))
    replacement.replace(path)
    assert reader.read_message_retractions(sid)[0].payload["source_id"] == "b"
    writer.append(sid, EVENT_MESSAGE_RETRACTED, {"source_id": "c"})
    assert [e.payload["source_id"] for e in reader.read_message_retractions(sid)] == ["b", "c"]
    path.unlink()
    assert reader.read_message_retractions(sid) == []


def test_selective_segmented_read_and_old_segment_change(tmp_path):
    store = EventStore(tmp_path)
    sid = "test-session"
    directory = Path(store._segment_dir(sid))
    directory.mkdir()
    first = directory / "1.jsonl"
    first.write_text(_row(sid, 1, EVENT_MESSAGE_RETRACTED, {"source_id": "a"}) + "\n", encoding="utf-8")
    (directory / "2.jsonl").write_text(_row(sid, 2, "tool.result", {}) + "\n", encoding="utf-8")
    assert [e.seq for e in store.read_message_retractions(sid)] == [1]
    first.write_text(_row(sid, 1, EVENT_MESSAGE_RETRACTED, {"source_id": "b"}) + "\n", encoding="utf-8")
    assert store.read_message_retractions(sid)[0].payload["source_id"] == "b"


def test_selective_cache_budget_never_truncates_results(tmp_path, monkeypatch):
    store = EventStore(tmp_path)
    monkeypatch.setattr(store, "_retraction_cache_max_bytes", 500)
    monkeypatch.setattr(store, "_retraction_cache_max_sessions", 2)
    for i in range(4):
        sid = f"session-{i}"
        Path(store._path(sid)).write_text(_row(sid, 1, EVENT_MESSAGE_RETRACTED, {"source_id": "a"}) + "\n", encoding="utf-8")
        assert len(store.read_message_retractions(sid)) == 1
    assert len(store._retraction_cache) <= 2
    assert sum(entry[1] for entry in store._retraction_cache.values()) <= 500
    Path(store._path("large")).write_text(_row("large", 1, EVENT_MESSAGE_RETRACTED, {"source_id": "x" * 1000}) + "\n", encoding="utf-8")
    assert len(store.read_message_retractions("large")[0].payload["source_id"]) == 1000
    assert "large" not in store._retraction_cache


def test_selective_read_does_not_cache_unstable_snapshot(tmp_path, monkeypatch):
    store = EventStore(tmp_path)
    sid = "test-session"
    Path(store._path(sid)).write_text(_row(sid, 1, EVENT_MESSAGE_RETRACTED, {"source_id": "a"}) + "\n", encoding="utf-8")
    stamps = iter([("before",), ("after",)])
    monkeypatch.setattr(store, "history_source_stamp", lambda _sid: next(stamps))
    assert len(store.read_message_retractions(sid)) == 1
    assert sid not in store._retraction_cache

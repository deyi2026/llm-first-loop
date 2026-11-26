"""Usage projection must preserve accounting and avoid re-parsing sealed history."""
from __future__ import annotations

import json
from pathlib import Path

from llm_loop.event_log.store import EventStore
from llm_loop.event_log.usage_projection import UsageEventProjection


def _row(sid: str, seq: int, kind: str, payload: dict) -> str:
    return json.dumps({
        "event_id": f"e{seq}", "session_id": sid, "seq": seq, "type": kind,
        "ts": "2026-01-01T00:00:00", "payload": payload,
    }) + "\n"


def test_usage_projection_matches_canonical_and_reuses_sealed_segments(tmp_path, monkeypatch):
    store = EventStore(tmp_path)
    sid = "session-usage"
    directory = tmp_path / sid
    directory.mkdir()
    first = directory / "1.jsonl"
    second = directory / "2.jsonl"
    first.write_text(_row(sid, 1, "message.appended", {"content": "x" * 100000})
                     + _row(sid, 2, "request.usage", {"tokens_in": 20})
                     + "not-json\n", encoding="utf-8")
    second.write_text(_row(sid, 3, "provider.transport.opened", {"attempt_id": "a"})
                      + _row(sid, 4, "provider.transport.settled", {"attempt_id": "a"}),
                      encoding="utf-8")
    expected = [e for e in store.read(sid) if UsageEventProjection.includes(e.type)]
    assert store.read_usage_events(sid) == expected
    original = store._usage_projection._scan
    scans = []

    def record(path, before, parse):
        scans.append(Path(path).name)
        return original(path, before, parse)

    monkeypatch.setattr(store._usage_projection, "_scan", record)
    assert store.read_usage_events(sid) == expected
    assert scans == []
    with second.open("a", encoding="utf-8") as stream:
        stream.write(_row(sid, 5, "request.usage", {"tokens_in": 30}))
    assert [e.seq for e in store.read_usage_events(sid)] == [2, 3, 4, 5]
    assert scans == ["2.jsonl"]
    first.write_text(_row(sid, 2, "request.usage", {"tokens_in": 99}), encoding="utf-8")
    assert store.read_usage_events(sid)[0].payload["tokens_in"] == 99
    assert scans == ["2.jsonl", "1.jsonl"]


def test_escaped_event_type_and_delete(tmp_path):
    store = EventStore(tmp_path)
    sid = "escaped"
    path = tmp_path / (sid + ".jsonl")
    path.write_text(_row(sid, 1, "request.usage", {"tokens_in": 5}).replace(
        "request.usage", r"request.\u0075sage"), encoding="utf-8")
    assert [e.seq for e in store.read_usage_events(sid)] == [1]
    store.delete_session(sid)
    assert store.read_usage_events(sid) == []
    assert not store._usage_projection._cache


def test_projection_cache_bounded(tmp_path):
    store = EventStore(tmp_path)
    projection = UsageEventProjection(max_segments=1, max_bytes=1024)
    for sid in ("a", "b"):
        path = tmp_path / (sid + ".jsonl")
        path.write_text(_row(sid, 1, "request.usage", {"tokens_in": 5}), encoding="utf-8")
        assert projection.read(sid, [str(path)], store._parse_line)
    assert len(projection._cache) == 1
    assert projection._bytes <= 1024
    path = tmp_path / "large.jsonl"
    path.write_text(_row("large", 1, "request.usage", {"extra": "x" * 2048}), encoding="utf-8")
    assert projection.read("large", [str(path)], store._parse_line)
    assert all(key[0] != "large" for key in projection._cache)

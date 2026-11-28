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


def test_settlement_projection_matches_full_fold_and_reuses_sealed_segments(tmp_path, monkeypatch):
    from llm_loop.core.subagent_delivery import SubAgentDeliveryJournal

    store = EventStore(tmp_path)
    sid = "parent-settlement"
    directory = tmp_path / sid
    directory.mkdir()
    first = directory / "1.jsonl"
    second = directory / "2.jsonl"
    binding = {"child_id": "subagent_x", "parent_id": sid, "generation": "g1", "result_id": "r1"}
    receipt = {"tool_name": "subagent_result", "tool_call_id": "call",
               "metadata": {"subagent_settlement": binding}}
    commit = {"tool_name": "subagent_result", "tool_call_id": "call"}
    first.write_text(
        _row(sid, 1, "message.appended", {"content": "x" * 100000})
        + _row(sid, 2, "message.appended", receipt).replace(
            "subagent_result", r"subagent_\u0072esult")
        + _row(sid, 3, "request.meta", {"content": "subagent_result"})
        + "not-json\n", encoding="utf-8")
    second.write_text(_row(sid, 4, "tool.execution.receipt_committed", commit),
                      encoding="utf-8")
    journal = SubAgentDeliveryJournal(store)
    assert journal.settlement_committed(**binding)
    expected = [e for e in store.read(sid) if store._settlement_projection.accepts(e)]
    assert store.read_settlement_events_for_display(sid) == expected
    assert journal.settlement_committed_for_display(**binding)
    assert not journal.settlement_committed_for_display(**{**binding, "generation": "g2"})
    scans = []
    original = store._settlement_projection._scan

    def record(path, before, parse):
        scans.append(Path(path).name)
        return original(path, before, parse)

    monkeypatch.setattr(store._settlement_projection, "_scan", record)
    assert journal.settlement_committed_for_display(**binding)
    assert scans == []
    with second.open("a", encoding="utf-8") as stream:
        stream.write(_row(sid, 5, "message.appended", receipt))
    # A newer matching message requires a later commit; don't reuse a stale positive.
    assert not journal.settlement_committed_for_display(**binding)
    assert scans == ["2.jsonl"]
    with second.open("a", encoding="utf-8") as stream:
        stream.write(_row(sid, 6, "tool.execution.receipt_committed", commit))
    assert journal.settlement_committed_for_display(**binding)
    first.write_text(_row(sid, 2, "request.meta", {}), encoding="utf-8")
    assert journal.settlement_committed_for_display(**binding)
    second.write_text(_row(sid, 6, "tool.execution.receipt_committed", commit),
                      encoding="utf-8")
    # Same last seq, changed content: filesystem stamp must invalidate the display cache.
    assert not journal.settlement_committed_for_display(**binding)
    assert scans == ["2.jsonl", "2.jsonl", "1.jsonl", "2.jsonl"]
    store.delete_session(sid)
    assert not store._settlement_projection._cache
    assert not journal.settlement_committed_for_display(**binding)


def test_settlement_projection_skips_unrelated_large_payloads(tmp_path, monkeypatch):
    store = EventStore(tmp_path)
    sid = "large-parent"
    path = tmp_path / (sid + ".jsonl")
    path.write_text("".join(_row(sid, seq, "message.appended", {"content": "x" * 8192})
                            for seq in range(1, 1001))
                    + _row(sid, 1001, "tool.execution.receipt_committed",
                           {"tool_name": "subagent_result", "tool_call_id": "call"}),
                    encoding="utf-8")
    parsed = 0
    original = store._parse_line

    def count(line):
        nonlocal parsed
        parsed += 1
        return original(line)

    monkeypatch.setattr(store, "_parse_line", count)
    assert [e.seq for e in store.read_settlement_events_for_display(sid)] == [1001]
    assert parsed == 1
    assert [e.seq for e in store.read_settlement_events_for_display(sid)] == [1001]
    assert parsed == 1
    assert store._settlement_projection._bytes < 1024


def test_display_binding_cache_uses_source_stamp_not_tail_seq(tmp_path, monkeypatch):
    from llm_loop.core.subagent_delivery import SubAgentDeliveryJournal

    store = EventStore(tmp_path)
    sid = "parent-stamp"
    path = tmp_path / (sid + ".jsonl")
    binding = {"child_id": "subagent_x", "parent_id": sid, "generation": "g1", "result_id": "r1"}
    receipt = {"tool_name": "subagent_result", "tool_call_id": "c",
               "metadata": {"subagent_settlement": binding}}
    commit = {"tool_name": "subagent_result", "tool_call_id": "c"}
    path.write_text(_row(sid, 1, "message.appended", receipt)
                    + _row(sid, 2, "tool.execution.receipt_committed", commit),
                    encoding="utf-8")
    journal = SubAgentDeliveryJournal(store)
    original = store.read_settlement_events_for_display
    reads = []

    def counted(parent):
        reads.append(parent)
        return original(parent)

    monkeypatch.setattr(store, "read_settlement_events_for_display", counted)
    assert journal.settlement_committed_for_display(**binding)
    for _ in range(8):
        assert journal.settlement_committed_for_display(**binding)
    assert reads == [sid]
    assert not journal._settlement_cache
    path.write_text(_row(sid, 1, "request.meta", {})
                    + _row(sid, 2, "tool.execution.receipt_committed", commit),
                    encoding="utf-8")
    assert not journal.settlement_committed_for_display(**binding)
    assert reads == [sid, sid]

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from llm_loop.core.message import Message, MessageSource
from llm_loop.event_log.store import EventStore
from llm_loop.web import build_app
from llm_loop.web.schemas import MessageItem


def _seed(build_test_engine, events=None):
    engine, _ = build_test_engine([])
    if events is not None:
        engine._event_store = events
        engine.session._event_store = events
    sid = engine.session.create()
    session = engine.session.load(sid)
    session.messages = [
        Message(role="user", content="small", source=MessageSource.USER),
        Message(role="user", content="中文\n\t" * 20000, source=MessageSource.USER,
                metadata={"human_turn_source_id": "feishu:compact-test"}),
        Message(role="assistant", content="short answer", source=MessageSource.SYSTEM,
                reasoning_content="r" * 40000,
                tool_calls=[{"id": "call", "function": {"name": "test", "arguments": "x" * 50000}}]),
        Message(role="tool", content="tool result" * 10000, source=MessageSource.TOOL, tool_call_id="call"),
    ]
    engine.session.save(session)
    return engine, sid, TestClient(build_app(engine=engine))


def test_compact_page_preserves_offsets_and_exact_original(build_test_engine):
    _, sid, client = _seed(build_test_engine)
    url = f"/api/v1/sessions/{sid}/messages"
    full = client.get(url, params={"limit": 4}).json()
    response = client.get(url, params={"limit": 4, "compact": True})
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 4 and len(page["messages"]) == 4
    assert len(response.content) < 16000
    assert page["messages"][0] == full["messages"][0]
    for i in (1, 2, 3):
        row = page["messages"][i]
        ref = row["history_preview"]
        assert ref["offset"] == 3 - i
        assert ref["revision"] == page["revision"]
        original = full["messages"][i]
        raw = MessageItem.model_validate(original).model_dump_json().encode()
        assert ref["sha256"] == hashlib.sha256(raw).hexdigest()
        assert ref["bytes"] == len(raw)
        exact = client.get(url, params={"limit": 1, "offset": ref["offset"],
                           "snapshot_revision": ref["revision"], "expected_sha256": ref["sha256"]})
        assert exact.status_code == 200
        assert exact.json()["verified_sha256"] == ref["sha256"]
        assert exact.json()["messages"] == [original]
    assert page["messages"][2]["tool_calls"] is None
    assert page["messages"][2]["reasoning_content"] is None


def test_compact_original_rejects_wrong_hash_position_and_changed_snapshot(build_test_engine):
    engine, sid, client = _seed(build_test_engine)
    url = f"/api/v1/sessions/{sid}/messages"
    page = client.get(url, params={"limit": 4, "compact": True}).json()
    ref = page["messages"][1]["history_preview"]
    params = {"limit": 1, "offset": ref["offset"], "snapshot_revision": ref["revision"], "expected_sha256": ref["sha256"]}
    assert client.get(url, params={**params, "offset": 0}).status_code == 409
    assert client.get(url, params={**params, "expected_sha256": "0" * 64}).status_code == 409
    assert client.get(url, params={**params, "limit": 2}).status_code == 400
    assert client.get(url, params={"limit": 101, "compact": True}).status_code == 400
    session = engine.session.load(sid)
    session.messages.append(Message(role="user", content="new", source=MessageSource.USER))
    engine.session.save(session)
    assert client.get(url, params=params).status_code == 409


def test_initial_compact_page_drops_unstable_revision_instead_of_blocking_active_run(build_test_engine, monkeypatch):
    engine, sid, client = _seed(build_test_engine)
    original = engine.session.history_revision(sid)
    assert original
    calls = iter([original, original, "changed"])
    monkeypatch.setattr(engine.session, "history_revision", lambda _sid: next(calls, "changed"))
    response = client.get(f"/api/v1/sessions/{sid}/messages", params={"limit": 4, "compact": True})
    assert response.status_code == 200
    page = response.json()
    assert page["revision"] is None
    assert page["messages"][1]["history_preview"]["revision"] is None


def test_compact_large_window_has_bounded_response_and_no_lost_rows(build_test_engine):
    engine, sid, client = _seed(build_test_engine)
    session = engine.session.load(sid)
    session.messages = [Message(role="user", content=f"row-{i} " + "\n" * 9000, source=MessageSource.USER) for i in range(105)]
    engine.session.save(session)
    url = f"/api/v1/sessions/{sid}/messages"
    first = client.get(url, params={"limit": 50, "compact": True})
    legacy = client.get(url, params={"limit": 50})
    assert first.status_code == 200
    assert legacy.status_code == 200
    assert len(first.content) < 50 * 8192 + 4096
    assert len(first.content) < len(legacy.content) / 8
    print(f"COMPACT_HTTP_BYTES legacy={len(legacy.content)} compact={len(first.content)} rows=50")
    body = first.json()
    second = client.get(url, params={"limit": 50, "offset": 50, "compact": True, "snapshot_revision": body["revision"]}).json()
    third = client.get(url, params={"limit": 50, "offset": 100, "compact": True, "snapshot_revision": body["revision"]}).json()
    rows = third["messages"] + second["messages"] + body["messages"]
    assert [r["history_preview"]["offset"] for r in rows] == list(range(104, -1, -1))
    assert not third["has_more"]


def test_retraction_invalidates_original_reference(build_test_engine, tmp_path):
    events = EventStore(tmp_path / "events")
    engine, sid, client = _seed(build_test_engine, events)
    url = f"/api/v1/sessions/{sid}/messages"
    page = client.get(url, params={"limit": 4, "compact": True}).json()
    ref = page["messages"][1]["history_preview"]
    assert engine.session.retract_message_by_source_id("feishu:compact-test")["status"] == "retracted"
    response = client.get(url, params={"limit": 1, "offset": ref["offset"], "snapshot_revision": ref["revision"], "expected_sha256": ref["sha256"]})
    assert response.status_code == 409
    fresh = client.get(url, params={"limit": 4, "compact": True}).json()
    assert fresh["messages"][1]["content"] == "[RETRACTED]"
    assert fresh["messages"][1]["history_preview"] is None


def test_program_final_preview_expands_exact_hydrated_text(build_test_engine, tmp_path):
    engine, _ = build_test_engine([])
    events = EventStore(tmp_path / "events")
    engine._event_store = events
    engine.session._event_store = events
    sid = engine.session.create()
    text = "terminal evidence 中文\n" * 5000
    event = events.append(sid, "program.final", {"full_text": text})
    assert event is not None
    session = engine.session.load(sid)
    session.messages.append(Message(role="assistant", content="", source=MessageSource.SYSTEM,
                                    metadata={"program_final_placeholder": True, "program_final_event_seq": event.seq}))
    engine.session.save(session)
    client = TestClient(build_app(engine=engine))
    url = f"/api/v1/sessions/{sid}/messages"
    page = client.get(url, params={"limit": 1, "compact": True}).json()
    ref = page["messages"][0]["history_preview"]
    exact = client.get(url, params={"limit": 1, "offset": 0, "snapshot_revision": ref["revision"], "expected_sha256": ref["sha256"]})
    assert exact.status_code == 200
    assert exact.json()["messages"][0]["content"] == text
    assert engine.session.load(sid).messages[0].content == ""

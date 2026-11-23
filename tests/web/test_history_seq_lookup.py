"""Web history restores only requested terminal facts, without full event replay."""

from fastapi.testclient import TestClient

from llm_loop.core.message import Message, MessageSource
from llm_loop.event_log.store import EventStore
from llm_loop.web import build_app


def test_history_hydration_never_replays_whole_event_log(build_test_engine, tmp_path, monkeypatch):
    engine, _ = build_test_engine([])
    engine._event_store = EventStore(tmp_path / "events")  # pyright: ignore[reportPrivateUsage]
    sid = engine.session.create()
    event = engine._event_store.append(  # pyright: ignore[reportPrivateUsage]
        sid, "program.final", {"full_text": "真实终态文本"}
    )
    assert event is not None
    session = engine.session.load(sid)
    session.messages.append(Message(
        role="assistant", content="", source=MessageSource.SYSTEM,
        metadata={"program_final_placeholder": True, "program_final_event_seq": event.seq},
    ))
    engine.session.save(session)

    def forbidden(_sid):
        raise AssertionError("full event replay is forbidden for a history page")

    monkeypatch.setattr(engine._event_store, "read_cached", forbidden)  # pyright: ignore[reportPrivateUsage]
    response = TestClient(build_app(engine=engine)).get(
        f"/api/v1/sessions/{sid}/messages?limit=1&offset=0"
    )
    assert response.status_code == 200
    assert response.json()["messages"][-1]["content"] == "真实终态文本"
    assert engine.session.load(sid).messages[-1].content == ""


def test_malformed_terminal_seq_does_not_crash_history(build_test_engine):
    engine, _ = build_test_engine([])
    sid = engine.session.create()
    session = engine.session.load(sid)
    session.messages.append(Message(
        role="assistant", content="", source=MessageSource.SYSTEM,
        metadata={"program_final_placeholder": True, "program_final_event_seq": "invalid"},
    ))
    engine.session.save(session)
    response = TestClient(build_app(engine=engine)).get(
        f"/api/v1/sessions/{sid}/messages?limit=1"
    )
    assert response.status_code == 200
    assert response.json()["messages"][-1]["content"] == ""


def test_pagination_hydrates_only_the_requested_page(build_test_engine, tmp_path, monkeypatch):
    engine, _ = build_test_engine([])
    engine._event_store = EventStore(tmp_path / "events")  # pyright: ignore[reportPrivateUsage]
    sid = engine.session.create()
    session = engine.session.load(sid)
    seqs = []
    for text in ("旧终态", "新终态"):
        event = engine._event_store.append(sid, "program.final", {"full_text": text})  # pyright: ignore[reportPrivateUsage]
        assert event is not None
        seqs.append(event.seq)
        session.messages.append(Message(
            role="assistant", content="", source=MessageSource.SYSTEM,
            metadata={"program_final_placeholder": True, "program_final_event_seq": event.seq},
        ))
    session.messages.append(Message(role="user", content="普通消息", source=MessageSource.USER))
    engine.session.save(session)
    store = engine._event_store  # pyright: ignore[reportPrivateUsage]
    original = store.read_seqs
    requested: list[set[int]] = []

    def spy(_sid: str, wanted: set[int]):
        requested.append(set(wanted))
        return original(_sid, wanted)

    monkeypatch.setattr(store, "read_seqs", spy)
    client = TestClient(build_app(engine=engine))
    assert client.get(f"/api/v1/sessions/{sid}/messages?limit=1&offset=0").json()["messages"][0]["content"] == "普通消息"
    assert requested == []
    assert client.get(f"/api/v1/sessions/{sid}/messages?limit=1&offset=1").json()["messages"][0]["content"] == "新终态"
    assert client.get(f"/api/v1/sessions/{sid}/messages?limit=1&offset=2").json()["messages"][0]["content"] == "旧终态"
    assert requested == [{seqs[1]}, {seqs[0]}]

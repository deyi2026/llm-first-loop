from __future__ import annotations

from pathlib import Path

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore
from llm_loop.event_log.model import EVENT_MESSAGE_RETRACTED
from llm_loop.event_log.replay import replay_session
from llm_loop.event_log.store import EventStore

SOURCE_ID = "feishu:om_retract_1"


def _stores(tmp_path: Path) -> tuple[SessionStore, EventStore]:
    events = EventStore(tmp_path / "events")
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    return sessions, events


def _seed_user(sessions: SessionStore, text: str = "不应再进入后续模型上下文") -> str:
    sid = sessions.create()
    sess = sessions.load(sid)
    sess.messages.append(
        Message(
            role="user",
            content=text,
            source=MessageSource.USER,
            metadata={
                "human_turn_source_id": SOURCE_ID,
                "attachments": [{"text": "撤回附件正文也不能继续投影"}],
            },
        )
    )
    sessions.save(sess)
    return sid


def test_retraction_event_keeps_original_audit_but_replay_projects_marker(tmp_path: Path):
    sessions, events = _stores(tmp_path)
    sid = _seed_user(sessions)

    result = sessions.retract_message_by_source_id(
        SOURCE_ID,
        actor="feishu_user",
        reason="source_recalled",
        retracted_at="2026-09-12T02:00:00+00:00",
    )
    assert result["status"] == "retracted"
    assert result["session_id"] == sid

    logged = events.read(sid)
    original = next(e for e in logged if e.type == "message.appended")
    assert original.payload["content"] == "不应再进入后续模型上下文"
    retractions = [e for e in logged if e.type == EVENT_MESSAGE_RETRACTED]
    assert len(retractions) == 1
    assert retractions[0].payload["source_id"] == SOURCE_ID

    view = replay_session(logged)
    projected = view["messages"][0]
    assert projected["content"] == "[RETRACTED]"
    assert projected["metadata"]["retracted"] is True
    assert "attachments" not in projected["metadata"]


def test_session_json_read_path_overlays_append_only_retraction(tmp_path: Path):
    sessions, _events = _stores(tmp_path)
    sid = _seed_user(sessions, "原始 JSON 仍保留这个正文")

    raw_path = tmp_path / "sessions" / f"{sid}.json"
    assert "原始 JSON 仍保留这个正文" in raw_path.read_text(encoding="utf-8")

    assert sessions.retract_message_by_source_id(SOURCE_ID)["status"] == "retracted"

    loaded = sessions.load(sid)
    assert loaded.messages[0].content == "[RETRACTED]"
    assert loaded.messages[0].metadata["retracted"] is True
    # retraction is an overlay: append-only event is authority; the original derived JSON
    # is not destructively rewritten and remains auditable.
    assert "原始 JSON 仍保留这个正文" in raw_path.read_text(encoding="utf-8")


def test_retraction_is_idempotent_and_does_not_append_duplicate_events(tmp_path: Path):
    sessions, events = _stores(tmp_path)
    sid = _seed_user(sessions)

    first = sessions.retract_message_by_source_id(SOURCE_ID)
    second = sessions.retract_message_by_source_id(SOURCE_ID)

    assert first["status"] == "retracted"
    assert second["status"] == "already_retracted"
    assert len([e for e in events.read(sid) if e.type == EVENT_MESSAGE_RETRACTED]) == 1


def test_retracted_message_wire_never_reprojects_attachments():
    msg = Message(
        role="user",
        content="原文",
        source=MessageSource.USER,
        metadata={
            "retracted": True,
            "attachments": [{"text": "附件秘密"}],
        },
    )
    assert msg.to_llm_dict() == {"role": "user", "content": "[RETRACTED]"}


def test_engine_ingress_persists_exact_source_id_into_eventstore(build_test_engine, tmp_path: Path):
    from llm_loop.core.trace_leak.ingress_token import issue_ingress

    engine, _fake = build_test_engine([{"content": "ok"}])
    events = EventStore(tmp_path / "engine-events")
    engine._event_store = events  # noqa: SLF001 - explicit integration wiring under test
    engine.session._event_store = events  # noqa: SLF001
    sid = engine.session.create()

    result = engine.run(
        sid,
        "来自飞书的原始消息",
        ingress=issue_ingress("feishu"),
        user_metadata={"human_turn_source_id": "feishu:om_engine_exact"},
    )
    assert result.final_answer == "ok"

    ingress = [
        e
        for e in events.read(sid)
        if e.type == "message.appended"
        and e.payload.get("role") == "user"
    ]
    assert len(ingress) == 1
    assert ingress[0].payload["metadata"]["human_turn_source_id"] == "feishu:om_engine_exact"


def test_same_exact_source_id_is_retracted_in_every_session_projection(tmp_path: Path):
    sessions, events = _stores(tmp_path)
    sids: list[str] = []
    for _ in range(2):
        sid = _seed_user(sessions, "同一上游消息在分支中的副本")
        sids.append(sid)

    result = sessions.retract_message_by_source_id(SOURCE_ID)
    assert result["status"] == "retracted"
    assert set(result["session_ids"]) == set(sids)
    for sid in sids:
        assert sessions.load(sid).messages[0].content == "[RETRACTED]"
        assert len([e for e in events.read(sid) if e.type == EVENT_MESSAGE_RETRACTED]) == 1


def test_partial_fork_keeps_late_retraction_for_inherited_message():
    from llm_loop.event_log.fork import _truncate_events
    from llm_loop.event_log.model import Event

    def ev(seq: int, type_: str, payload: dict) -> Event:
        return Event(
            event_id=f"e{seq}",
            session_id="source",
            seq=seq,
            type=type_,
            ts="2026-09-12T00:00:00+00:00",
            payload=payload,
        )

    events = [
        ev(1, "session.created", {"version": 5}),
        ev(2, "message.appended", {
            "index": 0,
            "role": "user",
            "content": "必须保持撤回",
            "source": "user",
            "metadata": {"human_turn_source_id": SOURCE_ID},
        }),
        ev(3, "message.appended", {
            "index": 1,
            "role": "assistant",
            "content": "later",
            "source": "user",
            "metadata": {},
        }),
        ev(4, EVENT_MESSAGE_RETRACTED, {
            "source_id": SOURCE_ID,
            "msg_seq": 0,
            "actor": "unknown",
            "reason": "source_recalled",
            "retracted_at": "2026-09-12T00:01:00+00:00",
        }),
    ]

    inherited = _truncate_events(events, 1)
    assert [e.seq for e in inherited] == [1, 2, 4]
    assert replay_session(inherited)["messages"][0]["content"] == "[RETRACTED]"

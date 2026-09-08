from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from llm_loop.core.loop.events import _EventsMixin
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore
from llm_loop.event_log.model import EVENT_MESSAGE_APPENDED, build_message_payload
from llm_loop.event_log.store import EventStore


def _m(content: str, *, role: str = "user") -> Message:
    return Message(role=role, content=content, source=MessageSource.USER)  # type: ignore[arg-type]


class _Event:
    type = "message.appended"


class _Store:
    enabled = True

    def __init__(self, count: int) -> None:
        self.count = count

    def exists(self, _session_id: str) -> bool:
        return True

    def read(self, _session_id: str) -> list[_Event]:
        return [_Event() for _ in range(self.count)]


class _SessionStore:
    def __init__(self, replay_messages: list[Message] | None) -> None:
        self.replay_messages = replay_messages
        self.calls = 0

    def _load_from_event_log(self, _session_id: str):
        self.calls += 1
        if self.replay_messages is None:
            return None
        return SimpleNamespace(messages=list(self.replay_messages))


class _Harness(_EventsMixin):
    _event_store: Any
    session: Any

    def __init__(self, *, event_count: int, replay_messages: list[Message] | None) -> None:
        self._event_store = _Store(event_count)
        self.session = _SessionStore(replay_messages)
        self.actions: list[tuple[str, str, str]] = []

    def _record_action(self, phase: str, action_type: str, detail: str) -> None:
        self.actions.append((phase, action_type, detail))


def test_repair_inserts_missing_history_before_live_current_user() -> None:
    old = _m("old")
    missing1 = _m("missing-1", role="assistant")
    missing2 = _m("missing-2")
    current = _m("CURRENT")
    sess = SimpleNamespace(messages=[old, current])
    h = _Harness(event_count=4, replay_messages=[old, missing1, missing2, _m("CURRENT")])

    h._inject_interruption_recovery("sid", sess)

    assert [m.content for m in sess.messages] == ["old", "missing-1", "missing-2", "CURRENT"]
    assert sess.messages[-1] is current, "must preserve the live ingress object"
    assert h.actions == [
        (
            "run.interruption_recovery",
            "repaired",
            "event_messages=4;memory_messages=2;recovered=2;prompt_chars=0",
        )
    ]
    assert not hasattr(h, "_tip_tail_messages")


def test_repair_preserves_current_user_when_its_event_append_failed() -> None:
    old = _m("old")
    missing = _m("missing", role="assistant")
    current = _m("CURRENT")
    sess = SimpleNamespace(messages=[old, current])
    h = _Harness(event_count=2, replay_messages=[old, missing])

    h._inject_interruption_recovery("sid", sess)

    assert [m.content for m in sess.messages] == ["old", "missing", "CURRENT"]
    assert sess.messages[-1] is current
    assert h.actions[-1][1] == "repaired"
    assert "recovered=1" in h.actions[-1][2]
    assert "prompt_chars=0" in h.actions[-1][2]


def test_prefix_mismatch_fails_open_without_prompt_or_mutation() -> None:
    old = _m("old")
    current = _m("CURRENT")
    original = [old, current]
    sess = SimpleNamespace(messages=list(original))
    h = _Harness(event_count=3, replay_messages=[_m("DIFFERENT"), _m("missing"), _m("CURRENT")])

    h._inject_interruption_recovery("sid", sess)

    assert sess.messages == original
    assert h.actions[-1][1] == "repair_failed"
    assert "reason=prefix_mismatch" in h.actions[-1][2]
    assert "prompt_chars=0" in h.actions[-1][2]
    assert not hasattr(h, "_tip_tail_messages")


def test_replay_failure_fails_open_without_prompt() -> None:
    sess = SimpleNamespace(messages=[_m("old"), _m("CURRENT")])
    h = _Harness(event_count=3, replay_messages=None)

    h._inject_interruption_recovery("sid", sess)

    assert [m.content for m in sess.messages] == ["old", "CURRENT"]
    assert h.actions[-1][1] == "repair_failed"
    assert "reason=replay_failed" in h.actions[-1][2]
    assert not hasattr(h, "_tip_tail_messages")


def test_no_gap_does_not_replay_or_emit_observability() -> None:
    sess = SimpleNamespace(messages=[_m("old"), _m("CURRENT")])
    h = _Harness(event_count=2, replay_messages=[_m("old"), _m("CURRENT")])

    h._inject_interruption_recovery("sid", sess)

    assert h.session.calls == 1
    assert h.actions == []
    assert [m.content for m in sess.messages] == ["old", "CURRENT"]


def test_event_log_behind_live_prefix_is_ignored_without_prompt() -> None:
    sess = SimpleNamespace(messages=[_m("old-1"), _m("old-2"), _m("CURRENT")])
    h = _Harness(event_count=1, replay_messages=[_m("old-1")])

    h._inject_interruption_recovery("sid", sess)

    assert [m.content for m in sess.messages] == ["old-1", "old-2", "CURRENT"]
    assert h.actions == []
    assert not hasattr(h, "_tip_tail_messages")


def test_ambiguous_current_user_position_refuses_to_guess() -> None:
    old = _m("old")
    current = _m("CURRENT")
    sess = SimpleNamespace(messages=[old, current])
    h = _Harness(
        event_count=4,
        replay_messages=[old, _m("CURRENT"), _m("later"), _m("CURRENT")],
    )

    h._inject_interruption_recovery("sid", sess)

    assert [m.content for m in sess.messages] == ["old", "CURRENT"]
    assert h.actions[-1][1] == "repair_failed"
    assert "reason=current_user_order" in h.actions[-1][2]


def test_real_event_store_replay_repairs_duplicate_interrupted_index(tmp_path) -> None:
    """Real replay path: previous crash and current ingress may reuse the same index."""
    event_store = EventStore(tmp_path / "events", enabled=True)
    session_store = SessionStore(tmp_path / "sessions", event_store=event_store)
    sid = session_store.create()
    old = _m("old")
    session_store.append(sid, old)
    sess = session_store.load(sid)

    # Previous process wrote this event but died before session JSON save. Its index=1.
    event_store.append(
        sid,
        EVENT_MESSAGE_APPENDED,
        build_message_payload(
            index=1,
            role="assistant",
            content="MISSING_FROM_JSON",
            source=MessageSource.USER.value,
        ),
    )

    # New run loaded the stale JSON, so its current ingress also uses index=1. Replay's
    # existing duplicate-index rule must retain both in event sequence order.
    current = _m("CURRENT")
    sess.messages.append(current)
    event_store.append(
        sid,
        EVENT_MESSAGE_APPENDED,
        build_message_payload(
            index=1,
            role="user",
            content="CURRENT",
            source=MessageSource.USER.value,
        ),
    )

    h = _Harness(event_count=0, replay_messages=[])
    h._event_store = event_store
    h.session = session_store

    h._inject_interruption_recovery(sid, sess)

    assert [m.content for m in sess.messages] == ["old", "MISSING_FROM_JSON", "CURRENT"]
    assert sess.messages[-1] is current
    assert h.actions[-1][1] == "repaired"
    assert "recovered=1" in h.actions[-1][2]
    assert "prompt_chars=0" in h.actions[-1][2]
    assert not hasattr(h, "_tip_tail_messages")


def test_pre_ingress_repair_restores_open_human_task_before_resolved_history_retirement() -> None:
    """Crash-open human authority survives even when older completed episodes retire."""
    from llm_loop.core.episode_history import provider_view_without_resolved_episodes

    ref = "episode:sid:0:done"
    old_user = _m("OLD-RESOLVED-TASK")
    old_user.metadata["resolved_episode_ref"] = ref
    old_answer = _m("OLD-RESOLVED-ANSWER", role="assistant")
    old_answer.metadata.update(
        {
            "resolved_episode_ref": ref,
            "answer_origin": "model",
            "run_end_reason": "completed",
            "episode_resolution_candidate": True,
        }
    )
    active_user = _m("帮我去 GitHub 仓库核实作者身份、许可证和实际代码结构。")
    partial = _m("I have the README; now verify author/license/tree", role="assistant")
    sess = SimpleNamespace(messages=[old_user, old_answer])
    h = _Harness(
        event_count=4,
        replay_messages=[old_user, old_answer, active_user, partial],
    )

    # Production ordering: repair runs before the new follow-up human ingress exists.
    h._inject_interruption_recovery("sid", sess)

    assert [m.content for m in sess.messages] == [
        "OLD-RESOLVED-TASK",
        "OLD-RESOLVED-ANSWER",
        "帮我去 GitHub 仓库核实作者身份、许可证和实际代码结构。",
        "I have the README; now verify author/license/tree",
    ]
    projected = provider_view_without_resolved_episodes(sess.messages)
    visible = [m.content for m in projected]
    assert "OLD-RESOLVED-TASK" not in visible
    assert "OLD-RESOLVED-ANSWER" not in visible
    assert "帮我去 GitHub 仓库核实作者身份、许可证和实际代码结构。" in visible
    assert "I have the README; now verify author/license/tree" in visible
    assert h.actions[-1][1] == "repaired"
    assert "recovered=2" in h.actions[-1][2]

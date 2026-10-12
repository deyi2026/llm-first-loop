"""Host-local wall-clock contract."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from llm_loop.core.session import SessionStore
from llm_loop.event_log.store import EventStore
from llm_loop.introspection.goal import GoalStore
from llm_loop.runtime.service_control import _local_now
from llm_loop.timekeeping import system_local_now, system_local_now_iso


def _assert_host_local(value: str) -> None:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == datetime.now().astimezone().utcoffset()


def test_system_local_clock_is_aware_and_matches_host_offset() -> None:
    now = system_local_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == datetime.now().astimezone().utcoffset()
    _assert_host_local(system_local_now_iso())


def test_core_persisted_records_use_host_local_offset(tmp_path) -> None:
    sessions = SessionStore(tmp_path / "sessions")
    sid = sessions.create()
    session = sessions.load(sid)
    _assert_host_local(session.created_at)
    _assert_host_local(session.updated_at)

    events = EventStore(tmp_path / "event_logs")
    event = events.append(sid, "test.local_time", {"ok": True})
    _assert_host_local(event.ts)

    goals = GoalStore(tmp_path / "audit")
    goal = goals.create("local time contract")
    _assert_host_local(goal.created_at)
    _assert_host_local(goal.updated_at)


def test_service_control_wall_clock_uses_host_local_offset() -> None:
    _assert_host_local(_local_now())


def test_source_does_not_serialize_new_wall_clock_in_utc() -> None:
    """New LFL-owned wall-clock records must use the host-local authority."""
    root = Path(__file__).resolve().parents[2] / "src" / "llm_loop"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "datetime.now(UTC)" in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == []

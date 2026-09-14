from __future__ import annotations

import gc
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from llm_loop.event_log.store import EventStore


def test_read_cached_reuses_parsed_snapshot_until_event_changes(tmp_path, monkeypatch) -> None:
    store = EventStore(tmp_path / "events", enabled=True)
    sid = "session-cache"
    store.append(sid, "message.appended", {"index": 0})

    original_read = store.read
    calls = 0

    def counted_read(session_id: str):
        nonlocal calls
        calls += 1
        return original_read(session_id)

    monkeypatch.setattr(store, "read", counted_read)

    assert [event.seq for event in store.read_cached(sid)] == [1]
    assert [event.seq for event in store.read_cached(sid)] == [1]
    assert calls == 1


def test_same_store_append_extends_hot_cache_without_full_replay(tmp_path, monkeypatch) -> None:
    store = EventStore(tmp_path / "events", enabled=True)
    sid = "session-cache-append"
    store.append(sid, "message.appended", {"index": 0})
    assert [event.seq for event in store.read_cached(sid)] == [1]

    def no_full_replay(_session_id: str):
        raise AssertionError("same-process append should extend the hot cache mechanically")

    monkeypatch.setattr(store, "read", no_full_replay)
    store.append(sid, "request.meta", {"round": 1})
    assert [event.seq for event in store.read_cached(sid)] == [1, 2]


def test_cross_process_style_append_invalidates_by_last_seq(tmp_path) -> None:
    root = tmp_path / "events"
    reader = EventStore(root, enabled=True)
    writer = EventStore(root, enabled=True)
    sid = "session-cache-cross-process"

    writer.append(sid, "message.appended", {"index": 0})
    assert [event.seq for event in reader.read_cached(sid)] == [1]

    writer.append(sid, "request.meta", {"round": 1})
    assert [event.seq for event in reader.read_cached(sid)] == [1, 2]


def test_delete_session_invalidates_hot_cache(tmp_path) -> None:
    store = EventStore(tmp_path / "events", enabled=True)
    sid = "session-cache-delete"
    store.append(sid, "message.appended", {"index": 0})
    assert store.read_cached(sid)
    store._note_rotate_checked(sid, time.monotonic())  # noqa: SLF001

    store.delete_session(sid)
    assert sid not in store._read_cache  # noqa: SLF001
    assert sid not in store._rotate_checked_at  # noqa: SLF001
    assert store.read_cached(sid) == []


def test_concurrent_cold_read_cached_is_single_flight(tmp_path, monkeypatch) -> None:
    store = EventStore(tmp_path / "events", enabled=True)
    sid = "session-cache-singleflight"
    for index in range(8):
        store.append(sid, "message.appended", {"index": index})

    original_read = store.read
    calls = 0
    calls_lock = threading.Lock()

    def slow_read(session_id: str):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.03)
        return original_read(session_id)

    monkeypatch.setattr(store, "read", slow_read)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: len(store.read_cached(sid)), range(8)))

    assert results == [8] * 8
    assert calls == 1


def test_read_cache_build_lock_table_plateaus_across_many_sessions(tmp_path) -> None:
    """P4: per-session single-flight locks are ephemeral, not an all-session index."""
    store = EventStore(tmp_path / "events", enabled=True)

    for i in range(100):
        assert store.read_cached(f"session-{i:04d}") == []

    gc.collect()
    assert len(store._read_cache) <= store._read_cache_max_sessions  # noqa: SLF001
    assert len(store._read_cache_build_locks) <= store._read_cache_max_sessions  # noqa: SLF001


def test_rotate_throttle_metadata_plateaus_across_many_sessions(tmp_path) -> None:
    """P4: per-session rotate timestamps are bounded performance hints, not durable truth."""

    class _RotateManager:
        def check_and_rotate(self, session_id: str) -> None:  # noqa: ARG002
            return None

    store = EventStore(tmp_path / "events", enabled=True)
    store._rotate_checked_at_max_sessions = 8  # noqa: SLF001 - deterministic small gate
    store.set_rotate_manager(_RotateManager())

    for i in range(64):
        store.check_rotate(f"session-{i:04d}")

    assert len(store._rotate_checked_at) <= 8  # noqa: SLF001

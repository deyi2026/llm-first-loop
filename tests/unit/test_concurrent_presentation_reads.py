"""Overlapping presentation reads share work without retaining stale results."""
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event

import pytest

from llm_loop.core import read_coalescing
from llm_loop.core.read_coalescing import ConcurrentRead
from llm_loop.core.session import SessionStore
from llm_loop.introspection import lane_board


def _exercise_overlap(monkeypatch, invoke, patch_target, patch_name, result):
    entered = Event()
    joined = Event()
    release = Event()
    calls = []

    class TrackedFuture(Future):
        def result(self, timeout=None):
            joined.set()
            return super().result(timeout)

    def compute(*args, **kwargs):
        calls.append((args, kwargs))
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(read_coalescing, "Future", TrackedFuture)
    monkeypatch.setattr(patch_target, patch_name, compute)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(invoke)
        try:
            assert entered.wait(5)
            second = pool.submit(invoke)
            assert joined.wait(5)
        finally:
            release.set()
        assert first.result(5) == result
        assert second.result(5) == result
    assert len(calls) == 1
    assert invoke() == result
    assert len(calls) == 2


def test_board_coalesces_only_overlapping_reads(monkeypatch, tmp_path):
    _exercise_overlap(
        monkeypatch, lambda: lane_board.build_board(tmp_path, workspace_root=str(tmp_path)),
        lane_board, "_build_board", {"lanes": [], "degraded": []},
    )


def test_display_session_scan_coalesces_only_overlapping_reads(monkeypatch, tmp_path):
    store = SessionStore(tmp_path)
    _exercise_overlap(
        monkeypatch, lambda: store.list_sessions(display_only=True),
        store, "_list_sessions_in", [],
    )


def test_scope_and_error_do_not_poison_next_read():
    reads: ConcurrentRead[str] = ConcurrentRead()

    def fail():
        assert reads.read("other", lambda: "other") == "other"
        raise ValueError("test")

    with pytest.raises(ValueError, match="test"):
        reads.read("first", fail)
    assert reads.read("first", lambda: "recovered") == "recovered"

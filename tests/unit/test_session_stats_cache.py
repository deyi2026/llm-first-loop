"""SessionStatsProjection: bounded scalar stats cache for the 60s stats poll.

Pinned behaviours (P0 CPU fix 2026-11-26):
- fingerprint hit -> zero event reads (the whole point)
- fingerprint move -> exactly one recompute, single-flight under concurrency
- LRU bound (never a parsed-event cache; entries are KB-scale scalars)
- correctness pinned against the uncached reference aggregation
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

from llm_loop.web.session_stats_cache import SessionStatsProjection


class _FakeStore:
    enabled = True

    def __init__(self) -> None:
        self.seq = 0
        self.stamp: tuple[Any, ...] = ("seg", 1, 100)
        self.events: list[Any] = []
        self.read_calls = 0

    def last_seq(self, session_id: str) -> int:
        return self.seq

    def history_source_stamp(self, session_id: str) -> tuple[Any, ...]:
        return self.stamp

    def read(self, session_id: str) -> list[Any]:
        self.read_calls += 1
        return list(self.events)


def _engine(store: _FakeStore) -> Any:
    return SimpleNamespace(
        session=SimpleNamespace(_event_store=store, exists=lambda s: True,
                                history_revision=lambda s: (store.last_seq(s), store.history_source_stamp(s)))
    )


def _usage_event(i: int, model: str = "m1") -> SimpleNamespace:
    return SimpleNamespace(
        type="request.usage",
        payload={
            "model": model,
            "tokens_in": 10 + i,
            "tokens_out": 5 + i,
            "cache_hit": 4,
            "llm_ms": 100.0,
            "tool_ms": 10.0,
            "ttft_ms": 20.0,
        },
    )


def _recompute_from_store(store: _FakeStore) -> dict[str, Any]:
    """Reference aggregation: streaming scalars, list never retained."""
    events = store.read("s1")
    tokens_in = tokens_out = cache_hit = 0
    for e in events:
        if e.type != "request.usage":
            continue
        tokens_in += e.payload["tokens_in"]
        tokens_out += e.payload["tokens_out"]
        cache_hit += e.payload["cache_hit"]
    return {"tokens_in": tokens_in, "tokens_out": tokens_out, "cache_hit": cache_hit}


def test_fingerprint_hit_makes_zero_reads() -> None:
    store = _FakeStore()
    store.events = [_usage_event(0), _usage_event(1)]
    proj = SessionStatsProjection()
    eng = _engine(store)

    first = proj.compute_and_store(eng, "s1", lambda: _recompute_from_store(store))
    reads_after_first = store.read_calls
    second = proj.get_valid(eng, "s1")

    assert second == first == {"tokens_in": 21, "tokens_out": 11, "cache_hit": 8}
    assert store.read_calls == reads_after_first, "fingerprint hit must not re-read"


def test_fingerprint_move_triggers_single_recompute() -> None:
    store = _FakeStore()
    store.events = [_usage_event(0)]
    proj = SessionStatsProjection()
    eng = _engine(store)
    proj.compute_and_store(eng, "s1", lambda: _recompute_from_store(store))

    store.events.append(_usage_event(1))
    store.seq += 1
    assert proj.get_valid(eng, "s1") is None
    fresh = proj.compute_and_store(eng, "s1", lambda: _recompute_from_store(store))
    assert fresh["tokens_in"] == 21


def test_singleflight_concurrent_recompute_runs_once() -> None:
    store = _FakeStore()
    store.events = [_usage_event(0)]
    proj = SessionStatsProjection()
    eng = _engine(store)
    calls = {"n": 0}
    guard = threading.Lock()

    def slow() -> dict[str, Any]:
        with guard:
            calls["n"] += 1
        time.sleep(0.08)
        return _recompute_from_store(store)

    threads = [
        threading.Thread(target=lambda: proj.compute_and_store(eng, "s1", slow))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls["n"] == 1, calls


def test_lru_bound() -> None:
    proj = SessionStatsProjection(max_sessions=4)
    eng = _engine(_FakeStore())
    for i in range(6):
        proj.compute_and_store(eng, f"s{i}", lambda: {"ok": True})
    assert len(proj) == 4
    with proj._lock:
        assert "s0" not in proj._entries and "s5" in proj._entries


def test_unreadable_source_never_cached() -> None:
    store = _FakeStore()

    def boom(sid: str) -> tuple[Any, ...]:
        raise OSError("disk")

    store.history_source_stamp = boom  # type: ignore[assignment]
    proj = SessionStatsProjection()
    eng = _engine(store)
    assert proj.get_valid(eng, "s1") is None
    assert proj.compute_and_store(eng, "s1", lambda: {"ok": True}) == {"ok": True}
    assert len(proj) == 0


def test_cached_results_are_independent_of_response_decoration() -> None:
    proj = SessionStatsProjection()
    eng = _engine(_FakeStore())
    result = proj.compute_and_store(eng, "s1", lambda: {"by_model": {"a": {"tokens_in": 1}}})
    result["agent_comparison"] = {"child": "x"}
    result["by_model"]["a"]["tokens_in"] = 99
    fresh = proj.get_valid(eng, "s1")
    assert fresh == {"by_model": {"a": {"tokens_in": 1}}}
    fresh["by_model"]["a"]["tokens_in"] = 88
    assert proj.get_valid(eng, "s1")["by_model"]["a"]["tokens_in"] == 1


def test_source_change_during_compute_is_not_cached() -> None:
    store = _FakeStore()
    eng = _engine(store)
    proj = SessionStatsProjection()

    def changing() -> dict[str, Any]:
        store.seq += 1
        return {"turns": 1}

    assert proj.compute_and_store(eng, "s1", changing) == {"turns": 1}
    assert len(proj) == 0


def test_build_locks_do_not_accumulate() -> None:
    proj = SessionStatsProjection(max_sessions=2)
    eng = _engine(_FakeStore())
    for i in range(20):
        proj.compute_and_store(eng, str(i), lambda: {"turns": 1})
    assert len(proj) == 2
    assert len(proj._build_locks) == 0


def test_child_parentage_carried_in_projection_and_checked() -> None:
    """Parentage is authorization-adjacent: a cached entry from another parent
    must 404-equivalent (mismatch), never serve stats across parents."""
    store = _FakeStore()
    store.events = [_usage_event(0)]
    proj = SessionStatsProjection()
    eng = _engine(store)
    # Child c2 belongs to parent s2; parent s1 asks for it.
    proj.compute_and_store(
        eng, "c2", lambda: {**_recompute_from_store(store), "_parent_id": "s2"}
    )
    hit = proj.get_valid(eng, "c2")
    assert hit is not None, "fingerprint unchanged -> cache hit"
    assert hit.get("_parent_id") == "s2"
    # Endpoint semantics: parent s1 must reject (404-equivalent mismatch).
    assert hit.get("_parent_id") != "s1"
    # Parent s2 serves fine after popping the private key.
    served = dict(hit)
    served.pop("_parent_id", None)
    assert "_parent_id" not in served and served["tokens_in"] == 10


def test_hit_copy_mutation_never_touches_cache_entry() -> None:
    """Endpoint strips _parent_id on its own copy; the cache keeps serving it."""
    store = _FakeStore()
    store.events = [_usage_event(0)]
    proj = SessionStatsProjection()
    eng = _engine(store)
    proj.compute_and_store(
        eng, "s1", lambda: {**_recompute_from_store(store), "_parent_id": "p0"}
    )
    first = proj.get_valid(eng, "s1")
    assert first is not None and first["_parent_id"] == "p0"
    first.pop("_parent_id")  # endpoint strip on its own deep copy
    second = proj.get_valid(eng, "s1")
    assert second is not None and second.get("_parent_id") == "p0", (
        "cache entry must be unaffected by response mutation"
    )

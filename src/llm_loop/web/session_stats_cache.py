"""Bounded, per-engine scalar projection for Web session statistics.

The source revision includes the transcript and event log. Cached results
are isolated from response decoration and never used for execution decisions.
"""
from __future__ import annotations

import threading
import weakref
from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from typing import Any

_MAX_SESSIONS = 256


class SessionStatsProjection:
    """Cache only stable scalar snapshots, sharing overlapping cold reads."""

    def __init__(self, *, max_sessions: int = _MAX_SESSIONS) -> None:
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, tuple[Any, dict[str, Any]]] = OrderedDict()
        self._max = max(1, int(max_sessions))
        self._build_locks: weakref.WeakValueDictionary[str, threading.Lock] = (
            weakref.WeakValueDictionary()
        )

    @staticmethod
    def fingerprint(engine: Any, session_id: str) -> Any | None:
        """Use the existing body-free, workspace-aware history revision."""
        try:
            return engine.session.history_revision(session_id)
        except Exception:  # noqa: BLE001 - no reliable revision, no cache
            return None

    def _build_lock(self, session_id: str) -> threading.Lock:
        with self._lock:
            lock = self._build_locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._build_locks[session_id] = lock
            return lock

    def _lookup(self, session_id: str, fp: Any) -> dict[str, Any] | None:
        with self._lock:
            entry = self._entries.get(session_id)
            if entry is not None and entry[0] == fp:
                self._entries.move_to_end(session_id)
                return deepcopy(entry[1])
        return None

    def get_valid(self, engine: Any, session_id: str) -> dict[str, Any] | None:
        fp = self.fingerprint(engine, session_id)
        return None if fp is None else self._lookup(session_id, fp)

    def compute_and_store(
        self, engine: Any, session_id: str, recompute: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        fp = self.fingerprint(engine, session_id)
        if fp is None:
            return recompute()
        hit = self._lookup(session_id, fp)
        if hit is not None:
            return hit
        with self._build_lock(session_id):
            fp = self.fingerprint(engine, session_id)
            if fp is None:
                return recompute()
            hit = self._lookup(session_id, fp)
            if hit is not None:
                return hit
            stats = recompute()
            # A source change during the read cannot certify a cache entry.
            if self.fingerprint(engine, session_id) == fp:
                with self._lock:
                    self._entries[session_id] = (fp, deepcopy(stats))
                    self._entries.move_to_end(session_id)
                    while len(self._entries) > self._max:
                        self._entries.popitem(last=False)
            return stats

    def invalidate(self, session_id: str) -> None:
        with self._lock:
            self._entries.pop(session_id, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_PROJECTIONS_LOCK = threading.Lock()


def projection_for_engine(engine: Any) -> SessionStatsProjection:
    """Tie projection lifetime to its engine; no process-wide engine-id registry."""
    with _PROJECTIONS_LOCK:
        projection = getattr(engine, "_web_session_stats_projection", None)
        if projection is None:
            projection = SessionStatsProjection()
            engine._web_session_stats_projection = projection
        return projection


def continuity_projection_for_engine(engine: Any) -> SessionStatsProjection:
    """Separate bounded continuity cache of scalars and mechanical identities/states."""
    with _PROJECTIONS_LOCK:
        projection = getattr(engine, "_web_session_continuity_projection", None)
        if projection is None:
            projection = SessionStatsProjection(max_sessions=32)
            engine._web_session_continuity_projection = projection
        return projection

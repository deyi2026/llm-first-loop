"""Small, revision-keyed projections of selected events for Web display.

Sealed event segments are reused even when an active segment grows. Only
matching events are decoded/retained; canonical event files remain untouched.
"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from collections.abc import Callable

from llm_loop.event_log.model import Event

_TYPES = frozenset({
    "request.usage", "provider.transport.opened",
    "provider.transport.settled", "provider.transport.orphaned",
})
_Stamp = tuple[int, int, int, int, int]
_Entry = tuple[_Stamp, int, tuple[Event, ...]]


def _stamp(st: os.stat_result) -> _Stamp:
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


class SegmentEventProjection:
    """Bounded segment cache; caller verifies the whole source layout."""

    _types: frozenset[str] = frozenset()
    _markers: tuple[str, ...] = ()

    def __init__(self, max_segments: int = 128, max_bytes: int = 2 * 1024 * 1024) -> None:
        self._cache: OrderedDict[tuple[str, str], _Entry] = OrderedDict()
        self._lock = threading.Lock()
        self._max_segments = max_segments
        self._max_bytes = max_bytes
        self._bytes = 0

    @classmethod
    def includes(cls, event_type: str) -> bool:
        return event_type in cls._types

    @classmethod
    def accepts(cls, event: Event) -> bool:
        return cls.includes(event.type)

    def invalidate(self, session_id: str) -> None:
        with self._lock:
            for key in list(self._cache):
                if key[0] == session_id:
                    self._bytes -= self._cache.pop(key)[1]

    def read(
        self, session_id: str, paths: list[str], parse: Callable[[str], Event | None],
    ) -> list[Event]:
        result: list[Event] = []
        for path in paths:
            result.extend(self._segment(session_id, path, parse))
        return sorted(result, key=lambda event: event.seq)

    def _segment(
        self, session_id: str, path: str, parse: Callable[[str], Event | None],
    ) -> tuple[Event, ...]:
        key = (session_id, path)
        before = _stamp(os.stat(path))
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None and entry[0] == before:
                self._cache.move_to_end(key)
                return entry[2]
        events, retained = self._scan(path, before, parse)
        with self._lock:
            previous = self._cache.pop(key, None)
            if previous is not None:
                self._bytes -= previous[1]
            if retained <= self._max_bytes:
                self._cache[key] = (before, retained, events)
                self._bytes += retained
                while len(self._cache) > self._max_segments or self._bytes > self._max_bytes:
                    self._bytes -= self._cache.popitem(last=False)[1][1]
        return events

    @classmethod
    def _scan(
        cls, path: str, before: _Stamp, parse: Callable[[str], Event | None],
    ) -> tuple[tuple[Event, ...], int]:
        events: list[Event] = []
        retained = 0
        with open(path, encoding="utf-8") as source:
            if _stamp(os.fstat(source.fileno())) != before:
                raise OSError("projection source changed before read")
            for raw in source:
                # ASCII event types may be literal or Unicode-escaped in valid JSON.
                # False positives are parsed and discarded; no matching event is lost.
                if "\\u" not in raw and not any(marker in raw for marker in cls._markers):
                    continue
                event = parse(raw.strip())
                if event is not None and cls.accepts(event):
                    events.append(event)
                    retained += len(raw.encode("utf-8"))
            if _stamp(os.fstat(source.fileno())) != before:
                raise OSError("projection source changed during read")
        return tuple(events), retained


class UsageEventProjection(SegmentEventProjection):
    """Accounting-only Web display projection."""

    _types = _TYPES
    _markers = tuple(sorted(_TYPES))


class SettlementEventProjection(SegmentEventProjection):
    """Only parent subagent_result receipts and WAL commits, for display."""

    _types = frozenset({"message.appended", "tool.execution.receipt_committed"})
    _markers = ("subagent_result",)

    @classmethod
    def accepts(cls, event: Event) -> bool:
        return (cls.includes(event.type) and isinstance(event.payload, dict)
                and event.payload.get("tool_name") == "subagent_result")

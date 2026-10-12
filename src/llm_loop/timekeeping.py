"""Host-local wall-clock helpers.

LFL records human-facing/persisted wall-clock facts in the timezone configured on the
host OS.  Provider/proxy/network timestamps are source facts only and must never become
the clock used for LFL's own created_at/updated_at/ts fields.

Durations, deadlines, leases and TTL arithmetic may continue to use monotonic clocks or
epoch seconds; those are timezone-neutral and are intentionally outside this module.
"""

from __future__ import annotations

from datetime import datetime


def system_local_now() -> datetime:
    """Return the host process' current local wall clock as an aware datetime.

    ``datetime.now().astimezone()`` obtains the local timezone from the host runtime;
    no HTTP/provider/proxy response participates in this value.
    """

    return datetime.now().astimezone()


def system_local_now_iso(*, timespec: str = "microseconds") -> str:
    """Return an ISO-8601 host-local timestamp including its UTC offset."""

    return system_local_now().isoformat(timespec=timespec)

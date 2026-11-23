"""Bounded, read-only context observation for local llama.cpp-compatible endpoints.

A model registry describes an *upper bound*, not the live KV/slot capacity.  Only
an exact loopback OpenAI endpoint is eligible for this probe; cloud/remote models
are never queried.  Missing, contradictory, or stale runtime facts must not be
promoted into an unverified large context budget.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

_MAX_PROBE_BYTES = 65536
_PROBE_TIMEOUT_S = 0.6
_LIVE_TTL_S = 30.0
_UNKNOWN_TTL_S = 3.0


@dataclass(frozen=True, slots=True)
class LocalContextObservation:
    kind: str  # not_local | live | unavailable
    limit: int | None = None
    reason: str = ""


def _loopback_origin(base_url: str) -> str | None:
    """Canonicalize only literal loopback origins, never a user-supplied host."""
    try:
        parts = urlsplit(base_url)
        if (
            parts.scheme != "http"
            or parts.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or parts.path.rstrip("/") != "/v1"
            or parts.port is None
        ):
            return None
        host = "[::1]" if parts.hostname == "::1" else "127.0.0.1"
        return f"http://{host}:{parts.port}"
    except (ValueError, TypeError):
        return None


def _fetch_local_json(url: str, timeout_s: float) -> Any:
    """Read only local facts: no proxies, redirects, credentials, or generation."""
    with (
        httpx.Client(timeout=timeout_s, trust_env=False, follow_redirects=False) as client,
        client.stream("GET", url, headers={"accept": "application/json"}) as response,
    ):
        if response.status_code != 200:
            raise ValueError("runtime observation unavailable")
        chunks = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > _MAX_PROBE_BYTES:
                raise ValueError("runtime observation too large")
            chunks.append(chunk)
        return json.loads(b"".join(chunks))


def _positive_int(value: Any) -> int | None:
    return value if type(value) is int and 0 < value <= 2**31 - 1 else None


def _read_live_window(
    origin: str,
    model_id: str,
    fetch_json: Callable[[str, float], Any],
) -> LocalContextObservation:
    try:
        props = fetch_json(f"{origin}/props", _PROBE_TIMEOUT_S)
        if not isinstance(props, dict):
            return LocalContextObservation("unavailable", reason="props_invalid")
        if props.get("model_alias") != model_id or props.get("is_sleeping") is True:
            return LocalContextObservation("unavailable", reason="model_identity_unverified")
        defaults = props.get("default_generation_settings")
        total_slots = _positive_int(props.get("total_slots"))
        props_ctx = _positive_int(defaults.get("n_ctx")) if isinstance(defaults, dict) else None
        if total_slots is None or props_ctx is None:
            return LocalContextObservation("unavailable", reason="props_context_unverified")
        slots = fetch_json(f"{origin}/slots", _PROBE_TIMEOUT_S)
        if not isinstance(slots, list) or len(slots) != total_slots:
            return LocalContextObservation("unavailable", reason="slots_unverified")
        seen_ids: set[int] = set()
        contexts = [props_ctx]
        for slot in slots:
            if not isinstance(slot, dict):
                return LocalContextObservation("unavailable", reason="slot_invalid")
            slot_id = slot.get("id")
            slot_ctx = _positive_int(slot.get("n_ctx"))
            if type(slot_id) is not int or slot_id in seen_ids or slot_ctx is None:
                return LocalContextObservation("unavailable", reason="slot_invalid")
            seen_ids.add(slot_id)
            contexts.append(slot_ctx)
        return LocalContextObservation("live", limit=min(contexts))
    except Exception:  # noqa: BLE001 - any uncertain observation must fail closed
        return LocalContextObservation("unavailable", reason="probe_failed")


class LocalContextWindowObserver:
    """Small TTL cache shared by all rounds of one engine, keyed by exact model."""

    def __init__(
        self,
        *,
        fetch_json: Callable[[str, float], Any] = _fetch_local_json,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch_json = fetch_json
        self._clock = clock
        self._lock = threading.RLock()
        self._cache: dict[tuple[str, str], tuple[float, LocalContextObservation]] = {}

    def invalidate(self) -> None:
        """Re-observe at the next run boundary after any runtime restart."""
        with self._lock:
            self._cache.clear()

    def observe(self, base_url: str, model_id: str) -> LocalContextObservation:
        origin = _loopback_origin(str(base_url or ""))
        if origin is None:
            return LocalContextObservation("not_local")
        if not isinstance(model_id, str) or not model_id.strip():
            return LocalContextObservation("unavailable", reason="model_id_unknown")
        key = (origin, model_id)
        with self._lock:
            now = self._clock()
            cached = self._cache.get(key)
            if cached is not None:
                ttl = _LIVE_TTL_S if cached[1].kind == "live" else _UNKNOWN_TTL_S
                if cached[0] <= now < cached[0] + ttl:
                    return cached[1]
            observed = _read_live_window(origin, model_id, self._fetch_json)
            self._cache[key] = (now, observed)
            return observed

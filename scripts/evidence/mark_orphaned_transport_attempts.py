"""P0-3 GAP-DUR-1: durable orphaned transport-attempt reconciliation.

Decision: docs/DESIGN-20261002-p0-3-strict-durability-decision.md (frozen 2026-10-02).
Attribution: docs/DESIGN-20261002-multisegment-fork-inheritance-attribution.md (frozen 2026-10-02).

Mechanical, idempotent, one-time-history sweep:
1. scan `provider.transport.opened` attempts that never received a
   `provider.transport.settled` **in any scanned session** (settle-anywhere
   guard: session-fork physically copies events preserving ts/payload, so a
   forked replica of an attempt whose settle lives in another session must
   not be marked);
2. multi-segment session directories require `--include-multi-segment`;
   within them, fork replicas (opened events with `seq < session.forked
   marker seq`) are skipped and counted as `replicas_skipped` — only native
   occurrences are marked;
3. append a `provider.transport.orphaned` event to the SAME session carrying
   only durable mechanical facts (call/attempt/provider/model ids, opened_at,
   orphaned_at, mechanical_fact) — outcome stays unknown, nothing is fabricated;
4. re-running marks nothing new (existing orphaned events short-circuit).

The script performs zero provider/model calls and zero source-tool executions.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from llm_loop.event_log.store import EventStore  # noqa: E402

TRANSPORT_OPENED = "provider.transport.opened"
TRANSPORT_SETTLED = "provider.transport.settled"
TRANSPORT_ORPHANED = "provider.transport.orphaned"
SESSION_FORKED = "session.forked"


@dataclass(frozen=True)
class _SessionScan:
    session_id: str
    opened: tuple[tuple[int, dict[str, Any]], ...]
    settled_ids: frozenset[str]
    orphaned_ids: frozenset[str]
    fork_marker_seq: int  # seq of first session.forked marker; 0 = no marker


def _iter_session_ids(store: EventStore, *, include_multi_segment: bool = False) -> list[str]:
    directory = store._dir  # same layout knowledge the store itself owns
    sessions: list[str] = []
    for entry in sorted(directory.iterdir()):
        if entry.suffix == ".jsonl" and entry.is_file():
            sessions.append(entry.stem)
        elif include_multi_segment and entry.is_dir() and any(entry.glob("*.jsonl")):
            sessions.append(entry.name)
    return sessions


def _scan_session(store: EventStore, session_id: str) -> _SessionScan:
    opened: list[tuple[int, dict[str, Any]]] = []
    settled: set[str] = set()
    orphaned: set[str] = set()
    fork_marker_seq = 0
    for event in store.read(session_id):
        event_type = str(event.type or "")
        if event_type not in (TRANSPORT_OPENED, TRANSPORT_SETTLED, TRANSPORT_ORPHANED, SESSION_FORKED):
            continue
        payload = event.payload if isinstance(event.payload, dict) else {}
        if event_type == SESSION_FORKED:
            if not fork_marker_seq:
                try:
                    fork_marker_seq = int(event.seq or 0)
                except (TypeError, ValueError):
                    fork_marker_seq = 0
            continue
        attempt_id = str(payload.get("attempt_id") or "")
        if not attempt_id:
            continue
        if event_type == TRANSPORT_OPENED:
            try:
                seq = int(event.seq or 0)
            except (TypeError, ValueError):
                seq = 0
            opened.append((seq, dict(payload)))
        elif event_type == TRANSPORT_SETTLED:
            settled.add(attempt_id)
        else:
            orphaned.add(attempt_id)
    return _SessionScan(
        session_id, tuple(opened), frozenset(settled), frozenset(orphaned), fork_marker_seq
    )


def mark_orphaned_attempts(
    store: EventStore,
    *,
    dry_run: bool = False,
    now: float | None = None,
    include_multi_segment: bool = False,
) -> dict[str, int]:
    """Mark opened-without-settled transport attempts; idempotent.

    Default marking scope matches the frozen P0-3 measurement basis
    (single-file sessions only); the settle-anywhere index is nevertheless
    built over ALL sessions (both layers) because a settle observed in any
    session — including a fork replica — is a stronger fact than per-session
    absence and can only prevent false marks, never create one.
    Fork-replica skipping per the attribution mini-design requires
    `--include-multi-segment`.
    """

    stamped_at = float(time.time() if now is None else now)
    # Phase 1 — global indexes over every session on disk (read-only).
    all_scans: dict[str, _SessionScan] = {}
    settled_anywhere: set[str] = set()
    orphaned_anywhere: set[str] = set()
    for session_id in _iter_session_ids(store, include_multi_segment=True):
        scan = _scan_session(store, session_id)
        all_scans[session_id] = scan
        settled_anywhere |= scan.settled_ids
        orphaned_anywhere |= scan.orphaned_ids
    # Phase 2 — mark native settle-nowhere occurrences within the scan scope.
    summary = {
        "scanned_sessions": 0,
        "opened_total": 0,
        "candidates": 0,
        "already_orphaned": 0,
        "replicas_skipped": 0,
        "marked": 0,
    }
    for session_id in _iter_session_ids(store, include_multi_segment=include_multi_segment):
        scan = all_scans[session_id]
        summary["scanned_sessions"] += 1
        summary["opened_total"] += len(scan.opened)
        for seq, payload in scan.opened:
            attempt_id = str(payload.get("attempt_id") or "")
            if not attempt_id or attempt_id in settled_anywhere:
                continue
            if scan.fork_marker_seq and seq < scan.fork_marker_seq:
                summary["replicas_skipped"] += 1
                continue
            if attempt_id in orphaned_anywhere:
                summary["already_orphaned"] += 1
                continue
            summary["candidates"] += 1
            if dry_run:
                continue
            event = {
                "call_id": str(payload.get("call_id") or ""),
                "attempt_id": attempt_id,
                "provider_id": str(payload.get("provider_id") or ""),
                "model_id": str(payload.get("model_id") or ""),
                "opened_at": float(payload.get("started_at") or 0.0),
                "orphaned_at": stamped_at,
                "mechanical_fact": "opened_without_settled",
            }
            if store.append(session_id, TRANSPORT_ORPHANED, event) is None:
                continue
            orphaned_anywhere.add(attempt_id)
            summary["marked"] += 1
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-logs-dir", default="data/event_logs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--include-multi-segment",
        action="store_true",
        help="also scan multi-segment session directories; fork replicas are "
        "skipped per the 2026-10-02 attribution mini-design "
        "(docs/DESIGN-20261002-multisegment-fork-inheritance-attribution.md)",
    )
    args = parser.parse_args(argv)
    store = EventStore(Path(args.event_logs_dir))
    summary = mark_orphaned_attempts(
        store,
        dry_run=args.dry_run,
        include_multi_segment=args.include_multi_segment,
    )
    for key, value in summary.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

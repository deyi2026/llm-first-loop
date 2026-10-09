"""Explicit session-scoped event projection with exact recovery and currentness."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from llm_loop.event_log.model import Event, parse_event_line
from llm_loop.event_log.store import EventStore
from llm_loop.knowledge.digest_receipts import (
    event_ref,
    observation,
    payload_sha256,
    transport_pairs,
)

_SCHEMA = "session-digest/v1"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _integer(value: Any, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"expected integer >= {minimum}")
    return value


@dataclass(frozen=True)
class SessionDigest:
    body: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        body = copy.deepcopy(self.body)
        return {**body, "digest_ref": "session-digest:" + hashlib.sha256(_json(body).encode()).hexdigest()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionDigest:
        if not isinstance(data, dict) or data.get("schema") != _SCHEMA:
            raise ValueError("invalid digest schema")
        body = {k: v for k, v in data.items() if k != "digest_ref"}
        digest = cls(copy.deepcopy(body))
        if digest.to_dict() != data:
            raise ValueError("digest fingerprint mismatch; rebuild from canonical events")
        sid = body.get("session_id")
        rows = body.get("events")
        if not isinstance(sid, str) or not sid or not isinstance(rows, list):
            raise ValueError("invalid digest scope/events")
        for row in rows:
            if (
                not isinstance(row, dict) or not isinstance(row.get("event_ref"), str)
                or not row["event_ref"].startswith(f"event:{sid}:")
                or not isinstance(row.get("event_sha256"), str)
                or not re.fullmatch("[0-9a-f]{64}", row["event_sha256"])
            ):
                raise ValueError("invalid digest event ref/SHA")
            _integer(row.get("seq"), 1)
        return digest

    def page(self, *, start: int = 0, limit: int = 20) -> dict[str, Any]:
        start, limit = _integer(start), _integer(limit, 1)
        rows = self.body["events"]
        end = min(start + limit, len(rows))
        return {"digest_ref": self.to_dict()["digest_ref"], "session_id": self.body["session_id"],
                "view_current": "not_checked", "events": copy.deepcopy(rows[start:end]),
                "start": start, "total": len(rows), "next_start": end if end < len(rows) else None}

    def render_markdown(self) -> str:
        data = self.to_dict()
        header = {k: v for k, v in data.items() if k != "events"}
        lines = ["# Session digest", "", "Cached projection; currentness requires canonical hydration.",
                 "Statements, completion, delivery and adoption do not establish task benefit.",
                 "", "```json", json.dumps(header, ensure_ascii=False, indent=2), "```", ""]
        for row in data["events"]:
            lines.extend(["## " + row["event_ref"], "",
                          "```json", json.dumps(row, ensure_ascii=False, indent=2), "```", ""])
        return "\n".join(lines)


@dataclass(frozen=True)
class _RawEvent:
    event: Event
    raw: bytes


@dataclass(frozen=True)
class _Snapshot:
    events: tuple[_RawEvent, ...]
    files: list[dict[str, Any]]
    sha256: str


class SessionDigestReader:
    """The caller explicitly binds one authorized session; cached paths grant no access."""

    def __init__(self, store: EventStore, session_id: str) -> None:
        self._store = store
        self.session_id = session_id

    def _capture(self) -> _Snapshot:
        captures = self._store.read_source_files(self.session_id)
        if not captures:
            raise ValueError("canonical session source unavailable")
        if captures != self._store.read_source_files(self.session_id):
            raise ValueError("canonical source changed during capture; retry explicitly")
        files, rows = [], []
        ids: set[str] = set()
        previous_seq = None
        for name, payload in captures:
            if payload and not payload.endswith(b"\n"):
                raise ValueError("unterminated canonical event source")
            files.append({"ref": name, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)})
            for raw in payload.splitlines(keepends=True):
                if not raw.strip():
                    continue
                text = raw.decode("utf-8")
                parsed = json.loads(text)
                event = parse_event_line(text)
                if event is None or not isinstance(parsed.get("payload"), dict) or isinstance(event.seq, bool):
                    raise ValueError("invalid canonical event row")
                if event.session_id != self.session_id:
                    raise ValueError("canonical event is outside session scope")
                if event.event_id in ids or (previous_seq is not None and event.seq != previous_seq + 1):
                    raise ValueError("duplicate event identity or event sequence gap")
                ids.add(event.event_id)
                previous_seq = event.seq
                rows.append(_RawEvent(event, raw))
        if not rows:
            raise ValueError("canonical session events unavailable")
        return _Snapshot(tuple(rows), files, hashlib.sha256(_json(files).encode()).hexdigest())

    def build(
        self, *, start_seq: int = 1, end_seq: int | None = None, preview_chars: int = 240,
    ) -> SessionDigest:
        start_seq, preview_chars = _integer(start_seq, 1), _integer(preview_chars, 1)
        snap = self._capture()
        first, last = snap.events[0].event.seq, snap.events[-1].event.seq
        end_seq = last if end_seq is None else _integer(end_seq, start_seq)
        if start_seq > last or end_seq > last:
            raise ValueError("requested event range unavailable")
        selected = [r for r in snap.events if start_seq <= r.event.seq <= end_seq]
        if not selected:
            raise ValueError("requested event range unavailable")
        events = [r.event for r in selected]
        knowledge = [e for e in events if e.type.startswith("knowledge.")]
        observations = {
            "knowledge": [observation(e) for e in knowledge],
            "declarations": [observation(e) for e in knowledge if e.type in {
                "knowledge.method_declaration", "knowledge.experience_declaration",
            }],
            "outcomes": [observation(e) for e in knowledge if e.type == "knowledge.run_outcome"],
            "writes": [observation(e) for e in knowledge if e.type == "knowledge.learning_saved"],
            "statements": [{"event_ref": event_ref(e), "verification": "not_evaluated"}
                           for e in events if e.type == "message.appended"],
        }
        body = {
            "schema": _SCHEMA, "session_id": self.session_id, "scope": "session",
            "source_snapshot_sha256": snap.sha256, "source_files": snap.files,
            "snapshot_complete": True, "source_complete": first == 1, "session_complete": "unknown",
            "coverage": {"requested_start_seq": start_seq, "start_seq": selected[0].event.seq,
                         "end_seq": end_seq, "available_start_seq": first, "available_end_seq": last},
            "next_seq": end_seq + 1, "events": [self._row(r, preview_chars) for r in selected],
            "observations": observations, "transport": transport_pairs(events),
            "task_success": "not_evaluated", "task_benefit": "not_evaluated",
            "semantic_summary": "not_generated",
        }
        return SessionDigest(body)

    @staticmethod
    def _row(raw: _RawEvent, preview_chars: int) -> dict[str, Any]:
        e = raw.event
        payload = _json(e.payload)
        end = min(preview_chars, len(payload))
        return {
            "event_ref": event_ref(e), "event_id": e.event_id, "seq": e.seq,
            "type": e.type, "ts": e.ts, "run_ref": e.payload.get("run_ref"),
            "event_sha256": hashlib.sha256(raw.raw).hexdigest(),
            "payload_sha256": payload_sha256(e.payload),
            "preview": payload[:end], "preview_complete": end == len(payload),
            "coverage": {"field": "canonical_payload_json", "start": 0, "end": end,
                         "total": len(payload), "unit": "unicode_characters"},
            "authority": "recorded_event; content claims not independently verified",
        }

    def hydrate(
        self, digest: SessionDigest, ref: str, *, start: int = 0, max_chars: int = 4000,
        expected_event_sha256: str | None = None,
    ) -> dict[str, Any]:
        start, max_chars = _integer(start), _integer(max_chars, 1)
        if digest.body["session_id"] != self.session_id:
            raise ValueError("digest is outside the explicitly bound session scope")
        row = next((r for r in digest.body["events"] if r["event_ref"] == ref), None)
        if row is None:
            raise ValueError("event ref is outside digest coverage")
        if start and not expected_event_sha256:
            raise ValueError("continuation requires expected_event_sha256")
        snap = self._capture()
        current = next((r for r in snap.events if event_ref(r.event) == ref and r.event.seq == row["seq"]), None)
        result: dict[str, Any] = {
            "event_ref": ref, "state": "unavailable", "text": "", "next_start": None,
            "event_sha256": None, "projection_complete": False,
            "view_current": snap.sha256 == digest.body["source_snapshot_sha256"],
        }
        if current is None:
            return result
        sha = hashlib.sha256(current.raw).hexdigest()
        result["event_sha256"] = sha
        if sha != row["event_sha256"] or (expected_event_sha256 is not None and sha != expected_event_sha256):
            result.update(state="source_changed", detail="rebuild from current canonical events")
            return result
        text = current.raw.decode("utf-8")
        if start > len(text):
            raise ValueError("event offset exceeds source length")
        end = min(start + max_chars, len(text))
        result.update(
            state="current" if result["view_current"] else "stale_view",
            text=text[start:end], start=start, end=end, total_chars=len(text),
            offset_unit="unicode_characters", snapshot_complete=True,
            projection_complete=start == 0 and end == len(text),
            next_start=end if end < len(text) else None,
        )
        return result

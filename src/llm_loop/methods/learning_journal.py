"""Durable append-only learning journal (JSONL event stream).

Design (Learning Plane, DESIGN-20260910):

- One episode produces at most one learning job, ever: job ids are
  deterministic (``learning_job_id``) and terminal states block re-enqueue.
- The journal is an event log, not a mutable state document. Each transition
  appends one JSON line; the current state is the fold of all events, so a
  crash mid-job loses nothing that was already appended.
- Post-crash reconcile is mechanical: a job stuck in ``started`` either
  already produced a candidate (``candidate_lookup``, e.g. MethodStore
  records whose ``evidence_refs`` contain ``learning:{job_id}``) -> saved;
  or it gets requeued until ``max_attempts``, then failed.
- Corrupt/partial lines are skipped, orphan events (no queued) are ignored.
- Program proves identity and lineage here; it never judges method quality.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_TERMINAL_STATES = frozenset({"saved", "none", "failed", "cancelled"})
_REPLAYABLE_STATES = frozenset({"queued", "admitted", "started", "requeued", "failed"})


def learning_job_id(source_episode_ref: str) -> str:
    """Deterministic job id per episode ref: same episode -> same job, ever."""
    digest = hashlib.sha256(source_episode_ref.encode("utf-8")).hexdigest()[:12]
    return f"learn:{digest}"


@dataclass
class LearningJob:
    job_id: str
    source_episode_ref: str
    session_id: str = ""
    source_model: str = ""
    trigger_facts: dict[str, Any] = field(default_factory=dict)
    state: str = "queued"
    reason: str = ""
    attempt: int = 0
    candidate_ref: str = ""
    created_at: float = field(default_factory=time.time)

    @property
    def method_ref(self) -> str:  # backward-compatible alias
        return self.candidate_ref

    @property
    def runnable(self) -> bool:
        return self.state in ("queued", "admitted", "started", "requeued")


def _truncate(text: str, limit: int = 300) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit]


class LearningJournal:
    """Append-only JSONL journal with fold-on-read state machine.

    Thread-safe within the process (mutex) and across processes (flock on the
    journal file while reading the full fold or appending an event).
    """

    def __init__(
        self,
        path: str | Path,
        *,
        max_attempts: int = 3,
        candidate_lookup: Callable[[str], str | None] | None = None,
    ) -> None:
        self._path = Path(path)
        self._max_attempts = max(1, int(max_attempts))
        self._candidate_lookup = candidate_lookup or (lambda _job_id: None)
        self._lock = threading.Lock()

    # ---------- event log primitives ----------

    def _append_event(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, (line + "\n").encode("utf-8"))
            os.fsync(fd)
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _read_events(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        events: list[dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_SH)
            try:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        evt = json.loads(raw)
                    except (ValueError, TypeError):
                        continue  # torn/partial write line: skip, keep the rest
                    if isinstance(evt, dict) and evt.get("event") and evt.get("job_id"):
                        events.append(evt)
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
        return events

    def _fold(self) -> dict[str, LearningJob]:
        jobs: dict[str, LearningJob] = {}
        for evt in self._read_events():
            job_id = str(evt["job_id"])
            kind = str(evt["event"])
            job = jobs.get(job_id)
            if job is None:
                if kind != "queued":
                    continue  # orphan event without a queued record: ignore
                job = LearningJob(
                    job_id=job_id,
                    source_episode_ref=str(evt.get("source_episode_ref", "")),
                    session_id=str(evt.get("session_id", "")),
                    source_model=str(evt.get("source_model", "")),
                    trigger_facts=dict(evt.get("trigger_facts") or {}),
                    created_at=float(evt.get("ts") or 0.0),
                )
                jobs[job_id] = job
                continue
            if kind == "started":
                job.state = "started"
                job.attempt += 1
            elif kind == "admitted":
                job.state = "admitted"
            elif kind == "requeued":
                job.state = "queued"  # requeued folds back to queued
            elif kind == "saved":
                job.state = "saved"
                job.candidate_ref = str(evt.get("candidate_ref", ""))
                job.reason = ""
            elif kind == "none":
                job.state = "none"
                job.reason = _truncate(evt.get("reason", ""))
            elif kind == "failed":
                job.state = "failed"
                job.reason = _truncate(evt.get("reason", ""))
            elif kind == "cancelled":
                job.state = "cancelled"
                job.reason = _truncate(evt.get("reason", ""))
        return jobs

    def _snapshot(self) -> dict[str, LearningJob]:
        with self._lock:
            return self._fold()

    # ---------- enqueue / query ----------

    def enqueue(
        self,
        source_episode_ref: str,
        *,
        session_id: str,
        source_model: str = "",
        trigger_facts: dict[str, Any] | None = None,
    ) -> LearningJob | None:
        """Idempotent enqueue; returns None once the episode reached terminal."""
        if not source_episode_ref:
            return None
        job_id = learning_job_id(source_episode_ref)
        with self._lock:
            jobs = self._fold()
            existing = jobs.get(job_id)
            if existing is not None:
                if existing.state in _TERMINAL_STATES:
                    return None  # one episode, one learning lifecycle, ever
                return existing
            self._append_event(
                {
                    "event": "queued",
                    "job_id": job_id,
                    "ts": time.time(),
                    "source_episode_ref": source_episode_ref,
                    "session_id": session_id,
                    "source_model": source_model,
                    "trigger_facts": dict(trigger_facts or {}),
                }
            )
            return LearningJob(
                job_id=job_id,
                source_episode_ref=source_episode_ref,
                session_id=session_id,
                source_model=source_model,
                trigger_facts=dict(trigger_facts or {}),
            )

    # legacy alias used by method_learning.py post_run hook
    def append(
        self,
        *,
        session_id: str,
        source_episode_ref: str,
        source_model: str,
        trigger_facts: dict[str, Any] | None = None,
    ) -> LearningJob | None:
        return self.enqueue(
            source_episode_ref,
            session_id=session_id,
            source_model=source_model,
            trigger_facts=trigger_facts,
        )

    def job(self, job_id: str) -> LearningJob | None:
        return self._snapshot().get(job_id)

    def job_for_episode(self, source_episode_ref: str) -> LearningJob | None:
        return self._snapshot().get(learning_job_id(source_episode_ref))

    def episode_has_candidate(self, source_episode_ref: str) -> bool:
        job = self.job_for_episode(source_episode_ref)
        return bool(job) and job.state == "saved" and bool(job.candidate_ref)

    def runnable_jobs(self, max_n: int = 5) -> list[LearningJob]:
        """Jobs eligible to (re)run: non-terminal; failed retries below max."""
        jobs = self._snapshot()
        out = [
            job
            for job in jobs.values()
            if (job.runnable or (job.state == "failed" and job.attempt < self._max_attempts))
        ]
        out.sort(key=lambda j: j.created_at)
        return out[:max_n]

    # ---------- transitions (append-only) ----------

    def _mark(self, job_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            jobs = self._fold()
            if job_id not in jobs:
                return
            payload.update({"job_id": job_id, "ts": time.time()})
            self._append_event(payload)

    def mark_admitted(self, job_id: str) -> None:
        self._mark(job_id, {"event": "admitted"})

    def mark_started(self, job_id: str) -> None:
        self._mark(job_id, {"event": "started"})

    def mark_requeued(self, job_id: str, reason: str = "") -> None:
        self._mark(job_id, {"event": "requeued", "reason": _truncate(reason, 120)})

    def mark_saved(self, job_id: str, candidate_ref: str) -> None:
        self._mark(job_id, {"event": "saved", "candidate_ref": str(candidate_ref or "")})

    def mark_none(self, job_id: str, reason: str) -> None:
        self._mark(job_id, {"event": "none", "reason": _truncate(reason)})

    def mark_failed(self, job_id: str, reason: str) -> None:
        self._mark(job_id, {"event": "failed", "reason": _truncate(reason)})

    def cancel(self, job_id: str, reason: str = "") -> None:
        self._mark(job_id, {"event": "cancelled", "reason": _truncate(reason, 120)})

    # ---------- post-crash reconcile ----------

    def reconcile(self) -> list[str]:
        """Mechanical reconcile of jobs interrupted mid-run.

        - ``started`` + candidate already exists (lookup)  -> saved(reconciled)
        - ``started`` + no candidate + attempts left       -> requeued
        - ``started`` + no candidate + attempts exhausted  -> failed(reconciled)
        Returns human-readable change notes; never touches terminal jobs.
        """
        changed: list[str] = []
        for job in self._snapshot().values():
            if job.state != "started":
                continue
            found = None
            try:
                found = self._candidate_lookup(job.job_id)
            except Exception:  # noqa: BLE001 - lookup is best-effort
                found = None
            if found:
                self.mark_saved(job.job_id, str(found))
                changed.append(f"{job.job_id}:saved(reconciled)")
            elif job.attempt >= self._max_attempts:
                self.mark_failed(job.job_id, "attempts_exhausted")
                changed.append(f"{job.job_id}:failed(reconciled)")
            else:
                self.mark_requeued(job.job_id, "crash_recovered")
                changed.append(f"{job.job_id}:requeued")
        return changed

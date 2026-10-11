"""P0 fake-remote effect window probe. No external network or production tools."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from llm_loop.assurance.task_control_store import (
    AuthorityUnreadableError,
    RevisionConflictError,
    _check_id,
    _check_sha,
)


@dataclass(frozen=True)
class AttemptRecord:
    attempt_id: str
    operation_id: str
    action_sha256: str
    state: str


class OfflineEffectJournal:
    """A WAL 'started' is NOT proof remote execution did or didn't occur."""

    def __init__(self, data_dir: Path | str) -> None:
        root = Path(data_dir)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "effect_attempts.sqlite3"
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL,
                    action_sha256 TEXT NOT NULL, state TEXT NOT NULL)"""
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=8)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def start(self, attempt_id: str, operation_id: str, action_sha256: str) -> AttemptRecord:
        _check_id(attempt_id)
        _check_id(operation_id)
        _check_sha(action_sha256)
        with self._connect() as db:
            old = db.execute(
                "SELECT attempt_id,operation_id,action_sha256,state FROM attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if old:
                if old[1] != operation_id or old[2] != action_sha256:
                    raise RevisionConflictError("effect idempotency conflict")
                return AttemptRecord(*old)
            db.execute(
                "INSERT INTO attempts VALUES (?,?,?,'STARTED')",
                (attempt_id, operation_id, action_sha256),
            )
            return AttemptRecord(attempt_id, operation_id, action_sha256, "STARTED")

    def read(self, attempt_id: str) -> AttemptRecord:
        with self._connect() as db:
            row = db.execute(
                "SELECT attempt_id,operation_id,action_sha256,state FROM attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise AuthorityUnreadableError("attempt missing")
            return AttemptRecord(*row)

    def reconcile(self, attempt_id: str, remote_observer: Callable[[str, str], bool | None]) -> str:
        old = self.read(attempt_id)
        if old.state == "RECONCILED":
            return "RECONCILED"
        try:
            observed = remote_observer(old.operation_id, old.action_sha256)
        except Exception:  # noqa: BLE001 - authority can't be inferred from remote errors
            observed = None
        if observed is not True:
            # Even a missing row or 404 does not prove non-execution unless the
            # specific remote contract guarantees that property.
            return "OUTCOME_UNKNOWN"
        with self._connect() as db:
            db.execute(
                "UPDATE attempts SET state='RECONCILED' WHERE attempt_id=? AND state='STARTED'",
                (attempt_id,),
            )
        return "RECONCILED"


class FakeRemote:
    """Independent durable fake platform, with a physical dispatch counter."""

    def __init__(self, root: Path | str) -> None:
        self.path = Path(root) / "fake_remote.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS operations "
                "(operation_id TEXT PRIMARY KEY, action_sha TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS attempts "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, operation_id TEXT NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=8)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def dispatch(self, operation_id: str, action_sha256: str) -> None:
        with self._connect() as db:
            existing = db.execute(
                "SELECT action_sha FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if existing and existing[0] != action_sha256:
                raise RevisionConflictError("remote operation id reused with different action")
            db.execute("INSERT INTO attempts(operation_id) VALUES (?)", (operation_id,))
            if not existing:
                db.execute(
                    "INSERT INTO operations VALUES (?,?)",
                    (operation_id, action_sha256),
                )

    def observe(self, operation_id: str, action_sha256: str) -> bool | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT action_sha FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if row is None:
                return None  # absence does NOT prove NOT_APPLIED
            if row[0] != action_sha256:
                return None
            return True

    def dispatch_count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0])

    def applied_count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM operations").fetchone()[0])

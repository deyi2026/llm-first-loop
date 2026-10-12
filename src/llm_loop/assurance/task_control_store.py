"""Minimal durable Task control CAS; P0 offline prototype, not a runtime authority.

Only user-authenticated orchestration may supply owner/grant fields. This class does
not confer a Fleet lease or a physical tool capability.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = "lfl.dual_assurance.task_control/v1"
_SHA = re.compile(r"^[a-f0-9]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")
_COMMANDS = {"STOP", "PAUSE", "STEER", "RESUME"}
_STOP_SCOPES = {"RUN_EXACT", "TASK_STICKY"}


class AuthorityError(RuntimeError):
    """A P0 control authority refuses an action; callers must not fail open."""


class AuthorityUnreadableError(AuthorityError):
    pass


class PermissionDeniedError(AuthorityError):
    pass


class RevisionConflictError(AuthorityError):
    pass


class InvalidContractError(AuthorityError):
    pass


@dataclass(frozen=True)
class LeaseRef:
    run_key: str
    lease_id: str
    generation: int
    worker_id: str
    run_generation: str

    def __post_init__(self) -> None:
        for field in ("run_key", "lease_id", "worker_id", "run_generation"):
            _check_id(getattr(self, field))
        if type(self.generation) is not int or self.generation < 1:
            raise InvalidContractError("Fleet lease generation must be positive integer")


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    owner: str
    objective_sha256: str
    acceptance_sha256: str
    grant_ref: str
    revision: int
    control_epoch: int
    state: str
    active_binding: LeaseRef | None
    prepared_binding: LeaseRef | None


@dataclass(frozen=True)
class IntentReceipt:
    intent_seq: int
    revision: int
    control_epoch: int
    state: str
    replayed: bool = False


def _check_id(v: object) -> str:
    if not isinstance(v, str) or not _ID.fullmatch(v):
        raise InvalidContractError("invalid opaque id")
    return v


def _check_sha(v: object) -> str:
    if not isinstance(v, str) or not _SHA.fullmatch(v):
        raise InvalidContractError("expected lowercase SHA256 hex")
    return v


def _encode_lease(ref: LeaseRef | None) -> str | None:
    if ref is None:
        return None
    return json.dumps(
        {"generation": ref.generation, "lease_id": ref.lease_id,
         "run_key": ref.run_key, "worker_id": ref.worker_id,
         "run_generation": ref.run_generation},
        sort_keys=True, separators=(",", ":"),
    )


def _decode_lease(raw: str | None) -> LeaseRef | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {
            "generation", "lease_id", "run_key", "worker_id", "run_generation"
        }:
            raise ValueError("unexpected binding fields")
        return LeaseRef(**data)
    except (TypeError, ValueError) as exc:
        raise AuthorityUnreadableError("stored Fleet reference invalid") from exc


class TaskControlStore:
    """SQLite WAL + FULL synchronous minimal CAS, backed by independent DB.

    A successful STOP transaction commits both state and control_epoch. No
    production Runner, ToolRegistry or ReleaseBroker consumes this prototype.
    """

    def __init__(self, data_dir: str | Path) -> None:
        base = Path(data_dir)
        if base.is_symlink():
            raise InvalidContractError("store root symlink denied")
        base.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(base, 0o700)
        self.db_path = base / "task_control.sqlite3"
        if self.db_path.is_symlink():
            raise InvalidContractError("store file symlink denied")
        existed_nonempty = self.db_path.exists() and self.db_path.stat().st_size > 0
        try:
            with closing(self._open()) as db:
                version = int(db.execute("PRAGMA user_version").fetchone()[0])
                if (version == 0 and existed_nonempty) or version not in (0, 1):
                    raise AuthorityUnreadableError("unrecognized stored schema")
                if version == 0:
                    db.executescript(
                        """
                        CREATE TABLE meta (schema_name TEXT NOT NULL);
                        INSERT INTO meta VALUES ('lfl.dual_assurance.task_control/v1');
                        CREATE TABLE tasks (
                            task_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                            objective_sha TEXT NOT NULL, acceptance_sha TEXT NOT NULL,
                            grant_ref TEXT NOT NULL, revision INTEGER NOT NULL,
                            control_epoch INTEGER NOT NULL, state TEXT NOT NULL,
                            active_binding TEXT, prepared_binding TEXT
                        );
                        CREATE TABLE intents (
                            seq INTEGER PRIMARY KEY AUTOINCREMENT,
                            task_id TEXT NOT NULL, idem_key TEXT NOT NULL,
                            canonical_hash TEXT NOT NULL, revision INTEGER NOT NULL,
                            control_epoch INTEGER NOT NULL, state TEXT NOT NULL,
                            UNIQUE(task_id, idem_key)
                        );
                        PRAGMA user_version=1;
                        """
                    )
                self._verify_schema(db)
            os.chmod(self.db_path, 0o600)
        except sqlite3.DatabaseError as exc:
            raise AuthorityUnreadableError("corrupt or inaccessible task control store") from exc

    def _open(self) -> sqlite3.Connection:
        try:
            # Refuse to silently resurrect an invalid/replaced DB file through a
            # leftover SQLite -wal. Check the disk header *before* SQLite opens it.
            if self.db_path.is_symlink():
                raise AuthorityUnreadableError("store file symlink replaced")
            if self.db_path.exists():
                with self.db_path.open("rb") as f:
                    head = f.read(16)
                if head and head != b"SQLite format 3\x00":
                    raise AuthorityUnreadableError("store file header invalid; no WAL replay")
            elif Path(str(self.db_path) + "-wal").exists():
                raise AuthorityUnreadableError("store DB absent while WAL exists")
            db = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            return db
        except sqlite3.DatabaseError as exc:
            raise AuthorityUnreadableError("cannot open control authority") from exc

    @staticmethod
    def _verify_schema(db: sqlite3.Connection) -> None:
        try:
            name = db.execute("SELECT schema_name FROM meta").fetchone()[0]
            if name != SCHEMA_VERSION:
                raise AuthorityUnreadableError("unexpected schema version")
            for table in ("tasks", "intents"):
                if not db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name=? AND type='table'",
                    (table,),
                ).fetchone():
                    raise AuthorityUnreadableError("table missing")
            integrity = db.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise AuthorityUnreadableError("sqlite integrity check failed")
        except (sqlite3.DatabaseError, TypeError) as exc:
            raise AuthorityUnreadableError("invalid stored authority") from exc

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        db = self._open()
        try:
            db.execute("BEGIN IMMEDIATE")
            self._verify_schema(db)
            yield db
            db.commit()
        except sqlite3.DatabaseError as exc:
            db.rollback()
            raise AuthorityUnreadableError("task control transaction unavailable") from exc
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> TaskSnapshot:
        return TaskSnapshot(
            task_id=row["task_id"], owner=row["owner"],
            objective_sha256=_check_sha(row["objective_sha"]),
            acceptance_sha256=_check_sha(row["acceptance_sha"]),
            grant_ref=_check_id(row["grant_ref"]),
            revision=int(row["revision"]), control_epoch=int(row["control_epoch"]),
            state=row["state"], active_binding=_decode_lease(row["active_binding"]),
            prepared_binding=_decode_lease(row["prepared_binding"]),
        )

    @staticmethod
    def _owner_row(db: sqlite3.Connection, task_id: str, owner: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise AuthorityError("task not found")
        if row["owner"] != owner:
            raise PermissionDeniedError("task owner mismatch")
        return row

    def read_exact(self, task_id: str, owner: str) -> TaskSnapshot:
        _check_id(task_id)
        _check_id(owner)
        try:
            with closing(self._open()) as db:
                self._verify_schema(db)
                return self._snapshot(self._owner_row(db, task_id, owner))
        except sqlite3.DatabaseError as exc:
            raise AuthorityUnreadableError("read failed") from exc

    def create_once(
        self, task_id: str, owner: str, objective_sha256: str,
        acceptance_sha256: str, grant_ref: str,
    ) -> TaskSnapshot:
        for arg in (task_id, owner, grant_ref):
            _check_id(arg)
        _check_sha(objective_sha256)
        _check_sha(acceptance_sha256)
        with self._tx() as db:
            existing = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if existing:
                snap = self._snapshot(self._owner_row(db, task_id, owner))
                if (snap.objective_sha256, snap.acceptance_sha256, snap.grant_ref) != (
                    objective_sha256, acceptance_sha256, grant_ref
                ):
                    raise RevisionConflictError("task create replay changed immutable source")
                return snap
            db.execute(
                """INSERT INTO tasks
                (task_id,owner,objective_sha,acceptance_sha,grant_ref,
                 revision,control_epoch,state)
                VALUES (?,?,?,?,?,0,0,'ACTIVE')""",
                (task_id, owner, objective_sha256, acceptance_sha256, grant_ref),
            )
            return self._snapshot(self._owner_row(db, task_id, owner))

    def append_intent_cas(
        self, task_id: str, owner: str, expected_revision: int,
        idem_key: str, command: str, payload_sha256: str,
        *, stop_scope: str = "TASK_STICKY", expected_run_generation: str = "",
        resume_authorized: bool = False,
    ) -> IntentReceipt:
        for arg in (task_id, owner, idem_key):
            _check_id(arg)
        _check_sha(payload_sha256)
        if command not in _COMMANDS or stop_scope not in _STOP_SCOPES:
            raise InvalidContractError("unknown command or stop scope")
        if type(expected_revision) is not int or expected_revision < 0:
            raise InvalidContractError("invalid expected revision")
        if command == "RESUME" and not resume_authorized:
            raise PermissionDeniedError("RESUME needs a distinct trusted human grant")
        canonical = json.dumps({
            "command": command, "expected_revision": expected_revision,
            "expected_run_generation": expected_run_generation, "scope": stop_scope,
            "payload_sha256": payload_sha256,
        }, sort_keys=True, separators=(",", ":"))
        signature = hashlib.sha256(canonical.encode()).hexdigest()
        with self._tx() as db:
            row = self._owner_row(db, task_id, owner)
            existing = db.execute(
                "SELECT * FROM intents WHERE task_id=? AND idem_key=?",
                (task_id, idem_key),
            ).fetchone()
            if existing:
                if existing["canonical_hash"] != signature:
                    raise RevisionConflictError("idempotency key reused for different command")
                return IntentReceipt(
                    existing["seq"], existing["revision"],
                    existing["control_epoch"], existing["state"], replayed=True,
                )
            if row["revision"] != expected_revision and not (
                command == "STOP" and stop_scope == "TASK_STICKY"
            ):
                raise RevisionConflictError("stale task revision")
            if row["state"] == "STOP_REQUESTED" and command not in {"STOP", "RESUME"}:
                raise PermissionDeniedError("durable STOP blocks new control work")
            binding = _decode_lease(row["active_binding"])
            if (
                command == "STOP"
                and stop_scope == "RUN_EXACT"
                and (not binding or expected_run_generation != binding.run_generation)
            ):
                raise RevisionConflictError("stale exact run identity")
            new_state = {
                "STOP": "STOP_REQUESTED", "PAUSE": "PAUSE_REQUESTED",
                "RESUME": "ACTIVE", "STEER": row["state"],
            }[command]
            if row["state"] == "STOP_REQUESTED" and command == "STOP":
                new_state = "STOP_REQUESTED"
            revision = row["revision"] + 1
            epoch = row["control_epoch"] + (1 if command in ("STOP", "RESUME") else 0)
            db.execute(
                """UPDATE tasks SET revision=?,control_epoch=?,state=?
                   WHERE task_id=?""",
                (revision, epoch, new_state, task_id),
            )
            cur = db.execute(
                """INSERT INTO intents
                   (task_id, idem_key, canonical_hash, revision, control_epoch, state)
                   VALUES(?,?,?,?,?,?)""",
                (task_id, idem_key, signature, revision, epoch, new_state),
            )
            seq = cur.lastrowid
            if seq is None:
                raise AuthorityUnreadableError("committed intent sequence unavailable")
            return IntentReceipt(seq, revision, epoch, new_state)

    def prepare_binding_cas(
        self, task_id: str, owner: str, expected_revision: int,
        fleet_lease: LeaseRef, verify_fleet_lease: Callable[[LeaseRef], bool],
    ) -> TaskSnapshot:
        if not isinstance(fleet_lease, LeaseRef):
            raise InvalidContractError("only observed Fleet lease refs can be prepared")
        with self._tx() as db:
            row = self._owner_row(db, task_id, owner)
            if row["revision"] != expected_revision:
                raise RevisionConflictError("stale prepare revision")
            if row["state"] != "ACTIVE" or not verify_fleet_lease(fleet_lease):
                raise PermissionDeniedError("control stopped or observed Fleet lease invalid")
            db.execute(
                """UPDATE tasks SET revision=revision+1, prepared_binding=?
                   WHERE task_id=?""",
                (_encode_lease(fleet_lease), task_id),
            )
            return self._snapshot(self._owner_row(db, task_id, owner))

    def commit_binding_cas(
        self, task_id: str, owner: str, expected_revision: int,
        fleet_lease: LeaseRef, verify_fleet_lease: Callable[[LeaseRef], bool],
    ) -> TaskSnapshot:
        with self._tx() as db:
            row = self._owner_row(db, task_id, owner)
            if row["revision"] != expected_revision:
                raise RevisionConflictError("stale bind revision")
            if row["state"] != "ACTIVE" or row["prepared_binding"] != _encode_lease(fleet_lease):
                raise PermissionDeniedError("binding not prepared or task no longer active")
            if not verify_fleet_lease(fleet_lease):
                raise PermissionDeniedError("Fleet lease no longer current")
            db.execute(
                """UPDATE tasks SET revision=revision+1,
                    prepared_binding=NULL,active_binding=? WHERE task_id=?""",
                (_encode_lease(fleet_lease), task_id),
            )
            return self._snapshot(self._owner_row(db, task_id, owner))

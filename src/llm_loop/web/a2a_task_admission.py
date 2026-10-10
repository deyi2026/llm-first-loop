"""Offline-only durable A2A Task admission CAS (no HTTP route or dispatch).

This store records an exact, immutable human ingress BEFORE any side effect.
It is deliberately separate from provider TaskBudget: reserving an A2A Task
is not model/tool permission and never grants a physical provider attempt.

Integration preconditions (NOT met by this module): a real Huawei A2A host
principal verified by an authoritative platform adapter, Web session/workspace
authorization, and a dispatch path that requires newly_reserved=True.
"""

from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import json
import os
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = "lfl-a2a-task-admission/v1"
MAX_INGRESS_BYTES = 128 * 1024
MAX_RECORD_BYTES = 256 * 1024
MAX_ID_CHARS = 256


class A2aAdmissionDeniedError(PermissionError):
    """Invalid caller/scope/input or access to a different principal."""


class A2aAdmissionConflictError(RuntimeError):
    """Task identifier reused for a different identity or request."""


class A2aAdmissionUnavailableError(RuntimeError):
    """Missing, corrupt or insecure authoritative record. Fail closed."""


class A2aAdmissionPersistError(OSError):
    """Storage failure before any acknowledged reservation."""


class A2aAdmissionCommitUncertainError(A2aAdmissionPersistError):
    """Mutation might be visible; never authorize dispatch by retrying."""

    retry_safe = False


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_ID_CHARS:
        raise A2aAdmissionDeniedError(f"invalid_{field}")
    if any(ord(char) < 32 for char in value):
        raise A2aAdmissionDeniedError(f"invalid_{field}")
    return value


def _durable_directory(directory: Path) -> None:
    try:
        # The approved LFL data root must pre-exist. Recursively creating
        # multiple parent dirs could silently skip their durability fences.
        if not directory.parent.is_dir() or directory.parent.is_symlink():
            raise A2aAdmissionUnavailableError("authoritative data root unavailable")
        directory.mkdir(mode=0o700, exist_ok=True)
        metadata = directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_mode & 0o077:
            raise A2aAdmissionUnavailableError("admission directory not private")
        _fsync_directory(directory.parent)
    except OSError as exc:
        raise A2aAdmissionUnavailableError("admission directory unavailable") from exc


def _fsync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@dataclass(frozen=True)
class A2aTaskIngress:
    task_id: str
    principal_id: str
    context_id: str
    client_session_id: str
    agent_id: str
    workspace_scope: str
    payload: bytes = field(repr=False)  # never leak original human content in repr/log

    def frozen(self) -> dict[str, str]:
        for name in (
            "task_id", "principal_id", "context_id", "client_session_id",
            "agent_id", "workspace_scope",
        ):
            _required(getattr(self, name), name)
        if not isinstance(self.payload, bytes) or not 0 < len(self.payload) <= MAX_INGRESS_BYTES:
            raise A2aAdmissionDeniedError("invalid_payload")
        return {
            "task_id": self.task_id,
            "principal_id": self.principal_id,
            "context_id": self.context_id,
            "client_session_id": self.client_session_id,
            "agent_id": self.agent_id,
            "workspace_scope": self.workspace_scope,
            "request_sha256": hashlib.sha256(self.payload).hexdigest(),
        }


@dataclass(frozen=True)
class A2aAdmissionReceipt:
    task_id: str
    principal_id: str
    request_sha256: str
    receipt_id: str
    newly_reserved: bool

    @property
    def durable_record_confirmed(self) -> bool:
        return True

    def as_arkts_contract(self) -> dict[str, str | bool]:
        """Exact, non-secret DTO consumed by the offline ArkTS shadow contract.

        The receiving A2A adapter must independently trust the backend
        transport; the DTO is not a bearer credential or signature.
        """
        return {
            "taskId": self.task_id,
            "principalId": self.principal_id,
            "requestSha256": self.request_sha256,
            "receiptId": self.receipt_id,
            "newlyReserved": self.newly_reserved,
            "durableRecordConfirmed": True,
        }


class A2aTaskAdmissionStore:
    """Persistent create-if-absent Task gate, scoped to a private data dir.

    This store has no API to dispatch, retry a human turn, delete reservations
    or silently reset corrupt state. Duplicate exact requests return an
    existing receipt with newly_reserved=False, including after process restart.
    """

    def __init__(self, data_directory: str | Path) -> None:
        self.directory = Path(data_directory).expanduser().absolute() / "a2a-task-admission"

    def _paths(self, task_id: str) -> tuple[Path, Path]:
        digest = hashlib.sha256(_required(task_id, "task_id").encode("utf-8")).hexdigest()
        return (
            self.directory / f"task-{digest}.json",
            self.directory / f"task-{digest}.lock",
        )

    @contextmanager
    def _locked(self, task_id: str) -> Iterator[Path]:
        _durable_directory(self.directory)
        path, lock_path = self._paths(task_id)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise A2aAdmissionUnavailableError("task lock unavailable") from exc
        with os.fdopen(fd, "rb") as lock:
            if stat.S_IMODE(os.fstat(lock.fileno()).st_mode) & 0o077:
                raise A2aAdmissionUnavailableError("insecure task lock")
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            except OSError as exc:
                raise A2aAdmissionUnavailableError("task lock unavailable") from exc
            try:
                yield path
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _read_record(path: Path, task_id: str) -> dict[str, str]:
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as source:
                metadata = os.fstat(source.fileno())
                if (not stat.S_ISREG(metadata.st_mode)
                        or stat.S_IMODE(metadata.st_mode) & 0o077
                        or metadata.st_nlink != 1):
                    raise ValueError("insecure task record")
                if metadata.st_size > MAX_RECORD_BYTES:
                    raise ValueError("oversized task record")
                raw = source.read(MAX_RECORD_BYTES + 1)
            row = json.loads(raw)
            fields = {
                "schema", "task_id", "principal_id", "context_id",
                "client_session_id", "agent_id", "workspace_scope",
                "request_sha256", "payload_b64",
            }
            if not isinstance(row, dict) or set(row) != fields or row["schema"] != SCHEMA:
                raise ValueError("invalid task schema")
            if row["task_id"] != task_id:
                raise ValueError("task id mismatch")
            for name in fields - {"schema", "payload_b64", "request_sha256"}:
                _required(row[name], name)
            if not isinstance(row["payload_b64"], str):
                raise ValueError("invalid payload encoding")
            content = base64.b64decode(row["payload_b64"], validate=True)
            if not 0 < len(content) <= MAX_INGRESS_BYTES:
                raise ValueError("invalid payload size")
            if hashlib.sha256(content).hexdigest() != row["request_sha256"]:
                raise ValueError("payload integrity mismatch")
            frozen = {
                name: row[name] for name in (
                    "task_id", "principal_id", "context_id",
                    "client_session_id", "agent_id", "workspace_scope",
                    "request_sha256",
                )
            }
            if raw != A2aTaskAdmissionStore._record_bytes(frozen, content):
                raise ValueError("noncanonical immutable task record")
            return row
        except (OSError, ValueError, KeyError, TypeError, binascii.Error) as exc:
            raise A2aAdmissionUnavailableError("task record unreadable or corrupt") from exc

    @staticmethod
    def _record_bytes(frozen: dict[str, str], payload: bytes) -> bytes:
        row = {
            "schema": SCHEMA,
            **frozen,
            "payload_b64": base64.b64encode(payload).decode("ascii"),
        }
        return (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

    def reserve(self, ingress: A2aTaskIngress) -> A2aAdmissionReceipt:
        frozen = ingress.frozen()
        expected_bytes = self._record_bytes(frozen, ingress.payload)
        with self._locked(ingress.task_id) as path:
            if os.path.lexists(path):
                old = self._read_record(path, ingress.task_id)
                if any(old.get(field) != value for field, value in frozen.items()):
                    raise A2aAdmissionConflictError("task identity or request changed")
                # Even an existing root may have been produced by an earlier
                # post-link fsync-uncertain attempt; fence before acknowledging
                # its durability. Still NEVER grant a second dispatch.
                try:
                    _fsync_directory(path.parent)
                except OSError as exc:
                    raise A2aAdmissionCommitUncertainError(
                        "existing task durability unconfirmed; no replay"
                    ) from exc
                return self._receipt(frozen, expected_bytes, newly_reserved=False)

            temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
            linked = False
            try:
                fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as target:
                    target.write(expected_bytes)
                    target.flush()
                    os.fsync(target.fileno())
                # Kernel-level no-overwrite CAS across processes.
                os.link(temp, path)
                linked = True
                temp.unlink()
                _fsync_directory(path.parent)
            except OSError as exc:
                if linked:
                    raise A2aAdmissionCommitUncertainError(
                        "post-link directory durability unknown; reconcile without dispatch"
                    ) from exc
                raise A2aAdmissionPersistError("task reservation not acknowledged") from exc
            finally:
                with suppress(OSError):
                    temp.unlink()
            return self._receipt(frozen, expected_bytes, newly_reserved=True)

    def hydrate(self, task_id: str, principal_id: str, workspace_scope: str) -> bytes:
        """Exact bytes for a separately authenticated and authorized caller."""
        _required(principal_id, "principal_id")
        _required(workspace_scope, "workspace_scope")
        with self._locked(task_id) as path:
            row = self._read_record(path, task_id)
            if row["principal_id"] != principal_id or row["workspace_scope"] != workspace_scope:
                raise A2aAdmissionDeniedError("task_not_accessible")
            return base64.b64decode(row["payload_b64"], validate=True)

    @staticmethod
    def _receipt(frozen: dict[str, str], expected: bytes, *, newly_reserved: bool) -> A2aAdmissionReceipt:
        return A2aAdmissionReceipt(
            task_id=frozen["task_id"],
            principal_id=frozen["principal_id"],
            request_sha256=frozen["request_sha256"],
            receipt_id=hashlib.sha256(expected).hexdigest(),
            newly_reserved=newly_reserved,
        )

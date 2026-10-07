"""Integrity-checked one-shot schedule delegation; never creates human authority.

The private ledger stores the authorized scope and consumption state, not an
IngressToken. Only a valid pending record can restore its delegated capability.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from llm_loop.core.trace_leak.ingress_token import (
    _WAKE_PROOF_PIN,
    IngressToken,
    VerifiedWakeAuthorization,
    is_whitelisted,
    restore_scheduled_ingress,
)


def _scope(entry: dict[str, Any]) -> str:
    fields = {
        key: entry.get(key)
        for key in (
            "sid", "session_id", "message", "created_at", "repeat_interval",
            "max_count", "goal_id", "goal_generation", "scheduled_trigger_at",
        )
    }
    fields["subject_refs"] = entry.get("subject_refs") or []
    # Store round-trips normalize numeric values (e.g. 0 -> 0.0).
    for name in ("created_at", "repeat_interval", "scheduled_trigger_at"):
        fields[name] = float(fields.get(name) or 0.0)
    fields["max_count"] = int(fields.get("max_count") or 1)
    return hashlib.sha256(
        json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class WakeAuthorizationStore:
    """Private durable authority and consumed/revoked tombstones for one store."""

    def __init__(self, schedule_path: Path) -> None:
        self._path = schedule_path.with_name(schedule_path.stem + "-wake-authority.json")
        self._key_path = self._path.with_suffix(".key")
        self._lock = threading.RLock()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            import fcntl

            fd = os.open(self._path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600)
            with os.fdopen(fd, "a") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _key(self, *, create: bool = False) -> bytes:
        if create:
            try:
                fd = os.open(self._key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(secrets.token_bytes(32))
                    handle.flush()
                    os.fsync(handle.fileno())
        info = self._key_path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("wake authority key must be a private regular file")
        value = self._key_path.read_bytes()
        if len(value) != 32:
            raise ValueError("wake authority key is invalid")
        return value

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        data = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("wake authority ledger is invalid")
        return data

    def _write(self, records: dict[str, Any]) -> None:
        temp = self._path.with_name(self._path.name + "." + secrets.token_hex(6) + ".tmp")
        try:
            fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(records, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self._path)
            directory_fd = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temp.unlink(missing_ok=True)

    def _sign(self, record: dict[str, Any], key: bytes) -> str:
        content = {name: value for name, value in record.items() if name != "signature"}
        wire = json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(key, wire, hashlib.sha256).hexdigest()

    def _valid(self, record: Any, entry: dict[str, Any], key: bytes) -> bool:
        return (
            isinstance(record, dict)
            and record.get("version") == 1
            and record.get("sid") == entry.get("sid")
            and record.get("scope") == _scope(entry)
            and hmac.compare_digest(str(record.get("signature") or ""), self._sign(record, key))
        )

    def issue(self, entry: dict[str, Any], grant: Any) -> bool:
        if not isinstance(grant, IngressToken) or not grant.delegated or not is_whitelisted(grant):
            return False  # legacy/test opaque grants remain strictly process-local
        if not entry.get("wake") or not entry.get("session_id") or entry.get("repeat_interval"):
            raise ValueError("durable wake must be a same-session one-shot delegation")
        with self._locked():
            key = self._key(create=True)
            records = self._read()
            sid = str(entry["sid"])
            existing = records.get(sid)
            if existing is not None and (
                not self._valid(existing, entry, key) or existing.get("state") != "pending"
            ):
                raise ValueError("consumed, revoked or altered wake cannot be reauthorized")
            record = {
                "version": 1, "sid": sid, "scope": _scope(entry),
                "channel": grant.channel, "entry": grant.entry,
                "nonce": secrets.token_hex(16), "state": "pending",
            }
            record["signature"] = self._sign(record, key)
            records[sid] = record
            self._write(records)
        return True

    def state(self, entry: dict[str, Any]) -> str:
        try:
            with self._locked():
                records = self._read()
                record = records.get(str(entry.get("sid") or ""))
                if record is None:
                    return "missing"
                if not self._valid(record, entry, self._key()):
                    return "invalid"
                return str(record.get("state") or "invalid")
        except (OSError, ValueError, TypeError):
            return "invalid"

    def recover(self, entry: dict[str, Any]) -> Any | None:
        try:
            with self._locked():
                record = self._read().get(str(entry.get("sid") or ""))
                if not isinstance(record, dict) or not self._valid(record, entry, self._key()) or record["state"] != "pending":
                    return None
                proof = VerifiedWakeAuthorization(_WAKE_PROOF_PIN, record["channel"], record["entry"])
            return restore_scheduled_ingress(proof)
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def consume(self, entry: dict[str, Any]) -> None:
        """Persist at-most-once admission before any delegated provider work."""
        with self._locked():
            records = self._read()
            sid = str(entry["sid"])
            record = records.get(sid)
            if record is None:
                return  # legacy in-memory delegation
            key = self._key()
            if not self._valid(record, entry, key) or record["state"] != "pending":
                raise ValueError("wake authority unavailable or already consumed")
            record["state"] = "started"
            record["signature"] = self._sign(record, key)
            self._write(records)

    def revoke(self, sid: str) -> None:
        with self._locked():
            records = self._read()
            record = records.get(sid)
            if record is None:
                return
            record["state"] = "revoked"
            record["signature"] = self._sign(record, self._key())
            self._write(records)

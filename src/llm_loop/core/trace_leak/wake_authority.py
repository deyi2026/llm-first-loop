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
import time
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

_STANDING_SCOPE_KEYS = (
    "task_mode", "wake_dispatch", "wake_fires_total", "wake_expires_at",
    "wake_external", "wake_workdir",
)

# Goal 级授权池（v1.1）：多条常驻条目可共享同一份额度。池成员资格是签名范围的一部分，
# 但只在显式设置时进入 scope，保证既有条目签名逐字不变。
_POOL_PREFIX = "pool:"


def _pool_key(pool_id: str) -> str:
    return _POOL_PREFIX + str(pool_id)


def _pool_spec(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "goal_id": str(entry.get("goal_id") or ""),
        "fires_total": int(entry.get("wake_fires_total") or 0),
        "expires_at": float(entry.get("wake_expires_at") or 0.0),
        "external": bool(entry.get("wake_external")),
        "workdir": str(entry.get("wake_workdir") or ""),
    }


def _standing(entry: dict[str, Any]) -> bool:
    """常驻授权：同一凭据跨多次触发复用，签名范围与一次性委派不同（设计 §5.2）。"""
    return str(entry.get("task_mode") or "") == "task_recurring"


def _scope(entry: dict[str, Any]) -> str:
    keys = [
        "sid", "session_id", "message", "created_at", "repeat_interval",
        "max_count", "goal_id", "goal_generation",
    ]
    # 周期条目的 scheduled_trigger_at 每个周期前移；纳入签名会让第二次起全部
    # invalid。常驻授权改签「创建期不变」的规格字段。
    if not _standing(entry):
        keys.append("scheduled_trigger_at")
    fields = {key: entry.get(key) for key in keys}
    if _standing(entry):
        fields.update({key: entry.get(key) for key in _STANDING_SCOPE_KEYS})
        fields["wake_fires_total"] = int(fields.get("wake_fires_total") or 0)
        fields["wake_expires_at"] = float(fields.get("wake_expires_at") or 0.0)
        fields["wake_external"] = bool(fields.get("wake_external"))
        # Store 会省略空字符串字段，scope 必须用同一归一形态，否则 "" ↔ None 会把
        # 合法授权误判为 invalid（升级/迁移路径最容易踩到）。
        fields["wake_dispatch"] = str(fields.get("wake_dispatch") or "")
        fields["wake_workdir"] = str(fields.get("wake_workdir") or "")
        pool = str(entry.get("wake_pool") or "")
        if pool:
            fields["wake_pool"] = pool
    fields["subject_refs"] = entry.get("subject_refs") or []
    # Store round-trips normalize numeric values (e.g. 0 -> 0.0).
    for name in ("created_at", "repeat_interval"):
        fields[name] = float(fields.get(name) or 0.0)
    if "scheduled_trigger_at" in fields:
        fields["scheduled_trigger_at"] = float(fields.get("scheduled_trigger_at") or 0.0)
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

    def _pool_valid(self, record: Any, key: bytes) -> bool:
        return (
            isinstance(record, dict)
            and record.get("version") == 1
            and record.get("kind") == "pool"
            and hmac.compare_digest(str(record.get("signature") or ""), self._sign(record, key))
        )

    def _ensure_pool(
        self, records: dict[str, Any], entry: dict[str, Any], key: bytes
    ) -> dict[str, Any]:
        """第一期条目开池，后续条目只能按同一规格加入（不允许静默加额）。

        池规格（次数/到期/外部副作用/工作目录/所属 goal）在开池时由真人签发，
        之后每个成员的 scope 都绑定同一个 pool_id，避免「加一条条目绕开额度」。
        """
        pool = str(entry.get("wake_pool") or "")
        spec = _pool_spec(entry)
        if not spec["goal_id"]:
            raise ValueError("wake pool requires a goal_id")
        if pool != spec["goal_id"]:
            # 池只能是 Goal 级：不接受「用 goal A 的条目挂到 goal B 的池」。
            raise ValueError("wake pool must equal goal_id")
        existing = records.get(_pool_key(pool))
        if existing is None:
            record = {
                "version": 1, "kind": "pool", "pool_id": pool, **spec,
                "fires_used": 0, "state": "pending",
            }
            record["signature"] = self._sign(record, key)
            records[_pool_key(pool)] = record
            return record
        if not self._pool_valid(existing, key):
            raise ValueError("wake pool ledger entry is invalid")
        if existing.get("state") != "pending":
            raise ValueError("wake pool is closed")
        if {name: existing.get(name) for name in spec} != spec:
            raise ValueError("wake pool spec mismatch")
        return existing

    def _pool_record(
        self, records: dict[str, Any], entry: dict[str, Any], key: bytes
    ) -> dict[str, Any] | None:
        pool = str(entry.get("wake_pool") or "")
        if not pool:
            return None
        record = records.get(_pool_key(pool))
        return record if self._pool_valid(record, key) else None

    def pool_facts(self, pool_id: str) -> dict[str, Any] | None:
        """池的只读投影（规格 + 用量 + 状态）；不存在/签名无效返回 None。"""
        try:
            with self._locked():
                record = self._read().get(_pool_key(pool_id))
                if not isinstance(record, dict) or not self._pool_valid(record, self._key()):
                    return None
                return {name: record.get(name) for name in (
                    "pool_id", "goal_id", "fires_total", "fires_used",
                    "expires_at", "external", "workdir", "state",
                )}
        except (OSError, ValueError, TypeError):
            return None

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
        standing = _standing(entry)
        if not entry.get("wake") or not entry.get("session_id"):
            raise ValueError("durable wake must be a same-session delegation")
        if entry.get("repeat_interval") and not standing:
            raise ValueError("periodic entries cannot carry a one-shot wake delegation")
        if standing and (
            float(entry.get("repeat_interval") or 0.0) <= 0
            or int(entry.get("wake_fires_total") or 0) < 1
        ):
            raise ValueError("standing delegation requires repeat_interval>0 and wake_fires_total>=1")
        with self._locked():
            key = self._key(create=True)
            records = self._read()
            sid = str(entry["sid"])
            existing = records.get(sid)
            if existing is not None and not self._valid(existing, entry, key):
                raise ValueError("altered wake cannot be reauthorized")
            if existing is not None and existing.get("state") != "pending":
                if standing:
                    return False  # 已终结的常驻授权不能靠重新 issue 复活额度
                raise ValueError("consumed or revoked wake cannot be reauthorized")
            pool = str(entry.get("wake_pool") or "")
            if pool:
                self._ensure_pool(records, entry, key)
            record = {
                "version": 1, "sid": sid, "scope": _scope(entry),
                "channel": grant.channel, "entry": grant.entry,
                "nonce": secrets.token_hex(16), "state": "pending",
                "standing": (
                    {
                        "fires_total": int(entry.get("wake_fires_total") or 0),
                        "expires_at": float(entry.get("wake_expires_at") or 0.0),
                        "external": bool(entry.get("wake_external")),
                    }
                    if standing
                    else None
                ),
                "pool": pool,
                "fires_used": (
                    int((records.get(_pool_key(pool)) or {}).get("fires_used") or 0)
                    if pool
                    else int((existing or {}).get("fires_used") or 0)
                ),
                "projection": self._projection(entry),
            }
            record["signature"] = self._sign(record, key)
            records[sid] = record
            self._write(records)
        return True

    @staticmethod
    def _projection(entry: dict[str, Any]) -> dict[str, Any]:
        # Pre-upgrade services rewrite the shared schedule using their old schema.
        # Keep new projection fields in the signed private ledger, never a second queue.
        return {name: entry.get(name) for name in (
            "scheduled_trigger_at", "wake_delivery_state", "wake_wait_reason",
        )}

    def restore_fields(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Restore only absent fields after verifying the original authorization scope."""
        if not self._path.exists():
            return entry
        try:
            with self._locked():
                record = self._read().get(str(entry.get("sid") or ""))
                if not isinstance(record, dict) or not isinstance(record.get("projection"), dict):
                    return entry
                restored = dict(entry)
                for name, value in record["projection"].items():
                    if name in self._projection(entry) and name not in restored:
                        restored[name] = value
                if self._valid(record, restored, self._key()):
                    return restored
        except (OSError, ValueError, TypeError, KeyError):
            pass
        return entry

    def preserve_fields(self, entries: list[dict[str, Any]]) -> None:
        """Keep signed UI/admission projections across older writers' schema round trips."""
        if not self._path.exists():
            return
        with self._locked():
            records = self._read()
            if not records:
                return
            key = self._key()
            changed = False
            for entry in entries:
                record = records.get(str(entry.get("sid") or ""))
                if not isinstance(record, dict) or not self._valid(record, entry, key):
                    continue
                projection = self._projection(entry)
                if record.get("projection") != projection:
                    record["projection"] = projection
                    record["signature"] = self._sign(record, key)
                    changed = True
            if changed:
                self._write(records)

    def state(self, entry: dict[str, Any]) -> str:
        try:
            with self._locked():
                records = self._read()
                record = records.get(str(entry.get("sid") or ""))
                if record is None:
                    return "missing"
                key = self._key()
                if not self._valid(record, entry, key):
                    return "invalid"
                state = str(record.get("state") or "invalid")
                if state == "pending" and str(entry.get("wake_pool") or ""):
                    pool = self._pool_record(records, entry, key)
                    if pool is None:
                        return "invalid"
                    pool_state = str(pool.get("state") or "invalid")
                    if pool_state != "pending":
                        return pool_state
                    pool_expires = float(pool.get("expires_at") or 0.0)
                    if pool_expires and time.time() >= pool_expires:
                        return "expired"
                    if int(pool.get("fires_used") or 0) >= int(pool.get("fires_total") or 0):
                        return "consumed"
                if state == "pending" and record.get("standing"):
                    spec = record.get("standing") or {}
                    expires_at = float(spec.get("expires_at") or 0.0)
                    if expires_at and time.time() >= expires_at:
                        return "expired"
                    if int(record.get("fires_used") or 0) >= int(spec.get("fires_total") or 0):
                        return "consumed"
                return state
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

    def consume(self, entry: dict[str, Any], *, occurrence: int | None = None) -> int:
        """Persist admission before any delegated provider work.

        Returns fires consumed so far (``1`` for one-shot delegations).  A standing
        delegation keeps ``pending`` until its quota is reached, so later fires can
        reuse the same signed record; the terminal transition happens in
        :meth:`revoke` after ``mark_triggered``.

        ``occurrence`` makes the call idempotent for one fire: if the process dies
        after the ledger write but before ``mark_triggered``, the retry for the same
        occurrence returns the recorded count instead of spending a second credit
        (review P2-4).
        """
        with self._locked():
            records = self._read()
            sid = str(entry["sid"])
            record = records.get(sid)
            if record is None:
                return 1  # legacy in-memory delegation
            key = self._key()
            if not self._valid(record, entry, key) or record["state"] != "pending":
                raise ValueError("wake authority unavailable or already consumed")
            spec = record.get("standing")
            # 幂等重试必须先于「池已关闭/过期」检查：同一次到点的重试应拿回已记账结果，
            # 而不是因为最后一次消费把池关掉就变成报错。
            if occurrence is not None and int(record.get("last_occurrence") or 0) == int(occurrence):
                return int(record.get("fires_used") or 0)
            if spec and record.get("pool"):
                pool = self._pool_record(records, entry, key)
                if pool is None:
                    raise ValueError("wake pool is unavailable")
                if pool.get("state") != "pending":
                    raise ValueError("wake pool is closed")
                expires_at = float(pool.get("expires_at") or 0.0)
                if expires_at and time.time() >= expires_at:
                    raise ValueError("wake pool expired")
                used = int(pool.get("fires_used") or 0) + 1
                pool["fires_used"] = used
                if used >= int(pool.get("fires_total") or 0):
                    pool["state"] = "consumed"
                pool["signature"] = self._sign(pool, key)
                record["fires_used"] = used
                if occurrence is not None:
                    record["last_occurrence"] = int(occurrence)
                record["signature"] = self._sign(record, key)
                records[_pool_key(str(record["pool"]))] = pool
                self._write(records)
                return used
            if spec:
                if occurrence is not None and int(record.get("last_occurrence") or 0) == int(occurrence):
                    return int(record.get("fires_used") or 0)
                used = int(record.get("fires_used") or 0) + 1
                record["fires_used"] = used
                if occurrence is not None:
                    record["last_occurrence"] = int(occurrence)
                if used >= int(spec.get("fires_total") or 0):
                    record["state"] = "consumed"
                record["signature"] = self._sign(record, key)
                self._write(records)
                return used
            record["state"] = "started"
            record["signature"] = self._sign(record, key)
            self._write(records)
            return 1

    def revoke(self, sid: str) -> None:
        with self._locked():
            records = self._read()
            record = records.get(sid)
            if record is None:
                return
            key = self._key()
            record["state"] = "revoked"
            record["signature"] = self._sign(record, key)
            pool_id = str(record.get("pool") or "")
            if pool_id:
                # 池的最后一个成员被撤销时一并关池，避免留下「无人使用但仍有额度」的记录。
                remaining = any(
                    isinstance(other, dict)
                    and other.get("pool") == pool_id
                    and other.get("sid") != sid
                    and other.get("state") == "pending"
                    for other in records.values()
                )
                pool = records.get(_pool_key(pool_id))
                if not remaining and isinstance(pool, dict) and self._pool_valid(pool, key):
                    pool["state"] = "revoked"
                    pool["signature"] = self._sign(pool, key)
            self._write(records)

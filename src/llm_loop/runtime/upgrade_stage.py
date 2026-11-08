"""Offline wheel quarantine: stage/verify/abort without executing untrusted code.

Staging an integrity-checked wheel is useful before a service stop. It is NOT
trusted-source attestation, an installed version, or approval for a cutover.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import stat
import threading
from pathlib import Path
from typing import Any

from llm_loop.runtime.service_control import atomic_write_bytes_file
from llm_loop.runtime.upgrade_preflight import candidate_preflight
from llm_loop.timekeeping import system_local_now

SCHEMA = "lfl.upgrade.quarantine/v1"
_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
_CHUNK = 1024 * 1024


class StageRejectedError(Exception):
    """A bounded reason, never a user path or credential."""


def _private_directory(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISDIR(info.st_mode) and not (stat.S_IMODE(info.st_mode) & 0o077)


def _root(home: Path, *, create: bool = False) -> Path:
    home = home.expanduser()
    if ".." in home.parts or home.is_symlink():
        raise StageRejectedError("unsafe_stage_home")
    if not home.exists():
        if not create:
            raise StageRejectedError("unknown_transaction")
        home.mkdir(mode=0o700, parents=True)
    if not home.is_dir():
        raise StageRejectedError("unsafe_stage_home")
    root = home / "upgrade-staging"
    if root.is_symlink():
        raise StageRejectedError("unsafe_stage_root")
    if not root.exists():
        if not create:
            raise StageRejectedError("unknown_transaction")
        root.mkdir(mode=0o700)
    if not _private_directory(root):
        raise StageRejectedError("nonprivate_stage_root")
    return root


def _stage_id(value: str) -> str:
    if len(value) != 24 or any(c not in "0123456789abcdef" for c in value):
        raise StageRejectedError("unknown_transaction")
    return value


def _safe_file(path: Path, *, digest_only: bool = False) -> bytes | str:
    if path.is_symlink():
        raise StageRejectedError("stage_integrity_failed")
    try:
        fd = os.open(path, _FLAGS | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as reader:
            info = os.fstat(reader.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 512 * 1024 * 1024:
                raise StageRejectedError("stage_integrity_failed")
            if stat.S_IMODE(info.st_mode) & 0o077:
                raise StageRejectedError("nonprivate_stage_file")
            if not digest_only:
                if info.st_size > 1024 * 1024:
                    raise StageRejectedError("stage_integrity_failed")
                return reader.read()
            digest = hashlib.sha256()
            while block := reader.read(_CHUNK):
                digest.update(block)
            return digest.hexdigest()
    except (OSError, ValueError) as exc:
        raise StageRejectedError("stage_integrity_failed") from exc


def _read(stage: Path, stage_id: str) -> dict[str, Any]:
    if stage.is_symlink() or not stage.is_dir() or not _private_directory(stage):
        raise StageRejectedError("unknown_transaction")
    if {p.name for p in stage.iterdir()} != {"candidate.whl", "stage.json"}:
        raise StageRejectedError("unexpected_stage_files")
    try:
        obj = json.loads(_safe_file(stage / "stage.json"))
    except (ValueError, TypeError) as exc:
        raise StageRejectedError("stage_integrity_failed") from exc
    if (not isinstance(obj, dict) or set(obj) !=
            {"schema", "stage_id", "candidate_sha256", "candidate_version", "cutover_allowed"}
            or obj.get("schema") != SCHEMA or obj.get("stage_id") != stage_id
            or obj.get("cutover_allowed") is not False):
        raise StageRejectedError("stage_integrity_failed")
    digest = obj["candidate_sha256"]
    if (not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or not isinstance(obj["candidate_version"], str)):
        raise StageRejectedError("stage_integrity_failed")
    if _safe_file(stage / "candidate.whl", digest_only=True) != digest:
        raise StageRejectedError("stage_integrity_failed")
    return obj


def stage_candidate(*, home: Path, candidate: str, expected: str,
                    current_version: str | None) -> tuple[int, dict[str, Any]]:
    status, verified = candidate_preflight(
        candidate=candidate, expected_sha256=expected, current_version=current_version,
    )
    if status:
        return 1, {"schema": SCHEMA, "staged": False,
                   "reason": verified.get("reason", "candidate_unverified")}
    try:
        directory = _root(home, create=True)
        stage_id = secrets.token_hex(12)
        stage = directory / stage_id
        stage.mkdir(mode=0o700)
        # Re-read through O_NOFOLLOW: if source was switched since preflight,
        # the copied bytes must still match the operator's pinned digest.
        source = Path(candidate).expanduser()
        with os.fdopen(os.open(source, _FLAGS | getattr(os, "O_NONBLOCK", 0)), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise StageRejectedError("candidate_unsafe_path")
            fd = os.open(stage / "candidate.whl", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as dest:
                digest = hashlib.sha256()
                copied = 0
                while block := stream.read(_CHUNK):
                    copied += len(block)
                    if copied > 512 * 1024 * 1024:
                        raise StageRejectedError("candidate_too_large")
                    digest.update(block)
                    dest.write(block)
                dest.flush()
                os.fsync(dest.fileno())
            if digest.hexdigest() != expected.lower():
                raise StageRejectedError("candidate_changed_during_copy")
        metadata = {"schema": SCHEMA, "stage_id": stage_id,
                    "candidate_sha256": expected.lower(),
                    "candidate_version": verified["candidate_version"],
                    "cutover_allowed": False}
        fd = os.open(stage / "stage.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as dest:
            dest.write((json.dumps(metadata, sort_keys=True) + "\n").encode())
            dest.flush()
            os.fsync(dest.fileno())
        directory_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return 0, {"schema": SCHEMA, "staged": True, "stage_id": stage_id,
                   "candidate_sha256": expected.lower(),
                   "candidate_version": verified["candidate_version"],
                   "source_trusted": False, "ready_for_cutover": False,
                   "active_version_changed": False, "services_changed": False,
                   "next_step": "lfl upgrade --verify-stage --id " + stage_id}
    except (OSError, ValueError, StageRejectedError) as exc:
        reason = str(exc) if isinstance(exc, StageRejectedError) else "stage_io_failed"
        # Never recursively clean a partially created directory which could
        # contain unexpected user writes; leave it for explicit investigation.
        return 1, {"schema": SCHEMA, "staged": False, "reason": reason,
                   "incomplete_stage_requires_manual_inspection": True}


def inspect_stage(*, home: Path, stage_id: str, abort: bool) -> tuple[int, dict[str, Any]]:
    try:
        identifier = _stage_id(stage_id)
        stage = _root(home) / identifier
        entry = _read(stage, identifier)
        if abort:
            # Bounded destructive scope: exactly two known files in one
            # self-created transaction directory, no user backup/data paths.
            (stage / "candidate.whl").unlink()
            (stage / "stage.json").unlink()
            stage.rmdir()
            return 0, {"schema": SCHEMA, "aborted": True, "stage_id": identifier,
                       "user_data_modified": False, "active_version_changed": False}
        return 0, {"schema": SCHEMA, "valid": True, "read_only": True,
                   "stage_id": identifier, "candidate_version": entry["candidate_version"],
                   "candidate_sha256": entry["candidate_sha256"],
                   "ready_for_cutover": False, "source_trusted": False}
    except (StageRejectedError, OSError) as exc:
        reason = str(exc) if isinstance(exc, StageRejectedError) else "stage_io_failed"
        return 1, {"schema": SCHEMA, "valid": False, "aborted": False,
                   "reason": reason}


# ── 升级事务 journal（DESIGN-20261107 §5.6/§5.7）与 supervisor 单实例（§3.3.1）──
# journal 是事务的真值：目录 0700、文件 0600、原子写 + fsync；状态推进采用
# expected-state CAS；同一时刻只允许一个活动事务。本段不执行任何生产切换——
# 它只持久化与仲裁事务事实。

TX_SCHEMA = "lfl.upgrade.transaction/v1"

#: §5.6 状态机：S0 observed → … → S11 committed（顺序即列表序）。
TX_STATES: tuple[str, ...] = (
    "observed",
    "candidate_resolved",
    "source_and_digest_verified",
    "staged_release_built",
    "candidate_smoke_passed",
    "snapshot_verified",
    "services_confirmed_idle",
    "services_stopped",
    "active_pointer_switched",
    "services_started",
    "health_and_identity_verified",
    "committed",
)
#: 终态（成功 committed 之外，任一失败进入其中之一，绝不把中间态报成功）。
TX_TERMINAL_STATES: tuple[str, ...] = ("committed", "aborted_before_cutover", "rolled_back")

_VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
_TX_ID_RE = re.compile(r"[0-9a-f]{24}\Z")

# 审查 P2-2：单进程内 create/advance/handover 的串行化（CAS 读写与单活动
# 槽检查同锁）；跨进程由 supervisor.lock（flock）承担，§5.7 事务锁在
# Deepin 旁路阶段扩展。
_TX_LOCK = threading.Lock()

_JOURNAL_FIELDS = frozenset({
    "schema", "transaction_id", "idempotency_key", "state",
    "old_version", "candidate_version", "wheel_sha256",
    "expected_generation", "target_generation", "created_at", "updated_at",
    "failure_reason", "handover",
})


class TransactionError(Exception):
    """有界 reason（transaction_already_active / transaction_state_conflict /
    handover_cas_conflict / unknown_transaction / unsafe_transaction_home）。"""


def _tx_root(home: Path, *, create: bool = False) -> Path:
    home = home.expanduser()
    if ".." in home.parts or home.is_symlink():
        raise TransactionError("unsafe_transaction_home")
    root = home / "upgrade-transactions"
    if root.is_symlink():
        raise TransactionError("unsafe_transaction_home")
    if not root.exists():
        if not create:
            raise TransactionError("unknown_transaction")
        root.mkdir(mode=0o700, parents=True)
    if not _private_directory(root):
        raise TransactionError("unsafe_transaction_home")
    return root


def _atomic_write_journal(path: Path, payload: dict[str, Any]) -> None:
    # P2-2（审查 b7691f4e）：真原子写——复用 service_control 的
    # atomic_write_bytes_file（tmp+fsync+rename+目录 fsync），失败时旧 journal
    # 字节完整保留；不再 O_TRUNC 原地覆盖（半写窗口不可接受）。
    data = (json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n").encode()
    try:
        atomic_write_bytes_file(path, data, mode=0o600)
    except OSError as exc:
        raise TransactionError("journal_write_failed") from exc


def _active_transactions(root: Path) -> list[str]:
    active: list[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.is_symlink() or entry.name == "supervisor.lock":
            continue
        try:
            journal = _read_journal(entry)
        except TransactionError:
            # 无法解析的目录不是"可证明空闲"——按活动计（fail-closed）。
            active.append(entry.name)
            continue
        if journal.get("state") not in TX_TERMINAL_STATES:
            active.append(entry.name)
    return active


def _read_journal(tx_dir: Path) -> dict[str, Any]:
    journal = tx_dir / "journal.json"
    if journal.is_symlink() or not journal.is_file():
        raise TransactionError("unknown_transaction")
    try:
        raw = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TransactionError("unknown_transaction") from exc
    if (
        not isinstance(raw, dict)
        or raw.get("schema") != TX_SCHEMA
        or raw.get("state") not in TX_STATES + TX_TERMINAL_STATES
        or not _TX_ID_RE.fullmatch(str(raw.get("transaction_id") or ""))
        or tx_dir.name != raw.get("transaction_id")
    ):
        raise TransactionError("unknown_transaction")
    return raw


def create_transaction(
    home: Path,
    *,
    idempotency_key: str,
    old_version: str | None,
    candidate_version: str,
    wheel_sha256: str,
    expected_generation: int,
    target_generation: int,
) -> dict[str, Any]:
    """创建 S0 observed 事务 journal；已存在活动事务即拒绝（单活动槽）。

    参数校验无锁（纯函数式拒绝）；磁盘单活动槽检查与 journal 写入在
    ``_TX_LOCK`` 内串行（审查 P2-2），防止并发双创建绕过单槽检查。
    """
    if not idempotency_key.strip():
        raise TransactionError("invalid_idempotency_key")
    if not _VERSION_RE.fullmatch(candidate_version):
        raise TransactionError("invalid_candidate_version")
    if old_version is not None and not _VERSION_RE.fullmatch(old_version):
        raise TransactionError("invalid_old_version")
    if not re.fullmatch(r"[0-9a-f]{64}", wheel_sha256):
        raise TransactionError("invalid_wheel_sha256")
    if expected_generation < 0 or target_generation != expected_generation + 1:
        raise TransactionError("invalid_generation_pair")
    with _TX_LOCK:
        return _create_transaction_locked(
            home,
            idempotency_key=idempotency_key,
            old_version=old_version,
            candidate_version=candidate_version,
            wheel_sha256=wheel_sha256,
            expected_generation=expected_generation,
            target_generation=target_generation,
        )


def _invalidate_recovery_marker(home: Path) -> None:
    """§4.4 / Stage 3-C：事务创建/推进使旧 recovery 判定失效。

    必须在 ``_TX_LOCK`` 持锁路径内调用（与 journal 写入同临界区），保证
    "存在未完成事务 ⇒ recovery-ok 不在或必然 stale" 的时序不变量；
    lfl-recovery / lfl-service 侧的绑定核对（active_version + tx_fingerprint
    + journal gate）将拒绝任何残留的 stale marker。
    """
    marker = home / "state" / "recovery-ok"
    with contextlib.suppress(FileNotFoundError):
        marker.unlink()


def _create_transaction_locked(
    home: Path,
    *,
    idempotency_key: str,
    old_version: str | None,
    candidate_version: str,
    wheel_sha256: str,
    expected_generation: int,
    target_generation: int,
) -> dict[str, Any]:
    root = _tx_root(home, create=True)
    active = _active_transactions(root)
    if active:
        raise TransactionError(
            f"transaction_already_active: {active[0]}"
        )
    # §4.4：新事务创建前先删除旧 recovery-ok（设计原文"每次新事务推进前
    # 先删除该标记"）。删除先于 tx 目录创建：并发窗口内 recovery 若运行，
    # 会因孤儿/未完成事务 fail-closed，方向安全。
    _invalidate_recovery_marker(home)
    tx_id = secrets.token_hex(12)
    tx_dir = root / tx_id
    tx_dir.mkdir(mode=0o700)
    now = system_local_now().isoformat(timespec="seconds")
    payload = {
        "schema": TX_SCHEMA,
        "transaction_id": tx_id,
        "idempotency_key": idempotency_key,
        "state": "observed",
        "old_version": old_version,
        "candidate_version": candidate_version,
        "wheel_sha256": wheel_sha256,
        "expected_generation": expected_generation,
        "target_generation": target_generation,
        "created_at": now,
        "updated_at": now,
        "failure_reason": None,
        "handover": None,
    }
    _atomic_write_journal(tx_dir / "journal.json", payload)
    return payload


def read_transaction(home: Path, transaction_id: str) -> dict[str, Any]:
    tx_id = _TX_ID_RE.fullmatch(transaction_id or "")
    if tx_id is None:
        raise TransactionError("unknown_transaction")
    return _read_journal(_tx_root(home) / transaction_id)


def advance_transaction(
    home: Path,
    transaction_id: str,
    *,
    from_state: str,
    to_state: str,
    failure_reason: str | None = None,
    **extra_fields: Any,
) -> dict[str, Any]:
    """expected-state CAS 推进；``from_state == to_state`` 幂等重放。

    任何失败态（aborted_before_cutover / rolled_back）必须携带
    ``failure_reason``，中间态不得缺失或伪造成功。写前读与写盘在
    ``_TX_LOCK`` 内串行（审查 P2-2），防并发推进交叉覆盖。
    """
    probe = _read_journal(_tx_root(home) / transaction_id)
    current_probe = probe["state"]
    if to_state in ("aborted_before_cutover", "rolled_back") and not failure_reason:
        raise TransactionError("terminal_failure_requires_reason")
    if current_probe != from_state:
        raise TransactionError(
            f"transaction_state_conflict: expected={from_state} actual={current_probe}"
        )
    if from_state == to_state:
        # 幂等重放：同状态同事实，不重复推进。
        return probe
    with _TX_LOCK:
        return _advance_transaction_locked(
            home, transaction_id, from_state=from_state, to_state=to_state,
            failure_reason=failure_reason, **extra_fields,
        )


def _advance_transaction_locked(
    home: Path,
    transaction_id: str,
    *,
    from_state: str,
    to_state: str,
    failure_reason: str | None,
    **extra_fields: Any,
) -> dict[str, Any]:
    tx_dir = _tx_root(home) / transaction_id
    payload = _read_journal(tx_dir)
    current = payload["state"]
    if current != from_state:
        raise TransactionError(
            f"transaction_state_conflict: expected={from_state} actual={current}"
        )
    if from_state == to_state:
        # 幂等重放：同状态同事实，不重复推进。
        return payload
    payload["state"] = to_state
    payload["updated_at"] = system_local_now().isoformat(timespec="seconds")
    if failure_reason is not None:
        payload["failure_reason"] = failure_reason
    payload.update(extra_fields)
    _atomic_write_journal(tx_dir / "journal.json", payload)
    # §4.4 / Stage 3-C：journal 状态推进后旧 recovery 判定立即失效。删除在
    # 原子写入之后：并发 recovery 若在写后删前运行，读到的是新状态并按其
    # fail-closed；删除本身与 journal 写入同临界区，无双写者竞态。
    _invalidate_recovery_marker(home)
    return payload


class SupervisorLock:
    """§3.3.1 单实例锁：``upgrade-transactions/supervisor.lock``（0600 + flock）。

    拿不到锁的实例必须直接退出并回报 ``supervisor_conflict``，不改任何状态；
    本类只提供 acquire/release 与 conflict 事实，不猜测谁是权威实例。
    """

    def __init__(self, home: Path) -> None:
        self._root = _tx_root(home, create=True)
        self._path = self._root / "supervisor.lock"
        self._fd: int | None = None

    def acquire(self) -> bool:
        import fcntl

        if self._fd is not None:
            return True
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        self._fd = fd
        return True

    @property
    def conflict_reason(self) -> str:
        return "supervisor_conflict"

    def release(self) -> None:
        import fcntl

        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


def handover_mark_new_ready(home: Path, transaction_id: str, *, generation: int) -> dict[str, Any]:
    """§3.3.1 步骤 1：新 supervisor 通过 self-check 后回报 ready(generation)。

    只记录事实；旧实例是否 drain、CAS 是否执行由 :func:`handover_complete_cas`
    承担。重复回报同一 generation 幂等。
    """
    tx_dir = _tx_root(home) / transaction_id
    payload = _read_journal(tx_dir)
    handover = payload.get("handover") or {}
    if handover.get("phase") in ("ready", "drain", "settled"):
        if handover.get("new_ready_generation") == generation:
            return payload
        raise TransactionError("handover_ready_conflict")
    payload["handover"] = {
        "phase": "ready",
        "old_generation": payload.get("target_generation"),
        "new_ready_generation": generation,
        "recorded_at": system_local_now().isoformat(timespec="seconds"),
    }
    payload["updated_at"] = payload["handover"]["recorded_at"]
    _atomic_write_journal(tx_dir / "journal.json", payload)
    return payload


def handover_complete_cas(
    home: Path,
    transaction_id: str,
    *,
    expected_generation: int,
    authority_pid: int,
    authority_start_time: str,
) -> dict[str, Any]:
    """§3.3.1 步骤 3：``CAS expected_generation=N`` 交接 active_generation。

    CAS 失败即把 handover 置 ``rollback_pending``（不标 settled）并抛
    ``handover_cas_conflict``——旧实例继续服务，事务进入显式回滚待办。
    """
    tx_dir = _tx_root(home) / transaction_id
    payload = _read_journal(tx_dir)
    handover = payload.get("handover") or {}
    ready_generation = int(handover.get("new_ready_generation") or 0)
    if handover.get("phase") not in ("ready", "drain"):
        raise TransactionError("handover_not_ready")
    if expected_generation != ready_generation:
        payload["handover"] = {**handover, "phase": "rollback_pending"}
        payload["failure_reason"] = "handover_cas_conflict"
        payload["updated_at"] = system_local_now().isoformat(timespec="seconds")
        _atomic_write_journal(tx_dir / "journal.json", payload)
        raise TransactionError(
            f"handover_cas_conflict: expected={expected_generation} ready={ready_generation}"
        )
    payload["handover"] = {
        **handover,
        "phase": "settled",
        "cas": "ok",
        "authority_pid": authority_pid,
        "authority_start_time": authority_start_time,
        "settled_at": system_local_now().isoformat(timespec="seconds"),
    }
    payload["updated_at"] = payload["handover"]["settled_at"]
    _atomic_write_journal(tx_dir / "journal.json", payload)
    return payload

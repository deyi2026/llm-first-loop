"""Offline wheel quarantine: stage/verify/abort without executing untrusted code.

Staging an integrity-checked wheel is useful before a service stop. It is NOT
trusted-source attestation, an installed version, or approval for a cutover.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any

from llm_loop.runtime.upgrade_preflight import candidate_preflight

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

"""Read-only integrity inspection of a local upgrade wheel.

This is *not* a trust verifier, compatibility check, software installer or
authorization for live cutover. No file is extracted and no user state is read.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any

_MAX_WHEEL_BYTES = 512 * 1024 * 1024
_MAX_MEMBERS = 10_000
_MAX_UNCOMPRESSED = 2 * 1024**3
_MAX_METADATA_BYTES = 64 * 1024
_CHUNK = 1024 * 1024
SCHEMA = "lfl.upgrade.preflight/v1"
_DIGEST = re.compile(r"[0-9a-fA-F]{64}\Z")
_VERSION = re.compile(r"[0-9][a-zA-Z0-9.+_!]*\Z")
_WHEEL_NAME = re.compile(r"llm_first_loop-([^-]+)-(?:[0-9]+-)?[^-]+-[^-]+-[^-]+\.whl\Z")


class CandidateRejectedError(Exception):
    """Safe machine-readable reason. Never contains a path or secret."""


def _require_wheel_filename(path: Path) -> str:
    match = _WHEEL_NAME.fullmatch(path.name)
    if match is None:
        raise CandidateRejectedError("candidate_invalid_metadata")
    return match.group(1)


def _identity_from_archive(stream: Any, candidate_version: str) -> str:
    try:
        with zipfile.ZipFile(stream) as archive:
            members = archive.infolist()
            if len(members) > _MAX_MEMBERS:
                raise CandidateRejectedError("candidate_invalid_archive")
            if sum(member.file_size for member in members) > _MAX_UNCOMPRESSED:
                raise CandidateRejectedError("candidate_invalid_archive")
            if len({member.filename for member in members}) != len(members):
                raise CandidateRejectedError("candidate_invalid_archive")
            for member in members:
                parts = PurePosixPath(member.filename).parts
                unix_type = stat.S_IFMT(member.external_attr >> 16)
                if (not parts or member.filename.startswith("/") or ".." in parts
                        or "\\" in member.filename or unix_type == stat.S_IFLNK):
                    raise CandidateRejectedError("candidate_invalid_archive")
            identity = f"llm_first_loop-{candidate_version}.dist-info/"
            matches = [item for item in members if item.filename.endswith(".dist-info/METADATA")]
            wheel_files = [item for item in members if item.filename.endswith(".dist-info/WHEEL")]
            if (len(matches) != 1 or matches[0].filename != identity + "METADATA"
                    or len(wheel_files) != 1 or wheel_files[0].filename != identity + "WHEEL"
                    or matches[0].file_size > _MAX_METADATA_BYTES
                    or wheel_files[0].file_size > _MAX_METADATA_BYTES):
                raise CandidateRejectedError("candidate_invalid_metadata")
            metadata = BytesParser().parsebytes(archive.read(matches[0]))
            # Multiple conflicting headers must not silently choose a version.
            names = metadata.get_all("Name", [])
            versions = metadata.get_all("Version", [])
            if (len(names) != 1 or names[0].lower().replace("_", "-") != "llm-first-loop"
                    or len(versions) != 1 or versions[0] != candidate_version
                    or _VERSION.fullmatch(versions[0]) is None):
                raise CandidateRejectedError("candidate_invalid_metadata")
            wheel = BytesParser().parsebytes(archive.read(wheel_files[0]))
            if wheel.get("Wheel-Version", "").split(".", 1)[0] != "1":
                raise CandidateRejectedError("candidate_invalid_metadata")
            return versions[0]
    except CandidateRejectedError:
        raise
    except (zipfile.BadZipFile, EOFError, OSError, RuntimeError, NotImplementedError,
            ValueError, UnicodeError) as exc:
        raise CandidateRejectedError("candidate_invalid_archive") from exc


def _read_candidate(path: str, expected: str) -> str:
    # Never call resolve() on the candidate: it hides a final symlink and can
    # admit a different file from the one the operator actually supplied.
    candidate = Path(path).expanduser()
    if ".." in candidate.parts or not candidate.name or any(ord(c) < 32 for c in str(candidate)):
        raise CandidateRejectedError("candidate_unsafe_path")
    if candidate.is_symlink():
        raise CandidateRejectedError("candidate_unsafe_path")
    filename_version = _require_wheel_filename(candidate)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)  # avoid hanging forever on named pipes
    try:
        fd = os.open(candidate, flags)
    except (OSError, ValueError) as exc:
        if candidate.is_symlink():
            raise CandidateRejectedError("candidate_unsafe_path") from exc
        raise CandidateRejectedError("candidate_unreadable") from exc
    with os.fdopen(fd, "rb") as stream:
        original = os.fstat(stream.fileno())
        if not stat.S_ISREG(original.st_mode):
            raise CandidateRejectedError("candidate_unsafe_path")
        if original.st_size > _MAX_WHEEL_BYTES:
            raise CandidateRejectedError("candidate_too_large")
        digest = hashlib.sha256()
        while data := stream.read(_CHUNK):
            digest.update(data)
        if digest.hexdigest() != expected.lower():
            raise CandidateRejectedError("candidate_hash_mismatch")
        stream.seek(0)
        version = _identity_from_archive(stream, filename_version)
        final = os.fstat(stream.fileno())
        if ((original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns,
             original.st_ctime_ns) !=
                (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns,
                 final.st_ctime_ns)):
            raise CandidateRejectedError("candidate_changed_during_read")
        return version


def candidate_preflight(
    *, candidate: str, expected_sha256: str, current_version: str | None,
    require_trust: bool = False, require_data_compatibility: bool = False,
) -> tuple[int, dict[str, Any]]:
    """Validate only local wheel bytes; return 0 for integrity, not approval."""
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "read_only": True,
        "package_replaced": False,
        "services_changed": False,
        "current_version": current_version,
        "candidate_sha256": expected_sha256.lower(),
        "candidate_version": None,
        "candidate_integrity_verified": False,
        "candidate_trusted": False,
        "data_compatibility_verified": False,
        "stage_eligible": False,
        "compatibility": "unknown_requires_operator_review",
        "service_identity": "not_verified",
        "snapshot_coverage": "not_verified",
    }
    try:
        version = _read_candidate(candidate, expected_sha256)
        report.update(candidate_version=version, candidate_integrity_verified=True)
        if require_trust:
            raise CandidateRejectedError("candidate_trust_unknown")
        if require_data_compatibility:
            raise CandidateRejectedError("schema_compatibility_unknown")
    except CandidateRejectedError as exc:
        report["reason"] = str(exc)
        return 1, report
    # Hash equality proves bytes only. Deliberately no path to prepare/cutover.
    return 0, report

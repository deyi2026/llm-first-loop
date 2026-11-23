#!/usr/bin/python3 -I
"""Deepin Polkit attestation helper (candidate only; NOT installed).

The helper has ONE operation: record a 128-bit challenge in a fixed root-owned
receipt directory after pkexec authenticates the active administrator. It does
not issue LFL Task Leases, run commands, edit user files, restart services, or
replace a real signed Host authority. Production install needs separate consent.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

RECEIPT_DIR = Path("/var/lib/lfl-task-host-probe/receipts")
CHALLENGE_RE = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
SCHEMA = "lfl.task-host-polkit-attestation/v1"


class ProbeDeniedError(RuntimeError):
    """Fail-closed denial without leaking privileged paths or file content."""


def _check_private_root_chain(path: Path, *, expected_owner: int = 0) -> None:
    """All existing ancestors must be real root-owned, non-group-writable dirs."""
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ProbeDeniedError("unsafe_receipt_path")
    for parent in reversed((path, *path.parents)):
        info = parent.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in (0, expected_owner)
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise ProbeDeniedError("unsafe_receipt_directory")


def _write_attestation(
    challenge: str, requester_uid: int, *,
    directory: Path = RECEIPT_DIR, expected_owner: int = 0,
) -> str:
    """Exclusive O_NOFOLLOW single receipt; no path/command input from caller."""
    if CHALLENGE_RE.fullmatch(challenge) is None:
        raise ProbeDeniedError("invalid_challenge")
    _check_private_root_chain(directory, expected_owner=expected_owner)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_fd = os.open(directory, flags)
    try:
        info = os.fstat(directory_fd)
        if info.st_uid != expected_owner or stat.S_IMODE(info.st_mode) & 0o022:
            raise ProbeDeniedError("unsafe_receipt_directory")
        record = {
            "schema": SCHEMA,
            "challenge": challenge,
            "requester_uid": requester_uid,
            "issued_at_utc": datetime.now(UTC).isoformat(),
            "effect": "polkit_root_receipt_only",
            "signed_task_lease": False,
        }
        body = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
        fd = os.open(
            challenge + ".json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=directory_fd,
        )
        with os.fdopen(fd, "wb") as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        os.fsync(directory_fd)
        return hashlib.sha256(body).hexdigest()
    finally:
        os.close(directory_fd)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != "attest" or CHALLENGE_RE.fullmatch(args[1]) is None:
        print("DENY: expected attest <32-lowercase-hex-challenge>", file=sys.stderr)
        return 77
    raw_uid = os.environ.get("PKEXEC_UID", "")
    if (
        os.geteuid() != 0 or os.getuid() != 0
        or not raw_uid.isdecimal() or int(raw_uid) < 1000
    ):
        print("DENY: root-only pkexec caller identity required", file=sys.stderr)
        return 77
    os.umask(0o077)
    try:
        digest = _write_attestation(args[1], int(raw_uid))
    except (OSError, ProbeDeniedError):
        print("HOLD: root receipt path unavailable or replayed", file=sys.stderr)
        return 78
    print(json.dumps({
        "result": "POLKIT_ROOT_RECEIPT_WRITTEN",
        "challenge": args[1],
        "receipt_sha256": digest,
        "signed_task_lease": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

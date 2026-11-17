#!/usr/bin/env python3
"""One local integration writer per Git common directory.

Only a clean, non-main integration worktree at the supplied exact HEAD is changed.
This does not protect arbitrary shell writes or implement an atomic remote
main CAS. A failed cherry-pick preserves the dirty worktree for reconciliation.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

_SHA = re.compile(r"^[0-9a-f]{40}$")


class IntegrationHoldError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _git(worktree: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree), *args],
            capture_output=True, text=True, check=False, timeout=20,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise IntegrationHoldError("git_probe_unavailable") from exc
    if result.returncode:
        raise IntegrationHoldError("git_probe_failed")
    return result.stdout.strip()


def common_dir(worktree: Path) -> Path:
    """Resolve the same physical git-common-dir for all linked worktrees."""
    root = worktree.resolve(strict=True)
    if _git(root, "rev-parse", "--is-inside-work-tree") != "true":
        raise IntegrationHoldError("worktree_untrusted")
    if Path(_git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise IntegrationHoldError("worktree_untrusted")
    raw = Path(_git(root, "rev-parse", "--git-common-dir"))
    common = (raw if raw.is_absolute() else root / raw).resolve(strict=True)
    if not common.is_dir():
        raise IntegrationHoldError("integration_lock_unavailable")
    return common


@contextlib.contextmanager
def integration_lock(worktree: Path) -> Iterator[Path]:
    try:
        directory = common_dir(worktree)
        # Lock the stable Git directory inode, not a removable lock file.
        # Unlinking/recreating a lock file must never create a second writer.
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(directory, flags)
    except (OSError, ValueError, IntegrationHoldError) as exc:
        if isinstance(exc, IntegrationHoldError):
            raise
        raise IntegrationHoldError("integration_lock_unavailable") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode):
            raise IntegrationHoldError("integration_lock_unavailable")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise IntegrationHoldError("integration_writer_busy") from exc
        except OSError as exc:
            raise IntegrationHoldError("integration_lock_unavailable") from exc
        yield directory
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def apply_commits(worktree: Path, expected_head: str, commits: list[str]) -> dict:
    if not _SHA.fullmatch(expected_head) or not commits or not all(
        _SHA.fullmatch(c) for c in commits
    ):
        raise IntegrationHoldError("invalid_exact_sha")
    with integration_lock(worktree):
        root = worktree.resolve(strict=True)
        branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
        if branch in {"main", "master"}:
            raise IntegrationHoldError("main_write_forbidden")
        if _git(root, "rev-parse", "HEAD") != expected_head:
            raise IntegrationHoldError("integration_head_changed")
        if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
            raise IntegrationHoldError("integration_dirty")
        for sha in commits:
            if _git(root, "cat-file", "-t", sha) != "commit":
                raise IntegrationHoldError("source_not_commit")
            try:
                result = subprocess.run(
                    ["git", "-C", str(root), "cherry-pick", sha],
                    capture_output=True, text=True, check=False, timeout=90,
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                raise IntegrationHoldError("cherry_pick_needs_reconciliation") from exc
            if result.returncode:
                # Never abort or reset automatically: retain evidence and conflicts.
                raise IntegrationHoldError("cherry_pick_needs_reconciliation")
        return {
            "decision": "applied_local_only", "branch": branch,
            "old_head": expected_head, "new_head": _git(root, "rev-parse", "HEAD"),
            "commits": commits, "remote_main_cas": False,
            "push": False, "deployment": False,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("probe", "apply-commits"))
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--expected-head")
    parser.add_argument("--commit", action="append", default=[])
    parser.add_argument("--hold-seconds", type=float, default=0)
    args = parser.parse_args(argv)
    try:
        if args.mode == "probe":
            if not 0 <= args.hold_seconds <= 10:
                raise IntegrationHoldError("invalid_probe_duration")
            with integration_lock(Path(args.worktree)) as path:
                print(json.dumps({"decision": "lock_held", "lock_path": str(path)}), flush=True)
                time.sleep(args.hold_seconds)
            return 0
        result = apply_commits(Path(args.worktree), args.expected_head or "", args.commit)
        print(json.dumps(result))
        return 0
    except IntegrationHoldError as exc:
        print(json.dumps({"decision": "HOLD", "reason": exc.reason,
                          "remote_main_cas": False, "push": False}), flush=True)
        return 3


if __name__ == "__main__":
    sys.exit(main())

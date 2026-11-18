"""Bounded Host-side Git commit adapter for verified task capabilities.

This is deliberately NOT a model-facing shell or a push/merge tool. The trusted
Runtime must inject a RootOwnedTaskAuthority and the canonical LaneStore.
Only a signed task lease + exact Lane/CAS + parent write scope may reach Git.
No repository hooks, external diff filters, ambient GIT_* env, or arbitrary
Git options are accepted. Push/release retain independent review gates.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from llm_loop.core.run_context import current_session_id, current_write_scope, workspace_base
from llm_loop.core.task_capabilities import (
    CapabilityRequest,
    HostAuthorityFacts,
    resolve_capability,
)
from llm_loop.core.write_scope import scope_allows
from llm_loop.introspection.lane import LaneStore
from llm_loop.tools.task_authority import RootOwnedTaskAuthority, TaskAuthorityError

_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_PROTECTED_NAMES = frozenset({".git", ".gitattributes", ".gitmodules", ".lfl"})


class ManagedGitError(RuntimeError):
    """A bounded denial or uncertain effect; no raw secrets or Git environment."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class GitCommitRequest:
    lease_id: str
    capability: CapabilityRequest
    worktree: str
    expected_head: str
    expected_lane_version: int
    expected_gitdir: str
    expected_common_dir: str
    paths: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class GitCommitReceipt:
    old_head: str
    new_head: str
    paths: tuple[str, ...]
    lane_version: int
    worktree: str


def _safe_env() -> dict[str, str]:
    """No ambient Git config, filters, hooks, SSH, credentials or index overrides."""
    allowed = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "USER", "LOGNAME", "TMPDIR")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_ATTR_NOSYSTEM="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_NO_REPLACE_OBJECTS="1",
    )
    return env


def _git(worktree: str, *args: str, timeout: int = 30) -> bytes:
    """Fixed executable/flags; never a shell, user -c or model-controlled env."""
    cmd = [
        "git",
        "--no-pager",
        "--literal-pathspecs",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "commit.gpgsign=false",
        "-C",
        worktree,
        *args,
    ]
    try:
        result = subprocess.run(
            cmd, env=_safe_env(), capture_output=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ManagedGitError("git_execution_unavailable_or_unknown") from exc
    if result.returncode != 0:
        raise ManagedGitError("git_command_failed")
    return result.stdout


def _git_line(worktree: str, *args: str) -> str:
    try:
        return _git(worktree, *args).decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ManagedGitError("git_output_invalid") from exc


def _canonical_worktree(worktree: str) -> str:
    if not os.path.isabs(worktree) or os.path.realpath(worktree) != worktree:
        raise ManagedGitError("git_worktree_not_canonical")
    if not os.path.isdir(worktree) or os.path.islink(worktree):
        raise ManagedGitError("git_worktree_unavailable")
    return worktree


def _git_metadata(worktree: str) -> tuple[str, str]:
    actual = _git_line(worktree, "rev-parse", "--show-toplevel")
    if actual != worktree:
        raise ManagedGitError("git_worktree_mismatch")
    gitdir = _git_line(worktree, "rev-parse", "--absolute-git-dir")
    if not os.path.isdir(gitdir) or os.path.realpath(gitdir) != gitdir:
        raise ManagedGitError("git_metadata_untrusted")
    common_raw = _git_line(worktree, "rev-parse", "--git-common-dir")
    common = os.path.realpath(
        common_raw if os.path.isabs(common_raw) else os.path.join(worktree, common_raw)
    )
    if not os.path.isdir(common) or (
        gitdir != common and not gitdir.startswith(common.rstrip("/") + "/worktrees/")
    ):
        raise ManagedGitError("git_metadata_untrusted")
    marker = os.path.join(worktree, ".git")
    if os.path.islink(marker):
        raise ManagedGitError("git_metadata_untrusted")
    return gitdir, common


def _paths_checked(worktree: str, paths: tuple[str, ...], lane_paths: list[str]) -> tuple[str, ...]:
    if not paths or len(paths) > 64 or len(set(paths)) != len(paths):
        raise ManagedGitError("git_paths_invalid")
    accepted: list[str] = []
    for path in paths:
        if (
            not isinstance(path, str)
            or not path
            or os.path.isabs(path)
            or "\x00" in path
            or "\n" in path
            or "\r" in path
            or any(seg in ("", ".", "..") for seg in path.split("/"))
            or any(seg in _PROTECTED_NAMES for seg in path.split("/"))
        ):
            raise ManagedGitError("git_paths_invalid")
        target = os.path.join(worktree, path)
        if os.path.realpath(target) != target or not os.path.isfile(target):
            raise ManagedGitError("git_paths_untrusted")
        if not any(
            path == declared or (declared.endswith("/**") and path.startswith(declared[:-3] + "/"))
            for declared in lane_paths
        ):
            raise ManagedGitError("git_lane_path_denied")
        accepted.append(path)
    return tuple(accepted)


def _assert_no_filters(worktree: str, paths: tuple[str, ...]) -> None:
    raw = _git(worktree, "check-attr", "-z", "filter", "--", *paths)
    chunks = raw.split(b"\x00")
    if not chunks or chunks[-1] != b"" or (len(chunks) - 1) != 3 * len(paths):
        raise ManagedGitError("git_filter_inspection_invalid")
    for i in range(2, len(chunks) - 1, 3):
        if chunks[i] not in (b"unspecified", b"unset"):
            raise ManagedGitError("git_external_filter_denied")


class ManagedGitAdapter:
    """Run a bounded ordinary commit, never push/merge, in a linked worktree.

    The caller must be a trusted Runtime component; it must not expose this
    constructor or GitCommitRequest as arbitrary model arguments.
    """

    def __init__(
        self,
        *,
        authority: RootOwnedTaskAuthority,
        lanes: LaneStore,
        lock_dir: Path,
        protected_roots: tuple[str, ...],
    ) -> None:
        self._authority = authority
        self._lanes = lanes
        self._lock_dir = lock_dir
        self._protected_roots = protected_roots

    def _preflight(self, item: GitCommitRequest) -> tuple[str, tuple[str, ...]]:
        worktree = _canonical_worktree(item.worktree)
        request = item.capability
        if (
            request.kind != "project"
            or request.verb != "git_commit"
            or request.target != worktree
            or not _SHA_RE.fullmatch(item.expected_head)
            or current_session_id.get() != request.owner_session_id
        ):
            raise ManagedGitError("git_request_identity_invalid")
        lane = self._lanes.get(request.lane_id)
        if (
            not lane
            or lane.get("status") != "active"
            or lane.get("goal_id") != request.goal_id
            or lane.get("owner_session_id") != request.owner_session_id
            or os.path.realpath(str(lane.get("worktree") or "")) != worktree
            or lane.get("head_sha") != item.expected_head
            or lane.get("version") != item.expected_lane_version
        ):
            raise ManagedGitError("git_lane_cas_conflict")
        checked = _paths_checked(worktree, item.paths, lane.get("paths") or [])
        parent_scope = current_write_scope.get()
        parent_allows = all(
            scope_allows(parent_scope, os.path.join(worktree, path), workspace_base())[0]
            for path in checked
        )
        try:
            claims = self._authority.verify(item.lease_id, request)
        except TaskAuthorityError as exc:
            raise ManagedGitError(exc.reason_code) from exc
        gitdir, common = _git_metadata(worktree)
        if (
            not os.path.isabs(item.expected_gitdir)
            or not os.path.isabs(item.expected_common_dir)
            or item.expected_gitdir != gitdir
            or item.expected_common_dir != common
        ):
            raise ManagedGitError("git_metadata_identity_mismatch")
        os_ready = os.access(worktree, os.W_OK) and os.access(gitdir, os.W_OK)
        facts = HostAuthorityFacts(
            authority="verified",
            parent_scope_allows=parent_allows,
            lane_fence_valid=True,
            backend_supported=True,
            os_permission_granted=os_ready,
            protected_roots=self._protected_roots,
        )
        verdict = resolve_capability(request, lease=claims, facts=facts)
        if not verdict.allowed:
            raise ManagedGitError(verdict.reason_code)
        if _git_line(worktree, "rev-parse", "HEAD") != item.expected_head:
            raise ManagedGitError("git_head_cas_conflict")
        if any(
            os.path.commonpath((os.path.realpath(os.path.join(worktree, p)), root)) == root
            for p in checked
            for root in self._protected_roots
        ):
            raise ManagedGitError("git_protected_path_denied")
        return worktree, checked

    def commit_paths(self, item: GitCommitRequest) -> GitCommitReceipt:
        if (
            not isinstance(item.message, str)
            or not (1 <= len(item.message.strip()) <= 200)
            or "\n" in item.message
            or "\r" in item.message
        ):
            raise ManagedGitError("git_message_invalid")
        worktree, checked = self._preflight(item)
        if not self._lock_dir.is_dir() or self._lock_dir.is_symlink():
            raise ManagedGitError("git_lock_unavailable")
        lock_name = hashlib.sha256(worktree.encode()).hexdigest()[:32] + ".lock"
        lock_path = self._lock_dir / lock_name
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        except OSError as exc:
            raise ManagedGitError("git_lock_unavailable") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ManagedGitError("git_lock_untrusted")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ManagedGitError("git_lock_busy") from exc
            # Verify *again* under lock, then immediately before the commit.
            self._preflight(item)
            if _git(worktree, "diff", "--cached", "--name-only", "-z"):
                raise ManagedGitError("git_index_not_clean")
            _assert_no_filters(worktree, checked)
            _git(worktree, "add", "--", *checked)
            self._preflight(item)
            staged = tuple(
                path.decode("utf-8")
                for path in _git(worktree, "diff", "--cached", "--name-only", "-z").split(b"\x00")
                if path
            )
            if not staged:
                raise ManagedGitError("git_no_changes")
            if not set(staged).issubset(checked):
                raise ManagedGitError("git_index_changed_unexpectedly")
            _git(
                worktree,
                "commit",
                "--only",
                "--no-verify",
                "--no-gpg-sign",
                "-m",
                item.message,
                "--",
                *checked,
                timeout=60,
            )
            new_head = _git_line(worktree, "rev-parse", "HEAD")
            parents = _git_line(worktree, "rev-list", "--parents", "-n", "1", "HEAD").split()
            if len(parents) != 2 or parents != [new_head, item.expected_head]:
                raise ManagedGitError("git_effect_outcome_unknown")
            try:
                lane = self._lanes.update(
                    item.capability.lane_id,
                    expected_version=item.expected_lane_version,
                    head_sha=new_head,
                )
            except Exception as exc:
                raise ManagedGitError("git_effect_committed_lane_sync_failed") from exc
            return GitCommitReceipt(item.expected_head, new_head, staged, lane["version"], worktree)
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

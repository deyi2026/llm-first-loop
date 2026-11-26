#!/usr/bin/env python3
"""Offline operator-only Task Capability issuer for the separated Host UID.

Never expose as an LFL model tool, Web route, daemon or arbitrary signing API.
Production execution requires root-owned installed code, dedicated UID462,
Python -I -S and an issuer-owned 0600 Owner-reviewed approval file.
The premerge Host signing key/domain is never read or reused.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_ISSUER_UID = 462
_BASE = Path("/Library/LFL-TaskHostIssuer/task-authority")
_TRUSTED_SITE = Path("/Library/LFL-TaskHostIssuer/runtime/site")
_ID = re.compile(r"[A-Za-z0-9_-]{8,64}\Z")
_VERBS = {
    "project": {"read", "write", "create", "rename", "delete", "build", "git_commit"},
    "app": {"observe", "edit"},
    "service": {"status", "restart"},
}


class IssuerHoldError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise IssuerHoldError(code)


def _trusted_root_ancestor(path: Path, info: os.stat_result) -> bool:
    """Allow only macOS's privileged root:admin /Library group-write exception."""
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o002:
        return False
    if not info.st_mode & 0o020:
        return True
    # macOS admin (GID 80) is an OS-privileged group. Never extend this
    # exception to the dedicated TaskHostIssuer tree or to Linux.
    return (
        sys.platform == "darwin"
        and path == Path("/Library")
        and info.st_gid == 80
        and stat.S_IMODE(info.st_mode) == 0o775
    )


def canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise IssuerHoldError("approval_time_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IssuerHoldError("approval_time_invalid") from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "approval_time_invalid")
    return parsed.astimezone(UTC)


def _validate_approval(approval: dict[str, Any], now: datetime) -> None:
    required = {
        "schema",
        "approval_id",
        "approved_at",
        "approved_by",
        "purpose",
        "goal_id",
        "task_id",
        "owner_session_id",
        "agent_id",
        "lane_id",
        "revision",
        "authority_epoch",
        "ttl_seconds",
        "parent_lease_id",
        "resources",
    }
    require(
        set(approval) == required and approval.get("schema") == "lfl.task-approval/v1",
        "approval_schema_invalid",
    )
    require(
        isinstance(approval["approval_id"], str) and bool(_ID.fullmatch(approval["approval_id"])),
        "approval_id_invalid",
    )
    for name in (
        "approved_by",
        "purpose",
        "goal_id",
        "task_id",
        "owner_session_id",
        "agent_id",
        "lane_id",
    ):
        require(
            isinstance(approval[name], str) and 0 < len(approval[name]) <= 256,
            "approval_identity_invalid",
        )
    for name in ("revision", "authority_epoch"):
        require(type(approval[name]) is int and approval[name] > 0, "approval_revision_invalid")
    ttl = approval["ttl_seconds"]
    require(type(ttl) is int and 1 <= ttl <= 86400, "approval_ttl_invalid")
    age = now - _utc(approval["approved_at"])
    require(timedelta(seconds=-60) <= age <= timedelta(minutes=10), "approval_stale")
    parent = approval["parent_lease_id"]
    require(
        parent is None or (isinstance(parent, str) and bool(_ID.fullmatch(parent))),
        "approval_parent_invalid",
    )
    require(parent is None, "approval_parent_chain_not_yet_supported")
    resources = approval["resources"]
    require(isinstance(resources, list) and 1 <= len(resources) <= 8, "approval_resources_invalid")
    for resource in resources:
        require(
            isinstance(resource, dict) and set(resource) == {"kind", "identity", "verbs"},
            "approval_resource_schema_invalid",
        )
        kind, identity, verbs = (resource["kind"], resource["identity"], resource["verbs"])
        require(isinstance(kind, str) and kind in _VERBS, "approval_resource_kind_invalid")
        require(
            isinstance(verbs, list)
            and bool(verbs)
            and all(isinstance(v, str) for v in verbs)
            and set(verbs).issubset(_VERBS[kind]),
            "approval_resource_verbs_invalid",
        )
        require(isinstance(identity, str) and bool(identity), "approval_resource_identity_invalid")
        if kind == "project":
            require(
                os.path.isabs(identity)
                and os.path.realpath(identity) == identity
                and os.path.isdir(identity)
                and not os.path.islink(identity)
                and identity not in ("/", "/tmp", "/private/tmp", "/Users", "/home")
                and Path(identity).parent != Path("/Users")
                and Path(identity).parent != Path("/home")
                and os.path.commonpath((identity, str(_BASE))) != identity,
                "approval_project_root_unsafe",
            )
        else:
            require(
                "/" not in identity and "\\" not in identity and "*" not in identity,
                "approval_resource_identity_invalid",
            )


# Ordinary development entry: no new key, authority store or signing schema.
_LANE_REQUEST_SCHEMA = "lfl.lane-task-lease-request/v1"
_LANE_VERBS = ["read", "write", "create", "rename", "build", "git_commit"]
_LANE_DEFAULT_TTL = 4 * 3600
_LANE_MAX_TTL = 8 * 3600
_LANE_MAX_LEDGER = 16 * 1024 * 1024


def _lane_rows(path: Path, owner: int) -> list[dict[str, Any]]:
    """Bounded, read-only snapshot of existing ledger; never import repo code as Host."""
    require(path.resolve(strict=True) == path, "lane_request_ledger_path_untrusted")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        require(
            stat.S_ISREG(before.st_mode) and before.st_uid == owner
            and before.st_mode & 0o022 == 0 and 0 < before.st_size <= _LANE_MAX_LEDGER,
            "lane_request_ledger_untrusted",
        )
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(_LANE_MAX_LEDGER + 1)
        after = os.fstat(fd)
        require(
            len(raw) == before.st_size == after.st_size
            and before.st_mtime_ns == after.st_mtime_ns,
            "lane_request_ledger_changed",
        )
    finally:
        os.close(fd)
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    require(all(isinstance(row, dict) for row in rows), "lane_request_ledger_invalid")
    return rows


def _lane_git(worktree: Path, *args: str) -> str:
    """Fixed read-only Git queries; no hooks, user argv or inherited Git config."""
    result = subprocess.run(
        ["/usr/bin/git", "-c", f"safe.directory={worktree}", "-c",
         "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
         "-C", str(worktree), *args],
        env={"PATH": "/usr/bin:/bin", "HOME": "/var/empty", "LC_ALL": "C",
             "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
             "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1"},
        capture_output=True, text=True, timeout=5, check=False,
    )
    require(result.returncode == 0, "lane_request_git_unavailable")
    return result.stdout.strip()


def _lane_snapshot(
    repo: str, workspace: str, lane_id: str, task_id: str, session_id: str,
) -> dict[str, Any]:
    """Inspect one ordinary owned linked worktree and active Goal/Task/Lane."""
    require(
        all(isinstance(v, str) and bool(_ID.fullmatch(v))
            for v in (lane_id, task_id, session_id)),
        "lane_request_identity_invalid",
    )
    require(
        all(isinstance(v, str) and os.path.isabs(v) and os.path.realpath(v) == v
            and not any(ord(c) < 32 for c in v) for v in (repo, workspace)),
        "lane_request_workspace_invalid",
    )
    root, worktree = Path(repo), Path(workspace)
    require(
        worktree.parent == root / ".worktrees" and worktree.is_dir()
        and (root / ".git").is_dir() and not (root / ".git").is_symlink()
        and (worktree / ".git").is_file() and not (worktree / ".git").is_symlink(),
        "lane_request_not_linked_worktree",
    )
    owner = root.stat().st_uid
    require(owner != 0 and worktree.stat().st_uid == owner,
            "lane_request_workspace_owner_mismatch")
    audit = root / "data" / "audit"
    lanes = _lane_rows(audit / "lanes.jsonl", owner)
    matches = [row for row in lanes if row.get("lane_id") == lane_id]
    require(len(matches) == 1, "lane_request_lane_not_unique")
    lane = matches[0]
    goal_id = lane.get("goal_id")
    require(
        lane.get("status") == "active" and lane.get("owner_session_id") == session_id
        and lane.get("worktree") == workspace
        and isinstance(goal_id, str) and bool(_ID.fullmatch(goal_id))
        and type(lane.get("version")) is int and lane["version"] > 0,
        "lane_request_lane_mismatch",
    )
    goals = [row for row in _lane_rows(audit / "goals.jsonl", owner)
             if row.get("id") == goal_id]
    require(
        len(goals) == 1 and goals[0].get("status") == "active"
        and goals[0].get("session_id") == session_id,
        "lane_request_goal_mismatch",
    )
    tasks = [row for row in _lane_rows(audit / "tasks" / f"{goal_id}.jsonl", owner)
             if row.get("task_id") == task_id]
    require(
        bool(tasks) and tasks[-1].get("goal_id") == goal_id
        and tasks[-1].get("status") == "in_progress",
        "lane_request_task_inactive",
    )
    branch, head, paths = lane.get("branch"), lane.get("head_sha"), lane.get("paths")
    require(
        isinstance(branch, str) and branch.startswith(("fix/", "feat/"))
        and isinstance(head, str) and bool(re.fullmatch(r"[0-9a-f]{40}", head))
        and isinstance(paths, list) and 0 < len(paths) <= 256
        and all(isinstance(path, str) and 0 < len(path) <= 512
                and not Path(path).is_absolute() and path != "."
                and not {"..", ".git"}.intersection(Path(path).parts)
                and not any(ord(c) < 32 for c in path) for path in paths),
        "lane_request_scope_invalid",
    )
    for other in lanes:
        if other is lane or other.get("status") not in ("open", "active", "verifying", "merging"):
            continue
        other_root = other.get("worktree")
        require(
            not isinstance(other_root, str) or not other_root
            or os.path.commonpath((workspace, os.path.realpath(other_root))) not in
            (workspace, os.path.realpath(other_root)),
            "lane_request_other_lane_overlap",
        )
    common = _lane_git(worktree, "rev-parse", "--git-common-dir")
    common = os.path.realpath(os.path.join(workspace, common))
    gitdir = Path(_lane_git(worktree, "rev-parse", "--absolute-git-dir"))
    require(
        _lane_git(worktree, "rev-parse", "--show-toplevel") == workspace
        and common == str(root / ".git")
        and gitdir.parent == root / ".git" / "worktrees"
        and gitdir.resolve(strict=True) == gitdir
        and (gitdir / "index").is_file() and not (gitdir / "index").is_symlink()
        and _lane_git(worktree, "symbolic-ref", "HEAD") == f"refs/heads/{branch}"
        and _lane_git(worktree, "rev-parse", "--verify", "HEAD") == head,
        "lane_request_git_identity_or_cas_conflict",
    )
    return {"goal_id": goal_id, "lane_version": lane["version"], "branch": branch,
            "head_sha": head, "paths": sorted(paths)}


def lane_request(
    *, repo: str, workspace: str, lane_id: str, task_id: str, session_id: str,
    ttl_seconds: int = _LANE_DEFAULT_TTL, now: datetime | None = None,
) -> dict[str, Any]:
    """Unprivileged request, NOT an approval or authority grant."""
    require(type(ttl_seconds) is int and 1 <= ttl_seconds <= _LANE_MAX_TTL,
            "lane_request_ttl_invalid")
    snapshot = _lane_snapshot(repo, workspace, lane_id, task_id, session_id)
    return {
        "schema": _LANE_REQUEST_SCHEMA, "request_id": "approval-" + secrets.token_hex(16),
        "created_at": (now or datetime.now(UTC)).isoformat(),
        "repo": repo, "workspace": workspace, "lane_id": lane_id, "task_id": task_id,
        "owner_session_id": session_id, "ttl_seconds": ttl_seconds, "snapshot": snapshot,
        "resources": [{"kind": "project", "identity": workspace, "verbs": _LANE_VERBS.copy()}],
    }


def _check_lane_request(request: dict[str, Any], now: datetime) -> None:
    require(
        set(request) == {"schema", "request_id", "created_at", "repo", "workspace",
                         "lane_id", "task_id", "owner_session_id", "ttl_seconds",
                         "snapshot", "resources"}
        and request["schema"] == _LANE_REQUEST_SCHEMA
        and isinstance(request["request_id"], str) and bool(_ID.fullmatch(request["request_id"]))
        and type(request["ttl_seconds"]) is int
        and 1 <= request["ttl_seconds"] <= _LANE_MAX_TTL,
        "lane_request_schema_invalid",
    )
    require(timedelta(seconds=-60) <= now - _utc(request["created_at"]) <= timedelta(minutes=30),
            "lane_request_stale")
    require(
        request["resources"] == [{"kind": "project", "identity": request["workspace"],
                                  "verbs": _LANE_VERBS}],
        "lane_request_resources_invalid",
    )
    snapshot = _lane_snapshot(
        request["repo"], request["workspace"], request["lane_id"], request["task_id"],
        request["owner_session_id"],
    )
    require(request["snapshot"] == snapshot, "lane_request_snapshot_changed")


def _owner_confirm(request: dict[str, Any], digest: str) -> bool:
    # stdin contains the untrusted request, not the Owner's confirmation.
    # A real local controlling terminal is required; no --yes or Web approval API.
    with open("/dev/tty", encoding="utf-8") as terminal_in, open(
        "/dev/tty", "w", encoding="utf-8"
    ) as terminal_out:
        require(terminal_in.isatty() and terminal_out.isatty(), "lane_request_owner_tty_required")
        terminal_out.write(
            "\nReview ONE bounded development lease (no push/merge/release):\n"
            + json.dumps(request, ensure_ascii=True, indent=2, sort_keys=True)
            + f"\nSHA256: {digest}\nType APPROVE {digest[:12]} to authorize: "
        )
        terminal_out.flush()
        return terminal_in.readline(128).strip() == f"APPROVE {digest[:12]}"


def _owner_lane_approval(
    raw: bytes, digest: str, confirm: Callable[[dict[str, Any], str], bool],
    *, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    require(
        0 < len(raw) <= 65536 and bool(re.fullmatch(r"[0-9a-f]{64}", digest))
        and hashlib.sha256(raw).hexdigest() == digest,
        "lane_request_digest_mismatch",
    )
    request = json.loads(raw)
    require(isinstance(request, dict) and raw == canonical(request) + b"\n",
            "lane_request_encoding_invalid")
    _check_lane_request(request, clock())
    require(confirm(request, digest), "lane_request_owner_declined")
    now = clock()
    _check_lane_request(request, now)
    approval = {
        "schema": "lfl.task-approval/v1", "approval_id": request["request_id"],
        "approved_at": now.isoformat(), "approved_by": "local-owner-tty",
        "purpose": f"bounded ordinary Lane development; request_sha256={digest}",
        "goal_id": request["snapshot"]["goal_id"], "task_id": request["task_id"],
        "owner_session_id": request["owner_session_id"], "agent_id": "lane-owner",
        "lane_id": request["lane_id"], "revision": 1, "authority_epoch": 1,
        "ttl_seconds": request["ttl_seconds"], "parent_lease_id": None,
        "resources": request["resources"],
    }
    _validate_approval(approval, now)
    return approval


def _envelope(key: Any, payload: dict[str, Any], domain: bytes, eddsa: Any) -> bytes:
    public = key.public_key()
    key_id = hashlib.sha256(public.export_key(format="raw")).hexdigest()[:16]
    signature = eddsa.new(key, "rfc8032").sign(domain + b"\x00" + canonical(payload))
    return canonical(
        {
            "key_id": key_id,
            "payload": payload,
            "signature": base64.b64encode(signature).decode("ascii"),
        }
    )


def issue_receipts(
    approval: dict[str, Any],
    key: Any,
    eddsa: Any,
    *,
    now: datetime | None = None,
    lease_id: str | None = None,
) -> tuple[bytes, bytes, str]:
    """Construct ONLY the fixed Task Lease/State schemas after Owner approval."""
    clock = now or datetime.now(UTC)
    require(clock.tzinfo is not None and clock.utcoffset() is not None, "approval_time_invalid")
    clock = clock.astimezone(UTC)
    _validate_approval(approval, clock)
    ident = lease_id or "lease-" + secrets.token_hex(16)
    require(bool(_ID.fullmatch(ident)), "lease_id_invalid")
    lease = {
        "schema": "lfl.task-capability-lease/v1",
        "lease_id": ident,
        "goal_id": approval["goal_id"],
        "task_id": approval["task_id"],
        "owner_session_id": approval["owner_session_id"],
        "agent_id": approval["agent_id"],
        "lane_id": approval["lane_id"],
        "revision": approval["revision"],
        "issued_at": clock.isoformat(),
        "expires_at": (clock + timedelta(seconds=approval["ttl_seconds"])).isoformat(),
        "authority_epoch": approval["authority_epoch"],
        "parent_lease_id": approval["parent_lease_id"],
        "resources": approval["resources"],
    }
    state = {
        "schema": "lfl.task-lease-state/v1",
        "lease_id": ident,
        "lease_revision": lease["revision"],
        "lease_sha256": hashlib.sha256(canonical(lease)).hexdigest(),
        "authority_epoch": lease["authority_epoch"],
        "status": "active",
    }
    return (
        _envelope(key, lease, b"lfl.task-lease.v1", eddsa),
        _envelope(key, state, b"lfl.task-lease-state.v1", eddsa),
        ident,
    )


def revoked_state(lease_document: bytes, key: Any, eddsa: Any) -> tuple[bytes, str]:
    """Sign an irreversible revoked state for the exact existing lease."""
    try:
        lease_doc = json.loads(lease_document)
        lease = lease_doc["payload"]
    except (ValueError, KeyError, TypeError) as exc:
        raise IssuerHoldError("lease_receipt_invalid") from exc
    require(
        lease.get("schema") == "lfl.task-capability-lease/v1"
        and isinstance(lease.get("lease_id"), str)
        and bool(_ID.fullmatch(lease["lease_id"])),
        "lease_receipt_invalid",
    )
    # Do not revoke an unverified/forged lease by merely trusting its JSON.
    expected = _envelope(key, lease, b"lfl.task-lease.v1", eddsa)
    require(
        json.loads(expected)["signature"] == lease_doc.get("signature"),
        "lease_receipt_signature_invalid",
    )
    state = {
        "schema": "lfl.task-lease-state/v1",
        "lease_id": lease["lease_id"],
        "lease_revision": lease["revision"],
        "lease_sha256": hashlib.sha256(canonical(lease)).hexdigest(),
        "authority_epoch": lease["authority_epoch"],
        "status": "revoked",
    }
    return _envelope(key, state, b"lfl.task-lease-state.v1", eddsa), lease["lease_id"]


def _crypto() -> tuple[Any, Any]:
    """Only root-owned frozen runtime modules are importable in production."""
    parent = _TRUSTED_SITE
    while True:
        info = parent.lstat()
        require(
            _trusted_root_ancestor(parent, info),
            "issuer_crypto_runtime_untrusted",
        )
        if parent == parent.parent:
            break
        parent = parent.parent
    sys.path.insert(0, str(_TRUSTED_SITE))
    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa

    trusted = _TRUSTED_SITE.resolve(strict=True)
    for module in (ECC, eddsa):
        require(
            Path(module.__file__).resolve(strict=True).is_relative_to(trusted),
            "issuer_crypto_module_untrusted",
        )
    return ECC, eddsa


def _check_installed() -> None:
    require(os.getuid() == _ISSUER_UID and os.geteuid() == _ISSUER_UID, "issuer_uid_invalid")
    require(bool(sys.flags.isolated and sys.flags.no_site), "issuer_python_not_isolated")
    installed = _BASE.parent / "bin" / "task_lease_issuer.py"
    info = installed.lstat()
    parent = installed.parent
    while True:
        st = parent.lstat()
        require(
            _trusted_root_ancestor(parent, st),
            "issuer_install_parent_untrusted",
        )
        if parent == parent.parent:
            break
        parent = parent.parent
    require(
        Path(__file__).resolve(strict=True) == installed
        and stat.S_ISREG(info.st_mode)
        and info.st_uid == 0
        and info.st_mode & 0o222 == 0,
        "issuer_install_untrusted",
    )
    for path, uid, private in (
        (_BASE, 0, False),
        (_BASE / "private", _ISSUER_UID, True),
        (_BASE / "private" / "approvals", _ISSUER_UID, True),
        (_BASE / "private" / "consumed", _ISSUER_UID, True),
        (_BASE / "leases", _ISSUER_UID, False),
        (_BASE / "states", _ISSUER_UID, False),
        (_BASE / "bindings", _ISSUER_UID, False),
    ):
        st = path.lstat()
        require(
            stat.S_ISDIR(st.st_mode)
            and st.st_uid == uid
            and st.st_mode & 0o022 == 0
            and (not private or st.st_mode & 0o077 == 0),
            "issuer_directory_untrusted",
        )


def _read_owned(path: Path, *, mode_private: bool) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        require(
            stat.S_ISREG(st.st_mode)
            and st.st_uid == _ISSUER_UID
            and st.st_nlink == 1
            and (st.st_mode & (0o077 if mode_private else 0o022)) == 0
            and 0 < st.st_size <= 65536,
            "issuer_file_untrusted",
        )
        raw = os.read(fd, 65537)
        require(len(raw) == st.st_size, "issuer_file_changed")
        return raw
    finally:
        os.close(fd)


def _read_root_trust(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        require(
            stat.S_ISREG(st.st_mode)
            and st.st_uid == 0
            and st.st_nlink == 1
            and st.st_mode & 0o022 == 0
            and 0 < st.st_size <= 65536,
            "issuer_root_trust_untrusted",
        )
        raw = os.read(fd, 65537)
        require(len(raw) == st.st_size, "issuer_root_trust_changed")
        return raw
    finally:
        os.close(fd)


def _verify_public_trust(key: Any, ecc_module: Any) -> None:
    trust = json.loads(_read_root_trust(_BASE / "trust.json"))
    public_pem = _read_root_trust(_BASE / "public_key.pem")
    require(
        isinstance(trust, dict)
        and set(trust) == {"schema", "issuer_uid", "public_key_sha256"}
        and trust["schema"] == "lfl.task-authority-trust/v1"
        and type(trust["issuer_uid"]) is int
        and trust["issuer_uid"] == _ISSUER_UID
        and trust["public_key_sha256"] == hashlib.sha256(public_pem).hexdigest(),
        "issuer_public_trust_mismatch",
    )
    pub = ecc_module.import_key(public_pem)
    require(
        pub.export_key(format="raw") == key.public_key().export_key(format="raw"),
        "issuer_public_key_mismatch",
    )


def _sync_parent_directory(path: Path) -> None:
    """Persist the directory entry, not just the file contents, before success."""
    fd = os.open(
        path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        require(stat.S_ISDIR(os.fstat(fd).st_mode), "issuer_sync_parent_untrusted")
        os.fsync(fd)
    finally:
        os.close(fd)


def _create(path: Path, raw: bytes, mode: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            written = stream.write(raw)
            require(written == len(raw), "issuer_write_incomplete")
            stream.flush()
            # os.open's mode is masked by the Host process umask (normally 077).
            # Public signed receipts must remain readable by the Owner process.
            os.fchmod(fd, mode)
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    _sync_parent_directory(path)


def _publish_binding_directory(directory: Path) -> None:
    """Make only an issuer-owned, non-symlink session directory readable."""
    fd = os.open(
        directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        info = os.fstat(fd)
        require(
            stat.S_ISDIR(info.st_mode)
            and info.st_uid == _ISSUER_UID
            and info.st_mode & 0o022 == 0,
            "issuer_binding_dir_untrusted",
        )
        os.fchmod(fd, 0o755)
        os.fsync(fd)
    finally:
        os.close(fd)
    _sync_parent_directory(directory)


def _replace_state_durable(temporary: Path, state_path: Path) -> None:
    """REVOKED must not be reported until its rename survives a crash."""
    os.replace(temporary, state_path)
    _sync_parent_directory(state_path)


def _audit(event: str, lease_id: str, approval_id: str = "") -> None:
    path = _BASE / "private" / "task-issuer-audit.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        raw = (
            canonical(
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "event": event,
                    "lease_id": lease_id,
                    "approval_id": approval_id,
                }
            )
            + b"\n"
        )
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            require(written > 0, "issuer_audit_write_incomplete")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    _sync_parent_directory(path)


def _issue_approved(approval: dict[str, Any], key: Any, eddsa: Any) -> dict[str, Any]:
    approval_id = approval["approval_id"]
    lease_doc, state_doc, ident = issue_receipts(approval, key, eddsa)
    # A reviewed Owner approval is one-shot; O_EXCL is the CAS.
    _create(
        _BASE / "private" / "consumed" / f"{approval_id}.used",
        ident.encode("ascii"),
        0o600,
    )
    _audit("issue_intent", ident, approval_id)
    _create(_BASE / "leases" / f"{ident}.json", lease_doc, 0o644)
    _create(_BASE / "states" / f"{ident}.json", state_doc, 0o644)
    # Session selection is issuer-owned, never an LFL/model input.
    # Old bindings remain for audit; runtime ignores revoked/expired
    # leases and refuses multiple concurrently active candidates.
    session_digest = hashlib.sha256(
        approval["owner_session_id"].encode("utf-8")
    ).hexdigest()
    binding_dir = _BASE / "bindings" / session_digest
    with contextlib.suppress(FileExistsError):
        binding_dir.mkdir(mode=0o755)
    _publish_binding_directory(binding_dir)
    _create(
        binding_dir / f"{ident}.json",
        canonical(
            {
                "schema": "lfl.task-session-binding/v1",
                "owner_session_id": approval["owner_session_id"],
                "lease_id": ident,
            }
        ),
        0o644,
    )
    _audit("issue_published", ident, approval_id)
    return {"decision": "SIGNED", "lease_id": ident}


@contextlib.contextmanager
def _session_issue_lock(session_id: str):
    """Serialize existing issuer publications for one session, not task execution."""
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    path = _BASE / "private" / f"issue-{digest}.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == _ISSUER_UID
                and info.st_nlink == 1 and info.st_mode & 0o077 == 0,
                "issuer_session_lock_untrusted")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def _require_no_active_binding(session_id: str, now: datetime) -> None:
    """Do not turn an existing valid authorization into ambiguous bindings."""
    directory = _BASE / "bindings" / hashlib.sha256(session_id.encode()).hexdigest()
    if not os.path.lexists(directory):
        return
    info = directory.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == _ISSUER_UID
            and info.st_mode & 0o022 == 0, "issuer_binding_dir_untrusted")
    files = list(directory.iterdir())
    require(len(files) <= 256, "issuer_bindings_unavailable")
    for path in files:
        require(path.suffix == ".json" and bool(_ID.fullmatch(path.stem)),
                "issuer_binding_invalid")
        binding = json.loads(_read_owned(path, mode_private=False))
        require(binding == {"schema": "lfl.task-session-binding/v1",
                            "owner_session_id": session_id, "lease_id": path.stem},
                "issuer_binding_invalid")
        lease = json.loads(_read_owned(_BASE / "leases" / path.name, mode_private=False))["payload"]
        state = json.loads(_read_owned(_BASE / "states" / path.name, mode_private=False))["payload"]
        require(lease["lease_id"] == state["lease_id"] == path.stem
                and lease["owner_session_id"] == session_id
                and state["lease_sha256"] == hashlib.sha256(canonical(lease)).hexdigest()
                and state["lease_revision"] == lease["revision"]
                and state["authority_epoch"] == lease["authority_epoch"]
                and state["status"] in ("active", "revoked"), "issuer_binding_invalid")
        require(state["status"] == "revoked" or _utc(lease["expires_at"]) <= now,
                "issuer_session_already_authorized")


def _issue_lane_request(raw: bytes, digest: str, key: Any, eddsa: Any) -> dict[str, Any]:
    def confirm(request: dict[str, Any], fingerprint: str) -> bool:
        _require_no_active_binding(request["owner_session_id"], datetime.now(UTC))
        return _owner_confirm(request, fingerprint)

    approval = _owner_lane_approval(raw, digest, confirm)
    with _session_issue_lock(approval["owner_session_id"]):
        _require_no_active_binding(approval["owner_session_id"], datetime.now(UTC))
        # Check again under the publication lock; no silent adoption of a new Lane.
        _check_lane_request(json.loads(raw), datetime.now(UTC))
        _create(_BASE / "private" / "approvals" / f"{approval['approval_id']}.json",
                canonical(approval), 0o600)
        return _issue_approved(approval, key, eddsa)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("keygen", "issue", "revoke", "lane-request", "issue-lane"), required=True)
    parser.add_argument("--approval-id", default="")
    parser.add_argument("--lease-id", default="")
    parser.add_argument("--repo", default="")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--lane-id", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--ttl-seconds", type=int, default=_LANE_DEFAULT_TTL)
    parser.add_argument("--request-sha256", default="")
    args = parser.parse_args(argv)
    try:
        if args.mode == "lane-request":
            require(os.getuid() == os.geteuid() and os.getuid() not in (0, _ISSUER_UID),
                    "lane_request_requires_unprivileged_owner")
            request = lane_request(
                repo=args.repo, workspace=args.workspace, lane_id=args.lane_id,
                task_id=args.task_id, session_id=args.session_id, ttl_seconds=args.ttl_seconds,
            )
            print(canonical(request).decode("utf-8"))
            return 0
        _check_installed()
        ecc_module, eddsa = _crypto()
        key_path = _BASE / "private" / "task-ed25519.pem"
        if args.mode == "keygen":
            require(not key_path.exists(), "issuer_key_already_exists")
            key = ecc_module.generate(curve="Ed25519")
            _create(key_path, key.export_key(format="PEM").encode(), 0o600)
            _create(
                _BASE / "private" / "task-public.pending.pem",
                key.public_key().export_key(format="PEM").encode(),
                0o600,
            )
            result = {"decision": "KEY_CREATED", "public_pending": True}
        else:
            key = ecc_module.import_key(_read_owned(key_path, mode_private=True))
            _verify_public_trust(key, ecc_module)
            if args.mode == "issue":
                require(bool(_ID.fullmatch(args.approval_id)), "approval_id_invalid")
                approval_raw = _read_owned(
                    _BASE / "private" / "approvals" / f"{args.approval_id}.json",
                    mode_private=True,
                )
                approval = json.loads(approval_raw)
                require(
                    isinstance(approval, dict) and approval.get("approval_id") == args.approval_id,
                    "approval_id_mismatch",
                )
                _validate_approval(approval, datetime.now(UTC))
                with _session_issue_lock(approval["owner_session_id"]):
                    result = _issue_approved(approval, key, eddsa)
            elif args.mode == "issue-lane":
                require(not args.approval_id and not args.lease_id and not args.repo
                        and not args.workspace and not args.lane_id and not args.task_id
                        and not args.session_id and args.ttl_seconds == _LANE_DEFAULT_TTL,
                        "lane_request_arguments_invalid")
                result = _issue_lane_request(sys.stdin.buffer.read(65537),
                                             args.request_sha256, key, eddsa)
            else:
                require(bool(_ID.fullmatch(args.lease_id)), "lease_id_invalid")
                lease_doc = _read_owned(
                    _BASE / "leases" / f"{args.lease_id}.json", mode_private=False
                )
                state_doc, ident = revoked_state(lease_doc, key, eddsa)
                state_path = _BASE / "states" / f"{ident}.json"
                existing = _read_owned(state_path, mode_private=False)
                require(
                    json.loads(existing)["payload"].get("status") == "active",
                    "issuer_lease_not_active",
                )
                _audit("revoke_intent", ident)
                temporary = _BASE / "states" / (f".{ident}.{secrets.token_hex(8)}.tmp")
                _create(temporary, state_doc, 0o644)
                _replace_state_durable(temporary, state_path)
                _audit("revoke_published", ident)
                result = {"decision": "REVOKED", "lease_id": ident}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (IssuerHoldError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        code = str(exc) if isinstance(exc, IssuerHoldError) else type(exc).__name__
        print(json.dumps({"decision": "HOLD", "reason": code}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

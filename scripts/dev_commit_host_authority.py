#!/usr/bin/env python3
"""Frozen, independent Host authority for one-use LOCAL development commits.

Install root-owned outside the repository; execute with Python -I -S as the
dedicated Host issuer UID. Never use the premerge or Task Lease signing key.
Only a root-owned, exact-tree operator approval may mint a one-use grant.
Neither an LLM message nor a development test receipt grants authority.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any

BASE = Path("/Library/Application Support/LFL-HostIssuer")
HOST_UID = 462
WEB_UID = 501
DOMAIN = "lfl.dev_commit.grant.v1"
REPO = "deyi2026/llm-first-loop"
SITE = Path("/Library/Application Support/LFL-DualAgent/runtime/site")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
GRANT_ID = re.compile(r"[a-z0-9][a-z0-9-]{15,63}\Z")
GOAL_ID = re.compile(r"GOAL-[A-Za-z0-9-]{8,80}\Z")
REQ_ID = re.compile(r"REQ-[A-Za-z0-9-]{2,80}\Z")
DENIED_PREFIXES = (
    ".github/", ".githooks/", "scripts/", "tests/guards/",
    "docs/governance/", "src/llm_loop/tools/review_host_admission.py",
    "src/llm_loop/introspection/goal_gates.py",
)


def _protected_path(path: str) -> bool:
    # macOS case-insensitive volumes can map a differently-cased Git path
    # onto the same working-tree file. Reject aliases conservatively.
    normalized = unicodedata.normalize("NFC", path).casefold()
    return normalized.startswith(DENIED_PREFIXES)


class HostHoldError(Exception):
    """Fail closed; never mint or consume on an uncertain input."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise HostHoldError(reason)


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        require(n > 0, "host_write_incomplete")
        view = view[n:]


def _crypto() -> tuple[Any, Any]:
    site = SITE.lstat()
    require(stat.S_ISDIR(site.st_mode) and site.st_uid == 0
            and site.st_mode & 0o022 == 0, "trusted_crypto_site_unavailable")
    sys.path.insert(0, str(SITE))
    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa
    root = SITE.resolve(strict=True)
    for module in (ECC, eddsa):
        require(Path(module.__file__).resolve(strict=True).is_relative_to(root),
                "crypto_module_outside_trusted_site")
    return ECC, eddsa


def secure_file(path: Path, owner: int, *, private: bool = False,
                max_bytes: int = 262144) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_uid == owner
                and st.st_mode & 0o022 == 0
                and (not private or st.st_mode & 0o077 == 0)
                and 0 < st.st_size <= max_bytes, "authority_file_untrusted")
        raw = os.read(fd, max_bytes + 1)
        require(len(raw) == st.st_size, "authority_file_incomplete")
        return raw
    finally:
        os.close(fd)


def secure_dir(path: Path, owner: int, *, private: bool = False) -> None:
    st = path.lstat()
    require(stat.S_ISDIR(st.st_mode) and st.st_uid == owner
            and st.st_mode & 0o022 == 0
            and (not private or st.st_mode & 0o077 == 0),
            "authority_directory_untrusted")


def json_object(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeError, ValueError) as exc:
        raise HostHoldError("authority_json_invalid") from exc
    require(type(value) is dict, "authority_json_invalid")
    return value


def _git(root: Path, *args: str) -> str:
    require("\n" not in str(root) and "\r" not in str(root),
            "host_git_path_untrusted")
    result = subprocess.run(
        ["/usr/bin/git", "-c", f"safe.directory={root}", "-C", str(root), *args],
        capture_output=True, text=True, timeout=15, check=False,
        env={"PATH": "/usr/bin:/bin", "HOME": "/var/empty",
             "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
             "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"},
    )
    require(result.returncode == 0, "host_git_unavailable")
    return result.stdout.strip()


def _verified_protected_tree_unchanged(
    *, base: str, candidate: str, git_cmd: list[str], env: dict[str, str]
) -> None:
    """Compare protected Git entries using hash-verified object bytes.

    The developer owns the alternate object store. Git plumbing can read a
    corrupted loose object under a *different* OID without rejecting it, so
    `git diff base candidate` alone is not a trusted protection check. Verify
    the base commit and only the tree ancestors needed for protected paths.
    No owner-controlled object is trusted after the bytes have been read.
    """
    objects: dict[tuple[str, str], bytes] = {}

    def read_object(kind: str, oid: str) -> bytes:
        require(bool(HEX40.fullmatch(oid)), "host_git_object_invalid")
        key = (kind, oid)
        if key not in objects:
            result = subprocess.run(
                [*git_cmd, "cat-file", kind, oid], capture_output=True,
                timeout=15, check=False, env=env,
            )
            raw = result.stdout
            require(result.returncode == 0 and len(raw) <= 16 * 1024 * 1024,
                    "host_git_object_unavailable")
            header = f"{kind} {len(raw)}\0".encode("ascii")
            require(hashlib.sha1(header + raw).hexdigest() == oid,
                    "host_git_object_integrity_failed")
            objects[key] = raw
        return objects[key]

    commit = read_object("commit", base)
    match = re.match(rb"tree ([0-9a-f]{40})\n", commit)
    require(match is not None, "host_git_base_commit_invalid")
    assert match is not None
    base_tree = match.group(1).decode("ascii")

    def entries(oid: str) -> list[tuple[str, str, str]]:
        raw = read_object("tree", oid)
        result: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        offset = 0
        while offset < len(raw):
            space = raw.find(b" ", offset)
            end = raw.find(b"\0", space + 1)
            require(space > offset and end > space + 1 and end + 21 <= len(raw),
                    "host_git_tree_invalid")
            try:
                mode = raw[offset:space].decode("ascii")
                name = raw[space + 1:end].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HostHoldError("host_git_tree_invalid") from exc
            require(bool(name) and "/" not in name and "\n" not in name
                    and "\r" not in name, "host_git_tree_invalid")
            normalized = unicodedata.normalize("NFC", name).casefold()
            require(normalized not in seen, "host_git_tree_alias_ambiguous")
            seen.add(normalized)
            result.append((name, mode, raw[end + 1:end + 21].hex()))
            offset = end + 21
        return result

    def verify_subtree(entry: tuple[str, str, str] | None) -> None:
        if entry is None:
            return
        _, mode, oid = entry
        if mode in ("40000", "040000"):
            for name, child_mode, child_oid in entries(oid):
                verify_subtree((name, child_mode, child_oid))
        else:
            require(mode in ("100644", "100755", "120000"),
                    "host_git_protected_mode_invalid")
            read_object("blob", oid)

    def entry_at(tree_oid: str, path: str) -> tuple[str, str, str] | None:
        parts = path.rstrip("/").split("/")
        for index, component in enumerate(parts):
            aliases = [entry for entry in entries(tree_oid)
                       if unicodedata.normalize("NFC", entry[0]).casefold()
                       == component.casefold()]
            require(len(aliases) <= 1, "host_git_tree_alias_ambiguous")
            if not aliases:
                return None
            name, mode, oid = aliases[0]
            if index == len(parts) - 1:
                return name, mode, oid
            if mode not in ("40000", "040000"):
                return None
            tree_oid = oid
        return None

    for protected in DENIED_PREFIXES:
        old_entry = entry_at(base_tree, protected)
        new_entry = entry_at(candidate, protected)
        require(old_entry == new_entry,
                "protected_change_requires_full_r9")
        # Identical tree OIDs are not enough: an owner can replace a loose
        # subtree or blob under its old filename. Verify the full protected
        # object closure, not only the root/ancestor trees.
        verify_subtree(old_entry)


def _staged_tree_readonly(root: Path, *, owner_uid: int,
                          base: str | None = None) -> tuple[str, list[str]]:
    """Derive staged paths and tree from one Host-private index snapshot.

    `git write-tree` creates `.git/index.lock` even for a read-only inspection.
    The independent Host UID must never need write access to the developer's
    index or object store. Use a private copy and a disposable object store,
    with the repository's objects available as read-only alternates.
    """
    # `--git-path index` canonicalizes a symlink on macOS, hiding it from
    # O_NOFOLLOW. Derive the literal index entry from the private Git dir.
    dotgit = root / ".git"
    dotgit_stat = dotgit.lstat()
    require(dotgit_stat.st_uid == owner_uid and dotgit_stat.st_mode & 0o022 == 0
            and (stat.S_ISDIR(dotgit_stat.st_mode)
                 or stat.S_ISREG(dotgit_stat.st_mode)),
            "host_git_metadata_untrusted")
    git_dir = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-dir"))
    common = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    require(git_dir.is_absolute() and common.is_absolute()
            and git_dir.is_relative_to(common), "host_git_metadata_untrusted")
    directories = [common]
    for part in git_dir.relative_to(common).parts:
        directories.append(directories[-1] / part)
    for directory in directories:
        st = directory.lstat()
        require(stat.S_ISDIR(st.st_mode) and st.st_uid == owner_uid
                and st.st_mode & 0o022 == 0, "host_git_metadata_untrusted")
    index = git_dir / "index"
    objects = common / "objects"
    require(index.is_absolute() and objects.is_absolute()
            and ":" not in str(objects), "host_git_paths_untrusted")
    object_stat = objects.lstat()
    info = objects / "info"
    if os.path.lexists(info):
        info_stat = info.lstat()
        require(stat.S_ISDIR(info_stat.st_mode) and info_stat.st_uid == owner_uid
                and info_stat.st_mode & 0o022 == 0,
                "host_git_objects_untrusted")
    require(stat.S_ISDIR(object_stat.st_mode) and object_stat.st_uid == owner_uid
            and object_stat.st_mode & 0o022 == 0
            and not os.path.lexists(info / "alternates"),
            "host_git_objects_untrusted")
    if base is not None:
        require(bool(HEX40.fullmatch(base)), "main_base_changed")
    fd = os.open(index, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == owner_uid
                and before.st_mode & 0o022 == 0
                and 0 < before.st_size <= 64 * 1024 * 1024,
                "host_git_index_untrusted")
        # Keep the root fixed, not inherited from caller-controlled TMPDIR.
        # /tmp resolves to /private/tmp on macOS and exists on Linux; the
        # Host-private directory itself is created mode 0700 by tempfile.
        with tempfile.TemporaryDirectory(
            prefix="lfl-dev-host-index-", dir="/tmp"
        ) as directory:
            temporary = Path(directory)
            with (temporary / "index").open("xb") as output:
                remaining = before.st_size
                copied_digest = hashlib.sha256()
                while remaining:
                    chunk = os.read(fd, min(1024 * 1024, remaining))
                    require(bool(chunk), "host_git_index_changed")
                    output.write(chunk)
                    copied_digest.update(chunk)
                    remaining -= len(chunk)
                require(not os.read(fd, 1), "host_git_index_changed")
            (temporary / "objects").mkdir(mode=0o700)
            env = {
                "PATH": "/usr/bin:/bin", "HOME": "/var/empty",
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                "LC_ALL": "C", "GIT_INDEX_FILE": str(temporary / "index"),
                "GIT_OBJECT_DIRECTORY": str(temporary / "objects"),
                "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(objects),
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_NO_LAZY_FETCH": "1",
            }
            git_cmd = ["/usr/bin/git", "-c", f"safe.directory={root}",
                       "-C", str(root)]
            def diff_paths(*diff_args: str) -> list[str]:
                result = subprocess.run(
                    [*git_cmd, "diff", "--name-only", "-z", "--no-renames",
                     *diff_args],
                    capture_output=True, timeout=15, check=False, env=env,
                )
                require(result.returncode == 0, "host_git_paths_unavailable")
                raw = result.stdout
                require(len(raw) <= 1024 * 1024 and (not raw or raw.endswith(b"\0")),
                        "host_git_paths_invalid")
                try:
                    paths = [p.decode("utf-8") for p in raw[:-1].split(b"\0")] if raw else []
                except UnicodeDecodeError as exc:
                    raise HostHoldError("host_git_paths_invalid") from exc
                require(all(paths) and len(set(paths)) == len(paths)
                        and not any("\n" in p or "\r" in p for p in paths),
                        "host_git_paths_invalid")
                return paths

            paths = diff_paths("--cached")
            require(bool(paths), "host_git_paths_invalid")
            result = subprocess.run(
                [*git_cmd, "write-tree"],
                capture_output=True, text=True, timeout=15, check=False, env=env,
            )
            require(result.returncode == 0, "host_git_tree_unavailable")
            tree = result.stdout.strip()
            require(bool(HEX40.fullmatch(tree)), "host_git_tree_invalid")
            if base is not None:
                # Read owner-controlled Git objects only after validating
                # their content hashes. Comparing just Git's diff output is
                # insufficient: Git accepts a replaced loose object by name.
                _verified_protected_tree_unchanged(
                    base=base, candidate=tree, git_cmd=git_cmd, env=env,
                )
            after = os.fstat(fd)
            current = os.stat(index, follow_symlinks=False)
            os.lseek(fd, 0, os.SEEK_SET)
            verified_digest = hashlib.sha256()
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                verified_digest.update(chunk)
            def fingerprint(st: os.stat_result) -> tuple[int, int, int, int, int]:
                return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns,
                        st.st_ctime_ns)
            require(fingerprint(before) == fingerprint(after) == fingerprint(current),
                    "host_git_index_changed")
            require(copied_digest.digest() == verified_digest.digest(),
                    "host_git_index_changed")
            return tree, paths
    finally:
        os.close(fd)


def inspect_repo(root: Path, *, goal: str, req: str, base: str,
                 message_sha256: str, owner_uid: int = WEB_UID) -> dict[str, Any]:
    """Re-derive context from Git and the independent Lane ledger."""
    require(bool(GOAL_ID.fullmatch(goal)) and bool(REQ_ID.fullmatch(req))
            and bool(HEX40.fullmatch(base))
            and bool(HEX64.fullmatch(message_sha256)), "commit_request_invalid")
    root = root.resolve(strict=True)
    st = root.lstat()
    require(stat.S_ISDIR(st.st_mode) and st.st_uid == owner_uid,
            "worktree_owner_untrusted")
    origin = _git(root, "remote", "get-url", "origin")
    require(origin in (
        f"git@github.com:{REPO}.git", f"https://github.com/{REPO}.git",
        f"https://github.com/{REPO}", f"ssh://git@github.com/{REPO}.git",
    ), "repository_origin_untrusted")
    branch = _git(root, "symbolic-ref", "--short", "HEAD")
    require(branch.startswith("feat/") or branch.startswith("fix/"),
            "development_branch_required")
    head = _git(root, "rev-parse", "HEAD")
    require(bool(HEX40.fullmatch(head))
            and _git(root, "rev-parse", "refs/remotes/origin/main") == base,
            "main_base_changed")
    require(_git(root, "merge-base", base, head) == base,
            "development_base_not_ancestor")
    require(not _git(root, "diff", "--name-only")
            and not _git(root, "ls-files", "--others", "--exclude-standard"),
            "worktree_not_staged_clean")
    tree, paths = _staged_tree_readonly(root, owner_uid=owner_uid, base=base)
    require(bool(paths) and not any(
        _protected_path(path) for path in paths
    ), "protected_change_requires_full_r9")
    require(_git(root, "symbolic-ref", "--short", "HEAD") == branch
            and _git(root, "rev-parse", "HEAD") == head
            and _git(root, "rev-parse", "refs/remotes/origin/main") == base
            and _git(root, "remote", "get-url", "origin") == origin,
            "host_git_refs_changed")
    common = Path(_git(root, "rev-parse", "--path-format=absolute",
                       "--git-common-dir")).resolve()
    audit = common.parent / "data" / "audit"
    secure_dir(audit, owner_uid)
    raw = secure_file(audit / "lanes.jsonl", owner_uid, max_bytes=4 * 1024 * 1024)
    require(raw.endswith(b"\n"), "lane_ledger_truncated")
    lanes = [json_object(line) for line in raw.splitlines() if line.strip()]
    mine = [
        row for row in lanes
        if row.get("goal_id") == goal and row.get("branch") == branch
        and row.get("worktree") == str(root)
        and row.get("status") in ("open", "active")
    ]
    require(len(mine) == 1, "lane_identity_missing_or_ambiguous")
    lane = mine[0]
    require(lane.get("base_main_sha") == base
            and set(paths) <= set(lane.get("paths") or []),
            "lane_scope_or_base_changed")
    for row in lanes:
        if row.get("lane_id") == lane.get("lane_id") or row.get("status") not in ("open", "active"):
            continue
        require(not set(paths) & set(row.get("paths") or []),
                "cross_lane_path_conflict")
    return {
        "repo": REPO, "worktree": str(root), "branch": branch,
        "head": head, "tree": tree, "base": base,
        "goal": goal, "req": req, "lane_id": lane["lane_id"],
        "lane_version": lane["version"], "message_sha256": message_sha256,
        "paths": sorted(paths),
    }


def _sign(payload: dict[str, Any], private_pem: bytes) -> dict[str, Any]:
    ecc, eddsa = _crypto()
    key = ecc.import_key(private_pem)
    require(key.curve == "Ed25519" and key.has_private(), "dev_key_invalid")
    public = key.public_key().export_key(format="PEM")
    return {
        "payload": payload,
        "key_id": hashlib.sha256(public.encode()).hexdigest()[:16],
        "signature_ed25519": base64.b64encode(
            eddsa.new(key, "rfc8032").sign(canonical(payload))
        ).decode(),
    }


def _verify(envelope: dict[str, Any], public_pem: bytes) -> dict[str, Any]:
    ecc, eddsa = _crypto()
    key = ecc.import_key(public_pem)
    require(key.curve == "Ed25519" and not key.has_private(), "dev_public_key_invalid")
    expected_id = hashlib.sha256(key.export_key(format="PEM").encode()).hexdigest()[:16]
    require(envelope.get("key_id") == expected_id, "dev_key_id_mismatch")
    payload = envelope.get("payload")
    require(type(payload) is dict, "dev_payload_invalid")
    try:
        signature = base64.b64decode(envelope["signature_ed25519"], validate=True)
        eddsa.new(key, "rfc8032").verify(canonical(payload), signature)
    except (ValueError, KeyError, TypeError) as exc:
        raise HostHoldError("dev_grant_signature_invalid") from exc
    assert isinstance(payload, dict)
    return payload


def _ledger_transaction(path: Path, event: dict[str, Any], *,
                        grant_id: str, approval_id: str, expected_digest: str = "",
                        ledger_owner: int = HOST_UID) -> None:
    """Host-owned flock+fsync; missing, corrupt, replayed ledger => HOLD."""
    fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_uid == ledger_owner
                and st.st_mode & 0o077 == 0 and st.st_size <= 4 * 1024 * 1024,
                "dev_ledger_untrusted")
        fcntl.flock(fd, fcntl.LOCK_EX)
        data = os.read(fd, 4 * 1024 * 1024 + 1)
        require(not data or data.endswith(b"\n"), "dev_ledger_truncated")
        rows = [json_object(line) for line in data.splitlines() if line.strip()]
        prior = [row for row in rows if row.get("grant_id") == grant_id
                 or row.get("approval_id") == approval_id]
        if event["event"] == "issued":
            require(not prior, "dev_approval_already_used")
        else:
            issued = [row for row in prior if row.get("event") == "issued"]
            require(len(issued) == 1 and issued[0].get("digest") == expected_digest,
                    "dev_grant_not_issued")
            require(not any(row.get("event") == "consumed" for row in prior),
                    "dev_grant_replayed")
        os.lseek(fd, 0, os.SEEK_END)
        write_all(fd, canonical(event) + b"\n")
        os.fsync(fd)
    finally:
        os.close(fd)


def issue_grant(*, approval: dict[str, Any], context: dict[str, Any],
                private_pem: bytes, ledger: Path, receipts: Path,
                now: float, ledger_owner: int = HOST_UID) -> dict[str, Any]:
    require(approval.get("schema") == "lfl.dev_commit.approval.v1"
            and type(approval.get("context")) is dict
            and approval["context"] == context
            and type(approval.get("expires_at")) in (float, int)
            and now < approval["expires_at"] <= now + 600,
            "owner_approval_invalid_or_stale")
    grant_id = approval.get("approval_id")
    require(isinstance(grant_id, str) and bool(GRANT_ID.fullmatch(grant_id)),
            "approval_id_invalid")
    assert isinstance(grant_id, str)
    payload = {
        "domain": DOMAIN, "grant_id": grant_id, "context": context,
        "issued_at": now, "expires_at": min(approval["expires_at"], now + 300),
    }
    envelope = _sign(payload, private_pem)
    digest = hashlib.sha256(canonical(envelope)).hexdigest()
    _ledger_transaction(ledger, {
        "event": "issued", "grant_id": grant_id, "approval_id": grant_id,
        "digest": digest, "ts": now,
    }, grant_id=grant_id, approval_id=grant_id, ledger_owner=ledger_owner)
    target = receipts / f"{grant_id}.json"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        write_all(fd, canonical(envelope) + b"\n")
        os.fsync(fd)
    finally:
        os.close(fd)
    return {"decision": "SIGNED", "grant_id": grant_id, "expires_at": payload["expires_at"]}


def consume_grant(*, grant_id: str, context: dict[str, Any],
                  receipt: dict[str, Any], envelope: dict[str, Any],
                  public_pem: bytes, ledger: Path, now: float,
                  ledger_owner: int = HOST_UID) -> dict[str, Any]:
    require(bool(GRANT_ID.fullmatch(grant_id)), "grant_id_invalid")
    payload = _verify(envelope, public_pem)
    require(payload.get("domain") == DOMAIN
            and payload.get("grant_id") == grant_id
            and payload.get("context") == context
            and type(payload.get("issued_at")) in (float, int)
            and type(payload.get("expires_at")) in (float, int)
            and payload["issued_at"] <= now < payload["expires_at"]
            and payload["expires_at"] - payload["issued_at"] <= 300,
            "dev_grant_context_or_expiry_invalid")
    require(
        receipt.get("schema") == "lfl.dev_gate.v1"
        and receipt.get("status") == "PASS"
        and receipt.get("release_qualified") is False
        and receipt.get("goal_id") == context["goal"]
        and receipt.get("req_id") == context["req"]
        and receipt.get("base") == context["base"]
        and receipt.get("head") == context["head"]
        and receipt.get("staged_tree") == context["tree"]
        and not receipt.get("blockers")
        and bool(receipt.get("selected_tests"))
        and bool(HEX64.fullmatch(str(receipt.get("input_fingerprint") or "")))
        and type(receipt.get("completed_at")) in (float, int)
        and 0 <= now - receipt["completed_at"] <= 120
        and bool(receipt.get("checks"))
        and all(
            type(c) is dict and c.get("exit_code") == 0
            and type(c.get("argv")) is list
            for c in receipt["checks"]
        )
        and {"pytest", *(
            ("ruff", "pyright")
            if any(str(path).endswith(".py") for path in context["paths"])
            else ()
        )} <= {
            str(check["argv"][1])
            for check in receipt["checks"]
            if len(check["argv"]) >= 2 and check["argv"][0] == "-m"
        },
        "dev_test_receipt_invalid",
    )
    digest = hashlib.sha256(canonical(envelope)).hexdigest()
    _ledger_transaction(ledger, {
        "event": "consumed", "grant_id": grant_id, "approval_id": grant_id,
        "digest": digest, "ts": now,
    }, grant_id=grant_id, approval_id=grant_id, expected_digest=digest,
       ledger_owner=ledger_owner)
    return {"decision": "CONSUMED", "grant_id": grant_id, "tree": context["tree"],
            "release_qualified": False}


def _require_installed() -> None:
    require(os.geteuid() == HOST_UID and bool(sys.flags.isolated and sys.flags.no_site),
            "independent_host_runtime_required")
    binary = Path(__file__).resolve(strict=True)
    secure_dir(BASE, 0)
    secure_dir(binary.parent, 0)
    secure_file(binary, 0, max_bytes=1024 * 1024)
    secure_dir(BASE / "private", HOST_UID, private=True)
    # Existing premerge HostIssuer owns the shared receipts parent as UID462.
    # Never chown it to root or break the already-installed issuer.
    secure_dir(BASE / "receipts", HOST_UID)
    secure_dir(BASE / "receipts" / "dev-commit", HOST_UID)
    secure_dir(BASE / "approvals", 0)
    secure_dir(BASE / "approvals" / "dev-commit", 0)
    secure_dir(BASE / "config", 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("keygen", "inspect", "issue", "consume"))
    parser.add_argument("--worktree", type=Path)
    parser.add_argument("--goal")
    parser.add_argument("--req")
    parser.add_argument("--base")
    parser.add_argument("--message-sha256")
    parser.add_argument("--approval-id")
    parser.add_argument("--grant-id")
    args = parser.parse_args()
    try:
        _require_installed()
        private = BASE / "private"
        receipts = BASE / "receipts" / "dev-commit"
        ledger = private / "dev-commit-ledger.jsonl"
        if args.mode == "keygen":
            ecc, _ = _crypto()
            key = ecc.generate(curve="Ed25519")
            for name, data in (
                ("dev-commit-ed25519.pem", key.export_key(format="PEM").encode()),
                ("dev-commit-ed25519.pub.pem",
                 key.public_key().export_key(format="PEM").encode()),
                ("dev-commit-ledger.jsonl", b""),
            ):
                fd = os.open(private / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                try:
                    write_all(fd, data)
                    os.fsync(fd)
                finally:
                    os.close(fd)
            print(json.dumps({"decision": "KEYGEN_COMPLETE", "activated": False}))
            return 0
        require(all((args.worktree, args.goal, args.req, args.base,
                     args.message_sha256)), "required_context_missing")
        context = inspect_repo(
            args.worktree, goal=args.goal, req=args.req, base=args.base,
            message_sha256=args.message_sha256,
        )
        if args.mode == "inspect":
            print(json.dumps({"decision": "INSPECT_ONLY", "context": context,
                              "release_qualified": False}, sort_keys=True))
            return 0
        config = json_object(secure_file(BASE / "config" / "dev-commit-enabled.json", 0))
        require(config == {"schema": "lfl.dev_commit.activation.v1", "enabled": True,
                           "host_uid": HOST_UID, "repo": REPO},
                "dev_commit_not_activated")
        if args.mode == "issue":
            require(bool(args.approval_id) and bool(GRANT_ID.fullmatch(args.approval_id)),
                    "approval_id_invalid")
            approval = json_object(secure_file(
                BASE / "approvals" / "dev-commit" / f"{args.approval_id}.json", 0
            ))
            result = issue_grant(
                approval=approval, context=context,
                private_pem=secure_file(private / "dev-commit-ed25519.pem",
                                        HOST_UID, private=True),
                ledger=ledger, receipts=receipts, now=time.time(),
            )
        else:
            require(bool(args.grant_id) and bool(GRANT_ID.fullmatch(args.grant_id)),
                    "grant_id_invalid")
            raw = sys.stdin.buffer.read(262145)
            require(len(raw) <= 262144, "dev_receipt_oversize")
            receipt = json_object(raw)
            envelope = json_object(secure_file(
                receipts / f"{args.grant_id}.json", HOST_UID, private=True
            ))
            result = consume_grant(
                grant_id=args.grant_id, context=context, receipt=receipt,
                envelope=envelope,
                public_pem=secure_file(private / "dev-commit-ed25519.pub.pem",
                                       HOST_UID, private=True),
                ledger=ledger, now=time.time(),
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (HostHoldError, OSError, ValueError, KeyError, TypeError,
            subprocess.TimeoutExpired) as exc:
        print(json.dumps({"decision": "HOLD", "reason": str(exc),
                          "release_qualified": False}), file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())

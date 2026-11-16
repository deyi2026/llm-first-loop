#!/usr/bin/env python3
"""Offline operator-only Ed25519 issuer for the read-only Host premerge gate.

Install this immutable script outside the repository under a separate OS UID.
No network listener, Web route, model tool, arbitrary payload-signing API, or
private key in the repository. Evidence receipts must be owned by the issuer.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_ISSUER_UID = 462  # Existing dedicated macOS _lfl_dual_witness account.
_WEB_UID = 501
_SHA = re.compile(r"^[0-9a-f]{40}$")
_HEX256 = re.compile(r"^[0-9a-f]{64}$")
_BASE = Path("/Library/Application Support/LFL-HostIssuer")
_REPO = "deyi2026/llm-first-loop"
_TRUSTED_SITE = "/Library/Application Support/LFL-DualAgent/runtime/site"


class IssuerHoldError(Exception):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise IssuerHoldError(reason)


def crypto() -> tuple[Any, Any]:
    # The deployed interpreter uses -I -S. Only the root-owned frozen runtime
    # site is added; never import executable code from the mutable worktree.
    site = Path(_TRUSTED_SITE)
    st = site.lstat()
    require(stat.S_ISDIR(st.st_mode) and st.st_uid == 0
            and st.st_mode & 0o022 == 0, "crypto_runtime_untrusted")
    if _TRUSTED_SITE not in sys.path:
        sys.path.insert(0, _TRUSTED_SITE)
    before = site.lstat()
    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa
    after = site.lstat()
    require((before.st_dev, before.st_ino, before.st_uid) ==
            (after.st_dev, after.st_ino, after.st_uid),
            "crypto_runtime_changed")
    # The installed CLI MUST use Python -I -S; in that mode only this
    # root-owned site is on the additional import path. Revalidate the
    # imported module locations after import, not only the site directory.
    if sys.flags.isolated and sys.flags.no_site:
        root = site.resolve(strict=True)
        for module in (ECC, eddsa):
            require(Path(module.__file__).resolve(strict=True).is_relative_to(root),
                    "crypto_module_outside_trusted_site")
    return ECC, eddsa


def secure_bytes(path: Path, owner: int, *, max_bytes: int = 1024 * 1024) -> bytes:
    """Read a non-symlink, owner-only regular file via fixed descriptor."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_uid == owner, "evidence_owner_invalid")
        require(st.st_mode & 0o077 == 0 and 0 < st.st_size <= max_bytes,
                "evidence_mode_or_size_invalid")
        data = os.read(fd, max_bytes + 1)
        require(len(data) == st.st_size, "evidence_read_incomplete")
        return data
    finally:
        os.close(fd)


def public_bytes(path: Path, owner: int, *, max_bytes: int = 4 * 1024 * 1024) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_uid == owner, "authority_file_owner_invalid")
        require(st.st_mode & 0o022 == 0 and st.st_size <= max_bytes,
                "authority_file_writable_or_large")
        data = os.read(fd, max_bytes + 1)
        require(len(data) == st.st_size, "authority_file_incomplete")
        return data
    finally:
        os.close(fd)


def read_json(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise IssuerHoldError(label + "_malformed") from exc
    require(isinstance(value, dict), label + "_invalid")
    return value


def read_rows(path: Path, owner: int) -> list[dict[str, Any]]:
    raw = public_bytes(path, owner)
    rows = []
    for line in raw.splitlines():
        if line.strip():
            rows.append(read_json(line, "audit_row"))
    return rows


def fetch_json(url: str) -> dict[str, Any]:
    require(url.startswith("https://api.github.com/repos/" + _REPO + "/")
            or url == "http://127.0.0.1:8903/api/v1/coordination/board",
            "url_not_allowlisted")
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "lfl-host-offline-issuer",
    })
    try:
        with urllib.request.urlopen(request, timeout=7) as response:
            require(response.geturl() == url, "redirect_forbidden")
            raw = response.read(1024 * 1024 + 1)
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise IssuerHoldError("authority_unavailable") from exc
    require(len(raw) <= 1024 * 1024, "authority_response_oversize")
    return read_json(raw, "authority_response")


def local_state(lane_id: str, main: str, candidate: str, *,
                audit_dir: Path, owner: int = _WEB_UID,
                board: dict[str, Any] | None = None) -> tuple[dict, dict]:
    audit_st = audit_dir.lstat()
    require(stat.S_ISDIR(audit_st.st_mode) and audit_st.st_uid == owner
            and audit_st.st_mode & 0o022 == 0, "audit_dir_untrusted")
    board = board if board is not None else fetch_json(
        "http://127.0.0.1:8903/api/v1/coordination/board")
    require(board.get("main_head") == main and board.get("degraded") is not True,
            "board_main_untrusted")
    lane_rows = read_rows(audit_dir / "lanes.jsonl", owner)
    queue_rows = read_rows(audit_dir / "merge_queue.jsonl", owner)
    lane = next((x for x in reversed(lane_rows) if x.get("lane_id") == lane_id), None)
    queue = next((x for x in reversed(queue_rows) if x.get("lane_id") == lane_id), None)
    shown = next((x for x in board.get("lanes", []) if x.get("lane_id") == lane_id), None)
    require(isinstance(lane, dict) and isinstance(queue, dict) and isinstance(shown, dict),
            "lane_or_queue_missing")
    assert isinstance(lane, dict) and isinstance(queue, dict) and isinstance(shown, dict)
    require(lane.get("status") == shown.get("status") == "merging"
            and lane.get("head_sha") == shown.get("head_sha") == candidate
            and lane.get("base_main_sha") == shown.get("base_main_sha") == main
            and lane.get("version") == shown.get("version")
            and type(lane.get("version")) is int and lane["version"] > 0
            and bool(lane.get("verify_ref")) and lane.get("verify_ref") == shown.get("verify_ref"),
            "lane_snapshot_untrusted")
    holder = [x for x in queue_rows if x.get("status") in ("preflight", "merging")]
    require(len(holder) == 1 and holder[0].get("lane_id") == lane_id,
            "merge_slot_not_exclusive")
    preflight = queue.get("last_preflight") or {}
    require(queue.get("status") == "merging" and bool(queue.get("slot_acquired_at"))
            and bool(queue.get("slot_owner")) and queue.get("head_sha") == candidate
            and queue.get("base_main_sha") == main
            and type(queue.get("version")) is int and queue["version"] > 0
            and preflight.get("main_head") == main and preflight.get("verdict") == "pass"
            and queue.get("stale") is False,
            "queue_snapshot_untrusted")
    return (
        {"lane_id": lane_id, "version": lane["version"], "head_sha": candidate,
         "base_main_sha": main, "verify_ref": lane["verify_ref"], "status": "merging"},
        {"queue_id": queue["queue_id"], "version": queue["version"],
         "lane_id": lane_id, "status": "merging",
         "last_preflight_main_sha": main, "slot_held": True},
    )


def remote_state(pr: int, run_id: int) -> tuple[str, str]:
    prefix = "https://api.github.com/repos/" + _REPO
    branch = fetch_json(prefix + "/branches/main")
    pull = fetch_json(prefix + "/pulls/" + str(pr))
    run = fetch_json(prefix + "/actions/runs/" + str(run_id))
    main = (branch.get("commit") or {}).get("sha")
    candidate = (pull.get("head") or {}).get("sha")
    require(isinstance(main, str) and bool(_SHA.fullmatch(main))
            and isinstance(candidate, str) and bool(_SHA.fullmatch(candidate)),
            "remote_sha_invalid")
    assert isinstance(main, str) and isinstance(candidate, str)
    require(pull.get("state") == "open" and pull.get("draft") is False
            and (pull.get("base") or {}).get("ref") == "main"
            and (pull.get("base") or {}).get("sha") == main,
            "pr_base_changed")
    require(run.get("id") == run_id and run.get("event") == "pull_request"
            and run.get("status") == "completed" and run.get("conclusion") == "success"
            and run.get("head_sha") in (candidate, pull.get("merge_commit_sha")),
            "ci_run_not_verified")
    return main, candidate


def check_receipts(review: dict, r9: dict, integration: dict, *,
                   main: str, candidate: str) -> tuple[dict, dict, dict]:
    require(review.get("candidate_sha") == candidate
            and review.get("terminal") is True and review.get("verdict") == "PASS"
            and review.get("p0") == review.get("p1") == 0
            and review.get("reviewer_model") == "glm/glm-5.3-flash"
            and bool(review.get("reviewer_session_id")),
            "review_receipt_untrusted")
    require(r9.get("candidate_sha") == candidate and r9.get("full") is True
            and r9.get("exit_code") == 0 and bool(_HEX256.fullmatch(str(r9.get("log_sha256", "")))),
            "r9_receipt_untrusted")
    require(integration.get("candidate_sha") == candidate
            and integration.get("main_sha") == main
            and integration.get("contracts_verified") is True
            and integration.get("merge_tree_clean") is True,
            "integration_receipt_untrusted")
    return (
        {"terminal": True, "verdict": "PASS", "p0": 0, "p1": 0,
         "candidate_sha": candidate, "reviewer_model": review["reviewer_model"]},
        {"full": True, "exit_code": 0, "candidate_sha": candidate,
         "receipt": r9["log_sha256"]},
        {"clean": True, "contracts_verified": True, "merge_tree_clean": True},
    )


def sign_payload(payload: dict, private_pem: bytes) -> dict:
    ecc, eddsa = crypto()
    key = ecc.import_key(private_pem)
    require(key.curve == "Ed25519" and key.has_private(), "private_key_invalid")
    public = key.public_key().export_key(format="PEM")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode()
    signature = eddsa.new(key, "rfc8032").sign(canonical)
    return {"payload": payload,
            "key_id": hashlib.sha256(public.encode()).hexdigest()[:16],
            "signature_ed25519": base64.b64encode(signature).decode()}


def keygen(private_dir: Path, *, expected_uid: int = _ISSUER_UID) -> dict:
    require(os.geteuid() == expected_uid, "issuer_uid_invalid")
    st = private_dir.lstat()
    require(stat.S_ISDIR(st.st_mode) and st.st_uid == expected_uid
            and st.st_mode & 0o077 == 0, "private_dir_not_isolated")
    ecc, _ = crypto()
    private = ecc.generate(curve="Ed25519")
    key_file = private_dir / "host-ed25519.pem"
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.write(fd, private.export_key(format="PEM").encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    public = private.public_key().export_key(format="PEM")
    pub_file = private_dir / "host-ed25519.pub.pem"
    fd = os.open(pub_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, public.encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    return {"key_id": hashlib.sha256(public.encode()).hexdigest()[:16],
            "public_path": str(pub_file), "private_path": str(key_file)}


def issue(*, pr: int, run_id: int, lane_id: str, worktree: Path,
          review_path: Path, r9_path: Path, integration_path: Path,
          private_dir: Path, output_dir: Path, audit_dir: Path,
          expected_main: str = "", expected_candidate: str = "",
          expected_uid: int = _ISSUER_UID, web_uid: int = _WEB_UID,
          web_group_gid: int = 20) -> dict:
    require(os.geteuid() == expected_uid and expected_uid != web_uid
            and expected_uid != 0, "issuer_uid_invalid")
    st = output_dir.lstat()
    require(stat.S_ISDIR(st.st_mode) and st.st_uid == expected_uid
            and st.st_gid == web_group_gid and st.st_mode & 0o027 == 0,
            "output_dir_not_isolated")
    require(bool(_SHA.fullmatch(expected_main))
            and bool(_SHA.fullmatch(expected_candidate)), "operator_sha_missing")
    main, candidate = remote_state(pr, run_id)
    require(main == expected_main and candidate == expected_candidate,
            "operator_sha_mismatch")
    lane, queue = local_state(lane_id, main, candidate,
                              audit_dir=audit_dir, owner=web_uid)
    review = read_json(secure_bytes(review_path, expected_uid), "review_receipt")
    r9 = read_json(secure_bytes(r9_path, expected_uid), "r9_receipt")
    integration = read_json(secure_bytes(integration_path, expected_uid),
                            "integration_receipt")
    review_fact, r9_fact, integration_fact = check_receipts(
        review, r9, integration, main=main, candidate=candidate)
    log_path = Path(str(r9.get("log_path") or ""))
    require(log_path.is_absolute(), "r9_log_path_invalid")
    raw_log = public_bytes(log_path, web_uid, max_bytes=32 * 1024 * 1024)
    require(hashlib.sha256(raw_log).hexdigest() == r9["log_sha256"]
            and b"ci_gate " in raw_log and b"PASS" in raw_log,
            "r9_log_digest_mismatch")
    root = worktree.resolve(strict=True)
    require(root.is_dir() and root.stat().st_uid == web_uid, "worktree_owner_invalid")
    def git(*args: str) -> str:
        proc = subprocess.run(["/usr/bin/git", "-c", f"safe.directory={root}",
                               "-C", str(root), *args],
                              capture_output=True, text=True, timeout=15,
                              check=False, env={"PATH": "/usr/bin:/bin",
                                                "HOME": "/var/empty",
                                                "GIT_CONFIG_NOSYSTEM": "1",
                                                "GIT_CONFIG_GLOBAL": "/dev/null",
                                                "LC_ALL": "C"})
        require(proc.returncode == 0, "integration_git_unavailable")
        return proc.stdout.strip()
    require(git("rev-parse", "HEAD") == candidate
            and git("status", "--porcelain") == ""
            and git("merge-base", main, candidate) == main,
            "integration_worktree_untrusted")
    payload = {"checked_at": time.time(), "repo": _REPO, "pr_number": pr,
               "run_id": run_id, "main_sha": main, "candidate_sha": candidate,
               "lane": lane, "queue": queue, "review": review_fact,
               "r9": r9_fact, "integration": integration_fact}
    # Fresh read immediately before signing; stale Queue/PR transitions HOLD.
    require(remote_state(pr, run_id) == (main, candidate), "remote_changed")
    require(local_state(lane_id, main, candidate, audit_dir=audit_dir,
                        owner=web_uid) == (lane, queue), "local_state_changed")
    private_pem = secure_bytes(private_dir / "host-ed25519.pem", expected_uid)
    envelope = sign_payload(payload, private_pem)
    filename = f"host-snapshot-pr{pr}-{candidate[:12]}-{run_id}.json"
    target = output_dir / filename
    # Write into issuer-private space first. A failed audit must never leave
    # an unrecorded signed envelope readable by the Web process.
    staging = private_dir / (".snapshot-pending-" + secrets.token_hex(12))
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o640)
    try:
        os.write(fd, (json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    audit = {"ts": payload["checked_at"], "event": "host_snapshot_publish_intent",
             "repo": _REPO, "pr": pr, "run_id": run_id,
             "candidate_sha": candidate, "key_id": envelope["key_id"],
             "snapshot_name": filename}
    try:
        audit_fd = os.open(private_dir / "issuer-audit.jsonl",
                           os.O_WRONLY | os.O_CREAT | os.O_APPEND |
                           getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.write(audit_fd, (json.dumps(audit, sort_keys=True) + "\n").encode())
            os.fsync(audit_fd)
        finally:
            os.close(audit_fd)
        # Atomic no-overwrite publish on the same filesystem. The staging
        # path is inside 0700 private dir, unreadable to the Web UID.
        os.link(staging, target, follow_symlinks=False)
    finally:
        staging.unlink(missing_ok=True)
    return {"decision": "SIGNED", "key_id": envelope["key_id"],
            "candidate_sha": candidate, "snapshot_path": str(target)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("keygen", "issue"), required=True)
    parser.add_argument("--pr", type=int)
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--lane-id")
    parser.add_argument("--expected-main-sha")
    parser.add_argument("--expected-candidate-sha")
    parser.add_argument("--worktree")
    parser.add_argument("--audit-dir")
    parser.add_argument("--review-receipt")
    parser.add_argument("--r9-receipt")
    parser.add_argument("--integration-receipt")
    args = parser.parse_args(argv)
    try:
        # A same-UID model tool or non-isolated Python invocation cannot
        # silently become the production issuer.
        if os.geteuid() == _ISSUER_UID:
            require(bool(sys.flags.isolated and sys.flags.no_site),
                    "issuer_python_not_isolated")
        if args.mode == "keygen":
            result = keygen(_BASE / "private")
        else:
            require(all((args.pr, args.run_id, args.lane_id,
                         args.expected_main_sha, args.expected_candidate_sha,
                         args.worktree, args.audit_dir,
                         args.review_receipt, args.r9_receipt,
                         args.integration_receipt)), "required_argument_missing")
            for p in (args.review_receipt, args.r9_receipt, args.integration_receipt):
                require(Path(p).resolve().is_relative_to((_BASE / "private").resolve()),
                        "receipt_outside_operator_dir")
            result = issue(pr=args.pr, run_id=args.run_id, lane_id=args.lane_id,
                           worktree=Path(args.worktree), review_path=Path(args.review_receipt),
                           r9_path=Path(args.r9_receipt),
                           integration_path=Path(args.integration_receipt),
                           private_dir=_BASE / "private", output_dir=_BASE / "receipts",
                           audit_dir=Path(args.audit_dir),
                           expected_main=args.expected_main_sha,
                           expected_candidate=args.expected_candidate_sha)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (IssuerHoldError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"decision": "HOLD", "reason": str(exc),
                          "signed": False, "private_key_exposed": False}),
              file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Publish a required GitHub check ONLY after independent Host eligibility.

This program must run as the dedicated Host issuer UID with an isolated Python
runtime and a GitHub App installation token unavailable to LFL/Web/PR code.
The GitHub main branch must require (lfl-host-premerge, this App's ID) with
strict up-to-date checks. A green Actions artifact alone cannot publish it.

Dry-run by default. No branch protection mutation, merge, or push is possible.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import premerge_host
from premerge_host import (
    _HOST_CHECK_CONTEXT,
    GitHubReadOnly,
    HostHoldError,
    _checks,
    _lookup,
    _NoRedirect,
    _require,
    _verify_host_execution,
    evaluate_host,
)

_ISSUER_UID = 462
_TRUSTED_SITE = "/Library/Application Support/LFL-DualAgent/runtime/site"


def _fingerprint(envelope: dict) -> str:
    canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _post_check(repo: str, token: str, body: dict) -> dict:
    _require(bool(token) and len(token) >= 20, "host_check_token_unavailable")
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    req = urllib.request.Request(
        "https://api.github.com/repos/" + repo + "/check-runs",
        data=raw, method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "lfl-independent-host-check",
        },
    )
    try:
        with urllib.request.build_opener(_NoRedirect()).open(req, timeout=12) as response:
            value = json.loads(response.read(16385))
    except (urllib.error.HTTPError, urllib.error.URLError, OSError,
            TimeoutError, ValueError) as exc:
        # Never include a response body or Authorization header in the error.
        raise HostHoldError("host_check_publish_unavailable") from exc
    _require(isinstance(value, dict), "host_check_response_invalid")
    return value


def publish_verified(
    client: Any, *, repo: str, pr_number: int, main: str, candidate: str,
    run_id: int, envelope: dict, public_key: str, app_id: int,
    check_token: str = "", apply: bool = False,
    now: float | None = None,
    post: Callable[[str, str, dict], dict] = _post_check,
    live_state: Callable[[dict], None] | None = None,
) -> dict:
    """No check writes until all signed Host + CI + protection facts pass."""
    stamp = time.time() if now is None else now
    verdict = evaluate_host(
        client, repo=repo, pr_number=pr_number, main=main,
        candidate=candidate, run_id=run_id, envelope=envelope,
        snapshot_public_key=public_key, host_app_id=app_id, now=stamp,
    )
    tested_merge = verdict["tested_merge_sha"]
    digest = _fingerprint(envelope)
    external_id = f"lfl-host:{pr_number}:{main}:{candidate}:{tested_merge}:{digest}"
    if apply:
        _require(live_state is not None, "host_live_state_unavailable")
        assert live_state is not None
        live_state(envelope["payload"])
    existing = _lookup(
        _checks(client, f"repos/{repo}", tested_merge),
        _HOST_CHECK_CONTEXT, app_id, tested_merge,
    )
    if existing is not None:
        _require(
            existing.get("external_id") == external_id
            and existing.get("status") == "completed"
            and existing.get("conclusion") == "success",
            "host_check_existing_conflict", unavailable=False,
        )
        return {
            "decision": "ALREADY_PUBLISHED", "head_sha": tested_merge,
            "app_id": app_id, "check_id": existing.get("id"),
            "snapshot_sha256": digest,
        }
    # Recheck the exact live identities immediately before the write.
    branch = client.get(f"repos/{repo}/branches/main")
    pull = client.get(f"repos/{repo}/pulls/{pr_number}")
    _require(
        (branch.get("commit") or {}).get("sha") == main
        and pull.get("state") == "open" and pull.get("draft") is not True
        and (pull.get("base") or {}).get("sha") == main
        and (pull.get("head") or {}).get("sha") == candidate
        and pull.get("merge_commit_sha") == tested_merge,
        "prepublish_identity_changed", unavailable=False,
    )
    if not apply:
        return {
            "decision": "ELIGIBLE_TO_PUBLISH", "read_only": True,
            "head_sha": tested_merge, "app_id": app_id,
            "snapshot_sha256": digest,
        }
    # Check the Lane/Queue again after the last GitHub identity read.
    assert live_state is not None
    live_state(envelope["payload"])
    _require(bool(check_token) and len(check_token) >= 20,
             "host_check_token_unavailable")
    body = {
        "name": _HOST_CHECK_CONTEXT,
        # GitHub evaluates PR required checks on the tested merge ref.
        "head_sha": tested_merge,
        "status": "completed",
        "conclusion": "success",
        "external_id": external_id,
        "output": {
            "title": "Independent Host premerge eligibility verified",
            "summary": (
                f"PR #{pr_number}; base {main}; head {candidate}; "
                f"tested merge {tested_merge}; signed Host snapshot SHA-256 {digest}. "
                "Terminal independent review, full R9, exclusive Lane/Queue, "
                "protected CI and strict branch protection were verified."
            ),
        },
    }
    result = post(repo, check_token, body)
    _require(
        result.get("name") == _HOST_CHECK_CONTEXT
        and result.get("head_sha") == tested_merge
        and (result.get("app") or {}).get("id") == app_id
        and result.get("external_id") == external_id
        and result.get("status") == "completed"
        and result.get("conclusion") == "success"
        and type(result.get("id")) is int,
        "host_check_publish_identity_mismatch", unavailable=False,
    )
    return {
        "decision": "PUBLISHED", "check_id": result["id"],
        "head_sha": tested_merge, "app_id": app_id,
        "snapshot_sha256": digest,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--expected-main-sha", required=True)
    parser.add_argument("--expected-candidate-sha", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--host-snapshot", required=True)
    parser.add_argument("--execution-root", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        # The check writer must not be callable from the Web/model UID.
        _require(os.geteuid() == _ISSUER_UID and sys.flags.isolated
                 and sys.flags.no_site, "host_check_issuer_isolation_required")
        # Load only the root-owned frozen crypto runtime, never PR code.
        site = Path(_TRUSTED_SITE)
        st = site.lstat()
        _require(stat.S_ISDIR(st.st_mode) and st.st_uid == 0
                 and (st.st_mode & 0o022) == 0,
                 "host_check_crypto_runtime_untrusted")
        sys.path.insert(0, str(site))
        from Crypto.PublicKey import ECC
        from Crypto.Signature import eddsa
        trusted_site = site.resolve(strict=True)
        for module in (ECC, eddsa):
            source = Path(module.__file__).resolve(strict=True)
            _require(source.is_relative_to(trusted_site),
                     "host_check_crypto_module_untrusted")
        try:
            envelope = json.loads(Path(args.host_snapshot).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HostHoldError("host_snapshot_unavailable") from exc
        try:
            app_id = int(os.environ.get("LFL_PREMERGE_HOST_CHECK_APP_ID", "0"))
        except ValueError as exc:
            raise HostHoldError("host_check_app_unconfigured") from exc
        client = GitHubReadOnly(
            args.repo, os.environ.get("LFL_PREMERGE_HOST_GITHUB_TOKEN", "")
        )
        # The installed entrypoint and imported verifier are root-owned
        # immutable copies of protected main, not code from the candidate.
        installed = Path(__file__).resolve(strict=True)
        verifier = Path(premerge_host.__file__).resolve(strict=True)
        _require(installed.parent == verifier.parent,
                 "host_check_install_mismatch", unavailable=False)
        parent = installed.parent.lstat()
        _require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == 0
                 and (parent.st_mode & 0o022) == 0,
                 "host_check_install_dir_untrusted", unavailable=False)
        for source, name in (
            (installed, "scripts/host_premerge_check_publisher.py"),
            (verifier, "scripts/premerge_host.py"),
        ):
            st = source.lstat()
            _require(stat.S_ISREG(st.st_mode) and st.st_uid == 0
                     and st.st_mode & 0o022 == 0,
                     "host_check_install_untrusted", unavailable=False)
            trusted_blob, _ = client.blob(name, args.expected_main_sha)
            from premerge_host import _blob_sha
            _require(_blob_sha(source.read_bytes()) == trusted_blob,
                     "host_check_install_blob_mismatch", unavailable=False)
        _verify_host_execution(
            client, args.expected_main_sha,
            execution_root=Path(args.execution_root),
        )
        # Re-read the live Lane/Queue under the trusted installed issuer's
        # own read-only authority, immediately before publishing a check.
        issuer_path = Path(
            "/Library/Application Support/LFL-HostIssuer/bin/issuer.py"
        )
        issuer_stat = issuer_path.lstat()
        _require(stat.S_ISREG(issuer_stat.st_mode) and issuer_stat.st_uid == 0
                 and (issuer_stat.st_mode & 0o022) == 0,
                 "host_live_issuer_untrusted", unavailable=False)
        issuer_blob, _ = client.blob(
            "scripts/premerge_host_snapshot_issuer.py", args.expected_main_sha
        )
        from premerge_host import _blob_sha
        _require(_blob_sha(issuer_path.read_bytes()) == issuer_blob,
                 "host_live_issuer_blob_mismatch", unavailable=False)
        spec = importlib.util.spec_from_file_location(
            "lfl_trusted_installed_issuer", issuer_path
        )
        _require(spec is not None and spec.loader is not None,
                 "host_live_issuer_unavailable")
        assert spec is not None and spec.loader is not None
        issuer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(issuer)
        audit_dir = Path(os.environ.get("LFL_PREMERGE_HOST_AUDIT_DIR", ""))
        _require(audit_dir.is_absolute(), "host_audit_dir_unconfigured")

        def live_state(payload: dict) -> None:
            try:
                lane, queue = issuer.local_state(
                    payload["lane"]["lane_id"], payload["main_sha"],
                    payload["candidate_sha"], audit_dir=audit_dir,
                )
            except (OSError, ValueError, issuer.IssuerHoldError) as exc:
                raise HostHoldError("host_live_state_unavailable") from exc
            _require(lane == payload["lane"] and queue == payload["queue"],
                     "host_live_state_changed", unavailable=False)

        result = publish_verified(
            client, repo=args.repo, pr_number=args.pr,
            main=args.expected_main_sha, candidate=args.expected_candidate_sha,
            run_id=args.run_id, envelope=envelope,
            public_key=os.environ.get("LFL_PREMERGE_HOST_SNAPSHOT_PUBKEY", ""),
            app_id=app_id,
            check_token=os.environ.get("LFL_PREMERGE_HOST_CHECK_TOKEN", ""),
            apply=args.apply, live_state=live_state,
        )
        code = 0
    except HostHoldError as exc:
        code = 3 if exc.unavailable else 1
        result = {"decision": "HOLD", "reason": exc.reason, "exit_code": code,
                  "check_published": False}
    except Exception:
        code = 3
        result = {"decision": "HOLD", "reason": "host_check_unexpected_error",
                  "exit_code": code, "check_published": False}
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())

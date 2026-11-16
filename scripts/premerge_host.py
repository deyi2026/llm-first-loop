#!/usr/bin/env python3
"""Read-only, fail-closed Host-side premerge evidence verifier.

A signed, fresh Host snapshot is required for local Lane/Queue/Reviewer/R9
facts. GitHub branch protection, check runs, Actions run/artifact, PR refs,
trusted policy, and gate blobs are fetched independently using an operator
token. Neither a CI artifact nor a candidate PR may self-authorize its gate.
No git write, merge, push, policy mutation, or deployment occurs here.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_GATE_PATHS = (
    "scripts/premerge_gate.py",
    "scripts/ci_gate.sh",
    ".github/workflows/ci.yml",
    "scripts/git_security_scan.sh",
    "scripts/verify_linux_installer.py",
    "pyproject.toml",
    "scripts/check_static_diagnostics.py",
    "scripts/check_test_env_pins.py",
    "scripts/check_architecture_submission.py",
    ".github/workflows/architecture-review.yml",
)
_POLICY_PATH = "docs/governance/required-ci-checks.json"
_MAX_ARTIFACT = 1024 * 1024


class HostHoldError(Exception):
    def __init__(self, reason: str, *, unavailable: bool = True):
        self.reason = reason
        self.unavailable = unavailable
        super().__init__(reason)


def _require(ok: bool, reason: str, *, unavailable: bool = True) -> None:
    if not ok:
        raise HostHoldError(reason, unavailable=unavailable)


def _sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA.fullmatch(value))


def _blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


class GitHubReadOnly:
    def __init__(self, repo: str, token: str):
        _require(bool(_REPO.fullmatch(repo)), "repo_invalid")
        _require(bool(token) and len(token) >= 10, "host_credential_unavailable")
        self.repo = repo
        self.token = token

    def _open(self, path: str) -> bytes:
        url = "https://api.github.com/" + (
            path if path.startswith("repos/" + self.repo + "/")
            else "repos/" + self.repo + "/" + path
        )
        req = urllib.request.Request(
            url, headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "lfl-managed-premerge-host",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                raw = response.read(_MAX_ARTIFACT + 1)
        except urllib.error.HTTPError as exc:
            relative = path.removeprefix("repos/" + self.repo + "/")
            if exc.code == 403:
                reason = "host_credential_scope_missing"
            elif exc.code == 404 and relative.startswith(
                "branches/main/protection/"
            ):
                reason = "protection_not_installed"
            elif exc.code == 404 and relative.startswith(
                "contents/docs/governance/required-ci-checks.json"
            ):
                reason = "policy_missing"
            else:
                reason = "github_api_unavailable"
            raise HostHoldError(reason) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HostHoldError("github_api_unavailable") from exc
        _require(len(raw) <= _MAX_ARTIFACT, "github_response_oversize")
        return raw

    def get(self, path: str) -> Any:
        try:
            value = json.loads(self._open(path))
        except (ValueError, UnicodeDecodeError) as exc:
            raise HostHoldError("github_response_invalid") from exc
        _require(isinstance(value, (dict, list)), "github_response_invalid")
        return value

    def blob(self, path: str, ref: str) -> tuple[str, bytes]:
        _require(_sha(ref), "blob_ref_invalid")
        safe = urllib.parse.quote(path, safe="/")
        value = self.get(f"contents/{safe}?ref={ref}")
        _require(value.get("encoding") == "base64", "github_blob_unavailable")
        try:
            data = base64.b64decode(value["content"], validate=False)
        except (ValueError, KeyError, TypeError) as exc:
            raise HostHoldError("github_blob_invalid") from exc
        _require(len(data) <= _MAX_ARTIFACT, "github_blob_oversize")
        blob_sha = value.get("sha")
        _require(blob_sha == _blob_sha(data), "github_blob_hash_mismatch")
        return blob_sha, data

    def artifact(self, artifact_id: int) -> dict:
        _require(isinstance(artifact_id, int) and artifact_id > 0, "artifact_id_invalid")
        # GitHub's ZIP endpoint redirects to a GitHub-controlled artifact host.
        # No authorization header may be forwarded to the redirected host.
        endpoint = f"actions/artifacts/{artifact_id}/zip"
        req = urllib.request.Request(
            "https://api.github.com/repos/" + self.repo + "/" + endpoint,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "User-Agent": "lfl-managed-premerge-host",
            },
        )

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirect())
        try:
            opener.open(req, timeout=12)
            raise HostHoldError("artifact_redirect_missing")
        except urllib.error.HTTPError as exc:
            _require(exc.code in (301, 302, 303, 307, 308), "artifact_download_unavailable")
            target = exc.headers.get("Location", "")
        _require(target.startswith("https://"), "artifact_redirect_untrusted")
        parsed = urllib.parse.urlsplit(target)
        _require(
            parsed.hostname is not None and (
                parsed.hostname == "objects.githubusercontent.com"
                or parsed.hostname.endswith(".actions.githubusercontent.com")
                or parsed.hostname.endswith(".blob.core.windows.net")
            ),
            "artifact_redirect_untrusted",
        )
        try:
            with urllib.request.urlopen(
                urllib.request.Request(target, headers={"User-Agent": "lfl-managed-premerge-host"}),
                timeout=12,
            ) as response:
                content = response.read(_MAX_ARTIFACT + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HostHoldError("artifact_download_unavailable") from exc
        _require(len(content) <= _MAX_ARTIFACT, "artifact_oversize")
        return _decode_artifact_zip(content)


def _decode_artifact_zip(content: bytes) -> dict:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.namelist()
            _require(members == ["premerge-gate-receipt.json"], "artifact_members_invalid")
            _require(archive.getinfo(members[0]).file_size <= _MAX_ARTIFACT, "artifact_oversize")
            value = json.loads(archive.read(members[0]))
    except (zipfile.BadZipFile, ValueError, KeyError) as exc:
        raise HostHoldError("artifact_invalid") from exc
    _require(isinstance(value, dict), "artifact_invalid")
    return value


def _verified_snapshot(envelope: dict, public_key_pem: str, now: float) -> dict:
    """Verify an independent Host issuer signature using PUBLIC key only.

    The signing private key must live in a separate trusted issuer process.
    This verifier never receives, imports, or accepts a signing private key.
    """
    _require(isinstance(envelope, dict), "host_snapshot_missing")
    payload = envelope.get("payload")
    signature = envelope.get("signature_ed25519")
    key_id = envelope.get("key_id")
    _require(isinstance(payload, dict) and isinstance(signature, str),
             "host_snapshot_unsigned")
    _require(isinstance(public_key_pem, str) and public_key_pem.strip(),
             "host_snapshot_public_key_unavailable")
    _require(
        isinstance(key_id, str) and key_id ==
        hashlib.sha256(public_key_pem.encode()).hexdigest()[:16],
        "host_snapshot_key_id_mismatch",
    )
    try:
        from Crypto.PublicKey import ECC
        from Crypto.Signature import eddsa

        key = ECC.import_key(public_key_pem)
        _require(key.curve == "Ed25519" and not key.has_private(),
                 "host_snapshot_public_key_invalid")
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        raw_signature = base64.b64decode(signature, validate=True)
        _require(len(raw_signature) == 64, "host_snapshot_signature_invalid")
        eddsa.new(key, "rfc8032").verify(canonical, raw_signature)
    except (ValueError, TypeError, KeyError) as exc:
        raise HostHoldError("host_snapshot_signature_invalid") from exc
    stamp = payload.get("checked_at")
    _require(isinstance(stamp, (int, float)) and 0 <= now - stamp <= 90,
             "host_snapshot_stale")
    return payload

def _check_local(snapshot: dict, main: str, candidate: str) -> None:
    _require(snapshot.get("main_sha") == main and snapshot.get("candidate_sha") == candidate,
             "host_snapshot_identity_changed")
    lane = snapshot.get("lane") or {}
    queue = snapshot.get("queue") or {}
    review = snapshot.get("review") or {}
    r9 = snapshot.get("r9") or {}
    integration = snapshot.get("integration") or {}
    _require(
        bool(lane.get("lane_id")) and isinstance(lane.get("version"), int)
        and lane.get("version") > 0 and lane.get("head_sha") == candidate
        and lane.get("base_main_sha") == main and bool(lane.get("verify_ref")),
        "lane_snapshot_incomplete",
    )
    _require(
        bool(queue.get("queue_id")) and isinstance(queue.get("version"), int)
        and queue.get("version") > 0 and queue.get("lane_id") == lane["lane_id"]
        and queue.get("status") == "ready_for_confirm"
        and queue.get("last_preflight_main_sha") == main
        and queue.get("slot_held") is True,
        "queue_snapshot_incomplete",
    )
    _require(
        review.get("terminal") is True and review.get("verdict") == "PASS"
        and review.get("p0") == 0 and review.get("p1") == 0
        and review.get("candidate_sha") == candidate
        and bool(review.get("reviewer_model")),
        "review_missing_or_stale",
    )
    _require(
        r9.get("full") is True and r9.get("exit_code") == 0
        and r9.get("candidate_sha") == candidate and bool(r9.get("receipt")),
        "r9_missing_or_stale",
    )
    _require(
        integration.get("clean") is True
        and integration.get("contracts_verified") is True
        and integration.get("merge_tree_clean") is True,
        "integration_unverified",
    )


def _checks(client: Any, repo_path: str, sha: str) -> list[dict]:
    value = client.get(f"{repo_path}/commits/{sha}/check-runs?per_page=100&filter=all")
    runs = value.get("check_runs")
    _require(isinstance(runs, list) and value.get("total_count") == len(runs),
             "check_runs_incomplete")
    return runs


def _lookup(runs: list[dict], context: str, app_id: int, sha: str) -> dict | None:
    matches = [
        r for r in runs
        if r.get("name") == context and (r.get("app") or {}).get("id") == app_id
        and r.get("head_sha") == sha
    ]
    _require(len(matches) <= 1, "check_context_ambiguous", unavailable=False)
    return matches[0] if matches else None


def _passed(run: dict | None) -> bool:
    return bool(run and run.get("status") == "completed" and run.get("conclusion") == "success")


def _check_run_origin(client: Any, repo: str, check: dict, *,
                      event: str, main: str, candidate: str,
                      tested_merge: str, pr_number: int,
                      expected_run_id: int | None = None,
                      expected_workflow_path: str = "",
                      expected_workflow_id: int = 0) -> None:
    details = check.get("details_url")
    _require(isinstance(details, str), "check_run_origin_unverifiable")
    parsed = urllib.parse.urlsplit(details)
    match = re.fullmatch(
        rf"/{re.escape(repo)}/actions/runs/([1-9][0-9]*)(?:/job/[0-9]+)?",
        parsed.path,
    )
    _require(
        parsed.scheme == "https" and parsed.hostname == "github.com"
        and match is not None and not parsed.query and not parsed.fragment,
        "check_run_origin_unverifiable",
    )
    assert match is not None
    actual_run_id = int(match.group(1))
    if expected_run_id is not None:
        _require(actual_run_id == expected_run_id, "managed_run_identity_mismatch")
    run = client.get(f"repos/{repo}/actions/runs/{actual_run_id}")
    run_path = run.get("path")
    _require(
        isinstance(run_path, str)
        and run_path.split("@", 1)[0] == expected_workflow_path
        and run.get("workflow_id") == expected_workflow_id,
        "check_run_workflow_mismatch", unavailable=False,
    )
    _require(
        run.get("id") == actual_run_id and run.get("event") == event
        and run.get("status") == "completed" and run.get("conclusion") == "success",
        "check_run_event_mismatch",
    )
    if event == "push":
        _require(run.get("head_sha") == main, "main_check_run_identity_mismatch")
    else:
        associated = run.get("pull_requests")
        _require(
            run.get("head_sha") in (candidate, tested_merge)
            and isinstance(associated, list)
            and any(
                isinstance(a, dict) and a.get("number") == pr_number
                and (a.get("head") or {}).get("sha") == candidate
                and (a.get("base") or {}).get("sha") == main
                for a in associated
            ),
            "pr_check_run_identity_mismatch",
        )


def _workflow_events(data: bytes) -> set[str]:
    try:
        import yaml

        doc = yaml.load(data.decode("utf-8"), Loader=yaml.BaseLoader)
        trigger = doc.get("on") if isinstance(doc, dict) else None
    except (ImportError, ValueError, UnicodeDecodeError, AttributeError) as exc:
        raise HostHoldError("workflow_triggers_unverifiable") from exc
    if isinstance(trigger, list):
        return set(trigger)
    if isinstance(trigger, dict):
        return set(trigger)
    if isinstance(trigger, str):
        return {trigger}
    raise HostHoldError("workflow_triggers_unverifiable")


def _trusted_policy(client: Any, repo_path: str, main: str, candidate: str,
                    remote_required: list[dict]) -> list[dict]:
    main_policy_sha, raw = client.blob(_POLICY_PATH, main)
    candidate_policy_sha, _ = client.blob(_POLICY_PATH, candidate)
    _require(main_policy_sha == candidate_policy_sha, "gate_version_untrusted",
             unavailable=False)
    try:
        policy = json.loads(raw)
    except ValueError as exc:
        raise HostHoldError("policy_invalid") from exc
    _require(isinstance(policy, dict) and policy.get("schema") == "lfl.required_checks.v1",
             "policy_invalid")
    pinned = policy.get("checks")
    _require(isinstance(pinned, list) and len(pinned) >= 3, "required_checks_source_inadequate")
    seen: set[tuple[str, int]] = set()
    purposes: set[str] = set()
    for item in pinned:
        _require(isinstance(item, dict), "policy_invalid")
        context, app_id = item.get("context"), item.get("app_id")
        scope, purpose = item.get("event_scope"), item.get("purpose")
        path, expected_blob = item.get("workflow_path"), item.get("workflow_blob_sha")
        workflow_id = item.get("workflow_id")
        _require(
            isinstance(context, str) and bool(context.strip())
            and type(app_id) is int and app_id > 0
            and scope in ("push_and_pr", "pr_only")
            and isinstance(purpose, str) and bool(purpose)
            and isinstance(path, str) and path.startswith(".github/workflows/")
            and _sha(expected_blob)
            and type(workflow_id) is int and workflow_id > 0,
            "policy_invalid",
        )
        key = (context, app_id)
        _require(key not in seen, "required_checks_source_inadequate")
        seen.add(key)
        purposes.add(purpose)
        main_workflow_sha, workflow = client.blob(path, main)
        _require(main_workflow_sha == expected_blob, "policy_workflow_untrusted")
        events = _workflow_events(workflow)
        _require("pull_request" in events, "policy_event_scope_untrusted")
        _require(("push" in events) == (scope == "push_and_pr"),
                 "policy_event_scope_untrusted")
    _require({"test", "security_scan", "managed_evidence"} <= purposes,
             "required_checks_source_inadequate")
    required: set[tuple[str, int]] = set()
    for item in remote_required:
        _require(isinstance(item, dict), "required_checks_unavailable")
        context, app_id = item.get("context"), item.get("app_id")
        _require(isinstance(context, str) and type(app_id) is int and app_id > 0,
                 "required_checks_unavailable")
        key = (context, app_id)
        _require(key not in required, "check_context_ambiguous")
        required.add(key)
    _require(seen == required, "required_checks_source_inadequate")
    _require(sum(x.get("purpose") == "managed_evidence" for x in pinned) == 1,
             "required_checks_source_inadequate")
    return pinned


def _verify_gate_blobs(client: Any, main: str, candidate: str) -> dict[str, str]:
    hashes = {}
    for path in _GATE_PATHS:
        main_hash, _ = client.blob(path, main)
        candidate_hash, _ = client.blob(path, candidate)
        _require(main_hash == candidate_hash, "gate_version_untrusted",
                 unavailable=False)
        hashes[path] = main_hash
    return hashes


def evaluate_host(client: Any, *, repo: str, pr_number: int, main: str,
                  candidate: str, run_id: int, envelope: dict,
                  snapshot_public_key: str, now: float) -> dict:
    """No Git writes. All external facts are read through the injected client."""
    _require(bool(_REPO.fullmatch(repo)) and pr_number > 0 and run_id > 0,
             "host_arguments_invalid")
    _require(_sha(main) and _sha(candidate), "host_sha_invalid")
    snapshot = _verified_snapshot(envelope, snapshot_public_key, now)
    _check_local(snapshot, main, candidate)
    prefix = f"repos/{repo}"
    branch = client.get(f"{prefix}/branches/main")
    actual_main = ((branch.get("commit") or {}).get("sha"))
    _require(_sha(actual_main) and actual_main == main, "main_advanced")
    pr = client.get(f"{prefix}/pulls/{pr_number}")
    pr_head = ((pr.get("head") or {}).get("sha"))
    pr_base = ((pr.get("base") or {}).get("sha"))
    tested_merge = pr.get("merge_commit_sha")
    _require(
        pr.get("state") == "open" and (pr.get("base") or {}).get("ref") == "main"
        and pr_head == candidate and pr_base == main and _sha(tested_merge),
        "pr_identity_changed",
    )
    merge_commit = client.get(f"{prefix}/commits/{tested_merge}")
    parents = merge_commit.get("parents")
    _require(
        merge_commit.get("sha") == tested_merge and isinstance(parents, list)
        and len(parents) == 2 and (parents[0] or {}).get("sha") == main
        and (parents[1] or {}).get("sha") == candidate,
        "tested_merge_parents_mismatch", unavailable=False,
    )
    protection = client.get(f"{prefix}/branches/main/protection/required_status_checks")
    _require(protection.get("strict") is True, "base_guard_unavailable")
    remote_required = protection.get("checks")
    _require(isinstance(remote_required, list) and bool(remote_required),
             "required_checks_unavailable")
    rulesets = client.get(f"{prefix}/rulesets?includes_parents=true")
    _require(rulesets == [], "rulesets_unverified")
    pinned = _trusted_policy(client, prefix, main, candidate, remote_required)
    blobs = _verify_gate_blobs(client, main, candidate)
    main_runs = _checks(client, prefix, main)
    pr_runs = _checks(client, prefix, tested_merge)
    for item in pinned:
        context, app_id = item["context"], item["app_id"]
        if item["event_scope"] == "push_and_pr":
            main_check = _lookup(main_runs, context, app_id, main)
            _require(_passed(main_check), "main_ci_red", unavailable=False)
            assert main_check is not None
            _check_run_origin(
                client, repo, main_check, event="push", main=main,
                candidate=candidate, tested_merge=tested_merge, pr_number=pr_number,
                expected_workflow_path=item["workflow_path"],
                expected_workflow_id=item["workflow_id"],
            )
        merged = _lookup(pr_runs, context, app_id, tested_merge)
        _require(_passed(merged), "pr_required_checks_incomplete", unavailable=False)
        assert merged is not None
        _check_run_origin(
            client, repo, merged, event="pull_request", main=main,
            candidate=candidate, tested_merge=tested_merge, pr_number=pr_number,
            expected_run_id=run_id if item["purpose"] == "managed_evidence" else None,
            expected_workflow_path=item["workflow_path"],
            expected_workflow_id=item["workflow_id"],
        )
    run = client.get(f"{prefix}/actions/runs/{run_id}")
    associated = run.get("pull_requests")
    _require(
        run.get("id") == run_id and run.get("event") == "pull_request"
        and run.get("status") == "completed" and run.get("conclusion") == "success"
        and run.get("head_sha") in (candidate, tested_merge)
        and isinstance(associated, list)
        and any(
            (a.get("head") or {}).get("sha") == candidate
            and (a.get("base") or {}).get("sha") == main
            and a.get("number") == pr_number
            for a in associated if isinstance(a, dict)
        ),
        "run_identity_mismatch",
    )
    artifacts = client.get(f"{prefix}/actions/runs/{run_id}/artifacts?per_page=100")
    all_artifacts = artifacts.get("artifacts")
    _require(
        isinstance(all_artifacts, list) and artifacts.get("total_count") == len(all_artifacts),
        "artifact_list_incomplete",
    )
    matches = [a for a in all_artifacts if a.get("name") == "premerge-gate-receipt"
               and not a.get("expired")]
    _require(len(matches) == 1, "artifact_unavailable")
    artifact = client.artifact(matches[0].get("id"))
    identity = artifact.get("identity") or {}
    _require(
        artifact.get("mode") == "ci" and artifact.get("verdict") == "pass"
        and artifact.get("event") == "pull_request" and artifact.get("run_id") == run_id
        and artifact.get("same_run") is True and artifact.get("all_success") is True
        and identity.get("pr_head_sha") == candidate
        and identity.get("pr_base_sha") == main
        and identity.get("pr_merge_sha") == tested_merge,
        "artifact_identity_mismatch", unavailable=False,
    )
    _require(artifact.get("gate_blobs") == blobs, "artifact_gate_blob_mismatch",
             unavailable=False)
    # C6: fresh second read immediately before eligibility; never reuse C1.
    final_main = client.get(f"{prefix}/branches/main")
    final_pr = client.get(f"{prefix}/pulls/{pr_number}")
    final_protection = client.get(
        f"{prefix}/branches/main/protection/required_status_checks"
    )
    final_rulesets = client.get(f"{prefix}/rulesets?includes_parents=true")
    final_main_runs = _checks(client, prefix, main)
    final_pr_runs = _checks(client, prefix, tested_merge)
    final_run = client.get(f"{prefix}/actions/runs/{run_id}")
    final_artifacts = client.get(f"{prefix}/actions/runs/{run_id}/artifacts?per_page=100")
    _require(
        final_main_runs == main_runs and final_pr_runs == pr_runs
        and final_run == run and final_artifacts == artifacts
        and (final_main.get("commit") or {}).get("sha") == main
        and (final_pr.get("head") or {}).get("sha") == candidate
        and (final_pr.get("base") or {}).get("sha") == main
        and final_pr.get("merge_commit_sha") == tested_merge
        and final_pr.get("state") == "open"
        and final_protection == protection
        and final_rulesets == rulesets,
        "premerge_race_detected",
    )
    # This is a read-side recheck, NOT an atomic main ref CAS.
    return {
        "decision": "ELIGIBLE_FOR_MANAGED_MERGE",
        "read_only": True, "remote_main_sha": main, "candidate_sha": candidate,
        "pr_number": pr_number, "github_run_id": run_id,
        "tested_merge_sha": tested_merge, "required_checked": len(pinned),
        "trusted_gate_blobs": blobs, "host_snapshot_signature_verified": True,
        "branch_protection_verified": True, "remote_main_cas": False,
        "git_writes": False, "deployment": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("host",))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--expected-main-sha", required=True)
    parser.add_argument("--expected-candidate-sha", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--host-snapshot", required=True)
    args = parser.parse_args(argv)
    try:
        try:
            envelope = json.loads(Path(args.host_snapshot).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HostHoldError("host_snapshot_unavailable") from exc
        token = os.environ.get("LFL_PREMERGE_HOST_GITHUB_TOKEN", "")
        public_key = os.environ.get("LFL_PREMERGE_HOST_SNAPSHOT_PUBKEY", "")
        client = GitHubReadOnly(args.repo, token)
        result = evaluate_host(
            client, repo=args.repo, pr_number=args.pr,
            main=args.expected_main_sha, candidate=args.expected_candidate_sha,
            run_id=args.run_id, envelope=envelope,
            snapshot_public_key=public_key, now=time.time(),
        )
        code = 0
    except HostHoldError as exc:
        code = 3 if exc.unavailable else 1
        result = {"decision": "HOLD", "reason": exc.reason, "exit_code": code,
                  "read_only": True, "remote_main_cas": False,
                  "git_writes": False, "deployment": False}
    except Exception:
        code = 3
        result = {"decision": "HOLD", "reason": "host_unexpected_error",
                  "exit_code": code, "read_only": True,
                  "remote_main_cas": False, "git_writes": False, "deployment": False}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())

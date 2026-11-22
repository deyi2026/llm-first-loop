#!/usr/bin/env python3
"""Low-risk GitHub PR integration. Never deploys, restarts or changes protection.

The protected GitHub merge endpoint is the final CAS/authorization authority.
A stale head/base, untrusted check publisher, risky path, or missing CI is HOLD.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_MINIMUM_CHECKS = frozenset(
    {
        "门禁（pytest + ruff + pyright）",
        "安全扫描（敏感/私密/错误文件拦截）",
        "managed-premerge-evidence",
        "privacy-gate",
        "A.5 架构提交审查（机械 presence/coverage）",
    }
)
_LOW_PREFIXES = ("docs/", "tests/unit/", "src/llm_loop/", "examples/")
_HIGH_PREFIXES = (
    ".github/",
    "scripts/",
    "docs/governance/",
    "src/llm_loop/core/",
    "src/llm_loop/introspection/",
    "src/llm_loop/runtime/",
    "src/llm_loop/tools/",
    "src/llm_loop/web/",
    "src/llm_loop/llm/",
)
_HIGH_TOKENS = frozenset(
    {
        "auth",
        "authentication",
        "authorization",
        "secret",
        "credential",
        "token",
        "sandbox",
        "security",
        "approval",
        "policy",
        "premerge",
        "release",
        "deploy",
        "permission",
        "signing",
        "issuer",
        "host",
        "service",
        "control",
        "git",
        "lane",
        "queue",
        "guard",
        "password",
        "login",
        "config",
        "factory",
        "ci",
        "workflow",
        "workflow_dispatch",
    }
)


class GitHub(Protocol):
    def get(self, path: str) -> Any: ...
    def merge(self, repo: str, pr: int, head: str) -> Any: ...


class GhCli:
    """No shell, no credential output, no mutation except the protected merge API."""

    def _call(self, args: list[str]) -> Any:
        try:
            completed = subprocess.run(
                ["gh", "api", *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=40,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"github_unavailable:{type(exc).__name__}") from exc
        if completed.returncode != 0:
            # Do not echo gh stderr: it may contain credentials or request details.
            raise RuntimeError(f"github_api_rejected:exit_{completed.returncode}")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("github_invalid_json") from exc

    def get(self, path: str) -> Any:
        return self._call([path])

    def merge(self, repo: str, pr: int, head: str) -> Any:
        return self._call(
            [
                "-X",
                "PUT",
                f"repos/{repo}/pulls/{pr}/merge",
                "-f",
                f"sha={head}",
                "-f",
                "merge_method=merge",
            ]
        )


@dataclass(frozen=True)
class Result:
    decision: str
    reason: str
    head: str
    base: str
    risk: str = "unknown"
    merge_commit: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "head_sha": self.head,
            "base_sha": self.base,
            "risk": self.risk,
            "merge_commit": self.merge_commit,
            "deployment": "not_requested",
        }


def _valid_path(path: str) -> bool:
    return (
        bool(path)
        and not path.startswith("/")
        and "\\" not in path
        and ".." not in PurePosixPath(path).parts
        and PurePosixPath(path).as_posix() == path
    )


def _risky_path(path: str) -> bool:
    if not _valid_path(path):
        return True
    if any(path.startswith(prefix) for prefix in _HIGH_PREFIXES):
        return True
    if not any(path.startswith(prefix) for prefix in _LOW_PREFIXES):
        return True
    # A segment such as auth_gateway.py or security-policy.md is sensitive.
    for segment in PurePosixPath(path).parts:
        words = set(re.split(r"[^a-z0-9]+", segment.lower()))
        if words & _HIGH_TOKENS:
            return True
    return False


def _changed_paths(api: GitHub, repo: str, pr: int, count: int) -> list[dict]:
    if not isinstance(count, int) or not 1 <= count <= 100:
        raise ValueError("changed_files_out_of_scope")
    rows = api.get(f"repos/{repo}/pulls/{pr}/files?per_page=100&page=1")
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError("changed_files_incomplete")
    return rows


def _required_checks(api: GitHub, repo: str) -> dict[str, int]:
    protection = api.get(f"repos/{repo}/branches/main/protection")
    if not isinstance(protection, dict):
        raise ValueError("branch_protection_unavailable")
    checks = protection.get("required_status_checks") or {}
    if checks.get("strict") is not True:
        raise ValueError("main_not_strict")
    if (protection.get("enforce_admins") or {}).get("enabled") is not True:
        raise ValueError("main_admin_bypass_possible")
    declared = checks.get("checks")
    if not isinstance(declared, list):
        raise ValueError("required_checks_unpinned")
    required: dict[str, int] = {}
    for item in declared:
        if not isinstance(item, dict):
            raise ValueError("required_check_invalid")
        name, app_id = item.get("context"), item.get("app_id")
        if not isinstance(name, str) or not name or type(app_id) is not int or app_id <= 0:
            raise ValueError("required_check_untrusted_app")
        if name in required:
            raise ValueError("required_check_duplicate")
        required[name] = app_id
    if not _MINIMUM_CHECKS.issubset(required):
        raise ValueError("minimum_ci_protection_missing")

    raw = api.get(f"repos/{repo}/contents/docs/governance/required-ci-checks.json?ref=main")
    if not isinstance(raw, dict) or raw.get("encoding") != "base64":
        raise ValueError("trusted_policy_unavailable")
    try:
        doc = json.loads(base64.b64decode(raw["content"], validate=False))
        policy_rows = doc["checks"]
        policy = {row["context"]: row["app_id"] for row in policy_rows}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("trusted_policy_invalid") from exc
    if (
        doc.get("schema") != "lfl.required_checks.v1"
        or len(policy) != len(policy_rows)
        or policy != required
    ):
        raise ValueError("required_checks_policy_mismatch")
    return required


def _check_ci(api: GitHub, repo: str, head: str, required: dict[str, int]) -> str:
    raw = api.get(f"repos/{repo}/commits/{head}/check-runs?per_page=100")
    if not isinstance(raw, dict) or not isinstance(raw.get("check_runs"), list):
        raise ValueError("check_runs_unavailable")
    if raw.get("total_count", 101) > 100:
        raise ValueError("check_runs_incomplete")
    latest: dict[str, dict] = {}
    for run in raw["check_runs"]:
        if not isinstance(run, dict):
            continue
        name = run.get("name")
        if name not in required or (run.get("app") or {}).get("id") != required[name]:
            continue
        if run.get("head_sha") != head:
            continue
        if name not in latest or int(run.get("id") or 0) > int(latest[name].get("id") or 0):
            latest[name] = run
    if set(latest) != set(required):
        return "WAIT:required_check_missing"
    for run in latest.values():
        if run.get("status") != "completed":
            return "WAIT:required_check_pending"
        if run.get("conclusion") != "success":
            return "HOLD:required_check_not_success"
    return "PASS"


def assess(api: GitHub, repo: str, pr: int, head: str, base: str) -> Result:
    """Read-only, deterministic decision; never turns missing evidence into PASS."""
    try:
        if (
            not _REPO.fullmatch(repo)
            or repo.split("/")[0] in (".", "..")
            or repo.split("/")[1] in (".", "..")
            or not _SHA.fullmatch(head)
            or not _SHA.fullmatch(base)
            or pr <= 0
        ):
            return Result("HOLD", "invalid_identity", head, base)
        pull = api.get(f"repos/{repo}/pulls/{pr}")
        if not isinstance(pull, dict):
            raise ValueError("pull_unavailable")
        if pull.get("state") != "open" or pull.get("draft") is not False:
            return Result("HOLD", "pr_not_open_and_ready", head, base)
        if pull.get("head", {}).get("sha") != head:
            return Result("HOLD", "head_sha_changed", head, base)
        if pull.get("head", {}).get("repo", {}).get("full_name") != repo:
            return Result("HOLD", "cross_repo_pr_requires_review", head, base)
        if pull.get("base", {}).get("ref") != "main" or pull.get("base", {}).get("sha") != base:
            return Result("HOLD", "base_sha_changed", head, base)
        main = api.get(f"repos/{repo}/git/ref/heads/main")
        if main.get("object", {}).get("sha") != base:
            return Result("HOLD", "main_advanced", head, base)
        rows = _changed_paths(api, repo, pr, pull.get("changed_files"))
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("changed_files_invalid")
            if row.get("status") not in ("added", "modified") or _risky_path(
                str(row.get("filename") or "")
            ):
                return Result("HOLD", "high_risk_requires_independent_review", head, base, "high")
        required = _required_checks(api, repo)
        ci = _check_ci(api, repo, head, required)
        if ci != "PASS":
            decision, reason = ci.split(":", 1)
            return Result(decision, reason, head, base, "low")
        if pull.get("mergeable") is not True or pull.get("mergeable_state") != "clean":
            return Result("HOLD", "github_mergeability_not_clean", head, base, "low")
        return Result("READY", "protected_ci_green", head, base, "low")
    except (ValueError, TypeError, AttributeError, KeyError, RuntimeError) as exc:
        return Result("HOLD", str(exc)[:120], head, base)


class MergeSlotBusyError(RuntimeError):
    """Another LFL Lane owns the short merge critical section."""


@contextmanager
def local_merge_slot(audit_dir: Path) -> Iterator[None]:
    """Use the existing MergeQueueStore flock; do not invent a second lock."""
    if not (audit_dir / "merge_queue.jsonl").is_file():
        raise RuntimeError("merge_queue_unavailable")
    try:
        from llm_loop.introspection.merge_queue import MergeQueueStore
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from llm_loop.introspection.merge_queue import MergeQueueStore
    store = MergeQueueStore(audit_dir, create=False)
    with store._file_lock():
        holder = store._holder_row(store._read_rows())
        if holder is not None:
            raise MergeSlotBusyError("merge_slot_busy")
        yield


def _default_audit_dir() -> Path:
    """Find the shared Git common dir from any linked worktree."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return Path(result.stdout.strip()).resolve().parent / "data" / "audit"


def integrate(
    api: GitHub,
    repo: str,
    pr: int,
    head: str,
    base: str,
    *,
    apply: bool,
    slot_guard: Callable[[], Any] | None = None,
) -> Result:
    result = assess(api, repo, pr, head, base)
    if result.decision != "READY" or not apply:
        return result
    if slot_guard is None:
        return Result("HOLD", "merge_slot_guard_missing", head, base, "low")
    # Only the short final recheck + protected GitHub merge holds the shared lock.
    try:
        with slot_guard():
            again = assess(api, repo, pr, head, base)
            if again.decision != "READY":
                return again
            response = api.merge(repo, pr, head)
            if response.get("merged") is not True or not _SHA.fullmatch(
                str(response.get("sha") or "")
            ):
                return Result("HOLD", "merge_response_unverified", head, base, "low")
            post = api.get(f"repos/{repo}/pulls/{pr}")
            if (
                post.get("merged") is not True
                or post.get("head", {}).get("sha") != head
                or post.get("merge_commit_sha") != response["sha"]
            ):
                return Result("HOLD", "merge_postcondition_unverified", head, base, "low")
            return Result(
                "MERGED", "github_protected_merge_confirmed", head, base, "low", response["sha"]
            )
    except MergeSlotBusyError:
        return Result("WAIT", "merge_slot_busy", head, base, "low")
    except (ValueError, TypeError, AttributeError, KeyError, RuntimeError, OSError) as exc:
        return Result("HOLD", f"merge_unverified:{type(exc).__name__}", head, base, "low")


def main(argv: list[str] | None = None, *, api: GitHub | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub owner/repository")
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument(
        "--apply", action="store_true", help="Perform protected merge; default read-only"
    )
    parser.add_argument(
        "--audit-dir", type=Path, help="Shared LFL audit directory; inferred from git common dir"
    )
    parser.add_argument(
        "--wait-seconds", type=int, default=0, help="Wait for CI up to 3600 seconds"
    )
    args = parser.parse_args(argv)
    if not 0 <= args.wait_seconds <= 3600:
        parser.error("--wait-seconds must be between 0 and 3600")
    github = api if api is not None else GhCli()
    try:
        audit_dir = args.audit_dir or (_default_audit_dir() if args.apply else None)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print(
            json.dumps(
                Result(
                    "HOLD", "audit_dir_unavailable", args.expected_head, args.expected_base
                ).as_dict()
            )
        )
        return 4
    guard = (lambda: local_merge_slot(audit_dir)) if audit_dir is not None else None
    deadline = time.monotonic() + args.wait_seconds
    while True:
        result = integrate(
            github,
            args.repo,
            args.pr,
            args.expected_head,
            args.expected_base,
            apply=args.apply,
            slot_guard=guard,
        )
        if result.decision != "WAIT" or time.monotonic() >= deadline:
            print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
            return {"READY": 0, "MERGED": 0, "WAIT": 3, "HOLD": 4}[result.decision]
        time.sleep(min(15, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    sys.exit(main())

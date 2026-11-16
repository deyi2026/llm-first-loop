#!/usr/bin/env python3
"""premerge_gate.py --mode ci (B1-1, DESIGN-20261116 v1.9).

Read-only premerge CI gate over a frozen/trusted GitHub run event identity
and the results of the four sibling jobs of .github/workflows/ci.yml
(security-scan / test / linux-installer / ambient-env-gate).

Contract:
- Inputs come ONLY from CLI args (frozen/trusted run event data); no network,
  no repository mutations, no side effects.
- PASS iff all four required sibling needs are present, each with
  result == "success" and (when run_id present) the same run_id as the event,
  and the event identity is complete and non-conflicting. Fail-closed on
  anything else.
- Output: machine-consumable JSON receipt on stdout; exit 0 only on PASS.
  branch_protection.host_verified is always False here (the Host-side
  verification of branch protection is NOT claimed by this script).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

REQUIRED_JOBS = (
    "security-scan",
    "test",
    "linux-installer",
    "ambient-env-gate",
)

KNOWN_EVENTS = ("push", "pull_request")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Read-only premerge CI gate (B1-1)")
    p.add_argument("--mode", required=True, choices=("ci",))
    p.add_argument("--event", required=True, help="GitHub event name (push|pull_request)")
    p.add_argument("--run-id", type=int, required=True, help="GitHub Actions run id")
    p.add_argument("--head-sha", default=None, help="push event head SHA")
    p.add_argument("--pr-head-sha", default=None)
    p.add_argument("--pr-base-sha", default=None)
    p.add_argument("--pr-merge-sha", default=None)
    p.add_argument("--needs-json", default=None,
                   help="JSON object {job: {result, run_id?}} for the four siblings")
    p.add_argument("--bind-repo-blobs", action="store_true",
                   help="read-only SHA1 Git blob binding of three gate paths")
    p.add_argument("--need", action="append", default=[],
                   help="repeatable: job=result[@run_id], e.g. test=success@424242")
    return p


def _parse_needs(args: argparse.Namespace,
                 reasons: list[str]) -> dict[str, dict[str, Any]] | None:
    if args.needs_json is not None and args.need:
        reasons.append("input_conflict:needs-json-and-need")
        return None
    if args.needs_json is not None:
        try:
            raw = json.loads(args.needs_json)
        except json.JSONDecodeError as exc:
            reasons.append(f"malformed_needs_json:{exc.msg}")
            return None
        if not isinstance(raw, dict):
            reasons.append("malformed_needs_json:not-an-object")
            return None
        return raw
    if args.need:
        needs: dict[str, dict[str, Any]] = {}
        for item in args.need:
            if "@" in item:
                spec, _, run_raw = item.rpartition("@")
                try:
                    run_id = int(run_raw)
                except ValueError:
                    reasons.append(f"malformed_need:{item}")
                    return None
            else:
                spec, run_id = item, None
            job, sep, result = spec.partition("=")
            if not sep or not job or not result:
                reasons.append(f"malformed_need:{item}")
                return None
            needs[job] = {"result": result}
            if run_id is not None:
                needs[job]["run_id"] = run_id
        return needs
    reasons.append("missing_needs_input")
    return None


def run_gate(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    args = _build_parser().parse_args(argv)
    reasons: list[str] = []
    identity: dict[str, Any] = {}
    event = args.event
    if event not in KNOWN_EVENTS:
        reasons.append(f"unknown_event:{event}")
        receipt = {
            "mode": "ci", "verdict": "error", "event": event,
            "run_id": args.run_id, "required_jobs": list(REQUIRED_JOBS),
            "identity": identity, "same_run": False, "all_success": False,
            "read_only": True, "branch_protection": {"host_verified": False},
            "reasons": reasons, "exit_code": 2,
        }
        return 2, receipt

    pr_flags_used = any(
        v is not None
        for v in (args.pr_head_sha, args.pr_base_sha, args.pr_merge_sha)
    )
    if event == "push":
        if not args.head_sha:
            reasons.append("identity_incomplete:push-head-sha-missing")
        else:
            identity["push_head_sha"] = args.head_sha
        if pr_flags_used:
            reasons.append("identity_conflict:pr-flags-with-push-event")
    else:  # pull_request
        if args.head_sha:
            reasons.append("identity_conflict:head-sha-with-pr-event")
        if args.pr_head_sha:
            identity["pr_head_sha"] = args.pr_head_sha
        if args.pr_base_sha:
            identity["pr_base_sha"] = args.pr_base_sha
        if args.pr_merge_sha:
            identity["pr_merge_sha"] = args.pr_merge_sha
        if not args.pr_head_sha or not args.pr_base_sha:
            reasons.append("identity_incomplete:pr-head-or-base-missing")

    if any(r.startswith("identity_conflict") for r in reasons):
        receipt = {
            "mode": "ci", "verdict": "error", "event": event,
            "run_id": args.run_id, "required_jobs": list(REQUIRED_JOBS),
            "identity": identity, "same_run": False, "all_success": False,
            "read_only": True, "branch_protection": {"host_verified": False},
            "reasons": reasons, "exit_code": 2,
        }
        return 2, receipt

    needs = _parse_needs(args, reasons)
    if needs is None:
        verdict = "error"
        exit_code = 2
        same_run = all_success = False
    else:
        for job in sorted(set(needs) - set(REQUIRED_JOBS)):
            reasons.append(f"unexpected_need:{job}")
        same_run = True
        all_success = True
        for job in REQUIRED_JOBS:
            entry = needs.get(job)
            if not isinstance(entry, dict) or not entry:
                reasons.append(f"missing_need:{job}")
                all_success = False
                continue
            result = entry.get("result")
            entry_run = entry.get("run_id", args.run_id)
            if entry_run != args.run_id:
                reasons.append(
                    f"identity_mismatch:{job}:run_id={entry_run}!={args.run_id}"
                )
                same_run = False
            if result != "success":
                reasons.append(f"need_not_success:{job}:{result}")
                all_success = False
        if sum(1 for r in reasons if r.startswith("unexpected_need:")) > 0:
            all_success = False
        verdict = "pass" if (all_success and same_run and not reasons) else "fail"
        exit_code = 0 if verdict == "pass" else 1

    receipt = {
        "mode": "ci", "verdict": verdict, "event": event,
        "run_id": args.run_id, "required_jobs": list(REQUIRED_JOBS),
        "identity": identity, "same_run": same_run, "all_success": all_success,
        "read_only": True, "branch_protection": {"host_verified": False},
        "reasons": reasons, "exit_code": exit_code,
    }
    if args.bind_repo_blobs:
        try:
            from pathlib import Path

            from premerge_host import _GATE_PATHS, _blob_sha

            blobs = {}
            for name in _GATE_PATHS:
                path = Path(name)
                if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
                    raise OSError("gate_path_unavailable")
                blobs[name] = _blob_sha(path.read_bytes())
            receipt["gate_blobs"] = blobs
        except (OSError, ValueError):
            receipt["reasons"].append("gate_blob_binding_unavailable")
            receipt["verdict"] = "error"
            receipt["exit_code"] = 2
            exit_code = 2
    return exit_code, receipt


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--mode=host" in args or (
        "--mode" in args and args.index("--mode") + 1 < len(args)
        and args[args.index("--mode") + 1] == "host"
    ):
        from premerge_host import main as host_main

        return host_main(args)
    exit_code, receipt = run_gate(args)
    json.dump(receipt, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Finish a *staged* LFL Linux wheel cutover using existing managed service-control.

The official installer must already have installed the candidate with --no-start,
and the three LFL units must be stopped safely by the operator. This command
never installs a wheel, stops services, forces restart, or rolls back on its own.
Default is read-only plan; --execute authorizes publish-wheel and managed restart.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

SERVICES = ("lfl.service", "lfl-feishu.service", "lfl-learning.service")
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
ACTION_RE = re.compile(r"svc-[a-z0-9]+\Z")


def load_json(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"expected JSON object: {path}")
    return obj


def check_staged(root: Path, version: str, sha: str) -> None:
    active = root / ".LFL-active-version"
    manifest = root / "releases" / f"LFL-{version}" / ".installer-wheel.sha256"
    release = manifest.parent
    if active.is_symlink() or active.read_text(encoding="ascii").strip() != version:
        raise ValueError("staged active pointer mismatch")
    if release.is_symlink() or not release.is_dir() or manifest.is_symlink():
        raise ValueError("unsafe staged release layout")
    row = manifest.read_text(encoding="ascii").strip().split()
    if len(row) != 2 or row[0] != sha or row[1] != f"llm_first_loop-{version}-py3-none-any.whl":
        raise ValueError("staged wheel SHA manifest mismatch")
    if not (release / "venv" / "bin" / "python").is_file():
        raise ValueError("staged release Python missing")


def service_inactive() -> None:
    for unit in SERVICES:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", unit], check=False, capture_output=True,
            text=True, timeout=8,
        )
        if result.stdout.strip() != "inactive":
            raise RuntimeError(f"cutover requires {unit} inactive after operator idle check")


def call_svcctl(python: Path, *args: str) -> dict:
    cp = subprocess.run(
        [str(python), "-m", "llm_loop.runtime.service_control", *args],
        check=True, capture_output=True, text=True, timeout=40,
    )
    # `service_control restart` deliberately writes two JSON Lines records:
    # the immediate accepted receipt, then the detached/terminal action view.
    # `publish-wheel` writes one.  Treat stdout as JSONL and consume the final
    # record; parsing the entire stream as one JSON document raises
    # JSONDecodeError("Extra data") *after* publish/restart side effects occurred.
    records: list[dict] = []
    for line_number, line in enumerate(cp.stdout.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"service_control {args[0] if args else '<unknown>'} "
                f"emitted invalid JSONL at stdout line {line_number}"
            ) from exc
        if not isinstance(value, dict):
            raise ValueError(
                f"service_control {args[0] if args else '<unknown>'} "
                f"emitted non-object JSONL at stdout line {line_number}"
            )
        records.append(value)
    if not records:
        raise ValueError("service_control returned empty JSONL stdout")
    command = args[0] if args else "<unknown>"
    if command == "restart":
        if len(records) != 2:
            raise ValueError("service_control restart must emit accepted + final JSONL records")
        if any(not item.get("action_id") for item in records):
            raise ValueError("service_control restart JSONL record missing action_id")
    action_ids = {str(item["action_id"]) for item in records if item.get("action_id")}
    if len(action_ids) > 1:
        raise ValueError("service_control JSONL records refer to different actions")
    return records[-1]


def wait_for_action(data: Path, action_id: str, timeout_s: int) -> dict:
    if ACTION_RE.fullmatch(action_id) is None:
        raise ValueError("invalid managed restart action id")
    path = data / "runtime" / "service-control-actions" / f"{action_id}.json"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.is_file():
            action = load_json(path)
            if action.get("action_id") != action_id:
                raise RuntimeError("action receipt identity mismatch")
            if action.get("status") in {"failed", "cancelled", "rejected"}:
                raise RuntimeError(f"restart ended {action.get('status')}: {action.get('detail')}")
            if action.get("status") == "succeeded":
                if action.get("verify_verdict") != "confirmed_ok":
                    raise RuntimeError("restart succeeded without confirmed_ok")
                return action
        time.sleep(2)
    raise TimeoutError("restart worker not terminal; inspect durable action, do not retry blindly")


def converge(root: Path, host: str, version: str, sha: str, generation: int) -> Path:
    audit = root / "audit"
    audit.mkdir(mode=0o700, parents=True, exist_ok=True)
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    receipt = audit / f"managed-convergence-{version}-gen{generation}-{timestamp}.json"
    cp = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("verify_managed_release.py")),
         "--expected-host", host, "--install-root", str(root),
         "--expected-version", version, "--expected-generation", str(generation),
         "--expected-sha", sha, "--receipt", str(receipt)],
        check=False, text=True, capture_output=True, timeout=40,
    )
    if cp.returncode != 0:
        raise RuntimeError(f"managed convergence rejected: {cp.stderr.strip()} {cp.stdout[-600:]}")
    result = load_json(receipt)
    if result.get("result") != "PASS":
        raise RuntimeError("convergence receipt did not say PASS")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--prior-generation", required=True, type=int)
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--install-root", type=Path, default=Path.home() / ".local/share/lfl")
    parser.add_argument("--execute", action="store_true",
                        help="Publish + restart; default only prints a read-only plan")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args(argv)
    if not VERSION_RE.fullmatch(args.version) or not SHA_RE.fullmatch(args.sha):
        parser.error("--version and --sha must be exact, frozen identities")
    if args.prior_generation < 1 or not 1 <= args.timeout <= 1800:
        parser.error("invalid prior generation or timeout")
    if socket.gethostname() != args.expected_host:
        parser.error("host does not match frozen --expected-host")
    untrusted_root = args.install_root.expanduser()
    if untrusted_root.is_symlink():
        parser.error("install root must not be a symlink")
    root = untrusted_root.resolve()
    data = root / "data"
    try:
        desired = load_json(data / "runtime" / "managed_service_deployment.json")
        check_staged(root, args.version, args.sha)
        new_gen = args.prior_generation + 1
        if desired.get("generation") == new_gen and desired.get("version") == args.version:
            if desired.get("wheel_sha256") != args.sha:
                raise ValueError("same generation already assigned to a different wheel")
            if not args.execute:
                print(json.dumps({"result": "PLAN_ALREADY_DEPLOYED", "next_generation": new_gen,
                                  "version": args.version, "sha": args.sha}))
                return 0
            receipt = converge(root, args.expected_host, args.version, args.sha, new_gen)
            print(json.dumps({"result": "ALREADY_CONVERGED", "receipt": str(receipt)}))
            return 0
        if desired.get("generation") != args.prior_generation or desired.get("version") == args.version:
            raise ValueError("prior desired identity changed; CAS precondition failed")
        if desired.get("artifact_kind") != "wheel_release":
            raise ValueError("prior deployment is not a wheel release")
        previous = (root / ".LFL-previous-version").read_text(encoding="ascii").strip()
        if desired.get("version") != previous:
            raise ValueError("previous pointer does not match current deployed version")
        python = root / "releases" / f"LFL-{previous}" / "venv" / "bin" / "python"
        if not python.is_file():
            raise ValueError("prior release CLI is missing")
        if not args.execute:
            print(json.dumps({"result": "PLAN_ONLY", "prior_generation": args.prior_generation,
                              "next_generation": new_gen, "version": args.version,
                              "sha": args.sha, "host": args.expected_host}))
            return 0
        service_inactive()
        new = call_svcctl(python, "publish-wheel", "--lfl-home", str(root),
                          "--data-dir", str(data),
                          "--expected-generation", str(args.prior_generation))
        if (new.get("generation") != new_gen or new.get("version") != args.version
                or new.get("wheel_sha256") != args.sha):
            raise RuntimeError("publish-wheel returned a different identity; stop")
        accepted = call_svcctl(python, "restart", "--data-dir", str(data),
                               "--target", "all", "--requester", "managed-wheel-cutover")
        action_id = str(accepted.get("action_id") or "")
        wait_for_action(data, action_id, args.timeout)
        receipt = converge(root, args.expected_host, args.version, args.sha, new_gen)
        print(json.dumps({"result": "PASS", "action_id": action_id, "receipt": str(receipt)}))
        return 0
    except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.SubprocessError) as exc:
        print(f"FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read-only, fail-closed live convergence check for LFL managed Linux releases."""
from __future__ import annotations

import argparse
import datetime
import email.utils
import json
import os
import re
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

UNITS = {
    "web": "lfl.service",
    "feishu": "lfl-feishu.service",
    "learning": "lfl-learning.service",
}


def fetch_json(url: str) -> tuple[dict, str]:
    req = urllib.request.Request(
        url, headers={"Cache-Control": "no-cache, no-store", "Pragma": "no-cache"}
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        if response.status != 200:
            raise RuntimeError(f"{url}: HTTP {response.status}")
        date = response.headers.get("Date", "")
        data = json.load(response)
    if not isinstance(data, dict):
        raise ValueError(f"{url}: expected JSON object")
    if not date:
        raise ValueError(f"{url}: no HTTP Date header; cannot verify freshness")
    server_date = email.utils.parsedate_to_datetime(date)
    elapsed = abs((datetime.datetime.now(datetime.UTC) - server_date).total_seconds())
    if elapsed > 120:
        raise ValueError(f"{url}: stale or clock-drifted response: {round(elapsed)} seconds")
    return data, date


def unit_show(unit: str) -> dict[str, str]:
    out = subprocess.check_output(
        ["systemctl", "--user", "show", unit,
         "-p", "MainPID", "-p", "ActiveState", "-p", "SubState",
         "--no-pager"],
        text=True,
        timeout=8,
    )
    return dict(row.split("=", 1) for row in out.splitlines() if "=" in row)


def check(
    status: dict,
    health: dict,
    deployment: dict,
    active: str,
    installer_sha: str,
    service_units: dict[str, dict[str, str]],
    *,
    version: str,
    sha: str,
    generation: int,
) -> tuple[list[str], dict]:
    problems: list[str] = []
    def require(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    desired = status.get("deployment") or {}
    require(deployment == desired, "API desired differs from on-disk authoritative deployment")
    require(desired.get("generation") == generation, "desired generation mismatch")
    require(desired.get("version") == version, "desired version mismatch")
    require(desired.get("artifact_kind") == "wheel_release", "desired is not wheel_release")
    require(desired.get("wheel_sha256") == sha, "desired wheel SHA mismatch")
    require(active == version, "active version pointer differs from expected")
    require(installer_sha == sha, "installed wheel manifest SHA mismatch")
    require(not status.get("admission_barriers"), "active admission barrier(s) found")
    require(health.get("status") == "ok", "Web health not ok")
    require(health.get("version") == version, "Web health version mismatch")
    build = health.get("build") or {}
    require(build.get("release_version") == version, "Web build version mismatch")
    require(build.get("wheel_sha256") == sha, "Web build wheel SHA mismatch")

    observed: dict[str, dict] = {}
    for name, unit in UNITS.items():
        service = (status.get("services") or {}).get(name) or {}
        live, stable, verify = (
            service.get("live") or {},
            service.get("stable") or {},
            service.get("verify") or {},
        )
        os_state = service_units.get(name) or {}
        pid = str(live.get("pid") or "")
        require(bool(pid) and pid != "0" and live.get("pid_alive") is True,
                f"{name}: PID not live")
        require(live.get("release_version") == version, f"{name}: live version mismatch")
        require(live.get("wheel_sha256") == sha, f"{name}: live SHA mismatch")
        require(live.get("matches_desired_generation") is True,
                f"{name}: live does not match desired")
        require(stable.get("generation") == generation, f"{name}: stable generation mismatch")
        require(stable.get("matches_desired_generation") is True,
                f"{name}: stable does not match desired")
        require(verify.get("generation") == generation and verify.get("outcome") == "ok",
                f"{name}: missing current-generation verification")
        require(verify.get("action_status") == "succeeded" and
                verify.get("durable_succeeded_receipt") is True,
                f"{name}: durable succeeded receipt absent")
        require(service.get("restart_required") is False and not service.get("reasons"),
                f"{name}: requires restart or has unresolved reason(s)")
        require(service.get("terminal_action_barrier") is None,
                f"{name}: terminal action barrier")
        require(os_state.get("ActiveState") == "active" and
                os_state.get("SubState") == "running",
                f"{name}: systemd unit not running")
        require(os_state.get("MainPID") == pid, f"{name}: systemd PID disagrees with live")
        observed[name] = {
            "pid": pid,
            "live_version": live.get("release_version"),
            "stable_generation": stable.get("generation"),
            "verify_action_id": verify.get("action_id"),
            "unit": unit,
            "systemd": os_state.get("ActiveState"),
        }

    receipt = {
        "schema": "lfl.managed-release-convergence/v1",
        "checked_at_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "hostname": socket.gethostname(),
        "expected_version": version,
        "expected_generation": generation,
        "expected_wheel_sha256": sha,
        "deployment_id": desired.get("deployment_id"),
        "services": observed,
        "knowledge_status": (health.get("knowledge") or {}).get("status"),
        "knowledge_writes_enabled": (health.get("knowledge") or {}).get("writes_enabled"),
        "result": "PASS" if not problems else "FAIL",
        "problems": problems,
    }
    return problems, receipt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--expected-version", required=True)
    ap.add_argument("--expected-generation", required=True, type=int)
    ap.add_argument("--expected-sha", required=True)
    ap.add_argument("--expected-host", default="")
    ap.add_argument("--install-root", type=Path, default=Path.home() / ".local/share/lfl")
    ap.add_argument("--local-url", default="http://127.0.0.1:8903")
    ap.add_argument("--receipt", type=Path)
    args = ap.parse_args()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.expected_version):
        ap.error("expected version must be MAJOR.MINOR.PATCH")
    if not re.fullmatch(r"[a-f0-9]{64}", args.expected_sha):
        ap.error("expected SHA must be 64 lowercase hexadecimal characters")
    if args.expected_generation < 1:
        ap.error("expected generation must be positive")
    if args.expected_host and socket.gethostname() != args.expected_host:
        print(f"FAIL wrong host: expected {args.expected_host!r}, got {socket.gethostname()!r}",
              file=sys.stderr)
        return 2
    if args.local_url != "http://127.0.0.1:8903":
        ap.error("only the local loopback API is supported; no remote credentials")
    try:
        root = args.install_root
        status, api_date = fetch_json(args.local_url + "/api/v1/services/status")
        health, health_date = fetch_json(args.local_url + "/health")
        deployment = json.loads((root / "data/runtime/managed_service_deployment.json").read_text())
        active = (root / ".LFL-active-version").read_text().strip()
        manifest = root / f"releases/LFL-{args.expected_version}/.installer-wheel.sha256"
        line = manifest.read_text().splitlines()[0].strip()
        parts = line.split()
        installer_sha = parts[0] if len(parts) == 2 else ""
        if len(parts) != 2 or not parts[1].endswith(".whl"):
            raise ValueError("wheel manifest is not a verified sha256 + filename line")
        units = {name: unit_show(unit) for name, unit in UNITS.items()}
        problems, receipt = check(
            status, health, deployment, active, installer_sha, units,
            version=args.expected_version,
            sha=args.expected_sha,
            generation=args.expected_generation,
        )
        receipt["status_api_date"] = api_date
        receipt["health_api_date"] = health_date
    except Exception as exc:
        problems = [f"{type(exc).__name__}: {exc}"]
        receipt = {
            "schema": "lfl.managed-release-convergence/v1",
            "checked_at_utc": datetime.datetime.now(datetime.UTC).isoformat(),
            "hostname": socket.gethostname(),
            "expected_version": args.expected_version,
            "expected_generation": args.expected_generation,
            "expected_wheel_sha256": args.expected_sha,
            "result": "FAIL",
            "problems": problems,
        }
    print(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False))
    if args.receipt:
        # Preserve audit history even on retry or concurrent operator calls.
        args.receipt.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = args.receipt.with_name(f".{args.receipt.name}.{os.getpid()}.tmp")
        try:
            with tmp.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            tmp.chmod(0o600)
            # Atomic create-only: EEXIST rather than overwriting any old PASS.
            os.link(tmp, args.receipt)
        except FileExistsError:
            print(f"FAIL receipt already exists: {args.receipt}", file=sys.stderr)
            return 3
        finally:
            tmp.unlink(missing_ok=True)
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Physical systemd restart backend for the existing managed-service worker."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from llm_loop.runtime.installation import _MANAGED_UNIT_NAMES


def restart_units(lfl_home: Path, target: str) -> int:
    services = tuple(_MANAGED_UNIT_NAMES) if target == "all" else (target,)
    if any(service not in _MANAGED_UNIT_NAMES for service in services):
        raise ValueError("wheel restart supports web, feishu, learning, all")
    launcher = str(lfl_home.resolve() / "bin/lfl-service")
    for service in services:
        unit = _MANAGED_UNIT_NAMES[service]
        observed = subprocess.run(
            ["systemctl", "--user", "show", unit, "-p", "ExecStart", "--value"],
            capture_output=True, text=True, check=True, timeout=15,
        ).stdout
        if f"path={launcher} ;" not in observed or f"argv[]={launcher} {service} ;" not in observed:
            raise ValueError(f"{unit} is not bound to the managed service launcher")
    for unit in ("lfl-recovery.service", *(_MANAGED_UNIT_NAMES[s] for s in services)):
        result = subprocess.run(
            ["systemctl", "--user", "restart", unit], check=False,
            timeout=150 if unit == "lfl-recovery.service" else 90,
        )
        if result.returncode:
            return result.returncode
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lfl-home", required=True, type=Path)
    parser.add_argument("--target", choices=("web", "feishu", "learning", "all"), required=True)
    args = parser.parse_args(argv)
    return restart_units(args.lfl_home, args.target)


if __name__ == "__main__":
    raise SystemExit(main())

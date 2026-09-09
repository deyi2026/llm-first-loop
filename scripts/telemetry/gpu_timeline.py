#!/usr/bin/env python3
"""Prompt-neutral Apple GPU/process sampler for local LLM experiments.

Reads AGX PerformanceStatistics through ioreg (no sudo) and optional process CPU/RSS
through ps. Writes JSONL facts only; it does not import or modify LFL runtime state.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_PERF_RE = re.compile(r'"PerformanceStatistics" = \{([^}]*)\}')
_INT_FIELDS = {
    "device_utilization_pct": "Device Utilization %",
    "renderer_utilization_pct": "Renderer Utilization %",
    "tiler_utilization_pct": "Tiler Utilization %",
    "in_use_system_memory_bytes": "In use system memory",
    "alloc_system_memory_bytes": "Alloc system memory",
}


def parse_ioreg(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {key: None for key in _INT_FIELDS}
    match = _PERF_RE.search(text)
    if not match:
        return out
    body = match.group(1)
    for key, raw_name in _INT_FIELDS.items():
        field = re.search(rf'"{re.escape(raw_name)}"=(\d+)', body)
        if field:
            out[key] = int(field.group(1))
    return out


def sample_ioreg() -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["/usr/sbin/ioreg", "-r", "-c", "AGXAccelerator", "-d", "1"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        parsed = parse_ioreg(proc.stdout)
        parsed["ioreg_ok"] = proc.returncode == 0 and parsed["device_utilization_pct"] is not None
        if proc.returncode != 0:
            parsed["ioreg_error"] = f"exit={proc.returncode}"
        return parsed
    except Exception as exc:  # telemetry must stay fail-open
        return {
            **{key: None for key in _INT_FIELDS},
            "ioreg_ok": False,
            "ioreg_error": type(exc).__name__,
        }


def sample_process(pid: int | None) -> dict[str, Any]:
    if not pid:
        return {"process_pid": None, "process_alive": None}
    try:
        proc = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "%cpu=,%mem=,rss="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        row = proc.stdout.strip().split()
        if proc.returncode != 0 or len(row) < 3:
            return {"process_pid": pid, "process_alive": False}
        return {
            "process_pid": pid,
            "process_alive": True,
            "process_cpu_pct": float(row[0]),
            "process_mem_pct": float(row[1]),
            "process_rss_kib": int(row[2]),
        }
    except Exception as exc:  # telemetry must stay fail-open
        return {"process_pid": pid, "process_alive": None, "process_error": type(exc).__name__}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--pid", type=int, default=None)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    if args.interval <= 0 or args.duration <= 0:
        ap.error("--interval and --duration must be > 0")

    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    deadline = start + args.duration
    samples = 0
    with path.open("a", encoding="utf-8") as fh:
        while True:
            tick = time.monotonic()
            if tick >= deadline:
                break
            record: dict[str, Any] = {
                "ts_utc": utc_now(),
                "monotonic_s": tick,
                "label": args.label,
            }
            record.update(sample_ioreg())
            record.update(sample_process(args.pid))
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            samples += 1
            elapsed = time.monotonic() - tick
            time.sleep(max(0.0, args.interval - elapsed))
    print(
        json.dumps(
            {"output": str(path), "samples": samples, "duration_s": time.monotonic() - start}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

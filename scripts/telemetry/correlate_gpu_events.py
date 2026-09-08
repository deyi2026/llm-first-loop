#!/usr/bin/env python3
"""Correlate prompt-neutral GPU JSONL samples with LFL request/tool event timing."""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_samples(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        row["_dt"] = _dt(str(row["ts_utc"]))
        rows.append(row)
    return rows


def _num(rows: list[dict[str, Any]], key: str) -> list[float]:
    return [float(r[key]) for r in rows if isinstance(r.get(key), (int, float))]


def summarize_window(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gpu = _num(rows, "device_utilization_pct")
    cpu = _num(rows, "process_cpu_pct")
    if not gpu:
        return {"samples": len(rows), "gpu_samples": 0}
    low_runs: list[int] = []
    current = 0
    for value in gpu:
        if value <= 30:
            current += 1
        elif current:
            low_runs.append(current)
            current = 0
    if current:
        low_runs.append(current)
    return {
        "samples": len(rows),
        "gpu_samples": len(gpu),
        "gpu_avg_pct": round(statistics.fmean(gpu), 2),
        "gpu_median_pct": round(statistics.median(gpu), 2),
        "gpu_p90_pct": round(sorted(gpu)[max(0, int(0.9 * (len(gpu) - 1)))], 2),
        "gpu_ge80_ratio": round(sum(v >= 80 for v in gpu) / len(gpu), 4),
        "gpu_le30_ratio": round(sum(v <= 30 for v in gpu) / len(gpu), 4),
        "longest_low_run_samples": max(low_runs, default=0),
        "process_cpu_avg_pct": round(statistics.fmean(cpu), 2) if cpu else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True)
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--event-dir", required=True)
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    # Local import is deliberate: the sampler itself has zero LFL coupling; only this
    # offline correlator reads durable event facts.
    from llm_loop.event_log.store import EventStore

    samples = load_samples(Path(args.samples))
    store = EventStore(Path(args.event_dir), enabled=True)
    events = list(store.read(args.session_id) or [])

    open_requests: dict[int, Any] = {}
    windows: list[dict[str, Any]] = []
    for event in events:
        payload = event.payload or {}
        round_no = int(payload.get("round") or 0)
        if event.type == "request.meta" and round_no:
            open_requests[round_no] = event
        elif event.type == "request.usage" and round_no and round_no in open_requests:
            start = open_requests.pop(round_no)
            start_dt = _dt(str(start.ts))
            end_dt = _dt(str(event.ts))
            inside = [r for r in samples if start_dt <= r["_dt"] <= end_dt]
            raw_timing = payload.get("timing")
            timing: dict[str, Any] = raw_timing if isinstance(raw_timing, dict) else {}
            row = {
                "round": round_no,
                "start_utc": str(start.ts),
                "end_utc": str(event.ts),
                "wall_ms": round((end_dt - start_dt).total_seconds() * 1000.0, 2),
                "tokens_in": payload.get("tokens_in"),
                "tokens_out": payload.get("tokens_out"),
                "tokens_cache_hit": payload.get("tokens_cache_hit"),
                "provider_total_ms": timing.get("provider_total_ms"),
                "first_delta_ms": timing.get("first_delta_ms"),
                "first_visible_ms": timing.get("first_visible_ms"),
                "first_tool_call_ms": timing.get("first_tool_call_ms"),
            }
            row.update(summarize_window(inside))
            windows.append(row)

    result = {
        "session_id": args.session_id,
        "sample_file": args.samples,
        "sample_count": len(samples),
        "request_windows": windows,
        "note": "GPU facts are observational only; no certainty/quality label is inferred.",
    }
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Offline Effective Reasoning Duty Cycle (ERDC) timeline analysis.

ERDC is observational only. It aligns durable LFL event facts with prompt-neutral GPU
samples and reports physical compute duty plus mechanical observation novelty. It does
not infer model certainty, answer quality, relevance, retry desirability, or completion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _event_ts(event: dict[str, Any]) -> datetime:
    return _dt(str(event["ts"]))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_gpu_samples(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    rows = load_jsonl(path)
    for row in rows:
        row["_dt"] = _dt(str(row["ts_utc"]))
    rows.sort(key=lambda row: row["_dt"])
    return rows


def _median_gap_ms(samples: list[dict[str, Any]]) -> float:
    gaps = [
        (samples[i + 1]["_dt"] - samples[i]["_dt"]).total_seconds() * 1000.0
        for i in range(len(samples) - 1)
        if samples[i + 1]["_dt"] > samples[i]["_dt"]
    ]
    return statistics.median(gaps) if gaps else 0.0


def summarize_gpu_interval(
    samples: list[dict[str, Any]], start: datetime, end: datetime
) -> dict[str, Any]:
    """Time-weight AGX utilization over [start, end) using sample-and-hold spans."""
    if end <= start or not samples:
        return {
            "gpu_coverage_ms": 0.0,
            "gpu_equivalent_ms": 0.0,
            "gpu_time_weighted_avg_pct": None,
            "gpu_ge80_ms": 0.0,
            "gpu_le30_ms": 0.0,
        }

    fallback_ms = _median_gap_ms(samples)
    coverage = equivalent = ge80 = le30 = 0.0
    for idx, row in enumerate(samples):
        row_start = row["_dt"]
        if idx + 1 < len(samples):
            row_end = samples[idx + 1]["_dt"]
        elif fallback_ms > 0:
            row_end = row_start + timedelta(milliseconds=fallback_ms)
        else:
            continue
        seg_start = max(start, row_start)
        seg_end = min(end, row_end)
        if seg_end <= seg_start:
            continue
        util = row.get("device_utilization_pct")
        if not isinstance(util, (int, float)):
            continue
        span = (seg_end - seg_start).total_seconds() * 1000.0
        coverage += span
        equivalent += span * float(util) / 100.0
        if util >= 80:
            ge80 += span
        if util <= 30:
            le30 += span

    return {
        "gpu_coverage_ms": round(coverage, 2),
        "gpu_equivalent_ms": round(equivalent, 2),
        "gpu_time_weighted_avg_pct": (
            round(100.0 * equivalent / coverage, 2) if coverage > 0 else None
        ),
        "gpu_ge80_ms": round(ge80, 2),
        "gpu_le30_ms": round(le30, 2),
    }


def _interval_union_ms(intervals: Iterable[tuple[datetime, datetime]]) -> float:
    rows = sorted((a, b) for a, b in intervals if b > a)
    if not rows:
        return 0.0
    total = 0.0
    cur_start, cur_end = rows[0]
    for start, end in rows[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            total += (cur_end - cur_start).total_seconds() * 1000.0
            cur_start, cur_end = start, end
    total += (cur_end - cur_start).total_seconds() * 1000.0
    return total


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("payload")
    return value if isinstance(value, dict) else {}


def _result_fingerprint(payload: dict[str, Any]) -> str | None:
    """Use durable result hash when present; never interpret result text semantically."""
    value = payload.get("result_state_sha256")
    if isinstance(value, str) and value:
        return value
    # Conservative fallback for older events with no result hash: fingerprint only
    # bounded mechanical fields, not prose meaning.
    fallback = {
        "tool_name": payload.get("tool_name"),
        "status": payload.get("status"),
        "result_state_chars": payload.get("result_state_chars"),
    }
    if all(value in (None, "") for value in fallback.values()):
        return None
    raw = json.dumps(fallback, sort_keys=True, separators=(",", ":"), default=str)
    return "fallback:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def split_runs(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Partition a session event stream at run.end so round numbers may safely reset."""
    runs: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for event in events:
        current.append(event)
        if event.get("type") == "run.end":
            runs.append(current)
            current = []
    if current and any(event.get("type") == "request.meta" for event in current):
        runs.append(current)
    return runs


def analyze_run(
    events: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    *,
    run_index: int,
    seen_result_fps: set[str],
) -> dict[str, Any]:
    metas = [event for event in events if event.get("type") == "request.meta"]
    usages = [event for event in events if event.get("type") == "request.usage"]
    run_end = next((event for event in reversed(events) if event.get("type") == "run.end"), None)
    finished = [event for event in events if event.get("type") == "tool.execution.finished"]
    started_by_id = {
        str(_payload(event).get("execution_id") or ""): event
        for event in events
        if event.get("type") == "tool.execution.started"
    }

    usage_by_round: dict[int, list[dict[str, Any]]] = {}
    for event in usages:
        round_no = int(_payload(event).get("round") or 0)
        usage_by_round.setdefault(round_no, []).append(event)

    finished_by_round: dict[int, list[dict[str, Any]]] = {}
    for event in finished:
        round_no = int(_payload(event).get("round") or 0)
        finished_by_round.setdefault(round_no, []).append(event)

    rows: list[dict[str, Any]] = []
    for idx, meta in enumerate(metas):
        mp = _payload(meta)
        round_no = int(mp.get("round") or 0)
        candidates = usage_by_round.get(round_no) or []
        usage = next((item for item in candidates if _event_ts(item) >= _event_ts(meta)), None)
        if usage is None:
            continue
        usage_by_round[round_no] = [item for item in candidates if item is not usage]

        start = _event_ts(meta)
        provider_end = _event_ts(usage)
        if idx + 1 < len(metas):
            cycle_end = _event_ts(metas[idx + 1])
        elif run_end is not None:
            cycle_end = _event_ts(run_end)
        else:
            cycle_end = provider_end
        if cycle_end < provider_end:
            cycle_end = provider_end

        up = _payload(usage)
        raw_timing = up.get("timing")
        timing: dict[str, Any] = raw_timing if isinstance(raw_timing, dict) else {}
        provider_total_ms = timing.get("provider_total_ms")
        if not isinstance(provider_total_ms, (int, float)):
            provider_total_ms = (provider_end - start).total_seconds() * 1000.0
        first_delta_ms = timing.get("first_delta_ms")
        first_reasoning_ms = timing.get("first_reasoning_ms")
        first_visible_ms = timing.get("first_visible_ms")
        first_tool_ms = timing.get("first_tool_call_ms")

        generation_start = (
            start + timedelta(milliseconds=float(first_delta_ms))
            if isinstance(first_delta_ms, (int, float))
            else provider_end
        )
        generation_start = min(max(generation_start, start), provider_end)

        reasoning_start = None
        reasoning_end = None
        if isinstance(first_reasoning_ms, (int, float)):
            reasoning_start = start + timedelta(milliseconds=float(first_reasoning_ms))
            if isinstance(first_visible_ms, (int, float)):
                reasoning_end = start + timedelta(milliseconds=float(first_visible_ms))
            elif isinstance(first_tool_ms, (int, float)):
                reasoning_end = start + timedelta(milliseconds=float(first_tool_ms))
            else:
                reasoning_end = provider_end
            reasoning_start = min(max(reasoning_start, start), provider_end)
            reasoning_end = min(max(reasoning_end, reasoning_start), provider_end)

        provider_gpu = summarize_gpu_interval(samples, start, provider_end)
        pre_delta_gpu = summarize_gpu_interval(samples, start, generation_start)
        generation_gpu = summarize_gpu_interval(samples, generation_start, provider_end)
        reasoning_gpu = (
            summarize_gpu_interval(samples, reasoning_start, reasoning_end)
            if reasoning_start is not None and reasoning_end is not None
            else None
        )

        tool_intervals: list[tuple[datetime, datetime]] = []
        tool_duration_sum_ms = 0.0
        novel = repeated = unhashed = 0
        for event in finished_by_round.get(round_no, []):
            finish_ts = _event_ts(event)
            if finish_ts < provider_end or finish_ts > cycle_end:
                continue
            fp = _result_fingerprint(_payload(event))
            if fp is None:
                unhashed += 1
            elif fp in seen_result_fps:
                repeated += 1
            else:
                novel += 1
                seen_result_fps.add(fp)
            execution_id = str(_payload(event).get("execution_id") or "")
            started = started_by_id.get(execution_id)
            if started is not None:
                a, b = _event_ts(started), finish_ts
                if b > a:
                    tool_intervals.append((a, b))
                    tool_duration_sum_ms += (b - a).total_seconds() * 1000.0

        cycle_ms = max(0.0, (cycle_end - start).total_seconds() * 1000.0)
        cache_read = up.get("cache_read_tokens")
        tokens_in = up.get("tokens_in")
        uncached = up.get("uncached_prompt_tokens")
        if (
            not isinstance(uncached, (int, float))
            and isinstance(tokens_in, (int, float))
            and isinstance(cache_read, (int, float))
        ):
            uncached = max(0, tokens_in - cache_read)

        physical_erdc = (
            generation_gpu["gpu_equivalent_ms"] / cycle_ms
            if cycle_ms > 0 and generation_gpu["gpu_coverage_ms"] > 0
            else None
        )
        provider_compute_duty = (
            provider_gpu["gpu_equivalent_ms"] / cycle_ms
            if cycle_ms > 0 and provider_gpu["gpu_coverage_ms"] > 0
            else None
        )
        hashed_results = novel + repeated
        observation_yield = novel / hashed_results if hashed_results else None

        rows.append(
            {
                "round": round_no,
                "request_start_utc": str(meta["ts"]),
                "provider_end_utc": str(usage["ts"]),
                "cycle_end_utc": str(cycle_end.isoformat()),
                "cycle_ms": round(cycle_ms, 2),
                "provider_total_ms": round(float(provider_total_ms), 2),
                "provider_share_of_cycle": round(float(provider_total_ms) / cycle_ms, 4)
                if cycle_ms > 0
                else None,
                "first_delta_ms": first_delta_ms,
                "first_reasoning_ms": first_reasoning_ms,
                "first_visible_ms": first_visible_ms,
                "first_tool_call_ms": first_tool_ms,
                "tokens_in": tokens_in,
                "tokens_out": up.get("tokens_out"),
                "cache_read_tokens": cache_read,
                "uncached_prompt_tokens": uncached,
                "cache_reuse_ratio": (
                    round(float(cache_read) / float(tokens_in), 4)
                    if isinstance(cache_read, (int, float))
                    and isinstance(tokens_in, (int, float))
                    and tokens_in
                    else None
                ),
                "tool_calls_finished": len(finished_by_round.get(round_no, [])),
                "tool_elapsed_union_ms": round(_interval_union_ms(tool_intervals), 2),
                "tool_wait_share_of_cycle": (
                    round(_interval_union_ms(tool_intervals) / cycle_ms, 4)
                    if cycle_ms > 0
                    else None
                ),
                "tool_duration_sum_ms": round(tool_duration_sum_ms, 2),
                "novel_observation_results": novel,
                "repeated_observation_results": repeated,
                "unhashed_observation_results": unhashed,
                "observation_yield_ratio": round(observation_yield, 4)
                if observation_yield is not None
                else None,
                "gpu_provider": provider_gpu,
                "gpu_pre_first_delta": pre_delta_gpu,
                "gpu_generation": generation_gpu,
                "gpu_reasoning": reasoning_gpu,
                "physical_erdc": round(physical_erdc, 4) if physical_erdc is not None else None,
                "provider_compute_duty": round(provider_compute_duty, 4)
                if provider_compute_duty is not None
                else None,
            }
        )

    return {
        "run_index": run_index,
        "run_end_reason": _payload(run_end).get("reason") if run_end is not None else None,
        "rounds": rows,
    }


def analyze_session(events: list[dict[str, Any]], samples: list[dict[str, Any]]) -> dict[str, Any]:
    session_id = str(events[0].get("session_id") or "") if events else ""
    seen_result_fps: set[str] = set()
    runs = [
        analyze_run(run, samples, run_index=index + 1, seen_result_fps=seen_result_fps)
        for index, run in enumerate(split_runs(events))
    ]
    return {
        "session_id": session_id,
        "runs": runs,
        "definitions": {
            "physical_erdc": "generation-stage GPU-equivalent milliseconds divided by round cycle milliseconds",
            "provider_compute_duty": "whole-provider GPU-equivalent milliseconds divided by round cycle milliseconds",
            "observation_yield_ratio": "previously unseen durable tool-result fingerprints divided by hashed tool results",
            "cache_reuse_ratio": "cache_read_tokens divided by input tokens",
        },
        "authority_boundary": (
            "Observational only. No field infers certainty, semantic relevance, answer quality, "
            "retry desirability, or completion; observation novelty is exact mechanical identity only."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--event-dir", required=True)
    ap.add_argument("--gpu-samples", default="")
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    event_path = Path(args.event_dir) / f"{args.session_id}.jsonl"
    events = load_jsonl(event_path)
    if not events:
        raise SystemExit(f"no events found: {event_path}")
    samples = load_gpu_samples(Path(args.gpu_samples) if args.gpu_samples else None)
    result = analyze_session(events, samples)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

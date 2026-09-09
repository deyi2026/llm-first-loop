#!/usr/bin/env python3
"""Microbenchmark the only new per-request O(payload) causal-core operation.

The normal request.meta path already serializes messages+tools once to count provider-visible
chars.  Causal Core reuses that exact serialization and adds one SHA256 plus compact metadata
assembly.  This script measures only that incremental work; it does not call an LLM.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time


def _measure(size: int, iterations: int) -> dict[str, float]:
    payload = {
        "messages": [{"role": "user", "content": "x" * size}],
        "tools": [],
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        fp = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]
        influence = {
            "ingress": {"storage_messages": 1, "eligible_messages": 1},
            "history": {"history_total_chars": size, "effective_budget": size * 2},
            "recent_continuity": {"applied": False},
            "provider_structure_fp": fp,
        }
        assert influence["provider_structure_fp"]
        samples.append((time.perf_counter_ns() - t0) / 1_000_000)
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return {
        "median_ms": statistics.median(samples),
        "p95_ms": p95,
        "max_ms": max(samples),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=300)
    args = parser.parse_args()
    for size in (100_000, 1_000_000):
        result = _measure(size, args.iterations)
        print(size, json.dumps(result, sort_keys=True))
        limit = 0.2 if size == 100_000 else 0.5
        if result["p95_ms"] >= limit:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

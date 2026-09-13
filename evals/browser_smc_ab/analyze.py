#!/usr/bin/env python3
"""Offline mechanical scorer for Browser SMC real-model A/B."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def _num(rows: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value: Any = row
        for part in key.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(part)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    return values


def _summary(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    arm_rows = [row for row in rows if row.get("arm") == arm]
    out: dict[str, Any] = {
        "runs": len(arm_rows),
        "task_pass": sum(bool((row.get("oracle") or {}).get("pass")) for row in arm_rows),
        "status_pass": sum(row.get("status") == "PASS" for row in arm_rows),
        "infra_fail": sum(row.get("status") in {"INFRA_FAIL", "TIMEOUT", "INVALID"} for row in arm_rows),
    }
    for label, key in (
        ("rounds", "worker.rounds"),
        ("tool_calls", "worker.tool_call_count"),
        ("tokens_in", "worker.tokens_in"),
        ("tokens_out", "worker.tokens_out"),
        ("cache_hit_tokens", "worker.cache_hit_tokens"),
        ("wall_s", "wall_s"),
    ):
        values = _num(arm_rows, key)
        out[label] = {
            "observed": len(values),
            "median": round(statistics.median(values), 3) if values else None,
            "mean": round(statistics.mean(values), 3) if values else None,
        }
    return out


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pairs: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        pairs[(str(row["task_id"]), int(row["repeat"]))][str(row["arm"])] = row
    paired: list[dict[str, Any]] = []
    for (task_id, repeat), arms in sorted(pairs.items()):
        if set(arms) != {"smc", "legacy"}:
            continue
        smc, legacy = arms["smc"], arms["legacy"]
        item: dict[str, Any] = {
            "task_id": task_id,
            "repeat": repeat,
            "smc_pass": bool((smc.get("oracle") or {}).get("pass")),
            "legacy_pass": bool((legacy.get("oracle") or {}).get("pass")),
        }
        for name, key in (
            ("rounds_delta_smc_minus_legacy", "rounds"),
            ("tool_calls_delta_smc_minus_legacy", "tool_call_count"),
            ("tokens_in_delta_smc_minus_legacy", "tokens_in"),
            ("tokens_out_delta_smc_minus_legacy", "tokens_out"),
        ):
            a, b = (smc.get("worker") or {}).get(key), (legacy.get("worker") or {}).get(key)
            item[name] = a - b if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
        paired.append(item)
    smc_rows = [row for row in rows if row.get("arm") == "smc"]
    return {
        "schema": "smc.browser_real_model_ab.analysis.v0.2",
        "total_runs": len(rows),
        "arms": {arm: _summary(rows, arm) for arm in ("smc", "legacy")},
        "paired": paired,
        "smc_safety": {
            "automatic_retry_true_total": sum(int(((row.get("worker") or {}).get("receipt_facts") or {}).get("automatic_retry_true_count") or 0) for row in smc_rows),
            "receipt_rejected_total": sum(int(((row.get("worker") or {}).get("receipt_facts") or {}).get("rejected_count") or 0) for row in smc_rows),
            "receipt_failed_total": sum(int(((row.get("worker") or {}).get("receipt_facts") or {}).get("failed_count") or 0) for row in smc_rows),
            "receipt_ok_total": sum(int(((row.get("worker") or {}).get("receipt_facts") or {}).get("ok_count") or 0) for row in smc_rows),
            "scope_blocker_total": sum(int(((row.get("worker") or {}).get("receipt_facts") or {}).get("scope_blocker_count") or 0) for row in smc_rows),
            "security_agent_spawned_runs": sum(bool(row.get("security_agent_spawned")) for row in smc_rows),
        },
        "limitations": [
            "paired directional evidence only; no significance claim",
            "cache/token telemetry is descriptive because provider tool-schema prefixes differ by arm",
            "task success comes only from predeclared loopback external-state oracles",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in Path(args.results).read_text(encoding="utf-8").splitlines() if line.strip()]
    result = analyze(rows)
    Path(args.output_json).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

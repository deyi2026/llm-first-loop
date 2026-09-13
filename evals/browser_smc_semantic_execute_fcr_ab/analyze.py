#!/usr/bin/env python3
"""Offline mechanical analysis for Browser full-action vs semantic-execute smoke."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

ARMS = ("full_action", "semantic_execute")


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
    selected = [row for row in rows if row.get("arm") == arm]
    out: dict[str, Any] = {
        "runs": len(selected),
        "task_pass": sum(bool((row.get("oracle") or {}).get("pass")) for row in selected),
        "status_pass": sum(row.get("status") == "PASS" for row in selected),
        "infra_fail": sum(
            row.get("status") in {"INFRA_FAIL", "TIMEOUT", "INVALID"} for row in selected
        ),
        "smc_adopted": sum(bool((row.get("worker") or {}).get("smc_adopted")) for row in selected),
        "mutation_failure_calls": sum(
            int((row.get("worker") or {}).get("mutation_failure_call_count") or 0)
            for row in selected
        ),
    }
    for label, key in (
        ("rounds", "worker.rounds"),
        ("tool_calls", "worker.tool_call_count"),
        ("tokens_in", "worker.tokens_in"),
        ("tokens_out", "worker.tokens_out"),
        ("cache_hit_tokens", "worker.cache_hit_tokens"),
        ("wall_s", "wall_s"),
    ):
        values = _num(selected, key)
        out[label] = {
            "observed": len(values),
            "median": round(statistics.median(values), 3) if values else None,
            "mean": round(statistics.mean(values), 3) if values else None,
        }
    return out


def _receipt_total(rows: list[dict[str, Any]], key: str) -> int:
    return sum(
        int(((row.get("worker") or {}).get("receipt_facts") or {}).get(key) or 0)
        for row in rows
    )


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pairs: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        pairs[(str(row["task_id"]), int(row["repeat"]))][str(row["arm"])] = row
    paired: list[dict[str, Any]] = []
    for (task_id, repeat), arms in sorted(pairs.items()):
        if set(arms) != set(ARMS):
            continue
        control = arms["full_action"]
        treatment = arms["semantic_execute"]
        item: dict[str, Any] = {
            "task_id": task_id,
            "repeat": repeat,
            "full_action_pass": bool((control.get("oracle") or {}).get("pass")),
            "semantic_execute_pass": bool((treatment.get("oracle") or {}).get("pass")),
        }
        for name, key in (
            ("rounds_delta_semantic_minus_full", "rounds"),
            ("tool_calls_delta_semantic_minus_full", "tool_call_count"),
            ("tokens_in_delta_semantic_minus_full", "tokens_in"),
            ("tokens_out_delta_semantic_minus_full", "tokens_out"),
            ("wall_s_delta_semantic_minus_full", "wall_s"),
        ):
            a = (treatment.get("worker") or {}).get(key) if key != "wall_s" else treatment.get("wall_s")
            b = (control.get("worker") or {}).get(key) if key != "wall_s" else control.get("wall_s")
            item[name] = (
                round(float(a) - float(b), 3)
                if isinstance(a, (int, float)) and isinstance(b, (int, float))
                else None
            )
        paired.append(item)

    mechanics: dict[str, Any] = {}
    for arm in ARMS:
        selected = [row for row in rows if row.get("arm") == arm]
        reasons: dict[str, int] = {}
        for row in selected:
            counts = ((row.get("worker") or {}).get("receipt_facts") or {}).get(
                "reason_counts"
            ) or {}
            for reason, count in counts.items():
                reasons[str(reason)] = reasons.get(str(reason), 0) + int(count)
        mechanics[arm] = {
            "receipt_ok_total": _receipt_total(selected, "ok_count"),
            "object_ok_total": _receipt_total(selected, "object_ok_count"),
            "navigate_ok_total": _receipt_total(selected, "navigate_ok_count"),
            "receipt_rejected_total": _receipt_total(selected, "rejected_count"),
            "receipt_failed_total": _receipt_total(selected, "failed_count"),
            "automatic_retry_true_total": _receipt_total(
                selected, "automatic_retry_true_count"
            ),
            "scope_blocker_total": _receipt_total(selected, "scope_blocker_count"),
            "rejection_reasons": dict(sorted(reasons.items())),
            "security_agent_spawned_runs": sum(
                bool(row.get("security_agent_spawned")) for row in selected
            ),
        }

    return {
        "schema": "smc.browser_semantic_execute_fcr_ab.analysis.v0.4",
        "total_runs": len(rows),
        "arms": {arm: _summary(rows, arm) for arm in ARMS},
        "paired": paired,
        "mechanics": mechanics,
        "limitations": [
            "three paired tasks are a directional smoke, not a statistical significance study",
            "the intended intervention is the whole mutation interface contract: full SemanticAction tool versus thin semantic_execute tool",
            "browser_perceive and get_tool_schema are held identical across arms",
            "Method discovery/search is intentionally unavailable so this tests the tool's own usage description",
            "task success is judged only by predeclared loopback external-state oracles",
            "cache and wall-time are descriptive because all rows share one sequential local model server",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args()
    rows = [
        json.loads(line)
        for line in Path(args.results).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    result = analyze(rows)
    Path(args.output_json).write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

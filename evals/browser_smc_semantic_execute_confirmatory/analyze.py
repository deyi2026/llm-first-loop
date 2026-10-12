#!/usr/bin/env python3
"""Offline analysis for semantic_execute treatment-only confirmatory qualification."""

from __future__ import annotations

import argparse
import json
import statistics
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


def _receipt(row: dict[str, Any], key: str) -> int:
    return int(((row.get("worker") or {}).get("receipt_facts") or {}).get(key) or 0)


def _stat(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = _num(rows, key)
    return {
        "observed": len(values),
        "median": round(statistics.median(values), 3) if values else None,
        "mean": round(statistics.mean(values), 3) if values else None,
        "min": round(min(values), 3) if values else None,
        "max": round(max(values), 3) if values else None,
    }


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    per_task: dict[str, Any] = {}
    for task_id in ("click_commit", "fill_submit", "delayed_wait"):
        selected = [row for row in rows if row.get("task_id") == task_id]
        per_task[task_id] = {
            "runs": len(selected),
            "task_pass": sum(bool((row.get("oracle") or {}).get("pass")) for row in selected),
            "status_pass": sum(row.get("status") == "PASS" for row in selected),
            "smc_adopted": sum(bool((row.get("worker") or {}).get("smc_adopted")) for row in selected),
            "navigate_ok": sum(_receipt(row, "navigate_ok_count") for row in selected),
            "object_ok": sum(_receipt(row, "object_ok_count") for row in selected),
            "scope_blockers": sum(_receipt(row, "scope_blocker_count") for row in selected),
            "wall_s": _stat(selected, "wall_s"),
        }

    return {
        "schema": "smc.browser_semantic_execute_confirmatory.analysis.v0.5",
        "total_runs": len(rows),
        "task_pass": sum(bool((row.get("oracle") or {}).get("pass")) for row in rows),
        "status_pass": sum(row.get("status") == "PASS" for row in rows),
        "infra_fail": sum(row.get("status") in {"INFRA_FAIL", "TIMEOUT", "INVALID"} for row in rows),
        "smc_adopted": sum(bool((row.get("worker") or {}).get("smc_adopted")) for row in rows),
        "receipt_ok_total": sum(_receipt(row, "ok_count") for row in rows),
        "object_ok_total": sum(_receipt(row, "object_ok_count") for row in rows),
        "navigate_ok_total": sum(_receipt(row, "navigate_ok_count") for row in rows),
        "receipt_rejected_total": sum(_receipt(row, "rejected_count") for row in rows),
        "scope_blocker_total": sum(_receipt(row, "scope_blocker_count") for row in rows),
        "automatic_retry_true_total": sum(_receipt(row, "automatic_retry_true_count") for row in rows),
        "invalid_target_ref_failures_non_gate": sum(int((row.get("worker") or {}).get("invalid_target_ref_failure_count") or 0) for row in rows),
        "wait_contract_failures_non_gate": sum(int((row.get("worker") or {}).get("wait_contract_failure_count") or 0) for row in rows),
        "rounds": _stat(rows, "worker.rounds"),
        "tool_calls": _stat(rows, "worker.tool_call_count"),
        "tokens_in": _stat(rows, "worker.tokens_in"),
        "tokens_out": _stat(rows, "worker.tokens_out"),
        "cache_hit_tokens": _stat(rows, "worker.cache_hit_tokens"),
        "wall_s": _stat(rows, "wall_s"),
        "per_task": per_task,
        "limitations": [
            "six local Ornith treatment-only runs are confirmatory for this frozen task set, not statistical generalization",
            "legacy full_action is historical context only and does not participate in infra validity or the gate",
            "task success is judged only by predeclared loopback external-state oracles",
            "invalid target_ref and wait contract failures are observed residual-FCR diagnostics, not post-hoc gate additions",
            "cache/token/wall metrics are descriptive because all rows share one sequential local model server",
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

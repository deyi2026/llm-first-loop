#!/usr/bin/env python3
"""Offline mechanical scorer for compact Method Card OFF/ON A/B."""

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
        if set(arms) != {"card_off", "card_on"}:
            continue
        off, on = arms["card_off"], arms["card_on"]
        item: dict[str, Any] = {
            "task_id": task_id,
            "repeat": repeat,
            "card_off_pass": bool((off.get("oracle") or {}).get("pass")),
            "card_on_pass": bool((on.get("oracle") or {}).get("pass")),
            "card_on_method_hydrated": bool((on.get("worker") or {}).get("method_hydrated")),
        }
        for name, key in (
            ("rounds_delta_on_minus_off", "rounds"),
            ("tool_calls_delta_on_minus_off", "tool_call_count"),
            ("tokens_in_delta_on_minus_off", "tokens_in"),
            ("tokens_out_delta_on_minus_off", "tokens_out"),
        ):
            a, b = (on.get("worker") or {}).get(key), (off.get("worker") or {}).get(key)
            item[name] = a - b if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
        paired.append(item)

    def receipt_total(arm_rows: list[dict[str, Any]], key: str) -> int:
        return sum(
            int(((row.get("worker") or {}).get("receipt_facts") or {}).get(key) or 0)
            for row in arm_rows
        )

    arm_rows = {
        arm: [row for row in rows if row.get("arm") == arm]
        for arm in ("card_off", "card_on")
    }
    rejection_reasons: dict[str, dict[str, int]] = {}
    for arm, selected in arm_rows.items():
        counts: dict[str, int] = {}
        for row in selected:
            reasons = ((row.get("worker") or {}).get("receipt_facts") or {}).get("reason_counts") or {}
            for reason, count in reasons.items():
                counts[str(reason)] = counts.get(str(reason), 0) + int(count)
        rejection_reasons[arm] = dict(sorted(counts.items()))

    return {
        "schema": "smc.browser_semantic_method_card_ab.analysis.v0.2",
        "total_runs": len(rows),
        "arms": {arm: _summary(rows, arm) for arm in ("card_off", "card_on")},
        "paired": paired,
        "method": {
            arm: {
                "available_runs": sum(bool((row.get("worker") or {}).get("method_available")) for row in selected),
                "exact_query_runs": sum(int((row.get("worker") or {}).get("method_exact_query_count") or 0) > 0 for row in selected),
                "hydrated_runs": sum(bool((row.get("worker") or {}).get("method_hydrated")) for row in selected),
                "method_search_calls": sum(int((row.get("worker") or {}).get("method_search_count") or 0) for row in selected),
            }
            for arm, selected in arm_rows.items()
        },
        "smc_mechanics": {
            arm: {
                "receipt_ok_total": receipt_total(selected, "ok_count"),
                "object_ok_total": receipt_total(selected, "object_ok_count"),
                "navigate_ok_total": receipt_total(selected, "navigate_ok_count"),
                "receipt_rejected_total": receipt_total(selected, "rejected_count"),
                "receipt_failed_total": receipt_total(selected, "failed_count"),
                "automatic_retry_true_total": receipt_total(selected, "automatic_retry_true_count"),
                "old_scope_blocker_total": receipt_total(selected, "scope_blocker_count"),
                "security_agent_spawned_runs": sum(bool(row.get("security_agent_spawned")) for row in selected),
                "rejection_reasons": rejection_reasons[arm],
            }
            for arm, selected in arm_rows.items()
        },
        "limitations": [
            "paired directional evidence only; no significance claim",
            "both arms expose the same full Method and the same tool parameters; only Browser tool descriptions carry the compact Method Card treatment",
            "Method exact hydration is observable but does not mechanically prove semantic application",
            "cache and wall-time remain descriptive because rows share one sequential local model server",
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

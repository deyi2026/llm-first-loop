#!/usr/bin/env python3
"""Offline scorer for completed P4-FCR results; never executes tools or calls a model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from protocol import ARM_B


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    b_rows = [row for row in rows if row.get("arm") == ARM_B]
    targeted_errors = sum(
        len((row.get("score") or {}).get("cross_binding_errors") or []) for row in b_rows
    )
    return {
        "rows": len(rows),
        "b_rows": len(b_rows),
        "b_structural_valid": sum(
            bool((row.get("score") or {}).get("first_call_structural_valid")) for row in b_rows
        ),
        "b_mechanical_valid": sum(
            bool((row.get("score") or {}).get("first_call_mechanical_valid")) for row in b_rows
        ),
        "b_targeted_cross_binding_errors": targeted_errors,
        "tool_execution_total": sum(int(row.get("tool_execution_count") or 0) for row in rows),
        "browser_runtime_rows": sum(bool(row.get("browser_runtime_used")) for row in rows),
        "fallback_rows": sum(bool(row.get("fallback_used")) for row in rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_jsonl")
    args = parser.parse_args()
    path = Path(args.results_jsonl)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(json.dumps(analyze(rows), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

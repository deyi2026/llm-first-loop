"""Classify and optionally execute the frozen P4-LIVE RED suite.

Exit 0 means all 20 probes matched their expected production-missing taxonomy and,
when --pytest is requested, pytest produced exactly 20 RED failures.  A harness error,
unexpected GREEN, taxonomy drift, or a different pytest failure shape exits non-zero.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from evals.smc_semantic_logic_p4_live.red_contracts import (
    EXPECTED_PATH,
    RED_IDS,
    ROOT,
    load_expected_failures,
    run_probe,
)

PROTOCOL_SHA = "e946eab26032aa4faa6698a3244ebd30c836cce1"
PARENT_FCR_SHA = "66f8d6147a67c4b439ca930149359674e500ba68"


def classify() -> tuple[bool, list[dict[str, Any]]]:
    expected = load_expected_failures()
    rows: list[dict[str, Any]] = []
    ok = True
    for row_id in RED_IDS:
        result = run_probe(row_id)
        expected_code = expected[row_id]["code"]
        taxonomy_match = result.failure_code == expected_code
        remains_red = not result.contract_satisfied
        row_ok = taxonomy_match and remains_red and result.failure_code != "harness_error"
        ok = ok and row_ok
        rows.append(
            {
                "id": row_id,
                "expected_code": expected_code,
                "observed_code": result.failure_code,
                "taxonomy_match": taxonomy_match,
                "contract_satisfied": result.contract_satisfied,
                "expected_red": remains_red,
                "row_ok": row_ok,
                "detail": result.detail,
                "facts": result.facts,
            }
        )
    return ok, rows


def run_pytest() -> dict[str, Any]:
    target = "tests/unit/test_smc_p4_live_actionref_red.py"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "--tb=short"],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = proc.stdout
    sanitized_output = output.replace(str(ROOT), "<repo>")
    failed_rows = re.findall(
        r"(?m)^FAILED tests/unit/test_smc_p4_live_actionref_red\.py::"
        r"test_p4_live_actionref_contract_red\[(P4L-R\d{2})\]$",
        sanitized_output,
    )
    exact_rows = tuple(failed_rows) == RED_IDS
    return {
        "command": f"python -m pytest {target} -q --tb=short",
        "exit_code": proc.returncode,
        "failed_rows": failed_rows,
        "exact_20_failed": exact_rows,
        "output_tail": "\n".join(sanitized_output.splitlines()[-60:]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pytest", action="store_true", help="also require exactly 20 pytest RED failures")
    parser.add_argument("--output", type=Path, help="optional evidence JSON path")
    args = parser.parse_args()

    classified, rows = classify()
    pytest_evidence: dict[str, Any] | None = run_pytest() if args.pytest else None
    pytest_ok = (
        True
        if pytest_evidence is None
        else pytest_evidence["exit_code"] == 1 and pytest_evidence["exact_20_failed"]
    )
    ok = classified and pytest_ok and len(rows) == 20
    evidence = {
        "schema": "smc.semantic_logic_p4_live_red_evidence.v0.1",
        "protocol_git_sha": PROTOCOL_SHA,
        "parent_fcr_qualified_sha": PARENT_FCR_SHA,
        "expected_failures_file": str(EXPECTED_PATH.relative_to(ROOT)),
        "production_src_modified": False,
        "real_browser_actions_executed": 0,
        "model_requests_sent": 0,
        "row_count": len(rows),
        "all_taxonomies_match": all(row["taxonomy_match"] for row in rows),
        "all_rows_remain_red": all(row["expected_red"] for row in rows),
        "harness_errors": [row["id"] for row in rows if row["observed_code"] == "harness_error"],
        "pytest": pytest_evidence,
        "qualified_red_freeze": ok,
        "rows": rows,
    }
    rendered = json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output is not None:
        output_path = args.output if args.output.is_absolute() else ROOT / args.output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

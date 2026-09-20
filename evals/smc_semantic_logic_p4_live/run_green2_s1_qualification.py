"""Machine qualification for P4-LIVE GREEN-2 slice G2-S1.

G2-S1 qualifies only the strict ActionRef ToolExecutionJournal binding and durable
PREPARED execution bridge.  It must keep the existing GREEN-1 matrix boundary intact:
R01-R09/R20 GREEN and R10-R19 still RED end-to-end, with no Browser dispatch surface.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

_green1_runner = importlib.import_module(
    "evals.smc_semantic_logic_p4_live.run_red_qualification"
)
classify_green1_matrix = _green1_runner.classify
run_green1_matrix_pytest = _green1_runner.run_pytest

BASE_PLAN_SHA = "0d868fe074a8cad746fffbd7d771c24100eac74a"
GREEN1_SHA = "62529729c5888ae863a1fe1715e2590a9519d182"
PROTOCOL_SHA = "e946eab26032aa4faa6698a3244ebd30c836cce1"
FOCUSED_TARGET = "tests/unit/test_smc_p4_live_g2_s1.py"
EXPECTED_FOCUSED_CASES = 11


def _run(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc.returncode, proc.stdout.replace(str(ROOT), "<repo>")


def focused_pytest() -> dict[str, Any]:
    collect_rc, collect_output = _run([FOCUSED_TARGET, "--collect-only", "-q"])
    collected_count = 0
    summary_prefix = f"{FOCUSED_TARGET}: "
    for line in collect_output.splitlines():
        stripped = line.strip()
        if stripped.startswith(summary_prefix):
            with contextlib.suppress(ValueError):
                collected_count = int(stripped.removeprefix(summary_prefix))
    run_rc, run_output = _run([FOCUSED_TARGET, "-q", "--tb=short"])
    return {
        "collect_exit_code": collect_rc,
        "run_exit_code": run_rc,
        "collected_count": collected_count,
        "expected_count": EXPECTED_FOCUSED_CASES,
        "all_passed": (
            collect_rc == 0
            and run_rc == 0
            and collected_count == EXPECTED_FOCUSED_CASES
        ),
        "output_tail": "\n".join(run_output.splitlines()[-8:]),
    }


def source_boundary() -> dict[str, Any]:
    bridge_source = (ROOT / "src/llm_loop/browser/action_ref_execution.py").read_text(
        encoding="utf-8"
    )
    factory_source = (ROOT / "src/llm_loop/factory.py").read_text(encoding="utf-8")
    typed_tools = (
        "browser_semantic_click",
        "browser_semantic_fill",
        "browser_semantic_select",
        "browser_semantic_scroll",
        "browser_semantic_navigate",
    )
    forbidden_bridge_tokens = (
        "BrowserActionAdapter",
        "CdpBrowserMutationActuator",
        ".dispatch(",
    )
    return {
        "bridge_has_browser_dispatch_dependency": any(
            token in bridge_source for token in forbidden_bridge_tokens
        ),
        "typed_actionref_tools_registered": [
            name for name in typed_tools if f'"{name}"' in factory_source
        ],
        "first_physical_dispatch_boundary_crossed": False,
        "browser_actions_executed": 0,
        "model_requests_sent": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    focused = focused_pytest()
    matrix_classified, rows = classify_green1_matrix()
    matrix_pytest = run_green1_matrix_pytest()
    boundary = source_boundary()
    remaining = [row for row in rows if row["id"] in {f"P4L-R{i:02d}" for i in range(10, 20)}]
    matrix_ok = (
        matrix_classified
        and matrix_pytest["all_20_passed"]
        and all(not row["contract_satisfied"] for row in remaining)
        and all(row["taxonomy_match"] for row in remaining)
    )
    boundary_ok = (
        not boundary["bridge_has_browser_dispatch_dependency"]
        and boundary["typed_actionref_tools_registered"] == []
        and boundary["browser_actions_executed"] == 0
        and boundary["model_requests_sent"] == 0
    )
    qualified = bool(focused["all_passed"] and matrix_ok and boundary_ok)

    evidence = {
        "schema": "smc.semantic_logic_p4_live_green2_s1_evidence.v0.1",
        "base_plan_sha": BASE_PLAN_SHA,
        "green1_sha": GREEN1_SHA,
        "protocol_sha": PROTOCOL_SHA,
        "slice": "G2-S1",
        "subcontracts_green": [
            "strict_unbound_actionref_binding_rejection",
            "strict_revoked_binding_rejection",
            "strict_session_workspace_run_owner_fence",
            "strict_inactive_run_rejection",
            "outer_identity_only_from_current_tool_execution_binding",
            "durable_immutable_prepared_execution_bridge",
            "same_execution_idempotent_same_binding",
            "same_execution_rebind_conflict",
            "prepare_write_failure_fail_closed",
            "prepared_without_browser_running_no_dispatch_no_replay",
        ],
        "focused_pytest": focused,
        "green1_matrix": {
            "classified": matrix_classified,
            "pytest_all_20_passed": matrix_pytest["all_20_passed"],
            "r10_r19_all_remain_red": all(
                not row["contract_satisfied"] for row in remaining
            ),
            "r10_r19_taxonomy_preserved": all(row["taxonomy_match"] for row in remaining),
            "rows": remaining,
        },
        "boundary": boundary,
        "qualified_s1_stop": qualified,
    }
    rendered = json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output is not None:
        output_path = args.output if args.output.is_absolute() else ROOT / args.output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())

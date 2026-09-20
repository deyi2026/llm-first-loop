"""Machine qualification for the P4-LIVE G2-S2 pre-GREEN stop boundary."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = (ROOT / "src").resolve()
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from evals.smc_semantic_logic_p4_live.green2_s2_red_contracts import (  # noqa: E402
    S2_RED_IDS,
    load_expected_failures,
    run_probe,
)

BASE_S1_SHA = "06891fd144c635f0625644a0c2c2ea24ed009e52"
PARENT_PLAN_SHA = "0d868fe074a8cad746fffbd7d771c24100eac74a"
PROTOCOL_SHA = "e946eab26032aa4faa6698a3244ebd30c836cce1"
PLAN_PATH = ROOT / "evals/smc_semantic_logic_p4_live/GREEN2-S2-PREGREEN-PLAN.v0.1.json"
FOCUSED_TARGET = "tests/unit/test_smc_p4_live_g2_s2_red.py"
EXPECTED_FOCUSED_CASES = 3
PARENT_CODES = {
    "P4L-R12": "browser_target_independent_first_bind_gap",
    "P4L-R14": "actionref_inner_action_id_bridge_absent",
    "P4L-R19": "actionref_version_guard_delegation_absent",
}


def _run(command: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc.returncode, proc.stdout.replace(str(ROOT), "<repo>")


def _pytest_evidence() -> dict[str, Any]:
    collect_rc, collect_output = _run(
        [sys.executable, "-m", "pytest", FOCUSED_TARGET, "--collect-only", "-q"]
    )
    collected_count = 0
    prefix = f"{FOCUSED_TARGET}: "
    for line in collect_output.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            with contextlib.suppress(ValueError):
                collected_count = int(stripped.removeprefix(prefix))
    run_rc, run_output = _run(
        [sys.executable, "-m", "pytest", FOCUSED_TARGET, "-q", "--tb=short"]
    )
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


def _json_subprocess(module: str, output_path: str) -> tuple[int, dict[str, Any], str]:
    command = [sys.executable, "-m", module]
    if module.endswith("run_red_qualification"):
        command.append("--pytest")
    command.extend(["--output", output_path])
    rc, output = _run(command)
    path = Path(output_path)
    payload: dict[str, Any] = {}
    if path.is_file():
        with contextlib.suppress(json.JSONDecodeError, OSError):
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                payload = value
    return rc, payload, output


def _base_qualifications() -> dict[str, Any]:
    s1_path = "/tmp/p4live-g2-s2-pregreen-s1.json"
    matrix_path = "/tmp/p4live-g2-s2-pregreen-matrix.json"
    s1_rc, s1, _s1_output = _json_subprocess(
        "evals.smc_semantic_logic_p4_live.run_green2_s1_qualification", s1_path
    )
    matrix_rc, matrix, _matrix_output = _json_subprocess(
        "evals.smc_semantic_logic_p4_live.run_red_qualification", matrix_path
    )
    parent_rows = {
        str(row.get("id")): row
        for row in matrix.get("rows", [])
        if str(row.get("id")) in PARENT_CODES
    }
    parent_taxonomy_ok = all(
        row_id in parent_rows
        and parent_rows[row_id].get("observed_code") == code
        and parent_rows[row_id].get("contract_satisfied") is False
        for row_id, code in PARENT_CODES.items()
    )
    return {
        "s1_exit_code": s1_rc,
        "s1_qualified": s1.get("qualified_s1_stop") is True,
        "s1_focused_green": (s1.get("focused_pytest") or {}).get("all_passed") is True,
        "matrix_exit_code": matrix_rc,
        "green1_stop_qualified": matrix.get("qualified_green1_stop") is True,
        "matrix_harness_errors": list(matrix.get("harness_errors") or []),
        "r10_r19_all_red": matrix.get("all_remaining_rows_red") is True,
        "parent_s2_rows_taxonomy_preserved": parent_taxonomy_ok,
        "parent_s2_rows": parent_rows,
    }


def _critical_imports() -> dict[str, Any]:
    module_names = (
        "llm_loop.browser.action_ref",
        "llm_loop.browser.action_ref_execution",
        "llm_loop.browser.action",
        "llm_loop.browser.cdp_action_host",
        "llm_loop.tools.builtin.browser_semantic_execute",
    )
    records: list[dict[str, Any]] = []
    all_exact = True
    for name in module_names:
        module = importlib.import_module(name)
        module_path = Path(str(module.__file__ or "")).resolve()
        try:
            relative = module_path.relative_to(ROOT.resolve())
            under_src = module_path.is_relative_to(SRC_ROOT)
        except ValueError:
            relative = module_path
            under_src = False
        digest = (
            hashlib.sha256(module_path.read_bytes()).hexdigest()
            if module_path.is_file()
            else ""
        )
        all_exact = all_exact and under_src
        records.append(
            {
                "module": name,
                "path": str(relative),
                "under_exact_worktree_src": under_src,
                "sha256": digest,
            }
        )
    return {"all_under_exact_worktree_src": all_exact, "modules": records}


def _plan_validation() -> dict[str, Any]:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    candidate_paths = {
        str(item.get("path"))
        for item in (plan.get("future_s2_green_candidate") or {}).get("candidate_edits", [])
    }
    expected_candidate_paths = {
        "src/llm_loop/browser/action.py",
        "src/llm_loop/browser/cdp_action_host.py",
        "src/llm_loop/tools/builtin/browser_action_ref_kernel.py",
    }
    explicit_non_edits = set(
        (plan.get("future_s2_green_candidate") or {}).get("explicit_non_edits", [])
    )
    required_non_edits = {
        "src/llm_loop/browser/action_ref.py",
        "src/llm_loop/browser/action_ref_execution.py",
        "src/llm_loop/browser/perception.py",
        "src/llm_loop/tools/builtin/browser_semantic_execute.py",
        "src/llm_loop/factory.py",
        "src/llm_loop/tools/registry.py",
        "src/llm_loop/core/loop/engine.py",
    }
    stage = plan.get("stage") or {}
    valid = bool(
        plan.get("base_s1_sha") == BASE_S1_SHA
        and plan.get("protocol_sha") == PROTOCOL_SHA
        and stage.get("production_edits") is False
        and stage.get("stop_before_first_s2_production_green") is True
        and candidate_paths == expected_candidate_paths
        and required_non_edits.issubset(explicit_non_edits)
        and (plan.get("rollback_and_exposure") or {}).get(
            "first_actionref_physical_dispatch_boundary"
        )
        == "G2-S4"
    )
    return {
        "valid": valid,
        "candidate_edit_paths": sorted(candidate_paths),
        "explicit_non_edits": sorted(explicit_non_edits),
        "first_dispatch_boundary": (plan.get("rollback_and_exposure") or {}).get(
            "first_actionref_physical_dispatch_boundary"
        ),
    }


def _src_diff_boundary() -> dict[str, Any]:
    rc_diff, diff_output = _run(
        ["git", "diff", "--name-only", BASE_S1_SHA, "--", "src"]
    )
    rc_untracked, untracked_output = _run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "src"]
    )
    changed = sorted(line for line in diff_output.splitlines() if line.strip())
    untracked = sorted(line for line in untracked_output.splitlines() if line.strip())
    return {
        "git_diff_exit_code": rc_diff,
        "git_untracked_exit_code": rc_untracked,
        "changed_src_paths": changed,
        "untracked_src_paths": untracked,
        "zero_src_diff_from_base_s1": rc_diff == 0 and rc_untracked == 0 and not changed and not untracked,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    expected = load_expected_failures()
    rows = []
    for row_id in S2_RED_IDS:
        probe = run_probe(row_id)
        expected_code = expected[row_id]["code"]
        row_ok = (
            probe.failure_code == expected_code
            and probe.failure_code != "harness_error"
            and not probe.contract_satisfied
        )
        rows.append(
            {
                "id": row_id,
                "expected_code": expected_code,
                "observed_code": probe.failure_code,
                "contract_satisfied": probe.contract_satisfied,
                "row_ok": row_ok,
                "detail": probe.detail,
                "facts": probe.facts,
            }
        )

    focused = _pytest_evidence()
    base = _base_qualifications()
    imports = _critical_imports()
    plan = _plan_validation()
    src_boundary = _src_diff_boundary()
    qualified = bool(
        len(rows) == 3
        and all(row["row_ok"] for row in rows)
        and focused["all_passed"]
        and base["s1_exit_code"] == 0
        and base["s1_qualified"]
        and base["s1_focused_green"]
        and base["matrix_exit_code"] == 0
        and base["green1_stop_qualified"]
        and base["matrix_harness_errors"] == []
        and base["r10_r19_all_red"]
        and base["parent_s2_rows_taxonomy_preserved"]
        and imports["all_under_exact_worktree_src"]
        and plan["valid"]
        and src_boundary["zero_src_diff_from_base_s1"]
    )
    evidence = {
        "schema": "smc.semantic_logic_p4_live_green2_s2_pregreen_evidence.v0.1",
        "base_s1_sha": BASE_S1_SHA,
        "parent_plan_sha": PARENT_PLAN_SHA,
        "protocol_sha": PROTOCOL_SHA,
        "slice": "G2-S2-PREGREEN",
        "expected_red_rows": rows,
        "focused_pytest": focused,
        "base_qualifications": base,
        "critical_imports": imports,
        "plan_validation": plan,
        "src_boundary": src_boundary,
        "real_browser_actions_executed": 0,
        "model_requests_sent": 0,
        "production_green_started": False,
        "qualified_s2_pregreen_stop": qualified,
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

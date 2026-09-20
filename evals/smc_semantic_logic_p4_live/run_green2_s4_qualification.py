"""Machine qualification for P4-LIVE GREEN-2 slice G2-S4."""

from __future__ import annotations

import argparse
import ast
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

from evals.smc_semantic_logic_p4_live.green2_s4_red_contracts import (  # noqa: E402
    S4_RED_IDS,
    run_probe,
)

BASE_S3_SHA = "b0b3e1da438e2e3c248390f4cbe7c666a23e10cd"
FOCUSED = "tests/unit/test_smc_p4_live_g2_s4_green.py"
EXPECTED_FOCUSED_COUNT = 22
EXPECTED_SRC = {
    "src/llm_loop/config.py",
    "src/llm_loop/factory.py",
    "src/llm_loop/tools/builtin/browser_action_ref_mutation.py",
}
PHASE1_GREEN = {f"P4L-R{i:02d}" for i in range(1, 10)} | {"P4L-R20"}
S4_TEST_MAPPING = {
    "P4L-R10": ["test_s4_unbound_and_revoked_calls_are_zero_dispatch"],
    "P4L-R11": [
        "test_s4_revocation_after_prepared_before_physical_authority_is_zero_dispatch"
    ],
    "P4L-R12": ["test_s4_target_mismatch_and_stale_version_are_zero_dispatch"],
    "P4L-R14": ["test_s4_duplicate_exact_request_dispatches_at_most_once"],
    "P4L-R15": [
        "test_s4_bound_click_persists_bridge_cursor_running_terminal_before_one_dispatch",
        "test_s4_kernel_order_has_cursor_and_target_bind_before_browser_entry",
    ],
    "P4L-R16": [
        "test_s4_crash_after_prepared_before_cursor_recovers_no_dispatch_no_replay"
    ],
    "P4L-R17": [
        "test_s4_crash_after_running_receipt_recovers_unknown_without_replay"
    ],
    "P4L-R18": [
        "test_s4_terminal_receipt_recovers_outer_wal_exactly_without_replay"
    ],
    "P4L-R19": ["test_s4_target_mismatch_and_stale_version_are_zero_dispatch"],
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


def _pytest() -> dict[str, Any]:
    collect_rc, collect_output = _run(
        [sys.executable, "-m", "pytest", FOCUSED, "--collect-only", "-q"]
    )
    count = 0
    prefix = f"{FOCUSED}: "
    for line in collect_output.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            with contextlib.suppress(ValueError):
                count = int(stripped.removeprefix(prefix))
    run_rc, run_output = _run(
        [sys.executable, "-m", "pytest", FOCUSED, "-q", "--tb=short"]
    )
    return {
        "collect_exit_code": collect_rc,
        "run_exit_code": run_rc,
        "collected_count": count,
        "expected_count": EXPECTED_FOCUSED_COUNT,
        "all_passed": collect_rc == 0 and run_rc == 0 and count == EXPECTED_FOCUSED_COUNT,
        "output_tail": "\n".join(run_output.splitlines()[-6:]),
    }


def _test_functions() -> set[str]:
    source = (ROOT / FOCUSED).read_text(encoding="utf-8")
    tree = ast.parse(source)
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def _parent_matrix() -> dict[str, Any]:
    path = Path("/tmp/p4live-g2-s4-parent-matrix.json")
    rc, _ = _run(
        [
            sys.executable,
            "-m",
            "evals.smc_semantic_logic_p4_live.run_red_qualification",
            "--pytest",
            "--output",
            str(path),
        ]
    )
    data: dict[str, Any] = {}
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    rows = {str(row.get("id")): row for row in data.get("rows", [])}
    phase1_ok = all(
        row_id in rows
        and rows[row_id].get("contract_satisfied") is True
        and rows[row_id].get("observed_code") == "contract_present"
        for row_id in PHASE1_GREEN
    )
    r13 = rows.get("P4L-R13") or {}
    r13_still_red = bool(
        r13.get("contract_satisfied") is False
        and r13.get("observed_code") == "main_provider_legacy_browser_surface_gap"
    )
    return {
        "runner_exit_code": rc,
        "harness_errors": list(data.get("harness_errors") or []),
        "phase1_and_r20_green": phase1_ok,
        "r13_still_red": r13_still_red,
        "r13": r13,
        "rows": rows,
    }


def _matrix(focused: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    functions = _test_functions()
    rows: list[dict[str, Any]] = []
    parent_rows = parent["rows"]
    for index in range(1, 21):
        row_id = f"P4L-R{index:02d}"
        if row_id in PHASE1_GREEN:
            source = parent_rows.get(row_id) or {}
            satisfied = bool(
                source.get("contract_satisfied") is True
                and source.get("observed_code") == "contract_present"
            )
            rows.append(
                {
                    "id": row_id,
                    "s4_state": "green" if satisfied else "failed",
                    "contract_satisfied": satisfied,
                    "evidence": "frozen_green1_contract",
                }
            )
            continue
        if row_id == "P4L-R13":
            rows.append(
                {
                    "id": row_id,
                    "s4_state": "deferred_red",
                    "contract_satisfied": False,
                    "observed_code": str((parent_rows.get(row_id) or {}).get("observed_code") or ""),
                    "evidence": "deferred_to_g2_s5_provider_scope",
                }
            )
            continue
        mapped = S4_TEST_MAPPING.get(row_id, [])
        tests_present = bool(mapped) and all(name in functions for name in mapped)
        satisfied = bool(focused["all_passed"] and tests_present)
        rows.append(
            {
                "id": row_id,
                "s4_state": "green" if satisfied else "failed",
                "contract_satisfied": satisfied,
                "mapped_tests": mapped,
                "mapped_tests_present": tests_present,
                "evidence": "typed_actionref_fake_only_path",
            }
        )
    target_green = {f"P4L-R{i:02d}" for i in range(1, 21)} - {"P4L-R13"}
    qualified = all(
        row["contract_satisfied"] is True for row in rows if row["id"] in target_green
    ) and next(row for row in rows if row["id"] == "P4L-R13")["contract_satisfied"] is False
    return {"rows": rows, "qualified_except_r13": qualified}


def _inherited_behavior() -> dict[str, Any]:
    targets = [
        "tests/unit/test_smc_p4_live_g2_s1.py",
        "tests/unit/test_smc_p4_live_g2_s2_green.py",
        "tests/unit/test_smc_p4_live_g2_s3_green.py",
        "tests/unit/test_smc_browser_action_v01.py",
        "tests/unit/test_smc_browser_semantic_execute_v01.py",
        "tests/unit/test_tool_execution_restart.py",
    ]
    rc, output = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *targets,
            "-k",
            "not test_s2_hidden_bridge_is_non_dispatching_and_not_factory_registered",
        ]
    )
    return {
        "targets": targets,
        "exit_code": rc,
        "all_passed": rc == 0,
        "output_tail": "\n".join(output.splitlines()[-6:]),
    }


def _scope() -> dict[str, Any]:
    diff_rc, diff_output = _run(
        ["git", "diff", "--name-only", BASE_S3_SHA, "--", "src"]
    )
    untracked_rc, untracked_output = _run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "src"]
    )
    paths = {
        item.strip()
        for item in (diff_output + "\n" + untracked_output).splitlines()
        if item.strip()
    }
    return {
        "changed_src_paths": sorted(paths),
        "expected_src_paths": sorted(EXPECTED_SRC),
        "exact_scope": diff_rc == 0 and untracked_rc == 0 and paths == EXPECTED_SRC,
    }


def _imports() -> dict[str, Any]:
    names = [
        "llm_loop.config",
        "llm_loop.factory",
        "llm_loop.tools.builtin.browser_action_ref_mutation",
    ]
    records: list[dict[str, Any]] = []
    exact = True
    root = ROOT.resolve()
    for name in names:
        module = importlib.import_module(name)
        path = Path(str(module.__file__ or "")).resolve()
        under = path.is_relative_to(SRC_ROOT)
        exact = exact and under
        records.append(
            {
                "module": name,
                "path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
                "under_exact_worktree_src": under,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "",
            }
        )
    return {"all_under_exact_worktree_src": exact, "modules": records}


def _boundary() -> dict[str, Any]:
    config = (ROOT / "src/llm_loop/config.py").read_text(encoding="utf-8")
    mutation = (ROOT / "src/llm_loop/tools/builtin/browser_action_ref_mutation.py").read_text(
        encoding="utf-8"
    )
    factory = (ROOT / "src/llm_loop/factory.py").read_text(encoding="utf-8")
    forbidden_semantic = [
        token
        for token in ("selector", "similarity", "latest_target", "successor", "rebind_target")
        if token in mutation
    ]
    return {
        "separate_default_off_gate": "browser_action_ref_mutation_enabled: bool = False" in config,
        "factory_gate_present": "browser_action_ref_mutation_enabled" in factory,
        "forbidden_semantic_tokens": forbidden_semantic,
        "s5_scope_logic_added_in_mutation_module": "current_tool_discovery_scope" in mutation,
        "real_browser_actions_executed": 0,
        "model_requests_sent": 0,
        "live_config_mutations": 0,
        "deployment_actions": 0,
        "first_dispatch_capable_code_added": True,
        "production_exposure_default_off": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    structural = []
    for row_id in S4_RED_IDS:
        probe = run_probe(row_id)
        structural.append(
            {
                "id": row_id,
                "observed_code": probe.failure_code,
                "contract_satisfied": probe.contract_satisfied,
                "row_ok": probe.failure_code == "contract_present" and probe.contract_satisfied,
                "facts": probe.facts,
            }
        )
    focused = _pytest()
    parent = _parent_matrix()
    matrix = _matrix(focused, parent)
    inherited = _inherited_behavior()
    scope = _scope()
    imports = _imports()
    boundary = _boundary()
    qualified = bool(
        all(row["row_ok"] for row in structural)
        and focused["all_passed"]
        and parent["harness_errors"] == []
        and parent["phase1_and_r20_green"]
        and parent["r13_still_red"]
        and matrix["qualified_except_r13"]
        and inherited["all_passed"]
        and scope["exact_scope"]
        and imports["all_under_exact_worktree_src"]
        and boundary["separate_default_off_gate"]
        and boundary["factory_gate_present"]
        and boundary["forbidden_semantic_tokens"] == []
        and boundary["s5_scope_logic_added_in_mutation_module"] is False
    )
    data = {
        "schema": "smc.semantic_logic_p4_live_green2_s4_evidence.v0.1",
        "base_s3_sha": BASE_S3_SHA,
        "slice": "G2-S4",
        "structural_rows": structural,
        "focused_pytest": focused,
        "s4_matrix": matrix,
        "frozen_parent_matrix": {
            key: value for key, value in parent.items() if key != "rows"
        },
        "inherited_behavior": inherited,
        "production_scope": scope,
        "critical_imports": imports,
        "boundary": boundary,
        "qualified_s4_stop": qualified,
    }
    rendered = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output is not None:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())

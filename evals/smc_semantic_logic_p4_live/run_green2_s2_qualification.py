"""Machine qualification for P4-LIVE GREEN-2 slice G2-S2."""

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

from evals.smc_semantic_logic_p4_live.green2_s2_red_contracts import (  # noqa: E402
    S2_RED_IDS,
    run_probe,
)

BASE_PREGREEN_SHA = "8c000d74015af858d960d051ecb2619cf62ec8b9"
BASE_S1_SHA = "06891fd144c635f0625644a0c2c2ea24ed009e52"
PROTOCOL_SHA = "e946eab26032aa4faa6698a3244ebd30c836cce1"
FOCUSED_TARGET = "tests/unit/test_smc_p4_live_g2_s2_green.py"
EXPECTED_FOCUSED_CASES = 9
EXPECTED_SRC_PATHS = {
    "src/llm_loop/browser/action.py",
    "src/llm_loop/browser/cdp_action_host.py",
    "src/llm_loop/tools/builtin/browser_action_ref_kernel.py",
}
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
    count = 0
    prefix = f"{FOCUSED_TARGET}: "
    for line in collect_output.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            with contextlib.suppress(ValueError):
                count = int(stripped.removeprefix(prefix))
    run_rc, run_output = _run(
        [sys.executable, "-m", "pytest", FOCUSED_TARGET, "-q", "--tb=short"]
    )
    return {
        "collect_exit_code": collect_rc,
        "run_exit_code": run_rc,
        "collected_count": count,
        "expected_count": EXPECTED_FOCUSED_CASES,
        "all_passed": collect_rc == 0 and run_rc == 0 and count == EXPECTED_FOCUSED_CASES,
        "output_tail": "\n".join(run_output.splitlines()[-8:]),
    }


def _json_runner(module: str, output_path: str, *, pytest: bool = False) -> tuple[int, dict[str, Any]]:
    command = [sys.executable, "-m", module]
    if pytest:
        command.append("--pytest")
    command.extend(["--output", output_path])
    rc, _output = _run(command)
    payload: dict[str, Any] = {}
    path = Path(output_path)
    if path.is_file():
        with contextlib.suppress(OSError, json.JSONDecodeError):
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
    return rc, payload


def _base_qualifications() -> dict[str, Any]:
    s1_rc, s1 = _json_runner(
        "evals.smc_semantic_logic_p4_live.run_green2_s1_qualification",
        "/tmp/p4live-g2-s2-green-s1.json",
    )
    matrix_rc, matrix = _json_runner(
        "evals.smc_semantic_logic_p4_live.run_red_qualification",
        "/tmp/p4live-g2-s2-green-matrix.json",
        pytest=True,
    )
    parent_rows = {
        str(row.get("id")): row
        for row in matrix.get("rows", [])
        if str(row.get("id")) in PARENT_CODES
    }
    parent_ok = all(
        row_id in parent_rows
        and parent_rows[row_id].get("observed_code") == code
        and parent_rows[row_id].get("contract_satisfied") is False
        and parent_rows[row_id].get("taxonomy_match") is True
        for row_id, code in PARENT_CODES.items()
    )
    return {
        "s1_exit_code": s1_rc,
        "s1_qualified": s1.get("qualified_s1_stop") is True,
        "matrix_exit_code": matrix_rc,
        "green1_stop_qualified": matrix.get("qualified_green1_stop") is True,
        "r10_r19_all_red": matrix.get("all_remaining_rows_red") is True,
        "matrix_harness_errors": list(matrix.get("harness_errors") or []),
        "parent_s2_taxonomy_preserved": parent_ok,
        "parent_s2_rows": parent_rows,
    }


def _critical_imports() -> dict[str, Any]:
    names = (
        "llm_loop.browser.action",
        "llm_loop.browser.cdp_action_host",
        "llm_loop.browser.action_ref",
        "llm_loop.browser.action_ref_execution",
        "llm_loop.tools.builtin.browser_semantic_execute",
        "llm_loop.tools.builtin.browser_action_ref_kernel",
    )
    records: list[dict[str, Any]] = []
    exact = True
    for name in names:
        module = importlib.import_module(name)
        path = Path(str(module.__file__ or "")).resolve()
        under_src = path.is_relative_to(SRC_ROOT)
        exact = exact and under_src
        records.append(
            {
                "module": name,
                "path": str(path.relative_to(ROOT.resolve())) if path.is_relative_to(ROOT.resolve()) else str(path),
                "under_exact_worktree_src": under_src,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "",
            }
        )
    return {"all_under_exact_worktree_src": exact, "modules": records}


def _changed_src_paths() -> dict[str, Any]:
    rc_diff, diff_output = _run(["git", "diff", "--name-only", BASE_PREGREEN_SHA, "--", "src"])
    rc_untracked, untracked_output = _run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "src"]
    )
    paths = {
        line.strip()
        for line in (diff_output + "\n" + untracked_output).splitlines()
        if line.strip()
    }
    return {
        "git_diff_exit_code": rc_diff,
        "git_untracked_exit_code": rc_untracked,
        "changed_src_paths": sorted(paths),
        "expected_src_paths": sorted(EXPECTED_SRC_PATHS),
        "exact_three_file_candidate": rc_diff == 0 and rc_untracked == 0 and paths == EXPECTED_SRC_PATHS,
    }


def _git_show(path: str) -> str:
    rc, output = _run(["git", "show", f"{BASE_PREGREEN_SHA}:{path}"])
    if rc != 0:
        raise RuntimeError(f"git show failed for {path}")
    return output.replace("<repo>", str(ROOT))


def _extract_method(source: str, class_name: str, method_name: str) -> str:
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                    assert child.end_lineno is not None
                    return "".join(lines[child.lineno - 1 : child.end_lineno])
    raise RuntimeError(f"method not found: {class_name}.{method_name}")


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _unchanged_execution_methods() -> dict[str, Any]:
    action_path = "src/llm_loop/browser/action.py"
    cdp_path = "src/llm_loop/browser/cdp_action_host.py"
    current_action = (ROOT / action_path).read_text(encoding="utf-8")
    current_cdp = (ROOT / cdp_path).read_text(encoding="utf-8")
    base_action = _git_show(action_path)
    base_cdp = _git_show(cdp_path)
    specs = (
        ("BrowserActionAdapter.execute", base_action, current_action, "BrowserActionAdapter", "execute"),
        ("BrowserActionAdapter._validate", base_action, current_action, "BrowserActionAdapter", "_validate"),
        ("CdpBrowserMutationActuator.dispatch", base_cdp, current_cdp, "CdpBrowserMutationActuator", "dispatch"),
        ("CdpBrowserMutationActuator._ensure_session", base_cdp, current_cdp, "CdpBrowserMutationActuator", "_ensure_session"),
        ("CdpBrowserMutationActuator._resolve_target", base_cdp, current_cdp, "CdpBrowserMutationActuator", "_resolve_target"),
    )
    rows = []
    all_unchanged = True
    for name, base_source, current_source, cls, method in specs:
        base_method = _extract_method(base_source, cls, method)
        current_method = _extract_method(current_source, cls, method)
        unchanged = base_method == current_method
        all_unchanged = all_unchanged and unchanged
        rows.append(
            {
                "name": name,
                "unchanged": unchanged,
                "base_sha256": _sha_text(base_method),
                "current_sha256": _sha_text(current_method),
            }
        )
    return {"all_unchanged": all_unchanged, "methods": rows}


def _hidden_boundary() -> dict[str, Any]:
    kernel = (ROOT / "src/llm_loop/tools/builtin/browser_action_ref_kernel.py").read_text(encoding="utf-8")
    factory = (ROOT / "src/llm_loop/factory.py").read_text(encoding="utf-8")
    registry = (ROOT / "src/llm_loop/tools/registry.py").read_text(encoding="utf-8")
    banned = ("BrowserActionAdapter", "execute_request", ".dispatch(")
    return {
        "kernel_dispatch_dependencies": [token for token in banned if token in kernel],
        "factory_registration_present": "browser_action_ref_kernel" in factory,
        "registry_registration_present": "browser_action_ref_kernel" in registry,
        "first_physical_dispatch_boundary_crossed": False,
        "real_browser_actions_executed": 0,
        "model_requests_sent": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rows = []
    for row_id in S2_RED_IDS:
        probe = run_probe(row_id)
        rows.append(
            {
                "id": row_id,
                "observed_code": probe.failure_code,
                "contract_satisfied": probe.contract_satisfied,
                "row_ok": probe.failure_code == "contract_present" and probe.contract_satisfied,
                "detail": probe.detail,
                "facts": probe.facts,
            }
        )
    focused = _pytest_evidence()
    base = _base_qualifications()
    imports = _critical_imports()
    scope = _changed_src_paths()
    methods = _unchanged_execution_methods()
    hidden = _hidden_boundary()

    qualified = bool(
        len(rows) == 3
        and all(row["row_ok"] for row in rows)
        and focused["all_passed"]
        and base["s1_exit_code"] == 0
        and base["s1_qualified"]
        and base["matrix_exit_code"] == 0
        and base["green1_stop_qualified"]
        and base["r10_r19_all_red"]
        and base["matrix_harness_errors"] == []
        and base["parent_s2_taxonomy_preserved"]
        and imports["all_under_exact_worktree_src"]
        and scope["exact_three_file_candidate"]
        and methods["all_unchanged"]
        and hidden["kernel_dispatch_dependencies"] == []
        and hidden["factory_registration_present"] is False
        and hidden["registry_registration_present"] is False
    )
    evidence = {
        "schema": "smc.semantic_logic_p4_live_green2_s2_evidence.v0.1",
        "base_pregreen_sha": BASE_PREGREEN_SHA,
        "base_s1_sha": BASE_S1_SHA,
        "protocol_sha": PROTOCOL_SHA,
        "slice": "G2-S2",
        "s2_rows": rows,
        "focused_pytest": focused,
        "base_qualifications": base,
        "critical_imports": imports,
        "production_scope": scope,
        "unchanged_execution_methods": methods,
        "hidden_boundary": hidden,
        "qualified_s2_stop": qualified,
    }
    rendered = json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output is not None:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())

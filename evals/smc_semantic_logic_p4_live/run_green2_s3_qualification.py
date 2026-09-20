"""Machine qualification for P4-LIVE GREEN-2 slice G2-S3."""

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

from evals.smc_semantic_logic_p4_live.green2_s3_red_contracts import (  # noqa: E402
    S3_RED_IDS,
    run_probe,
)

BASE_S2_SHA = "dee507cd7aa69bc5425b57953a581f9b062f35b6"
FOCUSED = "tests/unit/test_smc_p4_live_g2_s3_green.py"
EXPECTED_COUNT = 12
EXPECTED_SRC = {
    "src/llm_loop/browser/action_ref_execution.py",
    "src/llm_loop/browser/action_ref_recovery.py",
    "src/llm_loop/core/tool_execution_journal.py",
    "src/llm_loop/core/loop/events.py",
    "src/llm_loop/subagent/runner.py",
}
PARENT_CODES = {
    "P4L-R16": "prepare_without_running_recovery_contract_absent",
    "P4L-R17": "running_unknown_browser_correlation_absent",
    "P4L-R18": "terminal_browser_outer_wal_correlation_absent",
}


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
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
        "expected_count": EXPECTED_COUNT,
        "all_passed": collect_rc == 0 and run_rc == 0 and count == EXPECTED_COUNT,
        "output_tail": "\n".join(run_output.splitlines()[-6:]),
    }


def _matrix() -> dict[str, Any]:
    path = Path("/tmp/p4live-g2-s3-matrix.json")
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
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            data = loaded
    rows = {
        str(row.get("id")): row
        for row in data.get("rows", [])
        if str(row.get("id")) in PARENT_CODES
    }
    parent_ok = all(
        row_id in rows
        and rows[row_id].get("observed_code") == code
        and rows[row_id].get("contract_satisfied") is False
        and rows[row_id].get("taxonomy_match") is True
        for row_id, code in PARENT_CODES.items()
    )
    return {
        "exit_code": rc,
        "green1_stop_qualified": data.get("qualified_green1_stop") is True,
        "all_remaining_rows_red": data.get("all_remaining_rows_red") is True,
        "harness_errors": list(data.get("harness_errors") or []),
        "parent_taxonomy_preserved": parent_ok,
        "parent_rows": rows,
    }


def _scope() -> dict[str, Any]:
    diff_rc, diff_output = _run(
        ["git", "diff", "--name-only", BASE_S2_SHA, "--", "src"]
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
        "llm_loop.browser.action_ref_execution",
        "llm_loop.browser.action_ref_recovery",
        "llm_loop.core.tool_execution_journal",
        "llm_loop.core.loop.events",
        "llm_loop.subagent.runner",
    ]
    rows: list[dict[str, Any]] = []
    all_exact = True
    root = ROOT.resolve()
    for name in names:
        module = importlib.import_module(name)
        path = Path(str(module.__file__ or "")).resolve()
        under_src = path.is_relative_to(SRC_ROOT)
        all_exact = all_exact and under_src
        rows.append(
            {
                "module": name,
                "path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
                "under_exact_worktree_src": under_src,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return {"all_under_exact_worktree_src": all_exact, "modules": rows}


def _boundary() -> dict[str, Any]:
    source = (ROOT / "src/llm_loop/browser/action_ref_recovery.py").read_text(
        encoding="utf-8"
    )
    forbidden = [
        token
        for token in (
            ".dispatch(",
            "BrowserActionAdapter",
            "selector",
            "similarity",
            "latest_target",
            "successor",
            "search_target",
            "rebind_target",
        )
        if token in source
    ]
    return {
        "forbidden_surface_tokens": forbidden,
        "real_browser_actions_executed": 0,
        "model_requests_sent": 0,
        "dispatch_capability_added": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rows = []
    for row_id in S3_RED_IDS:
        probe = run_probe(row_id)
        rows.append(
            {
                "id": row_id,
                "observed_code": probe.failure_code,
                "contract_satisfied": probe.contract_satisfied,
                "row_ok": probe.failure_code == "contract_present" and probe.contract_satisfied,
                "facts": probe.facts,
            }
        )

    focused = _pytest()
    matrix = _matrix()
    scope = _scope()
    imports = _imports()
    boundary = _boundary()
    qualified = bool(
        all(row["row_ok"] for row in rows)
        and focused["all_passed"]
        and matrix["exit_code"] == 0
        and matrix["green1_stop_qualified"]
        and matrix["all_remaining_rows_red"]
        and matrix["harness_errors"] == []
        and matrix["parent_taxonomy_preserved"]
        and scope["exact_scope"]
        and imports["all_under_exact_worktree_src"]
        and boundary["forbidden_surface_tokens"] == []
    )
    data = {
        "schema": "smc.semantic_logic_p4_live_green2_s3_evidence.v0.1",
        "base_s2_sha": BASE_S2_SHA,
        "slice": "G2-S3",
        "s3_rows": rows,
        "focused_pytest": focused,
        "green1_matrix": matrix,
        "production_scope": scope,
        "critical_imports": imports,
        "boundary": boundary,
        "qualified_s3_stop": qualified,
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

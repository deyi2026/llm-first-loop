"""Machine qualification for P4-LIVE GREEN-2 slice G2-S5."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import inspect
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = (ROOT / "src").resolve()
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from evals.smc_semantic_logic_p4_live.green2_s5_red_contracts import (  # noqa: E402
    exact_canary_scope,
    probe_canary_scope_authority,
    probe_discovery,
    probe_execution,
    probe_provider_projection,
)
from llm_loop.tools.p4_live_scope import P4_LIVE_CANARY_TOOL_SCOPE  # noqa: E402
from llm_loop.tools.registry import GetToolSchemaTool, ToolRegistry  # noqa: E402

BASE_S4_SHA = "44b38540691f7cddc1d34cf709dc92bb8e6b0e66"
S4_EVIDENCE_SHA256 = "f0737cfaa8e8068d4a839d7cbad8f17f77bb50fd4230310866b81dedf5a0db1c"
FOCUSED = "tests/unit/test_smc_p4_live_g2_s5_green.py"
EXPECTED_FOCUSED_COUNT = 7
EXPECTED_SRC = {
    "src/llm_loop/core/loop/engine.py",
    "src/llm_loop/tools/registry.py",
    "src/llm_loop/tools/p4_live_scope.py",
}
LEGACY_BROWSER_MUTATIONS = {
    "browser_action",
    "browser_semantic_execute",
    "browser_semantic_operation",
}
S4_EVIDENCE = ROOT / "evals/smc_semantic_logic_p4_live/results/P4-LIVE-G2-S4-v0.1-20260920/EVIDENCE.json"
PREFLIGHT = ROOT / "evals/smc_semantic_logic_p4_live/P4-LIVE-CANARY-PREFLIGHT.v0.1.json"


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
    run_rc, run_output = _run([sys.executable, "-m", "pytest", FOCUSED, "-q", "--tb=short"])
    return {
        "collect_exit_code": collect_rc,
        "run_exit_code": run_rc,
        "collected_count": count,
        "expected_count": EXPECTED_FOCUSED_COUNT,
        "all_passed": collect_rc == 0 and run_rc == 0 and count == EXPECTED_FOCUSED_COUNT,
        "output_tail": "\n".join(run_output.splitlines()[-6:]),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _s4_matrix() -> dict[str, Any]:
    loaded = json.loads(S4_EVIDENCE.read_text(encoding="utf-8"))
    rows = list((loaded.get("s4_matrix") or {}).get("rows") or [])
    by_id = {str(row.get("id")): row for row in rows}
    inherited_green = all(
        row_id in by_id and by_id[row_id].get("contract_satisfied") is True
        for row_id in {f"P4L-R{i:02d}" for i in range(1, 21)} - {"P4L-R13"}
    )
    parent_r13_red = bool(
        by_id.get("P4L-R13", {}).get("contract_satisfied") is False
        and by_id.get("P4L-R13", {}).get("s4_state") == "deferred_red"
    )
    return {
        "sha256": _sha256(S4_EVIDENCE),
        "expected_sha256": S4_EVIDENCE_SHA256,
        "hash_exact": _sha256(S4_EVIDENCE) == S4_EVIDENCE_SHA256,
        "qualified_s4_stop": loaded.get("qualified_s4_stop") is True,
        "inherited_r01_r12_r14_r20_green": inherited_green,
        "parent_r13_deferred_red": parent_r13_red,
        "rows": rows,
    }


def _s5_channels() -> dict[str, Any]:
    rows = [
        probe_provider_projection(),
        probe_discovery(),
        probe_execution(),
        probe_canary_scope_authority(),
    ]
    encoded = [
        {"id": row.channel_id, "state": row.state, "code": row.code, "facts": row.facts}
        for row in rows
    ]
    qualified = bool(
        rows[0].state == "green"
        and rows[0].code == "contract_present"
        and rows[1].state == "green_prerequisite"
        and rows[1].code == "discovery_scope_already_enforced"
        and rows[2].state == "green"
        and rows[2].code == "contract_present"
        and rows[3].state == "green"
        and rows[3].code == "contract_present"
    )
    return {"qualified": qualified, "channels": encoded}


def _final_matrix(s4: dict[str, Any], s5: dict[str, Any]) -> dict[str, Any]:
    parent = {str(row.get("id")): dict(row) for row in s4["rows"]}
    rows: list[dict[str, Any]] = []
    for index in range(1, 21):
        row_id = f"P4L-R{index:02d}"
        if row_id == "P4L-R13":
            rows.append(
                {
                    "id": row_id,
                    "contract_satisfied": bool(s5["qualified"]),
                    "state": "green" if s5["qualified"] else "failed",
                    "evidence": "g2_s5_provider_discovery_execution_scope",
                }
            )
        else:
            inherited = parent.get(row_id) or {}
            rows.append(
                {
                    "id": row_id,
                    "contract_satisfied": inherited.get("contract_satisfied") is True,
                    "state": "green" if inherited.get("contract_satisfied") is True else "failed",
                    "evidence": "frozen_g2_s4_evidence",
                }
            )
    return {
        "rows": rows,
        "all_20_green": len(rows) == 20 and all(row["contract_satisfied"] for row in rows),
    }


def _scope() -> dict[str, Any]:
    diff_rc, diff_output = _run(["git", "diff", "--name-only", BASE_S4_SHA, "--", "src"])
    untracked_rc, untracked_output = _run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "src"]
    )
    paths = {
        line.strip()
        for line in (diff_output + "\n" + untracked_output).splitlines()
        if line.strip()
    }
    return {
        "changed_src_paths": sorted(paths),
        "expected_src_paths": sorted(EXPECTED_SRC),
        "exact_scope": diff_rc == 0 and untracked_rc == 0 and paths == EXPECTED_SRC,
    }


def _imports() -> dict[str, Any]:
    names = (
        "llm_loop.core.loop.engine",
        "llm_loop.tools.registry",
        "llm_loop.tools.p4_live_scope",
    )
    root = ROOT.resolve()
    records: list[dict[str, Any]] = []
    exact = True
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
                "sha256": _sha256(path) if path.is_file() else "",
            }
        )
    return {"all_under_exact_worktree_src": exact, "modules": records}


def _source_order() -> dict[str, Any]:
    execute_source = inspect.getsource(ToolRegistry.execute)
    schema_source = inspect.getsource(GetToolSchemaTool.execute)
    from llm_loop.core.loop.engine import LoopEngine

    provider_source = inspect.getsource(LoopEngine._project_request_tools)
    execute_scope_before_get = (
        execute_source.index("current_scope_allows") < execute_source.index("self.get(call.name)")
    )
    return {
        "provider_uses_scoped_schemas": "schemas_for_current_scope" in provider_source,
        "discovery_uses_shared_names": "names_for_current_scope" in schema_source,
        "discovery_uses_shared_membership": "current_scope_allows" in schema_source,
        "execution_scope_check_before_tool_lookup": execute_scope_before_get,
    }


def _preflight() -> dict[str, Any]:
    data = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    expected_scope = frozenset(str(name) for name in data["exact_tool_scope"])
    forbidden = frozenset(str(name) for name in data["forbidden_browser_mutation_tools"])
    facts = data.get("required_runtime_facts") or {}
    valid = bool(
        data.get("pre_live_stop") is True
        and expected_scope == P4_LIVE_CANARY_TOOL_SCOPE
        and forbidden == LEGACY_BROWSER_MUTATIONS
        and facts.get("browser_perception_target_id")
        and facts.get("browser_action_enabled") is True
        and facts.get("browser_action_ref_enabled") is True
        and facts.get("browser_action_ref_mutation_enabled") is True
        and data.get("real_browser_actions_authorized_by_this_file") == 0
        and data.get("model_requests_authorized_by_this_file") == 0
    )
    return {
        "valid": valid,
        "sha256": _sha256(PREFLIGHT),
        "explicit_nonempty_target_id_required": bool(facts.get("browser_perception_target_id")),
        "pre_live_stop": data.get("pre_live_stop") is True,
    }


def _inherited_behavior() -> dict[str, Any]:
    targets = [
        "tests/unit/test_smc_p4_live_g2_s4_green.py",
        "tests/unit/test_smc_p4_live_g2_s3_green.py",
        "tests/unit/test_smc_p4_live_g2_s2_green.py",
        "tests/unit/test_smc_p4_live_g2_s1.py",
        "tests/unit/test_smc_browser_action_v01.py",
        "tests/unit/test_smc_browser_cdp_action_host_v01.py",
        "tests/unit/test_smc_browser_semantic_execute_v01.py",
        "tests/unit/test_smc_browser_perception_v01.py",
        "tests/unit/test_tool_execution_effects.py",
        "tests/unit/test_tool_execution_restart.py",
        "tests/unit/test_run_generation_ownership.py",
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    focused = _pytest()
    s4 = _s4_matrix()
    s5 = _s5_channels()
    matrix = _final_matrix(s4, s5)
    scope = _scope()
    imports = _imports()
    source_order = _source_order()
    preflight = _preflight()
    inherited = _inherited_behavior()
    exact_canary = frozenset(P4_LIVE_CANARY_TOOL_SCOPE) == exact_canary_scope()
    legacy_excluded = LEGACY_BROWSER_MUTATIONS.isdisjoint(P4_LIVE_CANARY_TOOL_SCOPE)
    qualified = bool(
        focused["all_passed"]
        and s4["hash_exact"]
        and s4["qualified_s4_stop"]
        and s4["inherited_r01_r12_r14_r20_green"]
        and s4["parent_r13_deferred_red"]
        and s5["qualified"]
        and matrix["all_20_green"]
        and scope["exact_scope"]
        and imports["all_under_exact_worktree_src"]
        and all(source_order.values())
        and preflight["valid"]
        and inherited["all_passed"]
        and exact_canary
        and legacy_excluded
    )
    data = {
        "schema": "smc.semantic_logic_p4_live_green2_s5_evidence.v0.1",
        "base_s4_sha": BASE_S4_SHA,
        "slice": "G2-S5",
        "focused_pytest": focused,
        "frozen_s4": {key: value for key, value in s4.items() if key != "rows"},
        "s5_channels": s5,
        "final_matrix": matrix,
        "production_scope": scope,
        "critical_imports": imports,
        "source_order": source_order,
        "canary_scope": {
            "exact_match": exact_canary,
            "tools": sorted(P4_LIVE_CANARY_TOOL_SCOPE),
            "legacy_browser_mutations_excluded": legacy_excluded,
        },
        "live_canary_preflight": preflight,
        "inherited_behavior": inherited,
        "real_browser_actions_executed": 0,
        "model_requests_sent": 0,
        "live_config_mutations": 0,
        "deployment_actions": 0,
        "qualified_s5_pre_live_stop": qualified,
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

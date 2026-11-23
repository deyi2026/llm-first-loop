"""Conservative, development-only incremental test selection and execution.

This is NOT an R9, Host, merge, or release credential. Uncertain impact blocks
the dev gate; it never silently turns an empty selection into a PASS.
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any

from llm_loop.introspection.goal_coverage import parse_requirements
from llm_loop.introspection.lane import LaneStore
from llm_loop.introspection.task_store import TaskStore, safe_goal_id

MAX_DEV_TEST_FILES = 200  # Broad shared-core changes require full integration R9.


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode:
        raise ValueError(f"git {' '.join(args)} failed: {result.stderr[:300]}")
    return result.stdout.strip()


def _module(path: str) -> str:
    parts = PurePosixPath(path).parts
    if len(parts) < 3 or parts[:2] != ("src", "llm_loop") or not path.endswith(".py"):
        return ""
    mod = list(parts[1:])
    mod[-1] = mod[-1][:-3]
    if mod[-1] == "__init__":
        mod.pop()
    return ".".join(mod)


def _imports(text: str, module_name: str) -> set[str]:
    tree = ast.parse(text)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            parent = module_name.split(".")[:-1]
            prefix = parent[: len(parent) - node.level + 1] if node.level else []
            name = ".".join([*prefix, *([node.module] if node.module else [])])
            if not node.level:
                name = node.module or ""
            if name:
                imported.add(name)
            for alias in node.names:
                if name and alias.name != "*":
                    imported.add(f"{name}.{alias.name}")
        elif (
            isinstance(node, ast.Call)
            and _is_dynamic_import(node)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            imported.add(node.args[0].value)
    return imported


def _is_dynamic_import(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Name)
        and node.func.id in ("__import__", "import_module")
    ) or (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "import_module"
    )


def _unknown_dynamic_import(text: str) -> bool:
    return any(
        _is_dynamic_import(node)
        and not (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        )
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.Call)
    )


def _reverse_impact(root: Path, changed_modules: set[str]) -> tuple[set[str], list[str]]:
    """Expand changed modules through import consumers, without executing code."""
    imports: dict[str, set[str]] = {}
    blockers: list[str] = []
    unknown_dynamic: set[str] = set()
    for file in sorted((root / "src" / "llm_loop").rglob("*.py")):
        rel = file.relative_to(root).as_posix()
        module_name = _module(rel)
        try:
            if file.is_symlink():
                blockers.append(f"source_symlink_untrusted:{rel}")
                continue
            text = file.read_text(encoding="utf-8")
            imports[module_name] = _imports(text, module_name)
            if _unknown_dynamic_import(text):
                unknown_dynamic.add(module_name)
        except (OSError, UnicodeError, SyntaxError):
            if module_name in changed_modules:
                blockers.append(f"changed_source_unparseable:{rel}")
    affected = set(changed_modules)
    for _ in range(32):
        previous = len(affected)
        for module_name, dependencies in imports.items():
            if any(
                dep == target or dep.startswith(target + ".")
                for dep in dependencies
                for target in affected
            ):
                affected.add(module_name)
        if len(affected) == previous:
            break
        if len(affected) > 250:
            blockers.append("impact_scope_too_broad")
            break
    else:
        blockers.append("impact_closure_not_converged")
    for module in sorted(unknown_dynamic):
        package = ".".join(module.split(".")[:2])
        if module in affected or any(
            changed == package or changed.startswith(package + ".")
            for changed in changed_modules
        ):
            blockers.append(f"dynamic_import_impact_unknown:{module}")
    return affected, blockers


def _test_hits(text: str, affected: set[str], test_path: str) -> set[str]:
    """Match Python imports or fully-qualified string references, not words.

    Matching the short module name (e.g. 'goal') as arbitrary prose caused
    1219 unrelated tests to be selected in a real development worktree.
    """
    tree = ast.parse(text)
    imported = _imports(text, test_path.removesuffix(".py").replace("/", "."))
    strings = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    return {
        target
        for target in affected
        if any(dep == target or dep.startswith(target + ".") for dep in imported)
        or any(target in literal for literal in strings)
    }


def select_tests(
    root: Path,
    changed_paths: list[str],
    explicit_tests: list[str],
) -> dict[str, Any]:
    """Pure selection given a change set and approved REQ test paths."""
    blockers: list[str] = []
    selected: set[str] = set()
    if not changed_paths:
        blockers.append("no_changes")
    for raw in [*changed_paths, *explicit_tests]:
        path = PurePosixPath(raw)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            blockers.append(f"unsafe_path:{raw}")
        elif (root / raw).is_symlink():
            blockers.append(f"symlink_untrusted:{raw}")
    for test in explicit_tests:
        if not test.startswith("tests/") or not test.endswith(".py"):
            blockers.append(f"unsupported_explicit_test:{test}")
        elif not (root / test).is_file():
            blockers.append(f"missing_explicit_test:{test}")
        else:
            selected.add(test)
    changed_modules: set[str] = set()
    for path in changed_paths:
        if path.startswith("tests/") and path.endswith(".py") and (root / path).is_file():
            selected.add(path)
        elif path.startswith("src/"):
            module_name = _module(path)
            if not module_name:
                blockers.append(f"unsupported_source:{path}")
            else:
                changed_modules.add(module_name)
        elif path.startswith("webui/") or path == "pyproject.toml":
            blockers.append(f"requires_non_pytest_impact_review:{path}")
        elif not path.startswith(("docs/", "scripts/", "tests/")):
            blockers.append(f"unknown_change_scope:{path}")
    affected, impact_blockers = _reverse_impact(root, changed_modules)
    blockers.extend(impact_blockers)
    matched_impact: set[str] = set()
    for file in sorted((root / "tests").rglob("*.py")):
        rel = file.relative_to(root).as_posix()
        if file.is_symlink():
            blockers.append(f"test_symlink_untrusted:{rel}")
            continue
        try:
            hits = _test_hits(file.read_text(encoding="utf-8"), affected, rel)
        except (OSError, UnicodeError, SyntaxError):
            blockers.append(f"test_unreadable_or_unparseable:{rel}")
            continue
        if hits:
            if file.name == "conftest.py":
                blockers.append(f"fixture_impact_requires_full_gate:{rel}")
            elif file.name.startswith("test_") or file.name.endswith("_test.py"):
                selected.add(rel)
            else:
                blockers.append(f"test_helper_impact_requires_review:{rel}")
            matched_impact.update(hits)
    for module_name in changed_modules:
        if module_name not in matched_impact:
            blockers.append(f"no_impact_test_for:{module_name}")
    if "docs/ai_rules.md" in changed_paths:
        rule_test = "tests/unit/test_ai_rules_sync.py"
        if (root / rule_test).is_file():
            selected.add(rule_test)
        else:
            blockers.append("missing_rules_sync_test")
    if not selected:
        blockers.append("empty_test_selection")
    if len(selected) > MAX_DEV_TEST_FILES:
        blockers.append(f"impact_scope_too_broad:{len(selected)}")
    return {
        "changed_paths": sorted(set(changed_paths)),
        "selected_tests": sorted(selected),
        "affected_modules": sorted(affected),
        "blockers": sorted(set(blockers)),
    }


def _changed_paths(root: Path, base: str) -> tuple[list[str], str]:
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        raise ValueError("base must be an exact 40-character commit SHA")
    head = _git(root, "rev-parse", "HEAD")
    resolved_base = _git(root, "rev-parse", "--verify", f"{base}^{{commit}}")
    remote_main = _git(root, "rev-parse", "--verify", "refs/remotes/origin/main^{commit}")
    if resolved_base != remote_main:
        raise ValueError("stale base: must equal current origin/main SHA")
    _git(root, "merge-base", "--is-ancestor", resolved_base, head)
    if _git(root, "symbolic-ref", "--short", "HEAD") == "main":
        raise ValueError("dev gate is forbidden on protected main")
    changed = _git(root, "diff", "--name-only", resolved_base).splitlines()
    untracked = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted(set(changed + untracked)), head


def _lane_blockers(
    *,
    root: Path,
    audit_dir: Path,
    goal_id: str,
    base: str,
    changed: list[str],
    affected_modules: list[str],
) -> list[str]:
    """Read-only cross-Lane check; never treats precheck warnings as grants."""
    lanes = LaneStore(
        audit_dir, lock_strict=True, enforce_cross_goal=True, repo_root=root
    ).list()
    branch = _git(root, "symbolic-ref", "--short", "HEAD")
    mine = [
        lane
        for lane in lanes
        if lane.get("goal_id") == goal_id
        and lane.get("branch") == branch
        and Path(str(lane.get("worktree") or "")).resolve() == root.resolve()
        and lane.get("status") in ("open", "active")
    ]
    if len(mine) != 1:
        return ["lane_identity_missing_or_ambiguous"]
    current = mine[0]
    blockers: list[str] = []
    if current.get("base_main_sha") != base:
        blockers.append("lane_base_mismatch")
    undeclared = set(changed) - set(current.get("paths") or [])
    blockers.extend(f"lane_path_undeclared:{p}" for p in sorted(undeclared))
    affected = set(affected_modules)
    for lane in lanes:
        if lane.get("lane_id") == current.get("lane_id"):
            continue
        other_id = str(lane.get("lane_id"))
        other_paths = set(lane.get("paths") or [])
        if set(changed) & other_paths:
            blockers.append(f"cross_lane_path_conflict:{other_id}")
        other_modules = {_module(path) for path in other_paths}
        if (other_modules - {""}) & affected:
            blockers.append(f"cross_lane_dependency_conflict:{other_id}")
    return sorted(set(blockers))


def _fingerprint(root: Path, base: str, head: str, paths: list[str]) -> str:
    digest = hashlib.sha256((base + "\n" + head + "\n").encode())
    for name in paths:
        digest.update(name.encode("utf-8") + b"\0")
        file = root / name
        digest.update(file.read_bytes() if file.is_file() else b"<deleted>")
        digest.update(b"\0")
    return digest.hexdigest()


def _inputs_fingerprint(
    root: Path,
    *,
    worktree_fingerprint: str,
    design: Path,
    ledger: Path,
    req_id: str,
    selected_tests: list[str],
) -> str:
    """Bind the decision to all inputs, not only modified source bytes."""
    digest = hashlib.sha256((worktree_fingerprint + "\n" + req_id).encode())
    for path in (design, ledger):
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    for test in selected_tests:
        if (root / test).is_symlink():
            raise ValueError(f"test_symlink_untrusted:{test}")
        digest.update(test.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256((root / test).read_bytes()).digest())
    return digest.hexdigest()


def _run_check(root: Path, args: list[str], timeout: int = 180) -> dict[str, Any]:
    from llm_loop.runtime.resolver import legacy_env_snapshot

    started = time.monotonic()
    # Do not let inherited pytest flags silently skip the selected tests or
    # load an unapproved plugin in a purported development PASS.
    env = {
        key: value for key, value in legacy_env_snapshot().items()
        if key not in {
            "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
            "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT",
        }
    }
    env["PYTHONPATH"] = str(root / "src")
    try:
        result = subprocess.run(
            args,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=env,
        )
        return {
            "argv": args[1:],
            "exit_code": result.returncode,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "output_tail": (result.stdout + result.stderr)[-1200:],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "argv": args[1:],
            "exit_code": -1,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "output_tail": f"{type(exc).__name__}: {exc}",
        }


def run_dev_gate(
    *,
    root: Path,
    design: Path,
    audit_dir: Path,
    goal_id: str,
    req_id: str,
    base: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": "lfl.dev_gate.v1",
        "status": "BLOCKED",
        "release_qualified": False,
        "goal_id": goal_id,
        "req_id": req_id,
        "base": base,
        "checks": [],
    }
    try:
        text = design.read_text(encoding="utf-8")
        if text.count(f"<!-- LFL-REQ-GOAL: {goal_id} -->") != 1:
            raise ValueError("design goal binding missing or mismatched")
        rows = parse_requirements(text)
        req = next((row for row in rows if row["req_id"] == req_id), None)
        if req is None:
            raise ValueError(f"REQ not declared: {req_id}")
        ledger = audit_dir / "tasks" / f"{safe_goal_id(goal_id)}.jsonl"
        if not ledger.is_file():
            raise ValueError("TaskStore ledger missing")
        ledger_before = hashlib.sha256(ledger.read_bytes()).hexdigest()
        tasks = {task.task_id: task for task in TaskStore(audit_dir).list_for_goal(goal_id)}
        if hashlib.sha256(ledger.read_bytes()).hexdigest() != ledger_before:
            raise ValueError("TaskStore ledger changed during planning")
        task = tasks.get(str(req["task_id"]))
        if task is None or req["acceptance"] not in task.acceptance:
            raise ValueError("REQ Task binding missing or acceptance changed")
        if task.status in ("failed", "cancelled"):
            raise ValueError(f"REQ Task is not actionable: {task.status}")
        changed, head = _changed_paths(root, base)
        selection = select_tests(root, changed, req["incremental"])
        report.update(selection)
        report["blockers"] = sorted(
            set(
                selection["blockers"]
                + _lane_blockers(
                    root=root,
                    audit_dir=audit_dir,
                    goal_id=goal_id,
                    base=base,
                    changed=changed,
                    affected_modules=selection["affected_modules"],
                )
            )
        )
        report["head"] = head
        report["worktree_fingerprint"] = _fingerprint(root, base, head, changed)
        report["design_sha256"] = hashlib.sha256(design.read_bytes()).hexdigest()
        report["ledger_sha256"] = ledger_before
        report["input_fingerprint"] = _inputs_fingerprint(
            root,
            worktree_fingerprint=report["worktree_fingerprint"],
            design=design,
            ledger=ledger,
            req_id=req_id,
            selected_tests=selection["selected_tests"],
        )
        if report["blockers"]:
            return report
        if dry_run:
            report["status"] = "DRY_RUN"
            return report
        changed_python = [p for p in changed if p.endswith(".py") and (root / p).is_file()]
        for argv in (
            [sys.executable, "-m", "ruff", "check", *changed_python] if changed_python else [],
            [sys.executable, "-m", "pyright", *changed_python] if changed_python else [],
            [sys.executable, "-m", "pytest", "-q", *selection["selected_tests"]],
        ):
            if not argv:
                continue
            check = _run_check(root, argv)
            report["checks"].append(check)
            if check["exit_code"] != 0:
                report["status"] = "FAIL"
                return report
        after_changed, after_head = _changed_paths(root, base)
        after_inputs = _inputs_fingerprint(
            root,
            worktree_fingerprint=_fingerprint(root, base, after_head, after_changed),
            design=design,
            ledger=ledger,
            req_id=req_id,
            selected_tests=selection["selected_tests"],
        )
        if after_inputs != report["input_fingerprint"]:
            report["status"] = "BLOCKED"
            report["error"] = "worktree/design/ledger/tests changed during gate"
            return report
        report["staged_tree"] = _git(root, "write-tree")
        report["completed_at"] = time.time()
        report["status"] = "PASS"
    except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report

"""Incremental selection must include consumers and refuse uncertain impact."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from llm_loop.introspection.dev_gate import run_dev_gate, select_tests
from llm_loop.introspection.lane import LaneStore
from llm_loop.introspection.task_store import TaskStore

GOAL = "GOAL-20261120-devgate"
ACCEPTANCE = "开发期增量测试覆盖新增和影响面且不假PASS"


def _write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _fixture_tree(root: Path) -> None:
    _write(root, "src/llm_loop/pkg/foo.py", "def value():\n    return 1\n")
    _write(root, "src/llm_loop/pkg/bar.py", "from llm_loop.pkg.foo import value\n")
    _write(root, "tests/unit/test_foo.py", "from llm_loop.pkg.foo import value\n")
    _write(root, "tests/unit/test_bar.py", "from llm_loop.pkg.bar import value\n")
    _write(root, "tests/unit/test_dynamic.py", 'monkeypatch_path = "llm_loop.pkg.foo.value"\n')
    _write(root, "tests/unit/test_explicit.py", "def test_x():\n    assert True\n")
    _write(root, "tests/unit/test_ai_rules_sync.py", "def test_rules():\n    assert True\n")


def test_reverse_imports_and_monkeypatch_consumers_selected(tmp_path):
    _fixture_tree(tmp_path)
    result = select_tests(
        tmp_path,
        ["src/llm_loop/pkg/foo.py"],
        ["tests/unit/test_explicit.py"],
    )
    assert result["blockers"] == []
    assert {
        "tests/unit/test_foo.py",
        "tests/unit/test_bar.py",
        "tests/unit/test_dynamic.py",
        "tests/unit/test_explicit.py",
    } <= set(result["selected_tests"])
    assert "llm_loop.pkg.bar" in result["affected_modules"]


def test_literal_dynamic_import_consumer_is_selected(tmp_path):
    _fixture_tree(tmp_path)
    _write(
        tmp_path, "src/llm_loop/pkg/loader.py",
        'import importlib\nitem = importlib.import_module("llm_loop.pkg.foo")\n',
    )
    _write(tmp_path, "tests/unit/test_loader.py", "import llm_loop.pkg.loader\n")
    result = select_tests(
        tmp_path, ["src/llm_loop/pkg/foo.py"], ["tests/unit/test_explicit.py"]
    )
    assert result["blockers"] == []
    assert "tests/unit/test_loader.py" in result["selected_tests"]


def test_unknown_dynamic_import_in_related_package_blocks(tmp_path):
    _fixture_tree(tmp_path)
    _write(
        tmp_path, "src/llm_loop/pkg/loader.py",
        "import importlib\ndef load(name):\n    return importlib.import_module(name)\n",
    )
    result = select_tests(
        tmp_path, ["src/llm_loop/pkg/foo.py"], ["tests/unit/test_explicit.py"]
    )
    assert "dynamic_import_impact_unknown:llm_loop.pkg.loader" in result["blockers"]


def test_unrelated_dynamic_loader_does_not_block_narrow_package(tmp_path):
    _fixture_tree(tmp_path)
    _write(
        tmp_path, "src/llm_loop/other/loader.py",
        "import importlib\ndef load(name):\n    return importlib.import_module(name)\n",
    )
    result = select_tests(
        tmp_path, ["src/llm_loop/pkg/foo.py"], ["tests/unit/test_explicit.py"]
    )
    assert result["blockers"] == []


def test_symlinked_test_and_changed_source_are_rejected(tmp_path):
    _fixture_tree(tmp_path)
    (tmp_path / "tests/unit/test_link.py").symlink_to(
        tmp_path / "tests/unit/test_foo.py"
    )
    result = select_tests(
        tmp_path, ["src/llm_loop/pkg/foo.py"], ["tests/unit/test_explicit.py"]
    )
    assert "test_symlink_untrusted:tests/unit/test_link.py" in result["blockers"]
    (tmp_path / "src/llm_loop/pkg/link.py").symlink_to(
        tmp_path / "src/llm_loop/pkg/foo.py"
    )
    result = select_tests(
        tmp_path, ["src/llm_loop/pkg/link.py"], ["tests/unit/test_explicit.py"]
    )
    assert "symlink_untrusted:src/llm_loop/pkg/link.py" in result["blockers"]


def test_common_short_name_in_prose_is_not_an_import_dependency(tmp_path):
    _fixture_tree(tmp_path)
    _write(tmp_path, "tests/unit/test_unrelated.py", '"""The foo goal was completed."""\n')
    result = select_tests(
        tmp_path, ["src/llm_loop/pkg/foo.py"], ["tests/unit/test_explicit.py"]
    )
    assert result["blockers"] == []
    assert "tests/unit/test_unrelated.py" not in result["selected_tests"]


def test_broken_python_test_blocks_instead_of_silently_skipping(tmp_path):
    _fixture_tree(tmp_path)
    _write(tmp_path, "tests/unit/test_broken.py", "def invalid(:\n")
    result = select_tests(
        tmp_path, ["src/llm_loop/pkg/foo.py"], ["tests/unit/test_explicit.py"]
    )
    assert "test_unreadable_or_unparseable:tests/unit/test_broken.py" in result["blockers"]


def test_shared_conftest_impact_requires_full_gate(tmp_path):
    _fixture_tree(tmp_path)
    _write(tmp_path, "tests/conftest.py", "from llm_loop.pkg.foo import value\n")
    result = select_tests(
        tmp_path, ["src/llm_loop/pkg/foo.py"], ["tests/unit/test_explicit.py"]
    )
    assert "fixture_impact_requires_full_gate:tests/conftest.py" in result["blockers"]
    assert "tests/conftest.py" not in result["selected_tests"]


def test_changed_test_and_rules_are_included(tmp_path):
    _fixture_tree(tmp_path)
    result = select_tests(
        tmp_path,
        ["tests/unit/test_foo.py", "docs/ai_rules.md"],
        ["tests/unit/test_explicit.py"],
    )
    assert result["blockers"] == []
    assert "tests/unit/test_foo.py" in result["selected_tests"]
    assert "tests/unit/test_ai_rules_sync.py" in result["selected_tests"]


def test_empty_change_never_passes(tmp_path):
    _fixture_tree(tmp_path)
    result = select_tests(tmp_path, [], ["tests/unit/test_explicit.py"])
    assert "no_changes" in result["blockers"]


def test_unmapped_source_blocks_even_with_explicit_test(tmp_path):
    _fixture_tree(tmp_path)
    _write(tmp_path, "src/llm_loop/pkg/unknown.py", "x = 1\n")
    result = select_tests(
        tmp_path,
        ["src/llm_loop/pkg/unknown.py"],
        ["tests/unit/test_explicit.py"],
    )
    assert "no_impact_test_for:llm_loop.pkg.unknown" in result["blockers"]


def test_missing_explicit_and_unknown_scope_block(tmp_path):
    _fixture_tree(tmp_path)
    result = select_tests(
        tmp_path,
        ["pyproject.toml", "webui/src/app.tsx", "other/random.txt"],
        ["tests/unit/does_not_exist.py"],
    )
    assert "missing_explicit_test:tests/unit/does_not_exist.py" in result["blockers"]
    assert any("requires_non_pytest_impact_review" in x for x in result["blockers"])
    assert "unknown_change_scope:other/random.txt" in result["blockers"]


def test_path_traversal_and_unsupported_explicit_test_block(tmp_path):
    result = select_tests(tmp_path, ["../outside.py"], ["../secret.py"])
    assert any(x.startswith("unsafe_path:") for x in result["blockers"])
    assert any(x.startswith("unsupported_explicit_test:") for x in result["blockers"])


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "checkout", "-q", "-b", "lane")
    _fixture_tree(root)
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base")
    base = _git(root, "rev-parse", "HEAD")
    _git(root, "update-ref", "refs/remotes/origin/main", base)
    _write(root, "src/llm_loop/pkg/foo.py", "def value():\n    return 2\n")
    audit = tmp_path / "audit"
    task = TaskStore(audit).create(
        GOAL, "REQ-FLOW-003", acceptance=[ACCEPTANCE], evidence_required=True
    )
    LaneStore(
        audit, lock_strict=True, enforce_cross_goal=True, repo_root=root
    ).create(
        branch="lane",
        worktree=str(root.resolve()),
        base_main_sha=base,
        goal_id=GOAL,
        paths=["src/llm_loop/pkg/foo.py"],
    )
    design = tmp_path / "design.md"
    design.write_text(
        f"<!-- LFL-REQ-GOAL: {GOAL} -->\n"
        "<!-- LFL-REQ-MATRIX:v1 -->\n"
        "| REQ | Task | Slice | Required | Acceptance | Incremental | Final | Scope approval |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        f"| REQ-FLOW-003 | {task.task_id} | B | yes | {ACCEPTANCE} | tests/unit/test_explicit.py | R9 | - |\n"
        "<!-- /LFL-REQ-MATRIX -->\n",
        encoding="utf-8",
    )
    return root, audit, design, base


def test_real_git_worktree_dry_run_is_not_release_pass(tmp_path):
    root, audit, design, base = _repo(tmp_path)
    report = run_dev_gate(
        root=root,
        design=design,
        audit_dir=audit,
        goal_id=GOAL,
        req_id="REQ-FLOW-003",
        base=base,
        dry_run=True,
    )
    assert report["status"] == "DRY_RUN"
    assert report["release_qualified"] is False
    assert len(report["worktree_fingerprint"]) == 64
    assert "tests/unit/test_bar.py" in report["selected_tests"]
    assert report["checks"] == []


def test_dry_run_cli_exit_is_nonzero_and_receipt_is_explicit(tmp_path):
    root, audit, design, base = _repo(tmp_path)
    receipt = tmp_path / "dry-run.json"
    source_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable, str(source_root / "scripts" / "dev_gate.py"),
            "--goal", GOAL, "--req", "REQ-FLOW-003",
            "--base", base, "--design", str(design),
            "--audit-dir", str(audit), "--receipt", str(receipt), "--dry-run",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(source_root / "src")},
        timeout=30,
    )
    assert result.returncode == 2
    assert json.loads(receipt.read_text())["status"] == "DRY_RUN"


def test_test_runner_drops_inherited_pytest_filters(tmp_path, monkeypatch):
    import llm_loop.introspection.dev_gate as gate

    root, _, _, _ = _repo(tmp_path)
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k never")
    monkeypatch.setenv("PYTEST_PLUGINS", "malicious.plugin")
    result = gate._run_check(
        root,
        [
            sys.executable, "-c",
            "import os; assert 'PYTEST_ADDOPTS' not in os.environ;"
            " assert 'PYTEST_PLUGINS' not in os.environ",
        ],
    )
    assert result["exit_code"] == 0


def test_cli_rejects_non_temporary_receipt_path(tmp_path):
    root, audit, design, base = _repo(tmp_path)
    source_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable, str(source_root / "scripts" / "dev_gate.py"),
            "--goal", GOAL, "--req", "REQ-FLOW-003",
            "--base", base, "--design", str(design),
            "--audit-dir", str(audit),
            "--receipt", "/etc/lfl-dev-gate-must-not-write.json",
            "--dry-run",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(source_root / "src")},
        timeout=30,
    )
    assert result.returncode == 2
    assert "--receipt must be an absolute temporary path" in result.stderr


def test_protected_main_refused(tmp_path):
    root, audit, design, base = _repo(tmp_path)
    _git(root, "branch", "-m", "main")
    report = run_dev_gate(
        root=root,
        design=design,
        audit_dir=audit,
        goal_id=GOAL,
        req_id="REQ-FLOW-003",
        base=base,
        dry_run=True,
    )
    assert report["status"] == "BLOCKED"
    assert "protected main" in report["error"]


def test_unknown_req_or_bad_base_blocked(tmp_path):
    root, audit, design, base = _repo(tmp_path)
    assert run_dev_gate(
        root=root, design=design, audit_dir=audit, goal_id=GOAL,
        req_id="REQ-OTHER", base=base, dry_run=True,
    )["status"] == "BLOCKED"
    assert run_dev_gate(
        root=root, design=design, audit_dir=audit, goal_id=GOAL,
        req_id="REQ-FLOW-003", base="bad", dry_run=True,
    )["status"] == "BLOCKED"


def test_stale_origin_main_base_is_rejected(tmp_path):
    root, audit, design, base = _repo(tmp_path)
    assert run_dev_gate(
        root=root, design=design, audit_dir=audit, goal_id=GOAL,
        req_id="REQ-FLOW-003", base=base, dry_run=True,
    )["status"] == "DRY_RUN"
    _git(root, "commit", "--allow-empty", "-qm", "remote advanced")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    report = run_dev_gate(
        root=root, design=design, audit_dir=audit, goal_id=GOAL,
        req_id="REQ-FLOW-003", base=base, dry_run=True,
    )
    assert report["status"] == "BLOCKED"
    assert "stale base" in report["error"]


def test_missing_active_lane_cannot_pass(tmp_path):
    root, audit, design, base = _repo(tmp_path)
    store = LaneStore(audit, lock_strict=True, enforce_cross_goal=True, repo_root=root)
    lane = store.find_by_goal(GOAL)[0]
    store.close(lane["lane_id"], expected_version=1, status="closed", reason="fixture")
    report = run_dev_gate(
        root=root, design=design, audit_dir=audit, goal_id=GOAL,
        req_id="REQ-FLOW-003", base=base, dry_run=True,
    )
    assert report["status"] == "BLOCKED"
    assert "lane_identity_missing_or_ambiguous" in report["blockers"]


def test_undeclared_file_change_is_not_covered_by_lane(tmp_path):
    root, audit, design, base = _repo(tmp_path)
    _write(root, "src/llm_loop/pkg/extra.py", "x = 1\n")
    report = run_dev_gate(
        root=root, design=design, audit_dir=audit, goal_id=GOAL,
        req_id="REQ-FLOW-003", base=base, dry_run=True,
    )
    assert report["status"] == "BLOCKED"
    assert "lane_path_undeclared:src/llm_loop/pkg/extra.py" in report["blockers"]


def test_other_lane_dependent_module_blocks_even_without_file_overlap(tmp_path):
    root, audit, design, base = _repo(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    LaneStore(
        audit, lock_strict=True, enforce_cross_goal=True, repo_root=root
    ).create(
        branch="other",
        worktree=str(other),
        base_main_sha=base,
        goal_id="GOAL-other",
        paths=["src/llm_loop/pkg/bar.py"],
    )
    report = run_dev_gate(
        root=root, design=design, audit_dir=audit, goal_id=GOAL,
        req_id="REQ-FLOW-003", base=base, dry_run=True,
    )
    assert report["status"] == "BLOCKED"
    assert any(x.startswith("cross_lane_dependency_conflict:") for x in report["blockers"])


def test_failed_static_check_cannot_be_reported_pass(tmp_path, monkeypatch):
    root, audit, design, base = _repo(tmp_path)
    import llm_loop.introspection.dev_gate as gate

    monkeypatch.setattr(
        gate,
        "_run_check",
        lambda _root, argv: {"argv": argv, "exit_code": 1, "output_tail": "fixture failure"},
    )
    report = run_dev_gate(
        root=root,
        design=design,
        audit_dir=audit,
        goal_id=GOAL,
        req_id="REQ-FLOW-003",
        base=base,
    )
    assert report["status"] == "FAIL"
    assert report["checks"][0]["exit_code"] == 1


@pytest.mark.parametrize("mutated", ["source", "design", "ledger", "test"])
def test_input_mutation_during_gate_cannot_pass(tmp_path, monkeypatch, mutated):
    root, audit, design, base = _repo(tmp_path)
    import llm_loop.introspection.dev_gate as gate

    invoked = False

    def check(_root, argv):
        nonlocal invoked
        if not invoked:
            invoked = True
            if mutated == "source":
                _write(root, "src/llm_loop/pkg/foo.py", "def value():\n    return 999\n")
            elif mutated == "design":
                design.write_text(design.read_text() + "\nchanged\n")
            elif mutated == "ledger":
                ledger = audit / "tasks" / f"{GOAL}.jsonl"
                ledger.write_text(ledger.read_text() + "\n")
            else:
                _write(root, "tests/unit/test_explicit.py", "def test_x():\n    assert False\n")
        return {"argv": argv, "exit_code": 0, "output_tail": "fixture-pass"}

    monkeypatch.setattr(gate, "_run_check", check)
    report = run_dev_gate(
        root=root, design=design, audit_dir=audit, goal_id=GOAL,
        req_id="REQ-FLOW-003", base=base,
    )
    assert report["status"] == "BLOCKED"
    assert "changed during gate" in report["error"]
    assert report["release_qualified"] is False


def test_cancelled_req_task_refused_even_if_source_has_tests(tmp_path):
    root, audit, design, base = _repo(tmp_path)
    store = TaskStore(audit)
    task = store.list_for_goal(GOAL)[0]
    store.update(GOAL, task.task_id, status="cancelled")
    report = run_dev_gate(
        root=root,
        design=design,
        audit_dir=audit,
        goal_id=GOAL,
        req_id="REQ-FLOW-003",
        base=base,
        dry_run=True,
    )
    assert report["status"] == "BLOCKED"
    assert "not actionable" in report["error"]


def test_fingerprint_changes_with_uncommitted_source_bytes(tmp_path):
    root, audit, design, base = _repo(tmp_path)
    first = run_dev_gate(
        root=root, design=design, audit_dir=audit,
        goal_id=GOAL, req_id="REQ-FLOW-003", base=base, dry_run=True,
    )
    _write(root, "src/llm_loop/pkg/foo.py", "def value():\n    return 3\n")
    second = run_dev_gate(
        root=root, design=design, audit_dir=audit,
        goal_id=GOAL, req_id="REQ-FLOW-003", base=base, dry_run=True,
    )
    assert first["status"] == second["status"] == "DRY_RUN"
    assert first["worktree_fingerprint"] != second["worktree_fingerprint"]

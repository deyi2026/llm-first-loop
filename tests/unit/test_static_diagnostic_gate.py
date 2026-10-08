"""Adversarial tests for the immutable R9 diagnostic-debt ratchet."""

from __future__ import annotations

import collections
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import check_static_diagnostics as gate


def _diag(path: str = "src/example.py", code: str = "F401", line: str = "import os"):
    return (path, code, "Unused import", hashlib.sha256(line.encode()).hexdigest())


def test_exact_existing_debt_visible_but_not_new() -> None:
    key = _diag()
    new, resolved, touched = gate.evaluate(
        collections.Counter({key: 1}), collections.Counter({key: 1}), set()
    )
    assert not new and not resolved and not touched


def test_second_occurrence_of_known_error_is_blocked() -> None:
    key = _diag()
    new, resolved, _ = gate.evaluate(
        collections.Counter({key: 2}), collections.Counter({key: 1}), set()
    )
    assert new[key] == 1 and not resolved


def test_new_error_in_already_red_file_is_blocked() -> None:
    old = _diag()
    new_key = _diag(code="F821")
    new, _, _ = gate.evaluate(
        collections.Counter({old: 1, new_key: 1}),
        collections.Counter({old: 1}),
        set(),
    )
    assert new[new_key] == 1


def test_modified_file_must_be_zero_even_for_historical_issue() -> None:
    key = _diag()
    new, resolved, touched = gate.evaluate(
        collections.Counter({key: 1}),
        collections.Counter({key: 1}),
        {"src/example.py"},
    )
    assert not new and not resolved and touched == [key]


def test_resolved_old_diagnostic_never_counts_as_new() -> None:
    new, resolved, touched = gate.evaluate(
        collections.Counter(), collections.Counter({_diag(): 1}), set()
    )
    assert not new and sum(resolved.values()) == 1 and not touched


def test_ruff_duplicate_normalize_uses_multiplicity(tmp_path: Path) -> None:
    file = tmp_path / "src" / "example.py"
    file.parent.mkdir()
    file.write_text("import os\n")
    item = {
        "filename": str(file), "code": "F401", "message": "Unused import",
        "location": {"row": 1, "column": 1},
    }
    result = gate.normalize("ruff", [item, item], tmp_path)
    assert sum(result.values()) == 2 and len(result) == 1


def test_pyright_normalize_ignores_warning_but_retains_error(tmp_path: Path) -> None:
    file = tmp_path / "src" / "example.py"
    file.parent.mkdir()
    file.write_text("value = None\n")
    item = {
        "file": str(file), "severity": "error", "rule": "reportOptionalCall",
        "message": "Cannot call None",
        "range": {"start": {"line": 0, "character": 0}},
    }
    result = gate.normalize("pyright", {"generalDiagnostics": [
        item, {**item, "severity": "warning"},
    ]}, tmp_path)
    assert sum(result.values()) == 1


def test_diagnostic_outside_repo_is_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside repo"):
        gate.normalize("ruff", [{
            "filename": "/outside/forbidden.py", "code": "F401",
            "message": "issue", "location": {"row": 1},
        }], tmp_path)


def test_source_line_mutation_changes_fingerprint(tmp_path: Path) -> None:
    file = tmp_path / "src" / "example.py"
    file.parent.mkdir()
    file.write_text("import os\n")
    old = gate.normalize("ruff", [{
        "filename": str(file), "code": "F401", "message": "Unused import",
        "location": {"row": 1},
    }], tmp_path)
    file.write_text("import sys\n")
    current = gate.normalize("ruff", [{
        "filename": str(file), "code": "F401", "message": "Unused import",
        "location": {"row": 1},
    }], tmp_path)
    assert sum((current - old).values()) == 1


def test_baseline_duplicate_key_cannot_increase_debt() -> None:
    row = gate.serialize(collections.Counter({_diag(): 1}))[0]
    with pytest.raises(ValueError, match="duplicate baseline"):
        gate.deserialize([row, row])
    with pytest.raises(ValueError, match="invalid"):
        gate.deserialize([{**row, "count": 0}])


def _git(root: Path, *cmd: str) -> str:
    return subprocess.run(["git", *cmd], cwd=root, check=True, text=True, capture_output=True).stdout.strip()


def _temp_repo(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "R9 gate test")
    _git(tmp_path, "config", "user.email", "gate@example.invalid")
    (tmp_path / "marker.txt").write_text("frozen original\n")
    _git(tmp_path, "add", "marker.txt")
    _git(tmp_path, "commit", "-m", "origin")
    origin = _git(tmp_path, "rev-parse", "HEAD")
    baseline: dict[str, object] = {
        "schema": gate.SCHEMA, "origin_head": origin,
        "versions": {"ruff": "ruff 0.16.5", "pyright": "pyright 1.1.411"},
        "diagnostics": {"ruff": [], "pyright": []},
    }
    destination = tmp_path / gate.BASELINE_REL
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps(baseline, sort_keys=True) + "\n")
    _git(tmp_path, "add", gate.BASELINE_REL)
    _git(tmp_path, "commit", "-m", "introduce frozen baseline")
    return destination, baseline


def test_frozen_baseline_is_validated_against_git_parent(tmp_path: Path) -> None:
    p, baseline = _temp_repo(tmp_path)
    gate.validate_baseline(tmp_path, baseline, p.read_bytes(), gate.TOOLS)


def test_baseline_ledger_rewrite_is_rejected(tmp_path: Path) -> None:
    p, baseline = _temp_repo(tmp_path)
    # Simulate the next commit after an independently reviewed introduction.
    # At initial bootstrap HEAD^ rightly has no ledger; at every successor
    # HEAD^ must have the exact same ledger bytes.
    (tmp_path / "next.txt").write_text("subsequent independent change\n")
    _git(tmp_path, "add", "next.txt")
    _git(tmp_path, "commit", "-m", "successor")
    modified = {**baseline, "versions": {"ruff": "untrusted", "pyright": "untrusted"}}
    raw = (json.dumps(modified, sort_keys=True) + "\n").encode()
    p.write_bytes(raw)
    with pytest.raises(ValueError, match="frozen historical debt ledger changed"):
        gate.validate_baseline(tmp_path, modified, raw, gate.TOOLS)


def test_frozen_diagnostics_json_is_strictly_complete(tmp_path: Path) -> None:
    p, baseline = _temp_repo(tmp_path)
    broken = {**baseline, "diagnostics": {"ruff": []}}
    with pytest.raises(ValueError, match="schema/tools"):
        gate.validate_baseline(tmp_path, broken, p.read_bytes(), gate.TOOLS)


def test_pinned_ledger_hash_rejects_silent_rebaseline(tmp_path: Path) -> None:
    p, baseline = _temp_repo(tmp_path)
    with pytest.raises(ValueError, match="SHA256 drift"):
        gate.validate_baseline(
            tmp_path, baseline, p.read_bytes(), gate.TOOLS, frozen_sha256="0" * 64,
        )


def test_changed_files_include_newly_added_code(tmp_path: Path) -> None:
    _temp_repo(tmp_path)
    path = tmp_path / "scripts" / "brand_new.py"
    path.parent.mkdir()
    path.write_text("value = 1\n")
    assert "scripts/brand_new.py" in gate.changed_python_paths(tmp_path)

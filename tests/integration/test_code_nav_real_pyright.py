from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "code_nav.py"


def load_code_nav() -> ModuleType:
    spec = importlib.util.spec_from_file_location("code_nav_real_fixture", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_fixture(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "ignored").mkdir()
    (root / "pyproject.toml").write_text(
        '[tool.pyright]\ninclude = ["src"]\n',
        encoding="utf-8",
    )
    (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (root / "src/api.py").write_text(
        """def target(value: int = 0) -> int:
    return value + 1


def caller() -> int:
    first = target()
    second = target()
    return first + second
""",
        encoding="utf-8",
    )
    (root / "src/other.py").write_text(
        """from .api import target


def external_caller() -> int:
    return target(3)
""",
        encoding="utf-8",
    )
    (root / "tests/test_api.py").write_text(
        """from src.api import target


def test_target() -> None:
    assert target(4) == 5
""",
        encoding="utf-8",
    )
    (root / "ignored/cache.py").write_text("target\ntarget\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "pyproject.toml", ".gitignore", "src", "tests"],
        cwd=root,
        check=True,
    )


def run_nav(
    root: Path,
    langserver: Path,
    *args: str,
    cwd: Path | None = None,
) -> dict:
    env = os.environ.copy()
    env["PATH"] = str(langserver.parent) + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            *args,
            "--json",
        ],
        cwd=cwd or root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(proc.stdout)


def test_real_pyright_fixture_contract(tmp_path: Path) -> None:
    nav = load_code_nav()
    langserver_raw = nav.find_langserver(str(REPO_ROOT))
    assert langserver_raw is not None, "pyright-langserver is required for this integration test"
    langserver = Path(langserver_raw)

    fixture = tmp_path / "repo"
    fixture.mkdir()
    write_fixture(fixture)

    refs_root = run_nav(fixture, langserver, "refs", "src/api.py", "target")
    refs_subdir = run_nav(
        fixture,
        langserver,
        "refs",
        "src/api.py",
        "target",
        cwd=fixture / "src",
    )
    callers = run_nav(fixture, langserver, "callers", "src/api.py", "target")
    callees = run_nav(fixture, langserver, "callees", "src/api.py", "caller")

    assert refs_root["status"] == "ok"
    assert refs_root["trust"]["analysis_ready"] is True
    assert refs_root["trust"]["semantic_scope"]["include"] == ["src"]
    assert refs_root["count"] == 5
    assert refs_root["files"] == 2
    assert [(r["path"], r["line"]) for r in refs_root["refs"]] == [
        ("src/api.py", 1),
        ("src/api.py", 6),
        ("src/api.py", 7),
        ("src/other.py", 1),
        ("src/other.py", 5),
    ]
    assert refs_root["refs"] == refs_subdir["refs"]

    lexical = refs_root["cross_check"]
    assert lexical["universe"] == "git-visible-python"
    assert lexical["matching_files"] == 1
    assert lexical["matching_lines"] == 2
    assert lexical["occurrences"] == 2
    assert lexical["by_top_level_dir"] == {"tests": 2}
    assert lexical["inside_configured_include"] == {
        "matching_files": 0,
        "occurrences": 0,
    }
    assert lexical["outside_configured_include"] == {
        "matching_files": 1,
        "occurrences": 2,
    }
    assert "ignored" not in lexical["by_top_level_dir"]

    assert callers["status"] == "ok"
    assert callers["count"] == 2
    assert callers["calls"] == [
        {
            "name": "caller",
            "site_path": "src/api.py",
            "site_lines": [6, 7],
            "caller_definition_path": "src/api.py",
            "caller_definition_line": 5,
            "caller_definition_col": 5,
        },
        {
            "name": "external_caller",
            "site_path": "src/other.py",
            "site_lines": [5],
            "caller_definition_path": "src/other.py",
            "caller_definition_line": 4,
            "caller_definition_col": 5,
        },
    ]

    assert callees["status"] == "ok"
    assert callees["count"] == 1
    assert callees["calls"] == [
        {
            "name": "target",
            "site_path": "src/api.py",
            "site_lines": [6, 7],
            "target_path": "src/api.py",
            "target_definition_line": 1,
            "target_definition_col": 5,
        }
    ]

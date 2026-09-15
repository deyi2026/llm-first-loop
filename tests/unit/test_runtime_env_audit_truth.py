"""Proof-gate tests for the runtime environment AST inventory.

These fixtures exercise source shapes that exist in production but were invisible to
C0's first scanner.  The audit is mechanical only: it identifies process-environment
access and execution timing; it does not decide whether a business value is useful.
"""
from __future__ import annotations

from pathlib import Path

from scripts.audit_runtime_env import build_inventory, scan_tree


def _scan(tmp_path: Path, source: str):
    src = tmp_path / "src"
    src.mkdir()
    (src / "sample.py").write_text(source, encoding="utf-8")
    return scan_tree(src)


def test_scan_tree_follows_os_module_aliases(tmp_path: Path) -> None:
    items = _scan(
        tmp_path,
        """
import os as _os

def read_models():
    return _os.environ.get("WEB_MODELS", "")
""",
    )
    hit = [item for item in items if item.key == "WEB_MODELS"]
    assert len(hit) == 1
    assert hit[0].scope == "read_models"
    assert hit[0].origin == "direct"
    assert hit[0].module_import is False


def test_scan_tree_follows_getenv_and_environ_aliases(tmp_path: Path) -> None:
    items = _scan(
        tmp_path,
        """
from os import environ as _env
from os import getenv as _getenv

A = _env.get("WEB_DOC_BACKEND", "local")
B = _getenv("WEB_DOC_TIMEOUT", "120")
""",
    )
    got = {item.key: item for item in items if item.key.startswith("WEB_DOC_")}
    assert set(got) == {"WEB_DOC_BACKEND", "WEB_DOC_TIMEOUT"}
    assert all(item.module_import for item in got.values())
    assert all(item.origin == "direct" for item in got.values())


def test_literal_env_wrapper_calls_are_projected_at_real_call_scope(tmp_path: Path) -> None:
    items = _scan(
        tmp_path,
        """
import os

def _env_float(name, default):
    return float(os.environ.get(name, str(default)))

EXIT_WAIT = _env_float("FEISHU_EXIT_WAIT_S", 10)

def runtime_value():
    return _env_float("FEISHU_RUNTIME_ONLY_S", 3)
""",
    )
    projected = {item.key: item for item in items if item.origin == "literal_helper"}
    assert set(projected) == {"FEISHU_EXIT_WAIT_S", "FEISHU_RUNTIME_ONLY_S"}
    assert projected["FEISHU_EXIT_WAIT_S"].module_import is True
    assert projected["FEISHU_EXIT_WAIT_S"].scope == "<module>"
    assert projected["FEISHU_RUNTIME_ONLY_S"].module_import is False
    assert projected["FEISHU_RUNTIME_ONLY_S"].scope == "runtime_value"


def test_dynamic_api_key_env_is_classified_as_secret_boundary(tmp_path: Path) -> None:
    inventory = build_inventory(
        _scan(
            tmp_path,
            """
import os

def credential(spec):
    return os.environ.get(spec.api_key_env, "")

def ordinary(key):
    return os.environ.get(key, "")
""",
        )
    )
    assert inventory["access_class_counts"]["dynamic_secret"] == 1
    assert inventory["access_class_counts"]["dynamic_or_bulk"] == 1
    assert len(inventory["dynamic_secret_signatures"]) == 1
    assert "credential" in inventory["dynamic_secret_signatures"][0]


def test_inventory_separates_direct_and_literal_helper_counts(tmp_path: Path) -> None:
    inventory = build_inventory(
        _scan(
            tmp_path,
            """
import os as _os

def _env_flag(name, default):
    return _os.environ.get(name, str(default))

ENABLED = _env_flag("FEISHU_WS_ENABLED", True)
""",
        )
    )
    assert inventory["schema_version"] == 2
    assert inventory["direct_access_count"] == 1
    assert inventory["literal_helper_access_count"] == 1
    assert inventory["access_count"] == 1  # backward-compatible physical/direct count
    assert inventory["effective_access_count"] == 2
    assert inventory["module_import_direct_access_count"] == 0
    assert inventory["module_import_helper_access_count"] == 1
    assert inventory["module_import_access_count"] == 1
    assert inventory["module_import_signature_counts"]

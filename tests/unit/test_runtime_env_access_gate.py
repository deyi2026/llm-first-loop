"""One-way ratchets for process-environment access.

Schema v2 freezes three independent facts:
1. physical/direct os.environ/os.getenv syntax (alias-aware),
2. local wrapper call sites whose key is mechanically recoverable,
3. effective module-import reads, including wrapper calls.

Deleting/migrating debt is always allowed. Adding debt requires an explicit reviewed
baseline update.  Secret-looking runtime key *values* are never read by this audit.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_runtime_env import build_inventory, scan_tree

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "tests" / "fixtures" / "runtime_env_access_baseline.json"


def _baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def _assert_signature_ratchet(current: dict[str, int], allowed: dict[str, int], label: str) -> None:
    regressions = {
        signature: count
        for signature, count in current.items()
        if count > allowed.get(signature, 0)
    }
    assert not regressions, f"{label} 新增/扩大，需显式审查 baseline：{regressions}"


def test_direct_environment_access_is_one_way_ratchet():
    baseline = _baseline()
    current = build_inventory(scan_tree(ROOT / "src"))
    _assert_signature_ratchet(
        current["signature_counts"],
        baseline["signature_counts"],
        "直接 os.environ/os.getenv 访问",
    )
    assert current["direct_access_count"] <= baseline["direct_access_count"]
    assert current["access_count"] <= baseline["access_count"]


def test_literal_or_dynamic_helper_environment_access_is_one_way_ratchet():
    baseline = _baseline()
    current = build_inventory(scan_tree(ROOT / "src"))
    _assert_signature_ratchet(
        current["helper_signature_counts"],
        baseline["helper_signature_counts"],
        "可解析 env wrapper 调用",
    )
    assert current["literal_helper_access_count"] <= baseline["literal_helper_access_count"]
    assert current["dynamic_helper_access_count"] <= baseline["dynamic_helper_access_count"]


def test_module_import_environment_access_is_one_way_ratchet():
    baseline = _baseline()
    current = build_inventory(scan_tree(ROOT / "src"))
    _assert_signature_ratchet(
        current["module_import_signature_counts"],
        baseline["module_import_signature_counts"],
        "模块 import 阶段 env 读取",
    )
    assert current["module_import_access_count"] <= baseline["module_import_access_count"]
    # P1-A did remove all *physical* module-scope env syntax.  C0-A discovered five
    # wrapper-mediated reads; keep the stronger physical invariant while separately
    # ratcheting the effective import-time truth above.
    assert current["module_import_direct_access_count"] == 0


def test_dynamic_secret_boundary_is_one_way_ratchet():
    baseline = _baseline()
    current = build_inventory(scan_tree(ROOT / "src"))
    assert set(current["dynamic_secret_signatures"]).issubset(
        baseline["dynamic_secret_signatures"]
    )


def test_runtime_toml_template_contains_no_secret_fields():
    text = (ROOT / "runtime.toml.example").read_text(encoding="utf-8").lower()
    for forbidden in ("api_key", "api-key", "password", "app_secret", "iam_token"):
        assert forbidden not in text


def test_c0a_env_ratchet_baseline_records_proof_correction():
    baseline = _baseline()
    assert baseline["schema_version"] == 2
    ctx = baseline["baseline_context"]
    assert ctx["phase"] == "runtime-config-c0a-proof-gate-20260916"
    assert ctx["parent_commit"] == "32a9a26611e147a32d4dc0fcccdf10dbc0d40c06"
    assert ctx["previous_scanner_access_count"] == 126
    assert ctx["alias_recovered_direct_access_count"] == 8
    assert ctx["corrected_direct_access_count"] == 134
    assert ctx["corrected_module_import_access_count"] == 5
    assert ctx["prior_p0_context"]["parent_commit"] == "e5bfe24985efd3328592692b496241b0ed743781"

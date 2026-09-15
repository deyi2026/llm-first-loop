"""One-way ratchet for direct process-environment access.

Existing debt is frozen by AST signature/count. Deleting or migrating a direct
access is always allowed. Adding a new direct access (including a new call in an
existing scope) requires an explicit reviewed baseline update.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_runtime_env import build_inventory, scan_tree

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "tests" / "fixtures" / "runtime_env_access_baseline.json"


def test_direct_environment_access_is_one_way_ratchet():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    current = build_inventory(scan_tree(ROOT / "src"))
    allowed = baseline["signature_counts"]
    regressions = {
        signature: count
        for signature, count in current["signature_counts"].items()
        if count > allowed.get(signature, 0)
    }
    assert not regressions, (
        "新增了直接 os.environ/os.getenv 读取或扩大了旧读取。"
        "业务配置应经 RuntimeConfig/Settings 显式注入；若确属 bootstrap/secret 边界，"
        f"需单独审查并显式更新 baseline。新增: {regressions}"
    )
    assert current["access_count"] <= baseline["access_count"]


def test_runtime_toml_template_contains_no_secret_fields():
    text = (ROOT / "runtime.toml.example").read_text(encoding="utf-8").lower()
    for forbidden in ("api_key", "api-key", "password", "app_secret", "iam_token"):
        assert forbidden not in text


def test_p0_env_ratchet_baseline_records_reviewed_parent_delta():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    ctx = baseline["baseline_context"]
    assert ctx["parent_commit"] == "96a4dce50c2dcaa0509780e1ff30929d6ca9cc8f"
    assert ctx["parent_access_count"] == 243
    assert ctx["candidate_access_count"] == 202
    assert len(ctx["reviewed_new_signatures"]) == 7
    assert all("business_value" not in sig for sig in ctx["reviewed_new_signatures"])

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

from scripts.audit_runtime_env import build_inventory, describe_registration, main, scan_tree

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


# ── 一键登记（--update-baseline）: 让"加债"变成可见的一步 ────────────────────
# 背景: 棘轮本身只报红，不改基线；人工去手改 JSON 容易漏、也看不出方向。这条通道
# 把"登记"变成: 打印逐项 diff(放宽/收紧) → 放宽必须给 --reason → 写入 registration_log。


def _write_probe_src(root: Path, *, extra_keys: tuple[str, ...] = ()) -> Path:
    src = root / "src"
    src.mkdir()
    body = 'import os\n\n\ndef probe():\n    value = os.environ.get("LFL_DEMO_KEY", "")\n'
    for key in extra_keys:
        body += f'    value += os.environ.get("{key}", "")\n'
    body += "    return value\n"
    (src / "demo.py").write_text(body, encoding="utf-8")
    return src


def test_describe_registration_marks_relaxation_direction():
    current = {"access_count": 5, "signature_counts": {"a.py|f|read|K": 2}}
    baseline = {"access_count": 3, "signature_counts": {"a.py|f|read|K": 1}}
    report = describe_registration(current, baseline)
    assert report["cap_changes"]["access_count"] == {"from": 3, "to": 5, "delta": 2}
    assert report["added_signatures"] == {"a.py|f|read|K": 1}
    assert report["relaxations"] is True

    tightening = describe_registration(
        {"access_count": 1}, {"access_count": 3, "signature_counts": {"x.py|f|read|K": 1}}
    )
    assert tightening["relaxations"] is False
    assert tightening["removed_signatures"] == {"x.py|f|read|K": 1}


def test_update_baseline_refuses_relaxation_without_reason(tmp_path):
    src = _write_probe_src(tmp_path, extra_keys=("LFL_DEMO_SECOND",))
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({}), encoding="utf-8")

    code = main(["--src", str(src), "--baseline", str(baseline_path), "--update-baseline"])

    assert code == 2
    # 拒绝时绝不落盘: 半登记的基线比不登记更危险
    assert json.loads(baseline_path.read_text(encoding="utf-8")) == {}


def test_update_baseline_records_reason_and_becomes_clean(tmp_path):
    src = _write_probe_src(tmp_path, extra_keys=("LFL_DEMO_SECOND",))
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({"baseline_context": {"phase": "unit"}}), encoding="utf-8")

    code = main(
        [
            "--src", str(src),
            "--baseline", str(baseline_path),
            "--update-baseline",
            "--reason", "演示用探针",
            "--parent-commit", "abc1234",
        ]
    )

    assert code == 0
    saved = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert saved["baseline_context"] == {"phase": "unit"}  # 历史证据不被登记覆盖
    assert "LFL_DEMO_SECOND" in saved["keys"]
    entry = saved["registration_log"][0]
    assert entry["reason"] == "演示用探针"
    assert entry["parent_commit"] == "abc1234"
    assert entry["relaxations"] is True

    # 登记后同一代码再登记 = 零差异，且不再需要理由
    assert main(["--src", str(src), "--baseline", str(baseline_path), "--update-baseline"]) == 0
    again = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert len(again["registration_log"]) == 2
    assert again["registration_log"][1]["relaxations"] is False


def test_update_baseline_allows_tightening_without_reason(tmp_path):
    src = _write_probe_src(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({}), encoding="utf-8")
    assert main(
        ["--src", str(src), "--baseline", str(baseline_path), "--update-baseline", "--reason", "首登记"]
    ) == 0

    tight_src = tmp_path / "tight" / "src"
    tight_src.mkdir(parents=True)
    (tight_src / "demo.py").write_text("def probe():\n    return ''\n", encoding="utf-8")

    # 只减不增 = 还债，不需要理由
    assert main(["--src", str(tight_src), "--baseline", str(baseline_path), "--update-baseline"]) == 0
    saved = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert saved["access_count"] == 0
    assert saved["registration_log"][-1]["relaxations"] is False


def test_update_baseline_dry_run_never_writes(tmp_path):
    src = _write_probe_src(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({}), encoding="utf-8")

    code = main(
        ["--src", str(src), "--baseline", str(baseline_path), "--update-baseline", "--reason", "x", "--dry-run"]
    )

    assert code == 0
    assert json.loads(baseline_path.read_text(encoding="utf-8")) == {}

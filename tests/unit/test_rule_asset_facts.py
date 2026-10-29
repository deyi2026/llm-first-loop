"""规则资产事实与版本归一（评审 §3.4 任务 3/4：doctor/自检共用单一事实函数）。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from llm_loop.runtime import installation


def _make_bundle(tmp_path: Path, *, lite: str | None,
                 body: str = "## RULE-AI-24 当前任务与授权来源\n\n正文\n",
                 manifest_files: dict | None = None) -> Path:
    bundle = tmp_path / "_bundled"
    (bundle / "docs").mkdir(parents=True)
    (bundle / "docs" / "ai_rules.md").write_text(body, encoding="utf-8")
    if lite is not None:
        (bundle / "docs" / "ai_rules.lite.md").write_text(lite, encoding="utf-8")
    if manifest_files is not None:
        (bundle / "manifest.json").write_text(
            json.dumps({"files": manifest_files}), encoding="utf-8")
    return bundle


def test_rules_version_normalizes_leading_zeros(monkeypatch, tmp_path):
    """"020" 归一为 "20"：严格相等比较不再受前导零写法影响（§3.4 任务 4）。"""
    bundle = _make_bundle(tmp_path, lite="---\nversion=020\n")
    monkeypatch.setattr(installation, "bundle_root", lambda: bundle)
    assert installation.rules_version() == "20"
    assert installation.rules_version() == installation.rules_version()


def test_rule_asset_facts_wheel_manifest_match_disclosed(monkeypatch, tmp_path):
    """P2-2（安全审查 2026-10-29）：manifest 声明值与实体计算值一致 → 独立披露、无错."""
    body = "## RULE-AI-24 当前任务与授权来源\n\n正文\n"
    trusted = hashlib.sha256(body.encode("utf-8")).hexdigest()
    bundle = _make_bundle(tmp_path, lite="version=20\n", body=body,
                          manifest_files={"docs/ai_rules.md": trusted})
    monkeypatch.setattr(installation, "bundle_root", lambda: bundle)
    assert installation.rule_asset_facts() == {
        "source_kind": "wheel",
        "rule_body_ref": "wheel:docs/ai_rules.md",
        "rule_body_retrievable": True,
        "rules_version": "20",
        "rule_body_sha256": trusted,
        "rule_body_sha256_manifest": trusted,
        "error_code": None,
    }


def test_rule_asset_facts_wheel_manifest_mismatch_flags_tamper(monkeypatch, tmp_path):
    """P2-2（安全审查 2026-10-29）：manifest 声明值不再覆盖计算值——不一致 →
    rule_body_sha256 保持实体计算值 + error_code=asset_hash_mismatch（掩盖篡改面关闭）."""
    body = "## RULE-AI-24 当前任务与授权来源\n\n正文\n"
    trusted = "f" * 64  # 与实体哈希不一致（篡改/打包损坏形态）
    bundle = _make_bundle(tmp_path, lite="version=20\n", body=body,
                          manifest_files={"docs/ai_rules.md": trusted})
    monkeypatch.setattr(installation, "bundle_root", lambda: bundle)
    facts = installation.rule_asset_facts()
    assert facts["rule_body_sha256"] == hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert facts["rule_body_sha256_manifest"] == trusted
    assert facts["error_code"] == "asset_hash_mismatch"


def test_rule_asset_facts_missing_lite_keeps_body_retrievable(monkeypatch, tmp_path):
    bundle = _make_bundle(tmp_path, lite=None)
    monkeypatch.setattr(installation, "bundle_root", lambda: bundle)
    facts = installation.rule_asset_facts()
    assert facts["rule_body_retrievable"] is True
    assert facts["rules_version"] == ""
    assert facts["error_code"] == "asset_missing"


def test_rule_asset_facts_unparseable_lite_reports_version_parse_error(monkeypatch, tmp_path):
    bundle = _make_bundle(tmp_path, lite="no version line\n")
    monkeypatch.setattr(installation, "bundle_root", lambda: bundle)
    facts = installation.rule_asset_facts()
    assert facts["rule_body_retrievable"] is True
    assert facts["error_code"] == "version_parse_error"


def test_rule_asset_facts_missing_body_is_asset_missing(monkeypatch, tmp_path):
    bundle = tmp_path / "_bundled"
    (bundle / "docs").mkdir(parents=True)
    (bundle / "docs" / "ai_rules.lite.md").write_text("version=20\n", encoding="utf-8")
    monkeypatch.setattr(installation, "bundle_root", lambda: bundle)
    facts = installation.rule_asset_facts()
    assert facts["rule_body_retrievable"] is False
    assert facts["error_code"] == "asset_missing"


def test_rule_asset_facts_source_mode_matches_repo_docs(monkeypatch):
    monkeypatch.setattr(installation, "bundle_root", lambda: None)
    facts = installation.rule_asset_facts()
    repo_body = Path(__file__).resolve().parents[2] / "docs" / "ai_rules.md"
    assert facts["source_kind"] == "source"
    assert facts["rule_body_ref"] == "source:docs/ai_rules.md"
    assert facts["rule_body_retrievable"] is True
    assert facts["rule_body_sha256"] == hashlib.sha256(repo_body.read_bytes()).hexdigest()
    assert facts["rules_version"] == installation.rules_version()
    assert facts["error_code"] is None

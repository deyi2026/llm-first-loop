"""规则版本信号在两种安装布局下解析一致（wheel 随包 / 源码检出）。"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from llm_loop.runtime import installation

ROOT = Path(__file__).resolve().parents[2]
LITE = ROOT / "docs" / "ai_rules.lite.md"


def _header_version(path: Path) -> str:
    match = re.search(r"version\s*=\s*(\d+)", path.read_text(encoding="utf-8")[:512])
    assert match, f"缺少 version= 头：{path}"
    return match.group(1)


def _fake_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "_bundled"
    (bundle / "docs").mkdir(parents=True)
    shutil.copyfile(LITE, bundle / "docs" / "ai_rules.lite.md")
    return bundle


def test_source_checkout_resolves_version():
    """源码检出：仓库根 docs/ai_rules.lite.md 解析出版本。"""
    assert installation.rules_version() == _header_version(LITE)


def test_bundled_layout_resolves_version(monkeypatch, tmp_path):
    """wheel 安装：_bundled/docs/ai_rules.lite.md 解析出同一版本。"""
    bundle = _fake_bundle(tmp_path)
    monkeypatch.setattr(installation, "bundle_root", lambda: bundle)
    assert installation.rules_version() == _header_version(LITE)


def test_readers_share_one_resolution(monkeypatch, tmp_path):
    """两个读取点与规则索引同源：同一布局下结论必须一致。"""
    from llm_loop.introspection import status
    from llm_loop.runtime import causality

    assert status._rules_version() == installation.rules_version()
    assert causality._rules_version() == installation.rules_version()

    bundle = _fake_bundle(tmp_path)
    monkeypatch.setattr(installation, "bundle_root", lambda: bundle)
    expected = _header_version(LITE)
    assert installation.rules_version() == expected
    assert status._rules_version() == expected
    assert causality._rules_version() == expected


def test_wheel_payload_ships_lite_rule_file():
    """随包清单必须含 ai_rules.lite.md，否则 wheel 安装读不到版本信号。"""
    setup_py = (ROOT / "setup.py").read_text(encoding="utf-8")
    assert '"ai_rules.lite.md"' in setup_py
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "include docs/ai_rules.lite.md" in manifest

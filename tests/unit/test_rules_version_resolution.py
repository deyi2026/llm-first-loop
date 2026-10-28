"""规则版本信号在两种安装布局下解析一致（wheel 随包 / 源码检出）。"""

from __future__ import annotations

import re
import shutil
import sys
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


def _fake_wheel_module(prefix: Path) -> Path:
    """伪造 venv 内的模块路径：<prefix>/lib/python3.11/site-packages/llm_loop/..."""
    return (
        prefix / "lib" / "python3.11" / "site-packages" / "llm_loop" / "runtime" / "installation.py"
    )


def test_no_fallback_to_sys_prefix_docs(monkeypatch, tmp_path):
    """负向（0.6.37 旁路收敛）：sys.prefix/docs 上的同名 lite 永不被读取。"""
    fake_venv = tmp_path / "fake-venv"
    decoy = fake_venv / "docs" / "ai_rules.lite.md"
    decoy.parent.mkdir(parents=True)
    decoy.write_text("---\nversion=999\n", encoding="utf-8")
    monkeypatch.setattr(installation, "bundle_root", lambda: None)
    monkeypatch.setattr(installation, "__file__", str(_fake_wheel_module(fake_venv)))
    monkeypatch.setattr(sys, "prefix", str(fake_venv))
    assert decoy not in installation.rules_doc_candidates("ai_rules.lite.md")
    assert installation.rules_version() == ""


def test_no_fallback_to_site_packages_docs(monkeypatch, tmp_path):
    """负向（0.6.37 旁路收敛）：site-packages/docs 上的同名 lite 永不被读取。"""
    fake_venv = tmp_path / "fake-venv"
    site_packages = fake_venv / "lib" / "python3.11" / "site-packages"
    decoy = site_packages / "docs" / "ai_rules.lite.md"
    decoy.parent.mkdir(parents=True)
    decoy.write_text("---\nversion=888\n", encoding="utf-8")
    monkeypatch.setattr(installation, "bundle_root", lambda: None)
    monkeypatch.setattr(installation, "__file__", str(_fake_wheel_module(fake_venv)))
    assert decoy not in installation.rules_doc_candidates("ai_rules.lite.md")
    assert installation.rules_version() == ""


def test_wheel_mode_does_not_cross_probe_source_root(monkeypatch, tmp_path):
    """负向：wheel 模式只认 bundle 根，bundle 文档缺失时不跨根兜底。"""
    fake_venv = tmp_path / "fake-venv"
    module_file = _fake_wheel_module(fake_venv)
    source_root = module_file.parents[3]
    (source_root / "docs").mkdir(parents=True)
    (source_root / "docs" / "ai_rules.lite.md").write_text("---\nversion=777\n", encoding="utf-8")
    bundle = tmp_path / "_bundled"
    bundle.mkdir()
    monkeypatch.setattr(installation, "bundle_root", lambda: bundle)
    monkeypatch.setattr(installation, "__file__", str(module_file))
    assert installation.rules_doc_candidates("ai_rules.lite.md") == (
        bundle / "docs" / "ai_rules.lite.md",
    )
    assert installation.rules_version() == ""

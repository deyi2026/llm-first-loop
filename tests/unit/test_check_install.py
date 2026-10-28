"""check_install 的 lite 版本门控：新版强制、pre-fix 存留版本降级 warn 不阻断。

Linux 0.6.37 wheel 事故收敛项（评审 §3.4 任务 2）：install_linux.sh 在
升级(:582)/回滚(:540)前用各 release 自身 venv 的 `lfl check-install` 做硬门；
required 无条件含 lite 会把从/到 pre-fix 存留版本的升级与回滚全部砖化。
0.6.37 存在 pre-fix 与修复版两种同号 wheel，同号区分只能靠 manifest 是否
显式列出 lite 条目；版本阈值只对更高发布号生效。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import llm_loop.cli as cli

LITE_NAME = "docs/ai_rules.lite.md"
LITE_TEXT = "# docs/ai_rules.lite.md\nversion=20\n"


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fake_bundle(tmp_path: Path, manifest_version: str, *,
                 lite_entry: bool = False, lite_file: bool = False) -> Path:
    root = tmp_path / "_bundled"
    (root / "docs").mkdir(parents=True)
    (root / "webui" / "dist").mkdir(parents=True)
    (root / "docs" / "ai_rules.md").write_text("# rules\n", encoding="utf-8")
    (root / "webui" / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
    files = {
        "docs/ai_rules.md": _sha_bytes((root / "docs" / "ai_rules.md").read_bytes()),
        "webui/dist/index.html": _sha_bytes((root / "webui" / "dist" / "index.html").read_bytes()),
    }
    if lite_file:
        (root / "docs" / "ai_rules.lite.md").write_text(LITE_TEXT, encoding="utf-8")
    if lite_entry:
        digest = (_sha_bytes((root / "docs" / "ai_rules.lite.md").read_bytes())
                  if lite_file else _sha_bytes(b"expected-but-absent-lite"))
        files[LITE_NAME] = digest
    manifest = {"schema": "lfl.application-bundle/v1", "version": manifest_version, "files": files}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _check(monkeypatch, root: Path, dist_version: str) -> dict:
    monkeypatch.setattr(cli, "bundle_root", lambda: root)
    monkeypatch.setattr(cli, "version", lambda name: dist_version)
    return cli.check_install()


def test_pre_fix_release_is_not_blocked_but_warns(monkeypatch, tmp_path):
    """验收 1：pre-fix 存留 release（manifest 无 lite）不被硬门阻断，降级 warn。"""
    root = _fake_bundle(tmp_path, "0.6.36", lite_entry=False, lite_file=False)
    report = _check(monkeypatch, root, "0.6.36")
    assert report["ok"] is True
    assert any(LITE_NAME in warning for warning in report.get("warnings", []))


def test_incident_pre_fix_wheel_same_version_is_not_blocked(monkeypatch, tmp_path):
    """砖化防线：事故形态（0.6.37 无 lite 条目）不得 fail，否则 :582 无法升级逃离。"""
    root = _fake_bundle(tmp_path, "0.6.37", lite_entry=False, lite_file=False)
    report = _check(monkeypatch, root, "0.6.37")
    assert report["ok"] is True
    assert report.get("warnings")


def test_future_release_without_lite_manifest_entry_fails(monkeypatch, tmp_path):
    """验收 2（打包回归防线）：version ≥ 门控下限的 manifest 未列 lite 必须 fail。"""
    from llm_loop.runtime.installation import LITE_RULES_MIN_VERSION

    root = _fake_bundle(tmp_path, "0.6.39", lite_entry=False, lite_file=False)
    report = _check(monkeypatch, root, "0.6.39")
    assert report["ok"] is False
    assert LITE_RULES_MIN_VERSION < "0.6.39"  # 保证用例版本确实高于门控下限


def test_manifest_lists_lite_but_file_missing_fails(monkeypatch, tmp_path):
    """验收 2：manifest 列了 lite 但文件缺失 → ok=false。"""
    root = _fake_bundle(tmp_path, "0.6.38", lite_entry=True, lite_file=False)
    report = _check(monkeypatch, root, "0.6.38")
    assert report["ok"] is False


def test_manifest_lists_lite_with_corrupt_file_fails(monkeypatch, tmp_path):
    """验收 2：lite 在位但内容与 manifest 摘要不符 → ok=false 且点名 failed_files。"""
    root = _fake_bundle(tmp_path, "0.6.38", lite_entry=True, lite_file=True)
    (root / "docs" / "ai_rules.lite.md").write_text("tampered", encoding="utf-8")
    report = _check(monkeypatch, root, "0.6.38")
    assert report["ok"] is False
    assert LITE_NAME in report.get("failed_files", [])


def test_fixed_wheel_with_lite_passes_silently(monkeypatch, tmp_path):
    """修复版 wheel（manifest 含 lite、文件在位）ok=true 且无 lite 相关告警。"""
    root = _fake_bundle(tmp_path, "0.6.37", lite_entry=True, lite_file=True)
    report = _check(monkeypatch, root, "0.6.37")
    assert report["ok"] is True
    assert not report.get("warnings")


def test_version_at_least_semantics():
    from llm_loop.runtime.installation import LITE_RULES_MIN_VERSION, version_at_least

    assert version_at_least("0.6.38", LITE_RULES_MIN_VERSION) is True
    assert version_at_least("0.6.40", LITE_RULES_MIN_VERSION) is True
    assert version_at_least("0.7.0", LITE_RULES_MIN_VERSION) is True
    assert version_at_least("0.6.37", LITE_RULES_MIN_VERSION) is False
    assert version_at_least("0.6.37.1", LITE_RULES_MIN_VERSION) is False  # 0.6.37 补丁按 pre-fix 对待
    assert version_at_least("not-a-version", LITE_RULES_MIN_VERSION) is False
    assert version_at_least("", LITE_RULES_MIN_VERSION) is False

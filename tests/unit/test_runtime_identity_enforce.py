"""enforce_identity / write_runtime_manifest 重写回归（2026-08-30 半改丢失 API 恢复）.

覆盖：CWD 锚定核验（通过/不一致 shadow/不一致 enforce 抛错）+ manifest 便捷版
落盘往返 + fail-open 语义。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from llm_loop.runtime.identity import RuntimeIdentityError, enforce_identity
from llm_loop.runtime.manifest import write_runtime_manifest

MIRROR_ROOT = Path(__file__).resolve().parents[2]


def test_enforce_identity_match_ok(monkeypatch):
    """模块归属与 CWD 锚定均一致 → ok=True 原样返回（无失败 detail）."""
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(MIRROR_ROOT))
    monkeypatch.setenv("RUNTIME_IDENTITY_MODE", "shadow")
    r = enforce_identity(MIRROR_ROOT)
    assert r.ok is True
    assert "cwd_match" not in r.detail


def test_enforce_identity_cwd_mismatch_shadow(monkeypatch, capsys, tmp_path):
    """CWD 锚定不一致（shadow）→ ok=False 不抛，stderr 告警含 FATAL_TAG."""
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(MIRROR_ROOT))
    monkeypatch.setenv("RUNTIME_IDENTITY_MODE", "shadow")
    r = enforce_identity(tmp_path)
    assert r.ok is False
    assert r.detail.get("cwd_match") is False
    assert r.detail.get("expected_workspace") == str(tmp_path.resolve())
    err = capsys.readouterr().err
    assert "FATAL_RUNTIME_IDENTITY_MISMATCH" in err


def test_enforce_identity_mismatch_enforce_raises(monkeypatch, tmp_path):
    """enforce 模式违规 → RuntimeIdentityError（report 附带）."""
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(MIRROR_ROOT))
    monkeypatch.setenv("RUNTIME_IDENTITY_MODE", "enforce")
    with pytest.raises(RuntimeIdentityError):
        enforce_identity(tmp_path)


def test_write_runtime_manifest_roundtrip(tmp_path):
    """便捷版落盘 → 文件存在且内容含 service 名."""
    p = write_runtime_manifest("unit-test", data_dir=tmp_path)
    assert p is not None and Path(p).exists()
    assert "unit-test" in Path(p).read_text()


def test_write_runtime_manifest_fail_open(monkeypatch, tmp_path):
    """内部异常 → None 不抛（R3 fail-open 语义）."""
    import llm_loop.runtime.resolver as resolver_mod

    def _boom(*a, **k):
        raise RuntimeError("simulated")

    monkeypatch.setattr(resolver_mod, "resolve_effective", _boom)
    assert write_runtime_manifest("unit-test", data_dir=tmp_path) is None

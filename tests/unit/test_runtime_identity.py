"""R1 Workspace Identity Guard 测试（RUNTIME-SOT-WIRE）。

覆盖 design §5.3 矩阵前 5 行的 identity 部分：
  main venv import → main；mirror venv import → mirror；
  带错误 PYTHONPATH → 检出违规；enforce 模式违规拒绝启动。
"""

import sys
from pathlib import Path

import pytest

from llm_loop.runtime.identity import (
    FATAL_TAG,
    RuntimeIdentityError,
    check_identity,
    compute_identity,
)

HERE_ROOT = Path(__file__).resolve().parents[2]  # 当前测试所在仓库根（动态推导）
OTHER_ROOT = HERE_ROOT.parent / (
    "llm-first-loop" if HERE_ROOT.name == "llm-first-loop-mirror" else "llm-first-loop-mirror"
)
# 对称化（2026-08-29）: 主区版在镜像跑时 MAIN/MIRROR 坍缩为同一路径，跨区检测恒
# ok=True；改为 HERE（当前区=预期 workspace）/ OTHER（对侧区=被检模块）两区通用。


def test_identity_ok_in_main_workspace(monkeypatch, tmp_path):
    """主区 venv + cwd 在主区 → ok=True（矩阵第 1 行）。"""
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(HERE_ROOT))
    monkeypatch.delenv("PYTHONPATH", raising=False)
    report = compute_identity()
    assert report.ok is True
    assert report.llm_loop_module.startswith(str(HERE_ROOT / "src"))


def test_identity_detects_cross_workspace_module(monkeypatch):
    """实际加载模块在对侧区、预期 workspace 是当前区 → ok=False（矩阵第 4/5 行等价语义）。"""
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(HERE_ROOT))
    import llm_loop.runtime.identity as ident

    class FakeModule:
        __file__ = str(OTHER_ROOT / "src" / "llm_loop" / "__init__.py")

    monkeypatch.setattr(ident, "_find_workspace_root", lambda: HERE_ROOT)
    monkeypatch.setitem(sys.modules, "llm_loop", FakeModule())
    # compute_identity 内部 import llm_loop → 被 fake 替换
    report = compute_identity()
    assert report.ok is False
    assert report.detail["expected_src"] == str(HERE_ROOT / "src")


def test_enforce_mode_raises_on_violation(monkeypatch):
    """enforce + 违规 → RuntimeIdentityError（FATAL_RUNTIME_IDENTITY_MISMATCH）。"""
    monkeypatch.setenv("RUNTIME_IDENTITY_MODE", "enforce")

    class FakeModule:
        __file__ = "/definitely/not/in/workspace/src/llm_loop/__init__.py"

    import llm_loop.runtime.identity as ident

    monkeypatch.setattr(ident, "_find_workspace_root", lambda: HERE_ROOT)
    monkeypatch.setitem(sys.modules, "llm_loop", FakeModule())
    with pytest.raises(RuntimeIdentityError) as ei:
        check_identity()
    assert FATAL_TAG in str(ei.value)
    assert "refusing to start" in str(ei.value)


def test_shadow_mode_does_not_raise_on_violation(monkeypatch, capsys):
    """shadow + 违规 → 只告警不阻断（观察期语义）。"""
    monkeypatch.setenv("RUNTIME_IDENTITY_MODE", "shadow")

    class FakeModule:
        __file__ = "/definitely/not/in/workspace/src/llm_loop/__init__.py"

    import llm_loop.runtime.identity as ident

    monkeypatch.setattr(ident, "_find_workspace_root", lambda: HERE_ROOT)
    monkeypatch.setitem(sys.modules, "llm_loop", FakeModule())
    report = check_identity()
    assert report.ok is False
    assert report.mode == "shadow"
    err = capsys.readouterr().err
    assert FATAL_TAG in err


def test_report_fields_complete(monkeypatch):
    """report 机械字段齐全（R3 manifest 的数据源）。"""
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(HERE_ROOT))
    r = compute_identity()
    for f in (
        "workspace_root",
        "git_head",
        "python_executable",
        "venv_root",
        "llm_loop_module",
        "data_dir",
        "config_file",
        "providers_file",
        "mode",
        "ok",
    ):
        assert hasattr(r, f)
    assert r.git_head  # 非空（unknown 或真实 hash）
    assert r.python_executable.endswith("python") or "python" in r.python_executable


def test_invalid_mode_falls_back_to_shadow(monkeypatch):
    monkeypatch.setenv("RUNTIME_IDENTITY_MODE", "bogus-mode")
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(HERE_ROOT))
    assert compute_identity().mode == "shadow"

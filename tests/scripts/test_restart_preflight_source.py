"""T0-A3: restart_mirror.sh CODE_ROOT 来源判定（环境残留防误用）+ PREFLIGHT_ONLY.

复现 2026-09-16 17:22 事故: 会话环境残留 LFL_RESTART_CODE_ROOT 指向旧 worktree，
自动化通道（FORCE=1 / 非交互）必须直接 abort，除非显式 CONFIRMED=1。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "restart_mirror.sh"
_SCRIPT_DIR = _SCRIPT.parent.resolve()
RESIDUE_MARKER = "[A3-RESIDUE]"  # R4 参数化后的稳定残留标记（含两个根变量）


def _run(extra_env: dict[str, str], timeout: int = 60) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("LFL_RESTART")}
    env.update(extra_env)
    return subprocess.run(
        ["bash", str(_SCRIPT), "preflight"],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_bash_syntax_still_clean():
    r = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_static_source_check_and_preflight_mode_present():
    src = _SCRIPT.read_text(encoding="utf-8")
    assert "_code_root_source_check" in src
    assert "_runtime_root_source_check" in src  # R4: RUNTIME_ROOT 同判
    assert "LFL_RESTART_CODE_ROOT_CONFIRMED" in src
    assert "LFL_RESTART_RUNTIME_ROOT_CONFIRMED" in src
    assert RESIDUE_MARKER in src
    assert "preflight)" in src  # PREFLIGHT_ONLY 分支存在
    # 嵌套禁令进入 dual-root 校验
    assert "嵌套" in src


def test_automation_residual_env_aborts(tmp_path: Path):
    r = _run({
        "LFL_RESTART_RUNTIME_ROOT": str(_SCRIPT_DIR),
        "LFL_RESTART_CODE_ROOT": str(tmp_path),  # 残留值 ≠ 脚本目录
        "RESTART_PREFLIGHT_ONLY": "1",
    })
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert RESIDUE_MARKER in out
    assert "CONFIRMED" in out


def test_residual_env_with_explicit_confirmed_passes_source_check(tmp_path: Path):
    r = _run({
        # R4: RUNTIME_ROOT 指向脚本仓根（== SCRIPT_ROOT）→ 默认来源路径
        "LFL_RESTART_RUNTIME_ROOT": str(_SCRIPT.parents[1]),
        "LFL_RESTART_CODE_ROOT": str(tmp_path),
        "LFL_RESTART_CODE_ROOT_CONFIRMED": "1",
        "RESTART_PREFLIGHT_ONLY": "1",
    })
    out = r.stdout + r.stderr
    # 来源判定必须放行（无残留标记）；后续校验可能因 tmp_path 非 worktree 失败，属预期
    assert RESIDUE_MARKER not in out or "显式确认" in out
    assert "拒绝重启" not in out


def test_script_dir_default_no_prompt():
    r = _run({"LFL_RESTART_RUNTIME_ROOT": str(_SCRIPT.parents[1]), "RESTART_PREFLIGHT_ONLY": "1"})
    out = r.stdout + r.stderr
    # 脚本目录默认来源: 不触发残留路径; 通过或因本地 dirty 停在校验（非来源判定）
    assert "拒绝重启" not in out
    assert r.returncode in (0, 1, 2)


def test_automation_residual_runtime_root_aborts(tmp_path: Path):
    """R4: ambient LFL_RESTART_RUNTIME_ROOT 残留（≠脚本目录）同样必须 abort."""
    residual = tmp_path / "residual-runtime"
    residual.mkdir()  # _resolve_root 要求目录存在，残留路径死于来源判定而非解析
    r = _run({
        "LFL_RESTART_RUNTIME_ROOT": str(residual),
        "RESTART_PREFLIGHT_ONLY": "1",
    })
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "LFL_RESTART_RUNTIME_ROOT" in out
    assert "拒绝重启" in out
    # MIRROR_DIR=RUNTIME_ROOT → audit 落在残留根下的 data/audit（不污染真实仓）
    audit = residual / "data" / "audit" / "restart_preflight.log"
    assert audit.is_file()
    last = audit.read_text(encoding="utf-8").strip().splitlines()[-1]
    assert "var=LFL_RESTART_RUNTIME_ROOT" in last


def test_runtime_root_confirmed_passes_source_check(tmp_path: Path):
    """R4: RUNTIME_ROOT 残留 + CONFIRMED=1 → 显式确认放行（受控路径语义）."""
    residual = tmp_path / "residual-runtime"
    residual.mkdir()
    r = _run({
        "LFL_RESTART_RUNTIME_ROOT": str(residual),
        "LFL_RESTART_RUNTIME_ROOT_CONFIRMED": "1",
        "RESTART_PREFLIGHT_ONLY": "1",
    })
    out = r.stdout + r.stderr
    assert "显式确认" in out
    assert "拒绝重启" not in out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

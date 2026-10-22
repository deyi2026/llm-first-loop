"""ci_gate.sh 结论行必须如实反映 pyright 状态（D6 收尾，2026-10-22）。

背景：check_static_diagnostics.py 在分析器墙钟超限时以 advisory 放行（exit 0），
本轮没有类型诊断数据，只落机器可读态 status=unknown。放行语义保留（环境性超时
不该把开发侧 push 门禁变成永久红），但 wrapper 的收尾行不得再声称「pyright 已
通过」。本用例在临时根目录用桩 python/npm 跑**真实** scripts/ci_gate.sh，锁定两条
分支的呈现差异：unknown ⇒ 不得出现「✅ 全链路通过」；complete ⇒ 保持原文案。
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = REPO_ROOT / "scripts" / "ci_gate.sh"

_FAKE_PYTHON = """#!/bin/sh
case "$*" in
  *"-c"*) echo /tmp; exit 0 ;;
  *"--tool pyright"*) printf '%s\\n' "$FAKE_PYRIGHT_OUTPUT"; exit 0 ;;
esac
exit 0
"""

_FAKE_NPM = """#!/bin/sh
mkdir -p dist && : > dist/index.html
"""


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_gate(tmp_path: Path, pyright_output: str) -> subprocess.CompletedProcess[str]:
    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(GATE_SCRIPT, root / "scripts" / "ci_gate.sh")

    fake_python = root / ".venv" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text(_FAKE_PYTHON, encoding="utf-8")
    _make_executable(fake_python)

    (root / "webui" / "node_modules").mkdir(parents=True)
    fake_npm = root / "stub-bin" / "npm"
    fake_npm.parent.mkdir(parents=True)
    fake_npm.write_text(_FAKE_NPM, encoding="utf-8")
    _make_executable(fake_npm)

    env = dict(os.environ)
    env["PY"] = str(fake_python)
    env["FAKE_PYRIGHT_OUTPUT"] = pyright_output
    env["PATH"] = f"{fake_npm.parent}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        ["bash", "scripts/ci_gate.sh"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def test_unknown_pyright_does_not_claim_full_pass(tmp_path: Path) -> None:
    result = _run_gate(tmp_path, "R9 pyright status=unknown reason=wallclock_advisory timeout_s=600")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "pyright=UNKNOWN" in result.stdout
    assert "✅ ci_gate 全链路通过" not in result.stdout


def test_complete_pyright_keeps_full_pass_line(tmp_path: Path) -> None:
    result = _run_gate(tmp_path, "R9 pyright status=complete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "✅ ci_gate 全链路通过" in result.stdout
    assert "pyright=UNKNOWN" not in result.stdout

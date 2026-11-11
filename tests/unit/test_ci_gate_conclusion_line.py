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
  *"pytest"*)
    if [ -n "${CAPTURE_HOME_FILE:-}" ]; then printf '%s' "$HOME" > "$CAPTURE_HOME_FILE"; fi ;;
esac
exit 0
"""

_FAKE_NPM = """#!/bin/sh
mkdir -p dist && : > dist/index.html
"""

# 抖动通道桩（2026-11-11 P1-1）：第一次并行全量返回红，serial 单点与并行复跑均绿。
# 桩用 $0 同目录的计数文件判次，不依赖外部状态目录。
_FAKE_PYTHON_FLAKY = """#!/bin/sh
_STATE="$(dirname "$0")/.fake-state"
mkdir -p "$_STATE"
case "$*" in
  *"--tool pyright"*) printf '%s\\n' "$FAKE_PYRIGHT_OUTPUT"; exit 0 ;;
  *"-m pytest"*)
    case "$*" in
      *"--dist loadfile"*)
        _N=$(cat "$_STATE/parallel_calls" 2>/dev/null || echo 0)
        _N=$((_N + 1))
        echo "$_N" > "$_STATE/parallel_calls"
        if [ "$_N" -eq 1 ]; then
          echo "FAILED tests/unit/test_flaky_sample.py::test_under_load - assert 1 == 2"
          echo "1 failed, 42 passed in 9.9s"
          exit 1
        fi
        exit 0
        ;;
    esac
    exit 0
    ;;
  *"-c"*) echo "$HOME"; exit 0 ;;
esac
exit 0
"""


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_gate(
    tmp_path: Path,
    pyright_output: str,
    *,
    python_script: str = _FAKE_PYTHON,
    symlink_cwd: bool = False,
    capture_home_file: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(GATE_SCRIPT, root / "scripts" / "ci_gate.sh")

    fake_python = root / ".venv" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text(python_script, encoding="utf-8")
    _make_executable(fake_python)

    fake_pytest = fake_python.with_name("pytest")
    fake_pytest.write_text("#!/bin/sh\necho 'chosen venv pytest'\n", encoding="utf-8")
    _make_executable(fake_pytest)

    (root / "webui" / "node_modules").mkdir(parents=True)
    fake_npm = root / "stub-bin" / "npm"
    fake_npm.parent.mkdir(parents=True)
    fake_npm.write_text(_FAKE_NPM, encoding="utf-8")
    _make_executable(fake_npm)

    env = dict(os.environ)
    env["PY"] = str(fake_python)
    env["FAKE_PYRIGHT_OUTPUT"] = pyright_output
    env["PATH"] = f"{fake_npm.parent}{os.pathsep}{env.get('PATH', '')}"
    if capture_home_file is not None:
        env["CAPTURE_HOME_FILE"] = str(capture_home_file)
    run_root = root
    if symlink_cwd:
        run_root = tmp_path / "root-link"
        run_root.symlink_to(root, target_is_directory=True)
        env["PWD"] = str(run_root)
    return subprocess.run(
        ["bash", "scripts/ci_gate.sh"],
        cwd=run_root,
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


def test_missing_test_dependency_stops_before_long_analysis(tmp_path: Path) -> None:
    result = _run_gate(tmp_path, "", python_script="#!/bin/sh\nexit 1\n")
    assert result.returncode != 0
    assert "CI test dependencies unavailable" in result.stderr
    assert "Ruff 全树" not in result.stdout


def test_gate_exposes_selected_venv_tools_to_child_commands(tmp_path: Path) -> None:
    python_script = _FAKE_PYTHON.replace("esac\nexit 0", """esac
case "$*" in
  *"-m pytest"*)
    [ "$(command -v pytest)" = "$(dirname "$0")/pytest" ] || exit 37
    pytest --version ;;
esac
exit 0""")
    result = _run_gate(tmp_path, "R9 pyright status=complete", python_script=python_script)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "chosen venv pytest" in result.stdout


def test_ci_home_is_physical_when_checkout_uses_symlink(tmp_path: Path) -> None:
    captured_home = tmp_path / "captured-home.txt"
    result = _run_gate(
        tmp_path,
        "R9 pyright status=complete",
        symlink_cwd=True,
        capture_home_file=captured_home,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert captured_home.read_text(encoding="utf-8") == str(
        (tmp_path / "root" / "data" / ".ci-test-home").resolve()
    )


def test_flaky_xdist_pass_is_not_reported_as_clean_pass(tmp_path: Path) -> None:
    """抖动放行必须与零失败绿在输出上可区分（P1-1，2026-11-11）。

    RULE-AI-35 的「应拦输入」在此表现为「应可区分输入」：修复前真实 ci_gate.sh 在
    抖动路径上打印一行 ⚠️ 后继续走无条件 ✅，抖动绿与干净绿对外不可分辨，下游引用
    「CI 绿」作发布/合并资格时会把一次真实首轮红当成零失败证据。
    """
    result = _run_gate(tmp_path, "R9 pyright status=complete", python_script=_FAKE_PYTHON_FLAKY)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "分布抖动" in result.stdout
    assert "FLAKY-PASS" in result.stdout
    assert "✅ ci_gate 全链路通过" not in result.stdout
    assert "test_flaky_sample.py" in result.stdout
    assert "并行首轮 1 文件红" in result.stdout  # $n_files 真被取到，不是空串
    # 「落盘」必须可核验，不能只验回显：取回清单路径并核对内容。
    marker = "首轮红清单落盘："
    manifest_line = next(ln for ln in result.stdout.splitlines() if marker in ln)
    manifest = Path(manifest_line.split(marker, 1)[1].strip())
    assert manifest.is_file(), manifest_line
    assert "test_flaky_sample.py" in manifest.read_text(encoding="utf-8")


def test_clean_run_never_claims_flaky(tmp_path: Path) -> None:
    result = _run_gate(tmp_path, "R9 pyright status=complete")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FLAKY-PASS" not in result.stdout
    assert "✅ ci_gate 全链路通过" in result.stdout

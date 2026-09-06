"""execute_command workdir/environment factual behavior tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from llm_loop.tools.builtin.execute_command import ExecuteCommandTool


def _tool() -> ExecuteCommandTool:
    return ExecuteCommandTool(timeout_s=15)


def test_workdir_applies_to_subprocess():
    """指定 workdir 后 pwd 输出 = workdir."""
    with tempfile.TemporaryDirectory() as d:
        r = _tool().execute(command="pwd", workdir=d)
        assert r.status.name == "SUCCESS", f"status={r.status}, content={r.content}"
        # 2026-08-21 摘要前置: 输出 = 元信息行 + 实际输出（取末行）
        out = r.content.strip().splitlines()[-1]
        # macOS /var → /private/var 符号链接，用 resolve 归一
        assert Path(out) == Path(d).resolve(), f"pwd 应为 {d}, 实际 {r.content}"


def test_workdir_missing_returns_failure():
    """workdir 不存在 → 如实失败回执."""
    r = _tool().execute(command="pwd", workdir="/nonexistent/definitely-not-here")
    assert r.status.name == "FAILURE", f"应失败, 实际 {r.status}"
    assert "不是有效目录" in r.content


def test_no_workdir_defaults_cwd():
    """未指定 workdir → 继承进程 cwd（零回归）."""
    r = _tool().execute(command="pwd")
    assert r.status.name == "SUCCESS"
    out = r.content.strip().splitlines()[-1]
    assert out == os.getcwd()


def test_llm_exec_cwd_injected():
    """LLM_EXEC_CWD 环境事实注入子进程."""
    r = _tool().execute(command="echo $LLM_EXEC_CWD")
    assert r.status.name == "SUCCESS"
    # 2026-08-21 摘要前置: 元信息行后为实际输出
    assert os.getcwd() in r.content

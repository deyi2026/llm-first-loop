"""execute_command 增强测试：workdir 支持 / 裁剪可配化 / 环境事实注入.

覆盖:
- workdir 指定后子进程 cwd 生效（pwd 输出 = workdir）
- workdir 不存在 → 失败回执（如实）
- workdir 为空 → 默认当前目录（零回归）
- TOOL_TRIM_MAX/HEAD/TAIL 环境变量生效（裁剪阈值可配）
- LLM_EXEC_CWD 环境事实注入子进程
- 裁剪默认值（未配置环境变量）不变（零回归）
"""

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
        # macOS /var → /private/var 符号链接，用 resolve 归一
        assert Path(r.content.strip()) == Path(d).resolve(), f"pwd 应为 {d}, 实际 {r.content}"


def test_workdir_missing_returns_failure():
    """workdir 不存在 → 如实失败回执."""
    r = _tool().execute(command="pwd", workdir="/nonexistent/definitely-not-here")
    assert r.status.name == "FAILURE", f"应失败, 实际 {r.status}"
    assert "不是有效目录" in r.content


def test_no_workdir_defaults_cwd():
    """未指定 workdir → 继承进程 cwd（零回归）."""
    r = _tool().execute(command="pwd")
    assert r.status.name == "SUCCESS"
    assert r.content.strip() == os.getcwd()


def test_llm_exec_cwd_injected():
    """LLM_EXEC_CWD 环境事实注入子进程."""
    r = _tool().execute(command="echo $LLM_EXEC_CWD")
    assert r.status.name == "SUCCESS"
    assert r.content.strip() == os.getcwd()


def test_trim_config_env_override():
    """TOOL_TRIM_MAX 可配：小阈值触发截断."""
    os.environ["TOOL_TRIM_MAX"] = "10"
    os.environ["TOOL_TRIM_HEAD"] = "5"
    os.environ["TOOL_TRIM_TAIL"] = "5"
    try:
        # 长输出（20 个 a）应触发截断（max=10）
        r = _tool().execute(command="printf 'aaaaaaaaaaaaaaaaaaaa'")
        assert "[输出已截断]" in r.content, f"应截断, 实际: {r.content}"
    finally:
        os.environ.pop("TOOL_TRIM_MAX", None)
        os.environ.pop("TOOL_TRIM_HEAD", None)
        os.environ.pop("TOOL_TRIM_TAIL", None)


def test_trim_config_default_no_truncate():
    """默认阈值（3000）下正常输出不截断（零回归）."""
    os.environ.pop("TOOL_TRIM_MAX", None)
    os.environ.pop("TOOL_TRIM_HEAD", None)
    os.environ.pop("TOOL_TRIM_TAIL", None)
    r = _tool().execute(command="printf 'hello'")
    assert "[输出已截断]" not in r.content
    assert r.content.strip() == "hello"


def test_trim_config_invalid_falls_back():
    """非法环境变量值回退默认（不报错）."""
    os.environ["TOOL_TRIM_MAX"] = "abc"
    try:
        r = _tool().execute(command="printf 'ok'")
        assert r.status.name == "SUCCESS"
        assert "ok" in r.content
    finally:
        os.environ.pop("TOOL_TRIM_MAX", None)

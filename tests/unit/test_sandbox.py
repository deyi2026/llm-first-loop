"""bash 沙箱后端测试（P3-3：EXEC_SANDBOX=bwrap|none）.

- 未启用 → 走既有 shell=True 路径（零回归）
- bwrap 启用且可用 → argv 含 bwrap 前缀（只读系统目录/独立命名空间/工作区可写），
  shell=False；回执如实标注"已启用 bwrap 沙箱"
- bwrap 启用但缺失 → fail-closed ERROR（命令不执行）
"""

from __future__ import annotations

from unittest import mock

import pytest

from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.registry import ToolResultStatus
from llm_loop.tools.sandbox import bwrap_argv, sandbox_argv, sandbox_mode


def test_sandbox_mode_default_none(monkeypatch):
    monkeypatch.delenv("EXEC_SANDBOX", raising=False)
    assert sandbox_mode() == "none"


def test_bwrap_argv_structure():
    argv = bwrap_argv("echo hi", "/tmp/work")
    assert argv[0] == "bwrap"
    assert "--unshare-pid" in argv and "--unshare-uts" in argv and "--unshare-ipc" in argv
    assert "--ro-bind" in argv and "/usr" in argv and "/etc" in argv
    assert "--tmpfs" in argv and "/tmp" in argv
    assert "--bind" in argv and "/tmp/work" in argv
    assert argv[-3:] == ["/bin/sh", "-c", "echo hi"]


def test_sandbox_argv_disabled(monkeypatch):
    monkeypatch.delenv("EXEC_SANDBOX", raising=False)
    argv, note = sandbox_argv("cmd", ".")
    assert argv is None and note == ""


def test_sandbox_argv_bwrap_ok(monkeypatch):
    monkeypatch.setenv("EXEC_SANDBOX", "bwrap")
    with mock.patch("llm_loop.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap"):
        argv, note = sandbox_argv("echo hi", "/w")
    assert argv is not None and argv[0] == "bwrap"
    assert note == "（已启用 bwrap 沙箱）"


def test_sandbox_argv_bwrap_missing_fail_closed(monkeypatch):
    monkeypatch.setenv("EXEC_SANDBOX", "bwrap")
    with (
        mock.patch("llm_loop.tools.sandbox.shutil.which", return_value=None),
        pytest.raises(RuntimeError) as ei,
    ):
        sandbox_argv("echo hi", "/w")
    assert "fail-closed" in str(ei.value)
    assert "bwrap" in str(ei.value)


def test_execute_bwrap_uses_argv_and_marks_receipt(monkeypatch, tmp_path):
    """启用 bwrap：Popen 收 argv（shell=False），回执含沙箱标注."""
    monkeypatch.setenv("EXEC_SANDBOX", "bwrap")
    with (
        mock.patch("llm_loop.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap"),
        mock.patch("subprocess.Popen") as popen,
    ):
        fake = mock.MagicMock()
        fake.communicate.return_value = ("输出内容", "")
        fake.returncode = 0
        popen.return_value = fake
        tool = ExecuteCommandTool()
        r = tool.execute(command="echo hi", workdir=str(tmp_path))
    assert r.status == ToolResultStatus.SUCCESS
    assert "已启用 bwrap 沙箱" in r.content
    kwargs = popen.call_args
    assert kwargs.kwargs["shell"] is False
    argv = kwargs.args[0]
    assert argv[0] == "bwrap" and "/bin/sh" in argv and "-c" in argv


def test_execute_bwrap_missing_fail_closed(monkeypatch, tmp_path):
    """显式 bwrap 而缺失：命令不执行，ERROR 如实（fail-closed）."""
    monkeypatch.setenv("EXEC_SANDBOX", "bwrap")
    with (
        mock.patch("llm_loop.tools.sandbox.shutil.which", return_value=None),
        mock.patch("subprocess.Popen") as popen,
    ):
        tool = ExecuteCommandTool()
        r = tool.execute(command="echo hi", workdir=str(tmp_path))
    assert r.status == ToolResultStatus.ERROR
    assert "沙箱不可用" in r.content
    popen.assert_not_called()


def test_execute_default_none_zero_regression(monkeypatch, tmp_path):
    """未启用：shell=True 路径不变（零回归）."""
    monkeypatch.delenv("EXEC_SANDBOX", raising=False)
    with mock.patch("subprocess.Popen") as popen:
        fake = mock.MagicMock()
        fake.communicate.return_value = ("ok", "")
        fake.returncode = 0
        popen.return_value = fake
        tool = ExecuteCommandTool()
        r = tool.execute(command="echo hi", workdir=str(tmp_path))
    assert r.status == ToolResultStatus.SUCCESS
    assert popen.call_args.kwargs["shell"] is True
    assert "已启用 bwrap 沙箱" not in r.content

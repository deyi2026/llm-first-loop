"""单元测试: execute_command 边界 + ToolResult 直接构造（T18 覆盖补强）."""

from __future__ import annotations

from unittest import mock

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.tools.base import Tool
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool


def test_execute_command_timeout():
    """命令超时 → timeout 状态.

    P1-5(审计发现 #11): 前台路径由 subprocess.run 改为 Popen + communicate
    （暴露句柄给注册表超时 terminate），工具内兜底超时对应 communicate(timeout)。
    """
    import subprocess

    tool = ExecuteCommandTool()

    class _FakePopen:
        pid = 1234567  # 不存在的 pid: terminate 的 killpg 会 ProcessLookupError（被抑制）

        def poll(self):
            return None

        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired("x", timeout)

        def kill(self):
            pass

        def wait(self, timeout=None):
            return -9

    with mock.patch("subprocess.Popen", return_value=_FakePopen()):
        r = tool.execute(command="sleep 100")
    assert r.status == ToolResultStatus.TIMEOUT


def test_execute_command_oserror():
    """OSError → error 状态 + 完整错误."""
    tool = ExecuteCommandTool()
    with mock.patch("subprocess.Popen", side_effect=OSError("boom")):
        r = tool.execute(command="whatever")
    assert r.status == ToolResultStatus.ERROR
    assert r.error_type == "OSError"


def test_execute_command_empty():
    """缺 command → failure."""
    tool = ExecuteCommandTool()
    r = tool.execute()
    assert r.status == ToolResultStatus.FAILURE


def test_tool_protocol_implementable():
    """Tool 协议可实现（FR-TOOL-03）: 自定义工具满足协议."""

    class MyTool:
        name = "my_tool"
        description = "test"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **kwargs) -> ToolResult:
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="ok",
                tool_call_id=kwargs.get("tool_call_id", ""),
                tool_name=self.name,
            )

    t: Tool = MyTool()  # 类型检查: 协议满足
    assert t.name == "my_tool"
    r = t.execute()
    assert r.status == ToolResultStatus.SUCCESS

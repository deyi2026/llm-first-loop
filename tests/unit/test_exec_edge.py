"""单元测试: execute_command 边界 + ToolResult 直接构造（T18 覆盖补强）."""

from __future__ import annotations

from unittest import mock

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.tools.base import Tool
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool


def test_execute_command_timeout():
    """命令超时 → timeout 状态."""
    tool = ExecuteCommandTool()
    with mock.patch("subprocess.run", side_effect=__import__("subprocess").TimeoutExpired("x", 30)):
        r = tool.execute(command="sleep 100")
    assert r.status == ToolResultStatus.TIMEOUT


def test_execute_command_oserror():
    """OSError → error 状态 + 完整错误."""
    tool = ExecuteCommandTool()
    with mock.patch("subprocess.run", side_effect=OSError("boom")):
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

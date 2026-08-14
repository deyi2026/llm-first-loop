"""unregister/dispose 测试（EVO-20260814-488e7ef7: 注册即回滚）.

覆盖: 卸载/重注册/不存在返回 False/批量卸载幂等/卸载后执行 fail-closed.
"""

from __future__ import annotations

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.registry import ToolRegistry


def test_unregister_removes_tool():
    reg = ToolRegistry()
    reg.register(ReadFileTool())
    assert "read_file" in reg.names()
    assert reg.unregister("read_file") is True
    assert "read_file" not in reg.names()


def test_unregister_nonexistent_returns_false():
    reg = ToolRegistry()
    assert reg.unregister("no-such-tool") is False  # 不存在不抛异常


def test_register_after_unregister_works():
    """卸载后可重新注册（热更新/演进回滚通道）."""
    reg = ToolRegistry()
    reg.register(ExecuteCommandTool())
    assert reg.unregister("execute_command") is True
    reg.register(ExecuteCommandTool())  # 重注册
    assert "execute_command" in reg.names()


def test_dispose_clears_all_and_idempotent():
    reg = ToolRegistry()
    reg.register(ReadFileTool())
    reg.register(ExecuteCommandTool())
    assert reg.dispose() == 2
    assert reg.names() == []
    assert reg.dispose() == 0  # 幂等


def test_unregister_then_execute_fails_closed():
    """卸载后 execute → 工具不存在 → failure（fail-closed，安全）."""
    reg = ToolRegistry()
    reg.register(ReadFileTool())
    reg.unregister("read_file")
    result = reg.execute(ToolCall(id="c1", name="read_file", arguments={"path": "/tmp/x"}))
    assert result.status == ToolResultStatus.FAILURE
    assert "不存在" in result.content or "工具" in result.content

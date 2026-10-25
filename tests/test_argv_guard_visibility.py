"""P2-2 回归护栏：argv 调用不能让围栏"看不见命令"。

背景（子代理交付时如实披露的残余风险）：registry 的共享服务控制权/审核准入/
灾难性安全三层围栏原先只读 args["command"]；argv 形态下 command 为空串，
managed_service 围栏会直接放行——等于给新入口开了一条绕过服务控制权的缝。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.tools.registry import ToolRegistry, _command_text_for_guard, _guard_view_args


def test_command_text_from_argv() -> None:
    args = {"argv": ["launchctl", "kickstart", "gui/501/com.example.web"], "cwd": "/tmp"}
    assert _command_text_for_guard("execute_command", args) == "launchctl kickstart gui/501/com.example.web"


def test_command_text_prefers_explicit_command() -> None:
    args = {"command": "echo hi", "argv": ["echo", "hi"]}
    assert _command_text_for_guard("execute_command", args) == "echo hi"


def test_guard_view_does_not_mutate_original() -> None:
    args = {"argv": ["ls", "-la"]}
    view = _guard_view_args("execute_command", args)
    assert view["command"] == "ls -la"
    assert "argv" not in view
    assert args == {"argv": ["ls", "-la"]}


def test_guard_view_ignored_for_other_tools() -> None:
    args = {"argv": ["x"]}
    assert _guard_view_args("read_file", args) is args


class _RecordingManagedGuard:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def guard(self, command: str):
        self.seen.append(command)
        if "launchctl" in command:
            return SimpleNamespace(blocked=True, reason="共享服务生命周期", services=["web"])
        return None


class _EchoTool:
    name = "execute_command"
    description = "test double"
    parameters = {"type": "object", "properties": {}}
    category = "runtime"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return ToolResult(status=ToolResultStatus.SUCCESS, content="ok", tool_call_id="t", tool_name=self.name)


@pytest.fixture()
def harness():
    registry = ToolRegistry()
    tool = _EchoTool()
    registry.register(tool)
    guard = _RecordingManagedGuard()
    registry.set_managed_service_guard(guard) if hasattr(registry, "set_managed_service_guard") else None
    registry._managed_service_guard = guard  # 直接注入：测试装配细节，生产由 factory 装配
    return registry, tool, guard


def test_argv_call_is_visible_to_managed_service_guard(harness) -> None:
    registry, tool, guard = harness
    call = ToolCall(
        id="c1",
        name="execute_command",
        arguments={"argv": ["launchctl", "kickstart", "gui/501/com.example.web"]},
    )
    result = registry.execute(call)
    assert result.status == ToolResultStatus.BLOCKED
    assert "共享服务控制权拦截" in result.content
    assert guard.seen == ["launchctl kickstart gui/501/com.example.web"]
    assert tool.calls == []  # 未真正执行


def test_argv_call_with_benign_command_executes(harness) -> None:
    registry, tool, guard = harness
    call = ToolCall(id="c2", name="execute_command", arguments={"argv": ["echo", "hi"]})
    result = registry.execute(call)
    assert result.status == ToolResultStatus.SUCCESS
    assert tool.calls and tool.calls[0]["argv"] == ["echo", "hi"]
    assert guard.seen == ["echo hi"]

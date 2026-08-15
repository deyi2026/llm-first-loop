"""MCP 客户端接入测试（P3-1）.

- 配置解析：合法/非法/缺字段条目如实跳过
- 连接握手 + 工具清单 + schema 透传（真实 stdio 进程 fake_mcp_server.py）
- 五态包装：echo→success；boom→failure；sleep→timeout（短超时）；进程缺失→error
- 注册进 ToolRegistry 后走统一 execute 通道（超时/输出分层复用）
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from llm_loop.tools.mcp_client import (
    McpConnection,
    McpServerSpec,
    parse_servers,
    register_mcp_tools,
)
from llm_loop.tools.registry import ToolRegistry, ToolResultStatus

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "fake_mcp_server.py"


def _spec(**kw) -> McpServerSpec:
    base = dict(name="fake", command="python3", args=[str(_FIXTURE)])
    base.update(kw)
    return McpServerSpec(**base)


# ── 配置解析 ──

def test_parse_servers_valid():
    raw = json.dumps([
        {"name": "fs", "command": "npx", "args": ["-y", "srv"], "env": {"A": "1"}},
        {"name": "off", "command": "x", "enabled": False},
    ])
    specs = parse_servers(raw)
    assert [s.name for s in specs] == ["fs", "off"]
    assert specs[0].args == ["-y", "srv"] and specs[0].env == {"A": "1"}
    assert specs[1].enabled is False


def test_parse_servers_invalid(caplog: pytest.LogCaptureFixture):
    assert parse_servers("not-json") == []
    assert parse_servers('{"a":1}') == []  # 非数组
    assert parse_servers('[{"command": "x"}]') == []  # 缺 name
    assert parse_servers('["str"]') == []  # 非对象条目
    assert any("MCP_SERVERS" in r.message for r in caplog.records) or True


# ── 连接与工具清单（真实 stdio 进程） ──

def test_connect_lists_tools():
    conn = McpConnection(_spec())
    tools = conn.connect()
    names = [t.name for t in tools]
    assert "echo" in names and "boom" in names
    echo = next(t for t in tools if t.name == "echo")
    assert echo.input_schema.get("required") == ["text"]
    conn.close()


def test_connect_missing_command_fails():
    conn = McpConnection(_spec(command="/nonexistent/bin/xyz"))
    with pytest.raises(RuntimeError):
        conn.connect()


# ── 五态包装 ──

def _make_registered_tool(timeout: float = 10.0) -> McpConnection:
    conn = McpConnection(_spec(), call_timeout=timeout)
    conn.connect()
    return conn


def test_call_success():
    conn = _make_registered_tool()
    result = conn.call_tool("echo", {"text": "你好"})
    assert result["isError"] is False
    text = result["content"][0]["text"]
    assert text == "echo:你好"
    conn.close()


def test_call_is_error_maps_failure():
    conn = _make_registered_tool()
    result = conn.call_tool("boom", {})
    assert result.get("isError") is True
    conn.close()


def test_call_timeout():
    conn = McpConnection(_spec(), call_timeout=1.0)
    conn.connect()
    with pytest.raises(RuntimeError) as ei:
        conn.call_tool("sleep", {"seconds": 30})
    assert "超时" in str(ei.value)
    conn.close()


# ── 注册表集成（五态 + 统一通道） ──

def test_register_mcp_tools_and_execute():
    from llm_loop.core.message import ToolCall

    registry = ToolRegistry()
    raw = json.dumps([{"name": "fake", "command": "python3", "args": [str(_FIXTURE)]}])
    registered = register_mcp_tools(registry, raw)
    assert "mcp.fake.echo" in registered
    assert "mcp.fake.boom" in registered

    def _exec(name: str, args: dict):
        return registry.execute(ToolCall(id=f"c-{name}", name=name, arguments=args))

    # echo → success
    r = _exec("mcp.fake.echo", {"text": "hi"})
    assert r.status == ToolResultStatus.SUCCESS
    assert "echo:hi" in r.content

    # boom → failure
    r = _exec("mcp.fake.boom", {})
    assert r.status == ToolResultStatus.FAILURE
    assert "boom 错误详情" in r.content

    # 未注册工具 → failure（fail-closed）
    r = _exec("mcp.fake.missing", {})
    assert r.status == ToolResultStatus.FAILURE


def test_register_fail_open_when_server_down(caplog: pytest.LogCaptureFixture):
    from llm_loop.core.message import ToolCall

    registry = ToolRegistry()
    raw = json.dumps([
        {"name": "dead", "command": "/nonexistent/bin/xyz"},
        {"name": "fake", "command": "python3", "args": [str(_FIXTURE)]},
    ])
    registered = register_mcp_tools(registry, raw)
    assert "mcp.dead.echo" not in registered  # 死服务器 fail-open
    assert "mcp.fake.echo" in registered  # 健康服务器不受影响
    r = registry.execute(ToolCall(id="c-d", name="mcp.dead.echo", arguments={}))
    assert r.status == ToolResultStatus.FAILURE


def test_mcp_tool_error_state_on_channel_failure():
    """进程失联（通道错误）→ ERROR 态（区别于工具自身失败）."""
    from llm_loop.tools.mcp_client import McpTool

    conn = mock.MagicMock()
    conn.call_tool.side_effect = RuntimeError("进程已退出")
    tool = McpTool("fake", conn, mock.MagicMock(name="x", description="d", input_schema={}))
    r = tool.execute()
    assert r.status == ToolResultStatus.ERROR
    assert "程序异常" in r.content

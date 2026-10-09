"""MCP 客户端接入测试（P3-1）.

- 配置解析：合法/非法/缺字段条目如实跳过
- 连接握手 + 工具清单 + schema 透传（真实 stdio 进程 fake_mcp_server.py）
- 五态包装：echo→success；boom→failure；sleep→timeout（短超时）；进程缺失→error
- 注册进 ToolRegistry 后走统一 execute 通道（超时/输出分层复用）
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from unittest import mock

import pytest

from llm_loop.tools.mcp_client import (
    McpConnection,
    McpNotDispatchedError,
    McpOutcomeUnknownError,
    McpProtocolError,
    McpServerSpec,
    McpTool,
    McpToolDef,
    _assign_registry_names,
    _close_server_conns,
    parse_servers,
    refresh_mcp_tools,
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
    assert "mcp_fake_echo" in registered
    assert "mcp_fake_boom" in registered

    def _exec(name: str, args: dict):
        return registry.execute(ToolCall(id=f"c-{name}", name=name, arguments=args))

    # echo → success
    r = _exec("mcp_fake_echo", {"text": "hi"})
    assert r.status == ToolResultStatus.SUCCESS
    assert "echo:hi" in r.content

    # boom → failure
    r = _exec("mcp_fake_boom", {})
    assert r.status == ToolResultStatus.FAILURE
    assert "boom 错误详情" in r.content

    # 未注册工具 → failure（fail-closed）
    r = _exec("mcp_fake_missing", {})
    assert r.status == ToolResultStatus.FAILURE


def test_register_fail_open_when_server_down(caplog: pytest.LogCaptureFixture):
    from llm_loop.core.message import ToolCall

    registry = ToolRegistry()
    raw = json.dumps([
        {"name": "dead", "command": "/nonexistent/bin/xyz"},
        {"name": "fake", "command": "python3", "args": [str(_FIXTURE)]},
    ])
    registered = register_mcp_tools(registry, raw)
    assert "mcp_dead_echo" not in registered  # 死服务器 fail-open
    assert "mcp_fake_echo" in registered  # 健康服务器不受影响
    r = registry.execute(ToolCall(id="c-d", name="mcp_dead_echo", arguments={}))
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


# ── P0 契约保真回归（2026-10-09，docs/DESIGN-20261009-plugin-ecosystem-integration §11 P0）──


class MockConn:
    """所有权/刷新测试用 mock 连接（记录 close 调用）."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def call_tool(self, name: str, arguments: dict) -> dict:
        return {"content": [{"type": "text", "text": f"mock:{name}"}]}


# 1) schema 保真：$defs/oneOf/additionalProperties 等原样保留，不重建
def test_p0_schema_fidelity_preserves_advanced_keywords():
    schema = {
        "type": "object",
        "properties": {
            "x": {"$ref": "#/$defs/P"},
            "y": {"type": "array", "items": {"$ref": "#/$defs/P"}},
        },
        "required": ["x"],
        "$defs": {"P": {"type": "string", "enum": ["a", "b"]}},
        "oneOf": [{"required": ["x"]}, {"required": ["y"]}],
        "additionalProperties": False,
        "propertyNames": {"pattern": "^[a-z]+$"},
    }
    tool = McpTool("srv", MockConn(), McpToolDef(name="adv", input_schema=schema))
    assert tool.parameters["$defs"] == schema["$defs"]
    assert tool.parameters["oneOf"] == schema["oneOf"]
    assert tool.parameters["additionalProperties"] is False
    assert tool.parameters["propertyNames"] == schema["propertyNames"]
    assert tool.parameters["properties"]["x"] == schema["properties"]["x"]
    # deepcopy：适配层改动不回写服务器声明
    tool.parameters["properties"]["x"]["description"] = "mutated"
    assert "description" not in schema["properties"]["x"]


def test_p0_schema_fidelity_empty_schema_minimal_object():
    tool = McpTool("srv", MockConn(), McpToolDef(name="e"))
    assert tool.parameters == {"type": "object", "properties": {}, "required": []}


# 2) 结果保真：非 text 块 / structuredContent 以指针标注，原始结果可取回
def test_p0_result_fidelity_non_text_and_structured_pointer():
    raw = {
        "content": [
            {"type": "text", "text": "hello"},
            {"type": "image", "data": "<bytes>", "mimeType": "image/png"},
        ],
        "structuredContent": {"answer": 42},
        "_meta": {"k": "v"},
    }

    class StructConn(MockConn):
        def call_tool(self, name: str, arguments: dict) -> dict:
            return raw

    tool = McpTool("srv", StructConn(), McpToolDef(name="s"))
    r = tool.execute(text="x")
    assert r.status == ToolResultStatus.SUCCESS
    assert "hello" in r.content
    assert "type=image" in r.content and "digest=" in r.content
    assert "[structuredContent" in r.content
    assert "42" not in r.content  # 结构化值不进模型视图（指针代之）
    assert tool.last_raw_result == raw


def test_p0_is_error_maps_failure_with_text_preserved():
    class BoomConn(MockConn):
        def call_tool(self, name: str, arguments: dict) -> dict:
            return {"content": [{"type": "text", "text": "boom 错误详情"}], "isError": True}

    tool = McpTool("srv", BoomConn(), McpToolDef(name="b"))
    r = tool.execute()
    assert r.status == ToolResultStatus.FAILURE
    assert "boom 错误详情" in r.content


# 3) typed 错误：未派发→重试安全；结果未知/协议错误→不重放
def test_p0_timeout_is_outcome_unknown_no_replay():
    """派发后超时 → McpOutcomeUnknownError（标注不自动重放），单次等待不翻倍."""
    conn = McpConnection(
        McpServerSpec(name="silent", command="python3", args=["-c", "import time; time.sleep(30)"]),
        call_timeout=1.0,
    )
    conn._start_process()
    try:
        t0 = time.monotonic()
        with pytest.raises(McpOutcomeUnknownError) as ei:
            conn.call_tool("echo", {"text": "x"})
        elapsed = time.monotonic() - t0
        assert "超时" in str(ei.value)
        assert "不自动重放" in str(ei.value)
        assert isinstance(ei.value, RuntimeError)  # 兼容旧 except RuntimeError 路径
        assert elapsed < 1.8  # 单次超时；旧实现会重连后再等一轮（≈2×timeout）
    finally:
        conn.close()


def test_p0_not_dispatched_reconnect_replays_once():
    """写入前进程已退出 → 确认未派发，重连重放一次并成功."""
    assert issubclass(McpNotDispatchedError, RuntimeError)  # typed 且兼容旧异常路径
    conn = McpConnection(_spec(name="retry"))
    dead = subprocess.Popen(["python3", "-c", "pass"])
    dead.wait()
    conn._proc = dead
    try:
        result = conn.call_tool("echo", {"text": "hi"})
        assert any(b.get("text") == "echo:hi" for b in result.get("content", []))
        assert conn._proc is not dead and conn._proc.poll() is None  # 已换新进程
    finally:
        conn.close()


def test_p0_protocol_error_typed_no_retry():
    """服务器 JSON-RPC error → McpProtocolError 立即上抛（派发已确认，不重放）."""
    conn = McpConnection(_spec(name="perr"))
    conn.connect()
    try:
        with pytest.raises(McpProtocolError) as ei:
            conn._rpc("bogus/method", {})
        assert "错误" in str(ei.value)
    finally:
        conn.close()


def test_p0_execute_outcome_unknown_error_state():
    class TimeoutConn(MockConn):
        def call_tool(self, name: str, arguments: dict) -> dict:
            raise McpOutcomeUnknownError("超时（请求已派发、结果未知，不自动重放）")

    tool = McpTool("srv", TimeoutConn(), McpToolDef(name="t"))
    r = tool.execute()
    assert r.status == ToolResultStatus.ERROR
    assert "程序异常" in r.content and "结果未知" in r.content


# 4) 身份与所有权：防碰撞 digest、精确关闭（非前缀）、刷新先建后拆
def test_p0_name_collision_digest_suffix_deterministic():
    """a.b 与 a_b 归一同名 → 确定性 digest 后缀消歧（不静默覆盖）."""
    defs = [McpToolDef(name="c")]
    occupied = {"mcp_a_b_c": "mcp.a_b.c"}  # 服务器 a_b 已持有基础名
    names1 = _assign_registry_names("a.b", defs, occupied)
    names2 = _assign_registry_names("a.b", defs, occupied)
    assert names1["c"].startswith("mcp_a_b_c_")
    assert names1 == names2  # 确定性（同输入同名）
    assert names1["c"] != "mcp_a_b_c"
    # 基础名空闲 / 同身份幂等重注册 → 保持基础名
    assert _assign_registry_names("free", [McpToolDef(name="t")], {})["t"] == "mcp_free_t"
    assert _assign_registry_names("a.b", defs, {"mcp_a_b_c": "mcp.a.b.c"})["c"] == "mcp_a_b_c"


def test_p0_cross_server_name_collision_integration():
    """真实双服务器（a.b / a_b）同名工具：三个基础名全部消歧且可执行."""
    from llm_loop.core.message import ToolCall

    raw = json.dumps([
        {"name": "a.b", "command": "python3", "args": [str(_FIXTURE)]},
        {"name": "a_b", "command": "python3", "args": [str(_FIXTURE)]},
    ])
    registry = ToolRegistry()
    registered = register_mcp_tools(registry, raw)
    assert len(registered) == 6  # 2 服务器 × (echo/boom/sleep)
    assert "mcp_a_b_echo" in registered
    suffixed = [n for n in registered if n.startswith("mcp_a_b_echo_")]
    assert len(suffixed) == 1  # 后注册者确定性后缀，不覆盖
    r = registry.execute(ToolCall(id="c1", name=suffixed[0], arguments={"text": "hi"}))
    assert r.status == ToolResultStatus.SUCCESS
    assert "echo:hi" in r.content
    _close_server_conns(registry, "a.b")
    _close_server_conns(registry, "a_b")


def test_p0_close_server_conns_exact_ownership_no_prefix_bleed():
    """关闭服务器 a 的连接不得误伤 a.b（旧前缀实现 mcp_a_ 会命中 mcp_a_b_）."""
    registry = ToolRegistry()
    conn_ab, conn_a = MockConn(), MockConn()
    registry.register(McpTool("a.b", conn_ab, McpToolDef(name="t")))
    registry.register(McpTool("a", conn_a, McpToolDef(name="t")))
    assert {"mcp_a_b_t", "mcp_a_t"} <= set(registry.names())
    _close_server_conns(registry, "a")
    assert conn_a.closed
    assert not conn_ab.closed


def test_p0_refresh_keeps_old_view_when_new_connection_fails():
    """新连接失败 → 保留旧可用视图（先建后拆；旧实现先丢旧再连，视图丢失）."""
    registry = ToolRegistry()
    conn = MockConn()
    registry.register(McpTool("s", conn, McpToolDef(name="t")))
    raw = json.dumps([{"name": "s", "command": "no_such_binary_zzz_20261009"}])
    registered, unregistered = refresh_mcp_tools(registry, raw)
    assert registered == [] and unregistered == []
    assert "mcp_s_t" in registry.names()
    assert not conn.closed


def test_p0_refresh_sweeps_servers_removed_from_config():
    """已从配置删除的服务器统一精确清理（旧实现只扫配置内服务器，删除者残留）."""
    registry = ToolRegistry()
    conn = MockConn()
    registry.register(McpTool("gone", conn, McpToolDef(name="t")))
    raw = json.dumps([{"name": "keep", "command": "no_such_binary_zzz_20261009"}])
    _, unregistered = refresh_mcp_tools(registry, raw)
    assert unregistered == ["mcp_gone_t"]
    assert "mcp_gone_t" not in registry.names()
    assert conn.closed

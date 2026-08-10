"""单元测试: tool_calls 流式聚合与工具注册/执行（T18 / 约束 C4-C5 / FR-TOOL）."""

from __future__ import annotations

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.llm.schemas import ToolCallDeltaAggregator, build_tools_schema
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.registry import ToolRegistry


def test_tool_calls_delta_aggregation():
    """约束 C5: 分片 delta 按 index 归并（含 id/name/arguments 分片）."""
    agg = ToolCallDeltaAggregator()
    agg.add_delta(
        {
            "index": 0,
            "id": "call_a",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":'},
        }
    )
    agg.add_delta({"index": 0, "function": {"arguments": ' "data/x.txt"}'}})
    agg.add_delta(
        {
            "index": 1,
            "id": "call_b",
            "type": "function",
            "function": {"name": "web_fetch", "arguments": '{"url": "https://example.com"}'},
        }
    )
    calls = agg.finish()
    assert len(calls) == 2
    assert calls[0]["id"] == "call_a"
    assert calls[0]["name"] == "read_file"
    assert calls[0]["arguments"] == {"path": "data/x.txt"}
    assert calls[1]["id"] == "call_b"
    assert calls[1]["arguments"]["url"] == "https://example.com"


def test_tools_schema_built():
    """约束 C4: tools 参数 JSON Schema 形态."""
    defs = [{"name": "read_file", "description": "读文件", "parameters": {"type": "object"}}]
    schema = build_tools_schema(defs)
    assert schema[0]["type"] == "function"
    assert schema[0]["function"]["name"] == "read_file"


def test_registry_register_and_execute(tmp_path):
    """FR-TOOL-03: 注册后可发现可执行."""
    reg = ToolRegistry()
    reg.register(ReadFileTool())
    assert "read_file" in reg.names()
    f = tmp_path / "notes.txt"
    f.write_text("hello", encoding="utf-8")
    result = reg.execute(ToolCall(id="c1", name="read_file", arguments={"path": str(f)}))
    assert result.status == ToolResultStatus.SUCCESS
    assert "hello" in result.content


def test_registry_unknown_tool():
    """工具不存在 → failure + 可用工具列表."""
    reg = ToolRegistry()
    result = reg.execute(ToolCall(id="c1", name="nope", arguments={}))
    assert result.status == ToolResultStatus.FAILURE
    assert "不存在" in result.content


def test_registry_param_validation():
    """T38: 参数类型不再硬拦截 → 容错执行（类型偏差由工具容错或如实反馈）."""
    reg = ToolRegistry()
    reg.register(ReadFileTool())
    # 类型偏差（123 非 str）不再被程序拦截，由工具容错执行（转 str 查文件 → 文件不存在如实反馈）
    result = reg.execute(ToolCall(id="c1", name="read_file", arguments={"path": 123}))
    assert result.status in {ToolResultStatus.FAILURE, ToolResultStatus.ERROR}
    # 非 dict 参数仍最小防御拦截（无法执行）
    result2 = reg.execute(ToolCall(id="c2", name="read_file", arguments="not-a-dict"))  # type: ignore[arg-type]
    assert result2.status == ToolResultStatus.FAILURE
    assert "参数" in result2.content


def test_registry_execute_command_success():
    """execute_command 成功路径."""
    reg = ToolRegistry()
    reg.register(ExecuteCommandTool())
    result = reg.execute(
        ToolCall(id="c1", name="execute_command", arguments={"command": "echo hi"})
    )
    assert result.status == ToolResultStatus.SUCCESS
    assert "hi" in result.content


def test_registry_execute_command_failure():
    """execute_command 非零退出 → failure + 退出码."""
    reg = ToolRegistry()
    reg.register(ExecuteCommandTool())
    result = reg.execute(ToolCall(id="c1", name="execute_command", arguments={"command": "exit 3"}))
    assert result.status == ToolResultStatus.FAILURE
    assert "3" in result.content

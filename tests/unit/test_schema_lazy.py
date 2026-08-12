"""工具 Schema 索引化测试（EVO-d5db88d9）.

lazy 索引（体积最小） / 默认全量零回归 / get_tool_schema 按需读取完整 Schema。
直接装配 ToolRegistry + 假工具，零真实 LLM、零真实网络。
"""

import json

from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.registry import GetToolSchemaTool, ToolRegistry


class _FakeTool:
    def __init__(self, name: str, description: str = "描述" * 50):
        self.name = name
        self.description = description
        self.parameters = {
            "type": "object",
            "properties": {
                "a": {"type": "string", "description": "参数a说明很长"},
                "b": {"type": "integer", "description": "参数b"},
            },
            "required": ["a"],
        }

    def execute(self, **kwargs):
        return f"{self.name}:ok"


def _reg() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_FakeTool("read_file"))
    reg.register(_FakeTool("execute_command"))
    return reg


def test_schemas_default_full_zeroregress():
    """默认（lazy=False）全量注入：完整 description + 完整 parameters（零回归）."""
    reg = _reg()
    defs = reg.schemas()
    assert len(defs) == 2
    for d in defs:
        assert d["description"]  # 完整 description
        assert "参数a说明很长" in d["parameters"]["properties"]["a"]["description"]  # 完整参数说明


def test_schemas_lazy_index_compact():
    """lazy=True 精简索引：description 截断 200 + 参数骨架（无 description）."""
    reg = _reg()
    defs = reg.schemas(lazy=True)
    for d in defs:
        assert len(d["description"]) <= 200  # 截断
        prop = d["parameters"]["properties"]["a"]
        assert "description" not in prop  # 骨架无参数说明
        assert prop["type"] == "string"  # 保留类型
        assert d["parameters"]["required"] == ["a"]


def test_lazy_index_smaller_than_full():
    """lazy 索引体积显著小于全量（期望效果：上下文占用可控）."""
    reg = _reg()
    full_len = len(json.dumps(reg.schemas(), ensure_ascii=False))
    lazy_len = len(json.dumps(reg.schemas(lazy=True), ensure_ascii=False))
    assert lazy_len < full_len


def test_get_tool_schema_full():
    """get_tool_schema 返回指定工具完整 Schema（含参数说明）."""
    reg = _reg()
    tool = GetToolSchemaTool(reg)
    result = tool.execute(tool_name="read_file")
    assert result.status == ToolResultStatus.SUCCESS
    assert "read_file" in result.content
    assert "参数a说明很长" in result.content  # 完整参数说明可读


def test_get_tool_schema_not_found():
    """get_tool_schema 查询不存在工具 → 如实 FAILURE + 可用工具列表."""
    reg = _reg()
    tool = GetToolSchemaTool(reg)
    result = tool.execute(tool_name="no_such_tool")
    assert result.status == ToolResultStatus.FAILURE
    assert "工具不存在" in result.content
    assert "read_file" in result.content

"""P1-B regression: schema discovery is not a capability grant."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.registry import GetToolSchemaTool, ToolRegistry


def test_promotion_module_is_retired():
    root = Path(__file__).resolve().parents[2]
    assert not (root / "src/llm_loop/tools/promotion.py").exists()
    assert importlib.util.find_spec("llm_loop.tools.promotion") is None


def test_exact_schema_lookup_has_no_promotion_side_effect():
    class T:
        name = "target_tool"
        description = "target"
        parameters = {"type": "object", "properties": {"x": {"type": "string"}}}

        def execute(self, **kwargs):  # pragma: no cover
            raise AssertionError("not executed")

    reg = ToolRegistry()
    reg.register(T())
    tool = GetToolSchemaTool(reg)
    first = tool.execute(tool_name="target_tool")
    second = tool.execute(tool_name="target_tool")
    assert first.status is ToolResultStatus.SUCCESS
    assert second.status is ToolResultStatus.SUCCESS
    assert first.content == second.content
    assert "target_tool" in first.content and '"x"' in first.content
    assert not hasattr(first, "promotion_signal")

"""P1-B regression: keyword/index provider schema selector is retired."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.tools.registry import ToolRegistry


@dataclass
class _Tool:
    name: str

    @property
    def description(self) -> str:
        return "long description " * 20

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "path description"},
                "mode": {"type": "string", "enum": ["a", "b"]},
            },
            "required": ["path"],
        }

    def execute(self, **kwargs):
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="ok",
            tool_call_id="",
            tool_name=self.name,
        )


def test_prefix_layer_selector_module_is_retired():
    root = Path(__file__).resolve().parents[2]
    assert not (root / "src/llm_loop/tools/prefix_layer.py").exists()
    assert importlib.util.find_spec("llm_loop.tools.prefix_layer") is None


def test_settings_has_no_prefix_layered_selector():
    from llm_loop.config import Settings

    assert not hasattr(Settings, "prefix_layered")


def test_lazy_schema_compaction_preserves_callable_parameter_skeleton():
    reg = ToolRegistry()
    reg.register(_Tool("parameterized_tool"))
    row = reg.schemas(lazy=True)[0]
    params = row["parameters"]
    assert row["name"] == "parameterized_tool"
    assert params["type"] == "object"
    assert params["required"] == ["path"]
    assert params["properties"]["path"]["type"] == "string"
    assert params["properties"]["mode"]["enum"] == ["a", "b"]
    assert "description" not in params["properties"]["path"]


def test_engine_user_text_cannot_upgrade_schema_shape(build_test_engine):
    engine, fake = build_test_engine([{"content": "a"}, {"content": "b"}])
    engine.registry.register(_Tool("parameterized_tool"))
    sid = engine.session.create()
    engine.run(sid, "完全无关文本")
    first = next(
        t for t in fake.calls[-1]["tools"] if t["function"]["name"] == "parameterized_tool"
    )
    engine.run(sid, "parameterized_tool path mode 请使用它")
    second = next(
        t for t in fake.calls[-1]["tools"] if t["function"]["name"] == "parameterized_tool"
    )
    assert second == first
    assert "path" in first["function"]["parameters"]["properties"]

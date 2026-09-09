"""枚举参数约束投递层前置暴露测试（EVO-20260903-20152277）.

lazy/index 投递不携带完整 JSON Schema，enum 原本会丢失 → 模型首调踩参数预检。
验收：① lazy 骨架保留 enum 键（机器可读真值）；② lazy description 不重复枚举；
③ index_schemas 因 parameters 只有空骨架，才内联紧凑枚举；④ 无枚举工具零回归。
"""

import json

from llm_loop.tools.registry import ToolRegistry


class _EnumTool:
    name = "self_evaluate"
    description = "主动触发自我评估" * 30  # 240 字符，验证截断让位
    parameters = {
        "type": "object",
        "properties": {
            "trigger": {
                "type": "string",
                "enum": ["periodic", "milestone", "anomaly", "manual"],
            },
            "plain": {"type": "string"},
        },
        "required": ["trigger"],
    }

    def execute(self, **kwargs):
        return "ok"


class _NestedTool:
    name = "workflow_like"
    description = "nested schema"
    parameters = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "large prose must disappear"},
                        "executor": {"type": "string", "enum": ["local", "remote"]},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["task"],
                },
            }
        },
        "required": ["steps"],
    }

    def execute(self, **kwargs):
        return "ok"


class _PlainTool:
    name = "plain_tool"
    description = "无枚举参数工具"
    parameters = {"type": "object", "properties": {"x": {"type": "string"}}}

    def execute(self, **kwargs):
        return "ok"


def _reg() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_EnumTool())
    reg.register(_PlainTool())
    return reg


def test_lazy_description_does_not_duplicate_enum_values():
    """lazy 已有机器可读 enum，不再把同一约束复制进自然语言描述。"""
    defs = {d["name"]: d for d in _reg().schemas(lazy=True)}
    d = defs["self_evaluate"]
    assert "trigger(periodic|milestone|anomaly|manual)" not in d["description"]
    assert len(d["description"]) <= 200


def test_lazy_description_uses_compact_contract_without_changing_full_description():
    """Built-in lazy prose is curated/short; full schema still preserves source text."""
    defs = {d["name"]: d for d in _reg().schemas(lazy=True)}
    d = defs["self_evaluate"]
    assert len(d["description"]) < 120
    assert d["description"] != _EnumTool.description[:200]
    full = {d["name"]: d for d in _reg().schemas()}["self_evaluate"]
    assert full["description"] == _EnumTool.description


def test_lazy_skeleton_keeps_enum_key():
    defs = {d["name"]: d for d in _reg().schemas(lazy=True)}
    prop = defs["self_evaluate"]["parameters"]["properties"]["trigger"]
    assert prop["type"] == "string"
    assert prop["enum"] == ["periodic", "milestone", "anomaly", "manual"]
    assert "description" not in prop  # 骨架仍不带参数说明


def test_plain_tool_zero_regression():
    defs = {d["name"]: d for d in _reg().schemas(lazy=True)}
    d = defs["plain_tool"]
    assert d["description"] == _PlainTool.description
    assert "enum" not in d["parameters"]["properties"]["x"]


def test_index_schemas_inline_enum_within_budget():
    r = _reg()
    idx = {t["name"]: t for t in r.index_schemas()}
    t = idx["self_evaluate"]
    assert "trigger(periodic|milestone|anomaly|manual)" in t["description"]
    assert "必填: trigger" in t["description"]
    assert len(t["description"]) <= 80 + 40
    assert t["parameters"] == {"type": "object"}  # 合法最小 schema 不变


def test_lazy_still_smaller_than_full():
    reg = _reg()
    assert len(json.dumps(reg.schemas(lazy=True), ensure_ascii=False)) < len(
        json.dumps(reg.schemas(), ensure_ascii=False)
    )


def test_lazy_preserves_nested_structure_and_enum_without_descriptions():
    reg = _reg()
    reg.register(_NestedTool())
    row = {d["name"]: d for d in reg.schemas(lazy=True)}["workflow_like"]
    steps = row["parameters"]["properties"]["steps"]
    assert steps["type"] == "array"
    item = steps["items"]
    assert item["type"] == "object"
    assert item["required"] == ["task"]
    assert item["properties"]["task"] == {"type": "string"}
    assert item["properties"]["executor"]["enum"] == ["local", "remote"]
    assert item["properties"]["depends_on"]["items"] == {"type": "string"}
    assert "description" not in json.dumps(row["parameters"], ensure_ascii=False)

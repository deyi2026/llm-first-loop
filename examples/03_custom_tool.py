"""示例 03：自定义工具注册（给 AI 添加新能力）.

实现工具协议（name/description/parameters/execute）→ registry.register →
AI 在循环中即可自主调用（工具 schema 自动注入 system prompt）。

运行: python examples/03_custom_tool.py（使用 Fake 引擎演示注册与执行，无需 key）
"""

from __future__ import annotations

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.tools.registry import ToolRegistry


class GreetTool:
    """打招呼工具：演示最小工具协议."""

    name = "greet"
    description = "向指定名字打招呼。何时用: 用户要求问候某人时。何时不用: 与问候无关的请求。失败对策: name 必填。"
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "要问候的名字"}},
        "required": ["name"],
    }

    def execute(self, **kwargs) -> ToolResult:
        name = str(kwargs.get("name", "")).strip()
        if not name:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'name'",
                tool_call_id="",
                tool_name=self.name,
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"你好，{name}！",
            tool_call_id="",
            tool_name=self.name,
        )


def main() -> None:
    registry = ToolRegistry()
    registry.register(GreetTool())

    # 直接执行（程序侧）
    r = registry.execute(ToolCall(id="tc-1", name="greet", arguments={"name": "世界"}))
    print(f"执行结果: [{r.status.value}] {r.content}")

    # schema 注入（LLM 侧可见的工具定义）
    print(f"工具 schema: {registry.schemas()}")


if __name__ == "__main__":
    main()

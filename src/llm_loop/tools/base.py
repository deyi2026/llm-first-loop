"""Tool 协议与 ToolResult（design.md §2.2.2.2 / §2.1.3.3 机制二）.

- Tool 协议: 注册新工具只需实现 name/description/parameters/execute（FR-TOOL-03）
- ToolResult 五态如实反馈: success/failure/error/timeout/blocked（数据约束 6.2）
- ToolResult.to_message: 构造为带 tool_call_id 绑定的 tool 消息
"""

from __future__ import annotations

from typing import Any, Protocol

from llm_loop.core.message import ToolResult, ToolResultStatus

__all__ = ["Tool", "ToolResult", "ToolResultStatus"]


class Tool(Protocol):
    """工具协议（FR-TOOL-03）：核心循环只依赖注册表接口，不感知工具细节."""

    name: str
    description: str
    parameters: dict  # JSON Schema（约束 C4，类型严格）

    def execute(self, **kwargs: Any) -> ToolResult: ...

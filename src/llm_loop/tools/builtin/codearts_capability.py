"""CodeArtsCapabilityTool 能力声明工具（design.md §2.2.2.10）.

向 LLM 如实暴露适用场景与局限性（spec §5.5）。不夸大能力不隐瞒局限。
"""

from __future__ import annotations

from typing import Any

from llm_loop.codearts.scheduler import CodeArtsScheduler
from llm_loop.core.message import ToolResult, ToolResultStatus


class CodeArtsCapabilityTool:
    name = "codearts_capability"
    description = (
        "声明 CodeArts 子 Agent 调度能力的适用场景与局限性。何时用: 需了解 CodeArts"
        "委派能力边界（适用场景/局限性/远端依赖/非完备调度声明）以决策是否委派。"
        "返回: 含适用场景/局限性/远端依赖/非完备声明四段，不夸大能力不隐瞒局限。"
    )
    parameters = {"type": "object", "properties": {}}

    def __init__(self, scheduler: CodeArtsScheduler) -> None:
        self._scheduler = scheduler

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=self._scheduler.declare_capability(),
            tool_call_id="",
            tool_name=self.name,
        )

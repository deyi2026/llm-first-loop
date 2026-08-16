"""CodeArtsCancelTool 取消工具（design.md §2.2.2.10）.

取消远端执行。execute 委托 CodeArtsScheduler.cancel。
取消失败如实标注"取消失败，远端任务可能仍在执行"不臆造已取消（spec §5.4.3.4）。
"""

from __future__ import annotations

from typing import Any

from llm_loop.codearts.scheduler import CodeArtsScheduler
from llm_loop.core.message import ToolResult, ToolResultStatus


class CodeArtsCancelTool:
    name = "codearts_cancel"
    description = (
        "取消 CodeArts 子 Agent 远端执行。何时用: 需取消在途委派任务（如超时/不再需要）。"
        "何时不用: 任务已终态。注意: 取消失败会如实标注'远端任务可能仍在执行'不臆造已取消。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "handle_id": {
                "type": "string",
                "description": "执行句柄标识（codearts_dispatch 返回的 handle_id）",
            },
        },
        "required": ["handle_id"],
    }

    def __init__(self, scheduler: CodeArtsScheduler) -> None:
        self._scheduler = scheduler

    def execute(self, **kwargs: Any) -> ToolResult:
        handle_id = str(kwargs.get("handle_id", "")).strip()
        if not handle_id:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'handle_id'",
                tool_call_id="",
                tool_name=self.name,
            )
        return self._scheduler.cancel(handle_id)

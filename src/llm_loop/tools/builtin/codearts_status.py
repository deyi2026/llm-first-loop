"""CodeArtsStatusTool 状态查询工具（design.md §2.2.2.10）.

查询在途委派状态。execute 委托 CodeArtsScheduler.query_status。
"""

from __future__ import annotations

from typing import Any

from llm_loop.codearts.scheduler import CodeArtsScheduler
from llm_loop.core.message import ToolResult, ToolResultStatus


class CodeArtsStatusTool:
    name = "codearts_status"
    description = (
        "查询 CodeArts 子 Agent 委派执行状态。何时用: 需查询在途委派任务的当前状态"
        "（本地状态/远端状态/最后同步时间）。何时不用: 句柄已终态。"
        "注意: 状态可能短暂滞后于远端（轮询间隔下限 5s）；状态未知如实标注不臆造。"
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
        return self._scheduler.query_status(handle_id)

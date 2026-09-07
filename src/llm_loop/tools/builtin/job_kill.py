"""Explicitly terminate a process-local background execution handle."""

from __future__ import annotations

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.tools.builtin.job_registry import JobRegistry


class JobKillTool:
    name = "job_kill"
    description = (
        "终止本进程仍持有句柄的后台任务。重启后仅有orphaned durable事实时不会自动重连/kill。"
        "何时用: 用户明确要停止仍在本进程运行的后台任务。失败对策: 不存在、已结束、"
        "非当前会话或orphaned时如实返回。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "后台任务 ID（后台启动回执中的 job_id）"},
        },
        "required": ["job_id"],
    }

    def execute(self, **kwargs) -> ToolResult:
        job_id = str(kwargs.get("job_id", "") or "").strip()
        if not job_id:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'job_id'",
                tool_call_id="",
                tool_name=self.name,
            )
        requester = current_session_id.get() or ""
        ok, detail = JobRegistry.instance().kill(
            job_id,
            requester_session_id=requester,
            reason="user_job_kill",
        )
        if not ok:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[无法终止] job_id={job_id}: {detail}",
                tool_call_id="",
                tool_name=self.name,
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[已终止] job_id={job_id}（{detail}）",
            tool_call_id="",
            tool_name=self.name,
        )

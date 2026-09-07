"""Query process-local or durable background execution facts."""

from __future__ import annotations

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.tools.builtin.job_registry import JobRegistry


class JobOutputTool:
    name = "job_output"
    description = (
        "查询后台任务当前状态与本进程已收集输出；重启后若只有durable事实会如实显示orphaned/终态，"
        "不会自动重连或重启。何时用: execute_command/dsh_task 后台启动后查询进度/结果。"
        "失败对策: job_id 不存在或不属于当前会话时如实返回。"
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
        snapshot = JobRegistry.instance().snapshot(job_id, session_id=requester)
        if snapshot is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[任务不存在或无权访问] job_id={job_id}",
                tool_call_id="",
                tool_name=self.name,
            )
        state = str(snapshot.get("state") or "unknown")
        exit_code = snapshot.get("exit_code")
        local = bool(snapshot.get("local_handle"))
        durable = bool(snapshot.get("durable"))
        state_durable = bool(snapshot.get("state_durable", durable))
        cancel_requested = bool(snapshot.get("cancel_requested"))
        state_label = (
            f"done (exit={exit_code})" if state in {"completed", "failed"} else state
        )
        raw_output = snapshot.get("output")
        output = list(raw_output) if isinstance(raw_output, list) else []
        body = "\n".join(str(x) for x in output) if output else "（暂无本进程输出）"
        command = str(snapshot.get("command") or "")
        command_line = f"\n命令: {command}" if command else ""
        content = (
            f"[任务 {job_id}] 状态={state_label} local_handle={str(local).lower()} "
            f"durable={str(durable).lower()} state_durable={str(state_durable).lower()} "
            f"cancel_requested={str(cancel_requested).lower()} auto_reclaim=false"
            f"{command_line}\n--- 输出（{len(output)} 行）---\n{body}"
        )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=content,
            tool_call_id="",
            tool_name=self.name,
        )

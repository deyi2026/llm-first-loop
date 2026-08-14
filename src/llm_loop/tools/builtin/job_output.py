"""基础工具: 查询后台任务输出（EVO-20260814: Harness ctx.jobs 对齐）.

与 execute_command(run_in_background=true) 配合：查询任务状态与已收集输出。
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.tools.builtin.job_registry import JobRegistry


class JobOutputTool:
    name = "job_output"
    description = (
        "查询后台任务（execute_command run_in_background=true 启动的）当前状态与已收集输出。"
        "何时用: 后台任务启动后查询进度/结果。"
        "何时不用: 前台命令直接看 execute_command 返回值即可。"
        "失败对策: job_id 不存在会如实返回失败。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "后台任务 ID（execute_command 返回的 job_id）"},
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
        entry = JobRegistry.instance().get(job_id)
        if entry is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[任务不存在] job_id={job_id}（可能从未启动或进程已退出）",
                tool_call_id="",
                tool_name=self.name,
            )
        with entry._lock:
            output = list(entry.output)
            done, exit_code, killed = entry.done, entry.exit_code, entry.killed
        if killed:
            state = "killed"
        elif done:
            state = f"done (exit={exit_code})"
        else:
            state = "running"
        body = "\n".join(output) if output else "（暂无输出）"
        content = (
            f"[任务 {job_id}] 状态={state}\n命令: {entry.command}\n"
            f"--- 输出（{len(output)} 行）---\n{body}"
        )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=content,
            tool_call_id="",
            tool_name=self.name,
        )

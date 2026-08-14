"""基础工具: 终止后台任务（EVO-20260814: Harness ctx.jobs 对齐）.

与 execute_command(run_in_background=true) 配合：终止运行中的任务（SIGTERM）。
"""

from __future__ import annotations

import os
import signal

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.tools.builtin.job_registry import JobRegistry


class JobKillTool:
    name = "job_kill"
    description = (
        "终止后台任务（execute_command run_in_background=true 启动的）。"
        "何时用: 后台任务不再需要/已失控/想提前结束时。"
        "何时不用: 任务已完成无需终止。"
        "失败对策: job_id 不存在或任务已完成会如实返回失败。"
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
                content=f"[任务不存在] job_id={job_id}",
                tool_call_id="",
                tool_name=self.name,
            )
        with entry._lock:
            done, killed = entry.done, entry.killed
        if done or killed:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[任务已结束] job_id={job_id}（{'已完成' if done else '已终止'}），无需 kill",
                tool_call_id="",
                tool_name=self.name,
            )
        proc = entry.proc
        if proc is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[任务无进程句柄] job_id={job_id}",
                tool_call_id="",
                tool_name=self.name,
            )
        try:
            # 进程组终止（start_new_session 确保 kill 波及 shell 及其全部子进程，防孤儿）
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()  # 兜底：单进程 SIGTERM
        with entry._lock:
            entry.killed = True
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[已终止] job_id={job_id}（SIGTERM 已发送）",
            tool_call_id="",
            tool_name=self.name,
        )

"""统一相邻代理通信工具：parent<->direct child，sender 由运行时推导。"""

from __future__ import annotations

from llm_loop.core.message import ToolResult, ToolResultStatus


class AgentMessageTool:
    """唯一模型可见的 agent-to-agent 通信操作。"""

    name = "agent_message"
    description = (
        "向直接相邻代理发送消息。sender 由运行时根据当前 session 推导，模型不可指定。"
        "允许 child→直接 parent（target_id='parent'）以及 parent→仍运行的直接 child；"
        "self/兄弟/隔代/已结束目标均拒绝。消息是通信，不代表任务结算或成功。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "target_id": {
                "type": "string",
                "description": "直接相邻目标 session id；子代理向父级发送时可用 'parent'",
            },
            "content": {
                "type": "string",
                "maxLength": 4000,
                "description": "要发送的进展、事实、纠偏指令或其他通信内容；最多 4000 字符",
            },
        },
        "required": ["target_id", "content"],
    }

    def __init__(self, runner) -> None:
        self._runner = runner

    def execute(self, **kwargs) -> ToolResult:
        target_id = str(kwargs.get("target_id", "") or "").strip()
        content = str(kwargs.get("content", "") or "").strip()
        ok, detail, _resolved_target = self._runner.send_current_message(target_id, content)
        if not ok:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[状态: failure] agent_message 未发送：{detail}",
                tool_call_id="",
                tool_name=self.name,
            )

        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[状态: success] {detail}",
            tool_call_id="",
            tool_name=self.name,
        )

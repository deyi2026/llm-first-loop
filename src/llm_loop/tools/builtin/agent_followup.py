"""对已终止的直接 child 发起有界续话（EVO-20260914-e6b8aa22）。"""

from __future__ import annotations

from llm_loop.core.message import ToolResult, ToolResultStatus


class AgentFollowupTool:
    """终止 child 的同会话、同深度、受限轮数续话。

    与 spawn_subagent 的区别：不新开会话、保留 child 原有全部上下文；
    程序侧硬预算（每 child 2 次 / 每父会话 4 次 / 终止后 15 分钟窗口），
    超限显式拒绝并提示改用 spawn_subagent，不静默新开。
    """

    name = "agent_followup"
    # 复合工具：内部是受限子代理循环（≤6 轮，每层 LLM/tool 调用有各自超时），
    # 外层 60s 原子超时对它在事实上不安全（线程池杀不掉 worker），显式豁免。
    registry_timeout_s = None
    description = (
        "对已终止的自己直接 child 发起有界续话：同会话（保留 child 全部历史），"
        "同深度，本轮最多 6 轮。预算由程序硬记账：每 child 最多 2 次、"
        "每父会话最多 4 次、child 终止后 15 分钟内有效；超限/过期/非直接 child/运行中"
        "均显式拒绝，此时改用 spawn_subagent 新开 child 并在 task 中携带必要上下文。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "child_id": {
                "type": "string",
                "description": "已终止的直接 child_id（spawn_subagent 返回，subagent_result 确认已完成）",
            },
            "instruction": {
                "type": "string",
                "description": "续话新指令：明确的追加任务/修正要求，不是重复原任务",
            },
        },
        "required": ["child_id", "instruction"],
    }

    def __init__(self, runner) -> None:
        self._runner = runner

    def execute(self, **kwargs) -> ToolResult:
        child_id = str(kwargs.get("child_id", "") or "").strip()
        instruction = str(kwargs.get("instruction", "") or "").strip()
        if not child_id:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] child_id 不能为空",
                tool_call_id="",
                tool_name=self.name,
            )
        if not instruction:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] instruction 不能为空；续话必须携带明确的新指令",
                tool_call_id="",
                tool_name=self.name,
            )
        ok, detail, result = self._runner.followup_current(child_id, instruction)
        if not ok:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[状态: failure] agent_followup: {detail}",
                tool_call_id="",
                tool_name=self.name,
            )
        outcome = str(getattr(result, "outcome", "") or "")
        parts = [
            f"[续话] {detail} outcome={outcome}",
            f"rounds={getattr(result, 'rounds', 0)} "
            f"tokens_in={getattr(result, 'tokens_in', 0)} tokens_out={getattr(result, 'tokens_out', 0)}",
        ]
        parts.append("[子代理回答]")
        parts.append(str(getattr(result, "final_answer", "") or ""))
        return ToolResult(
            status=ToolResultStatus.SUCCESS if outcome == "completed" else ToolResultStatus.FAILURE,
            content="\n".join(parts),
            tool_call_id="",
            tool_name=self.name,
        )

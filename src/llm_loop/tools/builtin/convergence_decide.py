"""Legacy convergence decision tool kept for replay/tests; not factory-registered."""

from __future__ import annotations

from llm_loop.core.message import ToolResult, ToolResultStatus


class ConvergenceDecideTool:
    name = "convergence_decide"
    description = (
        "仅在运行时收敛边界临时出现。若当前事实仍不足以直接回答用户，显式声明继续并写出"
        "一个具体 unresolved 事实；若可以收口，不调用本工具，直接回答。程序不替你判断任务完成。"
        "无进展或重复时可调整策略或直接回答；待办均依赖外部事件时可输出单条状态后停止动作；"
        "需要规则依据时可按需水合 RULE-AI-xx。"
    )
    compact_description = (
        "收敛边界继续声明：仅当仍有具体未解决事实时 decision=continue + unresolved；"
        "可以收口则直接回答，不调用。无进展/重复时可换策略或直接回答；待办依赖外部事件时"
        "输出单条状态后停止动作；需规则依据时按需水合 RULE-AI-xx。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["continue", "conclude"],
                "description": "continue=仍有具体未解决事实；conclude=我判定可以收口（自陈，非完成裁决）。",
            },
            "unresolved": {
                "type": "string",
                "maxLength": 1200,
                "description": "仍需继续的具体未解决事实/缺失证据；仅 continue 必填，conclude 可空；不得写泛化的“继续检查”。",
            },
        },
        "required": ["decision"],
    }

    def execute(self, **kwargs) -> ToolResult:
        decision = str(kwargs.get("decision") or "").strip().lower()
        unresolved = str(kwargs.get("unresolved") or "").strip()
        if decision == "continue":
            if not unresolved:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[参数错误] continue 必须给出非空 unresolved 事实。",
                    tool_call_id="",
                    tool_name=self.name,
                )
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="convergence_decision=continue; boundary_released=true",
                tool_call_id="",
                tool_name=self.name,
            )
        if decision == "conclude":
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=(
                    "convergence_decision=conclude; boundary_released=true; "
                    "非完成裁决=模型自陈，程序不作完成判定"
                ),
                tool_call_id="",
                tool_name=self.name,
            )
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] decision 仅允许 continue|conclude。",
            tool_call_id="",
            tool_name=self.name,
        )

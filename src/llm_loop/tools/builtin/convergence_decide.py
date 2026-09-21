"""Ephemeral model decision tool used only at a mechanical convergence boundary."""

from __future__ import annotations

from llm_loop.core.message import ToolResult, ToolResultStatus


class ConvergenceDecideTool:
    name = "convergence_decide"
    description = (
        "仅在运行时收敛边界临时出现。若当前事实仍不足以直接回答用户，显式声明继续并写出"
        "一个具体 unresolved 事实；若可以收口，不调用本工具，直接回答。程序不替你判断任务完成。"
    )
    compact_description = (
        "收敛边界继续声明：仅当仍有具体未解决事实时 decision=continue + unresolved；"
        "可以收口则直接回答，不调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["continue"]},
            "unresolved": {
                "type": "string",
                "maxLength": 1200,
                "description": "仍需继续的具体未解决事实/缺失证据；不得写泛化的“继续检查”。",
            },
        },
        "required": ["decision", "unresolved"],
    }

    def execute(self, **kwargs) -> ToolResult:
        decision = str(kwargs.get("decision") or "").strip().lower()
        unresolved = str(kwargs.get("unresolved") or "").strip()
        if decision != "continue":
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] decision 仅允许 continue；若要收口请直接回答用户。",
                tool_call_id="",
                tool_name=self.name,
            )
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

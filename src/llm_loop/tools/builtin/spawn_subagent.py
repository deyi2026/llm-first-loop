"""基础工具: spawn_subagent 递归子代理（EVO 第五项，参考 OpenRSI 四算子 + 执行反馈）.

LLM 自主拆解复杂任务 → 委派子代理（独立会话隔离 + 受限工具集 + 真实执行）→ 结果回传整合。
递归深度由 runner 控制（depth 参数自动自增，超限拒绝）。
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult, ToolResultStatus


class SpawnSubAgentTool:
    name = "spawn_subagent"
    description = (
        "派生子代理执行子任务（递归子代理，EVO 第五项）。何时用: 复杂任务需要拆解成独立子任务"
        "（如独立调研/独立计算/并行验证）时，委派给子代理在隔离上下文中真实执行，结果回传后整合。"
        "何时不用: 任务简单直接处理时；子任务依赖父上下文大量状态时。"
        "注意: 子代理可用工具受限（read_file/execute_command/web_fetch/web_search/get_tool_schema/edit_file），"
        "不可改文件/改架构；递归深度上限 3，超限会拒绝。"
        "失败对策: 深度超限/轮数超限会如实标注，请在父级整合已有结果。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "子任务描述（明确目标/约束/期望产出，越具体越好）",
            },
            "context": {
                "type": "string",
                "description": "父上下文要点（可选；子代理无需父全量历史，只传必要背景）",
            },
            "inherit": {
                "type": "boolean",
                "description": "fork 继承（可选，默认 false）：自动注入父会话最近上下文切片"
                               "（原文非摘要，条数/字符预算截断），省手动提取；可与 context 并存",
            },
            "depth": {
                "type": "integer",
                "description": "递归深度（内部自增，父调用不传；子代理再委派时自动+1）",
            },
        },
        "required": ["task"],
    }

    def __init__(self, runner) -> None:
        self._runner = runner

    def execute(self, **kwargs) -> ToolResult:
        task = str(kwargs.get("task", "")).strip()
        context = str(kwargs.get("context", "")).strip()
        inherit = bool(kwargs.get("inherit", False))
        depth = int(kwargs.get("depth", 0) or 0)

        if not task:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'task'（子任务描述）",
                tool_call_id="",
                tool_name=self.name,
            )

        try:
            result = self._runner.run(task=task, context=context, depth=depth, inherit=inherit)
        except Exception as exc:  # noqa: BLE001 — 子代理异常如实回传
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"[状态: error] 子代理执行异常: {type(exc).__name__}: {exc}",
                tool_call_id="",
                tool_name=self.name,
            )

        # 如实构造回执（五态 + 轨迹摘要 + 深度/截断标注）
        status = (
            ToolResultStatus.FAILURE if result.refused else ToolResultStatus.SUCCESS
        )
        parts = [
            f"[状态: {status.value}] 子代理完成（depth={result.depth}, rounds={result.rounds}, "
            f"tools={len(result.tool_calls)}, tokens_in={result.tokens_in}, tokens_out={result.tokens_out}）",
        ]
        if result.truncated:
            parts.append("[子代理截断] 已达轮数上限，结果未完整收敛")
        if result.reports:
            # DSH 借鉴 022-B: 中途报告摘要（最多 3 条防刷屏）
            parts.append(f"[中途报告 {len(result.reports)} 条]")
            for rep in result.reports[-3:]:
                parts.append(f"  - {rep[:150]}")
        if result.tool_calls:
            trace = ", ".join(
                f"{t['name']}:{t['status']}" for t in result.tool_calls[:10]
            )
            parts.append(f"[工具轨迹] {trace}")
        parts.append("[子代理回答]")
        parts.append(result.final_answer)
        return ToolResult(
            status=status,
            content="\n".join(parts),
            tool_call_id="",
            tool_name=self.name,
        )

"""基础工具: spawn_subagent 递归子代理（EVO 第五项，参考 OpenRSI 四算子 + 执行反馈）.

LLM 自主拆解复杂任务 → 启动非阻塞子代理（独立会话隔离 + 父执行域继承 + 真实执行）→
父代理继续决策，可中途 agent_message steer，并用 subagent_result 回收结果。
递归深度由 runner 控制（depth 参数自动自增，超限拒绝）。
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult, ToolResultStatus


class SpawnSubAgentTool:
    name = "spawn_subagent"
    # nonblocking start 只负责登记 handle + 启线程，不再同步等待 child。
    registry_timeout_s = 5.0
    description = (
        "非阻塞启动子代理并立即返回 child_id。何时用: 复杂任务需要拆解成独立子任务"
        "（如独立调研/独立计算/并行验证）时，让 child 在隔离上下文中后台真实执行，父代理继续决策。"
        "何时不用: 任务简单直接处理时；子任务依赖父上下文大量状态时。"
        "启动成功后可用 agent_message(target_id=child_id, ...) 中途纠偏；"
        "用 subagent_result(child_id, wait_seconds=...) 查询/等待报告与最终结果。"
        "注意: 子代理继承父代理当前工具执行域；父域完整时 child 可用完整已注册工具面，"
        "父域显式受限时 child 不得扩权。各工具自身安全/授权/并发写保护继续生效。"
        "递归深度由程序计算，上限 3，超限会拒绝。"
        "spawn 成功只代表 child 已启动，不代表子任务完成；最终 outcome 以 subagent_result 为准。"
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
            "acceptance": {
                "type": "array",
                "items": {"type": "string"},
                "description": "验收清单（可选，对齐 dsh_task 协议 v2）：子代理完成时逐项自检输出"
                "完成/未完成/原因——分歧显性化，父级保留最终裁决权。给验收标准后"
                "子代理结果更可靠（自检倒逼收敛，避免'答非所问'）。",
            },
        },
        "required": ["task"],
    }

    def __init__(self, runner) -> None:
        self._runner = runner

    def terminate_session(self, session_id: str) -> None:
        """父会话 Stop 向正在运行的 child/descendants 传播取消。"""
        self._runner.cancel_parent(session_id)

    def execute(self, **kwargs) -> ToolResult:
        task = str(kwargs.get("task", "")).strip()
        context = str(kwargs.get("context", "")).strip()
        inherit = bool(kwargs.get("inherit", False))
        # depth 属程序控制面：顶层 parent→0，子代理内再次 spawn→当前真实 depth+1。
        # 历史/模型即使携带 depth 参数也明确忽略，不能由模型绕过 max_depth。
        from llm_loop.subagent.runner import next_subagent_depth

        depth = next_subagent_depth()
        from llm_loop.tools.arg_coerce import coerce_str_list

        acceptance = coerce_str_list(kwargs.get("acceptance"))

        if not task:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'task'（子任务描述）",
                tool_call_id="",
                tool_name=self.name,
            )

        try:
            started = self._runner.start(
                task=task, context=context, depth=depth, inherit=inherit, acceptance=acceptance
            )
        except Exception as exc:  # noqa: BLE001 — 子代理异常如实回传
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"[状态: error] 子代理执行异常: {type(exc).__name__}: {exc}",
                tool_call_id="",
                tool_name=self.name,
            )

        if not bool(started.get("accepted")):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    f"[状态: failure] child_state={started.get('state', 'failed')} "
                    f"depth={started.get('depth', depth)} {started.get('detail', '')}"
                ).strip(),
                tool_call_id="",
                tool_name=self.name,
            )

        child_id = str(started.get("child_id", ""))
        parts = [
            f"[状态: success] child_state=running child_id={child_id} depth={started.get('depth', depth)}",
            "子代理已在后台启动；本回执不是任务结算。",
            f"中途纠偏: agent_message(target_id='{child_id}', content='...')",
            f"查询/等待: subagent_result(child_id='{child_id}', wait_seconds=0..30)",
        ]
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="\n".join(parts),
            tool_call_id="",
            tool_name=self.name,
        )

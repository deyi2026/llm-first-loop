"""CodeArtsDispatchTool 委派工具（design.md §2.2.2.9）.

LLM 经此工具发起 CodeArts 子 Agent 委派。execute 委托 CodeArtsScheduler.dispatch。
复用 ToolRegistry 统一包裹（参数校验/灾难性安全/审批/五态构造/审计）。
"""

from __future__ import annotations

import uuid
from typing import Any

from llm_loop.codearts.models import DispatchTask, Priority, RiskLevel, TimeoutBudget
from llm_loop.codearts.scheduler import CodeArtsScheduler
from llm_loop.core.message import ToolResult, ToolResultStatus


class CodeArtsDispatchTool:
    name = "codearts_dispatch"
    description = (
        "委派任务给 CodeArts 子 Agent 执行（远端平台能力：流水线/代码检查/部署/仓库操作）。"
        "何时用: 需华为云 CodeArts 平台能力的重任务（流水线触发/代码检查/部署/远端仓库操作）、"
        "需远端执行环境的任务、长时异步任务。"
        "何时不用: 本地轻量子任务用 spawn_subagent；任务简单直接处理。"
        "注意: 高风险动作（生产部署/制品发布/仓库强推/环境销毁）需人工审批，"
        "无人值守模式默认拒绝；灾难性动作经本地安全硬边界前置检查拦截。"
        "失败对策: 回执五态（success/failure/blocked/timeout/error），"
        "CodeArts 不可用时本地 LLM 可感知并改用本地子代理。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": "任务描述（明确目标/约束/期望产出，越具体越好）",
            },
            "context_summary": {
                "type": "string",
                "description": "上下文要点（可选；委派给远端子 Agent 的必要背景）",
            },
            "timeout_budget": {
                "type": "object",
                "properties": {
                    "connect_s": {"type": "integer", "description": "连接超时（秒）"},
                    "call_s": {"type": "integer", "description": "调用超时（秒）"},
                    "exec_s": {"type": "integer", "description": "执行超时（秒，单任务最大时长）"},
                },
                "description": "三级超时预算（可选；缺省用配置默认）",
            },
            "expected_output_format": {
                "type": "string",
                "description": "期望产出格式（可选）",
            },
            "priority": {
                "type": "string",
                "enum": ["low", "normal", "high"],
                "description": "优先级（可选，缺省 normal）",
            },
            "risk_level": {
                "type": "string",
                "enum": ["normal", "catastrophic"],
                "description": "风险等级（可选，缺省 normal；catastrophic 需人工审批）",
            },
            "trace_id": {
                "type": "string",
                "description": "链路追踪标识（可选；缺省程序自动生成）",
            },
        },
        "required": ["task_description"],
    }

    def __init__(self, scheduler: CodeArtsScheduler) -> None:
        self._scheduler = scheduler

    def execute(self, **kwargs: Any) -> ToolResult:
        task_description = str(kwargs.get("task_description", "")).strip()
        if not task_description:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'task_description'（任务描述）",
                tool_call_id="",
                tool_name=self.name,
            )

        # 构造 TimeoutBudget
        timeout_raw = kwargs.get("timeout_budget") or {}
        timeout_budget = TimeoutBudget(
            connect_s=int(timeout_raw.get("connect_s", 10)) if isinstance(timeout_raw, dict) else 10,
            call_s=int(timeout_raw.get("call_s", 30)) if isinstance(timeout_raw, dict) else 30,
            exec_s=int(timeout_raw.get("exec_s", 1800)) if isinstance(timeout_raw, dict) else 1800,
        )

        # 构造 Priority
        priority_raw = str(kwargs.get("priority", "normal")).strip().lower()
        try:
            priority = Priority(priority_raw)
        except ValueError:
            priority = Priority.NORMAL

        # 构造 RiskLevel
        risk_raw = str(kwargs.get("risk_level", "normal")).strip().lower()
        try:
            risk_level = RiskLevel(risk_raw)
        except ValueError:
            risk_level = RiskLevel.NORMAL

        trace_id = str(kwargs.get("trace_id", "")).strip() or str(uuid.uuid4())

        task = DispatchTask(
            task_description=task_description,
            trace_id=trace_id,
            context_summary=str(kwargs.get("context_summary", "")).strip(),
            timeout_budget=timeout_budget,
            expected_output_format=str(kwargs.get("expected_output_format", "")).strip(),
            priority=priority,
            risk_level=risk_level,
        )

        # 会话 ID 经 contextvar 优先 + 显式注入回退
        session_id = ""
        try:
            from llm_loop.core.run_context import current_session_id

            session_id = current_session_id.get() or ""
        except Exception:  # noqa: BLE001
            pass

        return self._scheduler.dispatch(task, session_id=session_id)

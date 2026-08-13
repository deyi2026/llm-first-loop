"""架构自省工具与 AI 自主修正工具（design.md §2.1.4.3/2.1.4.4 / 模块 J）.

边界说明（M11）: 本模块为 LLM 可见的工具注册/分派/呈现层（architecture_status/search_archive/search_records/adjust_strategy/retry_tool/refresh_config）;
统一检索实现层在 introspection/search.py（RecordSearcher，被本模块消费）。

- architecture_status: LLM 拉取架构运行状态（通道一）
- 修正工具集（P0 三个）: adjust_strategy / retry_tool / refresh_config（clear_state 已于 M11 移除）
  铁律: 程序如实反馈、LLM 决策；边界校验（白名单/范围/非破坏性）；
  不可绕过灾难性安全边界（FR-SAFE-01）；审计落盘 self_correction_log.jsonl。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.status import ArchitectureStatusProvider

# M16 拆分: submit_evolution / self_evaluate 工具定义（引自独立模块，避免重复维护）
from llm_loop.introspection.tools_eval import (
    SELF_EVALUATE_TOOL_DEF as _SELF_EVALUATE_TOOL_DEF,
)
from llm_loop.introspection.tools_evolution import (
    SUBMIT_EVOLUTION_TOOL_DEF as _SUBMIT_EVOLUTION_TOOL_DEF,
)

# M17 FR-REVIEW-AI-01: evolution_complete 工具定义（引自独立模块，避免重复维护）
from llm_loop.introspection.tools_exec_complete import (
    EVOLUTION_COMPLETE_TOOL_DEF as _EVOLUTION_COMPLETE_TOOL_DEF,
)

# M48（design §5.3）: model_catalog / switch_model 工具定义（引自独立模块，避免重复维护）
from llm_loop.introspection.tools_model import (
    MODEL_CATALOG_TOOL_DEF as _MODEL_CATALOG_TOOL_DEF,
)
from llm_loop.introspection.tools_model import (
    SWITCH_MODEL_TOOL_DEF as _SWITCH_MODEL_TOOL_DEF,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class CorrectionContext:
    """修正工具可作用的运行时状态（由主程序装配注入）."""

    # adjust_strategy 白名单参数（显式排除安全边界配置，FR-SAFE-01 不可绕过）
    # M57-M59 配置面收敛: memory_top_k / extract_interval_msgs / retrieve_semantic_top_k
    strategy_whitelist: dict[str, dict] = field(
        default_factory=lambda: {
            "max_iterations": {"type": "integer", "min": 5, "max": 500},
            "timeout_s": {"type": "number", "min": 5, "max": 600},
            "history_budget": {"type": "integer", "min": 1000, "max": 1000000},
            "memory_top_k": {"type": "integer", "min": 1, "max": 50},
            "extract_interval_msgs": {"type": "integer", "min": 5, "max": 200},
            "retrieve_semantic_top_k": {"type": "integer", "min": 1, "max": 100},
        }
    )
    # 运行时策略参数（可被 adjust_strategy 修改，由循环消费）
    strategy: dict = field(default_factory=dict)
    # 重试执行器: retry_tool(tool_name, arguments) -> ToolResult
    retry_executor: Callable[[str, dict], ToolResult] | None = None
    # 配置重载器: refresh_config() -> str
    refresh_executor: Callable[[], str] | None = None
    # 当前会话（T22/T23: search_archive/search_records 会话过滤）
    session_id: str = ""
    runtime: Any | None = None  # M12 T50
    evolution_store: Any | None = None  # M12 T52: EvolutionStore（submit_evolution）
    evolve_local_exec: int = (
        0  # M12 深化 T55: 演进执行权限级别 0=仅建议/1=白名单局部执行/2=全面执行
    )
    evolve_exec_whitelist: str = ""  # M12 深化 T60: 执行白名单（逗号分隔，级别 1 时生效）
    evaluator: Any | None = None  # M12 深化 T64: SelfEvaluator（self_evaluate）
    # M48（design §5.3）: 会话级模型覆盖 + 模型客户端池
    # model_pool 注入后, model_catalog / switch_model 工具可用
    # session_set_override(model_ref) 回调: switch_model 写入新 override（None=清除）
    model_pool: Any | None = None  # ModelClientPool（M48 新增；None 时工具回执"工具不可用"）
    session_set_override: Callable[[str | None], None] | None = None
    session_model_override: str | None = None  # 当前会话级覆盖（switch_model 审计 from→to 用）
    summarizer: Any | None = None  # R2: search_archive(with_summary=true) 时生成 LLM 语义摘要


class CorrectionToolRegistry:
    """修正工具注册/边界校验/执行/审计（design.md §2.1.4.4）.

    T22/T23: 扩展为架构自省 + 修正 + 检索工具的统一注册表
    （architecture_status / 修正工具 / search_archive / search_records）。
    """

    def __init__(
        self,
        ctx: CorrectionContext,
        *,
        audit_dir: str | Path | None = None,
        status_provider: ArchitectureStatusProvider | None = None,
        archive_store: Any | None = None,
    ) -> None:
        self.ctx = ctx
        self._audit_dir = Path(audit_dir) if audit_dir else None
        self._status = status_provider
        self._archive = archive_store  # ArchiveStore（T22 压缩档案检索）
        self._search_records_fn: Callable[..., list[dict]] | None = None  # T23: 统一检索实现
        self._experience_store: Any | None = None  # P1-2: ExperienceStore 注入通道

    # ── 工具定义（供 LLM 可见）──
    def tool_defs(self) -> list[dict]:
        return [
            {
                "name": "architecture_status",
                "description": "查询架构运行状态（当前循环阶段/动作轨迹/工具历史/异常/配置）。何时用: 需要了解系统运行情况、定位问题时。architecture_config 维度含演进状态摘要（evolution_summary: executing/pending_review 计数），可一站式感知演进待办。何时不用: 需要执行修正动作（调参数/重试/重载）时用 adjust_strategy/retry_tool/refresh_config。失败对策: 某维度数据不可用会如实标注“读取失败”，请基于已有维度继续分析。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dimensions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "按需裁剪的状态维度，可选: current_phase/action_trace/tool_history/message_flow/memory_state/context_usage/exception_log/architecture_config",
                        }
                    },
                },
            },
            {
                "name": "search_archive",
                "description": "检索被压缩的历史/超长工具结果（信息未丢失，全部另存在压缩档案）。何时用: 上下文压缩后需要找回早期信息、或工具结果被截断需要看完整内容时。何时不用: 需要检索所有历史记录（动作轨迹/异常/记忆/演进）用 search_records。失败对策: 未检索到匹配会如实返回空，请调整关键词或改用 search_records。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "关键词（匹配摘要/关键事实/关键路径/原文）",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "最多返回条数（默认 10，上限 50）",
                        },
                        "role": {
                            "type": "string",
                            "enum": ["user", "assistant", "tool", "system"],
                            "description": "按角色过滤",
                        },
                        "tool_name": {
                            "type": "string",
                            "description": "按来源工具名过滤（如 read_file）",
                        },
                        "with_summary": {
                            "type": "boolean",
                            "description": "是否对命中条目生成 LLM 语义摘要（默认 false，返回首尾摘要）。设 true 时每条命中多一次 LLM 调用（增加计费），用于需要语义理解被压内容的场景。",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "search_records",
                "description": "统一检索历史运行记录/记忆/压缩档案（可查可检索，不限于当前上下文）。何时用: 需要回溯动作轨迹/异常/修正记录/记忆/被压缩信息/演进建议/执行审计/自我评估/故障自愈/参数调整/配置变更/进程版本/飞书审计时。kind 可选: action_trace/exception_log/self_correction_log/declaration_check/memory/memory_extract/archive/selfheal/param_adjust/evolution/evolution_exec/self_eval/change_log/proc_versions/feishu_audit/experience/all。何时不用: 只查压缩档案用 search_archive；当前上下文已有信息不必检索。失败对策: 检索失败/无结果会如实返回，请调整 kind/关键词重试。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": [
                                "action_trace",
                                "exception_log",
                                "self_correction_log",
                                "declaration_check",
                                "memory",
                                "memory_extract",
                                "archive",
                                "selfheal",
                                "param_adjust",
                                "evolution",
                                "evolution_exec",
                                "self_eval",
                                "change_log",
                                "proc_versions",
                                "feishu_audit",
                                "experience",
                                "all",
                            ],
                        },
                        "query": {
                            "type": "string",
                            "description": "关键词（空则返回该 kind 最近记录）",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "最多返回条数（默认 10，上限 50）",
                        },
                    },
                    "required": ["kind"],
                },
            },
            {
                "name": "adjust_strategy",
                "description": "调整后续循环策略参数（白名单: max_iterations/timeout_s/history_budget）。何时用: 发现循环参数不合理时（异常率偏高/停滞/预算占用逼近上限，可先经 architecture_status 自查）。何时不用: 需要重试失败工具用 retry_tool；需重载配置用 refresh_config。失败对策: 参数非法/超出全局硬上限（500）会如实返回失败原因，请按引导更正参数。不可修改安全边界配置。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "strategy": {"type": "object", "description": "要调整的参数 dict"}
                    },
                    "required": ["strategy"],
                },
            },
            {
                "name": "retry_tool",
                "description": "对指定工具按提供参数重新执行（重新走完整执行包裹，含安全校验与超时）。何时用: 工具上次失败、且失败属瞬态（网络超时/上游 5xx）或参数已更正时重试。何时不用: 连续同参失败应停止重试、换路径（见停滞自主调整）；需调整策略参数用 adjust_strategy。失败对策: 重试仍失败会如实返回失败回执，请基于失败信息调整参数或换路径继续尝试一次；仍失败再如实说明。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tool_name": {"type": "string"},
                        "arguments": {"type": "object"},
                    },
                    "required": ["tool_name", "arguments"],
                },
            },
            # M16 拆分: submit_evolution / self_evaluate 工具定义（引自独立模块，避免重复维护）
            _SUBMIT_EVOLUTION_TOOL_DEF,
            _SELF_EVALUATE_TOOL_DEF,
            {
                "name": "refresh_config",
                "description": "重载程序自身配置（配置文件/环境变量）。何时用: 配置文件/环境变量变更后需要生效时。何时不用: 需要调整运行参数（max_iterations 等白名单）用 adjust_strategy；未变更配置时无需重载。失败对策: 重载失败会如实返回原因，程序保持旧配置继续运行，请核对配置后重试。",
                "parameters": {"type": "object", "properties": {}},
            },
            # M17 FR-REVIEW-AI-01: evolution_complete 工具（定义引自独立模块，避免重复维护）
            _EVOLUTION_COMPLETE_TOOL_DEF,
            # M48（design §5.3）: model_catalog / switch_model 工具（model_pool 未注入时仍注册 schema，
            # 执行时如实回执'工具不可用'，LLM 仍可感知工具存在）
            _MODEL_CATALOG_TOOL_DEF,
            _SWITCH_MODEL_TOOL_DEF,
            # P1-2: 经验库沉淀/生命周期工具（AI 优先：程序仅通道，提取/判断归 AI）
            {
                "name": "save_experience",
                "description": "沉淀工程经验到经验库（跨会话复用）。何时用: 产生可复用的工程经验（根因分析/修复模式/架构决策）时。何时不用: 闲聊/过程性内容。失败对策: 必填字段缺失返回参数错误，IO 异常返回程序异常，均如实不伪造成功。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "经验标题（生成文件名 slug）"},
                        "scenario": {"type": "string", "description": "触发场景"},
                        "solution": {"type": "string", "description": "解决方案"},
                        "root_cause": {"type": "string", "description": "根因（可选）"},
                        "evidence": {"type": "string", "description": "证据引用（可选）"},
                        "tags": {"type": "array", "items": {"type": "string"}, "description": "标签（可选）"},
                        "source": {"type": "object", "description": "来源溯源（可选）"},
                        "body": {"type": "string", "description": "经验正文原文（可选）"},
                    },
                    "required": ["title", "scenario", "solution"],
                },
            },
            {
                "name": "refine_experience",
                "description": "经验生命周期流转（归档/失效/恢复）。何时用: 经验过时/失效/需恢复时。何时不用: 经验仍有效时无需流转。失败对策: 经验不存在返回未找到，action 非法返回参数错误，均如实。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "experience_id": {"type": "string", "description": "经验标识（文件名去 .md）"},
                        "action": {"type": "string", "enum": ["archive", "invalidate", "restore"]},
                    },
                    "required": ["experience_id", "action"],
                },
            },
        ]

    def execute(self, name: str, arguments: dict) -> ToolResult:
        """执行修正/检索工具（边界校验 → 执行 → 审计 → 如实回传）."""
        if name == "architecture_status":
            return self._run_status(arguments)
        if name == "search_archive":
            return self._run_search_archive(arguments)
        if name == "search_records":
            return self._run_search_records(arguments)
        if name == "adjust_strategy":
            return self._run_adjust_strategy(arguments)
        if name == "retry_tool":
            return self._run_retry(arguments)
        if name == "submit_evolution":
            return self._run_submit_evolution(arguments)
        if name == "self_evaluate":
            return self._run_self_evaluate(arguments)
        if name == "evolution_complete":
            return self._run_evolution_complete(arguments)
        if name == "save_experience":
            return self._run_save_experience(arguments)
        if name == "refine_experience":
            return self._run_refine_experience(arguments)
        if name == "refresh_config":
            return self._run_refresh()
        if name == "model_catalog":
            return self._run_model_catalog(arguments)
        if name == "switch_model":
            return self._run_switch_model(arguments)
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[修正工具不存在] 未注册的修正工具 '{name}'",
            tool_call_id="",
            tool_name=name,
        )

    # ── M16 审计（FR-AUDIT-AI-14）: 状态/检索工具实现拆分至 tools_status.py ──
    def _run_status(self, args: dict) -> ToolResult:
        from llm_loop.introspection.tools_status import run_status

        return run_status(self.ctx, self._status, args)

    def _current_session_id(self) -> str:
        from llm_loop.introspection.tools_status import current_session_id

        return current_session_id(self.ctx)

    def _run_search_archive(self, args: dict) -> ToolResult:
        from llm_loop.introspection.tools_status import run_search_archive

        return run_search_archive(
            self.ctx, self._archive, args, self._current_session_id,
            summarizer=getattr(self.ctx, "summarizer", None),
        )

    def _run_search_records(self, args: dict) -> ToolResult:
        from llm_loop.introspection.tools_status import run_search_records

        return run_search_records(self.ctx, self._search_records_fn, args, self._current_session_id)

    def _run_save_experience(self, args: dict) -> ToolResult:
        """save_experience: 沉淀工程经验到经验库（P1-2，AI 优先：程序仅通道）。"""
        if self._experience_store is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[程序异常] 经验库未装配（experience_store 未注入）",
                tool_call_id="",
                tool_name="save_experience",
            )
        from llm_loop.introspection.tools_experience import run_save_experience

        content = run_save_experience(
            self._experience_store,
            title=args.get("title", ""),
            scenario=args.get("scenario", ""),
            solution=args.get("solution", ""),
            root_cause=args.get("root_cause", ""),
            evidence=args.get("evidence", ""),
            tags=args.get("tags") or [],
            source=args.get("source") or {},
            body=args.get("body", ""),
        )
        status = ToolResultStatus.SUCCESS if content.startswith("[save_experience]") else ToolResultStatus.FAILURE
        return ToolResult(status=status, content=content, tool_call_id="", tool_name="save_experience")

    def _run_refine_experience(self, args: dict) -> ToolResult:
        """refine_experience: 经验生命周期流转（P1-2）。"""
        if self._experience_store is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[程序异常] 经验库未装配（experience_store 未注入）",
                tool_call_id="",
                tool_name="refine_experience",
            )
        from llm_loop.introspection.tools_experience import run_refine_experience

        content = run_refine_experience(
            self._experience_store,
            experience_id=args.get("experience_id", ""),
            action=args.get("action", ""),
        )
        status = (
            ToolResultStatus.SUCCESS if content.startswith("[refine_experience]") else ToolResultStatus.FAILURE
        )
        return ToolResult(status=status, content=content, tool_call_id="", tool_name="refine_experience")

    def _current_params(self) -> dict:
        from llm_loop.introspection.tools_status import current_params

        return current_params(self.ctx)

    def _run_adjust_strategy(self, args: dict) -> ToolResult:
        """adjust_strategy: 调整白名单内循环策略参数（FR-SAFE-01 边界不可修改）."""
        proposed = args.get("strategy")
        if not isinstance(proposed, dict) or not proposed:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 'strategy' 必须为非空 JSON 对象，如 {\"max_iterations\": 30}",
                tool_call_id="",
                tool_name="adjust_strategy",
            )
        for key, val in proposed.items():
            spec = self.ctx.strategy_whitelist.get(key)
            if spec is None:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=f"[参数越界] 参数 '{key}' 不在白名单内（可选: {', '.join(self.ctx.strategy_whitelist)}）。注意安全边界配置不可修改（FR-SAFE-01）。",
                    tool_call_id="",
                    tool_name="adjust_strategy",
                )
            if spec["type"] == "integer" and not (
                isinstance(val, int) and not isinstance(val, bool)
            ):
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=f"[参数错误] '{key}' 需要整数，收到 {type(val).__name__}",
                    tool_call_id="",
                    tool_name="adjust_strategy",
                )
            if spec["type"] == "number" and not isinstance(val, (int, float)):
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=f"[参数错误] '{key}' 需要数值，收到 {type(val).__name__}",
                    tool_call_id="",
                    tool_name="adjust_strategy",
                )
            if not (spec["min"] <= val <= spec["max"]):
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=f"[参数越界] '{key}' 需在 [{spec['min']}, {spec['max']}] 范围内，收到 {val}",
                    tool_call_id="",
                    tool_name="adjust_strategy",
                )
        # M18 AA2: PARAM-03 单轮频次预算（schema 校验全部通过后检查，非法参数不消耗频次）
        if self.ctx.runtime is not None and not self.ctx.runtime.can_adjust():
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    "[参数调整频次超限] 事实: 本轮回合参数调整已达上限（"
                    f"{self.ctx.runtime.adjust_count()} 次，PARAM-03）。"
                    "原因: 防止参数抖动影响循环稳定。"
                    "建议: 下轮再调，或收敛为一次综合调整；不阻断你继续其他决策。"
                ),
                tool_call_id="",
                tool_name="adjust_strategy",
            )
        before = dict(self.ctx.strategy)
        self.ctx.strategy.update(proposed)
        if self.ctx.runtime is not None:
            self.ctx.runtime.record_adjust_multi(proposed)
        self._audit("adjust_strategy", proposed, "success")
        diffs = ", ".join(f"{k}: {before.get(k, '<默认>')} → {v}" for k, v in proposed.items())
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=(
                f"[已生效] 循环策略已更新: {{{diffs}}}（生效范围: 当前 run 起全部后续轮次；"
                f"受全局硬上限 500 约束）。\n当前生效值: {json.dumps(self._current_params(), ensure_ascii=False)}"
            ),
            tool_call_id="",
            tool_name="adjust_strategy",
        )

    def _run_retry(self, args: dict) -> ToolResult:
        """retry_tool: 对指定工具按提供参数重新执行."""
        tool_name = str(args.get("tool_name", "")).strip()
        arguments = args.get("arguments") or {}
        if not tool_name:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少 'tool_name'（要重试的工具名）",
                tool_call_id="",
                tool_name="retry_tool",
            )
        if not isinstance(arguments, dict):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 'arguments' 必须为 JSON 对象",
                tool_call_id="",
                tool_name="retry_tool",
            )
        if self.ctx.retry_executor is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[重试不可用] 重试执行器未装配（主程序未注入 retry_executor）",
                tool_call_id="",
                tool_name="retry_tool",
            )
        result = self.ctx.retry_executor(tool_name, arguments)
        self._audit(
            "retry_tool", {"tool_name": tool_name, "arguments": arguments}, result.status.value
        )
        return result

    # ── M16 审计（FR-AUDIT-AI-14）: submit_evolution/self_evaluate 实现拆分至独立模块 ──
    def _run_submit_evolution(self, args: dict) -> ToolResult:
        from llm_loop.introspection.tools_evolution import run_submit_evolution

        # M19 FIX-05: 传 audit_dir 供 eval_id 存在性校验（None 则跳过校验）
        return run_submit_evolution(
            self.ctx,
            self._audit,
            args,
            audit_dir=str(self._audit_dir) if self._audit_dir else None,
        )

    def _run_self_evaluate(self, args: dict) -> ToolResult:
        from llm_loop.introspection.tools_eval import run_self_evaluate

        return run_self_evaluate(self.ctx, self._audit, args)

    def _run_evolution_complete(self, args: dict) -> ToolResult:
        """evolution_complete: 登记演进执行完成（M17 FR-REVIEW-AI-01 闭环）."""
        from llm_loop.introspection.evolution_exec import EvolutionExecutor
        from llm_loop.introspection.tools_exec_complete import run_evolution_complete

        if self.ctx.evolution_store is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[演进建议不可用] 事实: 演进建议存储未装配。原因: EVOLVE_ENABLED=0。建议: 检查配置。",
                tool_call_id="",
                tool_name="evolution_complete",
            )
        executor = EvolutionExecutor(
            exec_level=int(getattr(self.ctx, "evolve_local_exec", 0) or 0),
            store=self.ctx.evolution_store,
            audit_dir=self._audit_dir,
        )
        return run_evolution_complete(self.ctx, executor, self._audit, args)

    def _run_refresh(self) -> ToolResult:
        if self.ctx.refresh_executor is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[重载不可用] 配置重载执行器未装配",
                tool_call_id="",
                tool_name="refresh_config",
            )
        detail = self.ctx.refresh_executor()
        self._audit("refresh_config", {}, "success")
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[已重载] {detail}",
            tool_call_id="",
            tool_name="refresh_config",
        )

    # ── M48（design §5.3）: model_catalog / switch_model 工具薄壳委托 ──
    def _run_model_catalog(self, args: dict) -> ToolResult:
        """model_catalog: 列出可用模型 + 当前会话模型（只读）.

        实现拆分至 introspection/tools_model.py（按 M17 evolution_complete 模式）,
        本壳仅做上下文转发 + 审计记录。
        """
        from llm_loop.introspection.tools_model import run_model_catalog

        result = run_model_catalog(
            self.ctx,
            self.ctx.model_pool,
            self.ctx.session_model_override,
        )
        self._audit("model_catalog", args, result.status.value)
        return result

    def _run_switch_model(self, args: dict) -> ToolResult:
        """switch_model: 切换会话级模型覆盖 + 审计落盘.

        实现拆分至 introspection/tools_model.py, 本壳仅做上下文转发;
        写入失败由 tools_model.run_switch_model 内部捕获并如实回执。
        """
        from llm_loop.introspection.tools_model import run_switch_model

        result = run_switch_model(
            self.ctx,
            self.ctx.model_pool,
            self.ctx.session_set_override,
            self._audit,
            args,
        )
        # tools_model.run_switch_model 内部已审计成功路径；此处补一次失败审计（如未记）
        # 简化: 不重复审计（tools_model 已处理 success 路径; 失败路径不污染审计）
        return result

    def _audit(self, tool_name: str, arguments: dict, result_status: str) -> None:
        """修正动作审计落盘（AI 可溯源，design.md §2.3.2）."""
        if self._audit_dir is None:
            return
        try:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "id": f"COR-{datetime.now(UTC).strftime('%Y%m%d')}",
                "ts": _now(),
                "tool_name": tool_name,
                "arguments": arguments,
                "result_status": result_status,
            }
            with (self._audit_dir / "self_correction_log.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # fail-open

    def audit_fallback_event(
        self,
        *,
        from_model: str,
        to_model: str,
        reason: str,
        result_status: str,
        detail: str = "",
    ) -> None:
        """M49（design §5.4）: 模型降级事件审计落盘（独立子方法便于 loop.py 直接调用）.

        与 _audit 一致落 self_correction_log.jsonl（AI 可经 search_records(kind=self_correction_log) 检索）;
        tool_name 固定为 "model_fallback", 便于检索时与 switch_model 等工具区分.

        Args:
            from_model: 原模型引用（如 "deepseek/deepseek-v4-flash" 或裸名）
            to_model: 降级后模型引用（同上格式；"all_failed" 表示链全失败）
            reason: 失败原因（如 "429 限流", "网络不可达", "5xx"）
            result_status: "success"（单次降级成功） / "all_failed"（链全失败汇总）/ "skipped"（严格模式不降级）
            detail: 详情（如各候选失败原因汇总, 仅 result_status="all_failed" 时有意义）
        """
        if self._audit_dir is None:
            return
        try:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "id": f"COR-{datetime.now(UTC).strftime('%Y%m%d')}",
                "ts": _now(),
                "tool_name": "model_fallback",
                "arguments": {
                    "from": from_model,
                    "to": to_model,
                    "reason": reason,
                    "detail": detail,
                },
                "result_status": result_status,
            }
            with (self._audit_dir / "self_correction_log.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # fail-open

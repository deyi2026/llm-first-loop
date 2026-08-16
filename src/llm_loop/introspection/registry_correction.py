"""AI 自主修正类工具注册（T2，design §2.1.2-5.2）.

承载: adjust_strategy / retry_tool / refresh_config
边界校验（白名单/范围/非破坏性）+ 审计落盘，FR-SAFE-01 不可绕过。
"""

from __future__ import annotations

import json
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.registry_host import RegistryHost

_ADJUST_STRATEGY_TOOL_DEF: dict[str, Any] = {
    "name": "adjust_strategy",
    "description": "调整后续循环策略参数（白名单: max_iterations/timeout_s/history_budget）。何时用: 发现循环参数不合理时（异常率偏高/停滞/预算占用逼近上限，可先经 architecture_status 自查）。何时不用: 需要重试失败工具用 retry_tool；需重载配置用 refresh_config。失败对策: 参数非法/超出全局硬上限（500）会如实返回失败原因，请按引导更正参数。不可修改安全边界配置。",
    "parameters": {
        "type": "object",
        "properties": {
            "strategy": {"type": "object", "description": "要调整的参数 dict"}
        },
        "required": ["strategy"],
    },
}

_RETRY_TOOL_DEF: dict[str, Any] = {
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
}

_REFRESH_CONFIG_TOOL_DEF: dict[str, Any] = {
    "name": "refresh_config",
    "description": "重载程序自身配置（配置文件/环境变量）。生效范围（EVO-20260815-b3339561）: LLM 凭据（api_key/base_url/model/协议）与模型目录（providers.json）原地同步即时生效；其余配置为启动时装配（冻结），变更需重启进程生效；运行参数（max_iterations 等白名单）用 adjust_strategy 即时调整。何时用: LLM 凭据/模型目录变更后需要生效时。何时不用: 未变更配置时无需重载。失败对策: 重载失败会如实返回原因，程序保持旧配置与旧凭据继续运行，请核对配置后重试。",
    "parameters": {"type": "object", "properties": {}},
}


def tool_defs() -> list[dict]:
    return [_ADJUST_STRATEGY_TOOL_DEF, _RETRY_TOOL_DEF, _REFRESH_CONFIG_TOOL_DEF]


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "adjust_strategy":
        return _run_adjust_strategy(args, host)
    if name == "retry_tool":
        return _run_retry(args, host)
    if name == "refresh_config":
        return _run_refresh(host)
    return None


def _run_adjust_strategy(args: dict, host: RegistryHost) -> ToolResult:
    proposed = args.get("strategy")
    if not isinstance(proposed, dict) or not proposed:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] 'strategy' 必须为非空 JSON 对象，如 {\"max_iterations\": 30}",
            tool_call_id="",
            tool_name="adjust_strategy",
        )
    whitelist = host.ctx.strategy_whitelist
    for key, val in proposed.items():
        spec = whitelist.get(key)
        if spec is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[参数越界] 参数 '{key}' 不在白名单内（可选: {', '.join(whitelist)}）。注意安全边界配置不可修改（FR-SAFE-01）。",
                tool_call_id="",
                tool_name="adjust_strategy",
            )
        if spec["type"] == "integer" and not (isinstance(val, int) and not isinstance(val, bool)):
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
    runtime = host.ctx.runtime
    if runtime is not None and not runtime.can_adjust():
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=(
                "[参数调整频次超限] 事实: 本轮回合参数调整已达上限（"
                f"{runtime.adjust_count()} 次，PARAM-03）。"
                "原因: 防止参数抖动影响循环稳定。"
                "建议: 下轮再调，或收敛为一次综合调整；不阻断你继续其他决策。"
            ),
            tool_call_id="",
            tool_name="adjust_strategy",
        )
    before = dict(host.ctx.strategy)
    host.ctx.strategy.update(proposed)
    if runtime is not None:
        runtime.record_adjust_multi(proposed)
    host.audit("adjust_strategy", proposed, "success")
    diffs = ", ".join(f"{k}: {before.get(k, '<默认>')} → {v}" for k, v in proposed.items())
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=(
            f"[已生效] 循环策略已更新: {{{diffs}}}（生效范围: 当前 run 起全部后续轮次；"
            f"受全局硬上限 500 约束）。\n当前生效值: {json.dumps(host.current_params(), ensure_ascii=False)}"
        ),
        tool_call_id="",
        tool_name="adjust_strategy",
    )


def _run_retry(args: dict, host: RegistryHost) -> ToolResult:
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
    retry_executor = host.ctx.retry_executor
    if retry_executor is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[重试不可用] 重试执行器未装配（主程序未注入 retry_executor）",
            tool_call_id="",
            tool_name="retry_tool",
        )
    result = retry_executor(tool_name, arguments)
    host.audit("retry_tool", {"tool_name": tool_name, "arguments": arguments}, result.status.value)
    return result


def _run_refresh(host: RegistryHost) -> ToolResult:
    refresh_executor = host.ctx.refresh_executor
    if refresh_executor is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[重载不可用] 配置重载执行器未装配",
            tool_call_id="",
            tool_name="refresh_config",
        )
    detail = refresh_executor()
    host.audit("refresh_config", {}, "success")
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=f"[已重载] {detail}",
        tool_call_id="",
        tool_name="refresh_config",
    )

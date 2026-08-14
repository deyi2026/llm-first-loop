"""架构自省类工具注册（T2，design §2.1.2-5.2）.

承载: architecture_status / search_archive / search_records / search_docs
执行实现委托至 introspection/tools_status.py + tools_docs.py（既有拆分）。
"""

from __future__ import annotations

from typing import Any

from llm_loop.core.message import ToolResult
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.tools_docs import SEARCH_DOCS_TOOL_DEF

_ARCHITECTURE_STATUS_TOOL_DEF: dict[str, Any] = {
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
}

_SEARCH_ARCHIVE_TOOL_DEF: dict[str, Any] = {
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
}

_SEARCH_RECORDS_TOOL_DEF: dict[str, Any] = {
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
}


def tool_defs() -> list[dict]:
    return [
        _ARCHITECTURE_STATUS_TOOL_DEF,
        _SEARCH_ARCHIVE_TOOL_DEF,
        _SEARCH_RECORDS_TOOL_DEF,
        SEARCH_DOCS_TOOL_DEF,
    ]


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "architecture_status":
        from llm_loop.introspection.tools_status import run_status

        return run_status(host.ctx, host.status_provider, args)

    if name == "search_archive":
        from llm_loop.introspection.tools_status import run_search_archive

        return run_search_archive(
            host.ctx,
            host.archive_store,
            args,
            host.current_session_id,
            summarizer=getattr(host.ctx, "summarizer", None),
        )

    if name == "search_records":
        from llm_loop.introspection.tools_status import run_search_records

        return run_search_records(host.ctx, host.search_records_fn, args, host.current_session_id)

    if name == "search_docs":
        from llm_loop.introspection.tools_docs import run_search_docs

        return run_search_docs(host.search_docs_fn, args)

    return None

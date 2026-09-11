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
    "description": "读取 LFL 运行时架构状态（循环阶段/动作轨迹/工具历史/缓存/异常/配置），用于诊断程序运行；architecture_config 含 evolution_summary 演进待办/状态摘要。它不是用户任务 Goal/Task 的事实源：当前活动目标用 get_goal，任务图用 task_frontier。需要执行参数/重试/重载修正时再用 adjust_strategy/retry_tool/refresh_config。",
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
    "description": "检索被压缩的历史/超长工具结果（信息未丢失，全部另存在压缩档案）。何时用: 上下文压缩后需要找回早期信息、或工具结果被截断需要看完整内容时。何时不用: 需要检索所有历史记录（动作轨迹/异常/记忆/演进）用 search_records。失败对策: 未检索到匹配会如实返回空，请调整关键词或改用 search_records。命中为历史记录：采信前先对照时间锚点（list_evidence/event_stream）；字面命中≠当前所指，过时命中仅作背景。",
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
                "description": "兼容参数。true 只显示既有 archive index summary + preview，并明确 projection_complete=false；不再对 preview 发起隐藏 LLM 摘要调用。需要全文摘要时先恢复 exact source，再由 source_synopsis 保存模型自写摘要。",
            },
        },
        "required": ["query"],
    },
}

_SEARCH_RECORDS_TOOL_DEF: dict[str, Any] = {
    "name": "search_records",
    "description": "检索持久记录与按需知识索引：运行审计、memory、archive、experience、lesson、self_eval、resolved/truncated episode、synopsis、rule 等。episode 表示已解决/退休的对话片段，不代表当前活动任务；experience=正向/legacy 经验 discovery，lesson=失败/未验证/已证伪教训；两者 exact 内容均用 stable experience:<id> 水合。当前 Goal/Task 状态用 get_goal/task_frontier。历史命中仍需检查时间与当前适用性；method 为 Method Learning 索引。",
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
                    "lesson",
                    "episode",
                    "rule",
                    "file_effect",
                    "synopsis",
                    "method",
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


_EVENT_STREAM_TOOL_DEF: dict[str, Any] = {
    "name": "event_stream",
    "description": "统一事件流视图（EVO-20260814，对齐 Harness Trajectory）：把分散的 append-only 审计流（action_trace/exception_log/self_correction/evolution/param_adjust 等）按时间序合并为单一轨迹流。何时用: 需要看'系统最近发生了什么'的连贯轨迹（回溯/审计/交接/排障）而非按 kind 分别检索时。何时不用: 只查单类记录或压缩档案时，应使用对应的专用检索能力。失败对策: 无事件/审计目录不存在会如实返回空视图（不伪造），请核对 audit_dir 配置。",
    "parameters": {
        "type": "object",
        "properties": {
            "streams": {
                "type": "string",
                "description": "逗号分隔的流名子集；'all' = 全部流（默认）。可选: action_trace/exception_log/self_correction/evolution/param_adjust/declaration_check/self_eval/memory_extract/proc_versions/feishu_audit/evolution_exec",
            },
            "query": {
                "type": "string",
                "description": "关键词过滤（匹配摘要字段，空 = 不过滤）",
            },
            "limit": {
                "type": "integer",
                "description": "返回条数上限（按时间倒序取最近 N 条，默认 50）",
            },
            "since": {
                "type": "string",
                "description": "ISO 时间下界（只返回 ts >= since 的事件，空 = 不限）。如 '2026-08-14T00:00:00'",
            },
        },
    },
}


def tool_defs() -> list[dict]:
    return [
        _ARCHITECTURE_STATUS_TOOL_DEF,
        _SEARCH_ARCHIVE_TOOL_DEF,
        _SEARCH_RECORDS_TOOL_DEF,
        _EVENT_STREAM_TOOL_DEF,
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

    if name == "event_stream":
        from llm_loop.introspection.tools_status import run_event_stream

        return run_event_stream(host.search_records_fn, args)

    if name == "search_docs":
        from llm_loop.introspection.tools_docs import run_search_docs

        return run_search_docs(host.search_docs_fn, args)

    return None

"""经验库类工具注册（T2，design §2.1.2-5.2）.

承载: save_experience / refine_experience
AI 优先：程序仅通道，提取/判断归 AI。
"""

from __future__ import annotations

from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.registry_host import RegistryHost

_SAVE_EXPERIENCE_TOOL_DEF: dict[str, Any] = {
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
}

_REFINE_EXPERIENCE_TOOL_DEF: dict[str, Any] = {
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
}


def tool_defs() -> list[dict]:
    return [_SAVE_EXPERIENCE_TOOL_DEF, _REFINE_EXPERIENCE_TOOL_DEF]


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "save_experience":
        return _run_save_experience(args, host)
    if name == "refine_experience":
        return _run_refine_experience(args, host)
    return None


def _run_save_experience(args: dict, host: RegistryHost) -> ToolResult:
    store = host.experience_store
    if store is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[程序异常] 经验库未装配（experience_store 未注入）",
            tool_call_id="",
            tool_name="save_experience",
        )
    from llm_loop.introspection.tools_experience import run_save_experience

    content = run_save_experience(
        store,
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


def _run_refine_experience(args: dict, host: RegistryHost) -> ToolResult:
    store = host.experience_store
    if store is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[程序异常] 经验库未装配（experience_store 未注入）",
            tool_call_id="",
            tool_name="refine_experience",
        )
    from llm_loop.introspection.tools_experience import run_refine_experience

    content = run_refine_experience(
        store,
        experience_id=args.get("experience_id", ""),
        action=args.get("action", ""),
    )
    status = ToolResultStatus.SUCCESS if content.startswith("[refine_experience]") else ToolResultStatus.FAILURE
    return ToolResult(status=status, content=content, tool_call_id="", tool_name="refine_experience")

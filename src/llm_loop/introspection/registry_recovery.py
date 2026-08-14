"""故障恢复类工具注册（T2，design §2.1.2-5.2）.

承载: recover_from_backup
AI 优先：是否恢复/恢复哪条/是否覆盖冲突归 AI 决策，程序仅提供恢复通道。
"""

from __future__ import annotations

from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.registry_host import RegistryHost

_RECOVER_FROM_BACKUP_TOOL_DEF: dict[str, Any] = {
    "name": "recover_from_backup",
    "description": (
        "从备份归档恢复未落盘数据到正式位置。何时用: 经 architecture_status 查询发现 "
        "recovery 维度有待恢复备份（pending_count>0），且自主判断需要恢复"
        "（如会话历史丢失影响后续对话/记忆统计偏移影响排序）时。"
        "何时不用: 无待恢复备份/备份已过期/正式位置已有更新数据且不愿覆盖。"
        "失败对策: 备份不存在/损坏/冲突会如实返回，不假装成功。"
        "AI 优先: 是否恢复/恢复哪条/是否覆盖冲突归 AI 决策，程序仅提供恢复通道。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "backup_id": {
                "type": "string",
                "description": "备份标识（文件名: <source_id>.<timestamp>.<target_type>.pending.json）",
            },
            "on_conflict": {
                "type": "string",
                "enum": ["abort", "overwrite"],
                "default": "abort",
                "description": "正式位置已有数据时策略: abort 不覆盖（默认）/overwrite 覆盖（显式决策）",
            },
        },
        "required": ["backup_id"],
    },
}


def tool_defs() -> list[dict]:
    return [_RECOVER_FROM_BACKUP_TOOL_DEF]


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "recover_from_backup":
        channel = host.recovery_channel
        if channel is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[程序异常] 恢复通道未装配（recovery_channel 未注入）",
                tool_call_id="",
                tool_name="recover_from_backup",
            )
        from llm_loop.introspection.tools_recovery import run_recover_from_backup

        content = run_recover_from_backup(
            channel,
            backup_id=args.get("backup_id", ""),
            on_conflict=args.get("on_conflict", "abort"),
            sessions_dir=host.recovery_sessions_dir,
            memory_dir=host.recovery_memory_dir,
        )
        status = ToolResultStatus.SUCCESS if content.startswith("[recover_from_backup]") else ToolResultStatus.FAILURE
        return ToolResult(status=status, content=content, tool_call_id="", tool_name="recover_from_backup")
    return None

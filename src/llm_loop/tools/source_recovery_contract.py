"""Shared model-facing semantics for source acquisition versus Evidence recovery.

This module is intentionally descriptive only. It does not suppress, rewrite, or block
source tool calls. The goal is to keep every source tool aligned on the same Evidence
enforce contract while preserving truthful freshness/coverage-driven acquisition.
"""

from __future__ import annotations

from enum import StrEnum


class SourceRecoveryKind(StrEnum):
    PROBEABLE_FILE = "probeable_file"
    COMMAND_SNAPSHOT = "command_snapshot"
    WEB_FETCH = "web_fetch"
    WEB_SEARCH = "web_search"


SHARED_SOURCE_RECOVERY_CONTRACT = (
    "Evidence enforce 模式 source/recovery 契约: source 工具表达 source data request；"
    "probeable source 的 freshness/currentness 只表示 source 版本是否变化，不表示其内容对当前任务/当前生产仍适用；"
    "程序不判断 task applicability，模型结合 acquired_at、来源与当前证据自主判断。"
    "已有 Evidence 覆盖所需内容时可恢复 observation，也可用 list_evidence/search_evidence/read_evidence 精确取回。"
    "EvidenceRef 只是控制面句柄，不是业务内容本身。"
    "若任务要求当前 source 状态而 source-version freshness 不足，则重新获取 source；"
    "若已有 Evidence 未覆盖所需范围，则获取未覆盖 source 范围；显式物理重获取使用 source-specific refresh 参数。"
)

_GUIDANCE = {
    SourceRecoveryKind.PROBEABLE_FILE: (
        "文件语义: verified_current 且覆盖所需范围时恢复已有 Evidence；"
        "stale 且任务要求当前文件状态时重新读取 source；"
        "offset/limit 在 Evidence enforce 模式用于 genuinely 未覆盖的文件范围；"
        "evidence_force_refresh=true 仅用于显式绕过 Evidence 复用并物理重读。"
    ),
    SourceRecoveryKind.COMMAND_SNAPSHOT: (
        "命令语义: 既有命令 Evidence 是历史执行 observation；需要该历史结果时恢复 Evidence；"
        "只有任务要求新的执行或当前运行时状态时才发起新的执行。"
    ),
    SourceRecoveryKind.WEB_FETCH: (
        "网页语义: 既有网页 Evidence 是此前获取的 observation；需要此前内容时恢复 Evidence；"
        "需要当前远端状态或 Evidence 未覆盖的远端内容时重新抓取。"
    ),
    SourceRecoveryKind.WEB_SEARCH: (
        "搜索语义: 既有搜索 Evidence 是此前取得的结果集；需要该历史结果集时恢复 Evidence；"
        "需要当前外部结果时重新搜索。"
    ),
}


def source_recovery_guidance(kind: SourceRecoveryKind) -> str:
    return _GUIDANCE[kind]

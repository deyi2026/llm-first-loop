"""fail-open 数据丢失恢复通道（design §2.2.2 / spec §4-5）.

恢复通道组件：重试编排 → 备份归档 → 恢复通道编排 → AI 触发恢复工具。
程序仅提供恢复通道（手脚）+ 备份状态感知（感官）+ 如实反馈；
恢复决策（恢复哪条/是否覆盖冲突）归 AI（大脑，RULE-AI-00）。
"""

from __future__ import annotations

from llm_loop.recovery.backup import BackupArchive, BackupStore
from llm_loop.recovery.channel import RecoveryChannel, RecoveryReceipt, RecoveryResult
from llm_loop.recovery.policy import RetryPolicy, RetryResult
from llm_loop.recovery.retry import retry_write

__all__ = [
    "BackupArchive",
    "BackupStore",
    "RecoveryChannel",
    "RecoveryReceipt",
    "RecoveryResult",
    "RetryPolicy",
    "RetryResult",
    "retry_write",
]

"""架构事件定义与冷却去重（design.md §2.1.4.3 通道二）.

异常/降级/偏差事件 → 冷却去重 → 构造 [架构上报] 消息（事实+原因+建议）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum

from llm_loop.core.message import Message
from llm_loop.feedback.honesty import architecture_report_message


class ArchitectureEventType(StrEnum):
    """上报事件类型（design.md §2.1.4.3）."""

    EXCEPTION = "exception"  # 异常事件（工具连续失败/LLM 异常/存储故障）
    DEGRADATION = "degradation"  # 降级事件（截断/兜底/标注）
    DEVIATION = "deviation"  # 偏差事件（停滞/声明-回执不一致/修正结果）


@dataclass
class ArchitectureEvent:
    """一次架构上报事件（冷却去重单元）."""

    event_type: ArchitectureEventType
    fact: str  # 事实（如实）
    reason: str  # 原因
    suggestion: str = ""  # 建议下一步（AI 易决策）


class EventReporter:
    """架构事件上报器：冷却去重 + 构造 [架构上报] 消息.

    设计: design.md §2.1.4.3 通道二 —— 冷却期内同类事件合并为
    "已连续发生 N 次"，防止上报刷屏挤占上下文预算。
    """

    def __init__(self, cooldown_s: float = 60.0) -> None:
        self._cooldown_s = cooldown_s
        self._last_report_ts: dict[str, float] = {}
        self._pending_counts: dict[str, int] = {}

    def _key(self, event: ArchitectureEvent) -> str:
        # 以 (类型, 事实) 为去重键：同类同因合并
        return f"{event.event_type.value}:{event.fact[:60]}"

    def should_report(self, event: ArchitectureEvent) -> bool:
        """冷却判定：冷却期内返回 False（由循环选择合并计数）.

        首次调用（该 key 无记录）恒返回 True——冷却表初始 last 不能取 0.0:
        time.monotonic() 从系统启动起算（CI 全新 runner 启动可能不足 60s），
        若取 0.0 会误判"仍在冷却"拦截首次上报（HARNESS-05 flaky 根因:
        eval_trigger 提醒偶发不注入, 本地无法复现, CI 全新 runner 复现）。
        """
        key = self._key(event)
        now = time.monotonic()
        last = self._last_report_ts.get(key)
        if last is None:
            self._last_report_ts[key] = now
            self._pending_counts[key] = 0
            return True
        if now - last >= self._cooldown_s:
            self._last_report_ts[key] = now
            self._pending_counts[key] = 0
            return True
        self._pending_counts[key] = self._pending_counts.get(key, 0) + 1
        return False

    def pending_count(self, event: ArchitectureEvent) -> int:
        return self._pending_counts.get(self._key(event), 0)

    def build_message(self, event: ArchitectureEvent) -> Message:
        """构造 [架构上报] 消息（冷却合并计数）."""
        n = self.pending_count(event)
        suffix = f"（该事件已连续发生 {n + 1} 次）" if n else ""
        return architecture_report_message(
            fact=event.fact + suffix,
            reason=event.reason,
            suggestion=event.suggestion,
        )

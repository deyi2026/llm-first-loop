"""自愈尝试预算 SelfHealBudget（design.md §5.1 / FR-AUTO-SELFHEAL-03）.

防止 AI 对同一故障无限重试：
- 单故障自愈尝试次数上限（默认 3）
- 单轮自愈动作数上限（默认 6）
- 耗尽 → 如实反馈并回退 RULE-AI-04 既有继续路径（不阻断循环）
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BudgetState:
    """单个故障指纹的预算状态."""

    fingerprint: str
    attempts: int = 0
    exhausted: bool = False


class SelfHealBudget:
    """自愈预算控制（单故障 + 单轮双层上限）."""

    def __init__(self, max_attempts: int = 3, max_per_round: int = 6) -> None:
        self._max_attempts = max(1, int(max_attempts))
        self._max_per_round = max(1, int(max_per_round))
        self._states: dict[str, BudgetState] = {}
        self._round_total = 0

    def reset_round(self) -> None:
        """每轮循环开始重置轮级计数（跨轮不累计，允许新轮重新尝试）."""
        self._round_total = 0

    def can_attempt(self, component: str, error_type: str) -> bool:
        """判定是否允许一次自愈尝试.

        Returns:
            True 允许；False 预算耗尽（单故障或单轮超限）。
        """
        fingerprint = f"{component}:{error_type}"
        state = self._states.setdefault(fingerprint, BudgetState(fingerprint=fingerprint))
        if state.exhausted or self._round_total >= self._max_per_round:
            return False
        if state.attempts >= self._max_attempts:
            state.exhausted = True
            return False
        state.attempts += 1
        self._round_total += 1
        return True

    def remaining(self, component: str, error_type: str) -> int:
        """单故障剩余可尝试次数（如实反馈用）."""
        fingerprint = f"{component}:{error_type}"
        state = self._states.get(fingerprint)
        if state is None or state.exhausted:
            return 0
        return max(0, self._max_attempts - state.attempts)

    def reset_all(self) -> None:
        """重置全部预算（新会话/手动 reset 用）."""
        self._states.clear()
        self._round_total = 0

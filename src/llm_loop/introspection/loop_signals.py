"""每轮末信号检测统一壳（M17 FR-REVIEW-AI-02/03 / design §8.2/8.3; M18 AA1 收敛）.

M18 审计（FR-AUDIT3-AI-01）: 参数信号检测（check_param_signal）已移除并移交 RULE-AI-02
"主动管理自查"（AI 经 architecture_status 自查 + adjust_strategy 调整通道）——
程序不再推送参数调整建议。本模块收敛为 eval_trigger + evolution_executing 二合一壳。

消费注入的 eval_trigger_detector/status/settings，显式传参可单测；
依赖 events.py（ArchitectureEvent）/ evaluator.py（EvalTrigger），无环依赖。
"""

from __future__ import annotations

import logging
from typing import Any

from llm_loop.introspection.events import ArchitectureEvent, ArchitectureEventType

logger = logging.getLogger(__name__)


class LoopSignalDetector:
    """每轮末检测注入统一壳（eval_trigger / evolution_executing，零 LLM 往返）."""

    def __init__(
        self,
        *,
        eval_trigger_detector: Any | None = None,  # EvalTriggerDetector
        status: Any | None = None,  # ArchitectureStatusProvider
        settings: Any | None = None,  # Settings（self_eval_remind_enabled 等）
    ) -> None:
        self._eval_trigger_detector = eval_trigger_detector
        self._status = status
        self._settings = settings

    # ── T63/T65 自我评估触发检测（逐字搬移自 loop.py:362-389，M16 收敛语义不变）──
    def check_eval_trigger(
        self,
        sess,
        rounds: int,
        *,
        milestone: bool = False,
    ) -> ArchitectureEvent | None:
        """自我评估触发检测（periodic/milestone 两个确定性触发；命中返回事件）.

        异常触发时机交 AI 自主（RULE-AI-06 子规则 3）；仅提示不强制。
        """
        if self._eval_trigger_detector is None or self._status is None or not self._status.enabled:
            return None
        if not getattr(self._settings, "self_eval_remind_enabled", True):
            return None
        try:
            trigger = self._eval_trigger_detector.check(
                rounds=rounds,
                task_completed=milestone,
            )
            if trigger is None:
                return None
            return ArchitectureEvent(
                event_type=ArchitectureEventType.DEGRADATION,
                fact=trigger.fact,
                reason=trigger.reason,
                suggestion=trigger.suggestion,
            )
        except Exception:
            logger.warning("自我评估触发检测异常（fail-open）", exc_info=True)
            return None

    # ── G2 executing 演进待办检测（design 8.2.2）──
    def check_evolution_executing(self, store) -> ArchitectureEvent | None:
        """executing 演进待办检测（读取失败 fail-open → None，不阻断）.

        有 executing 演进 → 返回 DEVIATION 事件（含 id + evolution_complete 引导）。
        """
        try:
            if store is None:
                return None
            items = store.list(status="executing")
        except OSError:
            return None  # 读取失败 → 不注入提醒（fail-open，DFX-REL-08）
        if not items:
            return None
        first = items[0]
        return ArchitectureEvent(
            event_type=ArchitectureEventType.DEVIATION,
            fact=f"存在 executing 演进建议（{first.get('id', '?')}）",
            reason="已 accepted 且权限允许自动执行，等待落地修正动作",
            suggestion=(
                "可经修正工具落地执行，完成后调用 evolution_complete 登记'已完成 + 验证结论'"
                "（RULE-AI-06 子规则 4）；不执行不阻断本循环。"
            ),
        )

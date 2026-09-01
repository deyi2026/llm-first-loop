"""TerminationController——终止判定 / 信号提醒 / overflow 确定性处理（R9 Phase 5 T6-A）.

B5-W1-02 迁入（design :475 直接消亡类）：_SignalsMixin（signals.py 6 法）+
_OverflowMixin（overflow.py 2 法）方法体逐字平移，``self.`` → ``self._host.``
（宿主 = LoopEngine，跨面依赖 _report/_record_action/_current_context_limit 与
loop_signal_detector/status/evolution_store 仍归宿主）。行为零变化：

- 信号检查面：均仅"事实提醒"不强制，触发判断与决策权归 AI（RULE-AI-10）
- overflow 面：R8.24-B B-D5 确定性处理（compact→end 两段，零 prompt 注入）
- should_terminate 门面（W5-01 RunCoordinator 组装消费）：基于 run 级状态对象的
  纯判定汇总入口（P5-03a 显式状态流事件锚点）

宿主依赖（engine 持有）：loop_signal_detector / status / evolution_store /
_report / _current_context_limit / _record_action / _overflow_* 计数（经桶 shim）。
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (host 属性来自 LoopEngine 混入体系，pyright 无法静态解析，文件级关闭这两条；
#   参数/返回类型等其余检查保留——沿 signals.py/overflow.py 既有豁免口径)

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from llm_loop.llm.errors import LLMError, is_overflow_error

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.loop.runstate import RunState

logger = logging.getLogger(__name__)

# R8.24-B B-D5: overflow 确定性收缩因子（build 链按收紧预算重组 + lossless 归档）
_OVERFLOW_SHRINK_FACTOR = 0.5


class TerminationController:
    """终止域 service：信号提醒 + overflow 确定性处理 + 终止判定门面."""

    def __init__(self, host: LoopEngine) -> None:
        self._host = host

    # ------------------------------------------------------------------
    # should_terminate 门面（R9-P5 接口预留；W5-01 RunCoordinator 接线）
    # ------------------------------------------------------------------
    def should_terminate(self, run_state: RunState) -> tuple[bool, str]:
        """纯判定汇总：轮数耗尽 / 停滞 hard_stop / overflow 二次终止.

        Returns:
            (terminated, reason)——terminated=False 时 reason 为空串。
            本步仅汇总 run_state 显式状态（不动主链控制流，W5-01 接线后生效）。
        """
        if run_state.run_end_reason:
            return True, str(run_state.run_end_reason)
        if run_state.cancel_reason:
            return True, str(run_state.cancel_reason)
        return False, ""

    # ------------------------------------------------------------------
    # overflow 面（迁自 overflow.py::_OverflowMixin，逐字平移）
    # ------------------------------------------------------------------
    def _handle_overflow(
        self,
        exc: LLMError,
        sess,
        model_used: str,
        *,
        model_window: dict[str, Any] | None = None,
    ) -> tuple[str, str | None]:
        """R8.24-B B-D5: overflow runtime 确定性处理（零 prompt 注入）.

        Returns:
            ("reinject", None)   首次 overflow：预算已确定性收缩，主链路 continue
            ("end", text)        第二次 overflow：确定性终止，text 为纯事实终态
            ("not_overflow", None)  非 overflow 错误，主链路继续 fallback 判定
        """
        host = self._host
        if not is_overflow_error(exc):
            return ("not_overflow", None)
        if model_window is None:
            ctx_limit = host._current_context_limit(model_used)
            model_window = {"label": model_used, "context": ctx_limit}
        # 第一次 overflow: 确定性 compaction——预算收缩（build 链重组时超出部分
        # 走既有 lossless 归档：完整另存、信息零丢失、可检索找回；unresolved
        # protocol（assistant 声明↔回执配对）与 active user evidence 不裁断）。
        # compact occurrence 只落 telemetry 事件（B-D5），不注入任何模型可见文本。
        if host._overflow_reinject_count < 1:
            host._overflow_reinject_count += 1
            host._overflow_shrink_factor = _OVERFLOW_SHRINK_FACTOR
            host._record_action(
                "overflow.compact",
                "budget_shrunk",
                f"factor={_OVERFLOW_SHRINK_FACTOR}; "
                f"provider_window={model_window.get('context', '?')}; "
                f"model={model_window.get('label', '?')}; prompt_chars=0",
            )
            return ("reinject", None)
        # 第二次 overflow: 确定性压缩后仍超限 → 直接终止（纯事实终态，B-G3 口径；
        # 无建议性自然语言——不再 instruct 模型检索/换模型/开新会话）。
        host._record_action(
            "overflow.end",
            "terminated",
            f"deterministic_compact_exhausted; provider_window="
            f"{model_window.get('context', '?')}; model={model_window.get('label', '?')}",
        )
        final_text = (
            f"[上下文超限] 事实: 上下文已达 provider 窗口上限"
            f"（模型 {model_window.get('label', model_used)}，"
            f"窗口 {model_window.get('context', '?')}），确定性压缩后仍超限，run 终止。\n"
            f"原因: {exc}。\n"
            f"超出部分已完整归档（信息零丢失，可经检索找回）。"
        )
        return ("end", final_text)

    def _reset_overflow_state(self) -> None:
        """R4→R8.24-B: 每次 run 重置 overflow 计数与预算收缩标志（move 自 engine.py:265）."""
        self._host._overflow_reinject_count = 0
        self._host._overflow_shrink_factor = None

    # ------------------------------------------------------------------
    # 信号面（迁自 signals.py::_SignalsMixin，逐字平移）
    # ------------------------------------------------------------------
    def _append_report_once(self, sess, msg) -> bool:
        """EVO-20260827-f42496bc: 上报注入内容级幂等 append（去重兜底）.

        实证 02:35:21 同轮 flush 7 条架构上报、其中 4 条内容完全相同（冷却 key
        变化/多路径调用穿透 60s 冷却）→ 存储层每轮膨胀重复 system 消息 → 加速
        触顶压缩（压缩轮必 miss）。兜底: 尾部 12 条内已有相同 role+content 的
        注入则跳过 append（首条保留，信息零丢失）。
        """
        if msg is None:
            return False
        msg.metadata = {**(msg.metadata or {}), "injected_system": True}
        _content = msg.content or ""
        for _pm in sess.messages[-12:]:
            _meta = getattr(_pm, "metadata", None) or {}
            if (
                getattr(_pm, "role", "") == "system"
                and _meta.get("injected_system")
                and (getattr(_pm, "content", "") or "") == _content
            ):
                return False
        sess.messages.append(msg)
        return True

    def _check_loop_signals(self, sess, rounds: int) -> None:
        """每轮末信号检测统一入口（M56 收敛，ANALYSIS-20260811）.

        合并自评触发 / executing 演进待办 / pending_review 待审三项检测为一次调用；
        均仅"事实提醒"不强制，触发判断与决策权归 AI（RULE-AI-10 每轮自主检查清单）。
        """
        self._check_eval_trigger(sess, rounds)
        self._check_evolution_executing(sess)
        self._check_pending_review(sess)
        self._check_proc_stale(sess)  # EVO-20260815-69ac0bd0

    def _check_proc_stale(self, sess) -> None:
        """EVO-20260815-69ac0bd0: 进程代码时效提醒（每轮末，仅提示不强制）.

        复用 LoopSignalDetector 冷却（每进程仅提示一次）；无 stale/检测关闭 → 不注入。
        """
        host = self._host
        if host.loop_signal_detector is None:
            return
        event = host.loop_signal_detector.check_proc_stale()
        if event is None:
            return
        msg = host._report(
            event.event_type, fact=event.fact, reason=event.reason, suggestion=event.suggestion
        )
        if msg is not None:
            self._append_report_once(sess, msg)  # EVO-20260827-f42496bc: 内容级幂等 append

    def _check_eval_trigger(self, sess, rounds: int, *, milestone: bool = False) -> None:
        """自我评估触发检测（T63/T65: 每轮末 + run 完成里程碑）.

        M16 审计（FR-AUDIT-AI-04/08）: 只保留 periodic/milestone 两个确定性触发；
        M17 FR-REVIEW-AI-03: 检测逻辑搬移至 introspection/loop_signals.py（薄壳委托）。
        命中且冷却通过 → 注入 [自我评估提醒]（仅提示不强制，EVAL-03；决策权归 LLM）。
        """
        host = self._host
        if host.loop_signal_detector is None:
            return
        event = host.loop_signal_detector.check_eval_trigger(sess, rounds, milestone=milestone)
        if event is None:
            return
        msg = host._report(
            event.event_type, fact=event.fact, reason=event.reason, suggestion=event.suggestion
        )
        if msg is not None:
            self._append_report_once(sess, msg)  # EVO-20260827-f42496bc: 内容级幂等 append

    def _check_evolution_executing(self, sess) -> None:
        """M17 FR-REVIEW-AI-02: executing 演进待办提醒（每轮末，仅提示不强制）.

        复用 EventReporter 冷却（key 含 fact 前缀去重）；无 executing / 读取失败 → 不注入。
        """
        host = self._host
        if host.loop_signal_detector is None or host.status is None or not host.status.enabled:
            return
        event = host.loop_signal_detector.check_evolution_executing(host.evolution_store)
        if event is None:
            return
        msg = host._report(
            event.event_type, fact=event.fact, reason=event.reason, suggestion=event.suggestion
        )
        if msg is not None:
            self._append_report_once(sess, msg)  # EVO-20260827-f42496bc: 内容级幂等 append

    def _check_pending_review(self, sess) -> None:
        """EVO-20260810-86e777d1: pending_review 演进弹窗提醒（每轮末，仅提示不强制）.

        复用 EventReporter 冷却；无 pending_review / 读取失败 → 不注入。
        """
        host = self._host
        if host.loop_signal_detector is None or host.status is None or not host.status.enabled:
            return
        event = host.loop_signal_detector.check_pending_review(host.evolution_store)
        if event is None:
            return
        msg = host._report(
            event.event_type, fact=event.fact, reason=event.reason, suggestion=event.suggestion
        )
        if msg is not None:
            self._append_report_once(sess, msg)  # EVO-20260827-f42496bc: 内容级幂等 append

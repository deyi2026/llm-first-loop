"""TerminationController——硬终止判定与 overflow 资源边界处理。

Rule-first 收正：周期自评、executing 演进、pending-review、进程 stale 等
“何时提醒/该做什么”不再由普通模型主循环扫描。这里仅保留模型无法自行
保证的运行级终止状态与物理上下文 overflow 处理。operator 的人工审批 UI
独立留在 CLI/control surface。
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
    """终止域 service：overflow 物理边界 + 显式 run 终止状态。"""

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
        if host._run_state().overflow_reinject_count < 1:
            host._run_state().overflow_reinject_count += 1
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
        self._host._run_state().overflow_reinject_count = 0
        self._host._overflow_shrink_factor = None

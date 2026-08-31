"""LoopEngine overflow 处理职责 mixin（M53 拆分；R8.24-B B-D5 重设计）.

move 自 engine.py 内联 overflow 段（397-425）与每 run 计数重置（265）：
- is_overflow_error 识别 + runtime 确定性处理（compact/route/end）
- R8.24-B B-D5: 删除"第一次注入 system 消息让 AI 自主决策"路径——
  首次 overflow → 确定性预算收缩（下一轮 build 以收紧预算重组，超出部分走
  既有 lossless 归档链）；第二次 → 直接终止（事实终态）。
  模型可见面零 overflow 教程、零"继续/压缩"询问（B-G1 E17 分量）。
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (mixin 模式: self 属性来自混入类 LoopEngine.__init__，pyright 无法静态解析，故文件级关闭这两条；参数/返回类型等其余检查保留)


from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from llm_loop.llm.errors import LLMError, is_overflow_error

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine

logger = logging.getLogger(__name__)

# R8.24-B B-D5: overflow 确定性收缩因子（build 链按收紧预算重组 + lossless 归档）
_OVERFLOW_SHRINK_FACTOR = 0.5


class _OverflowMixin:
    def _handle_overflow(
        self: LoopEngine,
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
        if not is_overflow_error(exc):
            return ("not_overflow", None)
        if model_window is None:
            ctx_limit = self._current_context_limit(model_used)
            model_window = {"label": model_used, "context": ctx_limit}
        # 第一次 overflow: 确定性 compaction——预算收缩（build 链重组时超出部分
        # 走既有 lossless 归档：完整另存、信息零丢失、可检索找回；unresolved
        # protocol（assistant 声明↔回执配对）与 active user evidence 不裁断）。
        # compact occurrence 只落 telemetry 事件（B-D5），不注入任何模型可见文本。
        if self._overflow_reinject_count < 1:
            self._overflow_reinject_count += 1
            self._overflow_shrink_factor = _OVERFLOW_SHRINK_FACTOR
            self._record_action(
                "overflow.compact",
                "budget_shrunk",
                f"factor={_OVERFLOW_SHRINK_FACTOR}; "
                f"provider_window={model_window.get('context', '?')}; "
                f"model={model_window.get('label', '?')}; prompt_chars=0",
            )
            return ("reinject", None)
        # 第二次 overflow: 确定性压缩后仍超限 → 直接终止（纯事实终态，B-G3 口径；
        # 无建议性自然语言——不再 instruct 模型检索/换模型/开新会话）。
        self._record_action(
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

    def _reset_overflow_state(self: LoopEngine) -> None:
        """R4→R8.24-B: 每次 run 重置 overflow 计数与预算收缩标志（move 自 engine.py:265）."""
        self._overflow_reinject_count = 0
        self._overflow_shrink_factor: float | None = None

"""LoopEngine overflow 处理职责 mixin（M53 拆分: engine.py 946 行→按职责分文件，纯重构行为零变化）.

move 自 engine.py 内联 overflow 段（397-425）与每 run 计数重置（265）：
- is_overflow_error 识别 + overflow_feedback 反馈文本构造 + 两段式注入决策（R4）
- 首次注入 system 消息让 AI 在同会话内自主决策；第二次直接结束避免无限循环
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (mixin 模式: self 属性来自混入类 LoopEngine.__init__，pyright 无法静态解析，故文件级关闭这两条；参数/返回类型等其余检查保留)


from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from llm_loop.core.message import Message, MessageSource
from llm_loop.feedback.honesty import overflow_feedback
from llm_loop.llm.errors import LLMError, is_overflow_error

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine

logger = logging.getLogger(__name__)


class _OverflowMixin:
    def _handle_overflow(self: LoopEngine, exc: LLMError, sess, model_used: str) -> tuple[str, str | None]:
        """R4: overflow 如实反馈（move 自 engine.py:397-425，不自动重试/不自动压缩，决策权归 AI）.

        Returns:
            ("reinject", None)  首次 overflow：system 消息已注入，主链路 continue
            ("end", text)       第二次 overflow：直接结束，text 为最终反馈
            ("not_overflow", None)  非 overflow 错误，主链路继续 fallback 判定
        """
        if not is_overflow_error(exc):
            return ("not_overflow", None)
        ctx_limit = self._current_context_limit(model_used)
        model_window = (
            {"label": model_used, "context": ctx_limit}
            if ctx_limit
            else {"label": model_used, "context": None}
        )
        feedback_text = overflow_feedback(
            exc,
            getattr(self, "_last_breakdown", None),
            model_window,
        )
        # 第一次 overflow: 注入 system 消息让 AI 在同会话内自主决策（调工具/换模型/回答）
        # 第二次 overflow: AI 已有一次机会但未解决，直接结束避免无限循环
        if self._overflow_reinject_count < 1:
            self._overflow_reinject_count += 1
            sess.messages.append(
                Message(
                    role="system",
                    content=feedback_text,
                    source=MessageSource.SYSTEM,
                )
            )
            return ("reinject", None)
        return ("end", feedback_text)

    def _reset_overflow_state(self: LoopEngine) -> None:
        """R4: 每次 run 重置 overflow 注入计数（move 自 engine.py:265）."""
        self._overflow_reinject_count = 0

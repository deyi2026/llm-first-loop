"""B1(EVO-20260902-41898b20) 中断半截产物捕获服务（R9/B5-W4-03 前置清障，D-B5-14）.

从 engine 侧内联挂点收编（结构等价迁移，行为零变化）：
- text/reasoning 增量累积（原 _run_stream_inner 局部列表 partial_parts/reasoning_parts；
  text 列兼容 P1-6 客户端断连落盘共用数据源语义）；
- 同一 run 至多一行截断标注（原局部标志 _interrupted_hook_fired，防重内聚于 fire）；
- LLMError 摘要（原 engine 模块级 _llm_error_digest 平迁，摘要口径不变）。
落盘语义仍委托 events.LoopEventsMixin._on_llm_interrupted（_last_interrupted 缓存与
truncated episode 行的写入不在此层）。
"""
from __future__ import annotations

from typing import Any


def llm_error_digest(exc: BaseException) -> str:
    """LLMError 摘要（状态码/provider/消息头，≤200 chars）.

    字段缺失如实省略（LLMError 仅 provider；LLMHTTPError 另有 status_code/body），
    用于中断落盘标注与 truncated episode 索引的 error_digest。
    """
    parts = (
        str(getattr(exc, "status_code", "") or ""),
        str(getattr(exc, "provider", "") or ""),
        str(exc),
    )
    return " ".join(p for p in parts if p)[:200]


class InterruptedCapture:
    """一 run 轮一实例：流式增量累积 + 中断触发口（同轮至多一行截断标注）."""

    __slots__ = ("_engine", "text_parts", "reasoning_parts", "cancelled", "_fired")

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self.text_parts: list[str] = []
        self.reasoning_parts: list[str] = []
        self.cancelled = False  # 吸收原局部 _cancelled_during_llm（取消归因消费点同名语义）
        self._fired = False

    def on_delta(self, delta: Any) -> None:
        """流式增量累积：text/reasoning 空串不收（与原两处内联判断逐字等价）."""
        if getattr(delta, "text", ""):
            self.text_parts.append(delta.text)
        if getattr(delta, "reasoning", ""):
            self.reasoning_parts.append(delta.reasoning)

    def fire(self, sess: Any, reason: str, round_no: int, exc: BaseException | None = None) -> None:
        """中断半截产物限量落盘（防重：同一 run 轮至多一行截断标注）."""
        if self._fired:
            return
        self._fired = True
        self._engine._on_llm_interrupted(
            sess,
            text_parts=self.text_parts,
            reasoning_parts=self.reasoning_parts,
            reason=reason,
            error_digest=llm_error_digest(exc) if exc else "",
            round_no=round_no,
        )

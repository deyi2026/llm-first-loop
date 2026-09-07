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

import json
import time
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

    __slots__ = (
        "_engine",
        "_sess",
        "_round_no",
        "_provider",
        "_model",
        "_text_chars",
        "_reasoning_chars",
        "_provider_replay",
        "_tool_call_drafts",
        "_native_state_chars",
        "_last_checkpoint_chars",
        "_last_checkpoint_at",
        "_provider_send_at",
        "_first_delta_ms",
        "_first_reasoning_ms",
        "_first_visible_ms",
        "_first_tool_call_ms",
        "text_parts",
        "reasoning_parts",
        "cancelled",
        "_fired",
    )

    def __init__(
        self,
        engine: Any,
        *,
        sess: Any | None = None,
        round_no: int = 0,
        provider: str = "",
        model: str = "",
    ) -> None:
        self._engine = engine
        self._sess = sess
        self._round_no = int(round_no or 0)
        self._provider = str(provider or "")
        self._model = str(model or "")
        self._text_chars = 0
        self._reasoning_chars = 0
        self._provider_replay: dict[str, Any] | None = None
        self._tool_call_drafts: list[dict[str, Any]] = []
        self._native_state_chars = 0
        self._last_checkpoint_chars = 0
        self._last_checkpoint_at = 0.0
        self._provider_send_at: float | None = None
        self._first_delta_ms: float | None = None
        self._first_reasoning_ms: float | None = None
        self._first_visible_ms: float | None = None
        self._first_tool_call_ms: float | None = None
        self.text_parts: list[str] = []
        self.reasoning_parts: list[str] = []
        self.cancelled = False  # 吸收原局部 _cancelled_during_llm（取消归因消费点同名语义）
        self._fired = False

    def mark_provider_send(self) -> None:
        """Mark the primary provider-call boundary; timing is telemetry only."""
        if self._provider_send_at is None:
            self._provider_send_at = time.perf_counter()

    def _elapsed_ms(self) -> float | None:
        if self._provider_send_at is None:
            return None
        return (time.perf_counter() - self._provider_send_at) * 1000.0

    def timing(self, *, total_ms: float | None = None) -> dict[str, Any]:
        return {
            "provider_total_ms": total_ms if total_ms is not None else self._elapsed_ms(),
            "first_delta_ms": self._first_delta_ms,
            "first_reasoning_ms": self._first_reasoning_ms,
            "first_visible_ms": self._first_visible_ms,
            "first_tool_call_ms": self._first_tool_call_ms,
            "prefill_end_ms": None,
        }

    def on_delta(self, delta: Any) -> None:
        """Accumulate streaming data; read the clock only for unresolved first boundaries."""
        text = getattr(delta, "text", "")
        reasoning = getattr(delta, "reasoning", "")
        need_timing = (
            self._first_delta_ms is None
            or (bool(reasoning) and self._first_reasoning_ms is None)
            or (bool(text) and self._first_visible_ms is None)
        )
        elapsed = self._elapsed_ms() if need_timing else None
        if self._first_delta_ms is None and elapsed is not None and (text or reasoning):
            self._first_delta_ms = elapsed
        if reasoning and self._first_reasoning_ms is None:
            self._first_reasoning_ms = elapsed
        if text and self._first_visible_ms is None:
            self._first_visible_ms = elapsed
        if text:
            self.text_parts.append(text)
            self._text_chars += len(text)
        if reasoning:
            self.reasoning_parts.append(reasoning)
            self._reasoning_chars += len(reasoning)
        self._maybe_checkpoint()

    def on_provider_state(self, state: dict[str, Any]) -> None:
        """Capture provider-native opaque replay/tool-call draft state.

        Tool-call drafts remain non-executable crash state.  They are persisted so a
        restart can diagnose/recover the exact interrupted phase, but they are never
        converted into normal ToolCall objects here.
        """
        drafts = state.get("tool_call_drafts")
        need_timing = bool(state) and (
            self._first_delta_ms is None
            or (isinstance(drafts, list) and bool(drafts) and self._first_tool_call_ms is None)
        )
        elapsed = self._elapsed_ms() if need_timing else None
        if state and self._first_delta_ms is None and elapsed is not None:
            self._first_delta_ms = elapsed
        replay = state.get("provider_replay")
        if isinstance(replay, dict):
            self._provider_replay = replay
        if isinstance(drafts, list):
            self._tool_call_drafts = [dict(item) for item in drafts if isinstance(item, dict)]
            if self._tool_call_drafts and self._first_tool_call_ms is None:
                self._first_tool_call_ms = elapsed
        try:
            self._native_state_chars = len(
                json.dumps(
                    {
                        "provider_replay": self._provider_replay,
                        "tool_call_drafts": self._tool_call_drafts,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        except (TypeError, ValueError):
            self._native_state_chars = 0
        self._maybe_checkpoint()

    def on_response(self, response: Any) -> None:
        """Capture terminal first-visible/tool boundaries for non-delta responses."""
        elapsed = self._elapsed_ms()
        if elapsed is None:
            return
        has_any = bool(
            getattr(response, "reasoning_content", None)
            or getattr(response, "content", None)
            or getattr(response, "tool_calls", None)
        )
        if has_any and self._first_delta_ms is None:
            self._first_delta_ms = elapsed
        if getattr(response, "reasoning_content", None) and self._first_reasoning_ms is None:
            self._first_reasoning_ms = elapsed
        if getattr(response, "content", None) and self._first_visible_ms is None:
            self._first_visible_ms = elapsed
        if getattr(response, "tool_calls", None) and self._first_tool_call_ms is None:
            self._first_tool_call_ms = elapsed

    def _maybe_checkpoint(self, *, force: bool = False) -> None:
        total_chars = self._text_chars + self._reasoning_chars + self._native_state_chars
        if not total_chars or self._sess is None:
            return
        now = time.monotonic()
        # First non-empty delta is checkpointed immediately; afterwards checkpoint
        # at most roughly once per 1 KiB or second.  This makes normal restart/kill
        # recovery durable without fsync-per-token/event-log explosion.
        if (
            force
            or self._last_checkpoint_chars == 0
            or total_chars - self._last_checkpoint_chars >= 1024
            or now - self._last_checkpoint_at >= 1.0
        ):
            try:
                self._engine._on_llm_partial_checkpoint(
                    self._sess,
                    text_parts=self.text_parts,
                    reasoning_parts=self.reasoning_parts,
                    round_no=self._round_no,
                    provider=self._provider,
                    model=self._model,
                    provider_replay=self._provider_replay,
                    tool_call_drafts=self._tool_call_drafts,
                )
                self._last_checkpoint_chars = total_chars
                self._last_checkpoint_at = now
            except Exception:  # noqa: BLE001 — checkpoint failure must not break streaming
                pass

    def fire(self, sess: Any, reason: str, round_no: int, exc: BaseException | None = None) -> None:
        """中断半截产物限量落盘（防重：同一 run 轮至多一行截断标注）."""
        if self._fired:
            return
        self._fired = True
        self._maybe_checkpoint(force=True)
        transport_facts: dict[str, Any] = {}
        if exc is not None:
            for name in (
                "finish_reason",
                "completion_tokens",
                "reasoning_tokens",
                "provider_truncated",
            ):
                if hasattr(exc, name):
                    transport_facts[name] = getattr(exc, name)
        self._engine._on_llm_interrupted(
            sess,
            text_parts=self.text_parts,
            reasoning_parts=self.reasoning_parts,
            reason=reason,
            error_digest=llm_error_digest(exc) if exc else "",
            round_no=round_no,
            provider=self._provider,
            model=self._model,
            provider_replay=self._provider_replay,
            tool_call_drafts=self._tool_call_drafts,
            transport_facts=transport_facts,
            timing=self.timing(),
        )

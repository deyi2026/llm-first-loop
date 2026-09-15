"""EVO-20260915-789eb9d5：纯机械 non-convergence 熔断守卫（人工审批 2026-09-15）.

同一 LLM 生成内，连续 ``windows`` 个 llm.partial_checkpoint 窗口同时满足：
① 无新 tool_call draft（窗口前后 draft 计数无增加）；
② 无新持久状态写入（journal receipt 提交计数无推进；不可测时保守不计入）；
③ reasoning 持续增长且同语义复读（规范化 token 多重集 Jaccard >= 阈值）；
即熔断：该生成立即终态终止，绝不进入重试/反馈环。

纯机械判定：零模型调用、零语义理解，仅确定性规范化指纹比对；
任一窗口任一条件不满足即清零连击。fail-safe 方向：宁可漏熔断，不误熔断。
"""
from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass

from llm_loop.llm.errors import LLMError

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

DEFAULT_WINDOWS = 3
DEFAULT_JACCARD = 0.6
DEFAULT_MIN_DELTA = 16


class NonconvergenceFuseError(LLMError):
    """机械非收敛熔断：流式生成被守卫终止（终态，非 provider 故障）."""

    def __init__(self, evidence: dict | None = None) -> None:
        self.evidence: dict = dict(evidence or {})
        e = self.evidence
        super().__init__(
            "nonconvergence_fuse: 连续 {streak} 个 partial_checkpoint 窗口无新 tool draft、"
            "无持久写入且 reasoning 同语义复读（jaccard={jac}）；生成已机械熔断终止，"
            "窗口证据见 llm.interrupted / llm.nonconvergence_fuse 事件。".format(
                streak=e.get("streak", 0), jac=e.get("jaccard", 0.0)
            )
        )


def _normalize_tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _multiset_jaccard(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    ca, cb = Counter(a), Counter(b)
    union = sum((ca | cb).values())
    return (sum((ca & cb).values()) / union) if union else 0.0


@dataclass
class _WindowFact:
    index: int
    qualifies: bool
    jaccard: float
    delta_chars: int
    no_new_draft: bool
    no_new_write: bool
    reasoning_grew: bool


class NonconvergenceGuard:
    """逐窗口机械状态机；每轮生成（InterruptedCapture）一实例，轮间自然重置."""

    def __init__(
        self,
        *,
        windows: int = DEFAULT_WINDOWS,
        jaccard_threshold: float = DEFAULT_JACCARD,
        min_delta_tokens: int = DEFAULT_MIN_DELTA,
    ) -> None:
        self.windows = int(windows)
        self.jaccard_threshold = float(jaccard_threshold)
        self.min_delta_tokens = int(min_delta_tokens)
        self._streak = 0
        self._tripped = False
        self._checkpoint_index = 0
        self._prev_reasoning_chars: int | None = None
        self._prev_draft_count: int | None = None
        self._prev_persist_seq: int | None = None
        self._prev_delta_tokens: list[str] | None = None
        self.last_window: _WindowFact | None = None
        self.evidence: dict = {}

    @classmethod
    def from_env(cls) -> NonconvergenceGuard:
        """环境旋钮：LFL_NONCONV_FUSE_WINDOWS(0=关)/…_JACCARD(0,1]/…_MIN_DELTA(tokens)."""

        def _int_env(name: str, default: int) -> int:
            raw = os.environ.get(name, "").strip()
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        def _float_env(name: str, default: float) -> float:
            raw = os.environ.get(name, "").strip()
            if not raw:
                return default
            try:
                value = float(raw)
            except ValueError:
                return default
            return value if 0.0 < value <= 1.0 else default

        return cls(
            windows=_int_env("LFL_NONCONV_FUSE_WINDOWS", DEFAULT_WINDOWS),
            jaccard_threshold=_float_env("LFL_NONCONV_FUSE_JACCARD", DEFAULT_JACCARD),
            min_delta_tokens=_int_env("LFL_NONCONV_FUSE_MIN_DELTA", DEFAULT_MIN_DELTA),
        )

    @property
    def tripped(self) -> bool:
        return self._tripped

    def observe_checkpoint(
        self,
        *,
        reasoning_chars: int,
        reasoning_full: str,
        tool_draft_count: int,
        persist_seq: int,
    ) -> None:
        """以一次 checkpoint 为窗口右边界，机械评估刚结束的窗口并推进连击."""
        if self._tripped or self.windows <= 0:
            return
        self._checkpoint_index += 1
        if self._prev_reasoning_chars is None:
            # 首个 checkpoint 只建立基线（draft/persist/delta 指纹），不计窗口
            self._prev_reasoning_chars = reasoning_chars
            self._prev_draft_count = tool_draft_count
            self._prev_persist_seq = persist_seq if persist_seq >= 0 else None
            self._prev_delta_tokens = _normalize_tokens(reasoning_full) or None
            self._streak = 0
            return
        delta = (
            reasoning_full[self._prev_reasoning_chars :]
            if reasoning_chars > self._prev_reasoning_chars
            else ""
        )
        tokens = _normalize_tokens(delta)
        jac = _multiset_jaccard(tokens, self._prev_delta_tokens or [])
        no_new_draft = (
            self._prev_draft_count is not None and tool_draft_count <= self._prev_draft_count
        )
        no_new_write = (
            persist_seq >= 0
            and self._prev_persist_seq is not None
            and persist_seq == self._prev_persist_seq
        )
        reasoning_grew = bool(delta) and len(tokens) >= self.min_delta_tokens
        qualifies = (
            no_new_draft
            and no_new_write
            and reasoning_grew
            and jac >= self.jaccard_threshold
        )
        self._streak = self._streak + 1 if qualifies else 0
        self.last_window = _WindowFact(
            index=self._checkpoint_index,
            qualifies=qualifies,
            jaccard=round(jac, 4),
            delta_chars=len(delta),
            no_new_draft=no_new_draft,
            no_new_write=no_new_write,
            reasoning_grew=reasoning_grew,
        )
        if tokens:
            self._prev_delta_tokens = tokens
        self._prev_reasoning_chars = reasoning_chars
        self._prev_draft_count = tool_draft_count
        if persist_seq >= 0:
            self._prev_persist_seq = persist_seq
        if self._streak >= self.windows:
            self._tripped = True
            self.evidence = {
                "streak": self._streak,
                "windows_required": self.windows,
                "jaccard_threshold": self.jaccard_threshold,
                "jaccard": round(jac, 4),
                "delta_chars": len(delta),
                "reasoning_chars": reasoning_chars,
                "tool_draft_count": tool_draft_count,
                "persist_seq": persist_seq,
                "min_delta_tokens": self.min_delta_tokens,
            }

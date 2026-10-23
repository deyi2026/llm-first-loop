"""双 ASR 终稿校正 `DualASRCorrector`（`T-CONTRACT-5`，INP-09）。

对应需求：`RTM-INP-01/02/03/09`、`RTM-AUD-03`。

核心语义（`DESIGN v1.3 §2.1.3-H`、D26）：

- 流式增量（`delta`）**只作实时字幕显示**，**不得**作为 `input.final` 或进入 `committed`；
- 句末/轮次结束用**高精度 ASR 重转写整段音频**，以其结果作为 `input.final`；
- 高精度不可用/超时 → **`ConservativeFinal`**：保守边界 + `precision_notice`（不冒充精确终稿）。

本模块只做机械事实（来源与精度标注），不做语义理解。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class CorrectionOutcome(StrEnum):
    """终稿来源：高精度重转写 / 保守兜底。"""

    PRECISE = "precise"
    CONSERVATIVE = "conservative"


CONSERVATIVE_PRECISION_NOTICE = (
    "终稿由流式结果保守收口（高精度重转写不可用/超时）——可能存在识别误差，"
    "不作为逐字精确依据"
)


@dataclass(frozen=True)
class FinalCorrection:
    """终稿校正结果。`outcome=CONSERVATIVE` 时必须带精度标注。"""

    text: str
    outcome: CorrectionOutcome
    precision_notice: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be str")
        if self.outcome is CorrectionOutcome.CONSERVATIVE and not self.precision_notice:
            raise ValueError("conservative final requires a precision_notice")


class FinalTranscriber(Protocol):
    """高精度整段转写（如 `/v1/audio/transcriptions`，Qwen3-ASR）。"""

    def __call__(self, pcm_segment: bytes) -> str: ...


class DualASRCorrector:
    """流式 `delta` 仅显示；`final` 由高精度重转写产生，失败/超时走保守兜底。"""

    def __init__(self, final_transcriber: FinalTranscriber | None = None) -> None:
        self._final_transcriber = final_transcriber

    def correct(
        self, pcm_segment: bytes | None, *, delta_text: str, timed_out: bool = False
    ) -> FinalCorrection:
        """产终稿。

        - 高精度可用且未超时 → `PRECISE`（其文本作为 `input.final`）；
        - 无重转写器 / 无音频 / 超时 / 抛错 → `CONSERVATIVE`（以 `delta_text` 保守收口 + 标注）。
        """
        if self._final_transcriber is None or timed_out or not pcm_segment:
            return self._conservative(delta_text)
        try:
            text = self._final_transcriber(pcm_segment)
        except Exception:  # noqa: BLE001 - 高精度不可用不得阻断轮次，转保守兜底
            return self._conservative(delta_text)
        if not text or not text.strip():
            return self._conservative(delta_text)
        return FinalCorrection(text=text, outcome=CorrectionOutcome.PRECISE)

    @staticmethod
    def _conservative(delta_text: str) -> FinalCorrection:
        return FinalCorrection(
            text=delta_text,
            outcome=CorrectionOutcome.CONSERVATIVE,
            precision_notice=CONSERVATIVE_PRECISION_NOTICE,
        )

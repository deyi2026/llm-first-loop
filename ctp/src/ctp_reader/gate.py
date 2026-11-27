"""B4 读出闸门（SPEC §5 C-4 双向抑制）+ K7 影子通道。

- 错读侧（"低阈值零输出"）：低于任一阈值 → allowed=False，调用方必须不输出（宁可漏检，不可错读）；
- 漏检侧（"达标漏检可统计"）：达到阈值 → allowed=True；达标却被抑制必须为 0。达标样本的
  漏检率由 V4 runner 用样本标签另行统计，闸门只提供 suppressed_count；
- K7 影子通道：shadow=True（仅测试构建）时记录近阈值候选，但绝不改变 allowed，日志里不含任何 ID 或观测内容。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import ThresholdConfig
from .errors import CONFIG_INVALID, INVALID_INPUT, ReaderError

REASON_OK = "ok"
REASON_BELOW_CORNERS = "below_min_corners"
REASON_BELOW_RATIO = "below_min_data_ratio"


@dataclass(frozen=True)
class ReadEvidence:
    """一次读取的几何证据：完整落在图像内的角点数与数据格比例。"""

    visible_corners: int
    visible_data_ratio: float


@dataclass(frozen=True)
class GateDecision:
    """闸门判定。shadow_candidate 仅供影子统计，调用方不得据此放行。"""

    allowed: bool
    reason: str
    shadow_candidate: bool


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_ratio(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0.0 <= value <= 1.0
    )


def _in_band(value: float, threshold: float, band: float) -> bool:
    """近阈值带（工程定义，待 G2 追认）：threshold·(1−b) ≤ value < threshold·(1+b)。"""
    return threshold * (1.0 - band) <= value < threshold * (1.0 + band)


class ReadGate:
    """C-4 闸门：恰等于阈值即允许（≥ 语义）；先判角点数，再判数据位比例。"""

    def __init__(self, config: ThresholdConfig) -> None:
        if not isinstance(config, ThresholdConfig):
            raise ReaderError(CONFIG_INVALID, "config", "ReadGate requires a ThresholdConfig")
        self._config = config
        self.suppressed_count = 0
        self.shadow_count = 0
        self.shadow_log: list[dict] = []

    @property
    def config(self) -> ThresholdConfig:
        return self._config

    def evaluate(self, evidence: ReadEvidence) -> GateDecision:
        if not isinstance(evidence, ReadEvidence):
            raise ReaderError(INVALID_INPUT, "evidence", "evaluate requires ReadEvidence")
        if not _is_count(evidence.visible_corners):
            raise ReaderError(INVALID_INPUT, "evidence.visible_corners", "must be an int >= 0")
        if not _is_ratio(evidence.visible_data_ratio):
            raise ReaderError(INVALID_INPUT, "evidence.visible_data_ratio", "must be a number in [0, 1]")

        allowed = True
        reason = REASON_OK
        if evidence.visible_corners < self._config.min_visible_corners:
            allowed = False
            reason = REASON_BELOW_CORNERS
        elif evidence.visible_data_ratio < self._config.min_visible_data_ratio:
            allowed = False
            reason = REASON_BELOW_RATIO

        shadow_candidate = False
        if self._config.shadow and self._config.shadow_band is not None:
            band = self._config.shadow_band
            shadow_candidate = _in_band(
                float(evidence.visible_corners), float(self._config.min_visible_corners), band
            ) or _in_band(
                float(evidence.visible_data_ratio), self._config.min_visible_data_ratio, band
            )
            if shadow_candidate:
                self.shadow_count += 1
                self.shadow_log.append(
                    {
                        "visible_corners": evidence.visible_corners,
                        "visible_data_ratio": evidence.visible_data_ratio,
                        "reason": reason,
                    }
                )

        if not allowed:
            self.suppressed_count += 1
        return GateDecision(allowed, reason, shadow_candidate)

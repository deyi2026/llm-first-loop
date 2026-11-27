"""B4 阈值配置（SPEC §5 C-4）：声明式、必填、无默认值（计划 §4.1 K1）。

[TBD-V4a]（可见角点数）与 [TBD-V4b]（数据位可见比例）在 P2 实测与工作组裁决前为空缺；
本模块不提供任何数值默认，也不在代码里出现门槛数字。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import CONFIG_INVALID, ReaderError

REQUIRED_FIELDS = ("min_visible_corners", "min_visible_data_ratio")
OPTIONAL_FIELDS = ("shadow", "shadow_band")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    )


@dataclass(frozen=True)
class ThresholdConfig:
    """最小可读条件 + 影子通道开关。两项阈值必填；没有任何数值默认值（K1）。"""

    min_visible_corners: int  # [TBD-V4a]：可见角点数下限（含）
    min_visible_data_ratio: float  # [TBD-V4b]：数据位可见比例下限（含），取值 (0, 1]
    shadow: bool = False  # K7：影子通道，仅测试构建置 True
    shadow_band: float | None = None  # 近阈值带宽（相对阈值的比例，>0）；shadow=True 时必填（工程定义，待 G2 追认）

    def __post_init__(self) -> None:
        if not _is_int(self.min_visible_corners) or self.min_visible_corners < 1:
            raise ReaderError(
                CONFIG_INVALID,
                "min_visible_corners",
                "must be an int >= 1 ([TBD-V4a] has no default)",
            )
        if not _is_number(self.min_visible_data_ratio) or not (
            0.0 < self.min_visible_data_ratio <= 1.0
        ):
            raise ReaderError(
                CONFIG_INVALID,
                "min_visible_data_ratio",
                "must be a number in (0, 1] ([TBD-V4b] has no default)",
            )
        object.__setattr__(self, "min_visible_data_ratio", float(self.min_visible_data_ratio))
        if not isinstance(self.shadow, bool):
            raise ReaderError(CONFIG_INVALID, "shadow", "must be a bool")
        if self.shadow_band is not None and (not _is_number(self.shadow_band) or self.shadow_band <= 0.0):
            raise ReaderError(CONFIG_INVALID, "shadow_band", "must be a number > 0 when given")
        if self.shadow:
            if self.shadow_band is None:
                raise ReaderError(CONFIG_INVALID, "shadow_band", "is required when shadow=True")
            object.__setattr__(self, "shadow_band", float(self.shadow_band))

    @classmethod
    def from_file(cls, path: str | Path) -> "ThresholdConfig":
        """声明式 JSON → ThresholdConfig。缺键 / 多键 / 类型不符 / 越界一律抛 config_invalid。

        不做默认值填充，不做字符串到数字的类型强转（fail-closed）。
        """
        target = Path(path)
        try:
            raw = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReaderError(CONFIG_INVALID, str(target), f"cannot read thresholds file: {exc}") from exc
        try:
            obj = json.loads(raw)
        except ValueError as exc:
            raise ReaderError(CONFIG_INVALID, str(target), "thresholds file is not valid JSON") from exc
        if not isinstance(obj, dict):
            raise ReaderError(CONFIG_INVALID, str(target), "thresholds file must contain a JSON object")
        missing = [name for name in REQUIRED_FIELDS if name not in obj]
        if missing:
            raise ReaderError(CONFIG_INVALID, str(target), f"missing required thresholds: {sorted(missing)}")
        unknown = sorted(key for key in obj if key not in REQUIRED_FIELDS + OPTIONAL_FIELDS)
        if unknown:
            raise ReaderError(CONFIG_INVALID, str(target), f"unknown thresholds fields: {unknown}")
        return cls(**obj)

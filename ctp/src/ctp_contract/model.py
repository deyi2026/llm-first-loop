"""C-5 读取输出契约的数据模型（SPEC-20261123-CTP-0.9.2 §5 C-5）。

边界：
- 只承载契约字段；不含检测、位姿解算（B3）与不确定度传播（B2）；
- 不做默认值填充：缺字段即报错（K6 fail-closed）；
- 枚举按 SPEC 原文，不做同义词归一（`none` / `None` / `NONE` 只有第一个合法）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Resolution(StrEnum):
    """C-5 resolution：解析状态。"""

    CODE = "code"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class DegradationFlag(StrEnum):
    """C-5 degradation_flag：降级标记。"""

    NONE = "none"
    COARSE = "coarse"
    QUARANTINE = "quarantine"


@dataclass(frozen=True)
class Vector3:
    x: float
    y: float
    z: float

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}


@dataclass(frozen=True)
class Quaternion:
    x: float
    y: float
    z: float
    w: float

    def norm(self) -> float:
        return (self.x**2 + self.y**2 + self.z**2 + self.w**2) ** 0.5

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z, "w": self.w}


@dataclass(frozen=True)
class Pose:
    """6DoF 位姿；frame_ref 指向注册表里的参考系定义（C-5 / R-1）。"""

    position_m: Vector3
    quaternion: Quaternion
    frame_ref: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "position_m": self.position_m.as_dict(),
            "quaternion": self.quaternion.as_dict(),
            "frame_ref": self.frame_ref,
        }


@dataclass(frozen=True)
class Uncertainty:
    """C-5 不确定度声明：必须同时给出覆盖因子 k 与 1σ 值（SPEC 11.2-V2）。"""

    k: float
    model: str
    translation_1sigma_m: Vector3
    rotation_1sigma_deg: Vector3
    covariance_6x6: tuple[tuple[float, ...], ...] | None = None
    extensions: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "k": self.k,
            "model": self.model,
            "translation_1sigma_m": self.translation_1sigma_m.as_dict(),
            "rotation_1sigma_deg": self.rotation_1sigma_deg.as_dict(),
        }
        if self.covariance_6x6 is not None:
            out["covariance_6x6"] = [list(row) for row in self.covariance_6x6]
        out.update(self.extensions)
        return out


@dataclass(frozen=True)
class Observation:
    """一次合规读取的输出（C-5 全字段）。"""

    target_index: int
    logical_id: str | None
    resolution: Resolution
    pose: Pose
    uncertainty: Uncertainty
    degradation_flag: DegradationFlag
    timestamp: str
    reader_id: str
    reader_version: str
    schema_version: str | None = None
    extensions: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "target_index": self.target_index,
            "logical_id": self.logical_id,
            "resolution": self.resolution.value,
            "pose": self.pose.as_dict(),
            "uncertainty": self.uncertainty.as_dict(),
            "degradation_flag": self.degradation_flag.value,
            "timestamp": self.timestamp,
            "reader_id": self.reader_id,
            "reader_version": self.reader_version,
        }
        if self.schema_version is not None:
            out["schema_version"] = self.schema_version
        out.update(self.extensions)
        return out

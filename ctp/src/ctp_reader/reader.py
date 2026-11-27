"""读码器封装 v0（B3）：单帧灰度图（含一枚 36h11）→ ctp_contract.Observation（C-5 全字段）。

读取顺序（计划 §4.1 K6 fail-closed）：
校验输入与时间戳 → 定位靶标并估计格阵 → 几何证据过闸门（不允许即 below_min_readable，
不解码、不输出）→ 解码（纠错能力外即 unknown_version，不输出 ID）→ 位姿与不确定度 →
组装观测 → 用 ctp_contract.parse_observation 自检后才返回。
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import numpy as np

from ctp_contract import (
    DegradationFlag,
    Observation,
    Pose,
    Quaternion,
    Resolution,
    Vector3,
    parse_observation,
)
from ctp_calib import pixel as pixel_model

from . import pose as pose_module
from .config import ThresholdConfig
from .decode36h11 import decode, sample_cells
from .errors import (
    BELOW_MIN_READABLE,
    CONFIG_INVALID,
    INVALID_INPUT,
    ReaderError,
)
from .gate import ReadEvidence, ReadGate
from .image import locate_tag, validate, visible_corners, visible_data_ratio


def _positive(value: Any, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0.0
    ):
        raise ReaderError(CONFIG_INVALID, name, f"{name} must be a finite number > 0 (required, no default)")
    return float(value)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReaderError(CONFIG_INVALID, name, f"{name} must be a non-empty string (required, no default)")
    return value


class Reader:
    """36h11 读码器 v0。全部构造参数必填、无默认值。"""

    def __init__(
        self,
        *,
        gate: ReadGate,
        camera: pixel_model.PinholeCamera,
        tag_size_m: float,
        sigma_px: float,
        coverage_factor_k: float,
        reader_id: str,
        reader_version: str,
        frame_ref: str,
    ) -> None:
        if not hasattr(gate, "evaluate"):
            raise ReaderError(CONFIG_INVALID, "gate", "gate must expose evaluate(ReadEvidence)")
        for attribute in ("fx", "fy", "cx", "cy"):
            if not hasattr(camera, attribute):
                raise ReaderError(CONFIG_INVALID, "camera", f"camera must expose {attribute}")
        self._gate = gate
        self._camera = camera
        self._tag_size_m = _positive(tag_size_m, "tag_size_m")
        self._sigma_px = _positive(sigma_px, "sigma_px")
        self._coverage_factor_k = _positive(coverage_factor_k, "coverage_factor_k")
        self._reader_id = _text(reader_id, "reader_id")
        self._reader_version = _text(reader_version, "reader_version")
        self._frame_ref = _text(frame_ref, "frame_ref")

    @property
    def reader_id(self) -> str:
        return self._reader_id

    @property
    def reader_version(self) -> str:
        return self._reader_version

    @property
    def thresholds(self) -> ThresholdConfig:
        return self._gate.config

    def read(
        self,
        image: np.ndarray,
        *,
        timestamp: str,
        resolver: Any = None,
        degradation: str = "none",
    ) -> Observation:
        frame = validate(image)
        when = _timestamp(timestamp)
        try:
            flag = DegradationFlag(degradation)
        except ValueError as exc:
            raise ReaderError(INVALID_INPUT, "degradation", f"unknown degradation flag {degradation!r}") from exc

        grid = locate_tag(frame)
        evidence = ReadEvidence(
            visible_corners=visible_corners(frame, grid),
            visible_data_ratio=visible_data_ratio(grid),
        )
        decision = self._gate.evaluate(evidence)
        if not decision.allowed:
            # C-4b：宁可漏检，不可错读——闸门不过就不解码，更不输出
            raise ReaderError(
                BELOW_MIN_READABLE,
                "evidence",
                f"{decision.reason} (visible_corners={evidence.visible_corners}, "
                f"visible_data_ratio={evidence.visible_data_ratio:.3f})",
            )

        dark, known = sample_cells(frame, grid)
        result = decode(dark, known)
        pose_matrix, covariance = pose_module.solve_pose(
            self._camera,
            grid,
            tag_size_m=self._tag_size_m,
            quarter_turns=result.quarter_turns,
            sigma_px=self._sigma_px,
        )
        qx, qy, qz, qw = pose_module.rotation_to_quaternion(pose_matrix[:3, :3])
        logical_id = self._resolve(result.target_index, resolver)
        observation = Observation(
            target_index=result.target_index,
            logical_id=logical_id,
            resolution=Resolution.RESOLVED if logical_id is not None else Resolution.UNRESOLVED,
            pose=Pose(
                position_m=Vector3(*(float(value) for value in pose_matrix[:3, 3])),
                quaternion=Quaternion(qx, qy, qz, qw),
                frame_ref=self._frame_ref,
            ),
            uncertainty=pose_module.declaration(self._coverage_factor_k, covariance),
            degradation_flag=flag,
            timestamp=when,
            reader_id=self._reader_id,
            reader_version=self._reader_version,
        )
        # 自检：产出必须是合规的 C-5 观测；不合规就抛错，绝不返回半成品
        parse_observation(observation.as_dict())
        return observation

    def _resolve(self, target_index: int, resolver: Any) -> str | None:
        """36h11 板内索引不等于全局 ID（SPEC C-1d）：没有解析器就是 unresolved，不自造 logical_id。"""
        if not callable(resolver):
            return None
        resolved = resolver(target_index)
        return resolved if isinstance(resolved, str) and resolved.strip() else None


def _timestamp(value: Any) -> str:
    """采集时刻必须是带时区的 ISO 8601 字符串；原样返回，不做任何补全。"""
    if not isinstance(value, str):
        raise ReaderError(INVALID_INPUT, "timestamp", "timestamp must be an ISO 8601 string with timezone")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ReaderError(INVALID_INPUT, "timestamp", f"timestamp is not ISO 8601: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ReaderError(INVALID_INPUT, "timestamp", "timestamp must carry a UTC offset")
    return value

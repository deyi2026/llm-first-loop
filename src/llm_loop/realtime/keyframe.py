"""关键帧帧元数据：`current_validity` 与 `retention_state` 分离（`T-CONTRACT-7`）。

对应需求：`RTM-VIS-02/03/05/06/09`、`RTM-RET-01/02/03`、`RTM-CAP-06`、`RTM-IDN-01`、`RTM-RET-05`。

核心语义（`DESIGN v1.3 §2.1.3-F`、D21）：

- 两个**正交维度**：`current_validity`（当前画面有效性）与 `retention_state`（证据保留状态）；
- **`Stale` 只使当前画面失效，仍可回答历史问题**（证据仍保留）；
- **只有删除 / 到期（`Expired`）才失去回读能力**，并返回明确失效；
- 图转文/派生结果标 `derived`，**不冒充原图**（`RTM-CAP-06`、`RTM-RET-03`）；
- 帧龄用**客户端同一单调时钟**计算；服务端另记接收时刻（`RTM-VIS-06`）；
- 原始帧字节经 `WorkspaceArtifactStore` 承载（`artifact://v1/<32hex>`），**不另建第二证据库**。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum

_ARTIFACT_REF = re.compile(r"artifact://v1/[0-9a-f]{32}\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class CurrentValidity(StrEnum):
    """当前画面有效性；`STALE` **不等于删除**。"""

    VALID = "valid"
    STALE = "stale"


class RetentionState(StrEnum):
    """证据保留状态；只有 `EXPIRED`/`DELETED` 才失去回读能力。"""

    RETAINED = "retained"
    EXPIRED = "expired"
    DELETED = "deleted"


class KeyframeReadbackError(RuntimeError):
    """帧已失去回读能力（到期/删除）。"""


@dataclass(frozen=True)
class Selection:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        for name in ("x", "y", "width", "height"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.width == 0 or self.height == 0:
            raise ValueError("selection must have non-zero area")


@dataclass(frozen=True)
class Keyframe:
    """不可变帧元数据。失效更新返回**新对象**（保存精确源，已绑定帧不被新帧替换）。"""

    frame_id: str
    source_id: str
    source_epoch: int
    captured_at_client_monotonic_s: float
    received_at_s: float
    width: int
    height: int
    content_ref: str
    selection: Selection | None = None
    derived: bool = False
    current_validity: CurrentValidity = CurrentValidity.VALID
    retention_state: RetentionState = RetentionState.RETAINED

    def __post_init__(self) -> None:
        for name in ("frame_id", "source_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _NAME.fullmatch(value):
                raise ValueError(f"{name} must be a bounded identifier")
        if not isinstance(self.content_ref, str) or not _ARTIFACT_REF.fullmatch(self.content_ref):
            raise ValueError("content_ref must be an artifact://v1/<32hex> reference")
        if self.source_epoch < 0:
            raise ValueError("source_epoch must be >= 0")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width/height must be positive")
        if self.captured_at_client_monotonic_s < 0 or self.received_at_s < 0:
            raise ValueError("timestamps must be non-negative")

    @property
    def is_stale(self) -> bool:
        return self.current_validity is CurrentValidity.STALE

    def mark_stale(self) -> Keyframe:
        """当前画面失效；**证据保留状态不变**（`Stale ≠ 删除`）。"""
        return replace(self, current_validity=CurrentValidity.STALE)

    def mark_valid(self) -> Keyframe:
        return replace(self, current_validity=CurrentValidity.VALID)

    def expire(self) -> Keyframe:
        """到期：失去回读能力。"""
        return replace(self, retention_state=RetentionState.EXPIRED)

    def delete(self) -> Keyframe:
        """删除：失去回读能力。"""
        return replace(self, retention_state=RetentionState.DELETED)

    def can_answer_current(self) -> bool:
        """可回答**当前画面**问题：需当前有效且证据仍保留。"""
        return (
            self.current_validity is CurrentValidity.VALID
            and self.retention_state is RetentionState.RETAINED
        )

    def can_answer_history(self) -> bool:
        """可回答**历史**问题：只要证据仍保留即可（`Stale` 也满足）。"""
        return self.retention_state is RetentionState.RETAINED

    def readback_ref(self) -> str:
        """回读内容引用；已失去回读能力时**返回明确失效**。"""
        if self.retention_state is not RetentionState.RETAINED:
            raise KeyframeReadbackError(
                f"keyframe {self.frame_id} no longer readable ({self.retention_state.value})"
            )
        return self.content_ref

    def frame_age_s(self, client_now_monotonic_s: float) -> float:
        """帧龄：客户端**同一单调时钟**计算。"""
        if client_now_monotonic_s < self.captured_at_client_monotonic_s:
            raise ValueError("client clock went backwards")
        return client_now_monotonic_s - self.captured_at_client_monotonic_s

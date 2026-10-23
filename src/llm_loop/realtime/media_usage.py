"""本地实时语音栈的媒体计量记录与任务预算适配层（T-CONTRACT-8）。

设计约束（`DESIGN v1.3`、`SPEC v1.2`）：

- **不改 `BudgetDimension` 合同**（`resources/task_budget_contracts.py`）：媒体用量以
  独立计量记录承载，经本模块的适配层**旁路映射**到既有维度或独立统计；
  旧额度 / 旧记录反序列化不得因此失败（`RTM-BUD-01/02`、`RTM-CMP-01`）。
- 本地栈下按**本地算力与模型许可口径**记录（`local_compute_ms` / `license_id`），
  而非远端模态计费（`RTM-BUD-01/02`）。
- 区分**估算 / 结算**；缺最终用量标 `incomplete`，**不标零**（`RTM-BUD-04/05`）。
- 实时路径与任务路径预算独立（`RTM-BUD-07`）：本模块不改写任务预算策略，
  只提供只读的旁路映射与独立账本。
- 残留并发上限与差异化拥塞：对不支持取消的路径限定在途请求数并计量
  （`RTM-LIF-05/07`、`RTM-STP-06`）。

本模块只做机械事实记录与边界，不做语义判断。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def _identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a non-empty, bounded identifier")


def _bounded_optional_text(name: str, value: str) -> None:
    if not isinstance(value, str) or len(value) > 256:
        raise ValueError(f"{name} must be bounded text")


class MediaModality(StrEnum):
    """媒体模态。**独立于** `BudgetDimension` 合同，仅用于本适配层的旁路计量。"""

    AUDIO_INPUT_MS = "audio_input_ms"
    AUDIO_OUTPUT_MS = "audio_output_ms"
    IMAGE_FRAMES = "image_frames"
    TTS_CHARS = "tts_chars"
    ASR_CHARS = "asr_chars"


class UsageStatus(StrEnum):
    """计量状态：区分估算与结算；缺最终用量为 `incomplete`（**不标零**）。"""

    ESTIMATED = "estimated"
    SETTLED = "settled"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class MediaUsageRecord:
    """单条媒体用量记录（不可变）。"""

    media_session_id: str
    modality: MediaModality
    quantity: int
    status: UsageStatus = UsageStatus.ESTIMATED
    provider_identity: str = ""
    exact_model_ref: str = ""
    license_id: str = ""
    local_compute_ms: int | None = None
    event_id: str = ""

    def __post_init__(self) -> None:
        _identifier("media_session_id", self.media_session_id)
        if not isinstance(self.modality, MediaModality):
            raise TypeError("modality must be MediaModality")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int) or self.quantity < 0:
            raise ValueError("quantity must be a non-negative integer")
        if not isinstance(self.status, UsageStatus):
            raise TypeError("status must be UsageStatus")
        for name in ("provider_identity", "exact_model_ref", "license_id", "event_id"):
            _bounded_optional_text(name, getattr(self, name))
        if self.event_id:
            _identifier("event_id", self.event_id)
        if self.local_compute_ms is not None and (
            isinstance(self.local_compute_ms, bool)
            or not isinstance(self.local_compute_ms, int)
            or self.local_compute_ms < 0
        ):
            raise ValueError("local_compute_ms must be a non-negative integer or None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "media_session_id": self.media_session_id,
            "modality": self.modality.value,
            "quantity": self.quantity,
            "status": self.status.value,
            "provider_identity": self.provider_identity,
            "exact_model_ref": self.exact_model_ref,
            "license_id": self.license_id,
            "local_compute_ms": self.local_compute_ms,
            "event_id": self.event_id,
        }


@dataclass
class MediaUsageLedger:
    """独立媒体计量账本，按 `media_session_id` 聚合；**不改任务预算合同**。"""

    records: list[MediaUsageRecord] = field(default_factory=list)

    def record(self, rec: MediaUsageRecord) -> MediaUsageRecord:
        if not isinstance(rec, MediaUsageRecord):
            raise TypeError("rec must be MediaUsageRecord")
        self.records.append(rec)
        return rec

    def _for_session(self, media_session_id: str) -> list[MediaUsageRecord]:
        return [r for r in self.records if r.media_session_id == media_session_id]

    def totals(self, media_session_id: str) -> dict[str, int]:
        """按模态聚合数量。**缺用量计数为 0 值不出现**——以 `status` 表达不完整，
        绝不用 0 冒充“无用量”（`RTM-BUD-04/05`）。"""
        out: dict[str, int] = {}
        for rec in self._for_session(media_session_id):
            key = rec.modality.value
            out[key] = out.get(key, 0) + rec.quantity
        return out

    def local_compute_ms(self, media_session_id: str) -> int:
        """本地算力口径合计（仅计入有值记录）。"""
        return sum(
            rec.local_compute_ms or 0 for rec in self._for_session(media_session_id)
        )

    def status(self, media_session_id: str) -> UsageStatus:
        """聚合状态：任一 `incomplete` → `incomplete`；否则任一 `estimated` → `estimated`；
        全部 `settled` → `settled`；无记录 → `incomplete`（缺失不等于零）。"""
        recs = self._for_session(media_session_id)
        if not recs:
            return UsageStatus.INCOMPLETE
        if any(r.status is UsageStatus.INCOMPLETE for r in recs):
            return UsageStatus.INCOMPLETE
        if any(r.status is UsageStatus.ESTIMATED for r in recs):
            return UsageStatus.ESTIMATED
        return UsageStatus.SETTLED

    def settle(self, media_session_id: str, *, event_id: str = "") -> int:
        """把该会话内所有 `estimated`/`incomplete` 记录视为最终结算。

        返回被结算的记录数。`incomplete` 若最终确认无账单，仍**保留 `incomplete`
        语义**由调用方决定；本方法只把可结算项转为 `settled`（缺用量不转）。
        """
        settled = 0
        updated: list[MediaUsageRecord] = []
        for rec in self.records:
            if rec.media_session_id != media_session_id:
                updated.append(rec)
                continue
            if rec.status is UsageStatus.ESTIMATED:
                updated.append(
                    MediaUsageRecord(
                        media_session_id=rec.media_session_id,
                        modality=rec.modality,
                        quantity=rec.quantity,
                        status=UsageStatus.SETTLED,
                        provider_identity=rec.provider_identity,
                        exact_model_ref=rec.exact_model_ref,
                        license_id=rec.license_id,
                        local_compute_ms=rec.local_compute_ms,
                        event_id=event_id or rec.event_id,
                    )
                )
                settled += 1
            else:
                updated.append(rec)
        self.records = updated
        return settled

    def summary(self, media_session_id: str) -> dict[str, Any]:
        return {
            "media_session_id": media_session_id,
            "totals": self.totals(media_session_id),
            "local_compute_ms": self.local_compute_ms(media_session_id),
            "status": self.status(media_session_id).value,
        }


class MediaUsageBudgetAdapter:
    """把媒体计量**旁路**映射到既有预算维度，而不扩展 `BudgetDimension`。

    - 映射只使用既有维度（`payload_bytes`），返回的是**建议补丁**，由调用方决定是否应用；
    - 不修改 `TaskBudgetLimits` 的字段集合，故 `TaskBudgetLimits.from_dict` 的严格校验
      不受影响（`RTM-CMP-01`）；
    - 实时路径与任务路径预算独立：本适配层不触碰任务预算策略（`RTM-BUD-07`）。
    """

    __slots__ = ()

    _BYTES_PER_AUDIO_MS_16K_PCM16 = 32  # 16000Hz * 2B / 1000ms

    def payload_bytes(self, records: list[MediaUsageRecord]) -> int:
        total = 0
        for rec in records:
            if rec.modality in (MediaModality.AUDIO_INPUT_MS, MediaModality.AUDIO_OUTPUT_MS):
                total += rec.quantity * self._BYTES_PER_AUDIO_MS_16K_PCM16
            elif rec.modality is MediaModality.IMAGE_FRAMES or rec.modality in (MediaModality.TTS_CHARS, MediaModality.ASR_CHARS):
                total += rec.quantity * 0
        return total

    def budget_hint(self, records: list[MediaUsageRecord]) -> dict[str, int]:
        """返回**旁路**建议（仅既有 `payload_bytes` 维度），供调用方按需并入预算。"""
        return {"payload_bytes": self.payload_bytes(records)}


class AdmissionDecision(StrEnum):
    ADMIT = "admit"
    STOP_NEW_REQUESTS = "stop_new_requests"


def decide_budget_admission(
    *, limit: int | None, used: int, requested: int
) -> AdmissionDecision:
    """达限行为：到限即停新请求，**不影响在途调用结算**（`RTM-BUD-04/05`）。

    `limit is None` 表示本层不限制（NOT QUALIFIED 的相反：显式放行由上层决定）。
    """
    if isinstance(used, bool) or isinstance(requested, bool):
        raise TypeError("used/requested must be integers")
    if not isinstance(used, int) or not isinstance(requested, int):
        raise TypeError("used/requested must be integers")
    if used < 0 or requested < 0:
        raise ValueError("used/requested must be non-negative")
    if limit is None:
        return AdmissionDecision.ADMIT
    if limit < 0:
        raise ValueError("limit must be non-negative")
    return (
        AdmissionDecision.ADMIT
        if used + requested <= limit
        else AdmissionDecision.STOP_NEW_REQUESTS
    )


class ResidualConcurrencyLimiter:
    """残留并发上限：对不支持取消的路径限定在途请求数并计量（`RTM-LIF-05/07`、`RTM-STP-06`）。

    仅做机械计数与上限，不做语义裁决；`release()` 拒绝下溢以暴露调用方错误。
    """

    __slots__ = ("_limit", "_inflight")

    def __init__(self, limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        self._limit = limit
        self._inflight = 0

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def inflight(self) -> int:
        return self._inflight

    @property
    def saturated(self) -> bool:
        return self._inflight >= self._limit

    def try_acquire(self) -> bool:
        if self._inflight >= self._limit:
            return False
        self._inflight += 1
        return True

    def release(self) -> None:
        if self._inflight <= 0:
            raise ValueError("release without a matching acquire")
        self._inflight -= 1

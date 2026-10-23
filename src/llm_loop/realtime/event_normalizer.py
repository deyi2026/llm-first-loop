"""转写事件规范化与去重（`T-CONTRACT-5`，INP-02/03）。

对应需求：`RTM-INP-02/03`、`RTM-CAP-12`。

- 把 Provider 原始事件规范化为 `DELTA`（临时字幕）/ `FINAL`（识别完成）；
- 同一 `(turn_id, revision)` 的 `FINAL` **只发一次**（重复到达被去重，仅一次进队列）；
- `DELTA` 仅作显示：本模块不做队列投递（由 `TurnAggregator` 保证 `delta` 永不驱动任务）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

_RAW_DELTA = "conversation.item.input_audio_transcription.delta"
_RAW_COMPLETED = "conversation.item.input_audio_transcription.completed"


class NormalizedKind(StrEnum):
    DELTA = "delta"
    FINAL = "final"


@dataclass(frozen=True)
class NormalizedEvent:
    kind: NormalizedKind
    text: str
    turn_id: str
    revision: int = 0


@dataclass
class EventNormalizer:
    """规范化 + 去重。`DELTA` 可重复（增量），`FINAL` 同修订号只发一次。"""

    _seen_final: set[tuple[str, int]] = field(default_factory=set)

    def normalize(
        self, raw_kind: str, text: str, *, turn_id: str, revision: int = 0
    ) -> NormalizedEvent | None:
        kind = self._classify(raw_kind)
        if kind is None:
            raise ValueError(f"unsupported transcription event: {raw_kind!r}")
        if kind is NormalizedKind.FINAL:
            key = (turn_id, revision)
            if key in self._seen_final:
                return None  # 重复终稿：去重，不再次进队列
            self._seen_final.add(key)
        return NormalizedEvent(kind=kind, text=text or "", turn_id=turn_id, revision=revision)

    @staticmethod
    def _classify(raw_kind: str) -> NormalizedKind | None:
        if raw_kind == _RAW_DELTA or raw_kind == "delta":
            return NormalizedKind.DELTA
        if raw_kind == _RAW_COMPLETED or raw_kind == "completed":
            return NormalizedKind.FINAL
        return None

    def reset_turn(self, turn_id: str) -> None:
        self._seen_final = {key for key in self._seen_final if key[0] != turn_id}

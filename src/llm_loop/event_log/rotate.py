"""事件日志滚动管理器（design.md §2.2.2-C / spec §5.3）.

单会话事件日志达阈值/会话结束/时间周期时切分为多段文件归档存储；
跨段 replay 逐字节一致；归档检索接口可用。

滚动后文件布局: `event_logs/<session_id>/<segment_seq>.jsonl`
- 归档段只读（历史段）
- 活跃段仅追加（最大 segment_seq）
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from llm_loop.event_log.store import EventStore, _validate_session_id

logger = logging.getLogger(__name__)


@dataclass
class SegmentInfo:
    """段信息（design.md §2.2.2-C）."""

    session_id: str
    segment_seq: int
    event_count: int
    ts_first: str
    ts_last: str
    size_bytes: int
    is_active: bool


class RotateManager:
    """事件日志滚动管理器."""

    def __init__(
        self,
        event_store: EventStore,
        *,
        rotate_bytes: int = 10 * 1024 * 1024,
        rotate_days: int = 30,
        rotate_on_session_end: bool = True,
    ) -> None:
        self._store = event_store
        self._rotate_bytes = rotate_bytes
        self._rotate_days = rotate_days
        self._rotate_on_session_end = rotate_on_session_end

    def size_triggered(self, path: str | os.PathLike[str]) -> bool:
        """大小触发判定（stat 廉价，供 EventStore.append 每次追加内联检查）."""
        return (
            self._rotate_bytes > 0
            and os.path.exists(path)
            and os.path.getsize(path) >= self._rotate_bytes
        )

    def check_and_rotate(self, session_id: str) -> list[SegmentInfo]:
        """检测触发条件 → 触发滚动（关闭当前段为归档段 + 创建新活跃段）.

        Returns:
            新段信息列表（未触发返回空列表）.
        """
        if self._rotate_bytes == 0 and self._rotate_days == 0:
            return []

        # 多段形态：检查活跃段是否需要滚动
        if self._store._is_multi_segment(session_id):  # noqa: SLF001
            active_path = self._store._active_segment_path(session_id)  # noqa: SLF001
            if self._should_rotate_file(active_path):
                return self._rotate_multi_segment(session_id)
            return []

        # 单文件形态：检查是否需要迁移为多段
        single_path = self._store._path(session_id)  # noqa: SLF001
        if not os.path.exists(single_path):
            return []
        if self._should_rotate_file(single_path):
            return self._migrate_to_segments(session_id)
        return []

    def _should_rotate_file(self, path: str | os.PathLike[str]) -> bool:
        """检测文件是否触发滚动条件."""
        if not os.path.exists(path):
            return False
        size = os.path.getsize(path)
        if self._rotate_bytes > 0 and size >= self._rotate_bytes:
            return True
        if self._rotate_days > 0:
            events = self._read_events_from_file(path)
            if events:
                try:
                    first_ts = datetime.fromisoformat(events[0].ts)
                    last_ts = datetime.fromisoformat(events[-1].ts)
                    delta = (last_ts - first_ts).total_seconds()
                    if delta >= self._rotate_days * 86400:
                        return True
                except (ValueError, TypeError):
                    pass  # 时间戳解析失败跳过天数检查（fail-open）
        return False

    def _migrate_to_segments(self, session_id: str) -> list[SegmentInfo]:
        """首次滚动：单文件 → 多段目录（1.jsonl 归档 + 2.jsonl 活跃）."""
        single_path = self._store._path(session_id)  # noqa: SLF001
        seg_dir = self._store._segment_dir(session_id)  # noqa: SLF001
        try:
            os.makedirs(seg_dir, exist_ok=True)
            archived = os.path.join(seg_dir, "1.jsonl")
            shutil.move(single_path, archived)
            active = os.path.join(seg_dir, "2.jsonl")
            with open(active, "a", encoding="utf-8"):
                pass
        except OSError as exc:
            logger.warning("滚动迁移失败（fail-open）: %s", exc)
            return []
        return self.list_segments(self._store._dir, session_id)  # noqa: SLF001

    def _rotate_multi_segment(self, session_id: str) -> list[SegmentInfo]:
        """多段形态滚动：关闭活跃段 + 创建新活跃段."""
        seg_dir = self._store._segment_dir(session_id)  # noqa: SLF001
        try:
            segments = sorted(
                (
                    entry.path
                    for entry in os.scandir(seg_dir)
                    if entry.is_file() and entry.name.endswith(".jsonl")
                ),
                key=self._store._segment_seq,  # noqa: SLF001
            )
        except FileNotFoundError:
            segments = []
        if not segments:
            return []
        next_seq = self._store._segment_seq(segments[-1]) + 1  # noqa: SLF001
        new_active = os.path.join(seg_dir, f"{next_seq}.jsonl")
        try:
            with open(new_active, "a", encoding="utf-8"):
                pass
        except OSError as exc:
            logger.warning("新段创建失败（fail-open）: %s", exc)
            return []
        return self.list_segments(self._store._dir, session_id)  # noqa: SLF001

    @staticmethod
    def list_segments(event_logs_dir: str | Path, session_id: str) -> list[SegmentInfo]:
        """按 session_id 列出全部段（spec §5.3.1-5）."""
        try:
            session_id = _validate_session_id(session_id)
        except ValueError:
            return []
        seg_dir = os.path.join(os.fspath(event_logs_dir), session_id)
        if not os.path.isdir(seg_dir):
            return []
        segments = sorted(
            (
                entry.path
                for entry in os.scandir(seg_dir)
                if entry.is_file() and entry.name.endswith(".jsonl")
            ),
            key=lambda p: int(os.path.splitext(os.path.basename(p))[0]),
        )
        result: list[SegmentInfo] = []
        max_seq = (
            int(os.path.splitext(os.path.basename(segments[-1]))[0]) if segments else 0
        )
        for p in segments:
            events = RotateManager._read_events_from_file_static(p)
            seq = int(os.path.splitext(os.path.basename(p))[0])
            result.append(
                SegmentInfo(
                    session_id=session_id,
                    segment_seq=seq,
                    event_count=len(events),
                    ts_first=events[0].ts if events else "",
                    ts_last=events[-1].ts if events else "",
                    size_bytes=os.path.getsize(p),
                    is_active=seq == max_seq,
                )
            )
        return result

    @staticmethod
    def read_range(
        event_logs_dir: str | Path,
        session_id: str,
        *,
        time_range: tuple[str, str] | None = None,
        seq_range: tuple[int, int] | None = None,
    ) -> list:
        """按时间范围/事件 seq 范围检索特定段事件（spec §5.3.1-5）."""
        store = EventStore(event_logs_dir, enabled=True)
        events = store.read(session_id)
        if seq_range:
            lo, hi = seq_range
            events = [e for e in events if lo <= e.seq <= hi]
        if time_range:
            lo_ts, hi_ts = time_range
            events = [e for e in events if lo_ts <= e.ts <= hi_ts]
        return events

    def _read_events_from_file(self, path: str | os.PathLike[str]) -> list:
        return self._read_events_from_file_static(path)

    @staticmethod
    def _read_events_from_file_static(path: str | os.PathLike[str]) -> list:
        from llm_loop.event_log.model import parse_event_line

        events = []
        try:
            with open(path, encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    event = parse_event_line(line)
                    if event is not None:
                        events.append(event)
        except OSError:
            pass  # 文件读取失败跳过（fail-open）
        return events

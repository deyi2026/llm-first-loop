"""D1 事件日志存储 EventStore（design.md §2.2.2-B）.

事件日志按会话组织为 `data/event_logs/<session_id>.jsonl`（append-only，每行一个事件 JSON）。
- `append`: flock 写锁 + O_APPEND 单行写；seq 会话内自动续号（last_seq + 1）；
  目录不可写 → logger.warning 如实记录 + 返回 write_failed 哨兵标注（fail-open，不抛穿主循环）。
- `read`: 按 seq 升序返回全部事件；单行损坏/结构非法如实跳过并计数（不伪造）。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_loop.event_log.model import Event, serialize_event

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class EventStore:
    """事件日志存储（append-only 单一真相源）.

    事件文件布局: `event_logs_dir/<session_id>.jsonl`；跨进程并发写同会话
    经 fcntl.flock 写锁兜底保证行不交错（对齐 session.py 跨进程原子写约定）。
    """

    def __init__(
        self, event_logs_dir: str | Path, *, enabled: bool = True, hook_chain: Any | None = None
    ) -> None:
        self._dir = Path(event_logs_dir)
        self._enabled = enabled
        self._hook_chain = hook_chain
        # 最近一次 read 如实跳过的损坏行数（供调用方标注，不伪造）
        self.last_read_skipped: int = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _path(self, session_id: str) -> Path:
        """单文件形态路径（D1 既有）."""
        return self._dir / f"{session_id}.jsonl"

    def _segment_dir(self, session_id: str) -> Path:
        """多段形态目录路径."""
        return self._dir / session_id

    def _is_multi_segment(self, session_id: str) -> bool:
        """检测是否为多段形态（目录存在）."""
        return self._segment_dir(session_id).is_dir()

    def _active_segment_path(self, session_id: str) -> Path:
        """多段形态活跃段路径（最大 segment_seq 文件）."""
        seg_dir = self._segment_dir(session_id)
        segments = sorted(seg_dir.glob("*.jsonl"), key=lambda p: int(p.stem))
        return segments[-1] if segments else seg_dir / "1.jsonl"

    def _all_segment_paths(self, session_id: str) -> list[Path]:
        """多段形态全部段路径（按 segment_seq 递增）."""
        seg_dir = self._segment_dir(session_id)
        return sorted(seg_dir.glob("*.jsonl"), key=lambda p: int(p.stem))

    def _ensure_dir(self) -> bool:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            return True
        except OSError as exc:
            logger.warning("事件日志目录创建失败（fail-open）: %s: %s", self._dir, exc)
            return False

    def last_seq(self, session_id: str) -> int:
        """会话内最大 seq（无事件返回 0）."""
        if self._is_multi_segment(session_id):
            last = 0
            for p in self._all_segment_paths(session_id):
                try:
                    with p.open("r", encoding="utf-8") as f:
                        for raw in f:
                            line = raw.strip()
                            if not line:
                                continue
                            event = self._parse_line(line)
                            if event is not None and event.seq > last:
                                last = event.seq
                except OSError as exc:
                    logger.warning("事件日志读取失败（fail-open）: %s: %s", p, exc)
            return last
        p = self._path(session_id)
        if not p.exists():
            return 0
        last = 0
        try:
            with p.open("r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    event = self._parse_line(line)
                    if event is not None and event.seq > last:
                        last = event.seq
        except OSError as exc:
            logger.warning("事件日志读取失败（fail-open）: %s: %s", p, exc)
        return last

    def exists(self, session_id: str) -> bool:
        return self._path(session_id).exists() or self._is_multi_segment(session_id)

    def append(
        self,
        session_id: str,
        event_type: str,
        payload: dict,
    ) -> Event | None:
        """追加事件（flock 写锁覆盖"读续号 + 写"临界区；失败 fail-open 返回 None）.

        seq 续号与落盘在同一把写锁内完成，保证多进程并发写同会话时 seq 单调不重号
        （行不交错 + 序号不冲突）。目录不可写 → 如实记录并返回 None（不抛穿主循环）。

        Returns:
            已落盘事件；写入不可用/失败返回 None（调用方经日志感知，不抛穿主循环）。
        """
        if not self._enabled:
            return None
        if not self._ensure_dir():
            return None
        # 多段形态写入活跃段，单文件形态写入单文件
        if self._is_multi_segment(session_id):
            p = self._active_segment_path(session_id)
        else:
            p = self._path(session_id)
        try:
            with p.open("a+", encoding="utf-8") as f:
                try:
                    import fcntl

                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    try:
                        event = self._append_locked(f, session_id, event_type, payload)
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except ImportError:
                    event = self._append_locked(f, session_id, event_type, payload)
        except OSError as exc:
            logger.warning("事件日志写入失败（fail-open）: %s: %s", p, exc)
            return None
        return event

    def _append_locked(
        self,
        f,
        session_id: str,
        event_type: str,
        payload: dict,
    ) -> Event | None:
        """锁内执行：读最后有效 seq → 分配新 seq → 追加写（O_APPEND 语义）."""
        f.seek(0)
        last = 0
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            ev = self._parse_line(line)
            if ev is not None and ev.seq > last:
                last = ev.seq
        event = Event(
            event_id=str(uuid.uuid4()),
            session_id=session_id,
            seq=last + 1,
            type=event_type,
            ts=_now_iso(),
            payload=payload,
        )
        # D4 pre-step 钩子链（默认空零行为；filter 丢弃返回 None 不写入）
        chain = self._hook_chain
        if chain is not None:
            processed, audits = chain.process(event)
            if processed is None:
                self._write_hook_audit(audits)
                return None  # 被过滤：不写事件日志
            event = processed
            if audits:
                self._write_hook_audit(audits)
        f.write(serialize_event(event) + "\n")
        f.flush()
        return event

    def append_event(self, session_id: str, event: Event) -> Event | None:
        """追加预构造事件（重分配 seq + event_id + session_id，保留 type/ts/payload）.

        用于 fork 物理复制：保留源事件 type/ts/payload 原值，仅重分配 seq（last_seq+1）、
        event_id（新 uuid4）、session_id（新会话 ID）。fail-open 语义同 ``append``。
        """
        if not self._enabled:
            return None
        if not self._ensure_dir():
            return None
        p = self._path(session_id)
        try:
            with p.open("a+", encoding="utf-8") as f:
                try:
                    import fcntl

                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    try:
                        new_event = self._append_event_locked(f, session_id, event)
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except ImportError:
                    new_event = self._append_event_locked(f, session_id, event)
        except OSError as exc:
            logger.warning("事件日志写入失败（fail-open）: %s: %s", p, exc)
            return None
        return new_event

    def _append_event_locked(self, f, session_id: str, event: Event) -> Event:
        """锁内执行：读最后有效 seq → 重分配 → 追加写（保留 type/ts/payload）."""
        f.seek(0)
        last = 0
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            ev = self._parse_line(line)
            if ev is not None and ev.seq > last:
                last = ev.seq
        new_event = Event(
            event_id=str(uuid.uuid4()),
            session_id=session_id,
            seq=last + 1,
            type=event.type,
            ts=event.ts,
            payload=event.payload,
        )
        f.write(serialize_event(new_event) + "\n")
        f.flush()
        return new_event

    def read(self, session_id: str) -> list[Event]:
        """读全部事件（按 seq 升序；损坏行如实跳过；文件不存在返回空列表）.

        多段形态时跨段合并——按 segment_seq 递增依次读取各段事件，合并后按 seq 升序返回。
        """
        # 多段形态：跨段合并
        if self._is_multi_segment(session_id):
            events: list[Event] = []
            skipped = 0
            for p in self._all_segment_paths(session_id):
                try:
                    with p.open("r", encoding="utf-8") as f:
                        for raw in f:
                            line = raw.strip()
                            if not line:
                                continue
                            event = self._parse_line(line)
                            if event is not None:
                                events.append(event)
                            else:
                                skipped += 1
                except OSError as exc:
                    logger.warning("事件日志读取失败（fail-open）: %s: %s", p, exc)
            self.last_read_skipped = skipped
            events.sort(key=lambda e: e.seq)
            return events
        # 单文件形态（D1 既有）
        p = self._path(session_id)
        if not p.exists():
            return []
        events: list[Event] = []
        skipped = 0
        try:
            with p.open("r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    event = self._parse_line(line)
                    if event is not None:
                        events.append(event)
                    else:
                        skipped += 1  # 损坏行：如实跳过并计数（不伪造）
        except OSError as exc:
            logger.warning("事件日志读取失败（fail-open）: %s: %s", p, exc)
            return []
        self.last_read_skipped = skipped
        events.sort(key=lambda e: e.seq)
        return events

    def _write_hook_audit(self, audits: list) -> None:
        """写钩子审计到 _hook_audit.jsonl（append-only，不含原始 payload 敏感内容）."""
        if not audits:
            return
        import json as _json

        p = self._dir / "_hook_audit.jsonl"
        try:
            with p.open("a", encoding="utf-8") as f:
                for a in audits:
                    f.write(
                        _json.dumps(
                            {
                                "hook_name": a.hook_name,
                                "action_type": a.action_type,
                                "event_meta": a.event_meta,
                                "reason": a.reason,
                                "transformed_from": a.transformed_from,
                                "fail_open": a.fail_open,
                            },
                            ensure_ascii=False,
                        )
                       .replace("\n", " ")
                        + "\n"
                    )
        except OSError as exc:
            logger.warning("钩子审计写入失败（fail-open）: %s", exc)

    @staticmethod
    def _parse_line(line: str) -> Event | None:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        try:
            return Event(
                event_id=str(data["event_id"]),
                session_id=str(data["session_id"]),
                seq=int(data["seq"]),
                type=str(data["type"]),
                ts=str(data["ts"]),
                payload=data.get("payload") or {},
            )
        except (KeyError, ValueError, TypeError):
            return None


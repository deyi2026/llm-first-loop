"""D1 事件日志存储 EventStore（design.md §2.2.2-B）.

事件日志按会话组织为 `data/event_logs/<session_id>.jsonl`（append-only，每行一个事件 JSON）。
- `append`: flock 写锁 + O_APPEND 单行写；seq 会话内自动续号（last_seq + 1）；
  目录不可写 → logger.warning 如实记录 + 返回 write_failed 哨兵标注（fail-open，不抛穿主循环）。
- `read`: 按 seq 升序返回全部事件；单行损坏/结构非法如实跳过并计数（不伪造）。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_loop.event_log.model import Event, serialize_event

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class EventStore:
    """事件日志存储（append-only 单一真相源）.

    事件文件布局: `event_logs_dir/<session_id>.jsonl`（单文件）或
    `event_logs_dir/<session_id>/<segment_seq>.jsonl`（多段，滚动后）。
    并发写同会话经会话级稳定锁文件 `<sid>.lock`（flock）兜底——
    P1-1(2026-08-15，审计发现 #9)：滚动检查（含单文件→多段迁移）与追加
    在同一把锁内完成，跨进程并发不再因"检查在锁外"竞态丢事件；
    多段形态追加时 seq 全局续号（活跃段扫描 + 末归档段末事件取大）。
    """

    def __init__(
        self, event_logs_dir: str | Path, *, enabled: bool = True, hook_chain: Any | None = None
    ) -> None:
        self._dir = Path(event_logs_dir)
        self._enabled = enabled
        self._hook_chain = hook_chain
        # 最近一次 read 如实跳过的损坏行数（供调用方标注，不伪造）
        self.last_read_skipped: int = 0
        # P1-1: 滚动管理器（None = 不自动滚动，零回归；set_rotate_manager 显式接线）
        self._rotate_manager: Any | None = None
        # P1-1: append 路径滚动检查节流（天级触发需读文件，30s 粒度足够）
        self._rotate_checked_at: dict[str, float] = {}
        # P1-1: 会话级稳定锁的进程内回退（fcntl 不可用时）与锁表守护
        self._fallback_locks: dict[str, threading.Lock] = {}
        self._fallback_locks_guard = threading.Lock()

    def set_rotate_manager(self, manager: Any | None) -> None:
        """接线滚动管理器（P1-1：append/run 末自动检查滚动；None 解除接线）."""
        self._rotate_manager = manager

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

    # ── P1-1: 会话级稳定锁（滚动+追加同锁，闭合审计 #9 竞态）──
    @contextmanager
    def _session_flock(self, session_id: str):
        """会话级稳定锁（`<sid>.lock` flock；fcntl 不可用回退进程内锁；锁失败告警降级）.

        锁文件独立于事件文件——滚动会移动/新建事件文件（inode 变化），
        文件锁无法跨越迁移边界提供互斥，稳定锁文件可以。
        """
        lock_path = self._dir / f"{session_id}.lock"
        try:
            import fcntl
        except ImportError:
            with self._fallback_locks_guard:
                lock = self._fallback_locks.setdefault(session_id, threading.Lock())
            with lock:
                yield
            return
        try:
            with lock_path.open("a") as lf:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            # 锁不可用降级（fail-open 保可用性，与 append 的写失败语义一致）
            logger.warning("事件日志会话锁不可用（降级无锁写入）: %s", exc)
            yield

    def check_rotate(self, session_id: str) -> None:
        """公开滚动检查（引擎 run 末钩子/运维入口）：完整检查不节流，fail-open 不抛."""
        rm = self._rotate_manager
        if rm is None or not self._enabled:
            return
        try:
            with self._session_flock(session_id):
                rm.check_and_rotate(session_id)  # 锁内检查+迁移（审计 #9 竞态闭合）
            self._rotate_checked_at[session_id] = time.monotonic()
        except Exception:  # noqa: BLE001 — 滚动失败不影响主流程
            logger.warning("事件日志滚动检查失败（fail-open）: sid=%s", session_id, exc_info=True)

    def _rotate_check_throttled(self, session_id: str) -> None:
        """append 内联滚动检查：大小触发每次查（stat 廉价），天数触发 30s 节流（需读文件）."""
        rm = self._rotate_manager
        if rm is None:
            return
        try:
            p = (
                self._active_segment_path(session_id)
                if self._is_multi_segment(session_id)
                else self._path(session_id)
            )
            size_hit = rm.size_triggered(p)
            now = time.monotonic()
            if size_hit or now - self._rotate_checked_at.get(session_id, 0.0) >= 30.0:
                rm.check_and_rotate(session_id)  # 调用方已持会话锁
                self._rotate_checked_at[session_id] = now
        except Exception:  # noqa: BLE001
            logger.warning("事件日志滚动检查失败（fail-open）: sid=%s", session_id, exc_info=True)

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
        """追加事件（会话级稳定锁覆盖"滚动检查 + 读续号 + 写"临界区；失败 fail-open 返回 None）.

        P1-1(2026-08-15，审计发现 #9)：滚动检查（含单文件→多段迁移）与追加在
        同一把 `<sid>.lock` flock 内完成——跨进程并发写同会话 seq 单调不重号、
        迁移不丢事件。多段形态 seq 全局续号（活跃段 + 末归档段取大）。
        目录不可写 → 如实记录并返回 None（不抛穿主循环）。

        Returns:
            已落盘事件；写入不可用/失败返回 None（调用方经日志感知，不抛穿主循环）。
        """
        if not self._enabled:
            return None
        if not self._ensure_dir():
            return None
        with self._session_flock(session_id):
            # 锁内滚动检查（节流）：大小/天数触发时先迁移再选定写入路径
            self._rotate_check_throttled(session_id)
            # 多段形态写入活跃段，单文件形态写入单文件
            if self._is_multi_segment(session_id):
                p = self._active_segment_path(session_id)
            else:
                p = self._path(session_id)
            try:
                with p.open("a+", encoding="utf-8") as f:
                    event = self._append_locked(f, session_id, event_type, payload)
            except OSError as exc:
                logger.warning("事件日志写入失败（fail-open）: %s: %s", p, exc)
                return None
        return event

    def _global_last_seq_locked(self, f, session_id: str) -> int:
        """稳定锁内取会话全局最大 seq：活跃段文件扫描 + 末归档段末事件取大.

        seq 全局单调（本方法即保证者），故归档段中只需读末段的末事件。
        """
        last = 0
        f.seek(0)
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            ev = self._parse_line(line)
            if ev is not None and ev.seq > last:
                last = ev.seq
        segs = self._all_segment_paths(session_id)
        if len(segs) >= 2:  # 多段形态且有归档段
            for ev in self._read_last_event_of(segs[-2]):
                if ev.seq > last:
                    last = ev.seq
        return last

    @staticmethod
    def _read_last_event_of(path: Path) -> list[Event]:
        """读文件最后一个有效事件（单元素列表；无则空）."""
        last: Event | None = None
        try:
            with path.open("r", encoding="utf-8") as fp:
                for raw in fp:
                    line = raw.strip()
                    if not line:
                        continue
                    ev = EventStore._parse_line(line)
                    if ev is not None:
                        last = ev
        except OSError:
            pass  # 读取失败 fail-open（seq 退化为活跃段扫描结果）
        return [last] if last is not None else []

    def _append_locked(
        self,
        f,
        session_id: str,
        event_type: str,
        payload: dict,
    ) -> Event | None:
        """锁内执行：全局续号（多段取全局最大）→ 分配新 seq → 追加写（O_APPEND 语义）."""
        last = self._global_last_seq_locked(f, session_id)
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
        # P1-1: 与 append 同一把会话级稳定锁（fork 复制目标可能是多段形态）
        with self._session_flock(session_id):
            if self._is_multi_segment(session_id):
                p = self._active_segment_path(session_id)
            else:
                p = self._path(session_id)
            try:
                with p.open("a+", encoding="utf-8") as f:
                    new_event = self._append_event_locked(f, session_id, event)
            except OSError as exc:
                logger.warning("事件日志写入失败（fail-open）: %s: %s", p, exc)
                return None
        return new_event

    def _append_event_locked(self, f, session_id: str, event: Event) -> Event:
        """锁内执行：全局续号 → 重分配 → 追加写（保留 type/ts/payload）."""
        last = self._global_last_seq_locked(f, session_id)
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


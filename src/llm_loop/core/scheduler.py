"""调度提醒（DSH-PLUGINS-20260816 ②）：at/after/rate 提醒 → interop notify 注入会话.

设计（2026-08-17，协调通道定时化）:
- 工具侧: schedule 工具注册提醒（after 秒 / at 绝对时间 / rate 重复），落盘 data/schedule.json
- 检查侧: 常驻 daemon 线程（factory 装配）每 10s tick，到点触发 → 写 interop LFL inbox
  （lfl_to_dsh/pending/，topic=notify）——LFL 下轮 run 读到回显（web/飞书可见），
  不额外触发 run、不占会话锁（对齐协调通道协议）。
- 持久化: 提醒存 JSON，进程重启不丢；触发后移除；rate 提醒按间隔重复直到 max_count。
- fail-open: 存储读写失败不阻断主循环；线程异常自愈重试。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEDULE_PATH = Path("data/schedule.json")
_TICK_INTERVAL_S = 10.0  # 检查周期


class ScheduleEntry:
    """单条提醒."""

    def __init__(
        self,
        *,
        sid: str,
        message: str,
        trigger_at: float,  # epoch 秒（首次触发）
        repeat_interval: float = 0.0,  # 0=单次；>0 重复间隔
        max_count: int = 1,  # 最多触发次数
        created_at: float | None = None,
        count: int = 0,
    ) -> None:
        self.sid = sid
        self.message = message
        self.trigger_at = trigger_at
        self.repeat_interval = repeat_interval
        self.max_count = max_count
        self.created_at = created_at or time.time()
        self.count = count

    def to_dict(self) -> dict:
        return {
            "sid": self.sid,
            "message": self.message,
            "trigger_at": self.trigger_at,
            "repeat_interval": self.repeat_interval,
            "max_count": self.max_count,
            "created_at": self.created_at,
            "count": self.count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ScheduleEntry:
        return cls(
            sid=str(d.get("sid", "")),
            message=str(d.get("message", "")),
            trigger_at=float(d.get("trigger_at", 0)),
            repeat_interval=float(d.get("repeat_interval", 0) or 0),
            max_count=int(d.get("max_count", 1) or 1),
            created_at=float(d.get("created_at", 0) or 0),
            count=int(d.get("count", 0) or 0),
        )


class ScheduleStore:
    """提醒持久化存储（JSON 文件，fail-open）."""

    def __init__(self, path: Path | str = _SCHEDULE_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._entries: dict[str, ScheduleEntry] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for d in data:
                    e = ScheduleEntry.from_dict(d)
                    self._entries[e.sid] = e
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("schedule 存储加载失败（fail-open）: %s", exc)

    def _persist(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = [e.to_dict() for e in self._entries.values()]
            self._path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            logger.warning("schedule 存储写盘失败（fail-open）: %s", exc)

    def add(self, message: str, *, after: float = 0, at: float | None = None,
            repeat_interval: float = 0, max_count: int = 1) -> str:
        """新增提醒；返回 sid."""
        trigger = at if at is not None else time.time() + max(0.0, after)
        sid = f"sched-{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._entries[sid] = ScheduleEntry(
                sid=sid, message=message, trigger_at=trigger,
                repeat_interval=repeat_interval, max_count=max(1, max_count),
            )
        self._persist()
        return sid

    def cancel(self, sid: str) -> bool:
        with self._lock:
            removed = self._entries.pop(sid, None)
        if removed is not None:
            self._persist()
            return True
        return False

    def list(self) -> list[dict]:
        with self._lock:
            return [e.to_dict() for e in self._entries.values()]

    def due(self, now: float | None = None) -> list[ScheduleEntry]:
        """到点条目（不删除；由触发方处理后调用 complete/fail）."""
        now = now if now is not None else time.time()
        due: list[ScheduleEntry] = []
        with self._lock:
            for e in self._entries.values():
                if e.trigger_at <= now:
                    due.append(e)
        return due

    def mark_triggered(self, sid: str, now: float | None = None) -> None:
        """触发后推进：单次删除；重复按间隔重排，超 max_count 删除."""
        now = now if now is not None else time.time()
        with self._lock:
            e = self._entries.get(sid)
            if e is None:
                return
            e.count += 1
            if e.repeat_interval > 0 and e.count < e.max_count:
                e.trigger_at = now + e.repeat_interval
            else:
                self._entries.pop(sid, None)
        self._persist()


class SchedulerThread:
    """常驻检查线程：每 TICK 检查到点提醒 → 回调（默认写 interop notify）.

    回调由装配方注入（默认 _notify_via_interop）；异常自愈（单次 tick 失败不退出）。
    """

    def __init__(
        self,
        store: ScheduleStore,
        *,
        tick_interval: float = _TICK_INTERVAL_S,
        notify: Callable[[ScheduleEntry], None] | None = None,
    ) -> None:
        self._store = store
        self._tick = tick_interval
        self._notify = notify or self._notify_via_interop
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="scheduler-tick")
        self._thread.start()
        logger.info("调度提醒线程已启动（tick=%ss）", self._tick)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                for e in self._store.due():
                    try:
                        self._notify(e)
                    except Exception:  # noqa: BLE001 — 单条通知失败不中断
                        logger.warning("提醒触发失败（fail-open）: %s", e.sid, exc_info=True)
                    finally:
                        self._store.mark_triggered(e.sid)
            except Exception:  # noqa: BLE001 — tick 异常自愈
                logger.warning("调度 tick 异常（自愈继续）", exc_info=True)
            self._stop.wait(self._tick)

    @staticmethod
    def _notify_via_interop(entry: ScheduleEntry) -> None:
        """默认通知：写 interop LFL inbox（lfl_to_dsh/pending/，topic=notify）.

        LFL 下轮 run 读到并回显 [外部协调·from DSH] 或 [定时提醒]——web/飞书可见。
        """
        from datetime import datetime as _dt

        inbox = Path("data/interop/lfl_to_dsh/pending")
        inbox.mkdir(parents=True, exist_ok=True)
        now = _dt.now(UTC)
        ts = now.strftime("%Y%m%d-%H%M%S")
        fname = f"{now.strftime('%Y%m%d')}-sched-{ts}-{entry.sid}.json"
        payload = {
            "id": f"{now.strftime('%Y%m%d')}-sched-{entry.sid}",
            "from": "lfl-scheduler",
            "to": "lfl",
            "ts": now.isoformat(),
            "topic": "notify",
            "ref": entry.sid,
            "body": f"[定时提醒] {entry.message}",
            "status": "pending",
        }
        (inbox / fname).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

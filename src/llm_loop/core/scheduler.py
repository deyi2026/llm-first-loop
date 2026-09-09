"""调度提醒：持久化计时 + 通知交付 + 显式一次性 delegated wake。

程序只承载机械边界：schedule.json 持久化、跨进程 claim/lease、一次性 wake
capability 与失败重试。普通提醒只走 notify/UI，不进入模型 prompt；wake 只能消费
当前真人 run 降权委派出的同会话 capability，重启后 capability 不恢复。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# EVO-20260817 审查 P0-3: 基准统一——LFL_DATA_DIR 优先（与 interop/web 一致），
# 避免配置 LFL_DATA_DIR 时提醒写错位置静默丢失（原硬编码相对 data/）。
_SCHEDULE_PATH = Path(os.environ.get("LFL_DATA_DIR", "data")) / "schedule.json"
_TICK_INTERVAL_S = 10.0  # 检查周期

# Wake authorization is process-local, not Store-instance-local. Multiple ScheduleStore
# objects may legitimately point at the same schedule.json in one process (tests/hot rebuild/
# parallel service adapters); keeping grants per instance creates a same-PID steal race.
# Key by resolved store path + sid so all same-process views share the same capability, while
# nothing serializes to disk and process restart still drops authorization.
_WAKE_GRANT_LOCK = threading.Lock()
_WAKE_GRANTS: dict[tuple[str, str], Any] = {}


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
        wake: bool = False,
        session_id: str = "",
        lease_owner: str = "",
        lease_until: float = 0.0,
        wake_owner_pid: int = 0,
    ) -> None:
        self.sid = sid
        self.message = message
        self.trigger_at = trigger_at
        self.repeat_interval = repeat_interval
        self.max_count = max_count
        self.created_at = created_at or time.time()
        self.count = count
        self.wake = bool(wake)
        self.session_id = str(session_id or "")
        self.lease_owner = str(lease_owner or "")
        self.lease_until = float(lease_until or 0.0)
        self.wake_owner_pid = int(wake_owner_pid or 0)

    def to_dict(self) -> dict:
        return {
            "sid": self.sid,
            "message": self.message,
            "trigger_at": self.trigger_at,
            "repeat_interval": self.repeat_interval,
            "max_count": self.max_count,
            "created_at": self.created_at,
            "count": self.count,
            "wake": self.wake,
            "session_id": self.session_id,
            "lease_owner": self.lease_owner,
            "lease_until": self.lease_until,
            "wake_owner_pid": self.wake_owner_pid,
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
            wake=bool(d.get("wake", False)),
            session_id=str(d.get("session_id", "") or ""),
            lease_owner=str(d.get("lease_owner", "") or ""),
            lease_until=float(d.get("lease_until", 0) or 0),
            wake_owner_pid=int(d.get("wake_owner_pid", 0) or 0),
        )


class ScheduleStore:
    """提醒持久化存储（JSON 文件，fail-open + 跨进程写锁）.

    多进程（web/feishu/CLI）共享同一 data/ 目录、各自实例化本类——原实现
    _persist 全量覆写，后写进程用自己内存副本覆盖先写进程的条目（丢提醒）。
    修复（审查中危）: persist 前 flock 锁 + 重读磁盘合并（保留其他进程新增），
    与 session.py _session_lock 对齐（非 POSIX 回退进程内锁）。
    """

    def __init__(self, path: Path | str = _SCHEDULE_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._entries: dict[str, ScheduleEntry] = {}
        # wake grant 只存在模块级进程内 capability registry；磁盘只保存意图/owner PID。
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

    def refresh(self) -> None:
        """读侧同步（2026-08-27 BUGFIX 配套）: 以磁盘 SoT 重载内存.

        其他 Store 实例/进程 add 后本实例 due() 立即可见。
        磁盘不存在/损坏 → 保持内存现状（fail-open，不静默清空——
        磁盘损坏可能是暂时性 IO，清空会经 due 触发后的 mark_triggered
        把空状态写回磁盘造成真丢失）。
        """
        try:
            if not self._path.exists():
                return
            data = json.loads(self._path.read_text(encoding="utf-8"))
            with self._lock:
                self._entries = {e.sid: e for e in (ScheduleEntry.from_dict(d) for d in data)}
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("schedule 存储刷新失败（fail-open，沿用内存）: %s", exc)

    @contextmanager
    def _file_lock(self) -> Iterator[None]:
        """跨进程写锁（flock LOCK_EX；非 POSIX 回退进程内锁，对齐 session.py）."""
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        try:
            import fcntl
        except ImportError:
            with self._lock:
                yield
            return
        try:
            with lock_path.open("a", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            logger.warning("schedule 文件锁不可用（fail-open，并发保护降级）: %s", exc)
            yield

    def _persist(self) -> None:
        """跨进程安全持久化: 锁内重读磁盘 → 合并（保留其他进程新增）→ 覆写.

        注意: 删除类操作必须走 _mutate（先重读磁盘再删），否则磁盘上已删条目
        会被合并逻辑读回（本实现 _persist 仅为内存已与磁盘同步时的落盘兜底）。
        """
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._file_lock():
                # 重读磁盘（其他进程可能新增/删除条目）
                disk: dict[str, ScheduleEntry] = {}
                if self._path.exists():
                    try:
                        disk_data = json.loads(self._path.read_text(encoding="utf-8"))
                        for d in disk_data:
                            e = ScheduleEntry.from_dict(d)
                            disk[e.sid] = e
                    except (OSError, json.JSONDecodeError, ValueError, TypeError):
                        disk = {}  # 磁盘损坏 → 以内存为准（fail-open）
                # 合并: 内存为主；磁盘上本进程没有的条目保留（防覆盖丢）
                with self._lock:
                    merged = dict(disk)
                    merged.update(self._entries)
                    self._entries = merged
                    data = [e.to_dict() for e in self._entries.values()]
                self._path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            logger.warning("schedule 存储写盘失败（fail-open）: %s", exc)

    def _mutate(self, fn: Callable[[dict[str, ScheduleEntry]], None]) -> None:
        """锁内读-改-写（跨进程安全）：重读磁盘到内存 → 应用操作 → 覆写.

        删除/修改类操作必须走本方法：先以磁盘最新状态为基底，再应用操作，
        避免"内存已删、persist 又读回"或"覆盖其他进程新增"两类丢数据。
        """
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._file_lock():
                # 以磁盘为基底重建内存
                self._entries.clear()
                if self._path.exists():
                    try:
                        disk_data = json.loads(self._path.read_text(encoding="utf-8"))
                        for d in disk_data:
                            e = ScheduleEntry.from_dict(d)
                            self._entries[e.sid] = e
                    except (OSError, json.JSONDecodeError, ValueError, TypeError):
                        self._entries.clear()  # 磁盘损坏 → 空基底（fail-open）
                with self._lock:
                    fn(self._entries)
                    data = [e.to_dict() for e in self._entries.values()]
                self._path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            logger.warning("schedule 存储写盘失败（fail-open）: %s", exc)

    def add(
        self,
        message: str,
        *,
        after: float = 0,
        at: float | None = None,
        repeat_interval: float = 0,
        max_count: int = 1,
        wake: bool = False,
        session_id: str = "",
        wake_grant: Any = None,
    ) -> str:
        """新增提醒；返回 sid."""
        trigger = at if at is not None else time.time() + max(0.0, after)
        sid = f"sched-{uuid.uuid4().hex[:8]}"
        entry = ScheduleEntry(
            sid=sid,
            message=message,
            trigger_at=trigger,
            repeat_interval=repeat_interval,
            max_count=max(1, max_count),
            wake=wake,
            session_id=session_id,
            wake_owner_pid=(os.getpid() if wake and wake_grant is not None else 0),
        )
        # Capability must exist before the persisted entry becomes claimable. This removes
        # the after=0 window where a scheduler could see wake=True but no grant yet.
        if wake and wake_grant is not None:
            self._set_wake_grant(sid, wake_grant)
        self._mutate(lambda es: es.__setitem__(sid, entry))
        return sid

    def _wake_grant_key(self, sid: str) -> tuple[str, str]:
        return (str(self._path.resolve()), str(sid or ""))

    def _set_wake_grant(self, sid: str, grant: Any) -> None:
        with _WAKE_GRANT_LOCK:
            _WAKE_GRANTS[self._wake_grant_key(sid)] = grant

    def wake_grant(self, sid: str) -> Any | None:
        """返回本进程同一 schedule SoT 的 wake capability；永不从磁盘恢复。"""
        with _WAKE_GRANT_LOCK:
            return _WAKE_GRANTS.get(self._wake_grant_key(sid))

    def clear_wake_grant(self, sid: str) -> None:
        with _WAKE_GRANT_LOCK:
            _WAKE_GRANTS.pop(self._wake_grant_key(sid), None)

    def cancel(self, sid: str) -> bool:
        removed: list[bool] = []
        self._mutate(lambda es: removed.append(es.pop(sid, None) is not None))
        self.clear_wake_grant(sid)
        return bool(removed and removed[0])

    def list(self) -> list[dict]:
        """列出当前提醒（读侧 SoT: 先 refresh 磁盘，与 due() 一致——
        其他实例/进程的 add/cancel 立即可见，本实例内存不滞后）."""
        self.refresh()
        with self._lock:
            return [e.to_dict() for e in self._entries.values()]

    def due(self, now: float | None = None) -> list[ScheduleEntry]:
        """只读到点条目；兼容测试/诊断，不承担多进程 claim。"""
        self.refresh()
        now = now if now is not None else time.time()
        with self._lock:
            return [
                e
                for e in self._entries.values()
                if e.trigger_at <= now and (not e.lease_owner or e.lease_until <= now)
            ]

    def claim_due(
        self, owner: str, *, now: float | None = None, lease_s: float = 30.0
    ) -> list[ScheduleEntry]:
        """跨进程原子 claim 到点条目，避免 Web/Feishu scheduler 双触发。"""
        now = now if now is not None else time.time()
        claimed: list[ScheduleEntry] = []

        def _claim(entries: dict[str, ScheduleEntry]) -> None:
            for e in entries.values():
                if e.trigger_at > now:
                    continue
                if e.lease_owner and e.lease_until > now:
                    continue
                if (
                    e.wake
                    and e.wake_owner_pid
                    and e.wake_owner_pid != os.getpid()
                    and _pid_alive(e.wake_owner_pid)
                ):
                    continue
                e.lease_owner = owner
                e.lease_until = now + max(1.0, lease_s)
                claimed.append(e)

        self._mutate(_claim)
        return claimed

    def retry_later(self, sid: str, owner: str, *, delay_s: float = 5.0) -> None:
        """触发失败/会话忙时释放 claim 并持久化退避，避免每 tick 风暴。"""
        now = time.time()

        def _retry(entries: dict[str, ScheduleEntry]) -> None:
            e = entries.get(sid)
            if e is None or (e.lease_owner and e.lease_owner != owner):
                return
            e.trigger_at = max(e.trigger_at, now + max(1.0, delay_s))
            e.lease_owner = ""
            e.lease_until = 0.0

        self._mutate(_retry)

    def mark_triggered(self, sid: str, now: float | None = None, *, owner: str = "") -> None:
        """成功 ack 后推进；owner 非空时只允许 claim 持有者提交。"""
        now = now if now is not None else time.time()
        completed: list[bool] = []

        def _ack(entries: dict[str, ScheduleEntry]) -> None:
            e = entries.get(sid)
            if e is None or (owner and e.lease_owner != owner):
                return
            completed.append(True)
            _advance(entries, sid, now)

        self._mutate(_ack)
        if completed:
            self.clear_wake_grant(sid)


def _pid_alive(pid: int) -> bool:
    """本机 PID 是否仍存活；仅用于避免其它服务进程抢走内存 wake grant。"""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _advance(entries: dict[str, ScheduleEntry], sid: str, now: float) -> None:
    """mark_triggered 内部推进逻辑（供 _mutate 调用）."""
    e = entries.get(sid)
    if e is None:
        return
    e.count += 1
    e.lease_owner = ""
    e.lease_until = 0.0
    if e.repeat_interval > 0 and e.count < e.max_count:
        e.trigger_at = now + e.repeat_interval
    else:
        entries.pop(sid, None)


class SchedulerThread:
    """常驻检查线程：每 TICK 检查到点提醒 → 回调（默认写 interop notify）.

    回调由装配方注入（默认 _notify_via_interop）；异常自愈（单次 tick 失败不退出）。
    """

    def __init__(
        self,
        store: ScheduleStore,
        *,
        tick_interval: float = _TICK_INTERVAL_S,
        notify: Callable[[ScheduleEntry], bool | None] | None = None,
    ) -> None:
        self._store = store
        self._tick = tick_interval
        self._notify = notify or self._notify_via_interop
        self._owner = f"scheduler-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scheduler-tick")
        self._thread.start()
        logger.info("调度提醒线程已启动（tick=%ss）", self._tick)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                for e in self._store.claim_due(self._owner, lease_s=max(30.0, self._tick * 3)):
                    try:
                        outcome = self._notify(e)
                        if outcome is False:
                            self._store.retry_later(
                                e.sid, self._owner, delay_s=max(5.0, self._tick)
                            )
                            continue
                        self._store.mark_triggered(e.sid, owner=self._owner)
                    except Exception:  # noqa: BLE001 — 单条失败保留提醒并退避重试
                        logger.warning("提醒触发失败（保留并重试）: %s", e.sid, exc_info=True)
                        self._store.retry_later(e.sid, self._owner, delay_s=max(5.0, self._tick))
            except Exception:  # noqa: BLE001 — tick 异常自愈
                logger.warning("调度 tick 异常（自愈继续）", exc_info=True)
            self._stop.wait(self._tick)

    @staticmethod
    def _notify_via_interop(entry: ScheduleEntry) -> None:
        """默认通知：写 interop LFL inbox（lfl_to_dsh/pending/，topic=notify）.

        LFL 下轮 run 读到并回显 [外部协调·from DSH] 或 [定时提醒]——web/飞书可见。
        """
        from datetime import datetime as _dt

        # EVO-20260817-6efeb7a0: 基准统一（P0-3）——LFL_DATA_DIR 优先，与 interop/web 一致
        inbox = Path(os.environ.get("LFL_DATA_DIR", "data")) / "interop" / "lfl_to_dsh" / "pending"
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

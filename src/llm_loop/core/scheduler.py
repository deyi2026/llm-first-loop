"""调度提醒：持久化计时 + 通知交付 + 显式一次性 delegated wake。

程序只承载机械边界：schedule.json 持久化、跨进程 claim/lease、一次性 wake
capability 与失败重试。普通提醒只走 notify/UI，不进入模型 prompt；wake 只能消费
当前真人 run 降权委派出的同会话 capability。token 对象不落盘；已授权的一次性
委派通过独立私有签名账本恢复，started/revoked 不可再次启动。无账本的历史提醒
仍需同会话真人 run re-arm，有界退避窗口内未恢复才降级为通知。
"""

from __future__ import annotations

import hashlib
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
from typing import Any, NamedTuple

from llm_loop.core import schedule_task_grant as task_grant
from llm_loop.runtime.resolver import business_config_snapshot

logger = logging.getLogger(__name__)

_SCHEDULER_CONFIG = business_config_snapshot("scheduler")

# EVO-20260817 审查 P0-3: 基准统一——LFL_DATA_DIR 优先（与 interop/web 一致），
# 避免配置 LFL_DATA_DIR 时提醒写错位置静默丢失（原硬编码相对 data/）。
_SCHEDULE_PATH = Path(_SCHEDULER_CONFIG.get("LFL_DATA_DIR", "data")) / "schedule.json"
_TICK_INTERVAL_S = 10.0  # 检查周期

# EVO-20260919-f119847d: wake 交付瞬态失败的有界指数退避（秒）与双上限。
# 30s→1m→2m→4m→8m 后按 8m 平台重试；次数上限或"首败+30min"窗口任一到达即降级。
WAKE_RETRY_DELAYS_S = (30.0, 60.0, 120.0, 240.0, 480.0)
WAKE_MAX_RETRIES = 10
WAKE_RETRY_WINDOW_S = 1800.0

# 交付回调哨兵：返回本对象表示交付方已自行 defer（条目保留、下次触发时间已排好），
# SchedulerThread 既不得 mark_triggered 消费，也不得 retry_later 覆盖退避节奏。
WAKE_DEFERRED = object()

# Wake authorization is process-local, not Store-instance-local. Multiple ScheduleStore
# objects may legitimately point at the same schedule.json in one process (tests/hot rebuild/
# parallel service adapters); keeping grants per instance creates a same-PID steal race.
# Key by resolved store path + sid so all same-process views share the same capability, while
# nothing serializes to disk and process restart still drops authorization.
_WAKE_GRANT_LOCK = threading.Lock()
_WAKE_GRANTS: dict[tuple[str, str], Any] = {}

# ── Phase3 M4（G4）：事件谓词闭集与登记（白名单扩展点）──────────────────
# 扩展流程：先扩 EVENT_PREDICATE_KINDS（代码评审门），再 register_event_predicate
# 登记求值器。求值器契约：fn(ref: str) -> bool；异常一律按 False（fail-safe 回退
# 到超时分支，不阻断调度主链路）。求值只读外部状态，不得有副作用。
EVENT_PREDICATE_KINDS = frozenset({"job_terminal", "generation_reached", "action_settled"})
_EVENT_PREDICATES: dict[str, Callable[[str], bool]] = {}
_EVENT_PREDICATE_LOCK = threading.Lock()
_EVENT_PREDICATE_WARNED: set[str] = set()


def register_event_predicate(kind: str, evaluator: Callable[[str], bool]) -> str:
    """登记事件谓词求值器；闭集外 kind 拒绝（ValueError）。返回 kind。"""
    if kind not in EVENT_PREDICATE_KINDS:
        raise ValueError(f"event predicate kind not in closed set: {kind}")
    with _EVENT_PREDICATE_LOCK:
        _EVENT_PREDICATES[kind] = evaluator
    return kind


def _predicate_satisfied(entry: ScheduleEntry) -> bool:
    """求值条目谓词；未登记/异常按未满足（fail-safe 到超时分支）。"""
    kind = entry.event_predicate
    if not kind:
        return False
    with _EVENT_PREDICATE_LOCK:
        fn = _EVENT_PREDICATES.get(kind)
    if fn is None:
        if kind not in _EVENT_PREDICATE_WARNED:
            _EVENT_PREDICATE_WARNED.add(kind)
            logger.warning("event predicate kind 未登记求值器，回退超时分支: %s", kind)
        return False
    try:
        return bool(fn(entry.predicate_ref))
    except Exception:  # noqa: BLE001 — 求值器异常 fail-safe
        logger.warning("event predicate 求值异常，回退超时分支 kind=%s", kind, exc_info=True)
        return False


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
        task_mode: str = "",  # remind | task_once | task_recurring（空=老数据）
        wake_dispatch: str = "",  # session | new_session（空=按 mode 推导）
        wake_fires_total: int = 0,  # 常驻授权总次数
        wake_fires_used: int = 0,  # 已消费次数（与授权账本同步）
        wake_expires_at: float = 0.0,  # 常驻授权有效期（epoch 秒）
        wake_external: bool = False,  # 是否允许外部副作用
        wake_workdir: str = "",  # 授权时钉死的工作目录（R7）
        wake_pool: str = "",  # Goal 级授权池（v1.1，显式加入才写入）
        wake_child_session_id: str = "",  # 最近一次分叉出的会话
        created_at: float | None = None,
        count: int = 0,
        wake: bool = False,
        session_id: str = "",
        lease_owner: str = "",
        lease_until: float = 0.0,
        wake_owner_pid: int = 0,
        wake_started_at: float = 0.0,
        retry_count: int = 0,
        retry_deadline_at: float = 0.0,
        goal_id: str = "",
        goal_generation: str = "",
        subject_refs: list | None = None,
        scheduled_trigger_at: float | None = None,
        wake_delivery_state: str = "scheduled",
        wake_wait_reason: str = "",
        event_predicate: str = "",
        predicate_ref: str = "",
        armed: bool = False,
        event_won: str = "",
        event_fired_at: float = 0.0,
    ) -> None:
        self.sid = sid
        self.message = message
        self.trigger_at = trigger_at
        self.repeat_interval = repeat_interval
        self.max_count = max_count
        self.task_mode = str(task_mode or "")
        self.wake_dispatch = str(wake_dispatch or "")
        self.wake_fires_total = int(wake_fires_total or 0)
        self.wake_fires_used = int(wake_fires_used or 0)
        self.wake_expires_at = float(wake_expires_at or 0.0)
        self.wake_external = bool(wake_external)
        self.wake_workdir = str(wake_workdir or "")
        self.wake_pool = str(wake_pool or "")
        self.wake_child_session_id = str(wake_child_session_id or "")
        self.created_at = created_at or time.time()
        self.count = count
        self.wake = bool(wake)
        self.session_id = str(session_id or "")
        self.lease_owner = str(lease_owner or "")
        self.lease_until = float(lease_until or 0.0)
        self.wake_owner_pid = int(wake_owner_pid or 0)
        self.wake_started_at = float(wake_started_at or 0.0)
        self.retry_count = int(retry_count or 0)
        self.retry_deadline_at = float(retry_deadline_at or 0.0)
        self.goal_id = str(goal_id or "")
        self.goal_generation = str(goal_generation or "")
        self.scheduled_trigger_at = trigger_at if scheduled_trigger_at is None else float(scheduled_trigger_at)
        self.wake_delivery_state = str(wake_delivery_state)
        self.wake_wait_reason = str(wake_wait_reason)
        # antidrift R1: 排程时模型自报的结构化对象引用（封闭枚举三类）；缺省空=行为与现状一致
        self.subject_refs: list[dict] = [
            dict(r) for r in (subject_refs or []) if isinstance(r, dict)
        ]
        # Phase3 M4（G4）：事件谓词唤醒。armed=True 表示等待「事件先于超时」；
        # 谓词不携带授权语义（D8）——授权仍由 wake_grant 委派链独占。
        self.event_predicate = str(event_predicate or "")
        self.predicate_ref = str(predicate_ref or "")
        self.armed = bool(armed) and bool(self.event_predicate)
        self.event_won = str(event_won or "")
        self.event_fired_at = float(event_fired_at or 0.0)

    def to_dict(self) -> dict:
        d = {
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
            "wake_started_at": self.wake_started_at,
            "retry_count": self.retry_count,
            "retry_deadline_at": self.retry_deadline_at,
            "goal_id": self.goal_id,
            "goal_generation": self.goal_generation,
            "scheduled_trigger_at": self.scheduled_trigger_at,
            "wake_delivery_state": self.wake_delivery_state,
            "wake_wait_reason": self.wake_wait_reason,
        }
        # 仅非空时含键：不带 refs 的条目形态与现状逐字一致（回归项）
        if self.subject_refs:
            d["subject_refs"] = [dict(r) for r in self.subject_refs]
        # Phase3 M4：谓词字段只在设置时写入（回归安全：老数据回读/快照零变化）
        if self.event_predicate:
            d["event_predicate"] = self.event_predicate
            d["predicate_ref"] = self.predicate_ref
            d["armed"] = self.armed
        if self.event_won:
            d["event_won"] = self.event_won
        if self.event_fired_at:
            d["event_fired_at"] = self.event_fired_at
        # 任务语义字段只在显式设置时写入：老条目形态与现状逐字一致（回归项）
        if self.task_mode:
            d["task_mode"] = self.task_mode
            d["wake_dispatch"] = self.wake_dispatch
            d["wake_fires_total"] = self.wake_fires_total
            d["wake_fires_used"] = self.wake_fires_used
            d["wake_expires_at"] = self.wake_expires_at
            d["wake_external"] = self.wake_external
            if self.wake_workdir:
                d["wake_workdir"] = self.wake_workdir
            if self.wake_pool:
                d["wake_pool"] = self.wake_pool
            if self.wake_child_session_id:
                d["wake_child_session_id"] = self.wake_child_session_id
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ScheduleEntry:
        return cls(
            sid=str(d.get("sid", "")),
            message=str(d.get("message", "")),
            trigger_at=float(d.get("trigger_at", 0)),
            repeat_interval=float(d.get("repeat_interval", 0) or 0),
            max_count=int(d.get("max_count", 1) or 1),
            task_mode=str(d.get("task_mode", "") or ""),
            wake_dispatch=str(d.get("wake_dispatch", "") or ""),
            wake_fires_total=int(d.get("wake_fires_total", 0) or 0),
            wake_fires_used=int(d.get("wake_fires_used", 0) or 0),
            wake_expires_at=float(d.get("wake_expires_at", 0.0) or 0.0),
            wake_external=bool(d.get("wake_external", False)),
            wake_workdir=str(d.get("wake_workdir", "") or ""),
            wake_pool=str(d.get("wake_pool", "") or ""),
            wake_child_session_id=str(d.get("wake_child_session_id", "") or ""),
            created_at=float(d.get("created_at", 0) or 0),
            count=int(d.get("count", 0) or 0),
            wake=bool(d.get("wake", False)),
            session_id=str(d.get("session_id", "") or ""),
            lease_owner=str(d.get("lease_owner", "") or ""),
            lease_until=float(d.get("lease_until", 0) or 0),
            wake_owner_pid=int(d.get("wake_owner_pid", 0) or 0),
            wake_started_at=float(d.get("wake_started_at", 0.0) or 0.0),
            retry_count=int(d.get("retry_count", 0) or 0),
            retry_deadline_at=float(d.get("retry_deadline_at", 0.0) or 0.0),
            goal_id=str(d.get("goal_id", "") or ""),
            goal_generation=str(d.get("goal_generation", "") or ""),
            scheduled_trigger_at=d.get("scheduled_trigger_at"),
            wake_delivery_state=str(d.get("wake_delivery_state") or "scheduled"),
            wake_wait_reason=str(d.get("wake_wait_reason") or ""),
            subject_refs=[
                dict(r) for r in (d.get("subject_refs") or []) if isinstance(r, dict)
            ],
            event_predicate=str(d.get("event_predicate", "") or ""),
            predicate_ref=str(d.get("predicate_ref", "") or ""),
            armed=bool(d.get("armed", False)),
            event_won=str(d.get("event_won", "") or ""),
            event_fired_at=float(d.get("event_fired_at", 0.0) or 0.0),
        )


class WakeDefer(NamedTuple):
    """defer_wake_retry 的机械结果。

    present=条目仍在磁盘且未被其他 claim 接管；exhausted=重试预算耗尽
    （双上限任一到达，调用方应降级为通知并消费）；retry_count/next_delay_s
    供审计记录。
    """

    present: bool
    exhausted: bool
    retry_count: int
    next_delay_s: float


# ---- DRC T2 写路径（DESIGN-20261007-durable-run-contract §6 首迁 client）----
# 主状态覆写禁止裸 write_text / fail-open 吞写失败（契约红线 1）：
# tmp 独占创建 → flush+file fsync → os.replace → 目录 fsync；torn write 只可能
# 停留在 tmp，读者任意时刻看到旧全文或新全文。失败有界重试后显式抛
# SchedulePersistError（tick 循环捕获并记录=显式降级，不新增持久化面）。
_PERSIST_ATTEMPTS = 3
_PERSIST_RETRY_DELAY_S = 0.05


class SchedulePersistError(OSError):
    """主状态确定未提交（replace 前失败/锁失败/目录不可用）。"""

    outcome = "definitely_not_committed"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.operation = ""
        self.sid = ""
        self.retry_safe = False

    def bind(
        self, *, operation: str = "", sid: str = "", retry_safe: bool = False
    ) -> SchedulePersistError:
        self.operation = str(operation or "")
        self.sid = str(sid or "")
        self.retry_safe = bool(retry_safe)
        return self


class ScheduleCommitUncertainError(SchedulePersistError):
    """replace 已发生，但 directory fsync 最终失败；禁止盲重放语义 mutation。"""

    outcome = "commit_outcome_uncertain"

    def __init__(
        self,
        *,
        path: Path,
        expected_sha256: str,
        visible_state: str,
        cause: OSError,
    ) -> None:
        super().__init__(f"schedule 主状态 replace 已生效但 durability 未确认: {cause}")
        self.path = str(path)
        self.expected_sha256 = str(expected_sha256)
        self.visible_state = str(visible_state)
        self.cause = cause
        self.retry_safe = False

    def __str__(self) -> str:
        base = super().__str__()
        return (
            f"{base}; outcome={self.outcome}; visible_state={self.visible_state}; "
            f"retry_safe={'true' if self.retry_safe else 'false'}; "
            f"operation={self.operation or '-'}; sid={self.sid or '-'}"
        )


def _write_temp_exclusive(temp: Path, text: str) -> None:
    """独占创建 tmp 并完整写入 + file fsync（半写只会污染 tmp，不碰主状态）。"""
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(directory: Path) -> None:
    """目录 fsync：让 rename 本身在掉电后可见（对齐 wake_authority._write）。"""
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_state_atomic(path: Path, text: str) -> None:
    """原子可见性阶段：tmp → file fsync → replace；任何失败都清理 tmp."""
    temp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:12]}.tmp")
    try:
        _write_temp_exclusive(temp, text)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _payload_visible_state(path: Path, payload: str) -> str:
    """持有 store flock 时核当前文件是否逐字等于 intended payload."""
    try:
        current = path.read_text(encoding="utf-8")
    except OSError:
        return "unreadable"
    return "matches" if current == payload else "mismatch"


class ScheduleStore:
    """提醒持久化存储（JSON 文件，T2 原子覆写 + 读侧 fail-open + 跨进程写锁）.

    多进程（web/feishu/CLI）共享同一 data/ 目录、各自实例化本类——原实现
    _persist 全量覆写，后写进程用自己内存副本覆盖先写进程的条目（丢提醒）。
    修复（审查中危）: persist 前 flock 锁 + 重读磁盘合并（保留其他进程新增），
    与 session.py _session_lock 对齐（非 POSIX 回退进程内锁）。
    """

    def __init__(self, path: Path | str = _SCHEDULE_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._entries: dict[str, ScheduleEntry] = {}
        from llm_loop.core.trace_leak.wake_authority import WakeAuthorizationStore

        self._authority = WakeAuthorizationStore(self._path)
        # Token 对象只存在进程内；独立私有账本保存已授权范围与一次消费状态。
        self._load()

    def _load(self) -> None:
        report = self.recover()
        if report["corrupt"]:
            logger.error("schedule 主状态自检：文件损坏，按空基底继续（读侧 fail-open）: %s", report)
        elif report["invalid_entries"] or report["orphan_tmp"]:
            logger.warning("schedule 主状态自检发现异常项: %s", report)
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for d in data:
                    e = ScheduleEntry.from_dict(self._authority.restore_fields(d))
                    self._entries[e.sid] = e
        except (OSError, json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("schedule 存储加载失败（fail-open）: %s", exc)

    def recover(self) -> dict[str, Any]:
        """DRC T2 启动自检（只读不修复）：截断/损坏/无效条目/孤儿 tmp 计数。

        §7.1 决策：仅启动（_load）时调用。损坏基底的处理策略不变（读侧
        fail-open），但必须留下可审计报告，不再静默空基底。
        """
        report: dict[str, Any] = {
            "path": str(self._path), "exists": False, "readable": False,
            "corrupt": False, "entries": 0, "invalid_entries": 0, "orphan_tmp": 0,
        }
        if self._path.exists():
            report["exists"] = True
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, ValueError):
                data = None
                report["corrupt"] = True
            if isinstance(data, list):
                report["readable"] = True
                for d in data:
                    report["entries"] += 1
                    if not isinstance(d, dict):
                        report["invalid_entries"] += 1
                        continue
                    try:
                        ScheduleEntry.from_dict(d)
                    except (ValueError, TypeError):
                        report["invalid_entries"] += 1
            elif data is not None:
                report["corrupt"] = True
        if self._path.parent.exists():
            report["orphan_tmp"] = len(list(self._path.parent.glob(self._path.name + ".*.tmp")))
        return report

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
                self._entries = {
                    e.sid: e
                    for e in (ScheduleEntry.from_dict(self._authority.restore_fields(d)) for d in data)
                }
        except (OSError, json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("schedule 存储刷新失败（fail-open，沿用内存）: %s", exc)

    @contextmanager
    def _file_lock(self) -> Iterator[None]:
        """跨进程写锁（flock LOCK_EX；POSIX 锁失败 fail-closed）.

        非 POSIX 无 fcntl 时保留进程内兼容 fallback；但在支持 fcntl 的运行时，
        锁文件打开/加锁失败不能继续无锁写，否则不满足 T2 单写者语义。
        """
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        try:
            import fcntl
        except ImportError:
            with self._lock:
                yield
            return
        handle = None
        try:
            handle = lock_path.open("a", encoding="utf-8")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            if handle is not None:
                handle.close()
            raise SchedulePersistError(
                f"schedule 跨进程文件锁不可用，拒绝无锁写入: {exc}"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def _commit_state(self, data: list[dict]) -> None:
        """T2 提交：replace 前重写可重试；replace 后只重试 directory fsync."""
        payload = json.dumps(data, ensure_ascii=False)
        payload_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        last: OSError = OSError("schedule persist: no attempt recorded")
        for attempt in range(1, _PERSIST_ATTEMPTS + 1):
            if attempt > 1:
                time.sleep(_PERSIST_RETRY_DELAY_S * (attempt - 1))
            try:
                _write_state_atomic(self._path, payload)
                break
            except OSError as exc:
                last = exc
                logger.warning(
                    "schedule 主状态 replace 前写失败（attempt %s/%s）: %s",
                    attempt,
                    _PERSIST_ATTEMPTS,
                    exc,
                )
        else:
            logger.error(
                "schedule 主状态确定未提交（replace 前重试 %s 次耗尽）: %s",
                _PERSIST_ATTEMPTS,
                last,
            )
            raise SchedulePersistError(
                f"schedule 主状态确定未提交（replace 前重试 {_PERSIST_ATTEMPTS} 次后放弃）: {last}"
            ) from last

        last_dir: OSError = OSError("schedule directory fsync: no attempt recorded")
        for attempt in range(1, _PERSIST_ATTEMPTS + 1):
            if attempt > 1:
                time.sleep(_PERSIST_RETRY_DELAY_S * (attempt - 1))
            try:
                _fsync_directory(self._path.parent)
                return
            except OSError as exc:
                last_dir = exc
                logger.warning(
                    "schedule 主状态 replace 后目录 fsync 失败（attempt %s/%s）: %s",
                    attempt,
                    _PERSIST_ATTEMPTS,
                    exc,
                )
        visible_state = _payload_visible_state(self._path, payload)
        logger.error(
            "schedule 主状态 commit outcome uncertain：replace 已发生但目录 fsync 重试耗尽；"
            "visible_state=%s expected_sha256=%s",
            visible_state,
            payload_sha256,
        )
        raise ScheduleCommitUncertainError(
            path=self._path,
            expected_sha256=payload_sha256,
            visible_state=visible_state,
            cause=last_dir,
        ) from last_dir

    def _persist(self) -> None:
        """跨进程安全持久化: 锁内重读磁盘 → 合并（保留其他进程新增）→ T2 原子覆写.

        注意: 删除类操作必须走 _mutate（先重读磁盘再删），否则磁盘上已删条目
        会被合并逻辑读回（本实现 _persist 仅为内存已与磁盘同步时的落盘兜底）。
        写失败不再 fail-open：_commit_state 重试耗尽后抛 SchedulePersistError。
        """
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SchedulePersistError(f"schedule 主状态目录不可用: {exc}") from exc
        with self._file_lock():
            # 重读磁盘（其他进程可能新增/删除条目）
            disk: dict[str, ScheduleEntry] = {}
            if self._path.exists():
                try:
                    disk_data = json.loads(self._path.read_text(encoding="utf-8"))
                    for d in disk_data:
                        e = ScheduleEntry.from_dict(self._authority.restore_fields(d))
                        disk[e.sid] = e
                except (OSError, json.JSONDecodeError, ValueError, TypeError, AttributeError):
                    disk = {}  # 磁盘损坏 → 以内存为准（读侧 fail-open）
            # 合并: 内存为主；磁盘上本进程没有的条目保留（防覆盖丢）
            with self._lock:
                merged = dict(disk)
                merged.update(self._entries)
                self._entries = merged
                data = [e.to_dict() for e in self._entries.values()]
                try:
                    self._authority.preserve_fields(data)
                except OSError as exc:
                    # 授权投影失败=authority 域降级（wake 投递依赖其非致命，
                    # 见 test_failed_authority_persistence_prevents_model_work）：
                    # 跳过本次主状态提交、不写半套状态；内存已应用，下次提交重试。
                    logger.warning("schedule 主状态提交中止（授权投影写失败）: %s", exc)
                    return
            self._commit_state(data)

    def _mutate(self, fn: Callable[[dict[str, ScheduleEntry]], None]) -> None:
        """锁内读-改-写（跨进程安全）：重读磁盘到内存 → 应用操作 → T2 原子覆写.

        删除/修改类操作必须走本方法：先以磁盘最新状态为基底，再应用操作，
        避免"内存已删、persist 又读回"或"覆盖其他进程新增"两类丢数据。
        replace 前确定未提交时回滚内存 mutation；replace 后 uncertain 保留 intended
        内存态并显式抛 ScheduleCommitUncertainError，调用方不得盲重放。授权投影
        （preserve_fields）失败是 authority 域降级：跳过本次提交不写半套状态。
        """
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SchedulePersistError(f"schedule 主状态目录不可用: {exc}") from exc
        with self._file_lock():
            # 以磁盘为基底重建内存
            self._entries.clear()
            if self._path.exists():
                try:
                    disk_data = json.loads(self._path.read_text(encoding="utf-8"))
                    for d in disk_data:
                        e = ScheduleEntry.from_dict(self._authority.restore_fields(d))
                        self._entries[e.sid] = e
                except (OSError, json.JSONDecodeError, ValueError, TypeError, AttributeError):
                    self._entries.clear()  # 磁盘损坏 → 空基底（读侧 fail-open）
            with self._lock:
                before_data = [e.to_dict() for e in self._entries.values()]
                fn(self._entries)
                data = [e.to_dict() for e in self._entries.values()]
                try:
                    self._authority.preserve_fields(data)
                except OSError as exc:
                    # 同 _persist：authority 域降级语义，非主状态 fail-open 回潮。
                    logger.warning("schedule 主状态提交中止（授权投影写失败）: %s", exc)
                    return
            try:
                self._commit_state(data)
            except ScheduleCommitUncertainError:
                raise
            except SchedulePersistError:
                with self._lock:
                    self._entries = {}
                    for d in before_data:
                        e = ScheduleEntry.from_dict(d)
                        self._entries[e.sid] = e
                raise

    def _mutate_reconciled(
        self,
        fn: Callable[[dict[str, ScheduleEntry]], None],
        *,
        operation: str,
        sid: str = "",
        retry_safe: bool,
        accept_visible_match: bool,
    ) -> None:
        """Bind mutation identity and reconcile post-replace uncertainty mechanically.

        visible_state=matches is an exact whole-file readback while the store flock is
        still held. Internal lifecycle transitions may accept that visible state and
        continue; user-facing creation/cancellation keep surfacing uncertainty because
        durability confirmation itself is part of their contract.
        """
        try:
            self._mutate(fn)
        except ScheduleCommitUncertainError as exc:
            exc.bind(operation=operation, sid=sid, retry_safe=retry_safe)
            if accept_visible_match and exc.visible_state == "matches":
                logger.warning(
                    "schedule mutation durability uncertain but visible state matches; "
                    "reconciled without semantic replay: operation=%s sid=%s",
                    operation,
                    sid or "-",
                )
                return
            raise
        except SchedulePersistError as exc:
            exc.bind(operation=operation, sid=sid, retry_safe=retry_safe)
            raise

    def add(
        self, message: str, *, after: float = 0, at: float | None = None,
        repeat_interval: float = 0, max_count: int = 1, wake: bool = False,
        session_id: str = "", wake_grant: Any = None,
        goal_id: str = "", goal_generation: str = "",
        subject_refs: list | None = None,
        event_predicate: str = "",
        predicate_ref: str = "",
        task_mode: str = "",
        wake_dispatch: str = "",
        wake_fires: int = 0,
        wake_expires_at: float = 0.0,
        wake_external: bool = False,
        wake_workdir: str = "",
        wake_pool: str = "",
    ) -> str:
        """新增提醒；返回 sid.

        Phase3 M4（G4）：event_predicate 要求 ①wake=True（谓词不携带授权语义，
        授权仍由 wake_grant 委派链独占，D8）②非重复条目（armed 一次性语义）。
        违反即 ValueError——失败在落盘之前，不留半登记状态。

        task_mode=task_recurring 表示「常驻授权」：真人创建时一次签发 N 次，
        每次到点开新会话执行（设计 §2/§5）。次数与 max_count 取同一值，
        额度用尽/过期即降级为通知。
        """
        mode = str(task_mode or (task_grant.MODE_ONCE if wake else task_grant.MODE_REMIND))
        if mode not in (task_grant.MODE_REMIND, task_grant.MODE_ONCE, task_grant.MODE_RECURRING):
            raise ValueError(f"unknown task_mode: {mode}")
        standing = mode == task_grant.MODE_RECURRING
        if mode == task_grant.MODE_REMIND:
            wake = False
        if standing:
            if repeat_interval <= 0:
                raise ValueError("task_recurring requires repeat_interval>0")
            if int(wake_fires) < 1:
                raise ValueError("task_recurring requires wake_fires>=1")
            if float(wake_expires_at or 0.0) <= time.time():
                raise ValueError("task_recurring requires a future wake_expires_at (hard cap 90d)")
            if float(wake_expires_at) > time.time() + task_grant.MAX_WAKE_EXPIRY_S:
                raise ValueError("task_recurring wake_expires_at exceeds the 90d hard cap")
            if int(wake_fires) > task_grant.MAX_WAKE_FIRES:
                raise ValueError("task_recurring wake_fires exceeds the 90 hard cap")
            if not str(wake_workdir or "").strip():
                # 空 workdir 会让投递侧跳过 R7 目录固定，等于把「授权时钉死的目录」变成任意目录。
                raise ValueError("task_recurring requires a pinned workdir")
            wake = True
            max_count = int(wake_fires)  # 额度即上限：不会出现「第 N+1 次」无授权 run
            wake_dispatch = wake_dispatch or task_grant.DISPATCH_NEW_SESSION
        if wake_pool:
            # Goal 级授权池：一个 goal 一份额度，成员资格写进签名 scope；
            # 不允许用别的 goal 借池，也不允许非常驻条目入池。
            if not standing:
                raise ValueError("wake_pool requires task_recurring")
            if not goal_id or wake_pool != goal_id:
                raise ValueError("wake_pool must equal a non-empty goal_id")
        trigger = at if at is not None else time.time() + max(0.0, after)
        if event_predicate:
            if not wake:
                raise ValueError("event_predicate requires wake=True (D8: 谓词不携带授权语义)")
            if repeat_interval:
                raise ValueError("event_predicate requires non-repeating entry (armed 一次性)")
            if event_predicate not in EVENT_PREDICATE_KINDS:
                raise ValueError(f"event_predicate not in closed set: {event_predicate}")
            if not predicate_ref:
                raise ValueError("event_predicate requires predicate_ref")
        sid = f"sched-{uuid.uuid4().hex[:8]}"
        entry = ScheduleEntry(
            sid=sid, message=message, trigger_at=trigger,
            repeat_interval=repeat_interval, max_count=max(1, max_count),
            wake=wake, session_id=session_id,
            wake_owner_pid=(os.getpid() if wake and wake_grant is not None else 0),
            goal_id=goal_id,
            goal_generation=goal_generation,
            subject_refs=subject_refs,
            event_predicate=event_predicate,
            predicate_ref=predicate_ref,
            armed=bool(event_predicate),  # M4：登记即 armed，一次性即焚
            task_mode=(mode if wake else ""),
            wake_dispatch=(str(wake_dispatch or "") if wake else ""),
            wake_fires_total=(int(wake_fires) if standing else 0),
            wake_fires_used=0,
            wake_expires_at=(float(wake_expires_at or 0.0) if standing else 0.0),
            wake_external=(bool(wake_external) if standing else False),
            wake_workdir=(str(wake_workdir or "") if standing else ""),
            wake_pool=(str(wake_pool or "") if standing else ""),
        )
        # Capability must exist before the persisted entry becomes claimable. This removes
        # the after=0 window where a scheduler could see wake=True but no grant yet.
        if wake and wake_grant is not None:
            authority_issued = self._authority.issue(entry.to_dict(), wake_grant)
            self._set_wake_grant(sid, wake_grant)
        else:
            authority_issued = False
        try:
            self._mutate(lambda es: es.__setitem__(sid, entry))
        except ScheduleCommitUncertainError as exc:
            exc.bind(operation="add", sid=sid, retry_safe=False)
            raise
        except SchedulePersistError as exc:
            # 主状态确定未提交：先行签发的 wake authority 不得留下可恢复 pending。
            self.clear_wake_grant(sid)
            if authority_issued:
                try:
                    self._authority.revoke(sid)
                except (OSError, ValueError, TypeError):
                    # 无 schedule entry 时孤儿 authority 不能自行触发；保留审计痕迹，
                    # 但不要用补偿异常覆盖 definitely-not-committed 事实。
                    logger.warning(
                        "schedule add 失败后的 wake authority 补偿失败 sid=%s",
                        sid,
                        exc_info=True,
                    )
            exc.bind(operation="add", sid=sid, retry_safe=True)
            raise
        return sid

    def _wake_grant_key(self, sid: str) -> tuple[str, str]:
        return (str(self._path.resolve()), str(sid or ""))

    def _set_wake_grant(self, sid: str, grant: Any) -> None:
        with _WAKE_GRANT_LOCK:
            _WAKE_GRANTS[self._wake_grant_key(sid)] = grant

    def wake_grant(self, sid: str) -> Any | None:
        """返回进程内 capability；恢复必须单独验证私有授权账本。"""
        with _WAKE_GRANT_LOCK:
            return _WAKE_GRANTS.get(self._wake_grant_key(sid))

    def clear_wake_grant(self, sid: str) -> None:
        with _WAKE_GRANT_LOCK:
            _WAKE_GRANTS.pop(self._wake_grant_key(sid), None)

    def note_wake_started(self, sid: str, *, owner: str = "") -> None:
        """EVO-20260919-f119847d: 启动自动续跑前先落 started 标记（幂等）。

        该标记让跨进程/重启后仍能区分"grant 已消费（run 已启动过，stale 条目）"
        与"grant 随 owner 死亡丢失（可 re-arm 抢救）"，保证 re-arm 永不会把
        同一条目二次启动为自治 run。
        """
        now = time.time()
        marked: list[bool] = []

        def _mark(entries: dict[str, ScheduleEntry]) -> None:
            e = entries.get(sid)
            if owner and (e is None or e.lease_owner != owner or e.lease_until <= now or e.scheduled_trigger_at > now):
                raise ValueError("wake claim cancelled, replaced or expired before admission")
            if e is not None and e.wake and e.wake_started_at <= 0.0:
                used = self._authority.consume(e.to_dict(), occurrence=e.count + 1)
                e.wake_started_at = now
                if e.task_mode == task_grant.MODE_RECURRING:
                    # 账本权威计数镜像到条目，供 UI 与终结判定；一次性委派保持 0。
                    e.wake_fires_used = int(used)
                e.wake_delivery_state = "started"
                e.wake_wait_reason = ""
                marked.append(True)
            elif owner:
                raise ValueError("wake already started")

        self._mutate_reconciled(
            _mark,
            operation="note_wake_started",
            sid=sid,
            retry_safe=False,
            accept_visible_match=True,
        )
        if owner and not marked:
            raise ValueError("wake start could not be persisted")

    def note_wake_child(self, sid: str, child_session_id: str, *, owner: str = "") -> None:
        """记录常驻授权本次分叉出的会话（审计/Web 面板跳转用，best-effort）。"""

        def _note(entries: dict[str, ScheduleEntry]) -> None:
            e = entries.get(sid)
            if e is None or (owner and e.lease_owner != owner):
                return
            e.wake_child_session_id = str(child_session_id or "")

        self._mutate_reconciled(
            _note,
            operation="note_wake_child",
            sid=sid,
            retry_safe=True,
            accept_visible_match=True,
        )

    def defer_wake_retry(self, sid: str, *, owner: str = "", reason: str = "") -> WakeDefer:
        """EVO-20260919-f119847d: wake 交付瞬态失败 → 有界指数退避。

        推迟：retry_count+1、trigger_at=now+退避间隔、释放 lease（条目保留，
        下次到点重新 claim）。exhausted=True：重试预算耗尽（WAKE_MAX_RETRIES 次
        或首败+WAKE_RETRY_WINDOW_S 窗口任一到达）——保留 lease 供调用方降级
        通知后 mark_triggered 消费。present=False：条目已被他方消费/接管，
        调用方无需处理。
        """
        now = time.time()
        result: list[WakeDefer] = [WakeDefer(False, False, 0, 0.0)]

        def _defer(entries: dict[str, ScheduleEntry]) -> None:
            e = entries.get(sid)
            if e is None:
                return
            if owner and e.lease_owner and e.lease_owner != owner:
                return
            deadline = e.retry_deadline_at
            if deadline <= 0.0:
                deadline = now + WAKE_RETRY_WINDOW_S
                e.retry_deadline_at = deadline
            count = e.retry_count + 1
            delay = WAKE_RETRY_DELAYS_S[min(count - 1, len(WAKE_RETRY_DELAYS_S) - 1)]
            e.retry_count = count
            e.wake_wait_reason = reason
            e.wake_delivery_state = "waiting_human" if reason == "grant_lost_owner_dead" else "retrying"
            if count >= WAKE_MAX_RETRIES or now + delay >= deadline:
                result[0] = WakeDefer(True, True, count, delay)
                return
            e.trigger_at = now + delay
            e.lease_owner = ""
            e.lease_until = 0.0
            result[0] = WakeDefer(True, False, count, delay)

        self._mutate_reconciled(
            _defer,
            operation="defer_wake_retry",
            sid=sid,
            retry_safe=True,
            accept_visible_match=True,
        )
        return result[0]

    def cancel(self, sid: str) -> bool:
        removed: list[bool] = []
        self._mutate_reconciled(
            lambda es: removed.append(es.pop(sid, None) is not None),
            operation="cancel",
            sid=sid,
            retry_safe=True,
            accept_visible_match=False,
        )
        self.clear_wake_grant(sid)
        self._authority.revoke(sid)
        return bool(removed and removed[0])

    def upgrade_to_standing(
        self,
        sid: str,
        *,
        grant: Any,
        session_id: str,
        fires: int,
        expires_at: float,
        external: bool,
        workdir: str,
        pool: str = "",
    ) -> None:
        """把已有周期提醒原地升级为常驻授权任务（保留 sid/正文/节奏）。

        先签账本、后写条目：账本签发失败则条目原样不动；条目写入失败最多留下
        一份未被引用的授权（到期即失效），不会出现「条目自称能唤醒、账本却没有授权」。
        """
        row = next((entry for entry in self.list() if entry["sid"] == sid), None)
        if row is None:
            raise KeyError(sid)
        if float(row.get("repeat_interval") or 0.0) <= 0:
            raise ValueError("only periodic entries can become standing")
        if row.get("wake"):
            raise ValueError("entry already has a wake grant")
        if pool and pool != str(row.get("goal_id") or ""):
            raise ValueError("wake pool must equal the entry's goal_id")
        if not str(workdir or "").strip():
            raise ValueError("standing grants require a pinned workdir")
        prospective = dict(row)
        prospective.update({
            "session_id": session_id,
            "wake": True,
            "task_mode": task_grant.MODE_RECURRING,
            "wake_dispatch": task_grant.DISPATCH_NEW_SESSION,
            "wake_fires_total": int(fires),
            "wake_fires_used": 0,
            "wake_expires_at": float(expires_at),
            "wake_external": bool(external),
            "wake_workdir": str(workdir or ""),
            "wake_pool": pool,
            "count": 0,
            "max_count": int(fires),
            "wake_started_at": 0.0,
            "wake_delivery_state": "",
            "wake_wait_reason": "",
            "wake_owner_pid": 0,
        })
        if not self._authority.issue(prospective, grant):
            raise ValueError("standing grant rejected")
        applied: list[bool] = []

        def _apply(entries: dict[str, ScheduleEntry]) -> None:
            entry = entries.get(sid)
            if entry is None:
                return
            entry.session_id = session_id
            entry.wake = True
            entry.task_mode = task_grant.MODE_RECURRING
            entry.wake_dispatch = task_grant.DISPATCH_NEW_SESSION
            entry.wake_fires_total = int(fires)
            entry.wake_fires_used = 0
            entry.wake_expires_at = float(expires_at)
            entry.wake_external = bool(external)
            entry.wake_workdir = str(workdir or "")
            entry.wake_pool = pool
            entry.count = 0
            entry.max_count = int(fires)
            entry.wake_started_at = 0.0
            entry.wake_delivery_state = ""
            entry.wake_wait_reason = ""
            entry.wake_owner_pid = 0
            applied.append(True)

        self._mutate_reconciled(
            _apply,
            operation="upgrade_to_standing",
            sid=sid,
            retry_safe=True,
            accept_visible_match=True,
        )
        if not applied:
            raise ValueError("schedule entry vanished during upgrade")

    def revoke_wake_grant(self, sid: str) -> bool:
        """只撤销常驻授权，条目本身继续按通知提醒（schedule_cancel --revoke-only）。

        先降级条目再撤销账本：任一步失败都只会更保守（通知），不会留下
        「条目写着唤醒、账本却已撤销」的可疑中间态继续被 claim。
        """
        row = next((e for e in self.list() if e["sid"] == sid), None)
        if row is None or not row.get("wake"):
            return False
        downgraded: list[bool] = []

        def _downgrade(entries: dict[str, ScheduleEntry]) -> None:
            e = entries.get(sid)
            if e is None or not e.wake:
                return
            e.wake = False
            e.task_mode = ""
            e.wake_dispatch = ""
            e.wake_fires_total = 0
            e.wake_fires_used = 0
            e.wake_expires_at = 0.0
            e.wake_external = False
            e.wake_workdir = ""
            e.wake_pool = ""
            e.wake_started_at = 0.0
            e.wake_delivery_state = "scheduled"
            e.wake_wait_reason = ""
            e.wake_owner_pid = 0
            downgraded.append(True)

        self._mutate_reconciled(
            _downgrade,
            operation="revoke_wake_grant",
            sid=sid,
            retry_safe=True,
            accept_visible_match=True,
        )
        if not downgraded:
            return False
        self.clear_wake_grant(sid)
        self._authority.revoke(sid)
        return True

    def note_wake_waiting(self, sid: str, reason: str) -> None:
        def _note(entries: dict[str, ScheduleEntry]) -> None:
            e = entries.get(sid)
            if e is not None:
                e.wake_delivery_state = "queued"
                e.wake_wait_reason = reason

        self._mutate_reconciled(
            _note,
            operation="note_wake_waiting",
            sid=sid,
            retry_safe=True,
            accept_visible_match=True,
        )

    def authority_state(self, sid: str) -> str:
        row = next((e for e in self.list() if e["sid"] == sid), None)
        return self._authority.state(row) if row is not None else "missing"

    def pool_facts(self, pool_id: str) -> dict[str, Any] | None:
        """Goal 级授权池的只读投影（创建时对齐规格、面板展示用）。"""
        return self._authority.pool_facts(pool_id) if pool_id else None

    def recover_wake_grant(self, sid: str) -> Any | None:
        row = next((e for e in self.list() if e["sid"] == sid), None)
        if row is None or row.get("wake_started_at"):
            return None
        grant = self._authority.recover(row)
        if grant is None:
            return None
        adopted: list[bool] = []

        def _adopt(entries: dict[str, ScheduleEntry]) -> None:
            e = entries.get(sid)
            if e is None or e.wake_started_at > 0 or self._authority.state(e.to_dict()) != "pending":
                return
            e.wake_owner_pid = os.getpid()
            e.wake_delivery_state = "scheduled"
            e.wake_wait_reason = ""
            adopted.append(True)

        self._mutate_reconciled(
            _adopt,
            operation="recover_wake_grant",
            sid=sid,
            retry_safe=True,
            accept_visible_match=True,
        )
        if not adopted:
            return None
        self._set_wake_grant(sid, grant)
        logger.info("wake delegation recovered from private authority sid=%s", sid)
        return grant

    def wake_delivery_facts(self, row: dict[str, Any]) -> dict[str, Any]:
        if not row.get("wake"):
            return {}
        state = str(row.get("wake_delivery_state") or "scheduled")
        reason = str(row.get("wake_wait_reason") or "")
        authority_state = self._authority.state(row)
        if row.get("wake_started_at") or authority_state in {"started", "revoked"}:
            state = "inactive"
            reason = "delegation_consumed"
        elif self.wake_grant(str(row["sid"])) is None and authority_state != "pending":
            state = "waiting_human"
            reason = "grant_unavailable"
        return {"delivery_state": state, "wait_reason": reason}

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
                e for e in self._entries.values()
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
                live_other_owner = (
                    e.wake_owner_pid and e.wake_owner_pid != os.getpid()
                    and _pid_alive(e.wake_owner_pid)
                )
                # Recover a dead owner's verified delegation before checking due time.
                # Otherwise an older shared scheduler can win every due-time claim and
                # keep deferring a grant it cannot restore. No provider starts here.
                if e.wake and e.wake_started_at <= 0 and not live_other_owner and self.wake_grant(e.sid) is None:
                    grant = self._authority.recover(e.to_dict())
                    if grant is not None:
                        e.wake_owner_pid = os.getpid()
                        e.wake_delivery_state = "retrying" if e.retry_count else "scheduled"
                        e.wake_wait_reason = ""
                        self._set_wake_grant(e.sid, grant)
                        logger.info("wake delegation recovered before due sid=%s", e.sid)
                # Phase3 M4（G4）：事件谓词竞速。
                # 谓词分支先判（armed 且谓词满足）→ 提前 claim 且同 tick 双真时
                # 事件确定性取胜；超时分支（trigger_at 已到、谓词未满足）→ armed
                # 即焚，事件后到只记录不唤醒。竞速判定= flock 内字段翻转（CAS
                # 语义），不比较墙钟（D3）；armed 一次性即焚：事件重放/重复求值
                # 不会造成二次唤醒。
                if e.armed and _predicate_satisfied(e):
                    e.event_won = e.event_won or "event"
                    e.event_fired_at = e.event_fired_at or now
                    e.armed = False
                elif e.trigger_at > now:
                    continue
                elif e.armed:
                    e.armed = False
                    e.event_won = e.event_won or "timeout"
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

        self._mutate_reconciled(
            _claim,
            operation="claim_due",
            retry_safe=True,
            accept_visible_match=True,
        )
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

        self._mutate_reconciled(
            _retry,
            operation="retry_later",
            sid=sid,
            retry_safe=True,
            accept_visible_match=True,
        )

    def mark_triggered(
        self, sid: str, now: float | None = None, *, owner: str = ""
    ) -> None:
        """成功 ack 后推进；owner 非空时只允许 claim 持有者提交。"""
        now = now if now is not None else time.time()
        completed: list[bool] = []
        final: list[bool] = []

        def _ack(entries: dict[str, ScheduleEntry]) -> None:
            e = entries.get(sid)
            if e is None or (owner and e.lease_owner != owner):
                return
            completed.append(True)
            final.append(task_grant.is_final_fire(e))
            _advance(entries, sid, now)

        self._mutate_reconciled(
            _ack,
            operation="mark_triggered",
            sid=sid,
            retry_safe=True,
            accept_visible_match=True,
        )
        if completed and final and final[0]:
            # 常驻授权额度未尽时保留凭据，下一周期继续复用同一签名记录。
            self.clear_wake_grant(sid)
            self._authority.revoke(sid)


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
    """mark_triggered 内部推进逻辑（供 _mutate 调用）.

    设计 §5.4：锚定推进（scheduled_trigger_at + interval），避免 tick 延迟累积成
    相位漂移；停机跨过多个周期时最多立即补一次。常驻授权每次推进后重置「本次
    已启动」标记，额度/有效期由 ``task_grant.is_final_fire`` 决定是否终结。
    """
    e = entries.get(sid)
    if e is None:
        return
    e.count += 1
    e.lease_owner = ""
    e.lease_until = 0.0
    standing = task_grant.is_standing(e)
    keep = e.repeat_interval > 0 and e.count < e.max_count
    if standing and keep and task_grant.is_final_fire(e):
        keep = False
    if not keep:
        entries.pop(sid, None)
        return
    if standing:
        e.trigger_at = task_grant.next_anchor(e.scheduled_trigger_at, e.repeat_interval, now)
        e.scheduled_trigger_at = e.trigger_at
        e.wake_started_at = 0.0
        e.wake_owner_pid = 0
        e.wake_delivery_state = "scheduled"
        e.wake_wait_reason = ""
        e.retry_count = 0
        e.retry_deadline_at = 0.0
        return
    e.trigger_at = now + e.repeat_interval


def wake_goal_binding_state(
    entry: ScheduleEntry,
    resolver: Callable[[str], tuple[str, str] | None] | None,
) -> str:
    """Return unbound/active/stale/unknown for a persisted wake Goal binding.

    Only entries that carry a Goal identity are lifecycle-qualified. Legacy/unbound wake
    entries preserve historical behavior. Resolver exceptions are unknown and must never
    authorize an autonomous model run.
    """
    if not entry.goal_id:
        return "unbound"
    if resolver is None:
        return "unknown"
    try:
        current = resolver(entry.session_id)
    except Exception:  # noqa: BLE001 — unknown is fail-closed for autonomous wake
        return "unknown"
    if current is None:
        return "stale"
    goal_id, generation = current
    if str(goal_id) != entry.goal_id or str(generation) != entry.goal_generation:
        return "stale"
    return "active"


def rearm_wake_grants(
    store: ScheduleStore,
    session_id: str,
    ingress: Any,
    *,
    goal_binding_resolver: Callable[[str], tuple[str, str] | None] | None = None,
) -> int:
    """EVO-20260919-f119847d: 同会话下一次真人 run 重铸丢失的 wake grant。

    全部满足才重铸：
    - ingress 是未委派的真人 human token（委派 token 不能再委派——wake
      不可递归的禁令不变，也不存在伪造授权路径）；
    - 条目 wake=True 且 session_id 精确等于本次真人 run 会话；
    - 条目仍在（已消费/降级/取消的不存在）；
    - wake_started_at 为 0（run 已启动过的一律不重启第二次）；
    - 本进程无该 grant；wake_owner_pid 为 0 或已死（owner 存活时 grant 在
      那边；等于本进程 pid 时表示本进程 grant 已被消费）。

    重铸后 owner 归属迁至当前进程并重置退避预算：授权是新的、窗口也是新的，
    且仍受双上限约束；re-arm 只由真人 run 驱动，无自动放大回路。
    """
    if ingress is None or getattr(ingress, "delegated", True):
        return 0
    target = str(session_id or "")
    if not target:
        return 0
    from llm_loop.core.trace_leak.ingress_token import delegate_ingress

    rearmed = 0
    for snapshot in store.list():
        if not snapshot.get("wake") or str(snapshot.get("session_id", "")) != target:
            continue
        sid = str(snapshot.get("sid", ""))
        if not sid or store.wake_grant(sid) is not None:
            continue
        binding_state = wake_goal_binding_state(
            ScheduleEntry.from_dict(snapshot), goal_binding_resolver
        )
        if binding_state == "stale":
            # Goal is terminal/replaced: stale delegated intent is consumed as no-op.
            store.cancel(sid)
            logger.info("stale wake 已取消（goal binding terminal/replaced）sid=%s", sid)
            continue
        if binding_state == "unknown":
            # Read uncertainty cannot mint fresh autonomous authority.
            continue
        if float(snapshot.get("wake_started_at", 0.0) or 0.0) > 0.0:
            continue
        owner_pid = int(snapshot.get("wake_owner_pid", 0) or 0)
        if owner_pid == os.getpid():
            continue
        if owner_pid and _pid_alive(owner_pid):
            continue
        try:
            grant = delegate_ingress(ingress, entry="schedule_wake")
        except ValueError:
            logger.warning("wake grant re-arm 委派被拒（跳过）sid=%s", sid)
            continue
        adopted: list[bool] = []

        def _adopt(
            entries: dict[str, ScheduleEntry], _sid: str = sid,
            _grant: Any = grant, _adopted: list[bool] = adopted,
        ) -> None:
            e = entries.get(_sid)
            if e is None or e.session_id != target or e.wake_started_at > 0:
                return
            if wake_goal_binding_state(e, goal_binding_resolver) not in {"active", "unbound"}:
                return
            try:
                store._authority.issue(e.to_dict(), _grant)
            except ValueError:
                return  # consumption/cancellation raced the human re-arm snapshot
            e.wake_owner_pid = os.getpid()
            e.retry_count = 0
            e.retry_deadline_at = 0.0
            e.wake_delivery_state = "scheduled"
            e.wake_wait_reason = ""
            e.trigger_at = min(e.trigger_at, max(e.scheduled_trigger_at, time.time()))
            _adopted.append(True)

        # 不触碰 lease：他进程若正持有 claim，到期后自然让渡给 owner（本进程）。
        store._mutate_reconciled(
            _adopt,
            operation="rearm_wake_grant",
            sid=sid,
            retry_safe=True,
            accept_visible_match=True,
        )
        if not adopted:
            continue
        store._set_wake_grant(sid, grant)
        rearmed += 1
        logger.info("wake grant 已重铸（re-arm）sid=%s session=%s", sid, target)
    return rearmed


class SchedulerThread:
    """常驻检查线程：每 TICK 检查到点提醒 → 回调（默认写 interop notify）.

    回调由装配方注入（默认 _notify_via_interop）；异常自愈（单次 tick 失败不退出）。
    """

    def __init__(
        self,
        store: ScheduleStore,
        *,
        tick_interval: float = _TICK_INTERVAL_S,
        notify: Callable[[ScheduleEntry], Any] | None = None,
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
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="scheduler-tick")
        self._thread.start()
        logger.info("调度提醒线程已启动（tick=%ss）", self._tick)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                for e in self._store.claim_due(
                    self._owner, lease_s=max(30.0, self._tick * 3)
                ):
                    try:
                        outcome = self._notify(e)
                        if outcome is False:
                            self._store.retry_later(
                                e.sid, self._owner, delay_s=max(5.0, self._tick)
                            )
                            continue
                        if outcome is not WAKE_DEFERRED:
                            # WAKE_DEFERRED：交付方已自行 defer（条目保留、退避
                            # 已排）；此时 ack 会把等待 re-arm 的 wake 提前消费掉。
                            self._store.mark_triggered(e.sid, owner=self._owner)
                    except ScheduleCommitUncertainError as exc:
                        # replace 已发生：禁止再用 retry_later 追加第二个 semantic mutation。
                        # 下一 tick/进程从磁盘 SoT reconcile；这里只报告 durability 未确认。
                        logger.error(
                            "提醒状态 commit outcome uncertain（禁止盲 retry_later）: "
                            "sid=%s visible_state=%s",
                            e.sid,
                            exc.visible_state,
                            exc_info=True,
                        )
                    except Exception:  # noqa: BLE001 — 单条失败保留提醒并退避重试
                        logger.warning("提醒触发失败（保留并重试）: %s", e.sid, exc_info=True)
                        self._store.retry_later(
                            e.sid, self._owner, delay_s=max(5.0, self._tick)
                        )
            except Exception:  # noqa: BLE001 — tick 异常自愈
                logger.warning("调度 tick 异常（自愈继续）", exc_info=True)
            self._stop.wait(self._tick)

    @staticmethod
    def _notify_via_interop(
        entry: ScheduleEntry,
        *,
        data_dir: str | Path | None = None,
        wake_degraded_reason: str | None = None,
        wake_degraded_payload: dict[str, object] | None = None,
    ) -> None:
        """默认通知：写 interop LFL inbox（lfl_to_dsh/pending/，topic=notify）.

        LFL 下轮 run 读到并回显 [外部协调·from DSH] 或 [定时提醒]——web/飞书可见。
        wake_degraded_reason（EVO-20260920-213965a1 案2）：wake 降级为通知时
        携带结构化原因，供下一会话 pending 投影列出（sid/时间/原因）。
        """
        from datetime import datetime as _dt

        # P1-B1: notification storage follows the resolved runtime data owner.
        # The fallback is the same immutable startup snapshot that owns schedule.json.
        data_root = Path(data_dir).expanduser().resolve() if data_dir is not None else _SCHEDULE_PATH.parent
        inbox = data_root / "interop" / "lfl_to_dsh" / "pending"
        inbox.mkdir(parents=True, exist_ok=True)
        now = _dt.now(UTC)
        # Effect identity is sid + occurrence.  Ack persistence failure may cause the same
        # occurrence to be delivered again; reusing one filename/id makes that retry
        # mechanically idempotent instead of emitting another user-visible notification.
        occurrence = max(0, int(entry.count))
        effect_id = f"schedule:{entry.sid}:{occurrence}"
        fname = f"notify-{entry.sid}-occ-{occurrence}.json"
        payload: dict[str, Any] = {
            "id": effect_id,
            "from": "lfl-scheduler",
            "to": "lfl",
            "ts": now.isoformat(),
            "topic": "notify",
            "ref": entry.sid,
            "body": (
                f"[定时提醒] {entry.message}\n[自动执行已降级] {wake_degraded_reason}"
                if wake_degraded_reason
                and getattr(entry, "task_mode", "") == task_grant.MODE_RECURRING
                else f"[定时提醒] {entry.message}"
            ),
            "status": "pending",
        }
        if wake_degraded_reason:
            payload["wake_degraded_reason"] = wake_degraded_reason
            # EVO-20261007-8057c39a 案2: 降级通知携带可再锚定 payload
            # （sid/时间/原因之外补齐原始调度规格），供下一会话
            # 直接 re-issue schedule 而非丢失原计划。
            if wake_degraded_payload is not None:
                payload["wake_degraded_payload"] = dict(wake_degraded_payload)
        (inbox / fname).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

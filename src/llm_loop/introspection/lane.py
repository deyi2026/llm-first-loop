"""BranchLane 账本：main 主线 + 多 lane 并行的唯一登记处.

设计依据: docs/design/DESIGN-20261105-main-lane-parallel-delivery-v1.md §4.2 / §11
裁决要点（2026-11-05，用户已定）:
- lane 与 goal 强制 1:1：同一 goal 的非终态 main lane 至多 1 条；
  sub lane 必须复用同一 goal（并行拆分场景，由 main lane 汇总合并）。
- subagent 的 --detach 隔离 worktree **不登记**为 lane（私有中间态，父会话收口）。
- 双账本：lanes.jsonl 当前态（last-write-wins + version CAS）
          lane_events.jsonl 只追加历史（审计与 Board 时间线）。
- owner_session_id 仅用于显示，**不作鉴权依据**（沿用 claim fencing 口径）。

与 goal.py 同构：fcntl.flock 跨进程写锁 + tmp/os.replace 原子重写 + fail-closed 损坏判定。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

from llm_loop.timekeeping import system_local_now

logger = logging.getLogger(__name__)

_FALLBACK_LOCK = threading.Lock()

LANE_STATUSES = ("open", "active", "verifying", "merging", "merged", "closed", "abandoned")
TERMINAL_STATUSES = ("merged", "closed", "abandoned")
LANE_ROLES = ("main", "sub")
PRIORITIES = ("normal", "hotfix")

# 非终态之间的合法迁移（终态一律走 close，见 update）。收窄的是"倒退"
# （如 merging→open），不禁止前向跳跃：短任务可从 open 直接进 verifying。
ALLOWED_STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "open": ("active", "verifying"),
    "active": ("verifying", "open"),
    "verifying": ("merging", "active"),
    "merging": ("verifying",),
}

# lane_open 允许声明的字段（系统管理字段不可由调用方覆盖）
_MUTABLE_FIELDS = (
    "status",
    "head_sha",
    "paths",
    "contract_changes",
    "verify_ref",
    "priority",
    "base_main_sha",
    "close_reason",
)


class LaneStoreCorruptionError(RuntimeError):
    """lanes.jsonl 存在损坏记录，当前查询无法安全判定。"""


class LaneVersionConflictError(RuntimeError):
    """expected_version CAS 冲突：在 flock 内检出，写入未发生（A9）。"""

    def __init__(
        self,
        *,
        lane_id: str,
        expected: int,
        current: int,
        owner_session_id: str = "",
    ) -> None:
        self.lane_id = lane_id
        self.expected = expected
        self.current = current
        self.owner_session_id = owner_session_id
        super().__init__(
            f"version_conflict lane={lane_id} expected={expected} current={current}"
        )


class LaneConstraintError(RuntimeError):
    """违反硬约束（goal 1:1 / branch 唯一 / 终态不可逆 / 非法状态迁移）。"""


def _normalize_paths(paths: list[str] | tuple[str, ...] | None) -> list[str]:
    """声明路径规范化：去空白、去重、排序；空项丢弃。声明面只做规范化，不做存在性校验。"""
    out: list[str] = []
    for raw in paths or ():
        item = str(raw).strip().replace("\\", "/")
        if not item:
            continue
        if item not in out:
            out.append(item)
    return sorted(out)


@dataclass
class Lane:
    """一条可合并分支的登记记录（1 分支 × 1 worktree × 1 goal × 1 owner session）."""

    lane_id: str
    branch: str
    worktree: str
    base_main_sha: str
    goal_id: str
    owner_session_id: str = ""
    lane_role: str = "main"  # main|sub
    paths: list[str] = field(default_factory=list)
    contract_changes: list[str] = field(default_factory=list)
    status: str = "open"  # open|active|verifying|merging|merged|closed|abandoned
    head_sha: str = ""
    priority: str = "normal"  # normal|hotfix
    base_is_broken: bool = False
    verify_ref: str = ""
    close_reason: str = ""
    version: int = 1
    created_at: str = ""
    last_activity: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class LaneStore:
    """lanes.jsonl 当前态 + lane_events.jsonl 历史的存储层."""

    def __init__(self, audit_dir: str | Path) -> None:
        self._dir = Path(audit_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "lanes.jsonl"
        self._event_path = self._dir / "lane_events.jsonl"

    # ---------------- 写入 ----------------

    def create(
        self,
        *,
        branch: str,
        worktree: str,
        base_main_sha: str,
        goal_id: str,
        owner_session_id: str = "",
        lane_role: str = "main",
        paths: list[str] | None = None,
        contract_changes: list[str] | None = None,
        priority: str = "normal",
        base_is_broken: bool = False,
    ) -> Lane:
        """登记一条 lane。goal 1:1 / branch 唯一 / worktree 唯一在同一 flock 内校验。"""
        branch = str(branch or "").strip()
        worktree = str(worktree or "").strip()
        goal_id = str(goal_id or "").strip()
        if not branch:
            raise LaneConstraintError("branch 必填")
        if not worktree:
            raise LaneConstraintError("worktree 必填（lane 绑定一条真实工作树）")
        if not goal_id:
            raise LaneConstraintError("goal_id 必填（裁决：lane 与 goal 强制 1:1）")
        if lane_role not in LANE_ROLES:
            raise LaneConstraintError(f"lane_role 仅允许 {LANE_ROLES}: {lane_role!r}")
        if priority not in PRIORITIES:
            raise LaneConstraintError(f"priority 仅允许 {PRIORITIES}: {priority!r}")

        now = system_local_now().isoformat()
        lane = Lane(
            lane_id=f"lane-{uuid.uuid4().hex[:8]}",
            branch=branch,
            worktree=worktree,
            base_main_sha=str(base_main_sha or "").strip(),
            goal_id=goal_id,
            owner_session_id=str(owner_session_id or "").strip(),
            lane_role=lane_role,
            paths=_normalize_paths(paths),
            contract_changes=_normalize_paths(contract_changes),
            status="open",
            priority=priority,
            base_is_broken=bool(base_is_broken),
            version=1,
            created_at=now,
            last_activity=now,
        )
        with self._file_lock():
            rows = self._read_rows()
            self._assert_unique(rows, lane)
            rows.append(lane.to_dict())
            self._atomic_rewrite([json.dumps(r, ensure_ascii=False) for r in rows])
            self._append_event(
                {"event": "lane.created", "lane_id": lane.lane_id, "ts": now, "snapshot": lane.to_dict()}
            )
        return lane

    def update(
        self,
        lane_id: str,
        *,
        expected_version: int,
        **fields: object,
    ) -> dict:
        """按 CAS 更新可变字段；终态不可逆；未知字段直接拒绝（不静默丢弃）。"""
        unknown = sorted(set(fields) - set(_MUTABLE_FIELDS))
        if unknown:
            raise LaneConstraintError(f"不可更新字段: {unknown}（允许: {list(_MUTABLE_FIELDS)}）")
        if not fields:
            raise LaneConstraintError("update 至少需要一个字段")

        with self._file_lock():
            rows = self._read_rows()
            idx = self._find_index(rows, lane_id)
            entry = rows[idx]
            current_version = self.version_of(entry)
            if current_version != int(expected_version):
                raise LaneVersionConflictError(
                    lane_id=lane_id,
                    expected=int(expected_version),
                    current=current_version,
                    owner_session_id=str(entry.get("owner_session_id") or ""),
                )
            current_status = str(entry.get("status") or "open")
            new_status = fields.get("status")
            if current_status in TERMINAL_STATUSES:
                if new_status is not None and str(new_status) != current_status:
                    raise LaneConstraintError(
                        f"lane 终态不可逆: {current_status} → {new_status}"
                    )
                raise LaneConstraintError(f"lane 已是终态 {current_status}，不再接受更新")
            if new_status is not None:
                target = str(new_status)
                if target not in LANE_STATUSES:
                    raise LaneConstraintError(f"非法 status: {new_status!r}")
                if target in TERMINAL_STATUSES:
                    raise LaneConstraintError("终态迁移必须走 close（需显式 reason）")
                if target != current_status:
                    allowed = ALLOWED_STATUS_TRANSITIONS.get(current_status, ())
                    if target not in allowed:
                        raise LaneConstraintError(
                            f"非法状态迁移: {current_status} → {target}"
                            f"（允许: {list(allowed)}）"
                        )

            now = system_local_now().isoformat()
            for key, value in fields.items():
                if key in {"paths", "contract_changes"}:
                    entry[key] = _normalize_paths(value)  # type: ignore[arg-type]
                elif key == "priority":
                    if str(value) not in PRIORITIES:
                        raise LaneConstraintError(f"priority 仅允许 {PRIORITIES}: {value!r}")
                    entry[key] = str(value)
                else:
                    entry[key] = value
            entry["version"] = current_version + 1
            entry["last_activity"] = now
            rows[idx] = entry
            self._atomic_rewrite([json.dumps(r, ensure_ascii=False) for r in rows])
            self._append_event(
                {
                    "event": "lane.updated",
                    "lane_id": lane_id,
                    "ts": now,
                    "changed": sorted(fields),
                    "version": entry["version"],
                }
            )
            return entry

    def close(
        self,
        lane_id: str,
        *,
        expected_version: int,
        status: str = "closed",
        reason: str = "",
    ) -> dict:
        """终态收敛。merged/closed/abandoned 一律需要非空 reason（可归因）。"""
        if status not in TERMINAL_STATUSES:
            raise LaneConstraintError(f"close 仅接受终态 {TERMINAL_STATUSES}: {status!r}")
        reason = str(reason or "").strip()
        if not reason:
            raise LaneConstraintError("close 必须提供非空 reason（终态可归因）")

        with self._file_lock():
            rows = self._read_rows()
            idx = self._find_index(rows, lane_id)
            entry = rows[idx]
            current_version = self.version_of(entry)
            if current_version != int(expected_version):
                raise LaneVersionConflictError(
                    lane_id=lane_id,
                    expected=int(expected_version),
                    current=current_version,
                    owner_session_id=str(entry.get("owner_session_id") or ""),
                )
            current_status = str(entry.get("status") or "open")
            if current_status in TERMINAL_STATUSES:
                if current_status == status and entry.get("close_reason") == reason:
                    return entry  # 幂等重复提交
                raise LaneConstraintError(f"lane 终态不可逆: {current_status} → {status}")

            now = system_local_now().isoformat()
            entry["status"] = status
            entry["close_reason"] = reason
            entry["version"] = current_version + 1
            entry["last_activity"] = now
            rows[idx] = entry
            self._atomic_rewrite([json.dumps(r, ensure_ascii=False) for r in rows])
            self._append_event(
                {
                    "event": "lane.closed",
                    "lane_id": lane_id,
                    "ts": now,
                    "status": status,
                    "reason": reason,
                    "version": entry["version"],
                }
            )
            return entry

    def request_merge(self, lane_id: str, *, expected_version: int) -> dict:
        """申请合入 main：只把状态推进到 verifying（入队由合并队列负责）。"""
        return self.update(lane_id, expected_version=expected_version, status="verifying")

    # ---------------- 读取（零写副作用） ----------------

    @staticmethod
    def version_of(entry: dict) -> int:
        raw = (entry or {}).get("version", 1)
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return 1

    def get(self, lane_id: str) -> dict | None:
        if not self._path.exists():
            return None
        malformed: list[int] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    malformed.append(line_no)
                    continue
                if entry.get("lane_id") == lane_id:
                    return entry
        if malformed:
            raise self._corruption_error(malformed, "显式 lane_id 未命中")
        return None

    def list(
        self,
        statuses: tuple[str, ...] | list[str] | None = None,
        *,
        include_terminal: bool = False,
    ) -> list[dict]:
        """列出 lane；默认隐藏终态（Board 只展示在途）。损坏记录 fail-closed。"""
        if not self._path.exists():
            return []
        wanted = set(statuses) if statuses else None
        out: list[dict] = []
        malformed: list[int] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    malformed.append(line_no)
                    continue
                status = str(entry.get("status") or "")
                if wanted is not None and status not in wanted:
                    continue
                if wanted is None and not include_terminal and status in TERMINAL_STATUSES:
                    continue
                out.append(entry)
        if malformed:
            raise self._corruption_error(malformed, "列表读取")
        out.sort(key=lambda e: str(e.get("last_activity") or ""), reverse=True)
        return out

    def find_by_goal(self, goal_id: str) -> list[dict]:
        return [row for row in self.list(include_terminal=True) if row.get("goal_id") == goal_id]

    def find_by_branch(self, branch: str) -> list[dict]:
        return [
            row
            for row in self.list(include_terminal=True)
            if str(row.get("branch") or "") == branch
        ]

    # ---------------- 内部 ----------------

    def _assert_unique(self, rows: list[dict], lane: Lane) -> None:
        for row in rows:
            status = str(row.get("status") or "")
            if status in TERMINAL_STATUSES:
                continue
            if str(row.get("branch") or "") == lane.branch:
                raise LaneConstraintError(
                    f"branch 已被在途 lane 占用: {lane.branch}（{row.get('lane_id')}）"
                )
            if str(row.get("worktree") or "") == lane.worktree:
                raise LaneConstraintError(
                    f"worktree 已被在途 lane 占用: {lane.worktree}（{row.get('lane_id')}）"
                )
            if lane.lane_role == "main" and str(row.get("goal_id") or "") == lane.goal_id:
                raise LaneConstraintError(
                    "同一 goal 至多一条在途 main lane（裁决：lane 与 goal 强制 1:1）；"
                    f"已有 {row.get('lane_id')}；并行拆分请用 lane_role=sub"
                )

    @staticmethod
    def _find_index(rows: list[dict], lane_id: str) -> int:
        for idx, row in enumerate(rows):
            if row.get("lane_id") == lane_id:
                return idx
        raise LaneConstraintError(f"lane 不存在: {lane_id}")

    def _read_rows(self) -> list[dict]:
        if not self._path.exists():
            return []
        rows: list[dict] = []
        malformed: list[int] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    rows.append(json.loads(raw))
                except json.JSONDecodeError:
                    malformed.append(line_no)
        if malformed:
            raise self._corruption_error(malformed, "写入前读取")
        return rows

    def _append_event(self, event: dict) -> None:
        """只追加历史；写失败只告警不吞主写结果（与 goal.py 的 fail-open 口径一致）。"""
        try:
            with self._event_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            logger.warning("lane_events 写入失败（主账本已提交）: %s", self._event_path, exc_info=True)

    def _corruption_error(self, lines: list[int], reason: str) -> LaneStoreCorruptionError:
        shown = ",".join(str(n) for n in lines[:8])
        suffix = "..." if len(lines) > 8 else ""
        return LaneStoreCorruptionError(
            f"lane 存储损坏: {self._path} 存在不可解析 JSONL 行 {shown}{suffix}（{reason}）"
        )

    def _atomic_rewrite(self, lines: list[str]) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                if lines:
                    fh.write("\n".join(lines) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._path)
            dir_fd: int | None = None
            try:
                flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                dir_fd = os.open(self._dir, flags)
                os.fsync(dir_fd)
            except OSError:
                logger.warning("lane 目录 fsync 失败（写入已完成）: %s", self._dir, exc_info=True)
            finally:
                if dir_fd is not None:
                    os.close(dir_fd)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                logger.debug("lane 临时文件清理失败: %s", tmp, exc_info=True)

    @contextmanager
    def _file_lock(self) -> Iterator[None]:
        """lanes.jsonl 跨进程写锁；仅锁获取失败时 fail-open，业务 I/O 异常原样传播。"""
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        try:
            import fcntl
        except ImportError:
            with _FALLBACK_LOCK:
                yield
            return

        lock_file = None
        try:
            lock_file = lock_path.open("a", encoding="utf-8")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            if lock_file is not None:
                lock_file.close()
            logger.warning("lane 存储锁不可用（fail-open，并发保护降级）: %s: %s", lock_path, exc)
            yield
            return

        try:
            yield
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                logger.warning("lane 存储解锁失败: %s", lock_path, exc_info=True)
            finally:
                lock_file.close()

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
import posixpath
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from llm_loop.introspection.task_claim import overlapping_paths
from llm_loop.timekeeping import system_local_now

logger = logging.getLogger(__name__)

_FALLBACK_LOCK = threading.Lock()

LANE_STATUSES = ("open", "active", "verifying", "merging", "merged", "closed", "abandoned")
TERMINAL_STATUSES = ("merged", "closed", "abandoned")
# 收口态：进入时记 closing_since（供 push 门的 30min 收口截止判定），离开或
# 终态时清除。last_activity 每次更新都会刷新，不能拿它当收口计时。
_CLOSING_STATUSES = frozenset({"verifying", "merging"})
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
)
# close_reason 刻意不在 _MUTABLE_FIELDS：它只能由 close(reason=...) 在进入终态时写，
# 否则 lane_update 可给非终态 lane 留一个永远解释不了的终止理由。


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


class LaneStoreLockUnavailable(RuntimeError):  # noqa: N818 — 设计指定名（M2-A §3.2-1）
    """lock_strict=true 下跨进程锁不可用（fcntl 缺失 / flock OSError / 锁文件不可写）。

    M2-A（DESIGN-20261116 §3.2-1）：create/update/close 三入口一致拒写，
    任何入口不得降级放行（fail-closed）。warn 模式（默认）维持现状仅告警。
    """


class LaneStoreConfigError(RuntimeError):
    """LaneStore 构造配置非法（M2-A INV-1）：enforce_cross_goal=true 硬依赖
    lock_strict=true——该组合在初始化即抛错，不存在「enforce 在、锁 warn 化」
    的可用实例（§3.2-2 矩阵第 6 行）。"""


class LanePathConflict(RuntimeError):  # noqa: N818 — 设计指定名（M2-A §3.2-3）
    """enforce 模式锁内检出跨 Goal 声明路径**确证**重叠（create/update 引入/扩大占用）。

    M2-A §3.2-3：conflicts 属性逐项含 lane_id/goal_id/shared_paths（realpath
    辅助命中时 best_effort=True）。close 不抛本异常（BUG-09：close 是释放，
    不因现有重叠被拒）。无 force 放行参数（P0-2）——处置只有：请求 owner 复核 /
    缩小自身 paths / 等待对端终态。
    """

    def __init__(self, message: str, *, conflicts: list[dict] | None = None) -> None:
        self.conflicts = list(conflicts or [])
        super().__init__(message)


class LanePathConflictUnknown(RuntimeError):  # noqa: N818 — 设计指定名（M2-A §3.2-3）
    """enforce 模式下冲突面**不可判定**（fail-closed 拒写）——不是确证冲突。

    M2-A §3.2-3：对方在途 lane paths 空/缺失（如 lane-selftest-guard）、本方未
    声明 paths、或 realpath 判定失败。不得据此放行（不假装知道没有冲突），也
    不得表述为 overlap（不冒充确证）。处置：补 paths 或 owner 裁决。
    """

    def __init__(self, message: str, *, unknowns: list[dict] | None = None) -> None:
        self.unknowns = list(unknowns or [])
        super().__init__(message)


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
    closing_since: str = ""  # 进入 verifying/merging 的时刻（push 收口截止锚点）
    version: int = 1
    created_at: str = ""
    last_activity: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class LaneStore:
    """lanes.jsonl 当前态 + lane_events.jsonl 历史的存储层."""

    def __init__(
        self,
        audit_dir: str | Path,
        *,
        lock_strict: bool = False,
        enforce_cross_goal: bool = False,
        repo_root: str | Path | None = None,
    ) -> None:
        """M2-A（DESIGN-20261116 §3.2-1/§3.2-2）：

        - lock_strict=true: fcntl 缺失 / flock OSError / 锁文件不可用 →
          create/update/close 一致拒写（LaneStoreLockUnavailable，fail-closed）；
          默认 false 维持历史 warn 行为（锁失败仅告警放行）。
        - enforce_cross_goal=true: 锁内跨 Goal 声明路径重叠检查从 warn 升级硬拒
          （确证→LanePathConflict；不可判定→LanePathConflictUnknown）。INV-1:
          硬依赖 lock_strict=true，否则构造即抛 LaneStoreConfigError。
        - repo_root: 路径根绑定基准（strict 检查层归一/越界/symlink 判定用）。
          边界（§3.2-6）: 仅同主机同 audit_dir 的进程互斥；登记门不是 OS 写入
          隔离，symlink TOCTOU 只能 best-effort，无跨主机全局锁。
        旧调用（只传 audit_dir）行为与历史版本完全一致（§3.3 兼容）。
        """
        strict = bool(lock_strict)
        enforce = bool(enforce_cross_goal)
        if enforce and not strict:
            raise LaneStoreConfigError(
                "INV-1 违反: enforce_cross_goal=true 硬依赖 lock_strict=true"
                "（拒绝启用，不存在锁 warn 化的 enforce 实例）"
            )
        self._lock_strict = strict
        self._enforce_cross_goal = enforce
        self._repo_root = Path(repo_root).resolve() if repo_root else None
        self._dir = Path(audit_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "lanes.jsonl"
        self._event_path = self._dir / "lane_events.jsonl"
        # 写后诊断（best-effort，仅最近一次写操作；非账本数据，不入 JSONL）：
        # last_cross_goal_report——strict 锁内检查的 warn 级提示；
        # last_event_append_failed——主账本已提交而事件写入失败（§3.2-6 双事实）。
        self.last_cross_goal_report: dict = {}
        self.last_event_append_failed = False

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
            # M2-A §3.2-3: 锁内原子检查（create 引入占用；close 不检查——BUG-09）。
            # strict 下检查层归一结果同时作为存储值（repo 根相对 POSIX）；
            # enforce 下确证跨 Goal 重叠 / 冲突面 unknown → 拒写，账本与事件均不落。
            check_paths = list(lane.paths)
            if self._lock_strict:
                check_paths = self._normalize_declared_paths(lane.paths)
                self._cross_goal_check(rows, my_goal_id=goal_id, my_paths=check_paths)
                if check_paths:
                    lane.paths = check_paths
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

            # M2-A §3.2-3: 仅当本 update 引入/扩大占用（显式带 paths）才做锁内
            # 检查；不带 paths 的状态推进不重复检查（占用未变）。排除自身旧占用。
            if self._lock_strict and "paths" in fields:
                check_paths = self._normalize_declared_paths(fields["paths"])  # type: ignore[arg-type]
                self._cross_goal_check(
                    rows,
                    my_goal_id=str(entry.get("goal_id") or ""),
                    my_paths=check_paths,
                    exclude_lane_id=lane_id,
                )
                fields = {**fields, "paths": check_paths}
            now = system_local_now().isoformat()
            target_status = str(fields.get("status") or current_status)
            if target_status != current_status:
                if (
                    target_status in _CLOSING_STATUSES
                    and current_status not in _CLOSING_STATUSES
                ):
                    entry["closing_since"] = now
                elif target_status not in _CLOSING_STATUSES:
                    entry.pop("closing_since", None)
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
        """终态收敛。merged/closed/abandoned 一律需要非空 reason（可归因）。

        M2-A BUG-09: close 是释放占用——不做跨 Goal 重叠检查、不因现有重叠
        被拒（跨 Goal 硬拒只作用于 create/update 引入/扩大占用）；仍受
        strict 锁保护（锁不可用时拒写，§3.2-1）。
        """
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
            entry.pop("closing_since", None)
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

    def close_if_live(
        self,
        lane_id: str,
        *,
        status: str = "merged",
        reason: str = "",
        max_attempts: int = 3,
    ) -> dict:
        """幂等自动收口：在途则按终态关闭（CAS 冲突重读重试），已终态原样返回。

        收口治理③（2026-11-10，用户 2026-11-10 07:11 授权）：队列已完成合并后
        lane 必须落终态——2026-11-09 实测 queue.merged 已落、lane 停在 merging，
        卡住所有 main push 长达一夜（靠人工代收口解锁）。返回 dict 而非抛异常：

        - ``{"closed": True,  "entry": …}``：本次关闭成功；
        - ``{"closed": False, "already": <status>, "entry": …}``：已是终态（幂等）；
        - ``{"closed": False, "missing": True}``：账本无此 lane（队列孤儿）；
        - ``{"closed": False, "conflict": True}``：重试用尽仍 CAS 冲突（并发写者
          在动它），调用方应把事实带回执、不静默放弃。
        """
        if status not in TERMINAL_STATUSES:
            raise LaneConstraintError(f"close 仅接受终态 {TERMINAL_STATUSES}: {status!r}")
        reason = str(reason or "").strip()
        if not reason:
            raise LaneConstraintError("close 必须提供非空 reason（终态可归因）")
        for _ in range(max(1, int(max_attempts))):
            try:
                entry = self.get(lane_id)
            except (OSError, LaneStoreCorruptionError):
                return {"closed": False, "missing": True}
            if entry is None:
                return {"closed": False, "missing": True}
            current = str(entry.get("status") or "open")
            if current in TERMINAL_STATUSES:
                return {"closed": False, "already": current, "entry": entry}
            try:
                closed = self.close(
                    lane_id,
                    expected_version=self.version_of(entry),
                    status=status,
                    reason=reason,
                )
            except LaneVersionConflictError:
                continue
            return {"closed": True, "entry": closed}
        return {"closed": False, "conflict": True}

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

    # ---------------- 只读预检（DESIGN-20261114 §4.5 / R4） ----------------

    def precheck(
        self,
        *,
        branch: str,
        worktree: str,
        goal_id: str,
        paths: list[str] | None = None,
        contract_changes: list[str] | None = None,
    ) -> dict:
        """开门前纯读预检：零写账本、零建目录、不抛约束错。

        只回答三个「说了也不拦」的问题，与 create() 的硬拦（branch/worktree/goal
        1:1，见 _assert_unique）**互不替代**：
        - overlap_warning: 声明的 paths 与在途 lane 交叉（终态 lane 不参与）；
        - contract_same_key_warning: 与其他在途 lane 的 contract_changes 同键
          （M4-A，DESIGN-20261116 §6）。纯提示、零阻断、零审批：同键 ≠ 设计
          冲突（语义由模型/人判）；不读 approved_by/自报理由——授权判定只走
          用户显式指令，本预检不实现任何授权逻辑；
        - goal_unknown: goal_id 未在 goals.jsonl 出现（账本可能被轮转/裁剪，
          缺席 ≠ 从未存在，故默认只告警；lane_require_goal=true 时由调用方硬拒）。

        branch/worktree 只做回显，不参与判定：占用冲突由 create() 硬拦，这里提前
        算一遍等于把硬拦降级成告警，会松动既有裁决。
        """
        mine = _normalize_paths(paths)
        contract_keys = _normalize_paths(contract_changes)
        checked: list[str] = []
        overlaps: list[dict] = []
        for row in self.list():  # 默认隐藏终态：只与在途 lane 比
            lane_id = str(row.get("lane_id") or "")
            checked.append(lane_id)
            hits = overlapping_paths(mine, [str(p) for p in row.get("paths") or []])
            if not hits:
                continue
            shared = sorted({a for a, _ in hits} | {b for _, b in hits})
            overlaps.append(
                {
                    "lane_id": lane_id,
                    "branch": str(row.get("branch") or ""),
                    "status": str(row.get("status") or ""),
                    "shared_paths": shared,
                }
            )
        goal_text = str(goal_id or "").strip()
        return {
            "branch": str(branch or "").strip(),
            "worktree": str(worktree or "").strip(),
            "goal_id": goal_text,
            "declared_paths": mine,
            "overlap_warning": overlaps,
            "contract_same_key_warning": self.contract_same_key_hint(mine=contract_keys),
            "goal_unknown": bool(goal_text) and not self._goal_known(goal_text),
            "checked_against": checked,
        }

    def contract_same_key_hint(
        self, *, mine: list[str] | None = None, exclude_lane_id: str = ""
    ) -> list[dict]:
        "与在途 lane 的 contract_changes 同键提示（M4-A/DESIGN-20261116 §6）: 纯提示、"
        "零阻断、零审批；同键 ≠ 设计冲突（语义由模型/人判）；不读 approved_by/自报"
        "理由——授权判定只走用户显式指令，本方法不实现任何授权逻辑。"
        # 边界: 对方须在途（list() 默认隐藏终态）且非自身（exclude_lane_id）；
        # mine 为空 / 对方 contract_changes 空或缺失 → 空列表，不报错；
        # 键按 _normalize_paths 规范化后精确相等；输出按 (key, lane_id) 排序，
        # 逐项含 key + 对方 lane_id/goal_id（确定性输出）。
        wanted = set(_normalize_paths(mine))
        if not wanted:
            return []
        exclude = str(exclude_lane_id or "")
        hits: list[dict] = []
        for row in self.list():
            lane_id = str(row.get("lane_id") or "")
            if not lane_id or lane_id == exclude:
                continue
            for key in sorted({str(k) for k in row.get("contract_changes") or []}):
                if key in wanted:
                    hits.append(
                        {
                            "key": key,
                            "lane_id": lane_id,
                            "goal_id": str(row.get("goal_id") or ""),
                        }
                    )
        hits.sort(key=lambda h: (str(h.get("key") or ""), str(h.get("lane_id") or "")))
        return hits

    def _goal_known(self, goal_id: str) -> bool:
        """goal_id 是否在 goals.jsonl 出现过（只读；单行坏跳过，账本不可读按已知处理）。

        读不到账本返回 True 是刻意的：这条判定只用于提示，误报会让「默认只告警」
        退化成噪声，而漏报只是少一条提示，不影响任何写路径。
        """
        path = self._dir / "goals.jsonl"
        if not path.exists():
            return False
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return True
        for line in lines:
            raw = line.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if str(row.get("id") or "") == goal_id:
                return True
        return False

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

    # ---------------- M2-A 跨 Goal 路径冲突检查（DESIGN-20261116 §3.2） ----------------

    _MAX_DECLARED_PATH_LEN = 1024

    def _normalize_declared_paths(self, paths: list[str] | tuple[str, ...] | None) -> list[str]:
        """检查层严格归一（仅 strict/enforce 生效；账本 schema 不变，strict 下
        存储值取本归一结果——repo 根相对 POSIX，拒绝非法声明而非默默落账）。

        规则（§3.2-4）：
        - 反斜杠 → POSIX 斜杠；NUL / 超长(>1024) → LaneConstraintError
        - 绝对路径: repo_root 内 → 归一为 repo 相对；越出或 repo_root 未配置 → 拒
        - 相对路径 posixpath.normpath 折叠；逃出 repo 根（.. 前缀/等于 ../.）→ 拒
        - 不存在路径允许（按字面比较）；存在路径做 realpath 越界/symlink 判定：
          经 symlink 指向 repo_root 外 → 拒（best-effort，不承诺覆盖 TOCTOU 窗口）
        """
        root = self._repo_root
        out: list[str] = []
        for raw in paths or ():
            item = str(raw).strip().replace("\\", "/")
            if not item:
                continue
            if "\x00" in item or len(item) > self._MAX_DECLARED_PATH_LEN:
                raise LaneConstraintError(f"声明路径归一失败（NUL/超长）: {raw!r}")
            if item.startswith("/"):
                if root is None:
                    raise LaneConstraintError(f"绝对路径无法归一（repo_root 未配置）: {raw!r}")
                try:
                    rel = Path(item).resolve().relative_to(root)
                except (OSError, ValueError):
                    raise LaneConstraintError(f"绝对路径越出 repo_root 或不可解析: {raw!r}") from None
                norm = rel.as_posix()
            else:
                norm = posixpath.normpath(item)
                if norm in {".", ".."} or norm.startswith("../"):
                    raise LaneConstraintError(f"声明路径逃出 repo 根或指向根整体: {raw!r}")
            if root is not None:
                try:
                    (root / norm).resolve().relative_to(root)
                except (OSError, ValueError):
                    raise LaneConstraintError(
                        f"路径经 symlink 指向 repo_root 外或不可解析（best-effort 拒绝）: {raw!r}"
                    ) from None
            if norm not in out:
                out.append(norm)
        return sorted(out)

    def _realpath_or_unknown(self, p: str) -> str | None:
        """realpath 辅助归一（§3.2-4: 仅检查层辅助比较，不改账本）。解析失败
        返回 None——该路径冲突面不可判定，由调用方按 unknown 披露，不冒充无冲突。"""
        if not self._repo_root:
            return None
        try:
            return (self._repo_root / p).resolve().as_posix()
        except OSError:
            return None

    def _cross_goal_check(
        self,
        rows: list[dict],
        *,
        my_goal_id: str,
        my_paths: list[str],
        exclude_lane_id: str = "",
    ) -> dict:
        """锁内原子跨 Goal 检查（§3.2-3）。调用点: create（引入占用）/ update 带
        paths（引入或扩大占用）。close 不调用（BUG-09: close 是释放）。

        - 同 Goal 重叠（main/sub/sub 合法并行拆分）→ 仅提示，不拒。
        - 跨 Goal 确证重叠（字面；realpath 辅助命中标 best_effort=True）→
          warn 回执 / enforce 硬拒 LanePathConflict（无 bypass 参数，P0-2）。
        - 对方在途 paths 空/缺失、本方未声明、realpath 不可判定 → unknown：
          warn 提示；enforce fail-closed 拒写 LanePathConflictUnknown
          （不冒充确证冲突，也不放行）。
        warn 级提示存 last_cross_goal_report 供工具层渲染；仅最近一次写。
        """
        conflicts: list[dict] = []
        unknowns: list[dict] = []
        same_goal: list[dict] = []
        for row in rows:
            if str(row.get("status") or "open") in TERMINAL_STATUSES:
                continue
            lane_id = str(row.get("lane_id") or "")
            if exclude_lane_id and lane_id == exclude_lane_id:
                continue
            their_goal = str(row.get("goal_id") or "")
            their = _normalize_paths([str(p) for p in row.get("paths") or []])
            if their_goal != my_goal_id and not their:
                unknowns.append(
                    {
                        "lane_id": lane_id,
                        "goal_id": their_goal,
                        "reason": "对方在途 paths 为空/缺失，冲突面不可判定",
                    }
                )
                continue
            hits = overlapping_paths(list(my_paths), their)
            best_effort = False
            if not hits and self._repo_root is not None:
                mine_real = [self._realpath_or_unknown(p) for p in my_paths]
                theirs_real = [self._realpath_or_unknown(p) for p in their]
                if None in mine_real or None in theirs_real:
                    if their_goal != my_goal_id:
                        unknowns.append(
                            {
                                "lane_id": lane_id,
                                "goal_id": their_goal,
                                "reason": "realpath 解析失败，冲突面不可判定",
                            }
                        )
                else:
                    soft = overlapping_paths(
                        [r for r in mine_real if r is not None],
                        [r for r in theirs_real if r is not None],
                    )
                    if soft:
                        hits = soft
                        best_effort = True
            if not hits:
                continue
            item = {
                "lane_id": lane_id,
                "goal_id": their_goal,
                "shared": sorted({a for a, _ in hits} | {b for _, b in hits}),
                "best_effort": best_effort,
            }
            if their_goal != my_goal_id:
                conflicts.append(item)
            else:
                same_goal.append(item)
        report = {
            "own_paths_empty": not my_paths,
            "conflicts": conflicts,
            "unknowns": unknowns,
            "same_goal_overlaps": same_goal,
            "enforce": self._enforce_cross_goal,
        }
        self.last_cross_goal_report = report
        if self._enforce_cross_goal:
            if report["own_paths_empty"]:
                raise LanePathConflictUnknown(
                    "本方未声明 paths，冲突面不可判定（enforce fail-closed；处置: 补 paths 或 owner 裁决）",
                    unknowns=[{"lane_id": "", "goal_id": my_goal_id, "reason": "own paths empty"}],
                )
            if conflicts:
                raise LanePathConflict(
                    "跨 Goal 声明路径确证重叠（enforce 硬拒；处置: 缩小 paths / 请求 owner 复核 / 等对端终态）",
                    conflicts=conflicts,
                )
            if unknowns:
                raise LanePathConflictUnknown(
                    "存在冲突面不可判定的在途 lane（enforce fail-closed；处置: 补 paths 或 owner 裁决）",
                    unknowns=unknowns,
                )
        return report

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

    # ---------------- lane 生命周期收尾（DESIGN-20261114 §4.3） ----------------

    @staticmethod
    def _idle_hours(entry: dict, now_dt: datetime | None) -> float | None:
        """距 max(last_activity, closing_since) 的小时数；naive/不可解析返回 None。"""
        if now_dt is None:
            return None
        parsed = []
        for raw in (
            str(entry.get("last_activity") or "").strip(),
            str(entry.get("closing_since") or "").strip(),
        ):
            if not raw:
                continue
            try:
                ts = datetime.fromisoformat(raw)
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.astimezone()
            parsed.append(ts)
        if not parsed:
            return None
        return (now_dt - max(parsed)).total_seconds() / 3600.0

    def append_lane_event(self, event_type: str, **fields: object) -> bool:
        """追加一条 lane 事件到 lane_events.jsonl；写失败返回 False（不吞主操作结果）。"""
        event: dict = {"type": str(event_type), "ts": system_local_now().isoformat()}
        event.update(fields)
        try:
            self._append_event(event)
            return True
        except OSError:
            logger.warning("lane 事件写入失败: %s", event_type, exc_info=True)
            return False

    def reap_candidates(
        self,
        *,
        ttl_hours: float = 168.0,
        limit: int = 20,
        liveness_probe: Callable[[str], object] | None = None,
        tree_probe: Callable[[str], str] | None = None,
        now: str | None = None,
    ) -> dict:
        """纯读：筛出超时 lane 并按三判据分三态。零写盘、零 git 调用。

        判据三元组（全部成立才 conclusive）：
        1. idle_ttl——距 max(last_activity, closing_since) 超过 ttl_hours；
        2. liveness——注入的探针返回 "dead"（探针缺失/抛错/unknown 一律不收口）；
        3. tree_state——注入的 tree_probe 返回 "clean"（树脏只标疑，不动目录）。

        「超时≠死亡」（DESIGN-20261114 D1）：时间只用于筛候选，不用于判死。
        """
        now_ts = str(now) if now else system_local_now().isoformat()
        try:
            now_dt = datetime.fromisoformat(now_ts)
        except ValueError:
            now_dt = None
        if now_dt is not None and now_dt.tzinfo is None:
            now_dt = now_dt.astimezone()
        probe = liveness_probe if callable(liveness_probe) else None
        rows = [
            r
            for r in self._read_rows()
            if str(r.get("status") or "open") not in TERMINAL_STATUSES
        ]
        out: list[dict] = []
        counts = {"conclusive": 0, "suspect": 0, "unavailable": 0}
        for entry in rows:
            idle = self._idle_hours(entry, now_dt)
            if idle is None or idle <= float(ttl_hours):
                continue
            owner = str(entry.get("owner_session_id") or "").strip()
            liveness = "unavailable"
            if probe is not None:
                if owner:
                    try:
                        raw = str(probe(owner) or "").strip().lower()
                    except Exception:
                        raw = ""
                    liveness = raw if raw in ("alive", "dead") else "unknown"
                else:
                    liveness = "unknown"
            tree_state = "unknown"
            if callable(tree_probe):
                worktree = str(entry.get("worktree") or "").strip()
                if worktree:
                    try:
                        tree_state = str(tree_probe(worktree) or "unknown")
                    except Exception:
                        tree_state = "unknown"
            if liveness == "dead" and tree_state == "clean":
                verdict = "conclusive"
            elif liveness == "unavailable":
                verdict = "unavailable"
            else:
                verdict = "suspect"
            counts[verdict] += 1
            out.append(
                {
                    "lane_id": entry.get("lane_id"),
                    "status": entry.get("status"),
                    "owner_session_id": owner,
                    "worktree": entry.get("worktree"),
                    "idle_hours": round(idle, 3),
                    "liveness": liveness,
                    "tree_state": tree_state,
                    "verdict": verdict,
                }
            )
            if len(out) >= max(1, int(limit)):
                break
        return {
            "now": now_ts,
            "ttl_hours": float(ttl_hours),
            "liveness_available": probe is not None,
            "candidates": out,
            "counts": counts,
            "scanned": len(rows),
        }

    def _append_event(self, event: dict) -> bool:
        """只追加历史；写失败只告警不吞主写结果（与 goal.py 的 fail-open 口径一致）。

        M2-A §3.2-6（事件流独立）: 主账本提交与事件写入是两个独立事实。strict
        下事件写失败 → 置 last_event_append_failed=True，由工具层回执显式披露
        event_append_failed；不回滚主账本、不谎称全成功、也不把「事件写失败」
        伪装成「主账本未提交」。事件锁外独立写（不嵌套持 lanes 锁）。
        """
        try:
            with self._event_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return True
        except OSError:
            if self._lock_strict:
                self.last_event_append_failed = True
            logger.warning("lane_events 写入失败（主账本已提交）: %s", self._event_path, exc_info=True)
            return False

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
        """lanes.jsonl 跨进程写锁；仅锁获取失败时 fail-open，业务 I/O 异常原样传播。

        M2-A §3.2-1: lock_strict=true 时锁获取失败改为 fail-closed
        （LaneStoreLockUnavailable）——fcntl 缺失 / flock OSError / 锁文件
        不可写三种情况一致拒写，create/update/close 任何入口不降级放行。
        """
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        try:
            import fcntl
        except ImportError:
            if self._lock_strict:
                raise LaneStoreLockUnavailable(
                    f"fcntl 不可用且 lock_strict=true（fail-closed 拒写）: {lock_path}"
                ) from None
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
            if self._lock_strict:
                raise LaneStoreLockUnavailable(
                    f"lane 存储锁不可用且 lock_strict=true（fail-closed 拒写）: {lock_path}: {exc}"
                ) from exc
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

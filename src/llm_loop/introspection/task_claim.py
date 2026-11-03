"""Task claim 层：执行权租约 + fencing（DESIGN-20261103 §6.1–§6.6，阶段 PR-1）.

问题：task 账本是 append-only last-wins，没有"谁在执行这条 task"的权威事实。
两个 run 同时更新同一条 task 时都能写成功，post-check 无法分辨谁的写入是有效的
—— 这就是无 fencing 的典型故障。

本模块提供三件事：

1. **执行权（claim）**：``<audit>/claims/claim-<safe_goal_id>.jsonl`` append-only
   （**每个 goal 一份**，D-1；不是单文件 ``ledger.jsonl``），
   一次 grant/renew/release/revoke 一行，重放取每个 (goal_id, task_id) 的最后一行。
   过期是**派生态**（``expires_ms <= now``），不靠后台扫描、不在读路径写文件。
2. **fencing**：``token = "<claim_id>#<generation>"``。generation 每次换手 +1，
   旧的 token 永远对不上新 generation → 「过期后被别人接管，旧 owner 的迟到写入」
   会被拒绝而不是静默覆盖。
3. **组合入口**：``update_task_under_claim`` 在同一把 claims 锁内完成
   「校验 token → 必要时撤销旧 claim → 写入 task 账本」，并把真实决策写进
   ``claims_events`` 事件流（decision 不再是 PR-0 的 passthrough）。

锁序（固定，防死锁）：**claims 锁 → tasks 锁**。任何路径都不得反向获取。
因此本模块是唯一持有 claims 锁的地方，``task_store`` 从不 import 本模块的锁。

写失败语义（§6.3）：claim 账本 append 失败 → **拒绝**该操作（不是 fail-open）。
claim 只是执行权，丢了它任务不会凭空消失，所以"宁可拒绝"的代价是可接受的；
反过来放行会让两个 run 都以为自己在执行。

PR-1 的边界：``claim_enforcement="warn"``（默认）下，没有 token 的 task 写入
仍然成功，只在回执里给 ``claim_conflict_warning``。硬拒绝（enforce）留 PR-2。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_loop.timekeeping import system_local_now

from .claims.events import claims_dir, write_event
from .task_store import Task, TaskStore, safe_goal_id, write_holder

logger = logging.getLogger(__name__)

#: 每个 goal 一套账本文件，文件名**必须**与 task 账本同一归一函数（T-1.7）：
#: 若两处各自实现归一，claim 会落到另一个文件名上，claim 静默失效且看不出错。
LEDGER_TEMPLATE = "claim-{safe}.jsonl"
LOCK_TEMPLATE = "claim-{safe}.lock"
#: 折叠阈值（§6.2/T-1.1）：超过即把"当前态"重写为一行一 claim，原子替换。
COMPACT_ROW_THRESHOLD = 2000

MIN_TTL_S = 60
DEFAULT_TTL_S = 1800
MAX_TTL_S = 28800
MAX_CLAIMS_PER_HOLDER = 8

STATE_ACTIVE = "active"
STATE_RELEASED = "released"
STATE_REVOKED = "revoked"

#: 允许带 token 写入的 task 状态（§6.1 claim 只覆盖"可执行"任务）.
CLAIMABLE_STATES = frozenset({"pending", "in_progress"})

_CLAIM_PROCESS_LOCK = threading.Lock()


def now_ms() -> int:
    """claim 层统一时钟（毫秒）。所有租约算术都用它，便于测试替换."""
    return int(system_local_now().timestamp() * 1000)


def _ms_to_iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0).astimezone().isoformat(timespec="seconds")


def mask_holder(session_id: str | None) -> str:
    """持有者标识的对外形态（§6.3 模板）：≤8 字符原样，否则前 8 + 省略号.

    与 ``goal_coordination.mask_session`` 同规则，但**不跨模块 import**——claim 层
    不该为了一个 3 行函数把 introspection 的视图模块拉进 import 图。
    冲突回执/工具消息一律用它，避免把别人的完整 sid 写进模型可见文本。
    """
    sid = str(session_id or "")
    if not sid:
        return ""
    return sid if len(sid) <= 8 else f"{sid[:8]}…"


# ---------------------------------------------------------------- 策略


@dataclass(frozen=True, slots=True)
class ClaimPolicy:
    """claim 的运行参数。默认值与 §6.5 一致；用户可用环境变量覆盖."""

    ttl_s: int = DEFAULT_TTL_S
    max_ttl_s: int = MAX_TTL_S
    allow_unbounded: bool = False
    max_per_holder: int = MAX_CLAIMS_PER_HOLDER
    enforcement: str = "warn"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def policy_from_env() -> ClaimPolicy:
    """从环境读 claim 策略；**clamp 规则必须与 config.py 完全一致**。

    config.ToolRuntimeSettings 对同一批 env 做了 max(60)/max(1)/集合校验；
    这里若只读不 clamp，`LFL_CLAIM_TTL_S=1` 会绕过 config 的下界，签出 1 秒租约
    （test_policy_matches_config_defaults 只比默认值，比不出这个差异）。
    """
    ttl = max(60, _env_int("LFL_CLAIM_TTL_S", DEFAULT_TTL_S))
    max_ttl = max(60, _env_int("LFL_CLAIM_MAX_TTL_S", MAX_TTL_S))
    enforcement = os.environ.get("LFL_CLAIM_ENFORCEMENT", "").strip().lower() or "warn"
    if enforcement not in {"off", "warn", "enforce"}:
        enforcement = "warn"  # 与 config._mode 一致：未知值回落到最保守的可观测档
    return ClaimPolicy(
        ttl_s=ttl,
        max_ttl_s=max_ttl,
        allow_unbounded=os.environ.get("LFL_CLAIM_ALLOW_UNBOUNDED", "").strip().lower()
        in {"1", "true", "yes", "on"},
        max_per_holder=max(1, _env_int("LFL_CLAIM_MAX_PER_HOLDER", MAX_CLAIMS_PER_HOLDER)),
        enforcement=enforcement,
    )


# ---------------------------------------------------------------- 错误


class ClaimError(Exception):
    """claim 操作的机械失败。``code`` 是稳定的机器可读原因码."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class ClaimRefusedError(ClaimError):
    """业务拒绝（冲突/过期/配额/token 不匹配）。调用方应把 code 原样回执给模型."""


class ClaimLedgerUnavailableError(ClaimError):
    """账本不可写。必须拒绝操作（§6.3：不放行）."""


# ---------------------------------------------------------------- 数据


@dataclass(slots=True)
class Claim:
    claim_id: str
    goal_id: str
    task_id: str
    holder: str
    holder_kind: str
    generation: int
    state: str
    granted_ms: int
    renewed_ms: int
    expires_ms: int | None
    expected_paths: list[str] = field(default_factory=list)
    unbounded: bool = False
    action: str = "grant"
    #: 仅供回执展示：本次续期是「已过期但未被接管」后的续期（N2-A7）
    renewed_after_expiry: bool = False

    @property
    def token(self) -> str:
        return f"{self.claim_id}#{self.generation}"

    def is_active(self, now_ms: int) -> bool:
        if self.state != STATE_ACTIVE:
            return False
        if self.unbounded or self.expires_ms is None:
            return True
        return self.expires_ms > now_ms

    def expired(self, now_ms: int) -> bool:
        return self.state == STATE_ACTIVE and not self.is_active(now_ms)

    def to_row(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "goal_id": self.goal_id,
            "task_id": self.task_id,
            "holder": self.holder,
            "holder_kind": self.holder_kind,
            "generation": self.generation,
            "state": self.state,
            "granted_ms": self.granted_ms,
            "renewed_ms": self.renewed_ms,
            "expires_ms": self.expires_ms,
            "expected_paths": list(self.expected_paths),
            "unbounded": self.unbounded,
            "action": self.action,
        }

    @classmethod
    def from_row(cls, d: dict[str, Any]) -> Claim:
        return cls(
            claim_id=str(d.get("claim_id", "")),
            goal_id=str(d.get("goal_id", "")),
            task_id=str(d.get("task_id", "")),
            holder=str(d.get("holder", "")),
            holder_kind=str(d.get("holder_kind", "main")),
            generation=int(d.get("generation", 0) or 0),
            state=str(d.get("state", STATE_ACTIVE)),
            granted_ms=int(d.get("granted_ms", 0) or 0),
            renewed_ms=int(d.get("renewed_ms", 0) or 0),
            expires_ms=(int(d["expires_ms"]) if d.get("expires_ms") is not None else None),
            expected_paths=[str(p) for p in (d.get("expected_paths") or [])],
            unbounded=bool(d.get("unbounded", False)),
            action=str(d.get("action", "grant")),
        )

    def receipt(self, now_ms: int) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "token": self.token,
            "goal_id": self.goal_id,
            "task_id": self.task_id,
            "holder": self.holder,
            "holder_kind": self.holder_kind,
            "generation": self.generation,
            "unbounded": self.unbounded,
            "granted_at": _ms_to_iso(self.granted_ms),
            "renewed_at": _ms_to_iso(self.renewed_ms),
            "expires_at": _ms_to_iso(self.expires_ms),
            "ttl_remaining_s": (
                None if self.expires_ms is None else max(0, round((self.expires_ms - now_ms) / 1000.0, 1))
            ),
            "expected_paths": list(self.expected_paths),
            "active": self.is_active(now_ms),
            "renewed_after_expiry": self.renewed_after_expiry,
        }


@dataclass(frozen=True, slots=True)
class CheckResult:
    ok: bool
    code: str | None
    claim: Claim | None

    def reason(self) -> str:
        return self.code or "ok"


# ---------------------------------------------------------------- 路径归一


def normalize_paths(paths: list[str] | None) -> list[str]:
    """expected_paths 归一：去空白、去尾斜杠、normpath。不展开符号链接（只做冲突提示）."""
    out: list[str] = []
    for raw in paths or []:
        p = str(raw).strip()
        if not p:
            continue
        q = os.path.normpath(p)
        if len(q) > 1:
            q = q.rstrip(os.sep)
        if q and q not in out:
            out.append(q)
    return out


def _paths_overlap(a: str, b: str) -> bool:
    if a == b:
        return True
    pa = a.rstrip("/") + "/"
    pb = b.rstrip("/") + "/"
    return pa.startswith(pb) or pb.startswith(pa)


def overlapping_paths(mine: list[str], theirs: list[str]) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for a in mine:
        for b in theirs:
            if _paths_overlap(a, b):
                hits.append((a, b))
    return hits


# ---------------------------------------------------------------- 存储


class ClaimStore:
    """claims 账本。一个 audit_dir 一套文件；所有变更都在同一把 claims 锁内."""

    def __init__(self, audit_dir: str | os.PathLike[str], *, policy: ClaimPolicy | None = None) -> None:
        self._dir = claims_dir(audit_dir)
        self.audit_dir = str(audit_dir)
        self._policy = policy or policy_from_env()
        #: 读路径坏行计数（供 metrics 标注分母完整性）
        self.bad_lines = 0

    # -------- 基础

    def ledger_path(self, goal_id: str) -> Path:
        return self._dir / LEDGER_TEMPLATE.format(safe=safe_goal_id(goal_id))

    def lock_path(self, goal_id: str) -> Path:
        return self._dir / LOCK_TEMPLATE.format(safe=safe_goal_id(goal_id))

    @property
    def policy(self) -> ClaimPolicy:
        return self._policy

    @staticmethod
    def _now_ms() -> int:
        # 统一走模块级 now_ms()，测试可整体替换时钟（租约算术只依赖这一个入口）
        return now_ms()

    @contextmanager
    def _lock(self, goal_id: str) -> Iterator[None]:
        """claims 全局锁：进程内 threading + flock（macOS 同进程多 fd flock 不保证自冲突）."""
        with _CLAIM_PROCESS_LOCK:
            try:
                import fcntl
            except ImportError:  # pragma: no cover - 非 POSIX
                yield
                return
            self._dir.mkdir(parents=True, exist_ok=True)
            handle = None
            try:
                handle = self.lock_path(goal_id).open("a", encoding="utf-8")
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except OSError as exc:
                if handle is not None:
                    handle.close()
                # 锁不可用 → 不静默放行 claim 变更（§6.3：账本失效必须拒绝）
                raise ClaimLedgerUnavailableError(
                    "claim_lock_unavailable", f"claims 锁不可用: {self.lock_path(goal_id)}: {exc}"
                ) from exc
            try:
                yield
            finally:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                finally:
                    handle.close()

    def _iter_rows(self, goal_id: str) -> Iterator[dict[str, Any]]:
        path = self.ledger_path(goal_id)
        if not path.exists():
            return
        bad = 0
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    d = json.loads(raw)
                except json.JSONDecodeError:
                    bad += 1  # 截断/半行 → 跳过，不整单失败
                    continue
                if isinstance(d, dict) and d.get("claim_id"):
                    yield d
                else:
                    bad += 1
        if bad:
            self.bad_lines = bad
            logger.warning("claims 账本含 %d 坏行已跳过: %s", bad, path)

    def _replay(self, goal_id: str) -> dict[tuple[str, str], Claim]:
        """重放取最后一行（last-wins）。按 (goal_id, task_id) 覆盖."""
        current: dict[tuple[str, str], Claim] = {}
        for row in self._iter_rows(goal_id):
            try:
                claim = Claim.from_row(row)
            except (TypeError, ValueError):
                self.bad_lines += 1
                continue
            if not claim.goal_id or not claim.task_id:
                continue
            current[(claim.goal_id, claim.task_id)] = claim
        return current

    def _append(self, claim: Claim) -> None:
        """append + fsync。失败 → ClaimLedgerUnavailableError（调用方必须拒绝操作）."""
        row = claim.to_row()
        row["ts"] = system_local_now().isoformat(timespec="seconds")
        blob = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with self.ledger_path(claim.goal_id).open("ab") as fh:
                fh.write(blob)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            raise ClaimLedgerUnavailableError(
                "claim_ledger_unavailable",
                f"claims 账本写入失败: {self.ledger_path(claim.goal_id)}: {exc}",
            ) from exc

    def _maybe_compact(self, goal_id: str) -> None:
        """行数超阈值 → 只保留每个 (goal, task) 的当前行，原子替换（§6.2）."""
        path = self.ledger_path(goal_id)
        try:
            if not path.exists():
                return
            with path.open("rb") as fh:
                lines = sum(1 for _ in fh)
            if lines <= COMPACT_ROW_THRESHOLD:
                return
            current = self._replay(goal_id)
            tmp = path.with_suffix(".jsonl.tmp")
            with tmp.open("wb") as fh:
                for claim in current.values():
                    row = claim.to_row()
                    row["ts"] = system_local_now().isoformat(timespec="seconds")
                    fh.write((json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            logger.info("claims 账本已折叠: %d 行 → %d 条", lines, len(current))
        except OSError as exc:  # 折叠失败不影响正确性（重放仍然正确）
            logger.warning("claims 账本折叠失败（忽略）: %s", exc)

    # -------- 读

    def current(self, goal_id: str, task_id: str) -> Claim | None:
        return self._replay(goal_id).get((goal_id, task_id))

    def active_claims(self, goal_id: str) -> list[Claim]:
        now = self._now_ms()
        return [c for (g, _), c in self._replay(goal_id).items() if g == goal_id and c.is_active(now)]

    # -------- TTL

    def _clamp_ttl(self, ttl_s: Any) -> int:
        if ttl_s is None:
            # 无显式 ttl 时 policy 值也要过下界：程序化构造的 ClaimPolicy(ttl_s=1)
            # 绕过了 env 侧 clamp，会签出 1 秒租约（第四轮审查 P2-5）。
            return max(MIN_TTL_S, self._policy.ttl_s)
        if isinstance(ttl_s, bool) or not isinstance(ttl_s, (int, float)):
            raise ClaimRefusedError("ttl_invalid", f"ttl_s 必须是整数秒: {ttl_s!r}")
        value = int(ttl_s)
        if value <= 0:
            raise ClaimRefusedError("ttl_invalid", f"ttl_s 必须为正: {value}")
        return max(MIN_TTL_S, min(value, self._policy.max_ttl_s))

    def _deadline(self, now_ms: int, ttl_s: int, unbounded: bool) -> int | None:
        if unbounded:
            return None
        return now_ms + ttl_s * 1000

    # -------- T-1.1 / T-1.2：grant

    def grant(
        self,
        goal_id: str,
        task_id: str,
        *,
        holder: str | None = None,
        ttl_s: int | None = None,
        expected_paths: list[str] | None = None,
        unbounded: bool = False,
        store: TaskStore | None = None,
    ) -> Claim:
        """领取执行权。同 holder 重复 claim 幂等（不换 generation，沿用 claim_id）."""
        holder = holder or write_holder()
        if not holder:
            raise ClaimRefusedError("holder_unavailable", "无法确定当前 run 身份，拒绝签发 claim")
        paths = normalize_paths(expected_paths)
        if unbounded and not self._policy.allow_unbounded:
            raise ClaimRefusedError(
                "claim_ttl_out_of_range",
                "无期限 claim 未获授权（LFL_CLAIM_ALLOW_UNBOUNDED 未开启）",
            )
        ttl = self._clamp_ttl(ttl_s)
        with self._lock(goal_id):
            claims = self._replay(goal_id)
            now = self._now_ms()
            existing = claims.get((goal_id, task_id))
            # 事实优先（§6.2 第 (1) 步）：task 可 claim 是**无条件**前提，
            # 与「是否已存在旧 claim」无关——否则过期 claim 的 reclaim 路径会
            # 跳过状态检查，允许对 done/failed/cancelled 任务签发 claim。
            if store is not None:
                task = store.get(goal_id, task_id)  # 锁序：claims → tasks
                if task is None:
                    raise ClaimRefusedError("task_not_found", f"任务不存在: {goal_id}/{task_id}")
                if task.status not in CLAIMABLE_STATES:
                    raise ClaimRefusedError(
                        "task_not_claimable",
                        f"任务当前状态 {task.status} 不可 claim（仅 {sorted(CLAIMABLE_STATES)}）",
                    )
            if existing is not None and existing.is_active(now):
                if existing.holder != holder:
                    raise ClaimRefusedError(
                        "task_claimed_by_other",
                        f"已被 {mask_holder(existing.holder)} 持有至 {_ms_to_iso(existing.expires_ms)}",
                    )
                # 幂等 refresh：沿用 claim_id/generation，只延长租约
                renewed = replace(
                    existing,
                    renewed_ms=max(now, existing.renewed_ms),
                    expires_ms=self._deadline(max(now, existing.renewed_ms), ttl, unbounded),
                    unbounded=unbounded or existing.unbounded,
                    expected_paths=paths or existing.expected_paths,
                    action="renew",
                )
                self._append(renewed)
                self._emit(renewed, "grant", reason_code="idempotent", actor=holder)
                return renewed
            # 配额：同一 holder 的活跃 claim 数。§6.5 规定这是**仅警告**的软指标
            # （max_claims_per_holder=8）——超了说明 fanout 铺得太开，但不该让
            # 正在推进的任务因此失败，故记入 notes/reason_code 而不拒绝。
            # 口径说明（审查 P2-3）：`mine` 只在**本 goal 的账本文件**里统计，所以它是
            # per-goal 而非 §6.5 字面的跨 goal 每 holder。这是有意的——claim 文件按
            # goal 隔离（D-1），跨 goal 聚合要读全部账本，成本与锁面都不划算，而软指标
            # 不需要全局精确值。读数时按"单 goal 内同一 holder 的活跃 claim 数"解释。
            mine = [c for (g, t), c in claims.items() if c.is_active(now) and c.holder == holder]
            quota_exceeded = len(mine) >= self._policy.max_per_holder
            generation = (existing.generation + 1) if existing is not None else 1
            claim = Claim(
                claim_id=f"CLM-{uuid.uuid4().hex[:12]}",
                goal_id=goal_id,
                task_id=task_id,
                holder=holder,
                holder_kind="subagent" if holder.startswith("subagent_") else "main",
                generation=generation,
                state=STATE_ACTIVE,
                granted_ms=now,
                renewed_ms=now,
                expires_ms=self._deadline(now, ttl, unbounded),
                expected_paths=paths,
                unbounded=unbounded,
                action="reclaim" if existing is not None else "grant",
            )
            self._append(claim)
            self._maybe_compact(goal_id)
            self._emit(
                claim,
                "reclaim" if existing is not None else "grant",
                reason_code=(
                    "expired_reclaimed"
                    if existing is not None
                    else ("claim_quota_exceeded_warning" if quota_exceeded else None)
                ),
                actor=holder,
                ttl_s=ttl,
                expired=existing is not None,
            )
            self._warn_path_overlap(claim, claims, now)
            return claim

    def _warn_path_overlap(
        self, claim: Claim, claims: dict[tuple[str, str], Claim], now: int
    ) -> list[tuple[str, str]]:
        """不同 claim 的 expected_paths 交叉 → 提示（§5-N5，只警告不拒绝）."""
        if not claim.expected_paths:
            return []
        hits: list[tuple[str, str]] = []
        for (g, t), other in claims.items():
            if g != claim.goal_id or t == claim.task_id or not other.is_active(now):
                continue
            for pair in overlapping_paths(claim.expected_paths, other.expected_paths):
                hits.append(pair)
        if hits:
            logger.warning(
                "claim 路径可能交叉: %s/%s 与其它活跃 claim 重叠 %s", claim.goal_id, claim.task_id, hits[:3]
            )
        return hits

    # -------- T-1.2：renew / release

    def renew(
        self,
        goal_id: str,
        task_id: str,
        *,
        token: str,
        ttl_s: int | None = None,
        holder: str | None = None,
    ) -> Claim:
        holder = holder or write_holder()
        if not holder:
            raise ClaimRefusedError("holder_unavailable", "无法确定当前 run 身份，拒绝续租")
        ttl = self._clamp_ttl(ttl_s)
        with self._lock(goal_id):
            claims = self._replay(goal_id)
            now = self._now_ms()
            check = self._check(claims.get((goal_id, task_id)), token, holder, now)
            if not check.ok:
                raise ClaimRefusedError(check.code or "claim_absent", "续租被拒")
            claim = check.claim
            assert claim is not None
            renewed_after_expiry = claim.expired(now)
            renewed = replace(
                claim,
                renewed_ms=max(now, claim.renewed_ms),
                expires_ms=self._deadline(max(now, claim.renewed_ms), ttl, claim.unbounded),
                state=STATE_ACTIVE,
                action="renew",
                renewed_after_expiry=renewed_after_expiry,
            )
            self._append(renewed)
            self._maybe_compact(goal_id)
            self._emit(renewed, "renew", actor=holder, ttl_s=ttl, expired=renewed_after_expiry)
            return renewed

    def release(
        self,
        goal_id: str,
        task_id: str,
        *,
        token: str | None = None,
        holder: str | None = None,
    ) -> bool:
        holder = holder or write_holder()
        if not holder and not token:
            # 纵深防御：既无法证明是持有者、又没有 token 时，不得释放任何活跃 claim。
            # （工具层总会带 token 或 run 身份；这条只挡住绕过工具层的直接调用。）
            raise ClaimRefusedError(
                "holder_unavailable", "无法证明持有者身份且未提供 claim token，拒绝释放"
            )
        with self._lock(goal_id):
            claims = self._replay(goal_id)
            now = self._now_ms()
            claim = claims.get((goal_id, task_id))
            if claim is None or not claim.is_active(now):
                return False
            if holder and claim.holder != holder:
                raise ClaimRefusedError("claim_holder_mismatch", f"claim 属于 {mask_holder(claim.holder)}，不是当前 run")
            if token:
                check = self._check(claim, token, holder, now)
                if not check.ok:
                    raise ClaimRefusedError(check.code or "claim_token_mismatch", "释放被拒")
            released = replace(claim, state=STATE_RELEASED, action="release")
            self._append(released)
            self._emit(released, "release", actor=holder or claim.holder)
            return True

    def revoke(self, goal_id: str, task_id: str, *, actor: str | None = None) -> Claim | None:
        """撤销该任务上所有活跃 claim（重开/外部接管时用）。返回被撤销的 claim."""
        with self._lock(goal_id):
            claims = self._replay(goal_id)
            now = self._now_ms()
            claim = claims.get((goal_id, task_id))
            if claim is None or not claim.is_active(now):
                return None
            revoked = replace(claim, state=STATE_REVOKED, action="revoke")
            self._append(revoked)  # 写失败 → ClaimLedgerUnavailableError 直接冒泡（必须拒绝重开）
            self._emit(revoked, "revoke", actor=actor or write_holder(), revoked=True)
            return revoked

    # -------- 校验

    def _check(self, claim: Claim | None, token: str, holder: str | None, now: int) -> CheckResult:
        """校验 token 是否仍代表执行权。

        **过期本身不是失权**（Q33 / N2-A15）：时间不承担安全职责，唯一的安全边界是
        generation。已过期满但没被接管 → 放行并顺带续期（``claim_expired_renewed``）；
        被接管（generation 落后 / claim_id 已换）或已 released/revoked → 拒绝。
        这条差别是必须的：把过期当失权会让「长任务跨过一次 TTL」的写入无故失败，
        而真正的僵尸问题已经由 generation 挡住了。
        """
        if claim is None:
            return CheckResult(False, "claim_absent", None)
        wanted_id, _, wanted_gen = str(token).partition("#")
        if claim.claim_id != wanted_id:
            return CheckResult(False, "claim_generation_stale", claim)
        if wanted_gen:
            # 带 generation 段就必须是数字：`CLM-x#junk` 这类畸形 token 以前会被
            # "跳过比较"部分放行（第四轮审查 P2-6），现在直接拒绝而不是半校验。
            if not wanted_gen.isdigit():
                return CheckResult(False, "claim_token_malformed", claim)
            if claim.generation != int(wanted_gen):
                return CheckResult(False, "claim_generation_stale", claim)
        if claim.state == STATE_RELEASED:
            return CheckResult(False, "claim_released", claim)
        if claim.state == STATE_REVOKED:
            return CheckResult(False, "claim_revoked", claim)
        if holder and claim.holder != holder:
            return CheckResult(False, "claim_holder_mismatch", claim)
        return CheckResult(True, None, claim)

    def check(self, goal_id: str, task_id: str, token: str, *, holder: str | None = None) -> CheckResult:
        claim = self.current(goal_id, task_id)
        return self._check(claim, token, holder or write_holder(), self._now_ms())

    # -------- 事件

    def _emit_raw(
        self,
        goal_id: str,
        task_id: str,
        holder: str,
        generation: int,
        decision: str,
        *,
        reason_code: str | None = None,
        actor: str | None = None,
        ttl_s: int | None = None,
        expired: bool = False,
        revoked: bool = False,
        auto: bool = False,
        latency_ms: float | None = None,
    ) -> None:
        write_event(
            self.audit_dir,
            "claim_decision",
            goal_id=goal_id,
            task_id=task_id,
            holder=holder or None,
            decision=decision,
            reason_code=reason_code,
            claim_generation=generation,
            auto=auto,
            ttl_s=ttl_s or self._policy.ttl_s,
            expired=expired,
            revoked=revoked,
            actor=actor,
            latency_ms=latency_ms,
        )

    def _emit(self, claim: Claim, decision: str, **kwargs: Any) -> None:
        self._emit_raw(
            claim.goal_id, claim.task_id, claim.holder, claim.generation, decision, **kwargs
        )

    # -------- T-1.3/T-1.4/T-1.5：组合入口

    def _resolve_token_or_conflict(
        self,
        claim: Claim | None,
        *,
        token: str | None,
        holder: str | None,
        now: int,
        task_before: Task,
        notes: dict[str, Any],
    ) -> tuple[Claim | None, str, str | None, Claim | None]:
        """校验 token 或判定他人持有；返回 ``(claim, decided, reason_code, renew_after)``。

        有 token 就必须完全对得上（warn 模式也不放宽：token 是"我在执行这条 task"
        的显式声明，对不上说明是过期 holder）。无 token 且他人持活跃 claim 时按
        ``claim_enforcement`` 决定：enforce → deny 事件 + 硬拒；否则只记警告（N3）。

        ``renew_after`` 非空表示"应续租"，但**不在此落账**：调用方须在
        ``store.update`` 成功后 append，保证账本变更与 claim_decision 事件 1:1（D-8）。
        """
        if token:
            check = self._check(claim, token, holder, now)
            if not check.ok:
                raise ClaimRefusedError(check.code or "claim_absent", "claim 校验失败")
            if task_before.status not in CLAIMABLE_STATES:
                raise ClaimRefusedError(
                    "task_not_claimable",
                    f"任务当前状态 {task_before.status} 不可 claim（仅 {sorted(CLAIMABLE_STATES)}）",
                )
            assert check.claim is not None
            current = check.claim
            if current.expired(now):
                # 软过期：generation 仍匹配说明无人接管，放行并续期（N2-A15）
                notes["claim_expired_renewed"] = True
            renew_after = replace(
                current,
                renewed_ms=max(now, current.renewed_ms),
                expires_ms=self._deadline(
                    max(now, current.renewed_ms), self._policy.ttl_s, current.unbounded
                ),
                action="renew",
            )
            notes["claim_renewed"] = True
            return renew_after, "renew", None, renew_after

        enforcement = (self._policy.enforcement or "warn").lower()
        if (
            enforcement != "off"
            and claim is not None
            and claim.is_active(now)
            and holder
            and claim.holder != holder
        ):
            if enforcement == "enforce":
                self._emit(claim, "deny", reason_code="claim_held_by_other", actor=holder)
                raise ClaimRefusedError("claim_held_by_other", f"任务由 {mask_holder(claim.holder)} 持有")
            notes["claim_conflict_warning"] = mask_holder(claim.holder)
            return claim, "passthrough", "claim_held_by_other", None
        return claim, "passthrough", None, None

    def _revoke_on_reopen(
        self,
        claim: Claim | None,
        *,
        task_before: Task,
        target_status: str | None,
        now: int,
        notes: dict[str, Any],
        holder: str | None = None,
    ) -> Claim | None:
        """done→非done 重开：先用撤销抹掉旧 claim；落账失败即冒泡，重开必须被拒（Q38）。"""
        reopening = (
            task_before.status == "done"
            and target_status is not None
            and target_status != "done"
        )
        if not reopening or claim is None or not claim.is_active(now):
            return claim
        revoked = replace(claim, state=STATE_REVOKED, action="revoke")
        self._append(revoked)  # 失败 → ClaimLedgerUnavailableError，重开被拒
        # 账本 revoke 行必须有一条 claim_decision 对应（T-1.10 的 1:1）。
        # 以前只在账本写行、事件留到最后一条 passthrough，`claim_metrics.revoke_count`
        # 因此看不到重开撤销（第四轮审查 P2-2）。
        self._emit(revoked, "revoke", reason_code="reopen_revoke", actor=holder or revoked.holder)
        notes["revoked_claim_id"] = revoked.claim_id
        return revoked

    def _auto_claim_on_start(
        self,
        claims: dict[tuple[str, str], Claim],
        claim: Claim | None,
        *,
        token: str | None,
        goal_id: str,
        task_id: str,
        holder: str | None,
        task_before: Task,
        target_status: str | None,
        now: int,
        notes: dict[str, Any],
    ) -> tuple[Claim | None, str | None]:
        """T-1.4 隐式签发：pending→in_progress 且无 token 时由程序签发。

        返回 ``(claim, grant_reason)``；不满足条件时 ``grant_reason is None``，
        调用方据此保留原有 ``decided``（不能无条件覆盖 token 路径的 renew）。
        """
        if not (
            token is None
            and target_status == "in_progress"
            and task_before.status == "pending"
            and holder
        ):
            return claim, None
        granted = self._grant_locked(claims, goal_id, task_id, holder=holder, now=now)
        notes["auto_claimed"] = granted.token
        notes["claim"] = granted.receipt(now)
        return granted, "auto_claim"

    def update_task_under_claim(
        self,
        store: TaskStore,
        goal_id: str,
        task_id: str,
        *,
        token: str | None = None,
        holder: str | None = None,
        authorized: bool = False,
        **fields: Any,
    ) -> tuple[Task, dict[str, Any]]:
        """在**同一把 claims 锁**内：校验 token → 撤销(重开) → 写 task 账本.

        锁序：claims 锁（本方法持有）→ tasks 锁（``store.update`` 内部获取）。
        返回 ``(task, notes)``；``notes`` 承载 auto_claimed / claim_expired_renewed /
        claim_conflict_warning / revoked_claim_id，供工具层如实回执。

        ``authorized``：**显式授权契约**。本方法会先改 claim 账本（隐式签发 / 重开撤销 /
        续租）再调 ``store.update``，自身不做归属判定；因此只允许已通过
        ``resolve_write_permission``（工具层 ``_require_active_goal``）的调用方传 True。
        未传即拒绝，避免"组合入口被直接调用就绕过归属门"。
        """
        if not authorized:
            raise ValueError(
                "update_task_under_claim 只能由已通过归属校验的调用方调用（需显式 authorized=True）"
            )
        holder = holder or write_holder()
        t0 = time.perf_counter()
        notes: dict[str, Any] = {}
        with self._lock(goal_id):
            claims = self._replay(goal_id)
            now = self._now_ms()
            claim = claims.get((goal_id, task_id))
            task_before = store.get(goal_id, task_id)  # 锁序：claims → tasks
            if task_before is None:
                raise ValueError(f"任务不存在: {task_id}（goal {goal_id}）")
            target_status = fields.get("status")

            # 1) token 校验 / 他人持有判定（细节见 _resolve_token_or_conflict）
            claim, decided, reason_code, renew_after = self._resolve_token_or_conflict(
                claim,
                token=token,
                holder=holder,
                now=now,
                task_before=task_before,
                notes=notes,
            )
            # 2) done→非done 重开：先撤销旧 claim（失败即拒绝重开）
            claim = self._revoke_on_reopen(
                claim,
                task_before=task_before,
                target_status=target_status,
                now=now,
                notes=notes,
                holder=holder,
            )
            # 3) T-1.4 隐式签发：pending→in_progress 且无 token
            #    但**他人已持活跃 claim 时不签发**：隐式签发的目的是让"无 token"不再是
            #    错误，不是让后来者抢走别人的 claim。以前这里会直接 reclaim 掉他人
            #    claim（generation+1），warn 档下等于静默抢锁——与 D1"硬拒只剩他人
            #    已持 claim"直接冲突。冲突场景保持现状（只警告、不签发）。
            if reason_code == "claim_held_by_other":
                granted_reason = None
            else:
                claim, granted_reason = self._auto_claim_on_start(
                    claims,
                    claim,
                    token=token,
                    goal_id=goal_id,
                    task_id=task_id,
                    holder=holder,
                    task_before=task_before,
                    target_status=target_status,
                    now=now,
                    notes=notes,
                )
            if granted_reason is not None:
                decided, reason_code = "grant", granted_reason

            if not holder:
                # 没有 run 身份就无法签发/校验 fencing：如实标注，不假装已受保护。
                # 这里不拒绝写入——否则脚本/评测这类无 run context 的调用会整体失败，
                # 而它们本来也不并发。拒绝只在 .enforce 下由上层（PR-2）决定。
                notes["claim_unavailable"] = "no_run_identity"
            task = store.update(goal_id, task_id, emit_event=False, **fields)
            if renew_after is not None:
                # update 已成功才落账续租：账本变更与下面这条 claim_decision 成对出现，
                # 不会出现"有 renew 行、无对应事件"的中间态（T-1.10）。
                try:
                    self._append(renew_after)
                    claim = renew_after
                except ClaimLedgerUnavailableError:
                    # 反方向缺口（审查 P2-1）：task 已持久化、租约没续上。此时若让异常
                    # 冒泡，调用方会拿到 FAILURE 却实际写成功——比缺口本身更危险。
                    # 改为成功 + 降级标注；安全面不受影响：generation 未变，租约到期
                    # 只意味着「可被接管」，不意味着「旧写入变合法」。
                    notes["claim_renew_unavailable"] = "ledger_unavailable"
            latency = round((time.perf_counter() - t0) * 1000.0, 3)
            # 冲突透传时 `claim` 指向**别人**的 claim 行：把它的 generation 写进
            # 本 holder 的事件，会让"这次写没有 fencing"读起来像"这次写拿到了第 N 代"
            # （第四轮审查 P2-1）。本次未持有 → 记 0，与他人代次彻底分开。
            emit_generation = (
                0
                if decided == "passthrough" and reason_code == "claim_held_by_other"
                else (claim.generation if claim is not None else 0)
            )
            self._emit_raw(
                goal_id,
                task_id,
                holder or "",
                emit_generation,
                decided,
                reason_code=reason_code,
                actor=holder,
                latency_ms=latency,
                auto=bool(notes.get("auto_claimed")),
            )
            self._maybe_compact(goal_id)
            return task, notes

    def _grant_locked(
        self,
        claims: dict[tuple[str, str], Claim],
        goal_id: str,
        task_id: str,
        *,
        holder: str,
        now: int,
    ) -> Claim:
        """在已持有 claims 锁的前提下签发（隐式 claim 用）。"""
        existing = claims.get((goal_id, task_id))
        # 配额仅警告（§6.5）；隐式签发不该因为"铺得开"而拒绝推进中的任务
        claim = Claim(
            claim_id=f"CLM-{uuid.uuid4().hex[:12]}",
            goal_id=goal_id,
            task_id=task_id,
            holder=holder,
            holder_kind="subagent" if holder.startswith("subagent_") else "main",
            generation=(existing.generation + 1) if existing is not None else 1,
            state=STATE_ACTIVE,
            granted_ms=now,
            renewed_ms=now,
            expires_ms=self._deadline(now, self._policy.ttl_s, False),
            action="reclaim" if existing is not None else "grant",
        )
        self._append(claim)
        return claim


# ---------------------------------------------------------------- 便捷函数


def update_task_under_claim(
    audit_dir: str | os.PathLike[str],
    goal_id: str,
    task_id: str,
    *,
    token: str | None = None,
    store: TaskStore | None = None,
    authorized: bool = False,
    **fields: Any,
) -> tuple[Task, dict[str, Any]]:
    """模块级组合入口（工具层用）；``authorized`` 语义同
    :meth:`ClaimStore.update_task_under_claim`。"""
    store = store or TaskStore(str(audit_dir))  # TaskStore 只收 str | Path
    return ClaimStore(audit_dir).update_task_under_claim(
        store, goal_id, task_id, token=token, authorized=authorized, **fields
    )

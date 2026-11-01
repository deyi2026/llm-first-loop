"""Task Frontier 执行账本（DESIGN-20260828，GOAL-20260828-df03e08e T1）.

设计: docs/local/DESIGN-20260828-task-frontier.md v0.2
- 程序记账（结构/依赖/状态/验收/证据引用），模型决策（优先级/领取/放弃）
- 状态: pending/in_progress/blocked/done/failed/cancelled
  （ready 为派生态——pending 且依赖全 done——不落盘，frontier 每轮计算，避免写放大）
- 持久化: audit_dir/tasks/<goal_id>.jsonl，append-only 全量行 last-wins 重放，
  天然审计留痕（防 acceptance 洗白：历史行不可篡改）；坏行跳过+告警（§6 crash 容错）
- 完整性: 依赖环/依赖failed 的 unreachable-pending 检测（hope 收紧 + Kahn 拓扑），
  done 重开 → 下游 premise_stale 级联，blocked 需 reason
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from llm_loop.introspection.task_evidence import (
    TaskEvidenceVerificationError,
    TaskEvidenceVerifier,
)
from llm_loop.timekeeping import system_local_now

logger = logging.getLogger(__name__)

_FALLBACK_LOCK = threading.Lock()
# 进程内跨 goal 协调锁：macOS 上 flock 对同进程多 fd 的自冲突不作保证（实测两条反向边
# 并发创建会双双通过），故环检测临界区必须同时持有进程内锁与跨进程 flock。
_COORD_PROCESS_LOCK = threading.Lock()


def _parse_deadline(raw: str) -> datetime:
    """解析 ISO 期限；naive 时间补本地时区，避免与 tz-aware now 比较抛 TypeError（审查 P1-1）."""
    due = datetime.fromisoformat(raw)
    if due.tzinfo is None:
        due = due.replace(tzinfo=system_local_now().tzinfo)
    return due

TASK_STATUSES = ("pending", "in_progress", "blocked", "done", "failed", "cancelled")
TERMINAL_STATUSES = ("done", "failed", "cancelled")
TASK_LIMIT_PER_GOAL = 40  # §4 防粒度失控
STALLED_AFTER_SECONDS = 30 * 60  # T1: in_progress 空转提示阈值（时间口径，T2 可升级轮计数）
HOT_TASK_LIMIT = 8  # §3.1 注入体积阈值

_EVIDENCE_REF_RE = re.compile(r"^evidence://\S+$")

# 模型可发起的状态转移（合法转移表；ready 派生态不经此表）
ALLOWED_TRANSITIONS = {
    ("pending", "in_progress"),
    ("pending", "cancelled"),
    ("pending", "failed"),
    ("in_progress", "done"),
    ("in_progress", "blocked"),
    ("in_progress", "cancelled"),
    ("in_progress", "failed"),
    ("blocked", "in_progress"),
    ("blocked", "cancelled"),
    ("blocked", "failed"),
    ("done", "in_progress"),  # 重开（触发下游 premise_stale 级联）
    ("done", "failed"),
    ("failed", "in_progress"),  # 失败可重试
}


@dataclass
class Task:
    """执行账本条目（全量行持久化，last-wins 重放取最新）."""

    task_id: str
    goal_id: str
    title: str
    status: str = "pending"
    acceptance: list[str] = field(default_factory=list)
    done_when: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    # DESIGN-20261101 §4.5 (L3): 跨 goal 依赖——所列 goal 全部 complete 后本任务才可能 ready
    blocked_by_goals: list[str] = field(default_factory=list)
    deadline_at: str = ""  # §4.5 等待期限；到期未满足 → blocked(upstream_deadline_exceeded)
    parent_id: str = ""
    evidence_required: bool = False
    evidence_refs: list[str] = field(default_factory=list)
    owner: str = "main"  # T1 main-only 写（T3 subagent typed contract）
    blocked_reason: str = ""
    acceptance_revised: bool = False  # §2.2 防洗白：修订留痕
    premise_stale: bool = False  # §2.1 done 重开级联（提示性，不强制重做）
    evidence_verification_status: str = "not_checked"
    evidence_verified_at: str = ""
    evidence_refs_digest: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Task:
        t = Task(
            task_id=str(d.get("task_id", "")),
            goal_id=str(d.get("goal_id", "")),
            title=str(d.get("title", "")),
        )
        t.status = str(d.get("status", "pending"))
        for k in (
            "acceptance",
            "done_when",
            "dependencies",
            "evidence_refs",
            "blocked_by_goals",
        ):
            v = d.get(k)
            setattr(t, k, [str(x) for x in v] if isinstance(v, list) else [])
        t.deadline_at = str(d.get("deadline_at", "") or "")
        t.parent_id = str(d.get("parent_id", ""))
        t.evidence_required = bool(d.get("evidence_required", False))
        t.owner = str(d.get("owner", "main"))
        t.blocked_reason = str(d.get("blocked_reason", ""))
        t.acceptance_revised = bool(d.get("acceptance_revised", False))
        t.premise_stale = bool(d.get("premise_stale", False))
        t.evidence_verification_status = str(d.get("evidence_verification_status", "not_checked"))
        t.evidence_verified_at = str(d.get("evidence_verified_at", ""))
        t.evidence_refs_digest = str(d.get("evidence_refs_digest", ""))
        t.created_at = str(d.get("created_at", ""))
        t.updated_at = str(d.get("updated_at", ""))
        return t


def _now() -> str:
    return system_local_now().isoformat()


class TaskStore:
    """任务账本存储（JSONL append-only last-wins + flock，对齐 GoalStore 模式）."""

    def __init__(
        self,
        audit_dir: str | Path,
        *,
        evidence_verifier: TaskEvidenceVerifier | None = None,
    ) -> None:
        self._dir = Path(audit_dir)
        self._tasks_dir = self._dir / "tasks"
        self._tasks_dir.mkdir(parents=True, exist_ok=True)
        self._evidence_verifier = evidence_verifier

    # ---------- 写路径 ----------

    def create(
        self,
        goal_id: str,
        title: str,
        *,
        acceptance: list[str] | None = None,
        done_when: list[str] | None = None,
        dependencies: list[str] | None = None,
        blocked_by_goals: list[str] | None = None,
        deadline_at: str = "",
        parent_id: str = "",
        evidence_required: bool = False,
        owner: str = "main",
    ) -> Task:
        title = (title or "").strip()
        if not title:
            raise ValueError("task_create 必填 'title'")
        if not acceptance:
            raise ValueError("task_create 必填 'acceptance'（至少一条验收条件）")
        deps = [d.strip() for d in (dependencies or []) if d.strip()]
        # DESIGN-20261101 §4.5: 跨 goal 依赖归一化（去空/去重保序/禁自指）
        xdeps: list[str] = []
        for raw in blocked_by_goals or []:
            gid_ref = str(raw or "").strip()
            if not gid_ref:
                continue
            if gid_ref == goal_id:
                raise ValueError("dependency_cycle: 跨 goal 依赖不得指向自身 goal")
            if gid_ref not in xdeps:
                xdeps.append(gid_ref)
        deadline = str(deadline_at or "").strip()
        if deadline:
            try:
                deadline = _parse_deadline(deadline).isoformat()
            except ValueError as exc:
                raise ValueError(
                    f"deadline_at 必须是 ISO 时间（如 2026-11-02T12:00:00+08:00）: {deadline}"
                ) from exc
        with self._write_ctx(goal_id, xdeps=xdeps):
            if xdeps:
                # 环检测必须在锁内（P1-4）：两条反向边并发创建时，后写者必须看见先写者
                cycle = self._detect_cross_goal_cycle(goal_id, xdeps)
                if cycle:
                    raise ValueError(
                        "dependency_cycle: 跨 goal 依赖成环 → " + " -> ".join(cycle)
                    )
            tasks = self._replay(goal_id)
            if len(tasks) >= TASK_LIMIT_PER_GOAL:
                raise ValueError(
                    f"任务数已达上限 {TASK_LIMIT_PER_GOAL}（防粒度失控），请合并或拆分 goal"
                )
            for d in deps:
                if d not in tasks:
                    raise ValueError(f"依赖任务不存在: {d}（须为同 goal 内已有 task_id）")
            if parent_id and parent_id not in tasks:
                raise ValueError(f"parent 任务不存在: {parent_id}")
            seq = 1 + max(
                (int(t.task_id.rsplit("-", 1)[-1]) for t in tasks.values() if t.task_id.rsplit("-", 1)[-1].isdigit()),
                default=0,
            )
            now = _now()
            task = Task(
                task_id=f"TASK-{goal_id.rsplit('-', 1)[-1]}-{seq:03d}",
                goal_id=goal_id,
                title=title,
                acceptance=[str(a).strip() for a in acceptance if str(a).strip()],
                done_when=[str(w).strip() for w in (done_when or []) if str(w).strip()],
                dependencies=deps,
                blocked_by_goals=xdeps,
                deadline_at=deadline,
                parent_id=(parent_id or "").strip(),
                evidence_required=bool(evidence_required),
                owner=(owner or "main").strip(),
                created_at=now,
                updated_at=now,
            )
            self._append(goal_id, task)
            return task

    def get(self, goal_id: str, task_id: str) -> Task | None:
        """单任务读取（replay last-wins 语义）."""
        with self._file_lock(goal_id):
            return self._replay(goal_id).get(task_id)

    def update(
        self,
        goal_id: str,
        task_id: str,
        *,
        status: str | None = None,
        blocked_reason: str | None = None,
        evidence_refs: list[str] | None = None,
        acceptance: list[str] | None = None,
        done_when: list[str] | None = None,
        title: str | None = None,
        confirm: bool = False,
    ) -> Task:
        """更新任务。转移合法性/evidence 校验/blocked reason/重开级联在此层强制.

        done→非done 重开保留一个机械显式位 ``confirm``。程序不解析用户措辞，
        也不维护第二套授权 token；是否得到当前用户授权由模型依据 RULE-AI-23 判断。
        """
        with self._file_lock(goal_id):
            tasks = self._replay(goal_id)
            task = tasks.get(task_id)
            if task is None:
                raise ValueError(f"任务不存在: {task_id}（goal {goal_id}）")
            previous_status = task.status
            previous_refs = tuple(task.evidence_refs)
            no_change = all(
                v is None
                for v in (status, blocked_reason, evidence_refs, acceptance, done_when, title)
            )
            if no_change:
                return task  # 无实质变化不落盘（防空行写放大）
            if evidence_refs is not None:
                refs = [str(r).strip() for r in evidence_refs if str(r).strip()]
                bad = [r for r in refs if not _EVIDENCE_REF_RE.match(r)]
                if bad:
                    raise ValueError(f"evidence_refs 格式非法（须 evidence:// 开头）: {bad[:2]}")
                task.evidence_refs = refs
            if acceptance is not None:
                new_acc = [str(a).strip() for a in acceptance if str(a).strip()]
                if not new_acc:
                    raise ValueError("acceptance 不能清空")
                if new_acc != task.acceptance:
                    task.acceptance_revised = True  # §2.2 修订留痕（历史行不可篡改）
                task.acceptance = new_acc
            if done_when is not None:
                task.done_when = [str(w).strip() for w in done_when if str(w).strip()]
            if title is not None:
                t = title.strip()
                if t:
                    task.title = t
            if status is not None and status != task.status:
                if status not in TASK_STATUSES:
                    raise ValueError(f"未知 status: {status}（{TASK_STATUSES}）")
                if (task.status, status) not in ALLOWED_TRANSITIONS:
                    raise ValueError(f"非法转移: {task.status} → {status}")
                if status == "blocked":
                    reason = (blocked_reason or "").strip()
                    if not reason:
                        raise ValueError("→blocked 必须提供 blocked_reason")
                    task.blocked_reason = reason
                if task.status == "done" and status != "done":
                    # Mechanical guard only: reopening a completed task must be an
                    # explicit model action. The runtime does not interpret current
                    # user language into an authorization token.
                    if not confirm:
                        raise ValueError(
                            "已完成的任务禁止自动重启（禁止隐式重启）: done→非done 必须在当前用户明确授权后"
                            "由模型显式传 confirm=true；程序不解析用户措辞代填授权"
                        )
                    self._cascade_premise_stale(goal_id, tasks, task_id)
                task.status = status
            elif blocked_reason is not None and blocked_reason.strip():
                task.blocked_reason = blocked_reason.strip()

            refs_changed = tuple(task.evidence_refs) != previous_refs
            if refs_changed and task.status != "done":
                task.evidence_verification_status = "not_checked"
                task.evidence_verified_at = ""
                task.evidence_refs_digest = ""

            if task.status == "done":
                if task.evidence_required and not task.evidence_refs:
                    raise ValueError(
                        "→done 校验失败: evidence_required=true 但 evidence_refs 为空"
                        "（仅做引用真实性机械校验；证据语义充分性仍归模型判断）"
                    )
                entering_done = previous_status != "done"
                needs_verification = bool(task.evidence_refs) and (entering_done or refs_changed)
                if needs_verification:
                    if self._evidence_verifier is None:
                        raise TaskEvidenceVerificationError(
                            "verification_unavailable",
                            failing_ref=task.evidence_refs[0],
                        )
                    report = self._evidence_verifier.verify(task.evidence_refs)
                    if report.status != "verified":
                        raise TaskEvidenceVerificationError(
                            report.status,
                            failing_ref=report.failing_ref,
                        )
                    task.evidence_verification_status = report.status
                    task.evidence_verified_at = report.checked_at
                    task.evidence_refs_digest = report.refs_digest
                elif refs_changed and not task.evidence_refs:
                    task.evidence_verification_status = "not_checked"
                    task.evidence_verified_at = ""
                    task.evidence_refs_digest = ""
            task.updated_at = _now()
            self._append(goal_id, task)
            return task

    def _cascade_premise_stale(self, goal_id: str, tasks: dict[str, Task], reopened_id: str) -> None:
        """done 重开 → 传递闭包内已 done 下游标 premise_stale（提示性，§2.1）."""
        dependents: dict[str, list[str]] = {}
        for t in tasks.values():
            for d in t.dependencies:
                dependents.setdefault(d, []).append(t.task_id)
        queue: deque[str] = deque(dependents.get(reopened_id, []))
        touched: set[str] = set()
        while queue:
            tid = queue.popleft()
            if tid in touched:
                continue
            touched.add(tid)
            down = tasks.get(tid)
            if down is not None:
                down.premise_stale = True
                down.updated_at = _now()
                self._append(goal_id, down)
                queue.extend(dependents.get(tid, []))

    # ---------- 读路径 ----------

    def _path(self, goal_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", goal_id)
        return self._tasks_dir / f"{safe}.jsonl"

    def _replay(self, goal_id: str) -> dict[str, Task]:
        """last-wins 重放；坏行跳过+告警（§6 crash 容错，诚实降级不阻断）."""
        path = self._path(goal_id)
        tasks: dict[str, Task] = {}
        if not path.exists():
            return tasks
        bad = 0
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    d = json.loads(raw)
                    tid = str(d.get("task_id", ""))
                    if tid:
                        tasks[tid] = Task.from_dict(d)
                except json.JSONDecodeError:
                    bad += 1
        if bad:
            logger.warning("Task 存储含 %d 坏行已跳过（last-wins 取最后有效行）: %s", bad, path)
        return tasks

    def list_for_goal(self, goal_id: str) -> list[Task]:
        return list(self._replay(goal_id).values())

    def count_for_goal(self, goal_id: str) -> int:
        return len(self._replay(goal_id))

    # ---------- 跨 goal 依赖（DESIGN-20261101 §4.5） ----------

    def _goal_status_index(self) -> tuple[dict[str, str], list[str]]:
        """audit 目录内全部 goal 的 {goal_id: status}；读失败 → ({}, degraded 说明)（fail-open）."""
        try:
            from llm_loop.introspection.goal import GoalStore

            goals = GoalStore(str(self._dir)).list(limit=500)
        except Exception as exc:  # noqa: BLE001 — 跨 goal 依赖求值属附加门，读不到不得阻断 frontier
            return {}, [f"goal 账本不可读（跨 goal 依赖按未满足处理）: {exc}"]
        index = {}
        for g in goals:
            gid = str(g.get("id") or "")
            if gid:
                index[gid] = str(g.get("status") or "")
        return index, []

    def _cross_goal_edges(self) -> dict[str, set[str]]:
        """goal 级依赖边: A→B 表示「A 的某任务等 B complete」."""
        edges: dict[str, set[str]] = {}
        try:
            from llm_loop.introspection.goal import GoalStore

            goals = GoalStore(str(self._dir)).list(limit=500)
        except Exception:  # noqa: BLE001 — 读不到其他 goal 账本时按「已知边」判环，不阻断创建
            goals = [{"id": gid} for gid in self._known_goal_dirs()]
        for g in goals:
            gid = str(g.get("id") or "")
            if not gid:
                continue
            try:
                tasks = self._replay(gid)
            except Exception:  # noqa: BLE001 — 单 goal 账本损坏 → 跳过该 goal 的边
                continue
            for t in tasks.values():
                for dep in t.blocked_by_goals:
                    edges.setdefault(gid, set()).add(str(dep))
        return edges

    def _known_goal_dirs(self) -> list[str]:
        """降级路径：从 tasks 目录反推已知 goal 后缀（只用于尽力判环）."""
        out: list[str] = []
        try:
            for path in self._tasks_dir.glob("*.jsonl"):
                suffix = path.stem.rsplit("-", 1)[-1]
                if suffix:
                    out.append(f"GOAL-{suffix}")
        except OSError:
            return []
        return out

    def _detect_cross_goal_cycle(self, goal_id: str, new_deps: list[str]) -> list[str] | None:
        """加入 goal_id→new_deps 这些边后是否成环；成环返回环路径（含首尾同点）."""
        edges = self._cross_goal_edges()
        for dep in new_deps:
            edges.setdefault(goal_id, set()).add(str(dep))
        stack: list[tuple[str, list[str]]] = [(goal_id, [goal_id])]
        seen_paths: set[tuple[str, ...]] = set()
        while stack:
            node, path = stack.pop()
            for nxt in sorted(edges.get(node, ())):
                if nxt == goal_id:
                    return path + [goal_id]
                if nxt in path:
                    continue
                key = tuple(path + [nxt])
                if key in seen_paths:
                    continue
                seen_paths.add(key)
                stack.append((nxt, path + [nxt]))
        return None

    def _evaluate_cross_goal_deps(
        self, task: Task, status_index: dict[str, str], now_dt: datetime | None
    ) -> dict:
        """单个任务的跨 goal 依赖判决: satisfied | waiting | aborted | deadline（只读）."""
        names = [str(g) for g in task.blocked_by_goals]
        if not names:
            return {"state": "satisfied"}
        aborted = [g for g in names if status_index.get(g) in ("blocked", "cancelled")]
        if aborted:
            return {
                "state": "aborted",
                "reason_code": "upstream_goal_aborted",
                "blocked_by": names,
                "detail": ",".join(aborted),
            }
        missing = [g for g in names if g not in status_index]
        satisfied = not missing and all(status_index.get(g) == "complete" for g in names)
        if satisfied:
            return {"state": "satisfied"}
        if task.deadline_at:
            # 期限判定用「传入 now_ts 或真实当前时间」；stalled 语义不动（仍只认显式 now_ts）
            now_used = now_dt if now_dt is not None else system_local_now()
            # 审查 P2-2（2026-11-02）：now_ts 可带可不带时区。naive now 与
            # tz-aware deadline 直接比较抛 TypeError（不是 ValueError），会一路
            # 冒到 frontier/tool 层。这里把它归一到本地时区（与 _parse_deadline
            # 同一口径），并额外兜 TypeError 保持 fail-open。
            if now_used.tzinfo is None:
                now_used = now_used.replace(tzinfo=system_local_now().tzinfo)
            try:
                if now_used >= _parse_deadline(task.deadline_at):
                    return {
                        "state": "deadline",
                        "reason_code": "upstream_deadline_exceeded",
                        "blocked_by": names,
                        "detail": task.deadline_at,
                    }
            except (ValueError, TypeError):
                pass  # fail-open: deadline 格式非法 → 按未到期处理（创建时已校验）
        return {
            "state": "waiting",
            "reason_code": "upstream_goal_not_complete",
            "blocked_by": names,
            "detail": ",".join(missing),
        }

    # ---------- frontier 计算（纯函数区） ----------

    def compute_frontier(self, goal_id: str, *, now_ts: str = "") -> dict:
        """每轮注入用 frontier（§3）。ready=派生态；含环/依赖failed 检测与 stalled 标记."""
        tasks = self._replay(goal_id)
        by_id = tasks
        done_ids = {t.task_id for t in tasks.values() if t.status == "done"}
        now_dt = None
        if now_ts:
            try:
                now_dt = datetime.fromisoformat(now_ts)
            except ValueError:
                now_dt = None
        ready, in_progress, blocked, completed, unreachable = [], [], [], [], []
        waiting_cross: list[dict] = []
        blocked_upstream: list[dict] = []
        xstatus: dict[str, str] = {}
        xdegraded: list[str] = []
        if any(t.blocked_by_goals for t in tasks.values()):
            xstatus, xdegraded = self._goal_status_index()
        # hope 收紧: 依赖含 failed/cancelled → 无希望（迭代至稳定）
        hopeless: set[str] = set()
        changed = True
        while changed:
            changed = False
            for t in tasks.values():
                if t.task_id in hopeless or t.status in ("done",):
                    continue
                if t.status in ("failed", "cancelled"):
                    if t.task_id not in hopeless:
                        hopeless.add(t.task_id)
                        changed = True
                    continue
                if any(
                    by_id[d].task_id in hopeless
                    for d in t.dependencies
                    if d in by_id
                ):
                    hopeless.add(t.task_id)
                    changed = True
        # Kahn 拓扑（hope 存活的 pending 子图）: 环上/环下游 → unreachable
        pending_ids = {
            t.task_id
            for t in tasks.values()
            if t.status == "pending" and t.task_id not in hopeless
        }
        indeg: dict[str, int] = {}
        dependents: dict[str, list[str]] = {}
        for tid in pending_ids:
            deps = [d for d in by_id[tid].dependencies if d in pending_ids]
            indeg[tid] = len(deps)
            for d in deps:
                dependents.setdefault(d, []).append(tid)
        q: deque[str] = deque(tid for tid, n in indeg.items() if n == 0)
        topo_seen: set[str] = set(q)
        while q:
            u = q.popleft()
            for v in dependents.get(u, []):
                indeg[v] -= 1
                if indeg[v] == 0 and v not in topo_seen:
                    topo_seen.add(v)
                    q.append(v)
        for t in tasks.values():
            tid = t.task_id
            if t.status == "done":
                completed.append(t)
            elif t.status == "in_progress":
                entry = {"task": t, "stalled": False}
                if now_dt and t.updated_at:
                    try:
                        age = (now_dt - datetime.fromisoformat(t.updated_at)).total_seconds()
                        entry["stalled"] = age > STALLED_AFTER_SECONDS
                    except ValueError:
                        # fail-open: updated_at 非法格式时不标 stalled（视为未知，
                        # 交由模型经 frontier 自行判断），不阻断 frontier 构建
                        pass
                in_progress.append(entry)
            elif t.status == "blocked":
                blocked.append(t)
            elif t.status == "pending":
                if tid in hopeless or (tid in pending_ids and tid not in topo_seen):
                    unreachable.append(t)
                else:
                    verdict = (
                        self._evaluate_cross_goal_deps(t, xstatus, now_dt)
                        if t.blocked_by_goals
                        else {"state": "satisfied"}
                    )
                    if verdict["state"] in ("aborted", "deadline"):
                        # §4.5: 上游 goal 已中止/等待超期 → 计入 blocked 桶（不自动 failed）
                        blocked.append(t)
                        blocked_upstream.append(
                            {
                                "task": t,
                                "reason_code": verdict["reason_code"],
                                "blocked_by": verdict["blocked_by"],
                                "detail": verdict.get("detail", ""),
                            }
                        )
                    elif verdict["state"] == "waiting":
                        waiting_cross.append(
                            {
                                "task": t,
                                "blocked_by": verdict["blocked_by"],
                                "detail": verdict.get("detail", ""),
                            }
                        )
                    elif all(d in done_ids for d in t.dependencies):
                        ready.append(t)
        return {
            "ready": ready,
            "in_progress": in_progress,  # [{task, stalled}]
            "blocked": blocked,
            "completed": completed,
            "unreachable": unreachable,
            "premise_stale": [t for t in tasks.values() if t.premise_stale and t.status == "done"],
            "waiting_cross_goal": waiting_cross,
            "blocked_upstream": blocked_upstream,
            "cross_goal_degraded": xdegraded,
            "open_count": sum(
                1
                for t in tasks.values()
                if t.status in ("pending", "in_progress", "blocked")
            ),
            "total": len(tasks),
        }

    def goal_completion_ready(self, goal_id: str) -> tuple[bool, str]:
        """goal→complete 前置校验（§2.1）: 无 open 任务（blocked 可 waive 由上层提示）."""
        fr = self.compute_frontier(goal_id)
        if fr["open_count"] == 0:
            return True, ""
        detail = (
            f"ready={len(fr['ready'])} in_progress={len(fr['in_progress'])} "
            f"blocked={len(fr['blocked'])} unreachable={len(fr['unreachable'])}"
        )
        return False, detail

    # ---------- 渲染 ----------

    def render_frontier(self, goal_id: str, *, now_ts: str = "", compact: bool = False) -> str:
        """Decision Packet 注入文本（§3.1: HOT≤8 全量，超出 WARM 单行摘要）."""
        fr = self.compute_frontier(goal_id, now_ts=now_ts)
        lines: list[str] = []
        lines.append(
            f"[Task Frontier] open={fr['open_count']}/{fr['total']} "
            f"ready={len(fr['ready'])} done={len(fr['completed'])}"
        )
        hot_used = 0
        for t in fr["ready"]:
            if compact or hot_used >= HOT_TASK_LIMIT:
                lines.append(f"  ready(+{len(fr['ready']) - hot_used} 更多, 用 task_frontier() 查看全图)")
                break
            lines.append(f"  ▶ ready {t.task_id} {t.title[:60]}")
            hot_used += 1
        for entry in fr["in_progress"]:
            t = entry["task"]
            tag = " stalled=true" if entry["stalled"] else ""
            if hot_used < HOT_TASK_LIMIT:
                lines.append(f"  ◉ doing {t.task_id} {t.title[:60]}{tag}")
                hot_used += 1
            else:
                lines.append(f"  ◉ doing(+更多省略) {t.task_id}{tag}")
                break
        xmap = {e["task"].task_id: e for e in fr.get("blocked_upstream", [])}
        for t in fr["blocked"]:
            if hot_used < HOT_TASK_LIMIT:
                if t.task_id in xmap:
                    e = xmap[t.task_id]
                    lines.append(
                        f"  ⛔ blocked {t.task_id} {t.title[:40]} | "
                        f"reason_code={e['reason_code']} xgoal={','.join(e['blocked_by'])}"
                    )
                else:
                    lines.append(f"  ⛔ blocked {t.task_id} {t.title[:40]} | {t.blocked_reason[:50]}")
                hot_used += 1
        for e in fr.get("waiting_cross_goal", []):
            t = e["task"]
            lines.append(
                f"  … waiting_xgoal {t.task_id} {t.title[:40]} | 等 {','.join(e['blocked_by'])}"
            )
        for note in fr.get("cross_goal_degraded", []):
            lines.append(f"  ⚠ cross_goal_degraded {note[:80]}")
        if fr["unreachable"]:
            ids = ", ".join(t.task_id for t in fr["unreachable"][:5])
            lines.append(f"  ⚠ unreachable-pending {ids} | reason=dependency_cycle_or_failed_dependency")
        for t in fr["premise_stale"]:
            lines.append(f"  ◇ premise_stale {t.task_id} {t.title[:40]}")
        return "\n".join(lines)

    def summary_line(self, goal_id: str) -> str:
        """get_goal 回执扩展用单行摘要（跨会话恢复，§3.1）."""
        try:
            fr = self.compute_frontier(goal_id)
        except Exception:  # noqa: BLE001 — fail-open: 摘要失败不阻断 goal 读取
            return ""
        if fr["total"] == 0:
            return ""
        parts = [f"tasks: {fr['open_count']} open / {fr['total']}"]
        if fr["ready"]:
            parts.append(f"ready={len(fr['ready'])}")
        if fr["blocked"]:
            parts.append(f"blocked={len(fr['blocked'])}")
        if fr["unreachable"]:
            parts.append(f"⚠unreachable={len(fr['unreachable'])}")
        if fr.get("waiting_cross_goal"):
            parts.append(f"xwait={len(fr['waiting_cross_goal'])}")
        if fr.get("blocked_upstream"):
            parts.append(f"⛔xgoal={len(fr['blocked_upstream'])}")
        return " | ".join(parts)

    # ---------- 内部 ----------

    def _append(self, goal_id: str, task: Task) -> None:
        path = self._path(goal_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(task.to_dict(), ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    @contextmanager
    def _file_lock(self, goal_id: str) -> Iterator[None]:
        path = self._path(goal_id)
        with self._lock(path.with_suffix(path.suffix + ".lock")):
            yield

    @contextmanager
    def _write_ctx(self, goal_id: str, *, xdeps: list[str]) -> Iterator[None]:
        """写事务：涉及跨 goal 依赖时先取全局协调锁再取本 goal 锁（固定顺序防死锁）."""
        if xdeps:
            with self._coord_lock(), self._file_lock(goal_id):
                yield
            return
        with self._file_lock(goal_id):
            yield

    @contextmanager
    def _coord_lock(self) -> Iterator[None]:
        """跨 goal 依赖图互斥：环检测与写入必须同一临界区，否则反向边并发可双双通过.

        两把锁缺一不可：flock 挡跨进程，进程内 threading 锁挡同进程多线程
        （macOS 实测 flock 对同进程多 fd 的自冲突不保证）。
        """
        with _COORD_PROCESS_LOCK, self._lock(self._tasks_dir / ".cross_goal.lock"):
            yield

    @contextmanager
    def _lock(self, lock_path: Path) -> Iterator[None]:
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
            logger.warning("Task 存储锁不可用（fail-open）: %s: %s", lock_path, exc)
            yield
            return
        try:
            yield
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                logger.warning("Task 存储解锁失败: %s", lock_path, exc_info=True)
            finally:
                lock_file.close()

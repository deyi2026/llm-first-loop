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
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Iterator

logger = logging.getLogger(__name__)

_FALLBACK_LOCK = threading.Lock()

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
    parent_id: str = ""
    evidence_required: bool = False
    evidence_refs: list[str] = field(default_factory=list)
    owner: str = "main"  # T1 main-only 写（T3 subagent typed contract）
    blocked_reason: str = ""
    acceptance_revised: bool = False  # §2.2 防洗白：修订留痕
    premise_stale: bool = False  # §2.1 done 重开级联（提示性，不强制重做）
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Task":
        t = Task(
            task_id=str(d.get("task_id", "")),
            goal_id=str(d.get("goal_id", "")),
            title=str(d.get("title", "")),
        )
        t.status = str(d.get("status", "pending"))
        for k in ("acceptance", "done_when", "dependencies", "evidence_refs"):
            v = d.get(k)
            setattr(t, k, [str(x) for x in v] if isinstance(v, list) else [])
        t.parent_id = str(d.get("parent_id", ""))
        t.evidence_required = bool(d.get("evidence_required", False))
        t.owner = str(d.get("owner", "main"))
        t.blocked_reason = str(d.get("blocked_reason", ""))
        t.acceptance_revised = bool(d.get("acceptance_revised", False))
        t.premise_stale = bool(d.get("premise_stale", False))
        t.created_at = str(d.get("created_at", ""))
        t.updated_at = str(d.get("updated_at", ""))
        return t


def _now() -> str:
    return datetime.now(UTC).isoformat()


class TaskStore:
    """任务账本存储（JSONL append-only last-wins + flock，对齐 GoalStore 模式）."""

    def __init__(self, audit_dir: str | Path) -> None:
        self._dir = Path(audit_dir)
        self._tasks_dir = self._dir / "tasks"
        self._tasks_dir.mkdir(parents=True, exist_ok=True)

    # ---------- 写路径 ----------

    def create(
        self,
        goal_id: str,
        title: str,
        *,
        acceptance: list[str] | None = None,
        done_when: list[str] | None = None,
        dependencies: list[str] | None = None,
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
        with self._file_lock(goal_id):
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
    ) -> Task:
        """更新任务。转移合法性/evidence 校验/blocked reason/重开级联在此层强制."""
        with self._file_lock(goal_id):
            tasks = self._replay(goal_id)
            task = tasks.get(task_id)
            if task is None:
                raise ValueError(f"任务不存在: {task_id}（goal {goal_id}）")
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
                if status == "done" and task.evidence_required and not task.evidence_refs:
                    raise ValueError(
                        "→done 校验失败: evidence_required=true 但 evidence_refs 为空"
                        "（格式/存在性分层校验，语义判定归模型+validator，见设计 §2.2）"
                    )
                if task.status == "done" and status != "done":
                    self._cascade_premise_stale(goal_id, tasks, task_id)
                task.status = status
            elif blocked_reason is not None and blocked_reason.strip():
                task.blocked_reason = blocked_reason.strip()
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
                        pass
                in_progress.append(entry)
            elif t.status == "blocked":
                blocked.append(t)
            elif t.status == "pending":
                if tid in hopeless or (tid in pending_ids and tid not in topo_seen):
                    unreachable.append(t)
                elif all(d in done_ids for d in t.dependencies):
                    ready.append(t)
        return {
            "ready": ready,
            "in_progress": in_progress,  # [{task, stalled}]
            "blocked": blocked,
            "completed": completed,
            "unreachable": unreachable,
            "premise_stale": [t for t in tasks.values() if t.premise_stale and t.status == "done"],
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
            tag = " ⚠stalled(空转提示,重新评估/继续/放弃)" if entry["stalled"] else ""
            if hot_used < HOT_TASK_LIMIT:
                lines.append(f"  ◉ doing {t.task_id} {t.title[:60]}{tag}")
                hot_used += 1
            else:
                lines.append(f"  ◉ doing(+更多省略) {t.task_id}{tag}")
                break
        for t in fr["blocked"]:
            if hot_used < HOT_TASK_LIMIT:
                lines.append(f"  ⛔ blocked {t.task_id} {t.title[:40]} | {t.blocked_reason[:50]}")
                hot_used += 1
        if fr["unreachable"]:
            ids = ", ".join(t.task_id for t in fr["unreachable"][:5])
            lines.append(f"  ⚠ unreachable-pending（依赖环或依赖已失败）: {ids} — 需解环/取消/拆分")
        for t in fr["premise_stale"]:
            lines.append(f"  ◇ premise_stale {t.task_id} {t.title[:40]}（前置已重开，结论请复核）")
        lines.append("  程序记账/模型决策: 领取用 task_update→in_progress, 完成须 evidence_refs（evidence_required 时）")
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
        lock_path = path.with_suffix(path.suffix + ".lock")
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

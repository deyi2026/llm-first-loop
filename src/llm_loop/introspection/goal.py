"""任务级 Goal 状态机 + checkpoint 四要素（EVO-20260824-3cd4d74b，MCP Console Goal workflow 借鉴）.

设计约束（评估产出，有界推进改造）:
- 状态机: active → complete/blocked（blocked 仅严格条件：外部阻塞/安全边界/等人工）
- checkpoint 四要素: What（变化）/ Evidence（权威证据）/ Path（影响路径或外部状态）/ Next（确切下一步）
- 有界推进: 不引入"永不结束"语义；里程碑 checkpoint + 简报，遇成本/方向/安全边界即暂停等确认
- 单一数据源: 落盘 audit_dir/goals.jsonl + event_logs 事件（goal.created/checkpoint/updated）；
  不另起第二套持久化（LFL 已有 event_logs 每轮自动 append-only）
- 恢复: get_goal 返回最近 checkpoints 作 handoff 上下文；恢复时先验证 worktree/外部状态再依赖
"""

from __future__ import annotations

import json
import threading
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

import logging

logger = logging.getLogger(__name__)

_FALLBACK_LOCK = threading.Lock()

GOAL_STATUSES = ("active", "complete", "blocked")
CHECKPOINT_FIELDS = ("what", "evidence", "path", "next")


@dataclass
class Goal:
    """任务级目标记录（有界推进 + checkpoint 四要素）."""

    id: str
    objective: str
    status: str = "active"  # active|complete|blocked
    created_at: str = ""
    updated_at: str = ""
    session_id: str = ""
    checkpoints: list[dict] = field(default_factory=list)  # [{ts, what, evidence, path, next}]
    completed_at: str = ""
    blocked_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class GoalStore:
    """任务级 Goal 存储（JSONL + flock，对齐 EvolutionStore 模式）."""

    def __init__(self, audit_dir: str | Path) -> None:
        self._dir = Path(audit_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "goals.jsonl"

    def create(self, objective: str, session_id: str = "") -> Goal:
        """创建任务目标（active 初始态）."""
        now = datetime.now(UTC).isoformat()
        goal = Goal(
            id=f"GOAL-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}",
            objective=objective,
            status="active",
            created_at=now,
            updated_at=now,
            session_id=session_id,
        )
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(goal.to_dict(), ensure_ascii=False) + "\n")
        return goal

    def checkpoint(
        self,
        goal_id: str,
        *,
        what: str,
        evidence: str = "",
        path: str = "",
        next_step: str = "",
    ) -> dict | None:
        """里程碑 checkpoint（四要素: What/Evidence/Path/Next）.

        仅 active 目标可 checkpoint；complete/blocked 返回 None（如实不写入）。
        返回更新后的 goal dict（含新 checkpoint），无此 goal 返回 None。
        """
        if not what:
            raise ValueError("checkpoint 必填 'what'（本里程碑变化）")
        with self._file_lock():
            lines = self._path.read_text(encoding="utf-8").splitlines()
            out: list[str] = []
            target: dict | None = None
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    out.append(line)
                    continue
                if entry.get("id") == goal_id:
                    if entry.get("status") != "active":
                        out.append(json.dumps(entry, ensure_ascii=False))
                        target = entry  # 非 active：返回现状不追加（如实）
                        continue
                    cp = {
                        "ts": datetime.now(UTC).isoformat(),
                        "what": what,
                        "evidence": evidence,
                        "path": path,
                        "next": next_step,
                    }
                    entry.setdefault("checkpoints", []).append(cp)
                    entry["updated_at"] = datetime.now(UTC).isoformat()
                    target = entry
                out.append(json.dumps(entry, ensure_ascii=False))
            if target is not None:
                self._path.write_text("\n".join(out) + "\n", encoding="utf-8")
            return target

    def update(self, goal_id: str, status: str, reason: str = "") -> dict | None:
        """状态流转: complete（完成）/ blocked（仅严格条件: 外部阻塞/安全边界/等人工）."""
        if status not in GOAL_STATUSES:
            raise ValueError(f"status 必须为 {GOAL_STATUSES}，收到 {status}")
        with self._file_lock():
            lines = self._path.read_text(encoding="utf-8").splitlines()
            out: list[str] = []
            target: dict | None = None
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    out.append(line)
                    continue
                if entry.get("id") == goal_id:
                    entry["status"] = status
                    entry["updated_at"] = datetime.now(UTC).isoformat()
                    if status == "complete":
                        entry["completed_at"] = datetime.now(UTC).isoformat()
                    if status == "blocked" and reason:
                        entry["blocked_reason"] = reason
                    target = entry
                out.append(json.dumps(entry, ensure_ascii=False))
            if target is not None:
                self._path.write_text("\n".join(out) + "\n", encoding="utf-8")
            return target

    def get(self, goal_id: str | None = None) -> dict | None:
        """获取目标: 指定 id 或最近 active（无 active 取最近一条）."""
        if not self._path.exists():
            return None
        active: dict | None = None
        latest: dict | None = None
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                latest = entry
                if goal_id is not None and entry.get("id") == goal_id:
                    return entry
                if entry.get("status") == "active":
                    active = entry
        return active if active is not None else latest

    def list(self, status: str | None = None, limit: int = 20) -> list[dict]:
        """列出目标（可按状态过滤，最近优先）."""
        if not self._path.exists():
            return []
        out: list[dict] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if status and entry.get("status") != status:
                    continue
                out.append(entry)
        return out[-limit:][::-1]

    @contextmanager
    def _file_lock(self) -> Iterator[None]:
        """goals.jsonl 跨进程写锁（flock；非 POSIX 回退进程内锁，对齐 EvolutionStore）."""
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        try:
            import fcntl
        except ImportError:
            with _FALLBACK_LOCK:
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
            logger.warning("Goal 存储锁不可用（fail-open，并发保护降级）: %s: %s", lock_path, exc)
            yield


def _now() -> str:
    return datetime.now(UTC).isoformat()

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
import logging
import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_FALLBACK_LOCK = threading.Lock()

GOAL_STATUSES = ("active", "complete", "blocked")
CHECKPOINT_FIELDS = ("what", "evidence", "path", "next")


class GoalStoreCorruptionError(RuntimeError):
    """Goal JSONL 存在损坏记录，当前查询无法安全判定。"""


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
        """创建任务目标（active 初始态；与checkpoint/update共享同一写锁）."""
        now = datetime.now(UTC).isoformat()
        goal = Goal(
            id=f"GOAL-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}",
            objective=objective,
            status="active",
            created_at=now,
            updated_at=now,
            session_id=session_id,
        )
        with self._file_lock():
            lines = self._read_lines()
            lines.append(json.dumps(goal.to_dict(), ensure_ascii=False))
            self._atomic_rewrite(lines)
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
            lines = self._read_lines()
            out: list[str] = []
            target: dict | None = None
            matched = False
            malformed_lines: list[int] = []
            for line_no, line in enumerate(lines, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    malformed_lines.append(line_no)
                    out.append(raw)
                    continue
                if entry.get("id") == goal_id:
                    matched = True
                    if entry.get("status") != "active":
                        out.append(json.dumps(entry, ensure_ascii=False))
                        continue  # 非active明确拒绝：返回None，工具层不得误报已记录
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
            if not matched and malformed_lines:
                raise self._corruption_error(malformed_lines, "checkpoint 目标未命中")
            if target is not None:
                self._atomic_rewrite(out)
            return target

    def update(self, goal_id: str, status: str, reason: str = "") -> dict | None:
        """状态流转仅允许 active→complete/blocked；terminal 同状态幂等、跨终态拒绝。"""
        if status not in {"complete", "blocked"}:
            raise ValueError("status 仅允许 complete / blocked")
        reason = reason.strip()
        if status == "blocked" and not reason:
            raise ValueError("blocked 必须提供非空 reason（严格阻塞证据）")
        with self._file_lock():
            lines = self._read_lines()
            out: list[str] = []
            target: dict | None = None
            changed = False
            matched = False
            malformed_lines: list[int] = []
            for line_no, line in enumerate(lines, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    malformed_lines.append(line_no)
                    out.append(raw)
                    continue
                if entry.get("id") == goal_id:
                    matched = True
                    current = str(entry.get("status", "active"))
                    if current != "active":
                        if current == status:
                            target = entry  # 幂等重复提交同一终态，不重写时间戳/理由
                            out.append(json.dumps(entry, ensure_ascii=False))
                            continue
                        raise ValueError(f"Goal 终态不可逆: {current} → {status}")
                    now = datetime.now(UTC).isoformat()
                    entry["status"] = status
                    entry["updated_at"] = now
                    if status == "complete":
                        entry["completed_at"] = now
                    else:
                        entry["blocked_reason"] = reason
                    target = entry
                    changed = True
                out.append(json.dumps(entry, ensure_ascii=False))
            if not matched and malformed_lines:
                raise self._corruption_error(malformed_lines, "update 目标未命中")
            if changed:
                self._atomic_rewrite(out)
            return target

    def get(
        self,
        goal_id: str | None = None,
        *,
        prefer_session_id: str = "",
        strict_session: bool = False,
    ) -> dict | None:
        """获取目标：显式id精确匹配；否则当前session active优先，再回退全局active/latest。

        strict_session=True（CR-R1.1）：只返回 session_id 严格匹配 prefer_session_id
        的候选（preferred active → preferred latest），禁止跨会话全局回退——供
        Cognitive Runtime 等会话隔离读取方使用；恢复性读取（CLI 展示等）保持默认。

        JSONL 若有损坏记录，禁止把较旧可解析 Goal 猜成当前目标：
        - 显式 id 已解析命中：直接返回（已知事实可用）；
        - 显式 id 未命中但存在损坏行：无法证明“不存在”，fail-closed；
        - 隐式恢复：只有当所选候选比所有损坏行都更新时才可返回。
        """
        if not self._path.exists():
            return None
        active: tuple[int, dict] | None = None
        active_preferred: tuple[int, dict] | None = None
        latest: tuple[int, dict] | None = None
        latest_preferred: tuple[int, dict] | None = None
        malformed_lines: list[int] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    malformed_lines.append(line_no)
                    continue
                item = (line_no, entry)
                latest = item
                if prefer_session_id and entry.get("session_id") == prefer_session_id:
                    latest_preferred = item
                if goal_id is not None and entry.get("id") == goal_id:
                    return entry
                if entry.get("status") == "active":
                    active = item
                    if prefer_session_id and entry.get("session_id") == prefer_session_id:
                        active_preferred = item
        if goal_id is not None:
            if malformed_lines:
                raise self._corruption_error(malformed_lines, "显式 goal_id 未命中")
            return None
        if strict_session and prefer_session_id:
            # CR-R1.1: 严格会话读——禁止跨会话回退（全局 active/latest 均不可见）
            selected = active_preferred or latest_preferred
        else:
            selected = active_preferred or active or latest_preferred or latest
        if selected is None:
            if malformed_lines:
                raise self._corruption_error(malformed_lines, "无可解析 Goal")
            return None
        selected_line, entry = selected
        newer_malformed = [n for n in malformed_lines if n > selected_line]
        if newer_malformed:
            raise self._corruption_error(newer_malformed, "候选之后存在更新的损坏记录")
        if malformed_lines:
            logger.warning(
                "Goal 存储含较旧损坏行但已有更新的有效 Goal，可安全恢复: %s lines=%s",
                self._path,
                malformed_lines,
            )
        return entry

    def _corruption_error(self, lines: list[int], reason: str) -> GoalStoreCorruptionError:
        shown = ",".join(str(n) for n in lines[:8])
        suffix = "..." if len(lines) > 8 else ""
        return GoalStoreCorruptionError(
            f"Goal 存储损坏: {self._path} 存在不可解析 JSONL 行 {shown}{suffix}（{reason}）"
        )

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

    def _read_lines(self) -> list[str]:
        if not self._path.exists():
            return []
        return self._path.read_text(encoding="utf-8").splitlines()

    def _atomic_rewrite(self, lines: list[str]) -> None:
        """原子提交完整goals快照；锁外reader只会看到旧版或新版，不见truncate半态。"""
        tmp = self._dir / f".{self._path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        try:
            with tmp.open("w", encoding="utf-8") as f:
                if lines:
                    f.write("\n".join(lines) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
            dir_fd: int | None = None
            try:
                flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                dir_fd = os.open(self._dir, flags)
                os.fsync(dir_fd)
            except OSError:
                # rename 已成功；目录fsync只补崩溃/掉电耐久性，平台不支持时不伪装主写失败。
                logger.warning("Goal 目录 fsync 失败（写入已完成，耐久性降级）: %s", self._dir, exc_info=True)
            finally:
                if dir_fd is not None:
                    os.close(dir_fd)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                logger.debug("Goal 临时文件清理失败: %s", tmp, exc_info=True)

    @contextmanager
    def _file_lock(self) -> Iterator[None]:
        """goals.jsonl 跨进程写锁；仅锁获取失败时fail-open，业务I/O异常原样传播。"""
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
            logger.warning("Goal 存储锁不可用（fail-open，并发保护降级）: %s: %s", lock_path, exc)
            yield
            return

        try:
            yield
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                logger.warning("Goal 存储解锁失败: %s", lock_path, exc_info=True)
            finally:
                lock_file.close()


def _now() -> str:
    return datetime.now(UTC).isoformat()

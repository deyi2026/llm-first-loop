"""Peer 通道磁盘权威存储。

单一真值在磁盘：``data/peer/{nodes,grants,tasks}.json`` + ``admissions/`` + ``secrets/``。
并发模型与 ``fleet/store.py`` 同构：进程级 ``flock`` 串行化 + 临时文件 ``os.replace`` 原子替换
+ 每次写递增 ``generation``（读取方可用它做 CAS/对账）。

fail-closed：文件不可解析或结构异常一律抛 ``PeerError("executor_internal_error")``，
绝不静默回退成空集合（那会把"状态丢失"伪装成"没有授权"，是双重风险）。
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from llm_loop.peer.errors import PeerError
from llm_loop.peer.models import (
    GRANT_STATES,
    NODE_STATES,
    SLOT_STATES,
    GrantRecord,
    NodeRecord,
    TaskRecord,
    iso,
    now_local,
)
from llm_loop.peer.state import TERMINAL_STATES, can_quarantine, require_transition

_LOCK_NAME = ".peer.lock"
_DOC_NAMES = ("nodes", "grants", "tasks")


def _now_iso() -> str:
    return iso(now_local())


class PeerStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "admissions").mkdir(exist_ok=True)
        (self.root / "secrets").mkdir(exist_ok=True)
        os.chmod(self.root / "secrets", 0o700)
        self._docs = {name: self.root / f"{name}.json" for name in _DOC_NAMES}
        with self._lock(exclusive=True):
            for _name, path in self._docs.items():
                if not path.exists():
                    self._write_json(path, {"schema": "lfl.peer.v1", "generation": 0, "items": []})

    # ---- 基础设施 ----

    @contextmanager
    def _lock(self, *, exclusive: bool) -> Iterator[None]:
        fd = os.open(self.root / _LOCK_NAME, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @contextmanager
    def operation_lock(self, key: str) -> Iterator[bool]:
        """Nonblocking ownership shared by CLI, recovery and all service instances.

        Lock files are never unlinked: replacing an inode would split ownership.
        This holds no PeerStore document lock while execution performs file I/O.
        """
        directory = self.root / "operation-locks"
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
        name = hashlib.sha256(key.encode("utf-8")).hexdigest() + ".lock"
        fd = os.open(directory / name, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        acquired = False
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                pass
            yield acquired
        finally:
            if acquired:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _read(self, name: str) -> dict[str, Any]:
        path = self._docs[name]
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PeerError("executor_internal_error", f"{name}.json 不可读: {exc}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
            raise PeerError("executor_internal_error", f"{name}.json 结构损坏")
        raw.setdefault("generation", 0)
        return raw

    def _write(self, name: str, payload: dict[str, Any]) -> int:
        payload["generation"] = int(payload.get("generation", 0)) + 1
        self._write_json(self._docs[name], payload)
        return int(payload["generation"])

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, path)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    def generation(self, name: str) -> int:
        if name not in self._docs:
            raise ValueError(f"unknown peer doc: {name}")
        with self._lock(exclusive=False):
            return int(self._read(name)["generation"])

    # ---- 节点 ----

    def list_nodes(self) -> list[NodeRecord]:
        with self._lock(exclusive=False):
            items = self._read("nodes")["items"]
        return [NodeRecord.from_dict(item) for item in items]

    def get_node(self, node_id: str) -> NodeRecord | None:
        for node in self.list_nodes():
            if node.node_id == node_id:
                return node
        return None

    def node_state(self, node_id: str) -> str | None:
        node = self.get_node(node_id)
        return node.state if node else None

    def upsert_node(self, node: NodeRecord) -> int:
        if node.state not in NODE_STATES:
            raise ValueError(f"非法节点状态: {node.state}")
        with self._lock(exclusive=True):
            payload = self._read("nodes")
            items = [item for item in payload["items"] if item.get("node_id") != node.node_id]
            items.append(node.to_dict())
            payload["items"] = sorted(items, key=lambda item: item["node_id"])
            return self._write("nodes", payload)

    def set_node_state(self, node_id: str, state: str) -> int:
        if state not in NODE_STATES:
            raise ValueError(f"非法节点状态: {state}")
        node = self.get_node(node_id)
        if node is None:
            raise PeerError("peer_unknown_node", node_id)
        return self.upsert_node(_replace_node(node, state=state))

    def touch_node(self, node_id: str, *, when: str) -> None:
        node = self.get_node(node_id)
        if node is None:
            raise PeerError("peer_unknown_node", node_id)
        self.upsert_node(_replace_node(node, last_seen_at=when))

    # ---- 共享密钥（0600，单独目录）----

    def _secret_path(self, node_id: str) -> Path:
        return self.root / "secrets" / f"{_safe_name(node_id)}.key"

    def read_secret(self, node_id: str) -> str | None:
        path = self._secret_path(node_id)
        try:
            return path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise PeerError("executor_internal_error", f"secret 不可读: {exc}") from exc

    def write_secret(self, node_id: str, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("共享密钥至少 32 字符")
        path = self._secret_path(node_id)
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        try:
            os.write(fd, secret.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(path, 0o600)

    # ---- 授权（grant）----

    def list_grants(self, node_id: str | None = None) -> list[GrantRecord]:
        with self._lock(exclusive=False):
            items = self._read("grants")["items"]
        grants = [GrantRecord.from_dict(item) for item in items]
        if node_id is not None:
            grants = [grant for grant in grants if grant.node_id == node_id]
        return grants

    def get_grant(self, grant_id: str) -> GrantRecord | None:
        for grant in self.list_grants():
            if grant.grant_id == grant_id:
                return grant
        return None

    def issue_grant(self, grant: GrantRecord) -> GrantRecord:
        if grant.state not in GRANT_STATES:
            raise ValueError(f"非法 grant 状态: {grant.state}")
        with self._lock(exclusive=True):
            payload = self._read("grants")
            if any(item.get("grant_id") == grant.grant_id for item in payload["items"]):
                raise PeerError("idempotency_conflict", f"grant 已存在: {grant.grant_id}")
            payload["items"].append(grant.to_dict())
            payload["items"].sort(key=lambda item: item["grant_id"])
            self._write("grants", payload)
        return grant

    def revoke_grant(self, grant_id: str, *, by: str) -> GrantRecord:
        with self._lock(exclusive=True):
            payload = self._read("grants")
            for index, item in enumerate(payload["items"]):
                if item.get("grant_id") == grant_id:
                    revoked = GrantRecord.from_dict(item).revoked(by=by, at=_now_iso())
                    payload["items"][index] = revoked.to_dict()
                    self._write("grants", payload)
                    return revoked
        raise PeerError("grant_not_found", grant_id)

    def consume_grant(self, grant_id: str, *, expected_tasks_used: int) -> GrantRecord:
        with self._lock(exclusive=True):
            payload = self._read("grants")
            for index, item in enumerate(payload["items"]):
                if item.get("grant_id") != grant_id:
                    continue
                grant = GrantRecord.from_dict(item)
                if grant.state == "revoked" or grant.revoked_at:
                    raise PeerError("grant_revoked", grant_id)
                if grant.tasks_used != expected_tasks_used:
                    raise PeerError("idempotency_conflict", f"grant {grant_id} CAS 失败")
                if grant.tasks_used >= grant.max_tasks_total:
                    raise PeerError("grant_exhausted", grant_id)
                updated = grant.with_tasks_used(grant.tasks_used + 1)
                payload["items"][index] = updated.to_dict()
                self._write("grants", payload)
                return updated
        raise PeerError("grant_not_found", grant_id)

    # ---- 任务 ----

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._lock(exclusive=False):
            items = self._read("tasks")["items"]
        for item in items:
            if item.get("task_id") == task_id:
                return TaskRecord.from_dict(item)
        return None

    # ---- effect 幂等占坑（D6：dedup 先于副作用持久化）------------------------

    def _effect_path(self, node_id: str, effect_id: str) -> Path:
        name = f"{_safe_name(node_id)}__{_safe_name(effect_id)}.json"
        return self.root / "effects" / name

    def claim_effect(
        self, node_id: str, effect_id: str, task_id: str, *, now_iso: str = ""
    ) -> str | None:
        """O_EXCL 原子占坑；成功返回 None，已被占返回占坑记录里的 task_id。

        独立审查 P1-2：``find_task_by_effect``（扫描）→ ``put_task`` 是
        check-then-act——并发同 effect_id 双提交会双双通过扫描并双双执行。
        内核级 O_CREAT|O_EXCL 是免锁原子占坑：占坑成功才允许落任务与副作用；
        后来者读占坑记录返回既有 task_id（幂等回执）。
        """
        effects_dir = self.root / "effects"
        effects_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self._effect_path(node_id, effect_id)
        record = {
            "schema": "lfl.peer.v1",
            "node_id": node_id,
            "effect_id": effect_id,
            "task_id": task_id,
            "claimed_at": now_iso,
        }
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            # 占坑者先建后写：极短窗口内可能读到空/半文件，短暂重读。
            for _ in range(50):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return str(data.get("task_id") or "")
                except (OSError, ValueError):
                    time.sleep(0.02)
            return ""  # 读不到按已占用处理（fail-closed），调用方走冲突路径
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        return None

    def release_effect(self, node_id: str, effect_id: str) -> None:
        """回滚占坑：任务落盘失败（如磁盘满）时删除，允许同 effect_id 重试。"""
        with suppress(OSError):
            self._effect_path(node_id, effect_id).unlink(missing_ok=True)

    def find_task_by_effect(self, node_id: str, effect_id: str) -> TaskRecord | None:
        for task in self.list_tasks(node_id=node_id, limit=10_000):
            if task.effect_id == effect_id:
                return task
        return None

    def list_tasks(
        self,
        *,
        node_id: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        with self._lock(exclusive=False):
            items = list(self._read("tasks")["items"])
        tasks = [TaskRecord.from_dict(item) for item in items]
        if node_id is not None:
            tasks = [task for task in tasks if task.node_id == node_id]
        if state is not None:
            tasks = [task for task in tasks if task.state == state]
        tasks.sort(key=lambda task: task.created_at, reverse=True)
        return tasks[:limit]

    def put_task(
        self,
        task: TaskRecord,
        *,
        expected_state: str | None = None,
        allow_terminal_rewrite: bool = False,
        max_running: int | None = None,
    ) -> TaskRecord:
        """落盘任务；终局不可改写，唯一例外是产物篡改隔离（``succeeded → failed``）。

        ``max_running`` 非空时在**同一个排他锁临界区**内复查该 node 的并发占用再追加。
        调用方"读 running → 判定 → 落盘"的三步不是原子的：两个并发提交可以同时通过
        上面的检查。最终裁决放在这里，读与写才是一次比较-写入。
        """
        if expected_state is None and task.state != "submitted":
            raise PeerError("idempotency_conflict", "新任务只能以 submitted 落盘")
        with self._lock(exclusive=True):
            payload = self._read("tasks")
            for index, item in enumerate(payload["items"]):
                if item.get("task_id") != task.task_id:
                    continue
                current = TaskRecord.from_dict(item)
                if expected_state is not None and current.state != expected_state:
                    raise PeerError("idempotency_conflict", f"task {task.task_id} CAS 失败")
                if current.state in TERMINAL_STATES:
                    if not (allow_terminal_rewrite and can_quarantine(current.state, task.state)):
                        raise PeerError("idempotency_conflict", f"task {task.task_id} 已终局")
                else:
                    require_transition(current.state, task.state)
                # 进入槽位（非 SLOT_STATES → SLOT_STATES）时在同一临界区复查上限：
                # 监督通道的 awaiting→admitted 走的是更新分支，若只在追加分支检查，
                # "人点确认"就能绕过并发闸（P1-4 的更新分支一半）。
                if max_running is not None and task.state in SLOT_STATES:
                    occupied = sum(
                        1
                        for row in payload["items"]
                        if row.get("node_id") == task.node_id
                        and row.get("state") in SLOT_STATES
                        and row.get("task_id") != task.task_id
                    )
                    if occupied >= int(max_running):
                        raise PeerError(
                            "quota_concurrency_exceeded",
                            f"{occupied}/{int(max_running)} for {task.node_id}",
                        )
                payload["items"][index] = task.to_dict()
                self._write("tasks", payload)
                return task
            if max_running is not None:
                running = sum(
                    1
                    for item in payload["items"]
                    if item.get("node_id") == task.node_id
                    and item.get("state") in SLOT_STATES
                )
                if running >= int(max_running):
                    raise PeerError(
                        "quota_concurrency_exceeded",
                        f"{running}/{int(max_running)} for {task.node_id}",
                    )
            payload["items"].append(task.to_dict())
            self._write("tasks", payload)
        return task


def _replace_node(node: NodeRecord, **changes: Any) -> NodeRecord:
    data = node.to_dict()
    data.update(changes)
    return NodeRecord.from_dict(data)


def _safe_name(raw: str) -> str:
    if not raw or len(raw) > 128 or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_." for ch in raw):
        raise ValueError(f"非法标识符: {raw!r}")
    return raw

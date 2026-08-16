"""HandleRegistry 执行句柄注册表（design.md §2.2.2.4）.

维护在途委派句柄与本地会话/trace_id 关联。内存索引 + 事件日志落盘
（重启可恢复）。并发上限校验（spec §4.1.5 上限 10）。线程安全（threading.Lock）。

recover() 从事件日志扫描 codearts.dispatched 且未 codearts.collected/cancelled
的句柄重建内存索引（进程重启接管，spec §4.2.2）。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from llm_loop.codearts.models import ExecutionHandle, HandleStatus, RemoteStatus
from llm_loop.event_log.model import (
    EVENT_CODEARTS_CANCELLED,
    EVENT_CODEARTS_COLLECTED,
    EVENT_CODEARTS_DISPATCHED,
)
from llm_loop.event_log.store import EventStore

logger = logging.getLogger(__name__)

_IN_FLIGHT_STATUSES: frozenset[HandleStatus] = frozenset(
    {HandleStatus.PENDING, HandleStatus.RUNNING, HandleStatus.UNKNOWN}
)


class HandleRegistry:
    """执行句柄注册表（内存索引 + 事件日志落盘 + 重启恢复）."""

    def __init__(self, event_store: EventStore, *, max_concurrent: int = 10) -> None:
        self._event_store = event_store
        self._max_concurrent = max_concurrent
        self._handles: dict[str, ExecutionHandle] = {}
        self._sessions: dict[str, tuple[str, str]] = {}  # handle_id -> (session_id, trace_id)
        self._lock = threading.Lock()

    def register(
        self, handle: ExecutionHandle, *, session_id: str, trace_id: str
    ) -> None:
        """登记句柄 + 事件日志落盘（payload 不含凭证明文）."""
        with self._lock:
            self._handles[handle.handle_id] = handle
            self._sessions[handle.handle_id] = (session_id, trace_id)
        # 事件日志落盘（fail-open）
        self._event_store.append(
            session_id,
            EVENT_CODEARTS_DISPATCHED,
            {
                "handle_id": handle.handle_id,
                "session_id": session_id,
                "trace_id": trace_id,
                "created_at": handle.created_at,
                "task_description": "",
                "priority": "",
                "risk_level": "",
            },
        )

    def get(self, handle_id: str) -> ExecutionHandle | None:
        with self._lock:
            return self._handles.get(handle_id)

    def get_session_info(self, handle_id: str) -> tuple[str, str] | None:
        """获取句柄关联的 (session_id, trace_id)."""
        with self._lock:
            return self._sessions.get(handle_id)

    def list_in_flight(self) -> list[ExecutionHandle]:
        """列出在途句柄（status ∈ {PENDING, RUNNING, UNKNOWN}）."""
        with self._lock:
            return [
                h for h in self._handles.values() if h.status in _IN_FLIGHT_STATUSES
            ]

    def update_status(
        self,
        handle_id: str,
        status: HandleStatus,
        remote_status: RemoteStatus | None = None,
    ) -> bool:
        """更新句柄状态；返回是否检测到状态漂移."""
        with self._lock:
            handle = self._handles.get(handle_id)
            if handle is None:
                return False
            drift = False
            new_remote = remote_status if remote_status is not None else handle.remote_status
            # 状态漂移检测：本地与远端不一致
            if remote_status is not None and handle.status != HandleStatus.UNKNOWN:
                local_terminal = status in {
                    HandleStatus.SUCCEEDED,
                    HandleStatus.FAILED,
                    HandleStatus.TIMEOUT,
                    HandleStatus.CANCELLED,
                }
                if local_terminal and status.value != remote_status.value:
                    drift = True
            updated = replace(
                handle,
                status=status,
                remote_status=new_remote,
                last_synced_at=datetime.now(UTC).isoformat(),
            )
            self._handles[handle_id] = updated
            return drift

    def release(self, handle_id: str) -> None:
        """从在途集合移除（保留记录供审计，仅从在途判定中排除）."""
        with self._lock:
            handle = self._handles.get(handle_id)
            if handle is not None:
                # 标记为终态（不再计入在途）
                self._handles[handle_id] = replace(handle, status=handle.status)

    def is_full(self) -> bool:
        """在途句柄数是否达上限."""
        with self._lock:
            in_flight = sum(1 for h in self._handles.values() if h.status in _IN_FLIGHT_STATUSES)
            return in_flight >= self._max_concurrent

    def in_flight_count(self) -> int:
        """当前在途句柄数."""
        with self._lock:
            return sum(1 for h in self._handles.values() if h.status in _IN_FLIGHT_STATUSES)

    def recover(self) -> int:
        """从事件日志重建在途句柄内存索引（进程重启接管）.

        扫描所有会话事件日志中 codearts.dispatched 且未 codearts.collected/
        codearts.cancelled 的句柄，重建内存索引。返回恢复数量。
        """
        recovered = 0
        try:
            event_logs_dir = self._event_store._dir  # noqa: SLF001 — 读取事件日志目录
            from pathlib import Path

            dir_path = Path(event_logs_dir)
            if not dir_path.exists():
                return 0
            # 扫描所有会话事件日志文件
            for jsonl_path in dir_path.glob("*.jsonl"):
                if jsonl_path.name.endswith(".lock"):
                    continue
                session_id = jsonl_path.stem
                dispatched: dict[str, dict[str, Any]] = {}
                collected: set[str] = set()
                cancelled: set[str] = set()
                try:
                    with jsonl_path.open("r", encoding="utf-8") as f:
                        for raw in f:
                            line = raw.strip()
                            if not line:
                                continue
                            from llm_loop.event_log.model import parse_event_line

                            ev = parse_event_line(line)
                            if ev is None:
                                continue
                            if ev.type == EVENT_CODEARTS_DISPATCHED:
                                hid = str(ev.payload.get("handle_id") or "")
                                if hid:
                                    dispatched[hid] = ev.payload
                            elif ev.type == EVENT_CODEARTS_COLLECTED:
                                hid = str(ev.payload.get("handle_id") or "")
                                if hid:
                                    collected.add(hid)
                            elif ev.type == EVENT_CODEARTS_CANCELLED:
                                hid = str(ev.payload.get("handle_id") or "")
                                if hid:
                                    cancelled.add(hid)
                except OSError:
                    continue
                # 重建在途句柄（dispatched 但未 collected/cancelled）
                for hid, payload in dispatched.items():
                    if hid in collected or hid in cancelled:
                        continue
                    with self._lock:
                        if hid in self._handles:
                            continue  # 已存在不覆盖
                    handle = ExecutionHandle(
                        handle_id=hid,
                        session_id=str(payload.get("session_id") or session_id),
                        trace_id=str(payload.get("trace_id") or ""),
                        created_at=str(payload.get("created_at") or ""),
                        status=HandleStatus.UNKNOWN,  # 重启后状态未知，经同步最终对齐
                        last_synced_at="",
                        remote_status=RemoteStatus.PENDING,
                    )
                    with self._lock:
                        self._handles[hid] = handle
                        self._sessions[hid] = (handle.session_id, handle.trace_id)
                    recovered += 1
        except Exception:  # noqa: BLE001 — 恢复失败不阻断启动
            logger.warning("CodeArts 句柄恢复失败（fail-open）", exc_info=True)
        if recovered > 0:
            logger.info("CodeArts 句柄恢复: 接管 %d 个在途委派", recovered)
        return recovered

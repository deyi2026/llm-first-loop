"""StateSynchronizer 状态同步器（design.md §2.2.2.5）.

驱动本地状态与远端状态一致。轮询兜底（间隔下限 5s，spec §4.1.4）。
状态变更经 HandleRegistry.update_status 更新 + 事件日志落盘。
状态查询持续失败标注 HandleStatus.UNKNOWN 不臆造状态（spec §5.2.1.6）。
终态时调用 on_terminal 回调并停止轮询。

轮询在独立线程中执行（不阻塞主循环）。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from llm_loop.codearts.client import (
    CallTimeoutError,
    ClientError,
    CodeArtsClient,
    ConnectionTimeoutError,
    RetryableError,
)
from llm_loop.codearts.config import CodeArtsSettings
from llm_loop.codearts.credential import CredentialProvider, CredentialRefreshError
from llm_loop.codearts.handle import HandleRegistry
from llm_loop.codearts.models import (
    TERMINAL_STATUSES,
    ExecutionHandle,
    HandleStatus,
    RemoteStatus,
)
from llm_loop.event_log.model import (
    EVENT_CODEARTS_STATUS_SYNCED,
    EVENT_CODEARTS_STATUS_UNKNOWN,
)
from llm_loop.event_log.store import EventStore

logger = logging.getLogger(__name__)

# 远端状态 → 本地状态映射
_REMOTE_TO_LOCAL: dict[RemoteStatus, HandleStatus] = {
    RemoteStatus.PENDING: HandleStatus.PENDING,
    RemoteStatus.RUNNING: HandleStatus.RUNNING,
    RemoteStatus.SUCCEEDED: HandleStatus.SUCCEEDED,
    RemoteStatus.FAILED: HandleStatus.FAILED,
    RemoteStatus.TIMEOUT: HandleStatus.TIMEOUT,
    RemoteStatus.CANCELLED: HandleStatus.CANCELLED,
}


class StateSynchronizer(Protocol):
    """状态同步器协议（design.md §2.2.2.5 扩展点 3）."""

    def start(
        self,
        handle: ExecutionHandle,
        *,
        on_terminal: Callable[[HandleStatus], None],
    ) -> None: ...


    def stop(self, handle_id: str) -> None: ...


class PollingSynchronizer:
    """轮询状态同步器（默认实现，间隔下限 5s）.

    轮询在独立线程中执行（daemon=True，不阻塞主循环，进程退出自动结束）。
    """

    def __init__(
        self,
        client: CodeArtsClient,
        credential_provider: CredentialProvider,
        handle_registry: HandleRegistry,
        event_store: EventStore,
        config: CodeArtsSettings,
    ) -> None:
        self._client = client
        self._credential_provider = credential_provider
        self._handle_registry = handle_registry
        self._event_store = event_store
        self._config = config
        self._stop_flags: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def start(
        self,
        handle: ExecutionHandle,
        *,
        on_terminal: Callable[[HandleStatus], None],
    ) -> None:
        """启动状态同步轮询（独立线程）."""
        stop_flag = threading.Event()
        with self._lock:
            self._stop_flags[handle.handle_id] = stop_flag

        def _poll_loop() -> None:
            failed_attempts = 0
            max_fail = self._config.max_retries
            while not stop_flag.is_set():
                # 轮询间隔下限 5s
                interval = max(5, self._config.poll_interval_s)
                stop_flag.wait(interval)
                if stop_flag.is_set():
                    break
                try:
                    credential = self._credential_provider.get(self._config.region)
                    remote_status = self._client.query_status(handle, credential)
                    failed_attempts = 0
                    local_status = _REMOTE_TO_LOCAL.get(remote_status, HandleStatus.UNKNOWN)
                    drift = self._handle_registry.update_status(
                        handle.handle_id, local_status, remote_status
                    )
                    # 状态同步事件落盘
                    session_info = self._handle_registry.get_session_info(handle.handle_id)
                    sid = session_info[0] if session_info else handle.session_id
                    self._event_store.append(
                        sid,
                        EVENT_CODEARTS_STATUS_SYNCED,
                        {
                            "handle_id": handle.handle_id,
                            "session_id": sid,
                            "trace_id": handle.trace_id,
                            "status": local_status.value,
                            "remote_status": remote_status.value,
                            "synced_at": datetime.now(UTC).isoformat(),
                            "drift": drift,
                        },
                    )
                    if local_status in TERMINAL_STATUSES:
                        on_terminal(local_status)
                        return
                except (CredentialRefreshError, ConnectionTimeoutError, CallTimeoutError) as exc:
                    failed_attempts += 1
                    if failed_attempts > max_fail:
                        # 标注状态未知不臆造
                        self._handle_registry.update_status(
                            handle.handle_id, HandleStatus.UNKNOWN
                        )
                        session_info = self._handle_registry.get_session_info(handle.handle_id)
                        sid = session_info[0] if session_info else handle.session_id
                        self._event_store.append(
                            sid,
                            EVENT_CODEARTS_STATUS_UNKNOWN,
                            {
                                "handle_id": handle.handle_id,
                                "session_id": sid,
                                "trace_id": handle.trace_id,
                                "reason": f"{type(exc).__name__}: {exc}",
                                "failed_attempts": failed_attempts,
                            },
                        )
                        on_terminal(HandleStatus.UNKNOWN)
                        return
                except (ClientError, RetryableError) as exc:
                    failed_attempts += 1
                    if failed_attempts > max_fail:
                        self._handle_registry.update_status(
                            handle.handle_id, HandleStatus.UNKNOWN
                        )
                        session_info = self._handle_registry.get_session_info(handle.handle_id)
                        sid = session_info[0] if session_info else handle.session_id
                        self._event_store.append(
                            sid,
                            EVENT_CODEARTS_STATUS_UNKNOWN,
                            {
                                "handle_id": handle.handle_id,
                                "session_id": sid,
                                "trace_id": handle.trace_id,
                                "reason": f"{type(exc).__name__}: {exc}",
                                "failed_attempts": failed_attempts,
                            },
                        )
                        on_terminal(HandleStatus.UNKNOWN)
                        return
                except Exception:  # noqa: BLE001 — 未预期异常不阻断轮询
                    failed_attempts += 1
                    if failed_attempts > max_fail:
                        self._handle_registry.update_status(
                            handle.handle_id, HandleStatus.UNKNOWN
                        )
                        on_terminal(HandleStatus.UNKNOWN)
                        return

        thread = threading.Thread(target=_poll_loop, daemon=True, name=f"codearts-sync-{handle.handle_id}")
        with self._lock:
            self._threads[handle.handle_id] = thread
        thread.start()

    def stop(self, handle_id: str) -> None:
        """主动停止轮询."""
        with self._lock:
            stop_flag = self._stop_flags.get(handle_id)
            if stop_flag is not None:
                stop_flag.set()
            self._stop_flags.pop(handle_id, None)
            self._threads.pop(handle_id, None)

"""连接状态机与四事实分离（`T-CONTRACT-6`）。

对应需求：`RTM-SES-01/05`、`RTM-REC-03/05/09`、`RTM-LIF-01/02/04`、`RTM-IDN-03/07`、
`RTM-PLY-03`、`RTM-CAP-14`。

状态机：`opening → ready → reconnecting → ready / failed → closing → closed`

关键语义（`DESIGN v1.3 §2.1.3-A`、D27）：

- **`ready` = 握手完成 + 传输通道就绪（可双向收发）**，**不要求已收到首帧**；
  `opening` 未就绪前**不得上传媒体**；
- **任一活动态均可主动结束**并进入 `closing → closed`；
- **非可重试错误不循环**：鉴权失效/配额不足/协议不兼容/本地服务未起/端口不可达/格式协商失败
  直接 `failed`，**不进 `reconnecting`**；可重试错误有界重连（默认 3 次）；
- **四事实分离**：`connection_state` / `mic_enabled` / `playback_state` / `task_state`
  各自独立可观测（禁单一 `streaming` 布尔）；旧代次按 `connection_epoch` 隔离。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ConnectionState(StrEnum):
    OPENING = "opening"
    READY = "ready"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
    CLOSING = "closing"
    CLOSED = "closed"


class PlaybackState(StrEnum):
    IDLE = "idle"
    PLAYING = "playing"
    STOPPED = "stopped"


class TaskState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class NonRetryableFailure(StrEnum):
    """非可重试错误：**不得**进入 `reconnecting`（`RTM-REC-09`、`RTM-CAP-14`）。"""

    AUTH_INVALID = "auth_invalid"
    QUOTA_EXHAUSTED = "quota_exhausted"
    PROTOCOL_INCOMPATIBLE = "protocol_incompatible"
    LOCAL_SERVICE_DOWN = "local_service_down"
    PORT_UNREACHABLE = "port_unreachable"
    FORMAT_NEGOTIATION_FAILED = "format_negotiation_failed"


_ACTIVE_STATES = frozenset(
    {ConnectionState.OPENING, ConnectionState.READY, ConnectionState.RECONNECTING}
)


@dataclass(frozen=True)
class SessionFacts:
    """四事实分离：均可独立观测，互不折叠为单一布尔。"""

    media_session_id: str
    connection_state: ConnectionState
    mic_enabled: bool
    playback_state: PlaybackState
    task_state: TaskState
    connection_epoch: int


class MediaSession:
    """单个媒体会话的连接状态机与可观测事实。"""

    def __init__(self, media_session_id: str, *, max_reconnect: int = 3) -> None:
        if not media_session_id:
            raise ValueError("media_session_id is required")
        if max_reconnect < 0:
            raise ValueError("max_reconnect must be >= 0")
        self._media_session_id = media_session_id
        self._max_reconnect = max_reconnect
        self._state = ConnectionState.CLOSED
        self._epoch = 0
        self._reconnect_attempts = 0
        self._mic_enabled = False
        self._playback = PlaybackState.IDLE
        self._task = TaskState.IDLE

    @property
    def media_session_id(self) -> str:
        return self._media_session_id

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def connection_epoch(self) -> int:
        return self._epoch

    def start(self, *, epoch: int = 1) -> None:
        """开始建连（`opening`）。未就绪前不得上传媒体。"""
        if self._state in _ACTIVE_STATES:
            raise RuntimeError(f"already active: {self._state}")
        if epoch < 1:
            raise ValueError("epoch must be >= 1")
        self._epoch = epoch
        self._reconnect_attempts = 0
        self._state = ConnectionState.OPENING

    def mark_transport_ready(self, *, epoch: int | None = None) -> None:
        """握手完成 + 传输就绪即 `ready`（**不要求先收到首帧**）。"""
        if self._state not in (ConnectionState.OPENING, ConnectionState.RECONNECTING):
            raise RuntimeError(f"cannot become ready from {self._state}")
        if epoch is not None:
            if epoch < self._epoch:
                raise ValueError("stale connection_epoch must not update current session")
            self._epoch = epoch
        self._reconnect_attempts = 0
        self._state = ConnectionState.READY

    def can_upload(self) -> bool:
        """仅 `ready` 允许上传媒体。"""
        return self._state is ConnectionState.READY

    def on_retryable_error(self) -> ConnectionState:
        """可重试错误：**有界**重连；超过上限 → `failed`。"""
        if self._state not in _ACTIVE_STATES:
            raise RuntimeError(f"retryable error outside active state: {self._state}")
        if self._reconnect_attempts >= self._max_reconnect:
            self._state = ConnectionState.FAILED
            return self._state
        self._reconnect_attempts += 1
        self._state = ConnectionState.RECONNECTING
        return self._state

    def on_non_retryable_error(self, kind: NonRetryableFailure) -> ConnectionState:
        """非可重试错误：直接 `failed`，**不循环重连**。"""
        if not isinstance(kind, NonRetryableFailure):
            raise TypeError("kind must be NonRetryableFailure")
        self._state = ConnectionState.FAILED
        return self._state

    def close(self) -> ConnectionState:
        """**任一活动态**均可主动结束 → `closing → closed`。"""
        if self._state is ConnectionState.CLOSED:
            return self._state
        self._state = ConnectionState.CLOSING
        self._mic_enabled = False
        self._state = ConnectionState.CLOSED
        return self._state

    def set_mic(self, enabled: bool) -> None:
        self._mic_enabled = bool(enabled)

    def set_playback(self, state: PlaybackState) -> None:
        if not isinstance(state, PlaybackState):
            raise TypeError("state must be PlaybackState")
        self._playback = state

    def set_task(self, state: TaskState) -> None:
        if not isinstance(state, TaskState):
            raise TypeError("state must be TaskState")
        self._task = state

    def facts(self) -> SessionFacts:
        return SessionFacts(
            media_session_id=self._media_session_id,
            connection_state=self._state,
            mic_enabled=self._mic_enabled,
            playback_state=self._playback,
            task_state=self._task,
            connection_epoch=self._epoch,
        )

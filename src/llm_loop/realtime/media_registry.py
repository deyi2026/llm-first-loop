"""媒体会话登记与归属（`T-CONTRACT-6` / M1 装配）。

对应需求：`RTM-SES-01/02/03/06/07`、`RTM-IDN-02/03/07`、`RTM-SEC-06/08`。

- 提供媒体会话的**归属校验**（供 `realtime_ws` 在 accept 前查询；越权按防枚举统一处理）；
- 同一 LFL 会话的**媒体写入者租约**：已有活动写入者时新连接须显式接管（否则 409）；
- `connection_epoch` 代次隔离：旧代次不得更新当前会话（`RTM-IDN-02`）。

本模块只做机械事实（归属、租约、代次），不做语义判断。
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass

from llm_loop.realtime.media_session import MediaSession


@dataclass
class MediaSessionRecord:
    media_session_id: str
    session_id: str
    workspace_scope: str
    owner_cookie: str
    connection_epoch: int
    session: MediaSession
    audio_mode: str = "push_to_talk"
    enable_on_demand_vision: bool = False
    closed: bool = False


def _new_media_session_id() -> str:
    return "ms-" + secrets.token_hex(8)


class MediaSessionRegistry:
    """线程安全的媒体会话登记表。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, MediaSessionRecord] = {}

    def active_writer_conflict(self, session_id: str) -> bool:
        """同 LFL 会话是否已有未关闭的媒体写入者（用于 409 需显式接管）。"""
        with self._lock:
            return any(
                rec.session_id == session_id and not rec.closed
                for rec in self._by_id.values()
            )

    def create(
        self,
        *,
        session_id: str,
        workspace_scope: str,
        owner_cookie: str,
        audio_mode: str = "push_to_talk",
        enable_on_demand_vision: bool = False,
        take_over: bool = False,
    ) -> MediaSessionRecord:
        epoch = 1
        with self._lock:
            for rec in self._by_id.values():
                if rec.session_id == session_id and not rec.closed:
                    epoch = rec.connection_epoch + 1
                    if take_over:
                        # 显式接管：先关闭旧写入者，避免并存两个活动 writer
                        rec.session.close()
                        rec.closed = True
        media_session_id = _new_media_session_id()
        session = MediaSession(media_session_id)
        session.start(epoch=epoch)
        record = MediaSessionRecord(
            media_session_id=media_session_id,
            session_id=session_id,
            workspace_scope=workspace_scope,
            owner_cookie=owner_cookie,
            connection_epoch=epoch,
            session=session,
            audio_mode=audio_mode,
            enable_on_demand_vision=enable_on_demand_vision,
        )
        with self._lock:
            self._by_id[media_session_id] = record
        return record

    def owns(self, media_session_id: str, *, session_cookie: str) -> bool:
        """归属校验：ID + 所有者 cookie 均匹配且未关闭（越权/未知统一返回 False）。"""
        with self._lock:
            rec = self._by_id.get(media_session_id)
            if rec is None or rec.closed:
                return False
            return bool(session_cookie) and secrets.compare_digest(
                rec.owner_cookie, session_cookie
            )

    def get(self, media_session_id: str, *, session_cookie: str) -> MediaSessionRecord | None:
        """越权/未知一律返回 None（防枚举，不泄露存在性）。"""
        if not self.owns(media_session_id, session_cookie=session_cookie):
            return None
        with self._lock:
            return self._by_id.get(media_session_id)

    def close(self, media_session_id: str, *, session_cookie: str) -> MediaSessionRecord | None:
        """关闭媒体会话；**幂等**（重复关闭同一会话仍返回记录）。越权/未知返回 None。"""
        with self._lock:
            record = self._by_id.get(media_session_id)
            if record is None:
                return None
            if not session_cookie or not secrets.compare_digest(
                record.owner_cookie, session_cookie
            ):
                return None  # 越权/未知：统一不泄露存在性
            if not record.closed:
                record.session.close()
                record.closed = True
            return record

    def count_active(self) -> int:
        with self._lock:
            return sum(1 for rec in self._by_id.values() if not rec.closed)

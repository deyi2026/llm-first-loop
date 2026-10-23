"""T-CONTRACT-4：实时会话控制通道 WS 的握手鉴权与拒绝路径。

对应需求：`RTM-SES-02/03/07`、`RTM-SEC-01/06/08`、`RTM-CAP-05`、`RTM-IDN-02`。

关键事实（`DESIGN v1.3 §2.2.2-B1`）：

- 现有 `_OriginGuardMiddleware` / `_CanonicalOriginMiddleware` **只覆盖 HTTP**；
- 现有鉴权（`request_authenticated` / `WebSessionStore.valid`）是 HTTP 依赖，
  WS 不能直接复用 `Depends`，须在 **accept 之前**显式校验；
- 拒绝码：`4401`（未登录/身份失效）、`4403`（跨站 Origin）、`4404`（越权，防枚举）；
- 拒绝后**不建立任何媒体/任务副作用**；
- 控制通道同时承载文本事件帧与**音频二进制帧**（上行 16k PCM / 下行 TTS）。

本模块只做机械边界（身份、来源、归属、字节格式），不做语义判断。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from fastapi import FastAPI, WebSocket

from llm_loop.web.auth import (
    SESSION_COOKIE_NAME,
    configured_origin_allowlist,
    normalize_origin,
    request_authenticated,
    request_is_trusted_local,
)

logger = logging.getLogger(__name__)

REALTIME_WS_PATH = "/api/v1/realtime/sessions/{media_session_id}/events"

CLOSE_UNAUTHENTICATED = 4401
CLOSE_CROSS_SITE_ORIGIN = 4403
CLOSE_FORBIDDEN_TARGET = 4404


class HandshakeRejection(StrEnum):
    """握手裁决。

    - `ALLOW`：全部通过；
    - `PENDING_TARGET`：身份与 Origin 已通过，尚需查询归属（惰性，先决失败不接触归属登记）；
    - `UNAUTHENTICATED` / `CROSS_SITE_ORIGIN` / `FORBIDDEN_TARGET`：拒绝。
    """

    ALLOW = "allow"
    PENDING_TARGET = "pending_target"
    UNAUTHENTICATED = "unauthenticated"
    CROSS_SITE_ORIGIN = "cross_site_origin"
    FORBIDDEN_TARGET = "forbidden_target"


_CLOSE_CODES: dict[HandshakeRejection, int] = {
    HandshakeRejection.UNAUTHENTICATED: CLOSE_UNAUTHENTICATED,
    HandshakeRejection.CROSS_SITE_ORIGIN: CLOSE_CROSS_SITE_ORIGIN,
    HandshakeRejection.FORBIDDEN_TARGET: CLOSE_FORBIDDEN_TARGET,
}


def close_code_for(rejection: HandshakeRejection) -> int:
    return _CLOSE_CODES.get(rejection, 1000)


@dataclass(frozen=True)
class HandshakeFacts:
    """握手所需的机械事实（已从 WebSocket 抽取，便于确定性测试）。

    `target_owned=None` 表示**尚未查询归属**：先决检查（身份/Origin）未通过时
    不应接触归属登记（防枚举，且避免拒绝路径产生副作用）。
    """

    authenticated: bool
    origin: str
    allowed_origins: frozenset[str]
    trusted_local: bool
    target_owned: bool | None = None


def evaluate_handshake(facts: HandshakeFacts) -> HandshakeRejection:
    """按「身份 → Origin → 归属」顺序裁决；前者不通过即拒绝。

    归属只在身份与 Origin 均通过后才读取；`None` 表示需要调用方惰性查询。
    """
    if not facts.authenticated:
        return HandshakeRejection.UNAUTHENTICATED

    raw_origin = (facts.origin or "").strip()
    if raw_origin:
        try:
            origin = normalize_origin(raw_origin)
        except ValueError:
            return HandshakeRejection.CROSS_SITE_ORIGIN
        if origin not in facts.allowed_origins:
            return HandshakeRejection.CROSS_SITE_ORIGIN
    elif not facts.trusted_local:
        # 无 Origin 的非浏览器来源：仅直接回环可信，其余拒绝（防 CSRF/伪造）。
        return HandshakeRejection.CROSS_SITE_ORIGIN

    if facts.target_owned is None:
        return HandshakeRejection.PENDING_TARGET
    if not facts.target_owned:
        return HandshakeRejection.FORBIDDEN_TARGET

    return HandshakeRejection.ALLOW


class MediaSessionOwnership(Protocol):
    """媒体会话归属校验协议：仅知道 ID 不能读取或控制（`RTM-IDN-02`）。"""

    def owns(self, media_session_id: str, *, session_cookie: str) -> bool: ...


def _same_origin(websocket: WebSocket) -> str:
    """从 WS 连接计算其 HTTP 同源 Origin（ws→http、wss→https）。"""
    scheme = "https" if websocket.url.scheme == "wss" else "http"
    host = websocket.url.hostname or ""
    if not host:
        return ""
    port = websocket.url.port
    authority = f"[{host}]" if ":" in host else host
    if port is not None and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        authority += f":{port}"
    return f"{scheme}://{authority}"


def _allowed_origins(websocket: WebSocket) -> frozenset[str]:
    allowed = set(configured_origin_allowlist())
    same = _same_origin(websocket)
    if same:
        allowed.add(same)
    return frozenset(allowed)


def _target_owned(websocket: WebSocket, media_session_id: str) -> bool:
    registry = getattr(websocket.app.state, "realtime_media_sessions", None)
    if registry is None:
        # 尚无可核实的归属登记：拒绝（未知目标不建立副作用；防枚举）。
        return False
    session_cookie = websocket.cookies.get(SESSION_COOKIE_NAME, "")
    return bool(registry.owns(media_session_id, session_cookie=session_cookie))


def collect_handshake_facts(websocket: WebSocket) -> HandshakeFacts:
    """抽取先决事实（身份/Origin）。**不查询归属**——归属由调用方惰性查询。"""
    return HandshakeFacts(
        authenticated=bool(
            request_authenticated(websocket)  # type: ignore[arg-type]  # duck-typed WebSocket
        ),
        origin=websocket.headers.get("origin", ""),
        allowed_origins=_allowed_origins(websocket),
        trusted_local=bool(
            request_is_trusted_local(websocket)  # type: ignore[arg-type]
        ),
    )


def _default_transport_factory():
    """默认本地栈传输：经回环连接本机 `mlx-audio`（终稿/TTS 走 HTTP；流式可选）。"""
    import httpx

    from llm_loop.realtime.local_voice_stack_transport import (
        DEFAULT_MLX_AUDIO_BASE,
        DEFAULT_MLX_AUDIO_WS,
        LocalVoiceStackTransport,
        default_websocket_connector,
    )

    transport = LocalVoiceStackTransport(
        http_client=httpx.Client(timeout=30.0, follow_redirects=False),
        ws_connector=default_websocket_connector,
    )
    with contextlib.suppress(Exception):  # 流式通道可选，不可用不影响终稿
        transport.connect(DEFAULT_MLX_AUDIO_WS)
    return transport, f"{DEFAULT_MLX_AUDIO_BASE}/v1/audio/transcriptions"


async def _serve(websocket: WebSocket, media_session_id: str) -> None:
    """Authenticated media only; task execution remains in the existing chat ingress."""
    from llm_loop.realtime.realtime_session_runtime import RealtimeSessionRuntime

    registry = websocket.app.state.realtime_media_sessions
    cookie = websocket.cookies.get(SESSION_COOKIE_NAME, "")
    record = registry.get(media_session_id, session_cookie=cookie)
    if record is None:
        await websocket.close(code=4404)
        return
    def active() -> bool:
        return _target_owned(websocket, media_session_id)
    factory = getattr(websocket.app.state, "realtime_transport_factory", _default_transport_factory)
    try:
        transport, transcription_url = await asyncio.to_thread(factory)
    except Exception:
        await websocket.close(code=1011)
        return
    runtime = RealtimeSessionRuntime(
        media_session_id=media_session_id, session_id=record.session_id,
        connection_epoch=record.connection_epoch, transport=transport,
        transcription_url=transcription_url, send_text=websocket.send_text,
        send_binary=websocket.send_bytes, is_active=active,
    )
    pump = asyncio.create_task(runtime.pump_deltas())
    try:
        while active():
            try:
                # Revocation must close a quiet old writer as well as a chatty one.
                message = await asyncio.wait_for(websocket.receive(), timeout=0.25)
            except TimeoutError:
                continue
            if message.get("type") == "websocket.disconnect":
                return
            if not active():
                await websocket.close(code=4404)
                return
            if message.get("bytes") is not None:
                await runtime.handle_binary(message["bytes"])
            elif message.get("text") is not None:
                await runtime.handle_text(message["text"])
        with contextlib.suppress(Exception):
            await websocket.close(code=4404)
    except Exception:
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
    finally:
        runtime.stop()
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump
        await asyncio.to_thread(transport.close)
        registry.close(media_session_id, session_cookie=cookie)



def register_realtime_ws(app: FastAPI) -> None:
    """注册实时会话控制通道 WS。须在 `accept` 之前完成鉴权与归属校验。"""

    @app.websocket(REALTIME_WS_PATH)
    async def realtime_events(websocket: WebSocket, media_session_id: str) -> None:
        facts = collect_handshake_facts(websocket)
        rejection = evaluate_handshake(facts)
        if rejection is HandshakeRejection.PENDING_TARGET:
            # 仅当前置检查通过才查询归属（防枚举；拒绝路径不接触登记）。
            rejection = (
                HandshakeRejection.ALLOW
                if _target_owned(websocket, media_session_id)
                else HandshakeRejection.FORBIDDEN_TARGET
            )
        if rejection is not HandshakeRejection.ALLOW:
            # 未 accept 即关闭：不建立任何媒体/任务副作用。
            logger.info(
                "realtime_ws_rejected media_session_id=%s rejection=%s close_code=%s",
                media_session_id,
                rejection.value,
                close_code_for(rejection),
            )
            await websocket.close(code=close_code_for(rejection))
            return
        await websocket.accept()
        await _serve(websocket, media_session_id)

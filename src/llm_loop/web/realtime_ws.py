"""T-CONTRACT-4：实时会话控制通道 WS 的握手鉴权与拒绝路径。

对应需求：`RTM-SES-02/03/07`、`RTM-SEC-01/06/08`、`RTM-CAP-05`、`RTM-IDN-02`。

关键事实（`DESIGN v1.3 §2.2.2-B1`）：

- 现有 `_OriginGuardMiddleware` / `_CanonicalOriginMiddleware` **只覆盖 HTTP**；
- 现有鉴权（`request_authenticated` / `WebSessionStore.valid`）是 HTTP 依赖，
  WS 不能直接复用 `Depends`，须在 **accept 之前**显式校验；
- 拒绝码：`4401`（未登录/身份失效）、`4403`（跨站 Origin）、`4404`（越权，防枚举）、
  `4405`（S3-2：仅 Bearer、无浏览器会话——真实麦克风会话仅限浏览器）；
- 拒绝后**不建立任何媒体/任务副作用**；
- 控制通道同时承载文本事件帧与**音频二进制帧**（上行 16k PCM / 下行 TTS）。

本模块只做机械边界（身份、来源、归属、字节格式），不做语义判断。
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from fastapi import FastAPI, WebSocket

from llm_loop.web.auth import (
    configured_extra_origin_allowlist,
    configured_origin_allowlist,
    normalize_origin,
    request_authenticated,
    request_is_trusted_local,
    session_cookie_value,
    valid_browser_session,
)

logger = logging.getLogger(__name__)

REALTIME_WS_PATH = "/api/v1/realtime/sessions/{media_session_id}/events"

CLOSE_UNAUTHENTICATED = 4401
CLOSE_CROSS_SITE_ORIGIN = 4403
CLOSE_FORBIDDEN_TARGET = 4404
# S3-2（建议书 2026-10-25）：身份通过（如 Bearer API key）但没有浏览器会话
# cookie——真实麦克风会话必须由浏览器发起。accept 前拒绝，HTTP 层表现为 403。
CLOSE_REQUIRES_BROWSER_SESSION = 4405


class HandshakeRejection(StrEnum):
    """握手裁决。

    - `ALLOW`：全部通过；
    - `PENDING_TARGET`：身份与 Origin 已通过，尚需查询归属（惰性，先决失败不接触归属登记）；
    - `UNAUTHENTICATED` / `REQUIRES_BROWSER_SESSION` / `CROSS_SITE_ORIGIN` /
      `FORBIDDEN_TARGET`：拒绝（S3-2：真实麦克风会话要求浏览器会话 cookie，
      仅 Bearer → `REQUIRES_BROWSER_SESSION` = `ws_requires_browser_session`）。
    """

    ALLOW = "allow"
    PENDING_TARGET = "pending_target"
    UNAUTHENTICATED = "unauthenticated"
    REQUIRES_BROWSER_SESSION = "ws_requires_browser_session"
    CROSS_SITE_ORIGIN = "cross_site_origin"
    FORBIDDEN_TARGET = "forbidden_target"


_CLOSE_CODES: dict[HandshakeRejection, int] = {
    HandshakeRejection.UNAUTHENTICATED: CLOSE_UNAUTHENTICATED,
    HandshakeRejection.REQUIRES_BROWSER_SESSION: CLOSE_REQUIRES_BROWSER_SESSION,
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

    S3-2：`browser_session` 独立于 `authenticated`——Bearer API key 能通过
    `authenticated`，但真实麦克风会话还要求**浏览器会话 cookie** 有效。
    """

    authenticated: bool
    origin: str
    allowed_origins: frozenset[str]
    trusted_local: bool
    browser_session: bool = True
    target_owned: bool | None = None


def evaluate_handshake(facts: HandshakeFacts) -> HandshakeRejection:
    """按「身份 → 浏览器会话 → Origin → 归属」顺序裁决；前者不通过即拒绝。

    归属只在身份与 Origin 均通过后才读取；`None` 表示需要调用方惰性查询。
    """
    if not facts.authenticated:
        return HandshakeRejection.UNAUTHENTICATED

    # S3-2：真实麦克风会话仅限浏览器（会话 cookie + Origin 边界）。
    # Bearer-only（API/自动化通道）在此显式拒绝，而非依赖后续归属检查间接失败。
    if not facts.browser_session:
        return HandshakeRejection.REQUIRES_BROWSER_SESSION

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
    # S3-2：WS 握手专用扩展白名单（LFL_WEB_ALLOWED_ORIGINS）。
    allowed |= set(configured_extra_origin_allowlist())
    same = _same_origin(websocket)
    if same:
        allowed.add(same)
    return frozenset(allowed)


def _target_owned(websocket: WebSocket, media_session_id: str) -> bool:
    registry = getattr(websocket.app.state, "realtime_media_sessions", None)
    if registry is None:
        # 尚无可核实的归属登记：拒绝（未知目标不建立副作用；防枚举）。
        return False
    # S3-6 双名读取：__Host- 前缀名优先，旧名兼容。
    session_cookie = session_cookie_value(websocket.cookies)
    return bool(registry.owns(media_session_id, session_cookie=session_cookie))


def collect_handshake_facts(websocket: WebSocket) -> HandshakeFacts:
    """抽取先决事实（身份/浏览器会话/Origin）。**不查询归属**——归属由调用方惰性查询。"""
    return HandshakeFacts(
        authenticated=bool(
            request_authenticated(websocket)  # type: ignore[arg-type]  # duck-typed WebSocket
        ),
        origin=websocket.headers.get("origin", ""),
        allowed_origins=_allowed_origins(websocket),
        trusted_local=bool(
            request_is_trusted_local(websocket)  # type: ignore[arg-type]
        ),
        # S3-2：真实麦克风会话要求有效浏览器会话 cookie（__Host-/旧名双认）。
        browser_session=valid_browser_session(websocket),
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
        http_client=httpx.Client(timeout=30.0),
        ws_connector=default_websocket_connector,
        owns_http_client=True,  # P2-2：工厂自建客户端，所有权移交 transport，随会话 close 关闭
    )
    with contextlib.suppress(Exception):  # 流式通道可选，不可用不影响终稿
        transport.connect(DEFAULT_MLX_AUDIO_WS)
    return transport, f"{DEFAULT_MLX_AUDIO_BASE}/v1/audio/transcriptions"


def _session_id_for(websocket: WebSocket, media_session_id: str) -> str:
    registry = getattr(websocket.app.state, "realtime_media_sessions", None)
    if registry is None:
        return media_session_id
    record = getattr(registry, "_by_id", {}).get(media_session_id)
    return record.session_id if record is not None else media_session_id


def _connection_epoch_for(websocket: WebSocket, media_session_id: str) -> int:
    """读会话登记的 connection_epoch（IDN-02：信封代次校验基准）。"""
    registry = getattr(websocket.app.state, "realtime_media_sessions", None)
    if registry is None:
        return 1
    record = getattr(registry, "_by_id", {}).get(media_session_id)
    epoch = getattr(record, "connection_epoch", None)
    return int(epoch) if isinstance(epoch, int) and epoch > 0 else 1


def _record_closed(websocket: WebSocket, media_session_id: str) -> bool:
    """会话登记是否已被置 closed（take_over / DELETE；缺陷②）。

    无登记表或无记录时返回 False（不误杀既有连接；连接建立前的 closed 已由
    握手归属校验 ``owns`` 拒绝，这里只兜**收包循环期间**被并发关闭的场景）。
    """
    registry = getattr(websocket.app.state, "realtime_media_sessions", None)
    if registry is None:
        return False
    record = getattr(registry, "_by_id", {}).get(media_session_id)
    return bool(getattr(record, "closed", False))


def _keyframes_for(websocket: WebSocket, media_session_id: str):
    """M3：视觉链已装配则取本会话 pipeline；未装配返回 None（消息回 503）。"""
    service = getattr(websocket.app.state, "realtime_keyframes", None)
    if service is None:
        return None
    try:
        return service.pipeline_for(
            media_session_id=media_session_id,
            session_id=_session_id_for(websocket, media_session_id),
        )
    except Exception:  # noqa: BLE001 - 装配失败不伪装可用
        return None


def _session_probe_for(websocket: WebSocket):
    """P2-9a：视觉提交目标会话存在性探测（消费音频/bind/入队前拒绝不存在者）。

    生产装配（``build_app``）必有 ``app.state.engine``（``engine.session`` 为
    SessionStore）；未装配（局部测试 app）返回 None → runtime 不探测、行为不变。
    探测自身故障按不存在处理（fail-safe：宁可拒绝也不入死队）。
    """
    engine = getattr(websocket.app.state, "engine", None)
    session_store = getattr(engine, "session", None) if engine is not None else None
    if session_store is None:
        return None

    def _probe(session_id: str) -> bool:
        try:
            return bool(session_store.exists(str(session_id)))
        except Exception:  # noqa: BLE001 - 探测故障 = 无法核实存在性
            return False

    return _probe


async def _serve(websocket: WebSocket, media_session_id: str) -> None:
    """已鉴权连接：服务端回环代理（上行帧→终稿→TTS 下行）。

    - 上行二进制帧（16k PCM16）→ 累积并可选转发流式；
    - `input.commit` → 高精度终稿 → 下行 `input.final`/`turn.committed`；
    - `tts.request` → 本地 TTS → 下行二进制 `audio.playback`；
    - 断开即正常结束；不在鉴权失败路径建立任何副作用；
    - 会话登记被 take_over/DELETE 置 closed → 下一条消息回有界
      `error`（409 `session_closed`，契约枚举）后退出并清理（缺陷②）。
    """
    from llm_loop.realtime.realtime_session_runtime import RealtimeSessionRuntime

    factory = getattr(websocket.app.state, "realtime_transport_factory", _default_transport_factory)
    try:
        transport, transcription_url = factory()
    except Exception:  # noqa: BLE001 - 本地栈不可用：明确失败，不伪装
        await websocket.close(code=1011)
        return

    # P2-2：factory() 成功后、下方收包 try/finally 接管前是所有权空窗——
    # runtime 构造或起泵（create_task）若抛错，transport（含自有 httpx client）
    # 将无人关闭。兜底：先关 transport（与 finally 同口径 getattr+callable 判空）
    # 再以 1011 收口；正常路径零变化（关闭责任仍由既有 finally 负责）。
    try:
        runtime = RealtimeSessionRuntime(
            media_session_id=media_session_id,
            session_id=_session_id_for(websocket, media_session_id),
            transport=transport,
            transcription_url=transcription_url,
            send_text=websocket.send_text,
            send_binary=websocket.send_bytes,
            connection_epoch=_connection_epoch_for(websocket, media_session_id),
            keyframes=_keyframes_for(websocket, media_session_id),
            commit_sink=getattr(websocket.app.state, "realtime_commit_sink", None),
            session_probe=_session_probe_for(websocket),  # P2-9a：bind/入队前拒绝不存在的目标会话
        )
        import asyncio

        pump = asyncio.create_task(runtime.pump_deltas())  # 增量字幕下行（流式可选）
    except Exception:  # noqa: BLE001 - 兜底：不泄漏自有连接池，不伪装可用
        close = getattr(transport, "close", None)
        if callable(close):
            close()
        await websocket.close(code=1011)
        return
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
            if _record_closed(websocket, media_session_id):
                # 缺陷②：take_over/DELETE 已把本记录置 closed——旧写入者在
                # 下一条消息处立即退场（发契约枚举内的 409 session_closed 后
                # break），不再 ingest/commit，走既有 finally 清理，消除双 writer。
                await runtime.notify_session_closed()
                await websocket.close(code=1000)  # 正常关闭（模块既有约定值）
                break
            binary = message.get("bytes")
            if binary is not None:
                await runtime.handle_binary(binary)
                continue
            text = message.get("text")
            if text is not None:
                await runtime.handle_text(text)
    except Exception:  # noqa: BLE001 - 客户端断开/传输异常为正常结束路径
        return
    finally:
        runtime.stop()
        pump.cancel()
        close = getattr(transport, "close", None)
        if callable(close):
            close()


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
            # accept 前关闭：服务器以 HTTP 403 拒绝握手；reason 携带机器可读裁决
            # （如 S3-2 的 ws_requires_browser_session）。
            await websocket.close(code=close_code_for(rejection), reason=rejection.value)
            return
        await websocket.accept()
        await _serve(websocket, media_session_id)

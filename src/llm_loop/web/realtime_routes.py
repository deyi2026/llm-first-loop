"""实时媒体会话生命周期 REST 路由（`T-CONTRACT-6` / M1 装配）。

对应需求：`RTM-SES-01/02/03/06/07`、`RTM-LIF-01/02/03`、`RTM-IDN-03`、`RTM-SEC-06/08`、`RTM-CAP-03/04/11/14`。

接口（`DESIGN v1.3 §2.2.2-A`）：

- **A1** `POST /api/v1/realtime/sessions` — 建立媒体会话（401/403/409/429/503）
- **A2** `GET  /api/v1/realtime/sessions/{id}` — 四事实分离；越权不可读
- **A3** `DELETE /api/v1/realtime/sessions/{id}` — **幂等**；不等同取消 LFL 任务；缺用量 → `incomplete`

约束：不接收浏览器提交的任意远端 session / 长期 Key / 任意本机服务地址（`RTM-SEC-08`）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security.utils import get_authorization_scheme_param
from pydantic import BaseModel

from llm_loop.realtime.media_registry import MediaSessionRegistry, MediaWriterConflictError
from llm_loop.realtime.media_usage import UsageStatus
from llm_loop.web.auth import (
    SESSION_COOKIE_NAME,
    WebSessionStore,
    request_is_trusted_local,
    require_api_key,
    session_cookie_value,
    session_ttl_seconds,
)

router = APIRouter(prefix="/api/v1/realtime", tags=["realtime"])


class CreateRealtimeSessionBody(BaseModel):
    session_id: str
    audio_mode: str = "push_to_talk"
    enable_on_demand_vision: bool = False
    take_over: bool = False


def _registry(request: Request) -> MediaSessionRegistry:
    registry = getattr(request.app.state, "realtime_media_sessions", None)
    if not isinstance(registry, MediaSessionRegistry):
        raise HTTPException(status_code=503, detail="realtime media registry unavailable")
    return registry


def _owner_identity(request: Request) -> str:
    # S3-6 双名读取（__Host- 前缀名优先，旧名兼容）：secure 部署下会话 cookie
    # 已迁移前缀名，此处必须能读到，否则浏览器建会话将退化为 Bearer 身份。
    cookie = session_cookie_value(request.cookies)
    if cookie:
        return cookie
    scheme, token = get_authorization_scheme_param(request.headers.get("authorization", ""))
    return token if scheme.lower() == "bearer" and token else ""


def _create_owner_identity(request: Request) -> tuple[str, int | None]:
    """Bind an anonymous *direct loopback* client to a real revocable media owner.

    6a45f1741 语义移植（候选 S3-2/S3-6 架构下保留本地免登录语音 UX）：
    其他 Web 路由刻意放行受信 localhost 免登录；媒体 WS 仍需不可猜测 cookie
    做归属与重连，绝不用共享 local owner、绝不豁免 WS 身份校验。Web 重启
    后的陈旧 cookie 也不得继续当 owner。代理/公网请求在这里不会获得隐式会话。
    读取走 S3-6 双名（__Host- 优先），铸造仅在受信直连回环且现值无效时发生。
    """
    if not request_is_trusted_local(request):
        return _owner_identity(request), None
    store = getattr(request.app.state, "web_sessions", None)
    if not isinstance(store, WebSessionStore):
        raise HTTPException(status_code=503, detail="browser session store unavailable")
    cookie = session_cookie_value(request.cookies)
    if store.valid(cookie):
        return cookie, None
    ttl = session_ttl_seconds()
    token = store.create(ttl_seconds=ttl)
    return token, ttl


def _capability_profile(request: Request) -> dict:
    profile = getattr(request.app.state, "realtime_capability_profile", None)
    if isinstance(profile, dict):
        return profile
    return {
        "local_stack_version": "unknown",
        "models": {"streaming_asr": "unknown", "final_asr": "unknown", "tts": "unknown", "vad": "unknown"},
        "license": {},
        "recovery_mode": "local_rebuild_only",
        "evidence_level": "service_level_only",
    }


def _preflight(request: Request) -> None:
    """本地栈 preflight（CAP-14）。未装配或缺项 → 503（缺项降级，不伪装成功）。"""
    preflight = getattr(request.app.state, "realtime_preflight", None)
    if preflight is None:
        return
    ok = bool(preflight())
    if not ok:
        raise HTTPException(
            status_code=503, detail="local voice stack unavailable or format negotiation failed"
        )


@router.post("/sessions", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_api_key)])
def create_realtime_session(request: Request, response: Response, body: CreateRealtimeSessionBody) -> dict:
    if not body.session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    _preflight(request)
    registry = _registry(request)
    owner, minted_ttl = _create_owner_identity(request)
    if not owner:
        raise HTTPException(status_code=401, detail="unauthenticated")
    if registry.active_writer_conflict(body.session_id) and not body.take_over:
        if minted_ttl is not None:
            request.app.state.web_sessions.revoke(owner)
        raise HTTPException(status_code=409, detail="media session already has an active writer")
    try:
        record = registry.create(
            session_id=body.session_id,
            workspace_scope=body.session_id,
            owner_cookie=owner,
            audio_mode=body.audio_mode,
            enable_on_demand_vision=body.enable_on_demand_vision,
            take_over=body.take_over,
        )
    except MediaWriterConflictError as exc:
        # 预检查与 create 之间的竞态兜底：铸造出的 cookie 立即撤销（6a45f1741）。
        if minted_ttl is not None:
            request.app.state.web_sessions.revoke(owner)
        raise HTTPException(status_code=409, detail="media session already has an active writer") from exc
    if minted_ttl is not None:
        # Cookie 仅在 writer 成功准入后下发（6a45f1741）。
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=owner,
            max_age=minted_ttl,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"
    return {
        "media_session_id": record.media_session_id,
        "connection_epoch": record.connection_epoch,
        "capability_profile": _capability_profile(request),
        "transport_init": {"channel": "ws", "path": f"/api/v1/realtime/sessions/{record.media_session_id}/events"},
        "connection_state": record.session.state.value,
    }


@router.get("/sessions/{media_session_id}", dependencies=[Depends(require_api_key)])
def get_realtime_session(request: Request, media_session_id: str) -> dict:
    registry = _registry(request)
    record = registry.get(media_session_id, session_cookie=_owner_identity(request))
    if record is None:
        raise HTTPException(status_code=404, detail="media session not found")
    facts = record.session.facts()
    return {
        "media_session_id": record.media_session_id,
        "connection_state": facts.connection_state.value,
        "mic_enabled": facts.mic_enabled,
        "playback_state": facts.playback_state.value,
        "task_state": facts.task_state.value,
        "connection_epoch": facts.connection_epoch,
        "task_links": [],
        "cancel_stage": "idle",
        "last_confirmed_seq": 0,
        "capability_profile": _capability_profile(request),
        "service_level_baseline_id": getattr(request.app.state, "realtime_service_level_baseline_id", ""),
    }


@router.delete("/sessions/{media_session_id}", dependencies=[Depends(require_api_key)])
def delete_realtime_session(request: Request, media_session_id: str) -> dict:
    registry = _registry(request)
    record = registry.close(media_session_id, session_cookie=_owner_identity(request))
    if record is None:
        # 幂等：未知/越权不泄露存在性，按未找到处理
        raise HTTPException(status_code=404, detail="media session not found")
    # M3（RET-02）：会话清理 → 关键帧全部到期（回读明确失效；未装配视觉链则跳过）
    keyframes = getattr(request.app.state, "realtime_keyframes", None)
    if keyframes is not None:
        with_expire = getattr(keyframes, "close_session", None)
        if callable(with_expire):
            with_expire(media_session_id)
    return {
        "close_state": record.session.state.value,
        "task_state": record.session.facts().task_state.value,
        "usage": {"status": UsageStatus.INCOMPLETE.value, "note": "no final local usage collected"},
    }

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
    cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
    if cookie:
        return cookie
    scheme, token = get_authorization_scheme_param(request.headers.get("authorization", ""))
    return token if scheme.lower() == "bearer" and token else ""


def _create_owner_identity(request: Request) -> tuple[str, int | None]:
    """Bind an anonymous *direct loopback* client to a real revocable media owner.

    Other Web routes deliberately allow trusted localhost without login. The
    media WS still needs an unguessable cookie for ownership and reconnects;
    never use one shared ``local`` owner or waive the WebSocket identity check.
    A stale cookie from a Web restart must not be trusted as an owner either.
    Proxied/public requests never receive an implicit session here.
    """
    if not request_is_trusted_local(request):
        return _owner_identity(request), None
    store = getattr(request.app.state, "web_sessions", None)
    if not isinstance(store, WebSessionStore):
        raise HTTPException(status_code=503, detail="browser session store unavailable")
    cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
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
        if minted_ttl is not None:
            request.app.state.web_sessions.revoke(owner)
        raise HTTPException(status_code=409, detail="media session already has an active writer") from exc
    if minted_ttl is not None:
        # The cookie is only issued after a writer was successfully admitted.
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
    return {
        "close_state": record.session.state.value,
        "task_state": record.session.facts().task_state.value,
        "usage": {"status": UsageStatus.INCOMPLETE.value, "note": "no final local usage collected"},
    }

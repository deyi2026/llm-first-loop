"""受控端 HTTP 面（/peer/v1）：闸1 由 PeerAuthenticator 承担，业务委派给 PeerService。

不套 ``require_api_key``：控制面 API key 是浏览器/本机客户端凭证，远端 peer 用它属于
凭证混用；peer 请求只认四头 HMAC（DESIGN §5.8.3）。

端点（本切片）：
    GET  /peer/v1/manifest                     → manifest
    POST /peer/v1/tasks                        → receipt（202 表示仍在非终态）
    GET  /peer/v1/tasks/{task_id}/receipt       → receipt（仅限本节点自己的任务）
    GET  /peer/v1/artifacts/{ref:path}          ← ref 形如 ``v1/<sha256>``（拼回 artifact://）

产物授权：只有"本节点某任务的回执里引用过该 ref"才可取，避免知道 digest 就能拉别人的产物。
错误形状统一为 ``{reason_code, detail, suggested_next}``，reason_code ∈ 封闭集；
未知 task_id 用 ``params_schema_invalid`` + 404（集合内没有 task_not_found，不私造码）。
"""

from __future__ import annotations

import json
from functools import partial
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from llm_loop.peer.auth import PeerAuthenticator
from llm_loop.peer.errors import PeerError
from llm_loop.peer.service import PeerService
from llm_loop.peer.suggestions import REASON_SUGGESTIONS

_UNAUTHORIZED = frozenset(
    {"peer_bad_signature", "peer_unknown_node", "peer_stale_signature", "peer_replay_detected", "peer_not_paired"}
)
_NOT_FOUND = frozenset({"artifact_missing"})
_NON_TERMINAL = frozenset({"submitted", "admitted", "queued", "running", "blocked"})


def status_for(reason_code: str) -> int:
    if reason_code in _UNAUTHORIZED:
        return 401
    if reason_code in _NOT_FOUND:
        return 404
    if reason_code == "idempotency_conflict":
        return 409
    if reason_code == "params_schema_invalid":
        return 400
    return 403


def error_body(exc: PeerError) -> dict[str, Any]:
    body: dict[str, Any] = {"reason_code": exc.reason_code, "detail": exc.detail}
    suggestion = REASON_SUGGESTIONS.get(exc.reason_code)
    if suggestion:
        body["suggested_next"] = suggestion
    return body


def install_peer_error_handler(app: Any) -> None:
    """把 PeerError 映射成统一错误形状（独立 app 与挂载到主 app 时都要装）。"""

    @app.exception_handler(PeerError)
    async def _peer_error_handler(_request: Request, exc: PeerError) -> JSONResponse:  # noqa: ANN202
        return JSONResponse(status_code=status_for(exc.reason_code), content=error_body(exc))


def build_peer_router(*, service: PeerService, authenticator: PeerAuthenticator) -> APIRouter:
    router = APIRouter(prefix="/peer/v1", tags=["peer"])

    async def _authenticate(request: Request) -> str:
        body = await request.body()  # Starlette 会缓存，端点内再读不会二次消费
        return authenticator.verify_request(
            method=request.method,
            path=request.url.path,
            query=request.url.query,
            headers=request.headers,
            body=body,
        )

    @router.get("/manifest")
    async def get_manifest(request: Request) -> JSONResponse:
        await _authenticate(request)
        return JSONResponse(await run_in_threadpool(service.manifest))

    @router.post("/tasks")
    async def post_task(request: Request) -> JSONResponse:
        node_id = await _authenticate(request)
        raw = await request.body()
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            raise PeerError("params_schema_invalid", "body is not valid JSON") from None
        # requested_by 由服务端按认证身份写入：payload 同名字段可伪造，不能采信（T5 修）
        receipt = await run_in_threadpool(
            partial(service.submit, payload, requested_by=node_id)
        )
        status = 202 if receipt.get("state") in _NON_TERMINAL else 200
        return JSONResponse(status_code=status, content=receipt)

    @router.get("/tasks/{task_id}/receipt")
    async def get_receipt(task_id: str, request: Request) -> JSONResponse:
        node_id = await _authenticate(request)
        try:
            task = await run_in_threadpool(service.get_task_for, node_id, task_id)
        except PeerError as exc:
            return JSONResponse(status_code=404, content=error_body(exc))
        return JSONResponse(await run_in_threadpool(service.receipt, task))

    @router.get("/artifacts/{ref:path}")
    async def get_artifact(ref: str, request: Request) -> Response:
        node_id = await _authenticate(request)
        full_ref = f"artifact://{ref}"
        allowed = await run_in_threadpool(service.artifact_visible_to, node_id, full_ref)
        if not allowed:
            raise PeerError("artifact_missing", full_ref)
        try:
            data = await run_in_threadpool(service.read_artifact, full_ref)
        except PeerError as exc:
            if exc.reason_code == "artifact_digest_mismatch":
                # 篡改检测到就把引用它的任务收敛为 failed：不把已不可信的产物当成功
                await run_in_threadpool(service.quarantine_artifact, full_ref)
            raise
        return Response(content=data, media_type="application/octet-stream")

    return router


def create_peer_app(*, service: PeerService, authenticator: PeerAuthenticator) -> Any:
    """独立 peer app（测试与"单独端口/单独 unix socket"部署两用）。"""
    from fastapi import FastAPI

    app = FastAPI(title="lfl peer", docs_url=None, redoc_url=None, openapi_url=None)
    install_peer_error_handler(app)
    app.include_router(build_peer_router(service=service, authenticator=authenticator))
    return app

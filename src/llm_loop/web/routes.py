"""Web 路由（M36 薄壳适配器）。

仅经 request.app.state.engine 访问核心引擎，不复制核心逻辑。
对话路径唯一执行入口 = engine.run。
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from llm_loop.feedback.honesty import session_deleted_message, session_not_found_message

from .schemas import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    MessageItem,
    SessionListResponse,
    SessionMessagesResponse,
    SessionMetaItem,
    UploadRequest,
    UploadResponse,
)
from .upload_handlers import SUPPORTED_IMAGE_EXTS, file_ext, process_upload, validate_upload

logger = logging.getLogger(__name__)

router = APIRouter()

SERVICE_NAME = "llm-first-loop-web"
SERVICE_VERSION = "0.1.0"


class UTF8JSONResponse(JSONResponse):
    """强制 UTF-8 声明：content-type 带 charset=utf-8，杜绝中文按默认编码（如 GBK）误解码."""

    media_type = "application/json; charset=utf-8"


def _engine_from(request: Request) -> Any:
    """从 app.state 取单引擎实例（装配一次复用全部请求，不每请求重建）."""
    return request.app.state.engine


@router.post(
    "/api/v1/chat",
    response_model=ChatResponse,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def chat(payload: ChatRequest, request: Request) -> ChatResponse | Response:
    """同步对话端点：会话存在性检查 → engine.run 单一路径 → LoopResult 如实透传."""
    engine = _engine_from(request)

    if payload.session_id is not None:
        if not engine.session.exists(payload.session_id):
            return UTF8JSONResponse(
                status_code=404,
                content={
                    "error": "session_not_found",
                    "detail": session_not_found_message(payload.session_id),
                },
            )
        session_id = payload.session_id
    else:
        session_id = engine.session.create()

    try:
        result = engine.run(session_id, payload.message, model=payload.model)
    except Exception as exc:  # 如实反馈不静默降级（对齐 PREFERENCE_1）
        logger.exception("engine.run failed: session_id=%s", session_id)
        return UTF8JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "detail": f"[程序异常] 引擎执行失败（{type(exc).__name__}: {exc}）。",
            },
        )

    return ChatResponse(
        session_id=result.session_id,
        final_answer=result.final_answer,
        verification_note=result.verification_note,
        rounds=result.rounds,
        tool_calls=result.tool_calls,
        truncated=result.truncated,
    )


_STATIC_DIR = Path(__file__).resolve().parent / "static"


@router.get("/")
def root() -> Response:
    """服务根路径：返回 Web 聊天页面（M37 前端 UI）."""
    index = _STATIC_DIR / "index.html"
    if not index.exists():
        return JSONResponse(
            status_code=503,
            content={
                "error": "frontend_missing",
                "detail": "前端页面缺失（static/index.html 不存在），请检查安装完整性。",
            },
        )
    return HTMLResponse(content=index.read_text(encoding="utf-8"))


@router.get("/api/info")
def api_info() -> dict:
    """API 信息端点（JSON 服务信息，供程序/调试使用）."""
    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "endpoints": {
            "POST /api/v1/chat": "对话（body: {message, session_id?, model?}）",
            "GET /api/v1/sessions": "会话列表",
            "DELETE /api/v1/sessions/{session_id}?confirm=true": "删除会话（须确认）",
            "GET /api/v1/models": "可用模型列表",
            "GET /health": "健康检查",
            "GET /docs": "Swagger 交互文档",
        },
        "usage": "POST /api/v1/chat -H 'Content-Type: application/json' -d '{\"message\": \"你好\"}'",
    }


@router.get("/api/v1/models")
def list_models(request: Request) -> dict:
    """可用模型列表（供前端模型切换下拉，M50）.

    M50（design §六）三端一致性: 候选从 `engine.llm_pool.registry` 自动生成。
    - WEB_MODELS env 保留作**过滤子集**（若设置則只返回其交集; 未设置 = 注册表全量）
    - 零回归: 未配置注册表（仅 L0 单 provider 合成）时行为同现状（返回默认 + 常用档位）
    - current 如实呈现当前会话 override > 引擎默认装配（不伪造可用性）
    """
    import os as _os

    engine = _engine_from(request)
    default_model = getattr(getattr(engine, "llm", None), "model", None) or "deepseek-v4-flash"
    # M50: 从 session_map 取当前会话当前 override — sessions_id 不在查询参取中以当前不实现会话级（保留扩展位）
    current = default_model

    # M50: 从注册表生成候选
    registry = getattr(getattr(engine, "llm_pool", None), "registry", None)
    if registry is None:
        # 零回归回顾: 未注入 model_pool（test 场景）→ 行为同现状
        configured = _os.environ.get("WEB_MODELS", "").strip()
        names = (
            [m.strip() for m in configured.split(",") if m.strip()]
            if configured
            else ["deepseek-v4-flash", "deepseek-v4-pro"]
        )
        if current not in names:
            names.insert(0, current)
        return {"models": names, "current": current}

    # 拉取所有注册表内全限定 'provider/model'
    all_names: list[str] = []
    for pid, spec in registry.providers.items():
        for mid in spec.models:
            all_names.append(f"{pid}/{mid}")
    # WEB_MODELS 过滤子集（保留交集顺序, 避免跨 provider 冲突）
    configured = _os.environ.get("WEB_MODELS", "").strip()
    if configured:
        wanted = {m.strip() for m in configured.split(",") if m.strip()}
        names = [n for n in all_names if n in wanted]
    else:
        names = all_names
    # current 不在列表中 → 归一化为全限定名（前端下拉可匹配高亮）或插入首部
    # 修复（2026-08-11）: 裸名 current 已作为 provider/model 候选存在（如 deepseek/deepseek-v4-flash）
    # 时归一化为全限定名（避免下拉重复 + current 与候选项一致可高亮）
    if current not in names:
        matched = next((n for n in names if n.endswith(f"/{current}")), None)
        if matched:
            current = matched
        else:
            names.insert(0, current)
    return {"models": names, "current": current}


@router.get("/health")
def health() -> dict:
    """健康检查：纯服务层探活，不调用 LLM、不含凭证."""
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}


@router.get("/api/v1/sessions", response_model=SessionListResponse)
def list_sessions(request: Request, include_archived: bool = False) -> SessionListResponse:
    """会话列表：复用 engine.session.list_sessions，不遍历会话目录."""
    engine = _engine_from(request)
    metas = engine.session.list_sessions(include_archived=include_archived)
    items = [
        SessionMetaItem(
            session_id=m.session_id,
            title=m.title,
            created_at=m.created_at,
            updated_at=m.updated_at,
            message_count=m.message_count,
            status=m.status,
            last_message_preview=m.last_message_preview,
        )
        for m in metas
    ]
    return SessionListResponse(sessions=items, count=len(items))


@router.get(
    "/api/v1/sessions/{session_id}/messages",
    response_model=SessionMessagesResponse,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def get_session_messages(session_id: str, request: Request) -> SessionMessagesResponse | Response:
    """会话历史消息：刷新后恢复对话用（复用 engine.session.load，不复制存储逻辑）."""
    engine = _engine_from(request)
    if not engine.session.exists(session_id):
        return JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": session_not_found_message(session_id)},
        )
    try:
        session = engine.session.load(session_id)
    except Exception as exc:
        logger.exception("session load failed: session_id=%s", session_id)
        return JSONResponse(
            status_code=500,
            content={
                "error": "load_failed",
                "detail": f"[程序异常] 会话加载失败（{type(exc).__name__}: {exc}）。",
            },
        )
    messages = [MessageItem(role=m.role, content=m.content) for m in session.messages]
    return SessionMessagesResponse(session_id=session_id, messages=messages)


@router.delete(
    "/api/v1/sessions/{session_id}",
    response_model=None,
    responses={
        409: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def delete_session(session_id: str, request: Request, confirm: bool = False) -> Response:
    """会话删除：须 confirm=true 确认（对齐 CLI y/N 语义 + FR-P1-SES-04）."""
    if not confirm:
        return UTF8JSONResponse(
            status_code=409,
            content={
                "error": "confirm_required",
                "detail": "删除为不可逆操作，须带 confirm=true 确认。",
            },
        )

    engine = _engine_from(request)

    if not engine.session.exists(session_id):
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": session_not_found_message(session_id)},
        )

    try:
        engine.session.delete(session_id)
    except Exception as exc:
        logger.exception("session delete failed: session_id=%s", session_id)
        return UTF8JSONResponse(
            status_code=500,
            content={
                "error": "delete_failed",
                "detail": f"[程序异常] 会话删除失败（{type(exc).__name__}: {exc}）。",
            },
        )

    return UTF8JSONResponse(
        content={"status": "deleted", "detail": session_deleted_message(session_id)}
    )


@router.post(
    "/api/v1/upload",
    response_model=UploadResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def upload_file(payload: UploadRequest) -> UploadResponse | Response:
    """上传处理端点：base64 解码 → 校验 → 类型分发（文本/docx/PDF → 提取；图片 → 视觉识别）.

    不调用 engine.run（上传处理独立于核心对话链路，结果由前端注入对话上下文）。
    """
    import base64 as _b64

    try:
        data = _b64.b64decode(payload.data, validate=True)
    except Exception:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "invalid_base64", "detail": "文件数据 base64 解码失败。"},
        )

    err = validate_upload(payload.filename, data)
    if err:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "invalid_upload", "detail": err},
        )

    ext = file_ext(payload.filename)
    if ext in SUPPORTED_IMAGE_EXTS:
        # 图片 → 视觉识别（无 key 如实降级）
        from .vision import describe_image, vision_enabled

        if not vision_enabled():
            return UploadResponse(
                source_filename=payload.filename,
                content_type="image",
                status="degraded",
                result_text="",
                detail="视觉识别未配置（无 MINIMAX_API_KEY），图片无法识别。",
            )
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }.get(ext, "image/png")
        try:
            text = describe_image(data, mime=mime)
            return UploadResponse(
                source_filename=payload.filename,
                content_type="image",
                status="ok",
                result_text=text,
            )
        except Exception as exc:  # 识别失败如实反馈，不伪装成功
            logger.exception("image vision failed: %s", payload.filename)
            return UploadResponse(
                source_filename=payload.filename,
                content_type="image",
                status="degraded",
                detail=f"[程序异常] 图片识别失败（{type(exc).__name__}: {exc}）。",
            )

    # 文本/docx/PDF → 文档提取
    result = process_upload(payload.filename, data)
    return UploadResponse(
        source_filename=result.source_filename,
        content_type=result.content_type,
        status=result.status,
        result_text=result.result_text,
        detail=result.detail,
        truncated=result.truncated,
    )

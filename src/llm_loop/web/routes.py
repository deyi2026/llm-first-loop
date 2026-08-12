"""Web 路由（M36 薄壳适配器）。

仅经 request.app.state.engine 访问核心引擎，不复制核心逻辑。
对话路径唯一执行入口 = engine.run。
"""

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

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


_locks_guard = threading.Lock()
_LOCK_TIMEOUT_S = 30


def _get_session_lock(request: Request, session_id: str) -> threading.Lock | None:
    """T5.1: 获取会话级并发锁（未启用返回 None，向后兼容，spec.md 5.4.1）."""
    locks = getattr(request.app.state, "session_locks", None)
    if locks is None:
        return None
    with _locks_guard:
        if session_id not in locks:
            locks[session_id] = threading.Lock()
        return locks[session_id]


@router.post(
    "/api/v1/chat",
    response_model=ChatResponse,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def chat(
    payload: ChatRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> ChatResponse | Response:
    """同步对话端点：会话存在性检查 → engine.run 单一路径 → LoopResult 如实透传.

    M56：飞书来源会话在回复后经 background task 实时推送回飞书（不阻塞响应）。
    """
    engine = _engine_from(request)

    # T5.2: 超长输入前置校验（不创建会话、不写入审计、不消耗 LLM 配额，spec.md 5.4.1）
    input_max = getattr(engine.settings, "history_max_chars", 1000000)
    if len(payload.message) > input_max:
        return UTF8JSONResponse(
            status_code=413,
            content={
                "error": "input_too_long",
                "detail": f"输入超长（{len(payload.message)} > {input_max}），请缩短后重试或新建会话。",
            },
        )

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
        # 跨端共享当前会话：无 session_id 时复用共享当前（Web/飞书同一上下文）；
        # 无共享或共享会话已删则新建并设为共享当前
        shared = engine.session.get_shared_current()
        if shared is not None:
            session_id = shared
        else:
            session_id = engine.session.create()
            engine.session.set_shared_current(session_id)

    # T5.1: 会话级并发锁（同会话串行，不同会话并行，spec.md 5.4.1）
    lock = _get_session_lock(request, session_id)
    acquired = False
    if lock is not None and not lock.acquire(timeout=_LOCK_TIMEOUT_S):
        return UTF8JSONResponse(
            status_code=503,
            content={"error": "session_busy", "detail": "会话繁忙，请稍后重试"},
        )
    if lock is not None:
        acquired = True
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
    finally:
        if acquired and lock is not None:
            lock.release()

    # M56：飞书来源会话 → 后台推送用户消息 + 回答到飞书（fail-open 不阻断响应）
    try:
        sess = engine.session.load(session_id)
        channel = getattr(sess, "channel", "") or ""
    except Exception:  # noqa: BLE001 — 推送前置读取失败静默跳过
        channel = ""
    if channel.startswith("feishu:"):
        from .feishu_push import push_web_chat_to_feishu

        background_tasks.add_task(push_web_chat_to_feishu, channel, payload.message, result.final_answer)

    return ChatResponse(
        session_id=result.session_id,
        final_answer=result.final_answer,
        verification_note=result.verification_note,
        rounds=result.rounds,
        tool_calls=result.tool_calls,
        truncated=result.truncated,
        model_used=result.model_used,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
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
            "POST /api/v1/sessions/{session_id}/pin": "会话置顶/取消置顶（M56）",
            "GET /api/v1/models": "可用模型列表",
            "GET /api/v1/events": "SSE 会话更新事件流（M56 实时刷新）",
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
            pinned=m.pinned,      # M56: 置顶透传
            channel=m.channel,    # M56: 来源通道透传
        )
        for m in metas
    ]
    return SessionListResponse(sessions=items, count=len(items))


@router.get("/api/v1/session/current")
def get_shared_current(request: Request) -> JSONResponse:
    """跨端共享当前会话（Web 默认加载飞书当前会话，同一上下文）."""
    engine = _engine_from(request)
    current = engine.session.get_shared_current()
    return JSONResponse({"current": current})


@router.post(
    "/api/v1/sessions/{session_id}/pin",
    response_model=None,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def set_session_pin(session_id: str, request: Request, pinned: bool = False) -> Response:
    """会话置顶/取消置顶（M56，Web 端列表置顶优先）."""
    engine = _engine_from(request)
    if not engine.session.exists(session_id):
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": session_not_found_message(session_id)},
        )
    try:
        ok = engine.session.set_pinned(session_id, pinned)
    except Exception as exc:
        logger.exception("session pin failed: session_id=%s", session_id)
        return UTF8JSONResponse(
            status_code=500,
            content={
                "error": "pin_failed",
                "detail": f"[程序异常] 会话置顶失败（{type(exc).__name__}: {exc}）。",
            },
        )
    if not ok:
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": session_not_found_message(session_id)},
        )
    return UTF8JSONResponse(content={"status": "ok", "session_id": session_id, "pinned": pinned})


# ── M56：SSE 会话更新事件（Web 端实时刷新，轮询共享会话目录零新依赖）──


def _sessions_fingerprint(sessions_dir: str | Path) -> str:
    """会话目录轻量指纹：文件数 + 最新文件 mtime + 文件名（任一变化即事件）."""
    try:
        files = [p for p in Path(sessions_dir).glob("*.json")]
        if not files:
            return "0"
        newest = max(files, key=lambda p: p.stat().st_mtime)
        return f"{len(files)}:{newest.stat().st_mtime_ns}:{newest.name}"
    except OSError:
        return "err"


@router.get("/api/v1/events")
async def stream_session_events(request: Request) -> StreamingResponse:
    """SSE 会话更新事件流（M56：Web 端实时刷新）.

    轮询共享会话目录指纹（文件数 + 最新 mtime），变化即推送 sessions_updated 事件；
    Web 前端收到后刷新会话列表与当前会话消息。零新依赖（同进程内 asyncio 轮询）。
    """
    engine = _engine_from(request)
    sessions_dir = getattr(getattr(engine, "settings", None), "sessions_dir", None) or "./data/sessions"
    initial = _sessions_fingerprint(sessions_dir)

    async def gen():
        nonlocal initial
        yield "data: " + json.dumps({"type": "connected", "ts": asyncio.get_event_loop().time()}) + "\n\n"
        while True:
            try:
                if await request.is_disconnected():
                    break
            except Exception:  # noqa: BLE001 — 断开检测异常按断开处理
                break
            await asyncio.sleep(1.5)
            current = _sessions_fingerprint(sessions_dir)
            if current != initial and current != "err":
                initial = current
                yield "data: " + json.dumps({"type": "sessions_updated"}) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


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
    messages = [MessageItem(role=m.role, content=m.content, tool_call_id=m.tool_call_id) for m in session.messages]
    return SessionMessagesResponse(session_id=session_id, messages=messages)


@router.get("/api/v1/sessions/{session_id}/archive/{tool_call_id}", response_model=None)
def get_archived_tool_output(session_id: str, tool_call_id: str, request: Request) -> Response:
    """M52: 分层截断工具回执的完整原文（web 端"展开原文"数据源，按 tool_call_id 精确定位）."""
    engine = _engine_from(request)
    if not engine.session.exists(session_id):
        return JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": session_not_found_message(session_id)},
        )
    store = getattr(engine, "archive", None)
    if store is None:
        return JSONResponse(
            status_code=404,
            content={"error": "archive_unavailable", "detail": "压缩档案不可用（未配置），无法取回原文。"},
        )
    try:
        entry = store.get_by_tool_call_id(session_id, tool_call_id)
    except Exception as exc:  # fail-open 如实反馈（RULE-AI-04）
        logger.exception("archive lookup failed: %s/%s", session_id, tool_call_id)
        return JSONResponse(
            status_code=500,
            content={"error": "archive_lookup_failed", "detail": f"[程序异常] 档案检索失败（{type(exc).__name__}: {exc}）。"},
        )
    if entry is None:
        return JSONResponse(
            status_code=404,
            content={"error": "archive_not_found", "detail": "该工具回执未归档（可能未超长或归档降级），无完整原文可取。"},
        )
    return JSONResponse(
        content={
            "tool_call_id": tool_call_id,
            "tool_name": entry.get("tool_name") or "",
            "ts": entry.get("ts") or "",
            "chars": entry.get("chars") or len(entry.get("content", "")),
            "content": entry.get("content", ""),
        }
    )


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

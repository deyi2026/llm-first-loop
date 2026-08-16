"""Web 路由（M36 薄壳适配器）。

仅经 request.app.state.engine 访问核心引擎，不复制核心逻辑。
对话路径唯一执行入口 = engine.run。
"""

import asyncio
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from llm_loop.feedback.honesty import session_deleted_message, session_not_found_message
from llm_loop.workspace.store import workspace_key

from .schemas import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    FeedbackRequest,
    MessageItem,
    SessionListResponse,
    SessionMessagesResponse,
    SessionMetaItem,
    UploadRequest,
    UploadResponse,
    WorkspaceRequest,
    WorkspaceSwitchRequest,
)
from .upload_handlers import (
    SUPPORTED_IMAGE_EXTS,
    file_ext,
    process_upload,
    validate_upload,
    validate_upload_b64_size,
)

logger = logging.getLogger(__name__)

router = APIRouter()

SERVICE_NAME = "llm-first-loop-web"
SERVICE_VERSION = "0.6.6"  # T7: 语义化版本（与 pyproject 同步；git tag v0.5.2）


class UTF8JSONResponse(JSONResponse):
    """强制 UTF-8 声明：content-type 带 charset=utf-8，杜绝中文按默认编码（如 GBK）误解码."""

    media_type = "application/json; charset=utf-8"


def _engine_from(request: Request) -> Any:
    """从 app.state 取单引擎实例（装配一次复用全部请求，不每请求重建）."""
    return request.app.state.engine


_locks_guard = threading.Lock()
_LOCK_TIMEOUT_S = 30
# P2-3(2026-08-15，审计发现)：会话锁表上限（LRU 淘汰空闲锁；dict 保序即插入序）
_SESSION_LOCKS_MAX = 1024


def _get_session_lock(request: Request, session_id: str) -> threading.Lock | None:
    """T5.1: 获取会话级并发锁（未启用返回 None，向后兼容，spec.md 5.4.1）.

    P2-3: LRU 上限 _SESSION_LOCKS_MAX——触碰移至末尾，超限时淘汰最旧空闲锁
    （locked 的跳过，防互斥失效；极端全 locked 时允许超限增长并 debug 如实记录）。
    """
    locks = getattr(request.app.state, "session_locks", None)
    if locks is None:
        return None
    with _locks_guard:
        lock = locks.get(session_id)
        if lock is not None:
            locks[session_id] = locks.pop(session_id)  # 移至末尾（LRU 触碰）
            return lock
        lock = threading.Lock()
        locks[session_id] = lock
        while len(locks) > _SESSION_LOCKS_MAX:
            oldest_sid = next(iter(locks))
            oldest = locks[oldest_sid]
            if oldest.locked():
                # 找下一个空闲候选；全部持锁则容忍超限（如实记录，不破坏互斥）
                idle = next((s for s, lk in locks.items() if not lk.locked()), None)
                if idle is None:
                    logger.debug("会话锁表超限且全部持锁，容忍增长: %d", len(locks))
                    break
                oldest_sid = idle
            del locks[oldest_sid]
        return lock


def _resolve_session_id_locked(engine: Any, request: Request, explicit_sid: str | None) -> str:
    """P2-3: 会话解析原子段（模块级 guard 内完成，闭合"无 sid 并发首聊双建会话"竞态）.

    guard 内：无 sid 时 get_shared→create→set_shared 原子完成（并发请求必共享同一会话）；
    锁对象获取由调用方随后经 `_get_session_lock`（幂等落表 + LRU）完成。
    """
    del request  # 解析只涉引擎会话存储；锁表由 _get_session_lock 管
    with _locks_guard:
        if explicit_sid is not None:
            return explicit_sid
        # 跨端共享当前会话：无 session_id 时复用共享当前（Web/飞书同一上下文）；
        # 无共享或共享会话已删则新建并设为共享当前
        shared = engine.session.get_shared_current()
        if shared is not None:
            return shared
        session_id = engine.session.create()
        engine.session.set_shared_current(session_id)
        return session_id


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
    input_max = getattr(engine.settings, "history_max_chars", 100000)
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
        # P2-3: 无 sid 解析（复用共享/新建+设共享）在模块级 guard 内原子完成
        session_id = _resolve_session_id_locked(engine, request, None)

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
    except Exception as exc:  # noqa: BLE001 — 推送前置读取失败静默跳过（fail-open）
        logger.debug("飞书推送前置读取失败，跳过推送（fail-open）: %s", exc)
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
        reasoning_content=result.reasoning_content,  # P1-1: 非流式路径透传思考链
    )


def _sse(event_type: str, data: Any) -> str:
    """SSE 事件序列化（data: {json}，design §2.2.2.3）."""
    return f"data: {json.dumps({'type': event_type, 'data': data}, ensure_ascii=False)}\n\n"


@router.post("/api/v1/chat/stream")
def chat_stream(
    payload: ChatRequest,
    request: Request,
) -> Response:
    """真流式对话端点（SSE）：answer_delta* → done（九字段）| error.

    真流式仅作用于最终回答轮（中间工具轮无可见文本、同步等待）；终态 done 携带完整
    ChatResponse 九字段，与非流式 POST /api/v1/chat 内容等价（spec 5.2 规则 4）。
    """
    engine = _engine_from(request)

    # 超长输入前置校验（与 chat 端点一致，不创建会话、不消耗 LLM 配额）
    input_max = getattr(engine.settings, "history_max_chars", 100000)
    if len(payload.message) > input_max:
        return UTF8JSONResponse(
            status_code=413,
            content={
                "error": "input_too_long",
                "detail": f"输入超长（{len(payload.message)} > {input_max}），请缩短后重试或新建会话。",
            },
        )

    # 会话存在性检查（与 chat 端点一致）
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
        # P2-3: 无 sid 解析在模块级 guard 内原子完成（与 chat 端点同一事务语义）
        session_id = _resolve_session_id_locked(engine, request, None)

    def event_stream():
        lock = _get_session_lock(request, session_id)
        acquired = False
        if lock is not None and not lock.acquire(timeout=_LOCK_TIMEOUT_S):
            yield _sse("error", {"error": "session_busy", "detail": "会话繁忙，请稍后重试"})
            return
        if lock is not None:
            acquired = True
        try:
            it = engine.run_stream(session_id, payload.message, model=payload.model)
            while True:
                try:
                    delta = next(it)
                    # P1-1: text/reasoning 分片独立 yield（并行互不阻塞，spec 4.1.1）
                    # P2-1: tool_round 工具轮次进展独立 yield（三事件并行互不阻塞）
                    if delta.text:
                        yield _sse("answer_delta", {"data": delta.text})
                    if delta.reasoning:
                        yield _sse("reasoning_delta", {"data": delta.reasoning})
                    if delta.tool_round is not None:
                        yield _sse(
                            "tool_round",
                            {
                                "tool_name": delta.tool_round.tool_name,
                                "round_index": delta.tool_round.round_index,
                                "args_summary": delta.tool_round.args_summary,
                                "tool_call_id": delta.tool_round.tool_call_id,
                            },
                        )
                except StopIteration as exc:
                    result = exc.value
                    break
        except Exception as exc:  # noqa: BLE001 — 引擎异常如实反馈（已生成分片不撤回）
            logger.exception("engine.run_stream failed: session_id=%s", session_id)
            yield _sse(
                "error",
                {
                    "error": "internal_error",
                    "detail": f"[程序异常] 引擎执行失败（{type(exc).__name__}: {exc}）。",
                },
            )
            return
        finally:
            if acquired and lock is not None:
                lock.release()

        yield _sse(
            "done",
            {
                "session_id": result.session_id,
                "final_answer": result.final_answer,
                "verification_note": result.verification_note,
                "rounds": result.rounds,
                "tool_calls": result.tool_calls,
                "truncated": result.truncated,
                "model_used": result.model_used,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "reasoning_content": result.reasoning_content,  # P1-1: 终态兜底
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
    # M50: current 反映当前共享会话的 model_override（若有），否则回退默认装配。
    # 修复：Web 前端 state.model 初始值跟随此值，避免 per-call model 遮蔽 switch_model 会话 override。
    current = default_model
    try:
        sid = engine.session.get_shared_current()
        if sid and engine.session.exists(sid):
            sess = engine.session.load(sid)
            if sess.model_override:
                current = sess.model_override
    except Exception:  # noqa: BLE001 - 读取 override 失败不阻断（回退默认，如实不伪造）
        pass

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


@router.get("/api/v1/interop/messages")
def list_interop_messages(request: Request) -> dict:
    """协调通道消息（只读，不触发 run）——web 端展示给用户看.

    读 data/interop/{lfl_to_dsh,dsh_to_lfl}/pending/ 的 JSON 消息（协议见 INTEROP.md），
    返回两个方向的待处理消息摘要。只读文件系统，不触发 agent run、不占会话锁。
    """
    del request  # 纯文件读取，无引擎依赖
    base = Path(os.environ.get("LFL_DATA_DIR", "data")) / "interop"
    result: dict[str, list[dict]] = {"lfl_to_dsh": [], "dsh_to_lfl": []}
    for direction in ("lfl_to_dsh", "dsh_to_lfl"):
        pdir = base / direction / "pending"
        if not pdir.is_dir():
            continue
        for f in sorted(pdir.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue  # 格式坏/读失败 → 跳过（fail-open）
            result[direction].append(
                {
                    "id": d.get("id", f.stem),
                    "from": d.get("from", ""),
                    "to": d.get("to", ""),
                    "ts": d.get("ts", ""),
                    "topic": d.get("topic", ""),
                    "body": str(d.get("body", ""))[:300],
                }
            )
    return result

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


@router.post(
    "/api/v1/sessions/{session_id}/fork",
    response_model=None,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def fork_session_endpoint(
    session_id: str,
    request: Request,
    fork_point: int | None = None,
    summary: str = "",
) -> Response:
    """会话 fork（D3：事件日志物理复制继承 + session JSON 双轨）."""
    from llm_loop.event_log.fork import fork_session

    engine = _engine_from(request)
    if not engine.session.exists(session_id):
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": session_not_found_message(session_id)},
        )
    event_store = getattr(engine.session, "_event_store", None)
    try:
        report = fork_session(
            event_store,
            engine.session,
            session_id,
            fork_point=fork_point,
            branch_summary=summary,
        )
    except Exception as exc:
        logger.exception("session fork failed: session_id=%s", session_id)
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "fork_failed", "detail": f"[程序异常] fork 失败（{type(exc).__name__}: {exc}）"},
        )
    if not report.success:
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "fork_failed", "detail": report.error},
        )
    return UTF8JSONResponse(
        content={
            "status": "ok",
            "new_session_id": report.new_session_id,
            "source_session_id": report.source_session_id,
            "fork_point": report.fork_point,
            "inherited_event_count": report.inherited_event_count,
            "elapsed_ms": report.elapsed_ms,
        }
    )


# ── 2026-08-15：消息反馈（对齐 DSH ui-message-feedback；JSONL 追加审计，不侵入会话） ──

@router.post(
    "/api/v1/sessions/{session_id}/feedback",
    response_model=None,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def submit_message_feedback(
    session_id: str,
    payload: FeedbackRequest,
    request: Request,
) -> Response:
    """消息反馈：追加 data/feedback.jsonl（session_id/下标/up-down/note/ts）.

    仅审计记录，不修改会话内容；index 越界/非法 feedback 如实 400。
    """
    engine = _engine_from(request)
    if not engine.session.exists(session_id):
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": session_not_found_message(session_id)},
        )
    if payload.feedback not in ("up", "down"):
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "invalid_feedback", "detail": "feedback 仅支持 up / down。"},
        )
    try:
        sess = engine.session.load(session_id)
        if payload.message_index >= len(sess.messages):
            return UTF8JSONResponse(
                status_code=400,
                content={
                    "error": "index_out_of_range",
                    "detail": f"message_index {payload.message_index} 超出会话消息数 {len(sess.messages)}。",
                },
            )
        data_dir = Path(getattr(engine.settings, "data_dir", "./data"))
        feedback_file = data_dir / "feedback.jsonl"
        with open(feedback_file, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "ts": __import__("time").time(),
                        "session_id": session_id,
                        "message_index": payload.message_index,
                        "role": sess.messages[payload.message_index].role,
                        "feedback": payload.feedback,
                        "note": payload.note,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception as exc:  # noqa: BLE001 — 反馈失败如实 500（不影响主链路）
        logger.exception("message feedback failed: session=%s", session_id)
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "feedback_failed", "detail": f"[程序异常] 反馈记录失败（{type(exc).__name__}: {exc}）"},
        )
    return UTF8JSONResponse(content={"status": "ok", "session_id": session_id})


# ── M56：SSE 会话更新事件（Web 端实时刷新，轮询共享会话目录零新依赖）──


def _sse_event(name: str, payload: dict) -> str:
    """SSE 命名事件帧（2026-08-15 修复）：必须带 `event: <type>` 行浏览器才按命名事件分发。

    此前只发 `data: {"type": ...}` → 浏览器按默认 message 处理，前端
    addEventListener("sessions_updated") 永不触发（Web 端必须手动刷新）。
    """
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


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

    2026-08-15 修复：SSE 命名事件必须带 `event: <type>` 行——此前只发
    `data: {"type": ...}`，浏览器按默认 message 事件处理，前端
    addEventListener("sessions_updated") 永不触发（Web 端必须手动刷新才能看到
    飞书消息）。现补 `event:` 行（data 内 type 字段保留向后兼容），并加 20s
    keepalive 注释行防中间层/浏览器超时掐断长连接。
    """
    engine = _engine_from(request)
    sessions_dir = getattr(getattr(engine, "settings", None), "sessions_dir", None) or "./data/sessions"
    initial = _sessions_fingerprint(sessions_dir)

    async def gen():
        nonlocal initial
        loop = asyncio.get_event_loop()
        yield _sse_event("connected", {"type": "connected", "ts": loop.time()})
        last_beat = loop.time()
        while True:
            try:
                if await request.is_disconnected():
                    break
            except Exception:  # noqa: BLE001 — 断开检测异常按断开处理
                break
            await asyncio.sleep(1.5)
            now = loop.time()
            # keepalive：20s 无事件也保活（注释行，浏览器忽略内容仅感知存活）
            if now - last_beat >= 20.0:
                last_beat = now
                yield ": keepalive\n\n"
                continue
            current = _sessions_fingerprint(sessions_dir)
            if current != initial and current != "err":
                initial = current
                last_beat = now
                yield _sse_event("sessions_updated", {"type": "sessions_updated"})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get(
    "/api/v1/sessions/{session_id}/messages",
    response_model=SessionMessagesResponse,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def get_session_messages(
    session_id: str,
    request: Request,
    limit: int | None = None,
    offset: int = 0,
) -> SessionMessagesResponse | Response:
    """会话历史消息：刷新后恢复对话用（复用 engine.session.load，不复制存储逻辑）.

    D2: 可选 limit/offset 分页（offset = 跳过最近 N 条，返回更早消息）；不传 limit 全量返回。
    """
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
    messages = [
        MessageItem(
            role=m.role,
            content=m.content,
            tool_call_id=m.tool_call_id,
            reasoning_content=getattr(m, "reasoning_content", None),  # P1-1: 历史思考链透传
            model_used=getattr(m, "model_used", ""),  # M51: 历史模型标签透传（页脚）
            tokens_in=getattr(m, "tokens_in", 0),  # M52: 历史 token 消耗透传
            tokens_out=getattr(m, "tokens_out", 0),  # M52
            tool_calls=getattr(m, "tool_calls", None),  # 工具声明透传（历史出产物/正文链接）
        )
        for m in session.messages
    ]
    total = len(messages)
    if limit is not None:
        start = max(0, total - offset - limit)
        end = total - offset
        page = messages[start:end]
        return SessionMessagesResponse(
            session_id=session_id, messages=page, has_more=start > 0, total=total
        )
    return SessionMessagesResponse(session_id=session_id, messages=messages, total=total)


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
def upload_file(payload: UploadRequest, request: Request) -> UploadResponse | Response:
    """上传处理端点：base64 解码 → 校验 → 类型分发（文本/docx/PDF → 提取；图片 → 视觉识别）.

    不调用 engine.run（上传处理独立于核心对话链路，结果由前端注入对话上下文）。
    request: 注入以取引擎 settings（vision provider 后端注册表来源）。
    """
    engine = _engine_from(request)
    import base64 as _b64

    # P2-2(2026-08-15)：base64 体积前置检查（≈4/3 原始体积），超限 413 不解码
    size_err = validate_upload_b64_size(payload.data)
    if size_err:
        return UTF8JSONResponse(
            status_code=413,
            content={"error": "upload_too_large", "detail": size_err},
        )

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

        if not vision_enabled(settings=getattr(engine, "settings", None)):
            return UploadResponse(
                source_filename=payload.filename,
                content_type="image",
                status="degraded",
                result_text="",
                detail="图片识别不可用（无视觉模型/工具），图片未识别且未包含在请求中。",
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
            text = describe_image(data, mime=mime, settings=getattr(engine, "settings", None))
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
                detail=(
                    f"[程序异常] 图片识别失败（{type(exc).__name__}: {exc}）。"
                    "图片内容**未包含**在本次请求中——请勿让 LLM 猜测图片内容。"
                    "可设置 WEB_VISION_MODEL 指定 provider/model（如 kimi/k3），"
                    "或改用文本通道。"
                ),
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


# ── 出产物文件预览（Web V2 对齐 DSH deliverables：编辑的文件可点击打开） ──
_PREVIEW_ROOT = Path(__file__).resolve().parents[3]  # 项目根（与 _ui_v2_dir 同模式）
_PREVIEW_MAX_CHARS = 200_000  # 预览上限（超限截断提示，不整读）


@router.get("/api/v1/files/preview")
def preview_file(request: Request, path: str) -> Response:
    """只读文件预览（出产物点击打开）.

    安全边界：拒绝绝对路径与越界路径（resolve 后必须仍在项目根内）；
    仅限普通文件；大小上限截断（返回 truncated 标记如实提示）。
    """
    if not path:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "invalid_path", "detail": "缺少 path。"},
        )
    # 工作区跟随: 预览根 = 当前工作区根（无工作区 → 仓库根兜底）
    engine = _engine_from(request)
    root = Path(getattr(engine, "workspace_root", "") or _PREVIEW_ROOT)
    # 相对路径基于工作区根；绝对路径亦接受（resolve 后必须仍在根内，越界拒绝）
    raw = Path(path)
    target = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if not target.is_relative_to(root.resolve()):
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "out_of_bounds", "detail": "路径越出项目根，已拒绝。"},
        )
    # 裸文件名兜底（正文常引用 `development_methodology.md` 这类无目录前缀的文件名）：
    # 根下直接解析失败时，在工作区常见目录内按 basename 唯一匹配（多命中 → 409 歧义
    # 提示，宁可不猜不错开；防误开原则）。
    if not target.is_file() and not raw.is_absolute() and "/" not in path and "\\" not in path:
        try:
            candidates = [
                p.resolve()
                for base in ("docs", "src", "tests", "scripts", "skills", "webui")
                for p in (root / base).rglob(path)
                if p.is_file()
            ]
        except OSError:
            candidates = []
        if len(candidates) == 1:
            target = candidates[0]
        elif len(candidates) > 1:
            return UTF8JSONResponse(
                status_code=409,
                content={
                    "error": "ambiguous_path",
                    "detail": f"文件名 {path} 在工作区内有 {len(candidates)} 处，请用完整路径。",
                },
            )
    if not target.is_file():
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "file_not_found", "detail": f"文件不存在: {path}"},
        )
    try:
        raw = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.exception("file preview read failed: path=%s", path)
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "read_failed", "detail": f"[程序异常] 读取失败（{type(exc).__name__}）。"},
        )
    truncated = len(raw) > _PREVIEW_MAX_CHARS
    return UTF8JSONResponse(
        content={
            "path": path,
            "size": len(raw),
            "truncated": truncated,
            "content": raw[:_PREVIEW_MAX_CHARS] if truncated else raw,
        }
    )


# ── 工作区管理（对齐 DSH Workspace：注册/切换/注销；会话按工作区分区） ──
@router.get("/api/v1/workspaces")
def list_workspaces(request: Request) -> JSONResponse:
    """工作区列表 + 当前工作区（web 端选择器数据源）."""
    engine = _engine_from(request)
    store = getattr(engine, "workspace_store", None)
    if store is None:
        return JSONResponse({"workspaces": [], "current": ""})
    current = store.get_current()
    return JSONResponse(
        {
            "workspaces": [{"id": w.id, "path": w.path} for w in store.list()],
            "current": current.id if current else "",
        }
    )


@router.get("/api/v1/workspaces/{workspace_id}/sessions")
def list_workspace_sessions(workspace_id: str, request: Request) -> JSONResponse:
    """按工作区列会话（侧栏工作区分组展示；不改当前工作区）."""
    engine = _engine_from(request)
    store = getattr(engine, "workspace_store", None)
    if store is None:
        return JSONResponse({"sessions": [], "count": 0})
    ws = store.get(workspace_id)
    if ws is None:
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "workspace_not_found", "detail": f"工作区未注册: {workspace_id}"},
        )
    metas = engine.session.list_sessions_in(
        Path(engine.settings.sessions_dir) / workspace_key(ws.path)
    )
    return JSONResponse(
        {
            "sessions": [
                {
                    "session_id": m.session_id,
                    "title": m.title,
                    "updated_at": m.updated_at,
                    "message_count": m.message_count,
                    "status": m.status,
                    "last_message_preview": m.last_message_preview,
                    "pinned": m.pinned,
                    "channel": m.channel,
                }
                for m in metas
            ],
            "count": len(metas),
        }
    )


@router.post("/api/v1/workspaces")
def register_workspace(request: Request, body: WorkspaceRequest) -> Response:
    """注册并切换工作区（Open 语义：注册即采用）."""
    engine = _engine_from(request)
    store = getattr(engine, "workspace_store", None)
    if store is None:
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "workspace_unavailable", "detail": "工作区存储未装配。"},
        )
    path = body.path.strip()
    try:
        ws = store.register(path)
        store.switch(ws.id)
        engine.set_workspace(ws.path)
    except ValueError as exc:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "invalid_workspace", "detail": str(exc)},
        )
    return JSONResponse({"id": ws.id, "path": ws.path, "current": True})


@router.post("/api/v1/workspaces/switch")
def switch_workspace(request: Request, body: WorkspaceSwitchRequest) -> Response:
    """切换当前工作区（会话列表/工具根/文件预览根跟随）."""
    engine = _engine_from(request)
    store = getattr(engine, "workspace_store", None)
    if store is None:
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "workspace_unavailable", "detail": "工作区存储未装配。"},
        )
    try:
        ws = store.switch(body.id)
        engine.set_workspace(ws.path)
    except ValueError as exc:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "invalid_workspace", "detail": str(exc)},
        )
    return JSONResponse({"id": ws.id, "path": ws.path, "current": True})


@router.delete("/api/v1/workspaces/{workspace_id}")
def remove_workspace(workspace_id: str, request: Request) -> Response:
    """注销工作区（不删会话数据；当前工作区不可注销）."""
    engine = _engine_from(request)
    store = getattr(engine, "workspace_store", None)
    if store is None:
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "workspace_unavailable", "detail": "工作区存储未装配。"},
        )
    if not store.remove(workspace_id):
        return UTF8JSONResponse(
            status_code=409,
            content={
                "error": "workspace_conflict",
                "detail": "注销失败：当前工作区不可注销，或工作区不存在。",
            },
        )
    return JSONResponse({"removed": True})


# ── 目录浏览（对齐 DSH directory-browser：应用内选择工作区目录，替代输入路径） ──
@router.get("/api/v1/fs/dirs")
def list_dirs(request: Request, path: str = "") -> Response:
    """列出目录的子目录（工作区目录浏览器数据源）.

    默认从家目录开始；导航任意绝对路径（本地工具）；不存在/权限不足如实 4xx。
    """
    raw = (path or "").strip()
    try:
        target = Path(raw).expanduser() if raw else Path.home()
        target = target.resolve()
    except OSError as exc:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "invalid_path", "detail": f"路径解析失败: {exc}"},
        )
    if not target.is_dir():
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "dir_not_found", "detail": f"目录不存在: {target}"},
        )
    try:
        children = sorted(
            (p for p in target.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name.lower(),
        )
    except OSError as exc:
        return UTF8JSONResponse(
            status_code=403,
            content={"error": "dir_unreadable", "detail": f"目录不可读: {exc}"},
        )
    return JSONResponse(
        {
            "path": str(target),
            "parent": str(target.parent) if target != target.parent else None,
            "dirs": [p.name for p in children[:500]],  # 单层上限防超载
        }
    )

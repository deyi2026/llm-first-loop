"""Web 路由（M36 薄壳适配器）。

仅经 request.app.state.engine 访问核心引擎，不复制核心逻辑。
对话路径唯一执行入口 = engine.run。
"""

import asyncio
import json
import logging
import os
import queue
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)

from llm_loop.core.loop.runner import SessionBusyError
from llm_loop.core.session import SessionExternalResourceBusyError, SessionMutationBusyError
from llm_loop.feedback.honesty import (
    append_feedback,
    session_deleted_message,
    session_not_found_message,
)
from llm_loop.workspace.store import (
    WorkspaceBusyError,
    WorkspaceChangedError,
    WorkspacePathUnavailableError,
    WorkspacePersistenceError,
)

from .attachments import AttachmentError, AttachmentStore
from .attachments import workspace_scope as attachment_workspace_scope
from .schemas import (
    ChatCancelRequest,
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    EvolutionReviewRequest,
    FeedbackRequest,
    MessageItem,
    SessionListResponse,
    SessionMessagesResponse,
    SessionMetaItem,
    UploadRequest,
    UploadResponse,
    WorkspaceAttachmentImportRequest,
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


def _attachment_store(engine: Any) -> AttachmentStore:
    data_dir = getattr(getattr(engine, "settings", None), "data_dir", "./data")
    return AttachmentStore(data_dir)


def _current_attachment_workspace_scope(engine: Any) -> str:
    return attachment_workspace_scope(getattr(engine, "workspace_root", "") or None)


def _resolve_workspace_file(engine: Any, raw_path: str) -> Path | None:
    """Resolve one ordinary file inside the current workspace (no escape)."""
    root = (
        Path(getattr(engine, "workspace_root", "") or Path(__file__).resolve().parents[3])
        .expanduser()
        .resolve()
    )
    try:
        raw = Path(str(raw_path or "")).expanduser()
        target = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    except OSError:
        return None
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target


def _resolve_chat_attachment_facts(
    engine: Any, refs: list[Any], *, workspace_scope: str
) -> list[dict[str, Any]]:
    if not refs:
        return []
    store = _attachment_store(engine)
    facts: list[dict[str, Any]] = []
    for item in refs:
        ref = str(getattr(item, "ref", "") or "")
        record = store.resolve(ref, workspace_scope=workspace_scope, verify_content=True)
        facts.append(record.public_facts())
    return facts


def _persist_upload_response(
    engine: Any,
    *,
    workspace_scope: str,
    filename: str,
    data: bytes,
    response: UploadResponse,
    extracted_text: str | None = None,
    extraction_complete: bool | None = None,
    extraction_kind: str = "",
    page_count: int | None = None,
    pages_extracted: int | None = None,
) -> UploadResponse:
    excerpt_kind = ""
    if response.result_text:
        excerpt_kind = "vision_text" if response.content_type == "image" else "extracted_text"
    exact_text = response.result_text if extracted_text is None else str(extracted_text or "")
    if extraction_complete is None:
        # Vision text is a derived representation of durable image bytes, not a claim
        # that every source detail has been exhaustively recovered.
        exact_complete = bool(response.content_type != "image" and not response.truncated)
    else:
        exact_complete = bool(extraction_complete)
    if not extraction_kind and response.content_type == "image" and exact_text:
        extraction_kind = "vision_text"
    record = _attachment_store(engine).create(
        workspace_scope=workspace_scope,
        filename=filename,
        data=data,
        content_type=response.content_type,
        excerpt=response.result_text,
        excerpt_kind=excerpt_kind,
        extracted_text=exact_text,
        extraction_complete=exact_complete,
        extraction_kind=(extraction_kind or excerpt_kind),
        page_count=page_count,
        pages_extracted=pages_extracted,
    )
    return UploadResponse(
        source_filename=response.source_filename,
        content_type=response.content_type,
        status=response.status,
        result_text=response.result_text,
        detail=response.detail,
        truncated=response.truncated,
        attachment_ref=record.ref,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        excerpt=record.excerpt,
    )


def _result_fallback_receipt(result: Any) -> dict[str, str] | None:
    """Normalize optional LoopResult fallback facts; mocks/legacy results fail-open to None."""
    value = getattr(result, "fallback_receipt", None)
    if not isinstance(value, dict):
        return None
    return {str(k): str(v) for k, v in value.items()}


# EVO-20260818: 文件树/会话树 API（独立模块 fs_tree.py，安全边界+审计）
from llm_loop.web.file_routes import file_router  # noqa: E402
from llm_loop.web.fs_tree import fs_router  # noqa: E402 — 延迟导入防循环（与下方 approve 同模式）

router.include_router(fs_router)
router.include_router(file_router)

# EVO-20260818: web 演进审批（复用飞书 approval.py 状态机+幂等+flock 锁）
from llm_loop.feishu.approval import approve, reject  # noqa: E402

SERVICE_NAME = "llm-first-loop-web"
SERVICE_VERSION = "0.6.6"  # T7: 语义化版本（与 pyproject 同步；git tag v0.5.2）


class UTF8JSONResponse(JSONResponse):
    """强制 UTF-8 声明：content-type 带 charset=utf-8，杜绝中文按默认编码（如 GBK）误解码."""

    media_type = "application/json; charset=utf-8"


def _engine_from(request: Request) -> Any:
    """从 app.state 取单引擎实例（装配一次复用全部请求，不每请求重建）."""
    return request.app.state.engine


def _evolution_store_from(engine: Any) -> Any | None:
    """解析 EvolutionStore：优先 correction_ctx.evolution_store（factory.py 装配位置），兼容 engine.evolution_store（测试/历史挂载）.

    修复（EVO-20260909 web 审批确认键无效）：真实引擎只在 correction_ctx 上持有 store，
    旧的 engine.evolution_store 读取在生产恒为 None，导致 list 有数据但 review 恒 400 evolve_disabled。
    """
    ctx = getattr(engine, "correction_ctx", None)
    return getattr(ctx, "evolution_store", None) or getattr(engine, "evolution_store", None)


_locks_guard = threading.Lock()
_LOCK_TIMEOUT_S = 30
_SSE_QUEUE_TIMEOUT_S = 15  # 后台 run 订阅队列 get 超时（防御；正常 run 必有 done/error 终态）
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

    try:
        with engine.workspace_snapshot() as workspace_epoch:
            attachment_scope = _current_attachment_workspace_scope(engine)
            try:
                attachment_facts = _resolve_chat_attachment_facts(
                    engine, payload.attachments, workspace_scope=attachment_scope
                )
            except AttachmentError as exc:
                return UTF8JSONResponse(
                    status_code=400,
                    content={"error": "invalid_attachment", "detail": str(exc)},
                )
            if getattr(payload, "new_session", False):
                # schema 契约：new_session 与 session_id 同传时强制新建优先。
                # M60（Web 对齐 M52）: 继承旧共享会话 model_override，不回落装配默认——
                # 否则 Web 新建会话经 owner 跨端共享把飞书侧也拉回本地默认模型。
                session_id = engine.session.create(
                    model_override=_inherit_shared_model_override(engine)
                )
                engine.session.set_shared_current(session_id)
            elif payload.session_id is not None:
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
                session_id = _resolve_session_id_locked(engine, request, None)
    except WorkspaceBusyError as exc:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "workspace_busy", "detail": str(exc)},
        )

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
    _persist_model_ref = _canonical_persist_model(engine, payload.model)
    _on_run_acquired = (
        (lambda sess: _apply_session_model_override(sess, _persist_model_ref))
        if _persist_model_ref
        else None
    )
    try:
        # R8.24-D D-D2（DT-1.3）: Web 非流式端点签发人类通道凭据（ingress token）——
        # guard fail-closed（default enforce）下无凭据 user 写入将被拒绝；本接线使
        # Web 通道合法输入携带白名单凭据放行（叠加式改动，外部并行改动零触碰）。
        from llm_loop.core.trace_leak.ingress_token import issue_ingress

        result = engine._run_with_acquired(
            session_id,
            payload.message,
            model=payload.model,
            reasoning_effort=payload.reasoning_effort,
            reasoning_mode=payload.reasoning_mode,
            on_run_acquired=_on_run_acquired,
            expected_workspace_epoch=workspace_epoch,
            ingress=issue_ingress("web"),
            user_metadata={"attachments": attachment_facts} if attachment_facts else None,
        )
    except WorkspaceChangedError as exc:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "workspace_changed", "detail": str(exc)},
        )
    except SessionBusyError as exc:
        # EVO 后台 run 改造（B5/B7）: 同会话已有后台 run 进行中 → 503（与锁超时同语义）
        return UTF8JSONResponse(
            status_code=503,
            content={"error": "session_busy", "detail": str(exc)},
        )
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

        background_tasks.add_task(
            push_web_chat_to_feishu, channel, payload.message, result.final_answer
        )

    return ChatResponse(
        session_id=result.session_id,
        final_answer=result.final_answer,
        verification_note=result.verification_note,
        rounds=result.rounds,
        tool_calls=result.tool_calls,
        truncated=result.truncated,
        model_used=result.model_used,
        fallback_receipt=_result_fallback_receipt(result),
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        tokens_cache_hit=result.tokens_cache_hit,  # M58: 非流式路径透传（DSH 修复 20260817）
        reasoning_content=result.reasoning_content,  # P1-1: 非流式路径透传思考链
        reasoning_mode=result.reasoning_mode,
        reasoning_capable=result.reasoning_capable,
        reasoning_control=result.reasoning_control,
        reasoning_supported=result.reasoning_supported,
        reasoning_effective=result.reasoning_effective,
        reasoning_tokens=result.reasoning_tokens,
    )


def _sse(event_type: str, data: Any) -> str:
    """SSE 事件序列化（data: {json}，design §2.2.2.3）."""
    return f"data: {json.dumps({'type': event_type, 'data': data}, ensure_ascii=False)}\n\n"


def _fmt_ts(ts: float | None) -> str:
    """时间戳 → HH:MM:SS（busy 提示用；非法/缺失返回空串）."""
    if not ts:
        return ""
    try:
        import datetime

        return datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")
    except Exception:  # noqa: BLE001 — 格式化失败返回空串
        return ""


def _canonical_persist_model(engine: Any, model: str | None) -> str | None:
    """返回可安全持久化的规范模型引用；未知模型不持久化但仍由本次请求如实处理。"""
    if not model:
        return None
    pool = getattr(engine, "llm_pool", None)
    if pool is None:
        return model
    try:
        snapshot_fn = getattr(pool, "registry_snapshot", None)
        registry: Any = snapshot_fn() if callable(snapshot_fn) else pool.registry
        pid, mid = registry.resolve(model)
        return f"{pid}/{mid}"
    except ValueError:
        return None


def _apply_session_model_override(session: Any, model_ref: str | None) -> None:
    """接单成功后修改本轮 run-owned Session；持久化由 engine accepted 边界统一执行。"""
    # EVO-20260829-ad8c5984 装配漂移防御层：前端 stale state.model 经 payload.model
    # 无条件写回会静默覆盖 run 内 switch_model 的切换。前端回填（stream-chat.js
    # buildAssistantNote 用 done.model_used 回填 state.model）已闭合主环；
    # 此告警为可观测兜底——任何残余漂移尝试都会进日志，便于验证根治效果。
    if model_ref and getattr(session, "model_override", None) != model_ref:
        old = getattr(session, "model_override", None)
        if old:
            logger.warning(
                "model_override 写回覆盖: %s → %s（前轮 switch_model 可能被 web payload.model 覆盖）",
                old,
                model_ref,
            )
        session.model_override = model_ref


def _inherit_shared_model_override(engine: Any) -> str | None:
    """读旧共享当前会话的 model_override 供新建会话继承（M60，fail-open → None）.

    与飞书 SessionMap.inherit_model_override（M52-fix）/ CLI /new 同语义：新建会话
    沿用用户所选模型而非回落装配默认；旧共享会话缺失/损坏时不阻断新建。
    """
    from contextlib import suppress

    old_sid = engine.session.get_shared_current()
    if old_sid is None:
        return None
    with suppress(Exception):
        return engine.session.load(old_sid).model_override
    return None


def _stream_background(
    runner: Any,
    session_id: str,
    message: str,
    model: str | None,
    reasoning_effort: str | None = None,
    reasoning_mode: str | None = None,
    *,
    resume: bool = False,
    before_start: Callable[[Any], None] | None = None,
    expected_workspace_epoch: int | None = None,
    user_metadata: dict[str, Any] | None = None,
) -> Any:
    """后台 run 订阅生成器（EVO 后台 run 改造）：提交 → 消费事件 → 分片 yield SSE.

    - resume=True: 不提交新 run，订阅已有 run（刷新/切回会话场景）
    - delta: text/reasoning/tool_round 分片独立 yield（对齐旧路径 P1-1/P2-1）
    - done: 终态九字段（对齐非流式 ChatResponse）
    - error: 引擎异常如实回执
    - finally: unsubscribe（SSE 断连只停订阅，后台线程不受影响、继续落盘）
    """
    try:
        # R8.24-D D-D2（DT-1.3④盘点补齐）: 后台 run 提交同样携带 web 通道凭据
        # （runner 线程体透传 run_stream ingress；resume 不提交新 run 不需要凭据）。
        from llm_loop.core.trace_leak.ingress_token import issue_ingress

        start_kwargs: dict[str, Any] = {
            "model": model,
            "reasoning_effort": reasoning_effort,
            "reasoning_mode": reasoning_mode,
            "resume": resume,
            "before_start": before_start,
            "expected_workspace_epoch": expected_workspace_epoch,
            "ingress": None if resume else issue_ingress("web"),
        }
        if not resume and user_metadata is not None:
            start_kwargs["user_metadata"] = user_metadata
        handle, q = runner.start(session_id, message, **start_kwargs)
    except WorkspaceChangedError as exc:
        yield _sse("error", {"error": "workspace_changed", "detail": str(exc)})
        return
    if q is None:
        if resume:
            # DSH 017 ② 语义区分：resume 场景无进行中 run（已结束/不存在）→
            # no_active_run（前端据此直接重载已生成内容），区别于真正 busy
            yield _sse(
                "error",
                {
                    "error": "no_active_run",
                    "detail": "没有进行中的后台任务（run 已结束或不存在），可直接刷新查看结果",
                    "status": {},
                },
            )
            return
        # 提交被拒（同会话已有 running run）→ 附状态信息，前端可轮询
        snap = runner.get_handle(session_id) or {}
        yield _sse(
            "error",
            {
                "error": "session_busy",
                "detail": "该会话正在生成中"
                + (
                    f"（开始于 {_fmt_ts(snap.get('started_at'))}）"
                    if snap.get("started_at")
                    else ""
                )
                + "，完成后即可继续发送；可稍后刷新查看结果",
                "status": snap,
            },
        )
        return
    try:
        # 审查 P2 修复: 断连解绑提速——q.get 超时 15s→2s。同步生成器无法
        # await is_disconnected，断连靠 ASGI 在 yield 挂起点注入 GeneratorExit；
        # 短超时让循环更快回到 yield 挂起点（断连后订阅残留从 ~15s 降到 ~2s，
        # 期间不再长时间向无人消费的队列 put 事件）。
        while True:
            try:
                ev = q.get(timeout=2.0)
            except queue.Empty:
                # 防御超时（正常 run 必有终态）；后台长时间无 delta（如工具执行）时
                # 保持连接等待。断连由 ASGI 在 yield 挂起点注入 GeneratorExit。
                continue
            etype = ev["type"]
            if etype == "delta":
                delta = ev["delta"]
                if getattr(delta, "text", None):
                    yield _sse("answer_delta", {"data": delta.text})
                if getattr(delta, "reasoning", None):
                    yield _sse("reasoning_delta", {"data": delta.reasoning})
                tr = getattr(delta, "tool_round", None)
                if tr is not None:
                    yield _sse(
                        "tool_round",
                        {
                            "tool_name": getattr(tr, "tool_name", ""),
                            "round_index": getattr(tr, "round_index", 0),
                            "args_summary": getattr(tr, "args_summary", ""),
                            "tool_call_id": getattr(tr, "tool_call_id", ""),
                        },
                    )
            elif etype == "done":
                result = ev["result"]
                yield _sse(
                    "done",
                    {
                        "session_id": getattr(result, "session_id", session_id),
                        "final_answer": getattr(result, "final_answer", ""),
                        "verification_note": getattr(result, "verification_note", None),
                        "rounds": getattr(result, "rounds", 0),
                        "tool_calls": getattr(result, "tool_calls", 0),
                        "truncated": getattr(result, "truncated", False),
                        "model_used": getattr(result, "model_used", ""),
                        "fallback_receipt": _result_fallback_receipt(result),
                        "tokens_in": getattr(result, "tokens_in", 0),
                        "tokens_out": getattr(result, "tokens_out", 0),
                        "tokens_cache_hit": getattr(result, "tokens_cache_hit", 0),
                        "reasoning_content": getattr(result, "reasoning_content", ""),
                        "reasoning_mode": getattr(result, "reasoning_mode", "auto"),
                        "reasoning_capable": getattr(result, "reasoning_capable", False),
                        "reasoning_control": getattr(result, "reasoning_control", "unknown"),
                        "reasoning_supported": getattr(result, "reasoning_supported", False),
                        "reasoning_effective": getattr(result, "reasoning_effective", False),
                        "reasoning_tokens": getattr(result, "reasoning_tokens", None),
                    },
                )
                return
            elif etype == "error":
                code = ev.get("error_code", "internal_error")
                detail = (
                    "会话繁忙，请稍后重试"
                    if code == "session_busy"
                    else f"[程序异常] 引擎执行失败（{ev['error']}）。"
                )
                yield _sse("error", {"error": code, "detail": detail})
                return
    finally:
        runner.unsubscribe(session_id, q)  # 断连/完成：停止订阅，后台线程不受影响


@router.post("/api/v1/chat/stream")
def chat_stream(
    payload: ChatRequest,
    request: Request,
) -> Response:
    """真流式对话端点（SSE）：answer_delta* → done（九字段）| error.

    真流式仅作用于最终回答轮（中间工具轮无可见文本、同步等待）；终态 done 携带完整
    ChatResponse 九字段，与非流式 POST /api/v1/chat 内容等价（spec 5.2 规则 4）。

    EVO 后台 run 改造：装配了 runner 时走"提交 + 订阅"（run 在后台线程执行，SSE 断连
    只停订阅、run 继续落盘）；否则回退旧生成器直驱（RUNNER_BACKGROUND=0 或未装配）。
    """
    engine = _engine_from(request)

    # 会话查/建与workspace切换互斥；响应生成延迟执行时再用epoch复核归属。
    try:
        with engine.workspace_snapshot() as workspace_epoch:
            attachment_scope = _current_attachment_workspace_scope(engine)
            try:
                attachment_facts = _resolve_chat_attachment_facts(
                    engine, payload.attachments, workspace_scope=attachment_scope
                )
            except AttachmentError as exc:
                return UTF8JSONResponse(
                    status_code=400,
                    content={"error": "invalid_attachment", "detail": str(exc)},
                )
            if getattr(payload, "new_session", False):
                # M60（Web 对齐 M52）: 继承旧共享会话 model_override（fail-open → None）
                session_id = engine.session.create(
                    model_override=_inherit_shared_model_override(engine)
                )
                engine.session.set_shared_current(session_id)
            elif payload.session_id is not None:
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
                session_id = _resolve_session_id_locked(engine, request, None)
    except WorkspaceBusyError as exc:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "workspace_busy", "detail": str(exc)},
        )

    # Web 模型选择只在请求成功接单后持久化。未知模型不写 session，
    # 仍交本次 per-call 路由生成“模型不可用”反馈；busy/resume 必须零副作用。
    _persist_model_ref = _canonical_persist_model(engine, payload.model)

    def event_stream():
        # 后台 run 模式（EVO 后台 run 改造，对齐 DSH）：提交 + 订阅；断连只停订阅
        runner = getattr(engine, "runner", None)
        _resume = bool(getattr(payload, "resume", False))
        _before_start = (
            (lambda sess: _apply_session_model_override(sess, _persist_model_ref))
            if (_persist_model_ref and not _resume)
            else None
        )
        if runner is not None and runner.enabled:
            yield from _stream_background(
                runner,
                session_id,
                payload.message,
                payload.model,
                reasoning_effort=payload.reasoning_effort,
                reasoning_mode=payload.reasoning_mode,
                resume=_resume,
                before_start=_before_start,
                expected_workspace_epoch=workspace_epoch,
                user_metadata={"attachments": attachment_facts} if attachment_facts else None,
            )
            return
        if _resume:
            # resume 是“订阅已有后台 run”的协议语义，不是新的 human ingress。
            # runner 关闭/不可用时不能把恢复占位 message 落入旧直驱执行路径。
            yield _sse(
                "error",
                {
                    "error": "no_active_run",
                    "detail": "后台运行器未启用，当前请求不能恢复订阅。",
                },
            )
            return
        # 回退旧路径（生成器直驱，原行为；RUNNER_BACKGROUND=0 或未装配）
        lock = _get_session_lock(request, session_id)
        acquired = False
        if lock is not None and not lock.acquire(timeout=_LOCK_TIMEOUT_S):
            yield _sse("error", {"error": "session_busy", "detail": "会话繁忙，请稍后重试"})
            return
        if lock is not None:
            acquired = True
        try:
            # R8.24-D D-D2（DT-1.3）: Web 流式端点签发人类通道凭据（ingress token），
            # 与非流式端点同源（issue_ingress 幂等，双端点共享 web 通道凭据）。
            from llm_loop.core.trace_leak.ingress_token import issue_ingress

            it = engine._run_stream_with_acquired(
                session_id,
                payload.message,
                model=payload.model,
                reasoning_effort=payload.reasoning_effort,
                reasoning_mode=payload.reasoning_mode,
                on_run_acquired=_before_start,
                expected_workspace_epoch=workspace_epoch,
                ingress=issue_ingress("web"),
                user_metadata={"attachments": attachment_facts} if attachment_facts else None,
            )
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
        except WorkspaceChangedError as exc:
            yield _sse("error", {"error": "workspace_changed", "detail": str(exc)})
            return
        except SessionBusyError as exc:
            yield _sse("error", {"error": "session_busy", "detail": str(exc)})
            return
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
                "fallback_receipt": _result_fallback_receipt(result),
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "tokens_cache_hit": getattr(result, "tokens_cache_hit", 0),  # M58: 缓存命中
                "reasoning_content": result.reasoning_content,  # P1-1: 终态兜底
                "reasoning_mode": getattr(result, "reasoning_mode", "auto"),
                "reasoning_capable": getattr(result, "reasoning_capable", False),
                "reasoning_control": getattr(result, "reasoning_control", "unknown"),
                "reasoning_supported": getattr(result, "reasoning_supported", False),
                "reasoning_effective": getattr(result, "reasoning_effective", False),
                "reasoning_tokens": getattr(result, "reasoning_tokens", None),
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/api/v1/chat/stream/status")
def chat_stream_status(session_id: str, request: Request) -> Response:
    """后台 run 状态查询（EVO 后台 run）：running/done/error + 起止时间.

    前端收到 session_busy 或切换/刷新会话时轮询，判断生成是否完成。
    未装配 runner / 无进行中 run → {"running": false}（前端走会话历史兜底）。
    """
    engine = _engine_from(request)
    runner = getattr(engine, "runner", None)
    if runner is None or not runner.enabled:
        return UTF8JSONResponse(content={"running": False, "detail": "后台 run 未启用"})
    snap = runner.get_handle(session_id)
    if snap is None:
        return UTF8JSONResponse(content={"running": False})
    return UTF8JSONResponse(content={"running": True, **snap})


@router.post("/api/v1/chat/cancel")
def chat_cancel(payload: ChatCancelRequest, request: Request) -> Response:
    """停止当前会话的后台 run（2026-08-23 停止按钮修复）.

    前端 stopStreaming 在 abort SSE 订阅后调用本端点——SSE 断连只停订阅、
    后台 run 线程会继续执行（EVO 后台 run 语义），需显式请求取消：
    runner.cancel() 置 handle.cancelled → 引擎主循环每轮检查后提前终止。
    """
    engine = _engine_from(request)
    runner = getattr(engine, "runner", None)
    if runner is None or not runner.enabled:
        return UTF8JSONResponse(
            content={"cancelled": False, "detail": "后台 run 未启用（无取消需求）"}
        )
    ok = runner.cancel(payload.session_id)
    return UTF8JSONResponse(content={"cancelled": ok})


_STATIC_DIR = Path(__file__).resolve().parent / "static"


@router.get("/")
def root() -> Response:
    """服务根路径：默认重定向到 Web V2（/ui/v2，2026-08-20 起默认入口）。

    2026-09-04 弃用 v1（原版 M37 前端）：v2 产物缺失时直接 503，不再回退旧版
    聊天页面（static/index.html 保留不删，但不再服务，避免两套前端混淆）。
    """
    # 与 build_app 挂载逻辑同源：函数内求值（测试可 monkeypatch UI_V2_DIR）
    ui_v2 = Path(
        os.environ.get("UI_V2_DIR", "") or Path(__file__).resolve().parents[3] / "webui" / "dist"
    )
    if ui_v2.is_dir():
        return RedirectResponse("/ui/v2/", status_code=307)
    # v1 已弃用：产物缺失时返回 503，不再 fallback 旧版前端
    return JSONResponse(
        status_code=503,
        content={
            "error": "frontend_missing",
            "detail": "Web V2 前端产物缺失（webui/dist 不存在），请重新构建：cd webui && npm run build。",
        },
    )


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
    """健康检查：纯服务层探活，不调用 LLM、不含凭证.

    R3: runtime 字段读回启动时落盘的 manifest 摘要（身份+配置指纹）——
    跨区污染诊断（module_repo_root 指向哪个区、端口对不对）秒级完成。
    health_identity() 读回而非实时 compute（identity 含 git subprocess，探活高频不可跑）；
    fail-open：manifest 缺失时返回空 identity 仍可诊断。
    """
    from llm_loop.runtime.manifest import health_identity

    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "identity": health_identity(),
    }


@router.get("/api/v1/architecture_status")
def architecture_status_web(request: Request, session_id: str = "") -> Response:
    """EVO-20260818（spec §5.4.1-2）: 架构状态 web API 通道.

    含 context_usage.cache_health / cache_guard 快照——命中率权威口径为
    cache_guard.recent_hit_rate（会话近 10 次窗口，目标 ≥90%）。fail-open：
    快照异常返回部分字段（error + 空快照），不抛 500。
    """
    engine = _engine_from(request)
    try:
        snap = engine.status.snapshot(session_id=session_id)
        return UTF8JSONResponse(content=snap)
    except Exception as exc:  # noqa: BLE001 — 快照异常 fail-open
        return UTF8JSONResponse(
            content={
                "error": f"architecture_status 快照失败（fail-open）: {exc}",
                "cache_health": None,
                "cache_guard": None,
            },
            status_code=500,
        )


@router.get("/api/v1/evolution/list")
def evolution_list(request: Request, limit: int = 30, status: str = "") -> Response:
    """演进建议列表（只读——web 审批状态展示数据源；Approval UX v2 批 1）.

    status 可选过滤（pending_review/accepted/rejected/executed）；返回摘要
    （content 前 120 字）+ impact_hint（影响面），完整内容走 detail 端点（懒加载）。
    """
    from pathlib import Path

    base = Path(os.environ.get("LFL_DATA_DIR", "") or Path(__file__).resolve().parents[3] / "data")
    f = base / "audit" / "evolution_suggestions.jsonl"
    out = []
    if f.exists():
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:  # noqa: BLE001 — 单行坏数据跳过
                    continue
                if status and d.get("status") != status:
                    continue
                content = d.get("content") or ""
                impact_files = d.get("impact_files") or []
                impact_hint = (
                    ", ".join(impact_files[:5])
                    if impact_files
                    else ((d.get("impact_scope") or "")[:120] or content[:120])
                )
                out.append(
                    {
                        "id": d.get("id", ""),
                        "ts": d.get("ts", ""),
                        "status": d.get("status", ""),
                        "priority": d.get("priority", ""),
                        "requires_human": bool(d.get("requires_human")),
                        "content": content[:120],  # 摘要；全文走 detail 端点
                        "impact_hint": impact_hint,
                        "rejected_reason": d.get("rejected_reason", ""),
                        "reviewed_at": d.get("reviewed_at", ""),
                        "executed_at": d.get("executed_at"),
                        "verified_at": d.get("verified_at"),
                    }
                )
        except OSError:
            pass  # 建议文件读取失败 fail-open（返回已收集条目，日志由上层审计兜底）
    out.sort(key=lambda x: x["ts"], reverse=True)
    return JSONResponse(content={"suggestions": out[:limit], "count": len(out)})


@router.get("/api/v1/evolution/detail")
def evolution_detail(request: Request, id: str = "") -> Response:
    """演进建议详情（Approval UX v2 批 1: 完整内容懒加载，列表只回摘要）."""
    from pathlib import Path

    if not id:
        return UTF8JSONResponse(
            status_code=400, content={"error": "invalid_params", "detail": "id 必填。"}
        )
    base = Path(os.environ.get("LFL_DATA_DIR", "") or Path(__file__).resolve().parents[3] / "data")
    f = base / "audit" / "evolution_suggestions.jsonl"
    if not f.exists():
        return UTF8JSONResponse(
            status_code=404, content={"error": "not_found", "detail": "建议文件不存在"}
        )
    try:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if d.get("id") == id:
                return JSONResponse(
                    content={
                        "id": d.get("id", ""),
                        "ts": d.get("ts", ""),
                        "status": d.get("status", ""),
                        "priority": d.get("priority", ""),
                        "requires_human": bool(d.get("requires_human")),
                        "scope": d.get("scope", "global"),
                        "content": d.get("content", ""),
                        "evidence": d.get("evidence", ""),
                        "impact_scope": d.get("impact_scope", ""),
                        "impact_files": d.get("impact_files") or [],
                        "rejected_reason": d.get("rejected_reason", ""),
                        "reviewed_at": d.get("reviewed_at", ""),
                        "executed_at": d.get("executed_at", ""),
                        "verified_at": d.get("verified_at", ""),
                        "reason_history": d.get("reason_history") or [],
                    }
                )
        return UTF8JSONResponse(
            status_code=404, content={"error": "not_found", "detail": f"未找到 {id}"}
        )
    except OSError:
        return UTF8JSONResponse(
            status_code=500, content={"error": "read_failed", "detail": "建议文件读取失败。"}
        )


@router.post("/api/v1/evolution/review")
def evolution_review(payload: EvolutionReviewRequest, request: Request) -> Response:
    """web 演进建议审批（EVO-20260818: 用户要求审批按钮，替代仅飞书/CLI）.

    body: {"id": "EVO-xxx", "decision": "accepted|rejected", "reason": "可选"}
    复用 feishu/approval.py 的 approve/reject（状态机+幂等+flock 锁）；
    accepted 且 EVOLVE_LOCAL_EXEC 允许 → 自动触发执行（与飞书/CLI 行为一致）。
    安全: 本地 web（127.0.0.1）默认可信；WEB_AUTH_REQUIRE=1 时受 Bearer 保护。
    """
    engine = _engine_from(request)
    store = _evolution_store_from(engine)
    if store is None:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "evolve_disabled", "detail": "演进功能未启用（EVOLVE_ENABLED=0）。"},
        )
    evo_id = (payload.id or "").strip()
    decision = (payload.decision or "").strip()
    reason = (payload.reason or "").strip()
    if not evo_id or decision not in {"accepted", "rejected"}:
        return UTF8JSONResponse(
            status_code=400,
            content={
                "error": "invalid_params",
                "detail": "id 必填，decision 须为 accepted/rejected。",
            },
        )
    if decision == "rejected" and not reason:
        return UTF8JSONResponse(
            status_code=400,
            content={
                "error": "reason_required",
                "detail": "拒绝须提供理由（Approval UX v2 批 1: 拒绝理由必填留痕）。",
            },
        )
    # Approval UX v2 批 1（验证清单 #9）: 涉边界项单条批准需额外确认标志（extra_confirm）
    if decision == "accepted":
        cur_for_confirm = _find_suggestion(store, evo_id)
        if (
            cur_for_confirm is not None
            and bool(cur_for_confirm.get("requires_human"))
            and not payload.extra_confirm
        ):
            return UTF8JSONResponse(
                status_code=409,
                content={
                    "error": "confirm_required",
                    "detail": "涉边界项（requires_human）批准须额外确认（extra_confirm=true）。",
                    "requires_human": True,
                },
            )
    # Approval UX v2 批 1: 乐观锁 CAS——expected_status 不匹配 → 409 提示刷新（防双端状态竞争）
    if payload.expected_status:
        cur_for_cas = _find_suggestion(store, evo_id)
        if cur_for_cas is None:
            return UTF8JSONResponse(
                status_code=404, content={"error": "not_found", "detail": f"未找到 {evo_id}"}
            )
        if cur_for_cas.get("status") != payload.expected_status:
            return UTF8JSONResponse(
                status_code=409,
                content={
                    "error": "status_conflict",
                    "detail": f"状态已变（期望 {payload.expected_status}，当前 {cur_for_cas.get('status')}），已刷新。",
                    "current_status": cur_for_cas.get("status"),
                },
            )
    try:
        if decision == "accepted":
            ok, resp, reviewed = approve(store, evo_id)
            if ok and reviewed:
                from llm_loop.introspection.evolution_exec import maybe_auto_execute_from_engine

                cur = _find_suggestion(store, evo_id)
                if cur is not None:
                    try:
                        resp += "\n" + maybe_auto_execute_from_engine(engine, store, cur)
                    except Exception as exc:  # noqa: BLE001 — 执行触发失败不影响审批
                        resp += f"\n⚠️ 自动执行触发异常：{type(exc).__name__}"
        else:
            ok, resp = reject(store, evo_id, reason)
    except Exception as exc:  # noqa: BLE001 — 审批异常如实回执
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "review_failed", "detail": f"审批异常: {type(exc).__name__}: {exc}"},
        )
    return UTF8JSONResponse(
        content={"ok": ok, "message": resp},
        status_code=200 if ok else 400,
    )


@router.post("/api/v1/evolution/review-batch")
async def evolution_review_batch(request: Request) -> Response:
    """演进建议批量审批（Approval UX v2 批 1）.

    body: {"items": [{"id","decision","reason","expected_status"}], "decision":"accepted|rejected"}
    服务端硬校验：跳过 requires_human=true（涉边界必须单条审批）+ 拒绝理由必填；
    逐条独立事务（成功 n / 失败 m，不整体回滚）。
    """
    engine = _engine_from(request)
    store = _evolution_store_from(engine)
    if store is None:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "evolve_disabled", "detail": "演进功能未启用（EVOLVE_ENABLED=0）。"},
        )
    try:
        body = await request.json() if hasattr(request, "json") else {}
    except Exception:  # noqa: BLE001
        body = {}
    items = body.get("items") or []
    default_decision = (body.get("decision") or "").strip()
    if not items or default_decision not in {"accepted", "rejected"}:
        return UTF8JSONResponse(
            status_code=400,
            content={
                "error": "invalid_params",
                "detail": "items 必填且 decision 须为 accepted/rejected。",
            },
        )
    results: list[dict] = []
    ok_count = fail_count = 0
    for it in items:
        evo_id = str(it.get("id") or "").strip()
        decision = str(it.get("decision") or default_decision).strip()
        reason = str(it.get("reason") or "").strip()
        expected = str(it.get("expected_status") or "").strip()
        if not evo_id or decision not in {"accepted", "rejected"}:
            results.append({"id": evo_id, "ok": False, "message": "参数非法"})
            fail_count += 1
            continue
        # 服务端硬校验：涉边界跳过（禁止批量）
        cur = _find_suggestion(store, evo_id)
        if cur is not None and bool(cur.get("requires_human")):
            results.append(
                {
                    "id": evo_id,
                    "ok": False,
                    "message": "涉边界（requires_human），须单条审批",
                    "skipped": True,
                }
            )
            fail_count += 1
            continue
        # CAS 乐观锁
        if expected and cur is not None and cur.get("status") != expected:
            results.append(
                {
                    "id": evo_id,
                    "ok": False,
                    "message": f"状态冲突（期望 {expected}，当前 {cur.get('status')}）",
                }
            )
            fail_count += 1
            continue
        try:
            if decision == "accepted":
                ok, resp, reviewed = approve(store, evo_id)
            else:
                if not reason:
                    results.append({"id": evo_id, "ok": False, "message": "拒绝须提供理由"})
                    fail_count += 1
                    continue
                ok, resp = reject(store, evo_id, reason)
            results.append({"id": evo_id, "ok": bool(ok), "message": resp})
            ok_count += bool(ok)
            fail_count += not ok
        except Exception as exc:  # noqa: BLE001 — 单条失败不影响其余
            results.append(
                {"id": evo_id, "ok": False, "message": f"异常: {type(exc).__name__}: {exc}"}
            )
            fail_count += 1
    return UTF8JSONResponse(
        content={"ok_count": ok_count, "fail_count": fail_count, "results": results},
        status_code=200,
    )


@router.get("/api/v1/evolution/diff")
def evolution_diff(request: Request, id: str = "") -> Response:
    """演进建议关联 diff 预览（Approval UX v2 批 1: 只读）.

    仅返回建议自身 actions/impact_files 摘要（不含 prompt/密钥）；
    无关联改动 → 404（明确语义，非空壳 200）。
    """
    from pathlib import Path

    if not id:
        return UTF8JSONResponse(
            status_code=400, content={"error": "invalid_params", "detail": "id 必填。"}
        )
    base = Path(os.environ.get("LFL_DATA_DIR", "") or Path(__file__).resolve().parents[3] / "data")
    f = base / "audit" / "evolution_suggestions.jsonl"
    if not f.exists():
        return UTF8JSONResponse(
            status_code=404, content={"error": "not_found", "detail": "建议文件不存在"}
        )
    try:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if d.get("id") == id:
                if d.get("status") == "rejected":
                    return UTF8JSONResponse(
                        status_code=404,
                        content={"error": "no_diff", "detail": "已拒绝建议无 diff。"},
                    )
                actions = d.get("actions") or []
                impact_files = d.get("impact_files") or []
                if not actions and not impact_files:
                    return UTF8JSONResponse(
                        status_code=404,
                        content={"error": "no_diff", "detail": "该建议无关联改动。"},
                    )
                return JSONResponse(
                    content={
                        "id": id,
                        "impact_files": impact_files,
                        "actions": [a for a in actions if isinstance(a, dict)][:20],
                        "note": "只读摘要（不含 prompt/密钥）",
                    }
                )
        return UTF8JSONResponse(
            status_code=404, content={"error": "not_found", "detail": f"未找到 {id}"}
        )
    except OSError:
        return UTF8JSONResponse(
            status_code=500, content={"error": "read_failed", "detail": "建议文件读取失败。"}
        )


def _find_suggestion(store: Any, evo_id: str) -> dict | None:
    """按 id 在演进存储中查找建议（web 审批执行触发用）."""
    try:
        for s in store.list() or []:
            if s.get("id") == evo_id:
                return s
    except Exception:  # noqa: BLE001
        return None
    return None


@router.get("/api/v1/sessions/{session_id}/stats")
def session_stats(session_id: str, request: Request) -> Any:
    """会话统计（M59，对齐 DSH 统计栏）：轮/步/tokens/缓存命中/耗时聚合.

    双源聚合（只读，不触发 run）：
    - turns/steps：会话消息计数（assistant/tool）
    - tokens/耗时/缓存：优先从 request.usage 事件聚合（消息 payload 不含统计字段，
      message.appended 只存基础字段；request.usage 有 tokens_in/out/cache_hit/耗时）。
      事件缺失时回退消息字段（内存态兼容）。
    """
    engine = _engine_from(request)
    sess = engine.session.load(session_id)
    if sess is None:
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": f"会话不存在: {session_id}"},
        )
    msgs = getattr(sess, "messages", []) or []
    turns = steps = 0
    for m in msgs:
        if m.role == "assistant":
            turns += 1
        elif m.role == "tool":
            steps += 1

    # ── 统计字段：优先 request.usage 事件（持久化真相源），回退消息字段 ──
    tokens_in = tokens_out = cache_hit = 0
    by_model: dict[str, dict[str, int]] = {}  # 2026-08-20: 分模型命中率分桶
    llm_ms = tool_ms = 0.0
    ttft_sum = 0.0
    ttft_n = 0
    usage_events = 0
    event_store = getattr(engine.session, "_event_store", None)
    if event_store is not None and getattr(event_store, "enabled", False):
        try:
            events = event_store.read(session_id)
            for e in events:
                if e.type != "request.usage":
                    continue
                p = e.payload or {}
                usage_events += 1
                # 2026-08-20（镜像, 观测正确性）: 按模型分桶——跨端交替模型
                # （web=minimax / feishu=deepseek）时总命中率被另一模型轮次稀释,
                # 分模型口径才能正确归因（缓存按 provider 独立预热）。
                _mdl = str(p.get("model") or "unknown")
                _b = by_model.setdefault(_mdl, {"tokens_in": 0, "cache_hit": 0})
                _b["tokens_in"] += p.get("tokens_in") or 0
                _b["cache_hit"] += p.get("cache_hit") or 0
                tokens_in += p.get("tokens_in") or 0
                tokens_out += p.get("tokens_out") or 0
                cache_hit += p.get("cache_hit") or 0
                llm_ms += p.get("llm_ms") or 0.0
                tool_ms += p.get("tool_ms") or 0.0
                ttft = p.get("ttft_ms") or 0.0
                if ttft > 0:
                    ttft_sum += ttft
                    ttft_n += 1
        except Exception:  # noqa: BLE001 — 事件读取失败回退消息字段（fail-open）
            usage_events = 0
    if usage_events == 0:
        # 回退：消息字段（内存态会话有统计字段；event_log replay 无则如实 0）
        for m in msgs:
            if m.role == "assistant":
                tokens_in += getattr(m, "tokens_in", 0) or 0
                tokens_out += getattr(m, "tokens_out", 0) or 0
                cache_hit += getattr(m, "tokens_cache_hit", 0) or 0
                llm_ms += getattr(m, "llm_ms", 0.0) or 0.0
                ttft = getattr(m, "ttft_ms", 0.0) or 0.0
                if ttft > 0:
                    ttft_sum += ttft
                    ttft_n += 1
            elif m.role == "tool":
                tool_ms += getattr(m, "duration_ms", 0.0) or 0.0
    hit_rate = round(cache_hit / tokens_in * 100, 1) if tokens_in > 0 else 0.0
    tok_s = round(tokens_out / (llm_ms / 1000.0), 1) if llm_ms > 0 else 0.0
    # 2026-08-20（镜像）: 分模型命中率——跨模型交替时总口径被稀释, 分模型口径
    # 揭示真实缓存行为（每模型独立预热）
    by_model_out = {
        _mdl: {
            "tokens_in": _b["tokens_in"],
            "cache_hit": _b["cache_hit"],
            "cache_hit_rate": round(_b["cache_hit"] / _b["tokens_in"] * 100, 1)
            if _b["tokens_in"] > 0
            else 0.0,
        }
        for _mdl, _b in sorted(by_model.items())
    }
    return {
        "turns": turns,
        "steps": steps,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cache_hit": cache_hit,
        "cache_hit_rate": hit_rate,
        "by_model": by_model_out,
        "llm_ms": round(llm_ms, 1),
        "tool_ms": round(tool_ms, 1),
        "ttft_avg_ms": round(ttft_sum / ttft_n, 1) if ttft_n else 0.0,
        "tok_s": tok_s,
    }


@router.get("/api/v1/interop/messages")
def list_interop_messages(request: Request) -> dict:
    """协调通道消息（只读，不触发 run）——web 端展示给用户看.

    读 data/interop/{lfl_to_dsh,dsh_to_lfl}/pending/ 的 JSON 消息（协议见 INTEROP.md），
    返回两个方向的待处理消息摘要。只读文件系统，不触发 agent run、不占会话锁。
    """
    del request  # 纯文件读取，无引擎依赖
    base = Path(os.environ.get("LFL_DATA_DIR", "data")) / "interop"
    result: dict[str, dict] = {
        "lfl_to_dsh": {"pending": [], "recent_done": []},
        "dsh_to_lfl": {"pending": [], "recent_done": []},
    }
    for direction in ("lfl_to_dsh", "dsh_to_lfl"):
        for sub in ("pending", "done"):
            pdir = base / direction / sub
            if not pdir.is_dir():
                continue
            # done 只取最近 N 条（按文件名倒序）
            files = sorted(pdir.glob("*.json"), reverse=True)
            if sub == "done":
                files = files[:5]
            result_key = "recent_done" if sub == "done" else "pending"
            for f in files:
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue  # 格式坏/读失败 → 跳过（fail-open）
                result[direction][result_key].append(
                    {
                        "id": d.get("id", f.stem),
                        "from": d.get("from", ""),
                        "to": d.get("to", ""),
                        "ts": d.get("ts", ""),
                        "topic": d.get("topic", ""),
                        "body": str(d.get("body", ""))[:300],
                        "status": d.get("status", sub),
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
            pinned=m.pinned,  # M56: 置顶透传
            channel=m.channel,  # M56: 来源通道透传
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
    responses={
        409: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
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
    except SessionMutationBusyError as exc:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "session_busy", "detail": str(exc)},
        )
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
    "/api/v1/sessions/{session_id}/archive",
    response_model=None,
    responses={
        409: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def set_session_archive(session_id: str, request: Request, archived: bool = False) -> Response:
    """会话归档/取消归档（2026-08-21: 归档文件夹——旧会话收拢防误操作）."""
    engine = _engine_from(request)
    if not engine.session.exists(session_id):
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": session_not_found_message(session_id)},
        )
    try:
        ok = (
            engine.session.archive(session_id) if archived else engine.session.unarchive(session_id)
        )
    except SessionMutationBusyError as exc:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "session_busy", "detail": str(exc)},
        )
    except Exception as exc:
        logger.exception("session archive failed: session_id=%s", session_id)
        return UTF8JSONResponse(
            status_code=500,
            content={
                "error": "archive_failed",
                "detail": f"[程序异常] 会话归档失败（{type(exc).__name__}: {exc}）。",
            },
        )
    if not ok:
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": session_not_found_message(session_id)},
        )
    return UTF8JSONResponse(
        content={"status": "ok", "session_id": session_id, "archived": archived}
    )


@router.post(
    "/api/v1/sessions/{session_id}/fork",
    response_model=None,
    responses={
        409: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
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
        with engine.session.management_lease(session_id):
            report = fork_session(
                event_store,
                engine.session,
                session_id,
                fork_point=fork_point,
                branch_summary=summary,
            )
    except SessionMutationBusyError as exc:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "session_busy", "detail": str(exc)},
        )
    except Exception as exc:
        logger.exception("session fork failed: session_id=%s", session_id)
        return UTF8JSONResponse(
            status_code=500,
            content={
                "error": "fork_failed",
                "detail": f"[程序异常] fork 失败（{type(exc).__name__}: {exc}）",
            },
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
    if payload.feedback not in ("up", "down"):
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "invalid_feedback", "detail": "feedback 仅支持 up / down。"},
        )
    try:
        with engine.session.management_lease(session_id):
            if not engine.session.exists(session_id):
                return UTF8JSONResponse(
                    status_code=404,
                    content={
                        "error": "session_not_found",
                        "detail": session_not_found_message(session_id),
                    },
                )
            sess = engine.session.load(session_id)
            if payload.message_index >= len(sess.messages):
                return UTF8JSONResponse(
                    status_code=400,
                    content={
                        "error": "index_out_of_range",
                        "detail": (
                            f"message_index {payload.message_index} "
                            f"超出会话消息数 {len(sess.messages)}。"
                        ),
                    },
                )
            feedback_file = Path(getattr(engine.settings, "data_dir", "./data")) / "feedback.jsonl"
            append_feedback(
                feedback_file,
                {
                    "ts": __import__("time").time(),
                    "session_id": session_id,
                    "message_index": payload.message_index,
                    "role": sess.messages[payload.message_index].role,
                    "feedback": payload.feedback,
                    "note": payload.note,
                },
            )
    except SessionMutationBusyError as exc:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "session_busy", "detail": str(exc)},
        )
    except Exception as exc:  # noqa: BLE001 — 反馈失败如实 500（不影响主链路）
        logger.exception("message feedback failed: session=%s", session_id)
        return UTF8JSONResponse(
            status_code=500,
            content={
                "error": "feedback_failed",
                "detail": f"[程序异常] 反馈记录失败（{type(exc).__name__}: {exc}）",
            },
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


def _session_events_fingerprint(engine: Any) -> str:
    """当前SessionStore根 + 内容指纹；workspace切换本身也视为会话视图变化。"""
    session = getattr(engine, "session", None)
    sessions_dir = getattr(session, "root", None)
    if sessions_dir is None:
        sessions_dir = (
            getattr(getattr(engine, "settings", None), "sessions_dir", None) or "./data/sessions"
        )
    root = Path(sessions_dir)
    return f"{root}:{_sessions_fingerprint(root)}"


@router.get("/api/v1/events")
async def stream_session_events(request: Request) -> StreamingResponse:
    """SSE 会话更新事件流（M56：Web 端实时刷新）.

    动态轮询当前 SessionStore 根指纹（workspace根 + 文件数 + 最新mtime），变化即推送
    sessions_updated 事件；workspace切换本身也触发刷新，长连接无需重建。
    Web 前端收到后刷新会话列表与当前会话消息。零新依赖（同进程内 asyncio 轮询）。

    2026-08-15 修复：SSE 命名事件必须带 `event: <type>` 行——此前只发
    `data: {"type": ...}`，浏览器按默认 message 事件处理，前端
    addEventListener("sessions_updated") 永不触发（Web 端必须手动刷新才能看到
    飞书消息）。现补 `event:` 行（data 内 type 字段保留向后兼容），并加 20s
    keepalive 注释行防中间层/浏览器超时掐断长连接。
    """
    engine = _engine_from(request)
    initial = _session_events_fingerprint(engine)

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
            current = _session_events_fingerprint(engine)
            if current != initial and current != "err":
                initial = current
                last_beat = now
                yield _sse_event("sessions_updated", {"type": "sessions_updated"})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/api/v1/sessions/{session_id}/jobs")
def list_session_jobs(session_id: str, request: Request) -> Response:
    """List exact owner-scoped background execution facts for the current session."""
    from llm_loop.tools.builtin.job_registry import JobRegistry

    engine = _engine_from(request)
    if not engine.session.exists(session_id):
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": session_not_found_message(session_id)},
        )
    jobs = JobRegistry.instance().snapshots_for_session(session_id)
    safe_jobs = []
    for item in jobs:
        row = dict(item)
        # UI gets command/output only from a current-process owner-scoped handle.
        # Never expose workspace_root, PID/PGID, or other host identity.
        row.pop("workspace_root", None)
        safe_jobs.append(row)
    return UTF8JSONResponse(content={"jobs": safe_jobs, "count": len(safe_jobs)})


@router.post("/api/v1/sessions/{session_id}/jobs/{job_id}/kill")
def kill_session_job(session_id: str, job_id: str, request: Request) -> Response:
    """Explicit authenticated-user cancellation of one locally controlled job."""
    from llm_loop.tools.builtin.job_registry import JobRegistry

    engine = _engine_from(request)
    if not engine.session.exists(session_id):
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": session_not_found_message(session_id)},
        )
    ok, detail = JobRegistry.instance().kill(
        job_id, requester_session_id=session_id, reason="authenticated_user_job_kill"
    )
    if not ok:
        return UTF8JSONResponse(
            status_code=409, content={"error": "job_not_killable", "detail": detail}
        )
    return UTF8JSONResponse(content={"status": "ok", "job_id": job_id, "detail": detail})


@router.get("/api/v1/sessions/{session_id}/continuity")
def session_continuity_status(session_id: str, request: Request) -> Response:
    """Expose restart-continuity facts without model text/reasoning content."""
    from llm_loop.core.interruption_resume import (
        open_execution_facts,
        select_open_checkpoint_events,
    )

    engine = _engine_from(request)
    if not engine.session.exists(session_id):
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": session_not_found_message(session_id)},
        )
    estore = getattr(engine.session, "_event_store", None)
    if estore is None or not getattr(estore, "enabled", False) or not estore.exists(session_id):
        return UTF8JSONResponse(
            content={"available": False, "open": False, "reason": "event_store_unavailable"}
        )
    try:
        events = list(estore.read(session_id) or [])
    except Exception as exc:  # noqa: BLE001 - status is read-only/fail-open
        return UTF8JSONResponse(
            status_code=500,
            content={"available": False, "open": False, "reason": type(exc).__name__},
        )
    last_run_end = max(
        (pos for pos, event in enumerate(events) if str(getattr(event, "type", "")) == "run.end"),
        default=-1,
    )
    open_events = events[last_run_end + 1 :]
    has_open_run_fact = any(
        str(getattr(event, "type", "")) == "request.meta"
        or str(getattr(event, "type", "")) == "llm.partial_checkpoint"
        or str(getattr(event, "type", "")).startswith("tool.execution.")
        or str(getattr(event, "type", "")).startswith("external.execution.")
        for event in open_events
    )
    if not has_open_run_fact:
        return UTF8JSONResponse(content={"available": True, "open": False})
    model_checkpoint, latest_checkpoint = select_open_checkpoint_events(open_events)
    mechanical = open_execution_facts(events, after_pos=last_run_end)
    chosen = model_checkpoint or latest_checkpoint
    payload = dict(getattr(chosen, "payload", None) or {}) if chosen is not None else {}
    return UTF8JSONResponse(
        content={
            "available": True,
            "open": bool(chosen is not None or mechanical),
            "source": ("open_stream_checkpoint" if chosen is not None else "open_execution_state"),
            "provider": str(payload.get("provider") or ""),
            "model": str(payload.get("model") or ""),
            "text_chars": int(payload.get("text_chars") or 0),
            "reasoning_chars": int(payload.get("reasoning_chars") or 0),
            "checkpoint_seq": int(getattr(chosen, "seq", 0) or 0) if chosen is not None else 0,
            "mechanical_execution": mechanical,
        }
    )


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
            tokens_cache_hit=getattr(
                m, "tokens_cache_hit", 0
            ),  # M58: 历史命中透传（页脚 ⚡——漏了显示 0）
            ts=getattr(m, "ts", 0.0),  # 时间戳透传（web 端消息时间显示）
            tool_calls=getattr(m, "tool_calls", None),  # 工具声明透传（历史出产物/正文链接）
            attachments=list((getattr(m, "metadata", {}) or {}).get("attachments", []))
            if getattr(m, "role", "") == "user"
            else [],
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
            content={
                "error": "archive_unavailable",
                "detail": "压缩档案不可用（未配置），无法取回原文。",
            },
        )
    try:
        entry = store.get_by_tool_call_id(session_id, tool_call_id)
    except Exception as exc:  # fail-open 如实反馈（RULE-AI-04）
        logger.exception("archive lookup failed: %s/%s", session_id, tool_call_id)
        return JSONResponse(
            status_code=500,
            content={
                "error": "archive_lookup_failed",
                "detail": f"[程序异常] 档案检索失败（{type(exc).__name__}: {exc}）。",
            },
        )
    if entry is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "archive_not_found",
                "detail": "该工具回执未归档（可能未超长或归档降级），无完整原文可取。",
            },
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
        deleted = engine.session.delete(session_id)
    except SessionExternalResourceBusyError as exc:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "external_resource_busy", "detail": str(exc)},
        )
    except SessionMutationBusyError as exc:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "session_busy", "detail": str(exc)},
        )
    except Exception as exc:
        logger.exception("session delete failed: session_id=%s", session_id)
        return UTF8JSONResponse(
            status_code=500,
            content={
                "error": "delete_failed",
                "detail": f"[程序异常] 会话删除失败（{type(exc).__name__}: {exc}）。",
            },
        )
    if not deleted:
        return UTF8JSONResponse(
            status_code=500,
            content={
                "error": "delete_failed",
                "detail": "[删除失败] 会话或关联事件/档案未能完整清理，请检查后重试。",
            },
        )

    return UTF8JSONResponse(
        content={"status": "deleted", "detail": session_deleted_message(session_id)}
    )


def _process_upload_bytes(
    engine: Any,
    *,
    workspace_scope: str,
    filename: str,
    data: bytes,
) -> UploadResponse | Response:
    """Validate, extract/describe, and persist already-decoded upload bytes."""
    err = validate_upload(filename, data)
    if err:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "invalid_upload", "detail": err},
        )

    ext = file_ext(filename)
    if ext in SUPPORTED_IMAGE_EXTS:
        from .vision import describe_image, vision_enabled

        if not vision_enabled(settings=getattr(engine, "settings", None)):
            return _persist_upload_response(
                engine,
                workspace_scope=workspace_scope,
                filename=filename,
                data=data,
                response=UploadResponse(
                    source_filename=filename,
                    content_type="image",
                    status="degraded",
                    result_text="",
                    detail="图片识别不可用（无视觉模型/工具），图片未识别且未包含在请求中。",
                ),
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
            vision_text = describe_image(
                data, mime=mime, settings=getattr(engine, "settings", None)
            )
            return _persist_upload_response(
                engine,
                workspace_scope=workspace_scope,
                filename=filename,
                data=data,
                response=UploadResponse(
                    source_filename=filename,
                    content_type="image",
                    status="ok",
                    result_text=vision_text,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - persistence remains truthful on vision failure
            logger.exception("image vision failed: %s", filename)
            return _persist_upload_response(
                engine,
                workspace_scope=workspace_scope,
                filename=filename,
                data=data,
                response=UploadResponse(
                    source_filename=filename,
                    content_type="image",
                    status="degraded",
                    detail=(
                        f"[程序异常] 图片识别失败（{type(exc).__name__}: {exc}）。"
                        "图片内容**未包含**在本次请求中——请勿让 LLM 猜测图片内容。"
                        "可设置 WEB_VISION_MODEL 指定 provider/model，或改用文本通道。"
                    ),
                ),
            )

    result = process_upload(filename, data)
    return _persist_upload_response(
        engine,
        workspace_scope=workspace_scope,
        filename=filename,
        data=data,
        response=UploadResponse(
            source_filename=result.source_filename,
            content_type=result.content_type,
            status=result.status,
            result_text=result.result_text,
            detail=result.detail,
            truncated=result.truncated,
        ),
        extracted_text=result.exact_text,
        extraction_complete=result.extraction_complete,
        extraction_kind=(f"{result.content_type}_extracted" if result.exact_text else ""),
        page_count=result.page_count,
        pages_extracted=result.pages_extracted,
    )


@router.post(
    "/api/v1/upload",
    response_model=UploadResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def upload_file(payload: UploadRequest, request: Request) -> UploadResponse | Response:
    """上传处理端点：base64 解码 → 校验 → 类型分发（文本/docx/PDF → 提取；图片 → 视觉识别）.

    不调用 engine.run。原始 bytes 持久化为 workspace-scoped opaque attachment ref；
    提取文本仅作为兼容响应/受控 excerpt，后续 chat 由服务端解析 ref。
    request: 注入以取引擎 settings（vision provider 后端注册表来源）。
    """
    engine = _engine_from(request)
    try:
        with engine.workspace_snapshot():
            upload_workspace_scope = _current_attachment_workspace_scope(engine)
    except WorkspaceBusyError as exc:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "workspace_busy", "detail": str(exc)},
        )
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
    return _process_upload_bytes(
        engine,
        workspace_scope=upload_workspace_scope,
        filename=payload.filename,
        data=data,
    )


# ── Web V2 附件面板（近期附件 + 工作区文件导入为 durable attachment ref）──


@router.get("/api/v1/attachments/recent")
def attachments_recent(request: Request, limit: int = Query(20, ge=1, le=100)) -> Response:
    """Recent workspace-scoped attachment facts; no host paths or extracted bodies."""
    engine = _engine_from(request)
    try:
        with engine.workspace_snapshot():
            scope = _current_attachment_workspace_scope(engine)
            records = _attachment_store(engine).list_recent(
                workspace_scope=scope, limit=max(1, min(int(limit or 20), 100))
            )
    except WorkspaceBusyError as exc:
        return UTF8JSONResponse(
            status_code=409, content={"error": "workspace_busy", "detail": str(exc)}
        )
    except Exception as exc:  # noqa: BLE001 - discovery is fail-open
        logger.exception("recent attachment discovery failed")
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "attachment_list_failed", "detail": type(exc).__name__},
        )
    return UTF8JSONResponse(content={"attachments": [record.public_facts() for record in records]})


@router.post("/api/v1/attachments/import-workspace", response_model=None)
def import_workspace_attachment(
    payload: WorkspaceAttachmentImportRequest, request: Request
) -> UploadResponse | Response:
    """Explicitly import one current-workspace file into the attachment contract."""
    engine = _engine_from(request)
    try:
        with engine.workspace_snapshot():
            scope = _current_attachment_workspace_scope(engine)
            target = _resolve_workspace_file(engine, payload.path)
            if target is None:
                return UTF8JSONResponse(
                    status_code=404,
                    content={
                        "error": "workspace_file_not_found",
                        "detail": "文件不存在、不是普通文件或已越出当前工作区。",
                    },
                )
            try:
                size = target.stat().st_size
            except OSError:
                size = -1
            from .upload_handlers import MAX_UPLOAD_BYTES

            if size < 0 or size > MAX_UPLOAD_BYTES:
                return UTF8JSONResponse(
                    status_code=413 if size > MAX_UPLOAD_BYTES else 400,
                    content={
                        "error": "upload_too_large"
                        if size > MAX_UPLOAD_BYTES
                        else "file_unreadable",
                        "detail": (
                            f"文件超过 10MB 上限（{size} 字节）。"
                            if size > MAX_UPLOAD_BYTES
                            else "文件不可读。"
                        ),
                    },
                )
            try:
                data = target.read_bytes()
            except OSError as exc:
                return UTF8JSONResponse(
                    status_code=403,
                    content={"error": "file_unreadable", "detail": type(exc).__name__},
                )
            return _process_upload_bytes(
                engine,
                workspace_scope=scope,
                filename=target.name,
                data=data,
            )
    except WorkspaceBusyError as exc:
        return UTF8JSONResponse(
            status_code=409, content={"error": "workspace_busy", "detail": str(exc)}
        )


# ── 出产物文件预览（Web V2 对齐 DSH deliverables：编辑的文件可点击打开） ──
_PREVIEW_ROOT = Path(__file__).resolve().parents[3]  # 项目根（与 _ui_v2_dir 同模式）
_PREVIEW_MAX_CHARS = 200_000  # 预览上限（超限截断提示，不整读）
_PREVIEW_IMAGE_MAX_BYTES = 5 * 1024 * 1024  # 图片预览上限（超限拒绝，如实提示）
_PREVIEW_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


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
    root_resolved = root.resolve()
    # 相对路径基于工作区根；绝对路径亦接受（resolve 后必须仍在根内，越界拒绝）
    raw = Path(path)
    target = raw.resolve() if raw.is_absolute() else (root_resolved / raw).resolve()
    if not target.is_relative_to(root_resolved):
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "out_of_bounds", "detail": "路径越出项目根，已拒绝。"},
        )
    # 裸文件名兜底（正文常引用 `development_methodology.md` 这类无目录前缀的文件名）：
    # 根下直接解析失败时，在工作区常见目录内按 basename 唯一匹配（多命中 → 409 歧义
    # 提示，宁可不猜不错开；防误开原则）。
    if not target.is_file() and not raw.is_absolute() and "/" not in path and "\\" not in path:
        candidates: list[Path] = []
        unsafe_matches = 0
        try:
            for base in ("docs", "src", "tests", "scripts", "skills", "webui"):
                for candidate in (root_resolved / base).rglob(path):
                    if not candidate.is_file():
                        continue
                    resolved = candidate.resolve()
                    if resolved.is_relative_to(root_resolved):
                        candidates.append(resolved)
                    else:
                        unsafe_matches += 1
        except OSError:
            candidates = []
            unsafe_matches = 0
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
        elif unsafe_matches:
            return UTF8JSONResponse(
                status_code=400,
                content={"error": "out_of_bounds", "detail": "文件名匹配到项目根外链接，已拒绝。"},
            )
    # 纵深防御：任何 fallback/未来分支最终都必须再次通过解析后根边界。
    if not target.is_relative_to(root_resolved):
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "out_of_bounds", "detail": "路径越出项目根，已拒绝。"},
        )
    # 目录 → 单层列表预览（对齐 fs/tree 语义：文档/文件夹/文件皆可点开浏览）
    if target.is_dir():
        try:
            dirs, files = [], []
            for p in sorted(target.iterdir(), key=lambda q: q.name.lower()):
                if p.name.startswith(".") or p.name == "__pycache__":
                    continue
                if p.is_dir():
                    dirs.append(p.name)
                elif p.is_file():
                    files.append({"name": p.name, "size": p.stat().st_size})
        except OSError as exc:
            logger.exception("file preview dir list failed: path=%s", path)
            return UTF8JSONResponse(
                status_code=403,
                content={
                    "error": "dir_unreadable",
                    "detail": f"目录不可读（{type(exc).__name__}）。",
                },
            )
        # parent 相对根返回（根自身/根外 → "."；前端据此隐藏"返回上级"）
        try:
            rel_parent = str(target.parent.relative_to(root_resolved)) or "."
        except ValueError:
            rel_parent = "."
        return UTF8JSONResponse(
            content={
                "type": "dir",
                "path": path,
                "parent": rel_parent,
                "dirs": dirs[:500],
                "files": files[:500],
            }
        )
    # 图片 → base64 内联预览（≤5MB；前端 data:image/ URI 渲染，img 上下文不执行脚本）
    mime = _PREVIEW_IMAGE_MIME.get(target.suffix.lower())
    if mime:
        import base64

        try:
            blob = target.read_bytes()
        except OSError as exc:
            logger.exception("file preview image read failed: path=%s", path)
            return UTF8JSONResponse(
                status_code=500,
                content={
                    "error": "read_failed",
                    "detail": f"[程序异常] 读取失败（{type(exc).__name__}）。",
                },
            )
        if len(blob) > _PREVIEW_IMAGE_MAX_BYTES:
            return UTF8JSONResponse(
                status_code=413,
                content={
                    "error": "image_too_large",
                    "detail": f"图片 {len(blob)} 字节超预览上限 5MB。",
                },
            )
        return UTF8JSONResponse(
            content={
                "type": "image",
                "path": path,
                "size": len(blob),
                "mime": mime,
                "content_base64": base64.b64encode(blob).decode("ascii"),
            }
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
            content={
                "error": "read_failed",
                "detail": f"[程序异常] 读取失败（{type(exc).__name__}）。",
            },
        )
    truncated = len(raw) > _PREVIEW_MAX_CHARS
    return UTF8JSONResponse(
        content={
            "type": "text",
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
    metas = engine.session.list_sessions_in(Path(engine.settings.sessions_dir) / ws.id)
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
    prepared_sessions_dir: Path | None = None

    def prepare_runtime(ws: Any) -> None:
        nonlocal prepared_sessions_dir
        prepared_sessions_dir = engine.prepare_workspace(ws.path, ws.id)

    try:
        with engine.workspace_transition():
            ws = store.register_and_switch(path, precommit=prepare_runtime)
            engine.set_workspace(ws.path, ws.id, prepared_sessions_dir=prepared_sessions_dir)
    except WorkspaceBusyError as exc:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "workspace_busy", "detail": str(exc)},
        )
    except WorkspacePersistenceError as exc:
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "workspace_persist_failed", "detail": str(exc)},
        )
    except OSError as exc:
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "workspace_runtime_prepare_failed", "detail": str(exc)},
        )
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
    prepared_sessions_dir: Path | None = None

    def prepare_runtime(ws: Any) -> None:
        nonlocal prepared_sessions_dir
        prepared_sessions_dir = engine.prepare_workspace(ws.path, ws.id)

    try:
        with engine.workspace_transition():
            ws = store.switch(body.id, precommit=prepare_runtime)
            engine.set_workspace(ws.path, ws.id, prepared_sessions_dir=prepared_sessions_dir)
    except WorkspaceBusyError as exc:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "workspace_busy", "detail": str(exc)},
        )
    except WorkspacePersistenceError as exc:
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "workspace_persist_failed", "detail": str(exc)},
        )
    except WorkspacePathUnavailableError as exc:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "workspace_path_unavailable", "detail": str(exc)},
        )
    except OSError as exc:
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "workspace_runtime_prepare_failed", "detail": str(exc)},
        )
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
    try:
        removed = store.remove(workspace_id)
    except WorkspacePersistenceError as exc:
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "workspace_persist_failed", "detail": str(exc)},
        )
    if not removed:
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


# --- Capability manifest ---------------------------------------------------
# 只声明"本后端注册了哪些产品路由"这一机械事实，供前端一次拉取，
# 替代启动期 404/405 路由探测。不表达策略、健康度或业务判断。
_CAPABILITY_ROUTES: dict[str, tuple[tuple[str, str], ...]] = {
    "attachments": (
        ("GET", "/api/v1/attachments/recent"),
        ("POST", "/api/v1/attachments/import-workspace"),
    ),
    "fsTree": (("GET", "/api/v1/fs/tree"),),
    "pin": (("POST", "/api/v1/sessions/{session_id}/pin"),),
    "archive": (("POST", "/api/v1/sessions/{session_id}/archive"),),
    "delete": (("DELETE", "/api/v1/sessions/{session_id}"),),
    "fork": (("POST", "/api/v1/sessions/{session_id}/fork"),),
    "feedback": (("POST", "/api/v1/sessions/{session_id}/feedback"),),
    "jobs": (
        ("GET", "/api/v1/sessions/{session_id}/jobs"),
        ("POST", "/api/v1/sessions/{session_id}/jobs/{job_id}/kill"),
    ),
    "continuity": (("GET", "/api/v1/sessions/{session_id}/continuity"),),
}


@router.get("/api/v1/capabilities")
def api_capabilities(request: Request) -> Response:
    """Read-only capability manifest derived from actually registered routes."""
    registered: set[tuple[str, str]] = set()

    def _walk(routes) -> None:
        for route in routes:
            # FastAPI>=0.141 include_router 产出 _IncludedRouter 包装对象，
            # 递归展开其原始 router 以兼容直挂与包装两种结构。
            sub = getattr(route, "original_router", None)
            if sub is not None and hasattr(sub, "routes"):
                _walk(sub.routes)
                continue
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if path and methods:
                for method in methods:
                    registered.add((method, path))

    _walk(request.app.routes)
    capabilities = {
        key: all(pair in registered for pair in pairs) for key, pairs in _CAPABILITY_ROUTES.items()
    }
    return UTF8JSONResponse(content={"capabilities": capabilities})

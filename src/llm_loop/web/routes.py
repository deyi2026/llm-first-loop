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
import time
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
from pydantic import BaseModel, Field

from llm_loop.core.loop.runner import (
    QueuedIngressDurabilityError,
    RunGenerationMismatchError,
    SessionBusyError,
)
from llm_loop.core.session import SessionExternalResourceBusyError, SessionMutationBusyError
from llm_loop.feedback.honesty import (
    append_feedback,
    session_deleted_message,
    session_not_found_message,
)
from llm_loop.knowledge_score.ledger import KnowledgeScoreLedger
from llm_loop.knowledge_score.pending import scan_pending
from llm_loop.knowledge_score.runner import read_runner_state
from llm_loop.runtime.admission_barrier import (
    ServiceAdmissionBarrier,
    task_admission_barrier,
)
from llm_loop.timekeeping import system_local_now
from llm_loop.workspace.artifacts import ArtifactError, WorkspaceArtifactStore
from llm_loop.workspace.store import (
    WorkspaceBusyError,
    WorkspaceChangedError,
    WorkspacePathUnavailableError,
    WorkspacePersistenceError,
)

from .attachments import AttachmentError, AttachmentStore
from .attachments import workspace_scope as attachment_workspace_scope
from .human_turn_queue import HumanTurnQueue, QueuePersistError
from .local_runtime_admin import router as local_runtime_router
from .provider_routes import router as provider_admin_router
from .schemas import (
    ChatCancelRequest,
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    EvolutionReviewRequest,
    FeedbackRequest,
    MessageItem,
    QueueCancelRequest,
    QueueDispatchRequest,
    QueueEnqueueRequest,
    QueueInterjectRequest,
    QueueReleaseRequest,
    SessionListResponse,
    SessionMessagesResponse,
    SessionMetaItem,
    UploadRequest,
    UploadResponse,
    WorkspaceAttachmentImportRequest,
    WorkspaceRequest,
    WorkspaceSwitchRequest,
)
from .task_budget_canary import choose_signed_web_canary
from .upload_handlers import (
    SUPPORTED_IMAGE_EXTS,
    file_ext,
    process_upload,
    validate_upload,
    validate_upload_b64_size,
)

logger = logging.getLogger(__name__)

router = APIRouter()

router.include_router(provider_admin_router)
router.include_router(local_runtime_router)


def _attachment_store(engine: Any) -> AttachmentStore:
    data_dir = getattr(getattr(engine, "settings", None), "data_dir", "./data")
    return AttachmentStore(data_dir)


_BARRIER_QUEUE_CAP = 20


def _service_restart_barrier(
    request: Request, task_kind: str
) -> ServiceAdmissionBarrier | None:
    """§8.2 消息准入屏障（只读）：本任务声明的依赖服务是否有重启屏障.

    依赖范围来自 ``TASK_ADMISSION_DEPENDENCIES`` 闭表（缺口②统一注册表），
    调用点不再各自指定服务名。读失败 fail-open（可用性优先，日志告警）：
    屏障目录不存在是常态路径，物理性不可读属运行异常，由状态视图/CLI 兜
    底，不在消息热路径炸服务。
    """
    engine = _engine_from(request)
    data_dir = getattr(getattr(engine, "settings", None), "data_dir", "./data")
    try:
        return task_admission_barrier(Path(data_dir).expanduser(), task_kind)
    except KeyError:
        raise  # 编码错误：未登记的任务种类必须当场暴露
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.warning("service admission barrier check failed (fail-open): %s", exc)
        return None


def _log_barrier_rejection(request: Request, task_kind: str, barrier: ServiceAdmissionBarrier) -> None:
    """R3(P7): 准入拒绝 append-only 留痕（fail-open，不阻断回执路径）.

    07:49 用户撞屏障窗口期只收到排队回执、actions 目录零痕迹——审计
    线完全缺失。只在实际拒绝/排队的边界调用，不在轮询探测处调用。
    """
    try:
        from llm_loop.runtime.admission_barrier import log_admission_rejection

        engine = _engine_from(request)
        data_dir = getattr(getattr(engine, "settings", None), "data_dir", "./data")
        log_admission_rejection(
            Path(data_dir).expanduser(), task_kind, barrier, source="web"
        )
    except Exception:  # noqa: BLE001 — 审计失败不影响消息路径
        logger.debug("barrier rejection audit failed", exc_info=True)


def _barrier_queued_response(
    request: Request,
    session_id: str,
    message: str,
    barrier: ServiceAdmissionBarrier,
    *,
    task_kind: str = "",
    status_code: int = 202,
    extra: dict | None = None,
) -> Response:
    """屏障期排队回执（§8.2-2/§8.2-5）：durable 入队 + 带操作号的回执.

    容量上限 _BARRIER_QUEUE_CAP：超限拒绝（显式 queue_full 回执），
    不静默丢弃、不无界堆积。与 /chat/queue 同冻结事实字段。
    """
    if task_kind:
        _log_barrier_rejection(request, task_kind, barrier)
    hq = _human_turn_queue(request)
    active = hq.list_active(session_id)
    if sum(1 for it in active if it.get("status") == "queued") >= _BARRIER_QUEUE_CAP:
        return UTF8JSONResponse(
            status_code=503,
            content={
                "error": "queue_full",
                "detail": (
                    "服务重启窗口中且排队已达上限（"
                    f"{_BARRIER_QUEUE_CAP} 条）；请稍后重试或重新发送。"
                ),
                "restart_barrier": barrier.to_view(),
            },
        )
    # SPEC-20260923-queue-recovery：承诺"恢复后自动继续"的地方打上机械来源
    # 标记（origin=barrier_window + 操作号）——恢复重排只认标记项，不解析文本。
    item = hq.enqueue(
        session_id,
        message,
        origin="barrier_window",
        origin_operation_id=str(barrier.operation_id or ""),
    )
    content = {
        "queued": True,
        "queue_id": item["queue_id"],
        "item": item,
        "restart_barrier": barrier.to_view(),
        "detail": (
            "服务重启窗口中（操作 "
            f"{barrier.operation_id}）：消息已持久化排队，恢复后自动继续。"
        ),
    }
    if extra:
        content.update(extra)
    return UTF8JSONResponse(status_code=status_code, content=content)


def _human_turn_queue(request: Request) -> HumanTurnQueue:
    """Human Turn 队列单例（按 data_dir 缓存在 app.state；JSON 落盘为 durable 事实）."""
    engine = _engine_from(request)
    data_dir = getattr(getattr(engine, "settings", None), "data_dir", "./data")
    key = str(Path(data_dir).expanduser().resolve())
    store = getattr(request.app.state, "human_turn_queues", None)
    if store is None:
        store = {}
        request.app.state.human_turn_queues = store
    q = store.get(key)
    if q is None:
        q = HumanTurnQueue(
            data_dir,
            claim_state_probe=lambda sid, qid: _queue_claim_state(engine, sid, qid),
        )
        store[key] = q
    return q


def _queue_claim_state(engine: Any, session_id: str, queue_id: str) -> str:
    """Resolve one stale claim from formal run + EventStore facts only."""
    runner = getattr(engine, "runner", None)
    try:
        if runner is not None and (
            bool(runner.is_running(session_id)) or bool(runner.is_sync_active(session_id))
        ):
            return "active"
    except Exception:  # noqa: BLE001 - uncertainty is never replay authority
        return "unknown"

    # Cross-process whole-run lease is the formal activity truth. A shared management
    # lease can be acquired only when no exclusive run lease is active.
    try:
        with engine.session.management_lease(session_id):
            pass
    except SessionMutationBusyError:
        return "active"
    except Exception:  # noqa: BLE001 - lock uncertainty fails closed
        return "unknown"

    store = getattr(engine, "_event_store", None)
    if store is None or getattr(store, "enabled", False) is False:
        return "unknown"
    try:
        events = getattr(store, "read_cached", store.read)(session_id)
        if int(getattr(store, "last_read_skipped", 0) or 0) > 0:
            return "unknown"
    except Exception:  # noqa: BLE001 - corrupt/unreadable evidence cannot authorize replay
        return "unknown"

    matches: list[tuple[int, Any]] = []
    for pos, event in enumerate(events):
        if str(getattr(event, "type", "")) != "message.appended":
            continue
        payload = getattr(event, "payload", {}) or {}
        metadata = payload.get("metadata") if isinstance(payload, dict) else None
        if (
            isinstance(metadata, dict)
            and str(metadata.get("human_turn_queue_id") or "") == queue_id
            and str(payload.get("role") or "") == "user"
        ):
            matches.append((pos, event))
    if not matches:
        # Queued runs fail closed before any LLM/tool call when this exact ingress event
        # cannot be persisted; absence is therefore proof that execution never crossed
        # the queued-human durable boundary.
        return "not_started"
    if len(matches) != 1:
        return "unknown"

    start_pos = matches[0][0]
    for event in events[start_pos + 1 :]:
        event_type = str(getattr(event, "type", ""))
        payload = getattr(event, "payload", {}) or {}
        if event_type == "run.end":
            return "completed" if str(payload.get("reason") or "") == "completed" else "failed"
        if event_type == "message.appended" and isinstance(payload, dict):
            md = payload.get("metadata")
            if (
                str(payload.get("role") or "") == "user"
                and isinstance(md, dict)
                and not bool(md.get("program_origin"))
                and not bool(md.get("ingress_delegated"))
            ):
                # A later genuine human turn before a run.end makes correlation
                # ambiguous; never guess which run the later terminal belongs to.
                return "unknown"
    return "ingress_open"


def _queue_claim_matches(
    payload: ChatRequest, claimed: dict[str, Any], attachment_facts: list[dict[str, Any]]
) -> bool:
    """Exact mechanical handoff check: queue_id cannot authorize different request bytes."""
    payload_refs = [str(getattr(ref, "ref", "") or "") for ref in payload.attachments]
    frozen_refs = [
        str(ref.get("ref") or "")
        for ref in claimed.get("attachments", [])
        if isinstance(ref, dict)
    ]
    return bool(
        str(claimed.get("message") or "") == payload.message
        and frozen_refs == payload_refs
        and list(claimed.get("attachment_facts") or []) == list(attachment_facts)
        and (claimed.get("model") or None) == (payload.model or None)
        and bool(claimed.get("model_change", False)) == bool(payload.model_change)
        and (claimed.get("reasoning_effort") or None) == (payload.reasoning_effort or None)
        and str(claimed.get("reasoning_mode") or "auto") == str(payload.reasoning_mode or "auto")
    )


def _current_attachment_workspace_scope(engine: Any) -> str:
    return attachment_workspace_scope(getattr(engine, "workspace_root", "") or None)


def _resolve_workspace_file(engine: Any, raw_path: str) -> Path | None:
    """Resolve one ordinary file inside the current workspace (no escape)."""
    root = Path(
        getattr(engine, "workspace_root", "") or Path(__file__).resolve().parents[3]
    ).expanduser().resolve()
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


def _history_runtime_receipt_fields(message: Any) -> dict[str, Any]:
    """Project only the whitelisted UI receipt from provider-invisible message metadata."""
    metadata = getattr(message, "metadata", {})
    if not isinstance(metadata, dict):
        return {}
    raw = metadata.get("runtime_receipt")
    if not isinstance(raw, dict):
        return {}

    fields: dict[str, Any] = {}
    fallback = raw.get("fallback_receipt")
    if isinstance(fallback, dict):
        fields["fallback_receipt"] = {str(k): str(v) for k, v in fallback.items()}
    for key in ("reasoning_mode", "reasoning_control"):
        value = raw.get(key)
        if isinstance(value, str):
            fields[key] = value
    for key in ("reasoning_capable", "reasoning_supported", "reasoning_effective"):
        value = raw.get(key)
        if isinstance(value, bool):
            fields[key] = value
    reasoning_tokens = raw.get("reasoning_tokens")
    if isinstance(reasoning_tokens, int) and not isinstance(reasoning_tokens, bool):
        fields["reasoning_tokens"] = reasoning_tokens
    return fields

# EVO-20260818: 文件树/会话树 API（独立模块 fs_tree.py，安全边界+审计）
from llm_loop.web.file_routes import file_router  # noqa: E402
from llm_loop.web.fs_tree import fs_router  # noqa: E402 — 延迟导入防循环（与下方 approve 同模式）

router.include_router(fs_router)
router.include_router(file_router)

# EVO-20260818: web 演进审批（复用飞书 approval.py 状态机+幂等+flock 锁）
from llm_loop.feishu.approval import approve, reject  # noqa: E402

SERVICE_NAME = "llm-first-loop-web"
SERVICE_VERSION = "0.6.32"  # T7: 语义化版本；由版本一致性测试约束与 pyproject 同步


class UTF8JSONResponse(JSONResponse):
    """强制 UTF-8 声明：content-type 带 charset=utf-8，杜绝中文按默认编码（如 GBK）误解码."""

    media_type = "application/json; charset=utf-8"


# 出产物文件预览路由（对齐 DSH workspace-files/documentpreview）：独立模块，
# 在 UTF8JSONResponse 定义之后导入（preview_routes 顶部 from routes import 它）
from llm_loop.web.preview_routes import (  # noqa: E402 — 延迟导入防循环（与 fs_router 同模式）
    preview_router,
)

router.include_router(preview_router)


def _engine_from(request: Request) -> Any:
    """从 app.state 取单引擎实例（装配一次复用全部请求，不每请求重建）."""
    return request.app.state.engine


@router.get("/api/v1/learning/status")
def learning_status(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> Response:
    """Read-only Learning Plane observability without exposing hidden reasoning."""
    engine = _engine_from(request)
    journal = getattr(engine, "learning_journal", None)
    jobs = []
    # EVO-20261013-2: journal 读取失败仍 fail-open，但显式暴露降级信号（不再伪装成全 0/空）
    observability_errors: list[str] = []
    if journal is not None:
        try:
            for job in journal.recent_jobs(limit=limit):
                jobs.append(
                    {
                        "job_id": job.job_id,
                        "source_episode_ref": job.source_episode_ref,
                        "source_session_id": job.session_id,
                        "source_model": job.source_model,
                        "state": job.state,
                        "attempt": job.attempt,
                        "candidate_ref": job.candidate_ref or None,
                        "reason": job.reason or None,
                        "created_at": job.created_at,
                        "updated_at": job.updated_at or job.created_at,
                        "started_at": job.started_at or None,
                        "finished_at": job.finished_at or None,
                        # Only mechanical trigger facts are surfaced. Raw hidden reasoning is never stored here.
                        "trigger_facts": dict(job.trigger_facts or {}),
                    }
                )
        except Exception:  # noqa: BLE001 - observability must never break chat serving
            logger.warning("learning status journal read failed", exc_info=True)
            observability_errors.append("jobs")

    # 全历史口径（EVO 2026-09-24）：terminal 态单调累计（saved 不再随窗口滚动回退），
    # in-flight 态即当前在飞；count_states 不可得时 fail-open 回退窗口口径。
    counts: dict[str, int] = {}
    if journal is not None:
        try:
            counts = dict(journal.count_states())
        except Exception:  # noqa: BLE001 - observability must never break chat serving
            logger.warning("learning status count_states failed", exc_info=True)
            observability_errors.append("count_states")
    if not counts:
        for row in jobs:
            state = str(row.get("state") or "unknown")
            counts[state] = counts.get(state, 0) + 1

    settings = getattr(engine, "settings", None)
    data_dir = Path(getattr(settings, "data_dir", "./data")).expanduser()
    manifest_path = data_dir / "runtime" / "runtime_manifest.learning.json"
    worker: dict[str, Any] = {"running": False, "manifest_present": manifest_path.is_file()}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            pid = int(manifest.get("pid") or 0)
            running = False
            if pid > 0:
                try:
                    os.kill(pid, 0)
                    running = True
                except PermissionError:
                    # EPERM：进程存在但属主不同，不能据此判定未运行（EVO-20261013-2）
                    running = True
                except OSError:
                    running = False
            worker.update(
                {
                    "running": running,
                    "pid": pid or None,
                    "started_at": manifest.get("started_at"),
                    "git_head": manifest.get("git_head"),
                    "build": manifest.get("build_identity") or {},
                    "model_ref": manifest.get("model_ref"),
                    "provider_id": manifest.get("provider_id"),
                }
            )
        except Exception:  # noqa: BLE001
            worker["manifest_error"] = True

    # EVO-20261013 队列可观测性：排队数之外的三个显化维度——
    # ① 最老排队任务等待时长（积压严重度）② worker 准入状态心跳（为什么不动）
    # ③ requeue 原因统计（慢性抢占史）。全部只读、fail-open。
    oldest_queued: dict[str, Any] | None = None
    if journal is not None:
        try:
            oldest_queued = journal.oldest_queued()
        except Exception:  # noqa: BLE001 - observability must never break chat serving
            logger.warning("learning status oldest_queued failed", exc_info=True)
            observability_errors.append("oldest_queued")

    admission: dict[str, Any] = {"present": False}
    heartbeat_path = data_dir / "runtime" / "learning_admission.json"
    if heartbeat_path.is_file():
        try:
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            hb_ts = float(heartbeat.get("ts") or 0.0)
            admission = {
                "present": True,
                "state": str(heartbeat.get("state") or "unknown"),
                "reason": str(heartbeat.get("reason") or "") or None,
                "since": heartbeat.get("since"),
                "ts": heartbeat.get("ts"),
                "queued": int(heartbeat.get("queued") or 0),
                # 心跳新鲜度：worker 存活但 >60s 未刷新按 stale 呈现（不误判为阻塞）
                "age_seconds": round(max(0.0, time.time() - hb_ts), 1) if hb_ts else None,
                "stale": bool(hb_ts and (time.time() - hb_ts) > 60.0),
            }
        except Exception:  # noqa: BLE001
            admission = {"present": False, "parse_error": True}

    requeue_stats: dict[str, Any] = {}
    if journal is not None:
        try:
            requeue_stats = journal.requeue_stats()
        except Exception:  # noqa: BLE001 - observability must never break chat serving
            logger.warning("learning status requeue_stats failed", exc_info=True)
            observability_errors.append("requeue_stats")

    return JSONResponse(
        {
            "enabled": bool(getattr(settings, "learning_plane_enabled", False)),
            "producer_only": getattr(engine, "learning_plane", None) is None,
            "worker": worker,
            "counts": counts,
            "jobs": jobs,
            "oldest_queued": oldest_queued,
            "admission": admission,
            "requeue_stats": requeue_stats,
            "observability_errors": observability_errors,  # EVO-20261013-2: 降级信号，空列表=读取正常
        }
    )


def _evolution_store_from(engine: Any) -> Any | None:
    """解析 production EvolutionStore authority（factory.py 唯一装配位置）.

    修复（EVO-20260909 web 审批确认键无效）：真实引擎只在 correction_ctx 上持有 store，
    P6 起不再接受历史 ``engine.evolution_store`` 挂载作为审批写 authority。
    """
    ctx = getattr(engine, "correction_ctx", None)
    return getattr(ctx, "evolution_store", None)


# ---------- EVO-20261013 知识管理视图（经验/方法全生命周期） ----------


def _knowledge_stores(engine: Any) -> tuple[Any | None, Any | None]:
    """解析生产 ExperienceStore/MethodStore authority（factory 装配在 corrections registry）."""
    corrections = getattr(engine, "corrections", None)
    return (
        getattr(corrections, "_experience_store", None),
        getattr(corrections, "_method_store", None),
    )


_EXPERIENCE_LIFECYCLE_TARGETS = {
    # 与模型工具 run_refine_experience 的 action_map 完全一致（invalidate → invalid）
    "archive": "archived",
    "invalidate": "invalid",
    "restore": "active",
}


def _normalize_experience_ref(experience_ref: str) -> str:
    """Normalize public `experience:`/`.md` forms to the store's canonical stem."""
    value = str(experience_ref or "").strip()
    if value.startswith("experience:"):
        value = value.split(":", 1)[1].strip()
    if value.endswith(".md"):
        value = value[:-3]
    return value

_METHOD_TRANSITION_TARGETS = {
    "qualify": "qualified",
    "activate": "active",
    "hold": "hold",
    "invalidate": "invalidated",
    "retire": "retired",
    "reopen": "candidate",
}


@router.get("/api/v1/knowledge/experiences")
def knowledge_experiences(
    request: Request,
    query: str = Query(default=""),
    status: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=500),
) -> Response:
    """经验库管理视图：全生命周期状态分组 + 列表（含 archived/invalidated，只读）."""
    engine = _engine_from(request)
    store, _ = _knowledge_stores(engine)
    if store is None:
        return UTF8JSONResponse(
            status_code=503, content={"error": "experience_store_unavailable"}
        )
    try:
        view = store.catalog(query=query.strip(), limit=limit, status=status.strip())
    except Exception as exc:  # noqa: BLE001 - 管理视图不可得时如实 5xx
        logger.warning("knowledge experiences catalog failed: %s", type(exc).__name__, exc_info=True)
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "experience_catalog_failed", "detail": f"{type(exc).__name__}: {exc}"},
        )
    return UTF8JSONResponse(view)


@router.get("/api/v1/knowledge/experiences/{experience_id}")
def knowledge_experience_detail(request: Request, experience_id: str) -> Response:
    """单条经验详情：hydrated 卡 + 正文（只读，供管理页展开审阅）."""
    engine = _engine_from(request)
    store, _ = _knowledge_stores(engine)
    if store is None:
        return UTF8JSONResponse(
            status_code=503, content={"error": "experience_store_unavailable"}
        )
    stem = _normalize_experience_ref(experience_id)
    if not stem:
        return UTF8JSONResponse(status_code=422, content={"error": "invalid_experience_id"})
    try:
        doc = store.get(stem)
    except Exception as exc:  # noqa: BLE001
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "experience_get_failed", "detail": f"{type(exc).__name__}: {exc}"},
        )
    if doc is None:
        return UTF8JSONResponse(status_code=404, content={"error": "experience_not_found"})
    record = store.to_hydrated_record(stem, doc)
    record["body"] = doc.body
    return UTF8JSONResponse(record)


@router.post("/api/v1/knowledge/experiences/{experience_id}/lifecycle")
def knowledge_experience_lifecycle(
    request: Request, experience_id: str, action: str = Query(default="")
) -> Response:
    """经验生命周期操作（人工管理权威）：archive/invalidate/restore.

    复用模型工具同一条 store.update_status 路径，状态语义与审计留痕一致；
    非法 action 显式 4xx，不静默吞错。
    """
    engine = _engine_from(request)
    store, _ = _knowledge_stores(engine)
    if store is None:
        return UTF8JSONResponse(
            status_code=503, content={"error": "experience_store_unavailable"}
        )
    target = _EXPERIENCE_LIFECYCLE_TARGETS.get((action or "").strip().lower())
    if target is None:
        return UTF8JSONResponse(
            status_code=422,
            content={
                "error": "invalid_action",
                "detail": f"action must be one of {sorted(_EXPERIENCE_LIFECYCLE_TARGETS)}",
            },
        )
    stem = _normalize_experience_ref(experience_id)
    if not stem:
        return UTF8JSONResponse(status_code=422, content={"error": "invalid_experience_id"})
    try:
        updated = store.update_status(stem, target)
    except Exception as exc:  # noqa: BLE001 - store 拒绝/IO 失败如实上报
        logger.warning("knowledge experience lifecycle failed: %s", type(exc).__name__, exc_info=True)
        return UTF8JSONResponse(
            status_code=409,
            content={
                "error": "experience_lifecycle_failed",
                "detail": f"{type(exc).__name__}: {exc}",
            },
        )
    if not updated:
        return UTF8JSONResponse(status_code=404, content={"error": "experience_not_found"})
    doc = store.get(stem)
    return UTF8JSONResponse(
        {
            "experience_id": stem,
            "action": (action or "").strip().lower(),
            "status": getattr(doc, "status", target),
        }
    )


@router.get("/api/v1/knowledge/methods")
def knowledge_methods(
    request: Request,
    query: str = Query(default=""),
    status: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=500),
) -> Response:
    """方法库管理视图：全生命周期状态分组 + 列表（含 retired/invalidated，只读）."""
    engine = _engine_from(request)
    _, store = _knowledge_stores(engine)
    if store is None:
        return UTF8JSONResponse(status_code=503, content={"error": "method_store_unavailable"})
    try:
        view = store.inventory(query=query.strip(), limit=limit, status=status.strip())
    except Exception as exc:  # noqa: BLE001 - 管理视图不可得时如实 5xx
        logger.warning("knowledge methods inventory failed: %s", type(exc).__name__, exc_info=True)
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "method_inventory_failed", "detail": f"{type(exc).__name__}: {exc}"},
        )
    return UTF8JSONResponse(view)


@router.get("/api/v1/knowledge/methods/{method_id}")
def knowledge_method_detail(request: Request, method_id: str) -> Response:
    """单条方法详情：hydrated 卡 + qualification/use 信号（只读，供管理页展开审阅）."""
    engine = _engine_from(request)
    _, store = _knowledge_stores(engine)
    if store is None:
        return UTF8JSONResponse(status_code=503, content={"error": "method_store_unavailable"})
    if not method_id.startswith("method:"):
        method_id = f"method:{method_id}"
    try:
        record = store.get(method_id)
    except Exception as exc:  # noqa: BLE001
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "method_get_failed", "detail": f"{type(exc).__name__}: {exc}"},
        )
    if record is None:
        return UTF8JSONResponse(status_code=404, content={"error": "method_not_found"})
    hydrated = record.hydrated()
    store._attach_last_signal_age(hydrated, record)
    hydrated["qualification_entries"] = store.qualification_entries(method_id)
    hydrated["freshness"] = store.freshness(method_id)
    return UTF8JSONResponse(hydrated)


@router.post("/api/v1/knowledge/methods/{method_id}/transition")
def knowledge_method_transition(
    request: Request, method_id: str, transition: str = Query(default="")
) -> Response:
    """方法生命周期流转（人工管理权威）：qualify/activate/hold/invalidate/retire/reopen.

    复用模型工具同一 store.update_status 路径；qualify/activate 不设资格前置条件，
    invalidate/retire 仍需处置依据。状态不构成使用许可，非法流转如实返回 409。
    """
    engine = _engine_from(request)
    _, store = _knowledge_stores(engine)
    if store is None:
        return UTF8JSONResponse(status_code=503, content={"error": "method_store_unavailable"})
    target = _METHOD_TRANSITION_TARGETS.get((transition or "").strip().lower())
    if target is None:
        return UTF8JSONResponse(
            status_code=422,
            content={
                "error": "invalid_transition",
                "detail": f"transition must be one of {sorted(_METHOD_TRANSITION_TARGETS)}",
            },
        )
    if not method_id.startswith("method:"):
        method_id = f"method:{method_id}"
    try:
        store.update_status(method_id, target)
    except Exception as exc:  # noqa: BLE001 - 门禁拒绝/IO 失败如实上报
        logger.warning("knowledge method transition failed: %s", type(exc).__name__, exc_info=True)
        return UTF8JSONResponse(
            status_code=409,
            content={
                "error": "method_transition_failed",
                "detail": f"{type(exc).__name__}: {exc}",
            },
        )
    record = store.get(method_id)
    return UTF8JSONResponse(
        {
            "method_id": method_id,
            "transition": (transition or "").strip().lower(),
            "status": getattr(record, "status", target),
        }
    )


def _web_data_dir(engine: Any) -> Path:
    """Resolve Web route storage from the already-resolved engine settings authority."""
    return Path(getattr(getattr(engine, "settings", None), "data_dir", "./data")).expanduser().resolve()


# ---------- 阶段2: 知识打分只读聚合视图（知识管理页徽标 + 打分明细页签） ----------

# 徽标摘要字段（sidecar schema knowledge-score-sidecar/v1 的展示投影）
_SCORE_SUMMARY_FIELDS = (
    "top_label",
    "top_level",
    "confidence",
    "expected",
    "p_evidence_sufficient",
    "scored_slots",
    "last_scored_at",
    "evidence_level",
    "scorer_model",
)


def _read_score_sidecars(cards_dir: Path) -> dict[str, dict]:
    """读取全部打分 sidecar（<data>/knowledge_scores/cards/*.json）→ ref → 徽标摘要.

    逐文件隔离：单份损坏（IO/JSON/UTF-8 解码失败、非对象、缺 ref）跳过该文件
    不整体失败，对齐阶段1逐卡隔离语义；目录不存在视为尚无 sidecar（空索引）。
    """
    summaries: dict[str, dict] = {}
    if not cards_dir.is_dir():
        return summaries
    for path in sorted(cards_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        # ValueError 涵盖 JSONDecodeError 与 UnicodeDecodeError（二进制损坏 sidecar）
        except (OSError, ValueError) as exc:
            logger.warning("score sidecar unreadable, skipped: %s: %s", path.name, exc)
            continue
        if not isinstance(payload, dict):
            logger.warning("score sidecar not an object, skipped: %s", path.name)
            continue
        ref = str(payload.get("ref") or "")
        if not ref:
            continue
        summaries[ref] = {field: payload.get(field) for field in _SCORE_SUMMARY_FIELDS}
    return summaries


@router.get("/api/v1/knowledge/scores")
def knowledge_scores_index(request: Request) -> Response:
    """知识打分只读聚合：ledger 明细（ts 倒序）+ 徽标索引（sidecar 优先）.

    只读端点：不调打分服务、不写任何文件。数据落点与 CLI
    scripts/knowledge_score.py 一致（<root>/data/knowledge_scores，web 侧由
    settings.data_dir 权威解析）；数据未产生（文件缺失或为空）返回空结构
    200 而非 5xx，读取异常（IO/解析）如实 500。
    """
    engine = _engine_from(request)
    scores_dir = _web_data_dir(engine) / "knowledge_scores"
    ledger = KnowledgeScoreLedger(scores_dir / "ledger.jsonl")
    try:
        entries = ledger.read()  # 旧→新；损坏行沿用账本扫描的跳过语义
        scores: dict[str, dict] = _read_score_sidecars(scores_dir / "cards")
    except Exception as exc:  # noqa: BLE001 - 管理视图不可得时如实 5xx
        logger.warning("knowledge scores aggregate failed: %s", type(exc).__name__, exc_info=True)
        return UTF8JSONResponse(
            status_code=500,
            content={
                "error": "knowledge_scores_failed",
                "detail": f"{type(exc).__name__}: {exc}",
            },
        )
    for row in reversed(entries):  # 新→旧、先见者胜出 → 无 sidecar 的 ref 取 ledger 最新一条成功行
        ref = str(row.get("ref") or "")
        if not ref or ref in scores:
            continue
        if not str(row.get("top_label") or ""):
            continue  # error 行无打分结果（top_label 为空），不进徽标索引
        scores[ref] = {
            "top_label": row.get("top_label"),
            "top_level": row.get("top_level"),
            "confidence": row.get("confidence"),
            "expected": row.get("expected"),
            "p_evidence_sufficient": row.get("p_evidence_sufficient"),
            "scored_slots": 1,  # ledger 行即单 slot 打分；累计值只有 sidecar 才有
            "last_scored_at": row.get("ts"),
            "evidence_level": "",
            "scorer_model": row.get("scorer_model"),
        }
    ledger_rows = [
        {
            "ledger_seq": row.get("ledger_seq"),
            "ref": row.get("ref"),
            "kind": row.get("kind"),
            "adopted": row.get("adopted"),
            "top_label": row.get("top_label"),
            "top_level": row.get("top_level"),
            "confidence": row.get("confidence"),
            "expected": row.get("expected"),
            "p_evidence_sufficient": row.get("p_evidence_sufficient"),
            "decision_reported": row.get("decision_reported"),
            "error": row.get("error"),
            "ts": row.get("ts"),
            "scorer_model": row.get("scorer_model"),
        }
        for row in entries
    ]
    ledger_rows.sort(key=lambda r: (str(r.get("ts") or ""), r.get("ledger_seq") or 0), reverse=True)
    root = scores_dir.parent.parent
    try:
        pending: int | None = len(scan_pending(root, limit=None))
        pending_error = None
    except Exception as exc:  # noqa: BLE001 - 待办统计失败不拖垮已可读的打分明细
        pending = None
        pending_error = f"{type(exc).__name__}: {exc}"
        logger.warning("knowledge scores pending count failed: %s", pending_error)
    return UTF8JSONResponse(
        {
            "count": len(entries),
            "scores": scores,
            "ledger": ledger_rows,
            "pending": pending,
            "pending_error": pending_error,
            "runner": read_runner_state(root),
        }
    )


# TASK-005: 受管服务 desired/live/stable 身份视图（与 service_control 工具同一 composer 单一数据源）
from llm_loop.runtime.service_control import (  # noqa: E402
    ManagedServiceDeploymentStore,
    compose_service_identity_view,
)


@router.get("/api/v1/services/status")
def services_status(request: Request) -> Response:
    """Read-only managed-service identity view: desired vs live vs stable."""
    store = ManagedServiceDeploymentStore(_web_data_dir(_engine_from(request)))
    try:
        view = compose_service_identity_view(store)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("services status compose failed: %s: %s", type(exc).__name__, exc)
        return UTF8JSONResponse(
            status_code=500,
            content={
                "error": "service_status_unavailable",
                "detail": f"{type(exc).__name__}: {exc}",
            },
        )
    return UTF8JSONResponse(view)


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


def _web_session_reusable_meta(meta: Any | None) -> bool:
    """Mechanical ingress ownership boundary for Web session adoption.

    Web and Feishu are intentionally cross-surface compatible. CLI/eval/other human
    ingress channels are not implicitly adoptable by Web. Legacy sessions without a
    durable first-ingress fact fall back to the historical top-level channel.
    """

    if meta is None:
        return False
    origin = str(getattr(meta, "origin_channel", "") or "").strip()
    if origin:
        return origin in {"web", "feishu"}
    channel = str(getattr(meta, "channel", "") or "").strip()
    return channel == "web" or channel.startswith("feishu:")


def _web_session_reusable(engine: Any, session_id: str) -> bool:
    try:
        return _web_session_reusable_meta(engine.session.get_meta(session_id))
    except Exception:  # noqa: BLE001 - reuse check fails closed; caller can create a clean Web session
        return False


def _session_ingress_mismatch_response(session_id: str) -> Response:
    return UTF8JSONResponse(
        status_code=409,
        content={
            "error": "session_ingress_mismatch",
            "detail": (
                f"会话 {session_id} 的首个人类 ingress 不属于 Web/飞书可共享边界；"
                "为避免诊断/CLI 上下文污染，Web 不会接管该会话。请新建 Web 会话。"
            ),
        },
    )


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
        if shared is not None and _web_session_reusable(engine, shared):
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
                # 显式模型选择属于本次 human turn，必须在 session.created 时就成为
                # 新会话 authority；只有本请求未显式选模型时才继承 shared_current。
                # 2026-10-13 加固：同传组合本身是前端状态异常（newSessionPending 与
                # 残留 currentSessionId 并存）的信号，打 warn 便于观测定位。
                if payload.session_id is not None:
                    logger.warning(
                        "chat new_session=true combined with session_id=%s "
                        "(frontend session-state anomaly signal; new_session wins)",
                        payload.session_id,
                    )
                session_id = engine.session.create(
                    model_override=_new_session_model_override(engine, payload.model)
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
                if not _web_session_reusable(engine, payload.session_id):
                    return _session_ingress_mismatch_response(payload.session_id)
                session_id = payload.session_id
            else:
                session_id = _resolve_session_id_locked(engine, request, None)
    except WorkspaceBusyError as exc:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "workspace_busy", "detail": str(exc)},
        )

    # §8.2-2 消息准入屏障：重启 waiting 窗口内新消息只获持久化排队回执
    # （带操作号），不得立即成为新活跃 run。
    _barrier = _service_restart_barrier(request, "web_chat")
    if _barrier is not None:
        return _barrier_queued_response(
            request, session_id, payload.message, _barrier, task_kind="web_chat"
        )

    # The signed one-session positive Canary must run under the BackgroundRunner
    # Stop bridge, not this synchronous route's unbound Engine call.
    if getattr(getattr(request.app.state, "task_budget_web_canary", None), "session_id", None) == session_id:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "budget_canary_requires_stream", "detail": "受控预算验收会话只允许流式后台执行。"},
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
    # Known model refs route through accepted Session authority. This prevents a
    # stale browser payload from regaining authority after in-run switch_model.
    # Unknown refs still pass through per-call routing for the normal unavailable fact.
    _route_model = payload.model if (payload.model and _persist_model_ref is None) else None
    _explicit_model_change = bool(payload.model_change or payload.new_session)
    _on_run_acquired = (
        (
            lambda sess: _apply_session_model_override(
                sess, _persist_model_ref, explicit_change=_explicit_model_change
            )
        )
        if _persist_model_ref else None
    )
    try:
        # R8.24-D D-D2（DT-1.3）: Web 非流式端点签发人类通道凭据（ingress token）——
        # guard fail-closed（default enforce）下无凭据 user 写入将被拒绝；本接线使
        # Web 通道合法输入携带白名单凭据放行（叠加式改动，外部并行改动零触碰）。
        from llm_loop.core.trace_leak.ingress_token import issue_ingress

        result = engine._run_with_acquired(
            session_id, payload.message, model=_route_model,
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

        background_tasks.add_task(push_web_chat_to_feishu, channel, payload.message, result.final_answer)

    return ChatResponse(
        session_id=result.session_id,
        final_answer=result.final_answer,
        verification_note=result.verification_note,
        rounds=result.rounds,
        tool_calls=result.tool_calls,
        truncated=result.truncated,
        history_compacted=getattr(result, "history_compacted", False),
        provider_output_truncated=getattr(result, "provider_output_truncated", False),
        run_incomplete=getattr(result, "run_incomplete", False),
        projection_validator_failed=getattr(result, "projection_validator_failed", False),
        projection_rebuilt=getattr(result, "projection_rebuilt", False),
        projection_cannot_fit=getattr(result, "projection_cannot_fit", False),
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


def _safe_queue_terminal(
    cb: Callable[[str, str | None], None], status: str, run_error: str | None
) -> None:
    """队列终态回写 fail-open：失败只记日志，绝不影响主响应流."""
    try:
        cb(status, run_error)
    except Exception:  # noqa: BLE001
        logger.exception("human turn queue terminal 回写失败: status=%s", status)


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


def _apply_session_model_override(
    session: Any,
    model_ref: str | None,
    *,
    explicit_change: bool = False,
) -> None:
    """Apply one accepted Web model selection without letting stale UI regain authority.

    ``payload.model`` is sent on every Web request for routing/UI continuity, but only
    explicit human ``model_change`` (or the new-session path) may mutate session
    authority. A stale browser snapshot must not create an override on an old session
    that previously had none.
    """
    if not model_ref:
        return
    if not explicit_change:
        return
    old = getattr(session, "model_override", None)
    if old != model_ref:
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


def _new_session_model_override(engine: Any, requested_model: str | None) -> str | None:
    """Resolve the model authority a new Web session is born with.

    A non-empty model in this human request takes precedence over process-global
    ``shared_current``.  If that explicit value is unknown, return ``None`` rather
    than borrowing an unrelated tab/session's model.  M60 inheritance remains the
    fallback only when this request did not explicitly choose a model.
    """
    if requested_model:
        return _canonical_persist_model(engine, requested_model)
    return _inherit_shared_model_override(engine)


def _stream_background(
    runner: Any,
    session_id: str,
    message: str,
    model: str | None,
    reasoning_effort: str | None = None,
    reasoning_mode: str | None = None,
    *,
    resume: bool = False,
    expected_run_generation: str | None = None,
    before_start: Callable[[Any], None] | None = None,
    expected_workspace_epoch: int | None = None,
    user_metadata: dict[str, Any] | None = None,
    queue_terminal: Callable[[str, str | None], None] | None = None,
    signed_web_canary: Any = None,
) -> Any:
    """后台 run 订阅生成器（EVO 后台 run 改造）：提交 → 消费事件 → 分片 yield SSE.

    - resume=True: 不提交新 run，订阅已有 run（刷新/切回会话场景）
    - delta: text/reasoning/tool_round/tool_result 分片独立 yield（机械事实直传）
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
        if resume:
            start_kwargs["expected_run_generation"] = expected_run_generation
        if not resume and user_metadata is not None:
            start_kwargs["user_metadata"] = user_metadata
        if not resume and queue_terminal is not None:
            start_kwargs["terminal_callback"] = queue_terminal
        if not resume and signed_web_canary is not None:
            start_kwargs["signed_web_canary"] = signed_web_canary
        handle, q = runner.start(session_id, message, **start_kwargs)
    except WorkspaceChangedError as exc:
        yield _sse("error", {"error": "workspace_changed", "detail": str(exc)})
        return
    except RunGenerationMismatchError as exc:
        # TOCTOU closure: route preflight may race a terminal/new run transition;
        # runner rechecks under its registry lock and returns a typed mechanical fault.
        yield _sse(
            "error",
            {
                "error": "run_generation_mismatch",
                "detail": "恢复目标已不是原运行代次；拒绝订阅新的 run。",
                "expected_run_generation": exc.expected_run_generation,
                "actual_run_generation": exc.actual_run_generation,
            },
        )
        return
    if handle is not None:
        # First provider-independent receipt.  The browser records this before any model
        # delta so a later reconnect can name the exact execution instead of "latest".
        yield _sse(
            "run_started",
            {
                "session_id": session_id,
                "run_generation": handle.run_generation,
            },
        )
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
                + (f"（开始于 {_fmt_ts(snap.get('started_at'))}）" if snap.get("started_at") else "")
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
        pending_event: dict | None = None
        while True:
            if pending_event is not None:
                ev, pending_event = pending_event, None
            else:
                try:
                    ev = q.get(timeout=2.0)
                except queue.Empty:
                    # 防御超时（正常 run 必有终态）；后台长时间无 delta（如工具执行）时
                    # 保持连接等待。断连由 ASGI 在 yield 挂起点注入 GeneratorExit。
                    continue
            etype = ev["type"]
            if etype == "delta":
                # 2026-09-23 CPU #1：合并窗口内连续 delta 同通道拼接为一帧；
                # 非.delta 事件经 pending 保序穿透（终态/工具事件零延迟）。
                text_parts: list[str] = []
                reason_parts: list[str] = []
                tool_rounds: list[Any] = []
                tool_results: list[Any] = []
                cur = ev["delta"]
                while True:
                    t = getattr(cur, "text", None)
                    if t:
                        text_parts.append(t)
                    r = getattr(cur, "reasoning", None)
                    if r:
                        reason_parts.append(r)
                    tr = getattr(cur, "tool_round", None)
                    if tr is not None:
                        tool_rounds.append(tr)
                    tres = getattr(cur, "tool_result", None)
                    if tres is not None:
                        tool_results.append(tres)
                    deadline = time.monotonic() + _DELTA_COALESCE_S
                    nxt = None
                    while True:
                        remain = deadline - time.monotonic()
                        if remain <= 0:
                            break
                        try:
                            nxt = q.get(timeout=remain)
                            break
                        except queue.Empty:
                            nxt = None
                            break
                    if nxt is None or nxt["type"] != "delta":
                        pending_event = nxt
                        break
                    cur = nxt["delta"]
                if text_parts:
                    yield _sse("answer_delta", {"data": "".join(text_parts)})
                if reason_parts:
                    yield _sse("reasoning_delta", {"data": "".join(reason_parts)})
                for tr in tool_rounds:
                    yield _sse(
                        "tool_round",
                        {
                            "tool_name": getattr(tr, "tool_name", ""),
                            "round_index": getattr(tr, "round_index", 0),
                            "args_summary": getattr(tr, "args_summary", ""),
                            "tool_call_id": getattr(tr, "tool_call_id", ""),
                        },
                    )
                for tool_result in tool_results:
                    yield _sse(
                        "tool_result",
                        {
                            "tool_name": getattr(tool_result, "tool_name", ""),
                            "tool_call_id": getattr(tool_result, "tool_call_id", ""),
                            "status": getattr(tool_result, "status", ""),
                            "duration_ms": getattr(tool_result, "duration_ms", None),
                            "result_chars": getattr(tool_result, "result_chars", None),
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
                        "history_compacted": getattr(result, "history_compacted", False),
                        "provider_output_truncated": getattr(result, "provider_output_truncated", False),
                        "run_incomplete": getattr(result, "run_incomplete", False),
                        "projection_validator_failed": getattr(result, "projection_validator_failed", False),
                        "projection_rebuilt": getattr(result, "projection_rebuilt", False),
                        "projection_cannot_fit": getattr(result, "projection_cannot_fit", False),
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
                if code == "session_busy":
                    detail = "会话繁忙，请稍后重试"
                elif code == "queue_ingress_durability_unavailable":
                    detail = "排队消息持久化边界不可用，本次尚未执行；队列项已保留可重试"
                else:
                    detail = f"[程序异常] 引擎执行失败（{ev['error']}）。"
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
                # 与同步入口相同：本请求显式模型优先于进程级 shared_current；
                # 未显式选模型时才走 M60 继承（fail-open → None）。
                # 2026-10-13 加固：同传组合本身是前端状态异常（newSessionPending 与
                # 残留 currentSessionId 并存）的信号，打 warn 便于观测定位。
                if payload.session_id is not None:
                    logger.warning(
                        "chat new_session=true combined with session_id=%s "
                        "(frontend session-state anomaly signal; new_session wins)",
                        payload.session_id,
                    )
                session_id = engine.session.create(
                    model_override=_new_session_model_override(engine, payload.model)
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
                if not _web_session_reusable(engine, payload.session_id):
                    return _session_ingress_mismatch_response(payload.session_id)
                session_id = payload.session_id
            else:
                session_id = _resolve_session_id_locked(engine, request, None)
    except WorkspaceBusyError as exc:
        return UTF8JSONResponse(
            status_code=409,
            content={"error": "workspace_busy", "detail": str(exc)},
        )

    _queue_id = getattr(payload, "queue_id", None)
    _queue_store: HumanTurnQueue | None = None
    if _queue_id:
        if bool(getattr(payload, "resume", False)):
            return UTF8JSONResponse(
                status_code=409,
                content={"error": "queue_claim_mismatch", "detail": "排队项不能作为 resume 订阅重放"},
            )
        _queue_store = _human_turn_queue(request)
        _claimed = _queue_store.claimed_item(session_id, _queue_id)
        if _claimed is None or not _queue_claim_matches(payload, _claimed, attachment_facts):
            return UTF8JSONResponse(
                status_code=409,
                content={
                    "error": "queue_claim_mismatch",
                    "detail": "queue_id 不存在、未处于 claimed，或请求事实与领取时冻结值不一致",
                },
            )

    # §8.2-2 消息准入屏障：waiting 窗口内不得发起正式 run。
    # - 有 queue_id：服务端把 claim 回滚为 queued（保 FIFO），回执仍带
    #   queue_id 与操作号；前端按 session_busy 家族语义刷新队列继续等待。
    # - 无 queue_id（直接发送）：服务端 durable 入队后回执带 queue_id。
    _barrier = _service_restart_barrier(request, "web_chat_stream")
    if _barrier is not None:
        _log_barrier_rejection(request, "web_chat_stream", _barrier)
        if _queue_id and _queue_store is not None:
            # 领取项回滚 queued（保持 FIFO 原位）——冻结事实已在队列中，
            # 不再重复入队；回执确认 + 操作号。
            _queue_store.release(session_id, _queue_id)
            return UTF8JSONResponse(
                status_code=503,
                content={
                    "error": "session_busy",
                    "detail": (
                        "服务重启窗口中（操作 "
                        f"{_barrier.operation_id}）：排队项已回滚为 queued，恢复后自动继续。"
                    ),
                    "queue_id": _queue_id,
                    "restart_barrier": _barrier.to_view(),
                },
            )
        # 2026-09-22（切换会话无变化事故）：resume 是订阅协议请求（绑定精确
        # run_generation），不是 human turn——绝不能 durable 入队。此前它走了下方
        # 直接入队分支，把字面量 "resume" 排成毒丸队列项，之后被队列接力当成
        # 真人消息执行。排队重放一个 generation 已过期的订阅毫无意义；拒绝即可：
        # 前端 resume 失败路径自然回退轮询，run 终态仍可见。
        if bool(getattr(payload, "resume", False)):
            return UTF8JSONResponse(
                status_code=503,
                content={
                    "error": "session_busy",
                    "detail": (
                        "服务重启窗口中（操作 "
                        f"{_barrier.operation_id}）：resume 订阅被拒绝（协议请求不入队）；"
                        "前端将回退轮询，run 终态不受影响。"
                    ),
                    "restart_barrier": _barrier.to_view(),
                },
            )
        return _barrier_queued_response(
            request,
            session_id,
            getattr(payload, "message", "") or "",
            _barrier,
            task_kind="web_chat_stream",
            status_code=503,
            extra={"error": "session_busy"},
        )

    # resume identity preflight: never interpret "the current run for this session" as
    # the caller's run.  This closes the ordinary stale-tab case before StreamingResponse
    # is committed; BackgroundRunner repeats the check under its own lock for TOCTOU.
    _resume_requested = bool(getattr(payload, "resume", False))
    _expected_run_generation = getattr(payload, "run_generation", None)
    _resume_runner = getattr(engine, "runner", None)
    if _resume_requested and _resume_runner is not None and _resume_runner.enabled:
        _resume_snap = _resume_runner.get_handle(session_id)
        if _resume_snap is not None:
            _actual_run_generation = str(_resume_snap.get("run_generation") or "")
            if str(_expected_run_generation or "") != _actual_run_generation:
                return UTF8JSONResponse(
                    status_code=409,
                    content={
                        "error": "run_generation_mismatch",
                        "detail": "恢复目标已不是原运行代次；Web 不会订阅同会话的后续 run。",
                        "expected_run_generation": str(_expected_run_generation or ""),
                        "actual_run_generation": _actual_run_generation,
                    },
                )

    # Web 模型选择只在请求成功接单后持久化。未知模型不写 session，
    # 仍交本次 per-call 路由生成“模型不可用”反馈；busy/resume 必须零副作用。
    _persist_model_ref = _canonical_persist_model(engine, payload.model)
    _route_model = payload.model if (payload.model and _persist_model_ref is None) else None
    _explicit_model_change = bool(payload.model_change or payload.new_session)

    # Exact selected Session from operator-owned startup configuration.
    # Invalid canary requests are denied, never silently downgraded to an
    # unbounded/default run. Resume subscribes without creating another Run.
    from llm_loop.resources.task_budget_store import TaskBudgetDeniedError

    try:
        _signed_canary = choose_signed_web_canary(
            request, session_id, model=payload.model,
            resume=_resume_requested, queued=bool(_queue_id),
            attachments=bool(payload.attachments),
        )
    except TaskBudgetDeniedError:
        return UTF8JSONResponse(
            status_code=403,
            content={"error": "budget_canary_not_qualified", "detail": "受控预算会话未通过独立授权条件。"},
        )

    def event_stream():
        # 后台 run 模式（EVO 后台 run 改造，对齐 DSH）：提交 + 订阅；断连只停订阅
        runner = getattr(engine, "runner", None)
        _resume = bool(getattr(payload, "resume", False))
        _before_start = (
            (
                lambda sess: _apply_session_model_override(
                    sess, _persist_model_ref, explicit_change=_explicit_model_change
                )
            )
            if (_persist_model_ref and not _resume)
            else None
        )
        # 排队派发承接（feature/webui-human-turn-queue-20260910）：本次 run 若承接
        # 队列项（queue_id），终态时回写队列状态；fail-open 不影响响应流。
        _queue_terminal: Callable[[str, str | None], None] | None = None
        if _queue_id and _queue_store is not None:
            queue_id = str(_queue_id)
            queue_store = _queue_store

            def _mark_queue_terminal(status: str, run_error: str | None = None) -> None:
                if status == "not_started":
                    queue_store.release(session_id, queue_id)
                    return
                queue_store.mark_terminal(session_id, queue_id, status, run_error)

            _queue_terminal = _mark_queue_terminal

        if runner is not None and runner.enabled:
            yield from _stream_background(
                runner,
                session_id,
                payload.message,
                _route_model,
                reasoning_effort=payload.reasoning_effort,
                reasoning_mode=payload.reasoning_mode,
                resume=_resume,
                expected_run_generation=_expected_run_generation if _resume else None,
                before_start=_before_start,
                expected_workspace_epoch=workspace_epoch,
                user_metadata=(
                    {
                        "attachments": attachment_facts,
                        **({"human_turn_queue_id": _queue_id} if _queue_id else {}),
                    }
                    if attachment_facts or _queue_id
                    else None
                ),
                queue_terminal=_queue_terminal,
                signed_web_canary=_signed_canary,
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
                session_id, payload.message, model=_route_model,
                reasoning_effort=payload.reasoning_effort,
                reasoning_mode=payload.reasoning_mode,
                on_run_acquired=_before_start,
                expected_workspace_epoch=workspace_epoch,
                ingress=issue_ingress("web"),
                user_metadata=(
                    {
                        "attachments": attachment_facts,
                        **({"human_turn_queue_id": _queue_id} if _queue_id else {}),
                    }
                    if attachment_facts or _queue_id
                    else None
                ),
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
                    if delta.tool_result is not None:
                        yield _sse(
                            "tool_result",
                            {
                                "tool_name": delta.tool_result.tool_name,
                                "tool_call_id": delta.tool_result.tool_call_id,
                                "status": delta.tool_result.status,
                                "duration_ms": delta.tool_result.duration_ms,
                                "result_chars": delta.tool_result.result_chars,
                            },
                        )
                except StopIteration as exc:
                    result = exc.value
                    break
        except WorkspaceChangedError as exc:
            if _queue_terminal is not None:
                _safe_queue_terminal(_queue_terminal, "failed", str(exc))
            yield _sse("error", {"error": "workspace_changed", "detail": str(exc)})
            return
        except SessionBusyError as exc:
            if _queue_terminal is not None:
                _safe_queue_terminal(_queue_terminal, "not_started", str(exc))
            yield _sse("error", {"error": "session_busy", "detail": str(exc)})
            return
        except QueuedIngressDurabilityError as exc:
            if _queue_terminal is not None:
                _safe_queue_terminal(_queue_terminal, "not_started", str(exc))
            yield _sse(
                "error",
                {"error": "queue_ingress_durability_unavailable", "detail": str(exc)},
            )
            return
        except Exception as exc:  # noqa: BLE001 — 引擎异常如实反馈（已生成分片不撤回）
            logger.exception("engine.run_stream failed: session_id=%s", session_id)
            if _queue_terminal is not None:
                _safe_queue_terminal(
                    _queue_terminal, "failed", f"[程序异常] {type(exc).__name__}: {exc}"
                )
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
                "history_compacted": getattr(result, "history_compacted", False),
                "provider_output_truncated": getattr(result, "provider_output_truncated", False),
                "run_incomplete": getattr(result, "run_incomplete", False),
                "projection_validator_failed": getattr(result, "projection_validator_failed", False),
                "projection_rebuilt": getattr(result, "projection_rebuilt", False),
                "projection_cannot_fit": getattr(result, "projection_cannot_fit", False),
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
        if _queue_terminal is not None:
            _safe_queue_terminal(_queue_terminal, "completed", None)

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
    # Native/modern clients can bind the *exact* Run generation. The background
    # runner checks this under its own lock, so the comparison and stop are
    # atomic even if a different Run starts between HTTP preflight and dispatch.
    expected = payload.run_generation
    ok = (
        runner.cancel(payload.session_id, expected_run_generation=expected)
        if expected is not None else runner.cancel(payload.session_id)
    )
    if not ok and expected is not None:
        snap = runner.get_handle(payload.session_id)
        actual = str((snap or {}).get("run_generation") or "")
        if actual and actual != expected:
            return UTF8JSONResponse(
                status_code=409,
                content={"error": "run_generation_mismatch",
                         "detail": "拒绝取消不同运行代次", "actual_run_generation": actual},
            )
    return UTF8JSONResponse(content={"cancelled": ok})


@router.get("/api/v1/artifacts/{artifact_id}")
def artifact_hydrate(artifact_id: str, request: Request) -> Response:
    """验证的 workspace artifact 字节水合端点（harmonyos CONTRACT Required verification #4）.

    仅接受 ``artifact://v1/<32hex>`` 的 id 部分；workspace 归属与 SHA256
    readback 由 ``WorkspaceArtifactStore.hydrate`` 保证。不存在/越权统一
    404（防枚举），blob 完整性失败 409。本端点无 blob 写路径。
    """
    engine = _engine_from(request)
    chars = set("0123456789abcdef")
    if len(artifact_id) != 32 or any(c not in chars for c in artifact_id):
        return UTF8JSONResponse(status_code=404, content={"error": "artifact_not_found"})
    store = WorkspaceArtifactStore(
        getattr(getattr(engine, "settings", None), "data_dir", "./data")
    )
    try:
        resolution, data = store.hydrate(
            "artifact://v1/" + artifact_id,
            workspace_scope=_current_attachment_workspace_scope(engine),
        )
    except ArtifactError as exc:
        if "完整性" in str(exc):
            return UTF8JSONResponse(
                status_code=409, content={"error": "artifact_integrity_failure"}
            )
        return UTF8JSONResponse(status_code=404, content={"error": "artifact_not_found"})
    record = resolution.record
    headers = {
        "X-Artifact-Ref": record.ref,
        "X-Artifact-Sha256": record.sha256,
        "X-Artifact-Size-Bytes": str(record.size_bytes),
        "X-Artifact-Relative-Path": record.relative_path,
        "X-Artifact-Workspace-Path-State": resolution.workspace_path_state,
    }
    if resolution.current_sha256 is not None:
        headers["X-Artifact-Workspace-Path-Sha256"] = resolution.current_sha256
    return Response(content=data, media_type="application/octet-stream", headers=headers)


@router.get("/api/v1/chat/queue")
def queue_list(request: Request, session_id: str = Query(..., description="会话 ID")) -> Response:
    """查看会话的活跃排队项（FIFO 序；触发 claimed 悬挂 reaper）."""
    hq = _human_turn_queue(request)
    items = hq.list_active(session_id)
    return UTF8JSONResponse(
        content={
            "items": items,
            "count": len(items),
            "queued": sum(1 for it in items if it.get("status") == "queued"),
            "claimed": sum(1 for it in items if it.get("status") == "claimed"),
        }
    )


@router.post("/api/v1/chat/queue", status_code=202)
def queue_enqueue(payload: QueueEnqueueRequest, request: Request) -> Response:
    """入队：生成中 Cmd/Ctrl+Enter 插话；冻结本条事实（message/attachments/model）.

    会话不存在 → 404；附件引用非法 → 400（与 /chat 同规则）。
    """
    engine = _engine_from(request)
    if not engine.session.exists(payload.session_id):
        return UTF8JSONResponse(
            status_code=404,
            content={
                "error": "session_not_found",
                "detail": session_not_found_message(payload.session_id),
            },
        )
    try:
        with engine.workspace_snapshot():
            attachment_facts = _resolve_chat_attachment_facts(
                engine,
                payload.attachments,
                workspace_scope=_current_attachment_workspace_scope(engine),
            )
    except (AttachmentError, WorkspaceBusyError) as exc:
        return UTF8JSONResponse(
            status_code=400 if isinstance(exc, AttachmentError) else 409,
            content={"error": "invalid_attachment" if isinstance(exc, AttachmentError) else "workspace_busy", "detail": str(exc)},
        )
    hq = _human_turn_queue(request)
    try:
        item = hq.enqueue(
            payload.session_id,
            payload.message,
            attachments=[ref.model_dump() if hasattr(ref, "model_dump") else dict(ref) for ref in payload.attachments],
            model=payload.model,
            model_change=payload.model_change,
            reasoning_effort=payload.reasoning_effort,
            reasoning_mode=payload.reasoning_mode,
            attachment_facts=attachment_facts,
        )
    except QueuePersistError as exc:
        # Phase3 D2 二分：持久化失败分级透出（不静默吞、不假装成功；503 如实标注）
        return UTF8JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": f"queue_persist_{exc.stage}",
                "detail": f"排队持久化失败（{exc.stage}）：{exc}"[:200],
            },
        )
    active = hq.list_active(payload.session_id)
    position = sum(1 for it in active if it.get("status") == "queued")
    return UTF8JSONResponse(
        status_code=202,
        content={"queue_id": item["queue_id"], "position": position, "item": item},
    )


@router.delete("/api/v1/chat/queue")
def queue_cancel(payload: QueueCancelRequest, request: Request) -> Response:
    """取消排队项（仅 queued 可取消；claimed 已进入发送流程不可取消）."""
    hq = _human_turn_queue(request)
    item = hq.cancel_with_item(payload.session_id, payload.queue_id, cancelled_by="user")
    if item is None:
        return UTF8JSONResponse(
            status_code=409,
            content={
                "error": "queue_cancel_conflict",
                "detail": "排队项不存在或已在发送中，无法取消",
            },
        )
    return UTF8JSONResponse(content={"ok": True, "item": item})


@router.post("/api/v1/chat/queue/interject", status_code=202)
def queue_interject(payload: QueueInterjectRequest, request: Request) -> Response:
    """Hand one queued human turn to the exact currently-running Web run.

    "立即" means the next safe model-decision boundary.  This endpoint never mutates
    Session history from the Web thread and never cancels an in-flight tool/provider
    operation merely to make the handoff look immediate.
    """
    engine = _engine_from(request)
    runner = getattr(engine, "runner", None)
    if runner is None or not getattr(runner, "enabled", False):
        return UTF8JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "error": "interject_no_live_run",
                "detail": "当前会话没有可接收插话的运行任务；消息仍保留在排队中",
            },
        )
    handle = runner.get_handle(payload.session_id)
    if not handle:
        return UTF8JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "error": "interject_no_live_run",
                "detail": "当前会话没有可接收插话的运行任务；消息仍保留在排队中",
            },
        )

    actual_run_generation = str(handle.get("run_generation") or "")
    if payload.run_generation != actual_run_generation:
        return UTF8JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "error": "interject_run_changed",
                "detail": "当前任务已变化；消息仍保留在普通排队中",
            },
        )

    hq = _human_turn_queue(request)
    # run_generation 记入认领事实，供 QueueServerFallback 巡检判孤儿回收
    try:
        item = hq.claim_interject(
            payload.session_id, payload.queue_id, run_generation=actual_run_generation
        )
    except QueuePersistError as exc:
        # Phase3 D2：认领未落盘 ⇒ 队列项必然仍为 queued（definitely_not_committed）
        # 或无法裁决（commit_outcome_uncertain）——一律 503 如实透出，不降级重试。
        return UTF8JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": f"queue_persist_{exc.stage}",
                "detail": f"插话认领持久化失败（{exc.stage}）：{exc}"[:200],
            },
        )
    if item is None:
        return UTF8JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "error": "interject_claim_conflict",
                "detail": "该排队项已被领取、取消或不存在，无法立即插入",
            },
        )

    from llm_loop.core.trace_leak.ingress_token import issue_ingress

    accepted = runner.enqueue_interjection(
        payload.session_id,
        {
            "queue_id": payload.queue_id,
            "message": item.get("message", ""),
            "attachment_facts": list(item.get("attachment_facts") or []),
            "_ingress": issue_ingress("web"),
            "_on_received": lambda **ctx: hq.mark_interject_received(
                payload.session_id, payload.queue_id, **ctx
            ),
            # Phase3 G1 分级回执（全部 fail-open，回执失败不阻断主链路）：
            # denied=ingress 守卫拒绝；applied=含插话决策产生首个动作或改变终答；
            # cbf=终答结算边界拦截续跑。正文不出现在任何回执/日志（D6）。
            "_on_denied": lambda reason: hq.mark_interject_denied(
                payload.session_id, payload.queue_id, reason
            ),
            "_on_applied": lambda detail: hq.record_interject_applied(
                payload.session_id, payload.queue_id, detail
            ),
            "_on_cbf": lambda detail: hq.record_interject_cbf(
                payload.session_id, payload.queue_id, detail
            ),
        },
        expected_run_generation=payload.run_generation,
    )
    if not accepted:
        try:
            hq.release_interject(payload.session_id, payload.queue_id)
        except QueuePersistError as exc:
            return UTF8JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "error": f"queue_persist_{exc.stage}",
                    "detail": f"回滚排队持久化失败（{exc.stage}）：{exc}"[:200],
                },
            )
        return UTF8JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "error": "interject_run_changed",
                "detail": "当前任务刚刚结束或停止；消息已恢复为普通排队",
            },
        )
    return UTF8JSONResponse(
        status_code=202,
        content={
            "ok": True,
            "queue_id": payload.queue_id,
            "state": "interject_pending",
            "grade": "accepted",
            "grade_reason": "受理≠生效：已进入 live run 信箱；生效分级见 GET /api/v1/chat/queue/item",
        },
    )


@router.get("/api/v1/chat/queue/item")
def queue_item_grade(session_id: str, queue_id: str, request: Request) -> Response:
    """Phase3 G1 只读端点：单个排队项的分级回执（含终态项；零写副作用）.

    grade 全集：queued/requeued/accepted(受理≠生效)/received/applied/
    continued_before_final/denied(含 deny_reason)/cancelled。机械派生，
    不做语义判断；消息必达语义不变（M0 报告 S02/S03/S11/S12 回归保障）。
    """
    hq = _human_turn_queue(request)
    for it in hq.snapshot_items():
        if it.get("queue_id") == queue_id and it.get("session_id") == session_id:
            return UTF8JSONResponse(status_code=200, content={"ok": True, "item": it})
    return UTF8JSONResponse(
        status_code=404,
        content={"ok": False, "error": "queue_item_not_found"},
    )


@router.get("/api/v1/chat/queue/metrics")
def queue_interject_metrics(session_id: str, request: Request) -> Response:
    """Phase3 G2 只读端点：插话三口径时延聚合（t_ack/t_persist/t_effect/t_applied）.

    - P50/P95 为最近邻序法（机械可复算）；n=0 → p50/p95=null，不造数。
    - 只统计 interject_received 终态项；denied/requeued 不混入（口径含混即失真）。
    - 本端点零写副作用；与 M0 基线（S01：t_ack≈2ms vs t_effect≈2493ms）同口径，
      可直接对照「回执≠生效」的差值演化。
    """
    hq = _human_turn_queue(request)
    return UTF8JSONResponse(
        status_code=200, content={"ok": True, **hq.aggregate_interject_metrics(session_id)}
    )


@router.get("/api/v1/chat/queue/metrics/global")
def queue_interject_metrics_global(request: Request) -> Response:
    """可观测性 M1b（B1）：全局只读端点——跨 session 合并的六桶三口径聚合.

    - 与单 session 端点（Phase3 G2）同一 hq 同一实现（单一事实源）；零写副作用；
      不含逐条 items（合并视图不做 per-session 明细，明细走既有单 session 端点）。
    - window_terminal_cap 标注数据窗口=最近 N 条终态（compact 滚动上限），
      非全历史；n=0 → p50/p95=null 不造数。
    - 鉴权事实同层（M0 评审 B3）：/api/v1 现状=loopback 信任+OriginGuard，
      本端点不扩不降鉴权面。
    """
    hq = _human_turn_queue(request)
    return UTF8JSONResponse(
        status_code=200, content={"ok": True, **hq.aggregate_interject_metrics_global()}
    )


@router.get("/api/v1/chat/stop-state")
def chat_stop_state(session_id: str, request: Request) -> Response:
    """Phase3 G3 只读端点：停止四态组合查询（requested/dispatched_stopped/local_terminated）.

    - 空清单显式返回 no_known_external_side_effects=true（不静默空数组歧义）。
    - external_unknown 可枚举：工具+目标+发起时间+人工核验指引；
      禁 TTL 自动转 confirmed（D5）——确认只走 POST /confirm 人工登记。
    - 状态由真实时间戳组合而来（查询面，非状态机迁移）；run_alive 由
      runner 句柄（后台）+同步活跃登记（双路径，同 cancel 语义）判定。
    """
    from llm_loop.core.loop.side_effects import SideEffectRegistry

    engine = _engine_from(request)
    runner = getattr(engine, "runner", None)

    def _run_alive() -> bool:
        if runner is None:
            return False
        try:
            if runner.get_handle(session_id) is not None:
                return True
            return bool(runner.is_sync_active(session_id))
        except Exception:  # noqa: BLE001 — 查询面不放大异常
            return False

    se = SideEffectRegistry.instance()
    return UTF8JSONResponse(
        status_code=200,
        content={"ok": True, **se.stop_state(session_id, run_alive=_run_alive)},
    )


class StopConfirmRequest(BaseModel):
    session_id: str = Field(min_length=1)
    effect_id: str = Field(min_length=1)
    confirmed_by: str = Field(min_length=1, max_length=60)
    note: str = Field(default="", max_length=200)


@router.post("/api/v1/chat/stop-state/confirm")
def chat_stop_state_confirm(payload: StopConfirmRequest, request: Request) -> Response:
    """Phase3 G3：external_unknown 人工确认登记（幂等；无 TTL 自动确认，D5）."""
    from llm_loop.core.loop.side_effects import SideEffectRegistry

    # P2-5：确认必须通过会话归属校验（会话 A 不能确认会话 B 的副作用）
    ok = SideEffectRegistry.instance().confirm_external(
        payload.effect_id, payload.confirmed_by, payload.note,
        session_id=payload.session_id,
    )
    if not ok:
        return UTF8JSONResponse(
            status_code=404, content={"ok": False, "error": "side_effect_not_found"}
        )
    return UTF8JSONResponse(
        status_code=200,
        content={"ok": True, "effect_id": payload.effect_id, "confirmed_by": payload.confirmed_by},
    )


@router.post("/api/v1/chat/queue/dispatch")
def queue_dispatch(payload: QueueDispatchRequest, request: Request) -> Response:
    """原子领取队首 queued 项（FIFO）：多标签并发领取只有一个成功（幂等收敛）.

    返回冻结事实（message/attachment_facts/model/...），领取方以其发起正式
    /chat/stream 请求（带 queue_id）；无法发起（session_busy 等）时调 release 回滚。
    """
    hq = _human_turn_queue(request)
    # §8.2-2: waiting 窗口内不派发 claim（领取→/chat/stream 只会再被
    # 屏障拒绝）。claimed=None 让前端接力循环本轮停住，恢复后自动续。
    _barrier = _service_restart_barrier(request, "web_queue_dispatch")
    if _barrier is not None:
        _log_barrier_rejection(request, "web_queue_dispatch", _barrier)
        return UTF8JSONResponse(
            content={
                "claimed": None,
                "reason": "service_restart_barrier",
                "restart_barrier": _barrier.to_view(),
            }
        )
    claimed = hq.dispatch_claim(payload.session_id, claimed_by="web")
    return UTF8JSONResponse(content={"claimed": claimed})


@router.post("/api/v1/chat/queue/release")
def queue_release(payload: QueueReleaseRequest, request: Request) -> Response:
    """外部回滚仅允许机械证明 not_started 的 claim；执行态绝不重新排队."""
    engine = _engine_from(request)
    hq = _human_turn_queue(request)
    state = _queue_claim_state(engine, payload.session_id, payload.queue_id)
    if state != "not_started":
        return UTF8JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "error": "queue_release_not_safe",
                "detail": f"排队项当前机械状态为 {state}，不能证明未执行，拒绝重新排队",
            },
        )
    ok = hq.release(payload.session_id, payload.queue_id)
    return UTF8JSONResponse(content={"ok": ok})


_STATIC_DIR = Path(__file__).resolve().parent / "static"


@router.get("/")
def root() -> Response:
    """服务根路径：默认重定向到 Web V2（/ui/v2，2026-08-20 起默认入口）。

    2026-09-04 弃用 v1（原版 M37 前端）：v2 产物缺失时直接 503，不再回退旧版
    聊天页面（static/index.html 保留不删，但不再服务，避免两套前端混淆）。
    """
    # 与 build_app 挂载逻辑同源：函数内求值（测试可 monkeypatch UI_V2_DIR）
    ui_v2 = Path(os.environ.get("UI_V2_DIR", "") or Path(__file__).resolve().parents[3] / "webui" / "dist")
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
    from llm_loop.runtime.manifest import health_identity

    identity = health_identity()
    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "build": identity.get("build_identity", {}),
        "endpoints": {
            "POST /api/v1/chat": "对话（body: {message, session_id?, model?}）",
            "GET /api/v1/sessions": "会话列表",
            "DELETE /api/v1/sessions/{session_id}?confirm=true": "删除会话（须确认）",
            "POST /api/v1/sessions/{session_id}/pin": "会话置顶/取消置顶（M56）",
            "GET /api/v1/models": "可用模型列表",
            "GET /api/v1/providers": "Provider/模型本机配置（鉴权控制面）",
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
    default_model = getattr(getattr(engine, "llm", None), "model", None) or "deepseek-flash"
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
        # 零回归回顾: 未注入 model_pool（test 场景）→ 行为同现状。此路径没有
        # registry truth 可判定 availability，因此仍把 current 放入 fallback options。
        configured = _os.environ.get("WEB_MODELS", "").strip()
        names = (
            [m.strip() for m in configured.split(",") if m.strip()]
            if configured
            else ["deepseek-flash", "deepseek-v4-pro"]
        )
        if current not in names:
            names.insert(0, current)
        return {"models": names, "current": current, "current_available": True, "catalog": []}

    # 拉取所有当前 registry 中实际可用的全限定 'provider/model'。
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

    # current 是会话事实，不等于 availability。裸名若唯一匹配当前可用 registry，
    # 仅做显示规范化；若 provider/model 已被热禁用/删除，则保留原 current 并
    # 显式 current_available=false，绝不自动改写用户 session override，也不把它
    # 重新塞回“可用模型列表”。
    current_available = current in names
    if not current_available:
        matched = next((n for n in names if n.endswith(f"/{current}")), None)
        if matched:
            current = matched
            current_available = True

    catalog: list[dict[str, Any]] = []
    for pid, spec in registry.providers.items():
        for mid, mspec in spec.models.items():
            model_ref = f"{pid}/{mid}"
            if model_ref not in names:
                continue
            capable, control = registry.reasoning_contract(pid, mid)
            efforts = list(getattr(mspec, "reasoning_efforts", ()) or ())
            control_supported = (
                control in {"thinking_type", "chat_template", "always_on_effort"}
                or (control == "legacy" and bool(getattr(mspec, "thinking", False)))
                # ChatGPT Web is browser/provider-owned rather than API-field
                # controlled, but it exposes a qualified visible five-level
                # effort selector.  When the model explicitly declares those
                # levels, LFL Web may offer request-local effort selection; the
                # transport applies/verifies it on the owned browser surface.
                or (control == "provider_owned" and bool(efforts))
            )
            can_disable = control in {"thinking_type", "chat_template"} or (
                control == "legacy" and bool(getattr(mspec, "thinking", False))
            )
            default_effort = getattr(mspec, "reasoning_default_effort", None)
            catalog.append(
                {
                    "id": model_ref,
                    "provider": pid,
                    "model": mid,
                    "display_name": (
                        "网页版 GPT"
                        if model_ref == "chatgpt-web/web-gpt"
                        else "DeepSeek 网页版"
                        if model_ref == "deepseek-web/web-deepseek"
                        else None
                    ),
                    "context": int(getattr(mspec, "context", 0) or 0),
                    "max_input_tokens": getattr(mspec, "max_input_tokens", None)
                    or getattr(spec, "max_input_tokens", None),
                    "max_output_tokens": getattr(mspec, "max_tokens", None)
                    or getattr(spec, "max_tokens", None),
                    "cost_tier": str(getattr(mspec, "cost_tier", "") or ""),
                    "multimodal": bool(getattr(mspec, "multimodal", False)),
                    "reasoning_capable": bool(capable),
                    "reasoning_control": control,
                    "reasoning_control_supported": control_supported,
                    "reasoning_can_disable": can_disable,
                    "reasoning_efforts": efforts,
                    "reasoning_default_effort": default_effort,
                }
            )
    return {
        "models": names,
        "current": current,
        "current_available": current_available,
        "catalog": catalog,
    }


@router.get("/health")
def health() -> dict:
    """健康检查：纯服务层探活，不调用 LLM、不含凭证.

    R3: runtime 字段读回启动时落盘的 manifest 摘要（身份+配置指纹）——
    跨区污染诊断（module_repo_root 指向哪个区、端口对不对）秒级完成。
    health_identity() 读回而非实时 compute（identity 含 git subprocess，探活高频不可跑）；
    fail-open：manifest 缺失时返回空 identity 仍可诊断。
    """
    from llm_loop.runtime.manifest import health_identity

    identity = health_identity()
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "build": identity.get("build_identity", {}),
        "knowledge": identity.get("knowledge", {}),
        "identity": identity,
    }


@router.get("/api/v1/architecture_status")
def architecture_status_web(request: Request, session_id: str = "") -> Response:
    """EVO-20260818（spec §5.4.1-2）: 架构状态 web API 通道.

    含 context_usage.cache_health / cache_guard 快照。recent_hit_rate 是成本/展示事实；
    缓存回归以 cache_guard.cache_health 为权威机械口径：仅在同 run 连续轮、
    provider/model/stable_prefix_fp/cache_prefix_epoch/compaction_epoch 均可比、未过 TTL
    且 prompt 非收缩时，绝对 hit tokens 下降才标 regression。fail-open：
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


@router.get("/api/v1/escalation/list")
def escalation_list(request: Request, limit: int = 50, status: str = "") -> Response:
    """提权申请列表（只读；EVO-20260923-c58a0bb1 提权闭环 web 端）.

    status 可选过滤（pending/approved/denied/consumed/expired）；响应**永不
    含令牌**（令牌只由 AI 侧 escalation_wait 从存储读取，不经 web 通道）。
    前端轮询此端点驱动弹窗。本地 web（127.0.0.1）默认可信；WEB_AUTH_REQUIRE=1
    时受统一 Bearer 保护（与 evolution 审批一致）。
    """
    from pathlib import Path

    from llm_loop.tools.escalation import EscalationStore

    base = Path(os.environ.get("LFL_DATA_DIR", "") or Path(__file__).resolve().parents[3] / "data")
    store = EscalationStore(base / "audit" / "escalation_requests.json")
    try:
        items = store.list(status=status or "", limit=limit)
        pending = store.pending_count()
    except OSError:
        items, pending = [], 0
    return JSONResponse(content={"requests": items, "pending_count": pending})


@router.post("/api/v1/escalation/review")
async def escalation_review(request: Request) -> Response:
    """web 提权审批（人工决定端点；批准 = 铸造一次性令牌，拒绝 = 记录理由）.

    请求体见 schemas.EscalationReviewRequest；幂等约束: 仅 pending 可决，
    重复审批返回 409 语义（fail-closed 到首个决定）。
    """
    from pathlib import Path

    from llm_loop.tools.escalation import EscalationStore
    from llm_loop.web.schemas import EscalationReviewRequest

    try:
        payload = EscalationReviewRequest.model_validate_json(await request.body())
    except Exception as exc:  # noqa: BLE001 — 参数校验失败统一 400
        return JSONResponse(content={"error": f"参数校验失败: {exc}"}, status_code=400)

    base = Path(os.environ.get("LFL_DATA_DIR", "") or Path(__file__).resolve().parents[3] / "data")
    audit_file = base / "audit" / "escalation_review_log.jsonl"
    try:
        audit_file.parent.mkdir(parents=True, exist_ok=True)
        audit_line = {
            "ts": system_local_now().isoformat(),
            "action": "ESCALATION_REVIEW_WEB",
            "id": payload.id,
            "decision": payload.decision,
            "note": payload.note,
        }
        with audit_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(audit_line, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 审计写失败不阻断审批主流程（store 侧另有 escalation_log.jsonl 双写）

    store = EscalationStore(base / "audit" / "escalation_requests.json")
    rec, reason = store.decide(
        payload.id,
        payload.decision,
        decided_by="web_panel",
        note=payload.note,
        ttl_minutes=payload.ttl_minutes,
    )
    if rec is None:
        code = 404 if "不存在" in reason else 409
        return JSONResponse(content={"error": reason}, status_code=code)
    return JSONResponse(content={"ok": True, "request": rec})


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
                impact_hint = ", ".join(impact_files[:5]) if impact_files else (
                    (d.get("impact_scope") or "")[:120] or content[:120]
                )
                out.append({
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
                })
        except OSError:
            pass  # 建议文件读取失败 fail-open（返回已收集条目，日志由上层审计兜底）
    out.sort(key=lambda x: x["ts"], reverse=True)
    return JSONResponse(content={"suggestions": out[:limit], "count": len(out)})


@router.get("/api/v1/evolution/detail")
def evolution_detail(request: Request, id: str = "") -> Response:
    """演进建议详情（Approval UX v2 批 1: 完整内容懒加载，列表只回摘要）."""
    from pathlib import Path

    if not id:
        return UTF8JSONResponse(status_code=400, content={"error": "invalid_params", "detail": "id 必填。"})
    base = Path(os.environ.get("LFL_DATA_DIR", "") or Path(__file__).resolve().parents[3] / "data")
    f = base / "audit" / "evolution_suggestions.jsonl"
    if not f.exists():
        return UTF8JSONResponse(status_code=404, content={"error": "not_found", "detail": "建议文件不存在"})
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
                return JSONResponse(content={
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
                })
        return UTF8JSONResponse(status_code=404, content={"error": "not_found", "detail": f"未找到 {id}"})
    except OSError:
        return UTF8JSONResponse(status_code=500, content={"error": "read_failed", "detail": "建议文件读取失败。"})


def _log_web_review(
    evo_id: str,
    decision: str,
    ok: bool,
    *,
    data_dir: str | Path,
    note: str = "",
    reason: str = "",
) -> None:
    """web 面板审批动作审计行（EVO-20260918-d1182270: 人工决策写可检索事实）.

    追加 JSONL 到 data/audit/evolution_review_log.jsonl，行内含 action=EVO_REVIEW_WEB + 建议 id，
    AI 侧（search_files content="EVO_REVIEW_WEB"）可直接定位人工何时批了什么；
    fail-open：审计写入失败不影响审批回执本身。
    """

    try:
        base = Path(data_dir).expanduser().resolve()
        audit_dir = base / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": system_local_now().isoformat(),
            "source": "web_panel",
            "action": "EVO_REVIEW_WEB",
            "id": evo_id,
            "decision": decision,
            "ok": bool(ok),
            "reason": reason,
            "note": note,
        }
        with (audit_dir / "evolution_review_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # fail-open（DFX-REL-06）


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
            content={"error": "invalid_params", "detail": "id 必填，decision 须为 accepted/rejected。"},
        )
    if decision == "rejected" and not reason:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "reason_required", "detail": "拒绝须提供理由（Approval UX v2 批 1: 拒绝理由必填留痕）。"},
        )
    # 方案A（EVO-20260929）: exec_override 仅对 accepted 合法（拒绝无执行可言）
    if payload.exec_override and decision != "accepted":
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "invalid_params", "detail": "exec_override 仅用于 accepted。"},
        )
    # Approval UX v2 批 1（验证清单 #9）: 涉边界项单条批准需额外确认标志（extra_confirm）；
    # 方案A: exec_override（人工显式授权自动执行）等价并强于 extra_confirm——授权即确认。
    if decision == "accepted":
        cur_for_confirm = _find_suggestion(store, evo_id)
        if (
            cur_for_confirm is not None
            and bool(cur_for_confirm.get("requires_human"))
            and not (payload.extra_confirm or payload.exec_override)
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
            return UTF8JSONResponse(status_code=404, content={"error": "not_found", "detail": f"未找到 {evo_id}"})
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
            ok, resp, reviewed = approve(store, evo_id, exec_override=payload.exec_override)
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
        _log_web_review(
            evo_id,
            decision,
            False,
            data_dir=_web_data_dir(engine),
            note=f"异常: {type(exc).__name__}: {exc}",
            reason=reason,
        )
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "review_failed", "detail": f"审批异常: {type(exc).__name__}: {exc}"},
        )
    # 人工审批落可检索审计行 + 回执带新状态（EVO-20260918-d1182270: 面板反馈闭环）
    new_status = ""
    cur_after = _find_suggestion(store, evo_id)
    if cur_after is not None:
        new_status = str(cur_after.get("status") or "")
    _log_web_review(
        evo_id,
        decision,
        bool(ok),
        data_dir=_web_data_dir(engine),
        note=resp,
        reason=reason,
    )
    return UTF8JSONResponse(
        content={"ok": ok, "message": resp, "id": evo_id, "new_status": new_status},
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
    # 方案A EVO-20260929 / EVO-20261018-f5f7580a：人工逐条显式授权可随批量下传
    # （顶层默认，条目可覆盖）。此前批量只置 accepted，档位 0 下永远到不了 executing。
    raw_default_override = body.get("exec_override", False)
    if not isinstance(raw_default_override, bool):
        # 授权标志必须严格布尔：JSON 的 "false"/0/null 之类真值强转会变成"想拒绝实际授权"。
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "invalid_params", "detail": "exec_override 必须为布尔。"},
        )
    default_override = raw_default_override
    if not items or default_decision not in {"accepted", "rejected"}:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "invalid_params", "detail": "items 必填且 decision 须为 accepted/rejected。"},
        )
    results: list[dict] = []
    ok_count = fail_count = 0
    for it in items:
        evo_id = str(it.get("id") or "").strip()
        decision = str(it.get("decision") or default_decision).strip()
        reason = str(it.get("reason") or "").strip()
        expected = str(it.get("expected_status") or "").strip()
        raw_item_override = it.get("exec_override", default_override)
        if not isinstance(raw_item_override, bool):
            results.append({"id": evo_id, "ok": False, "message": "exec_override 必须为布尔"})
            fail_count += 1
            continue
        exec_override = raw_item_override
        if not evo_id or decision not in {"accepted", "rejected"}:
            results.append({"id": evo_id, "ok": False, "message": "参数非法"})
            fail_count += 1
            continue
        # 服务端硬校验：涉边界跳过（禁止批量）
        cur = _find_suggestion(store, evo_id)
        if cur is not None and bool(cur.get("requires_human")):
            results.append({"id": evo_id, "ok": False, "message": "涉边界（requires_human），须单条审批", "skipped": True})
            fail_count += 1
            continue
        # CAS 乐观锁
        if expected and cur is not None and cur.get("status") != expected:
            results.append({"id": evo_id, "ok": False, "message": f"状态冲突（期望 {expected}，当前 {cur.get('status')}）"})
            fail_count += 1
            continue
        try:
            if decision == "accepted":
                ok, resp, reviewed = approve(store, evo_id, exec_override=exec_override)
                if ok and reviewed:
                    # EVO-20261018：批量路径此前只置 accepted、从不触发执行推进，与单条审批
                    # 行为分叉（单条在 approve 后调 maybe_auto_execute_from_engine）。此处对齐。
                    from llm_loop.introspection.evolution_exec import maybe_auto_execute_from_engine

                    cur_after = _find_suggestion(store, evo_id)
                    if cur_after is not None:
                        try:
                            resp += "\n" + maybe_auto_execute_from_engine(engine, store, cur_after)
                        except Exception as exc:  # noqa: BLE001 — 执行触发失败不影响审批
                            resp += f"\n⚠️ 自动执行触发异常：{type(exc).__name__}"
            else:
                if not reason:
                    results.append({"id": evo_id, "ok": False, "message": "拒绝须提供理由"})
                    fail_count += 1
                    continue
                ok, resp = reject(store, evo_id, reason)
            results.append({"id": evo_id, "ok": bool(ok), "message": resp})
            _log_web_review(
                evo_id,
                decision,
                bool(ok),
                data_dir=_web_data_dir(engine),
                note=resp,
                reason=reason,
            )  # EVO-20260918-d1182270
            ok_count += bool(ok)
            fail_count += not ok
        except Exception as exc:  # noqa: BLE001 — 单条失败不影响其余
            _log_web_review(
                evo_id,
                decision,
                False,
                data_dir=_web_data_dir(engine),
                note=f"异常: {type(exc).__name__}: {exc}",
                reason=reason,
            )
            results.append({"id": evo_id, "ok": False, "message": f"异常: {type(exc).__name__}: {exc}"})
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
        return UTF8JSONResponse(status_code=400, content={"error": "invalid_params", "detail": "id 必填。"})
    base = Path(os.environ.get("LFL_DATA_DIR", "") or Path(__file__).resolve().parents[3] / "data")
    f = base / "audit" / "evolution_suggestions.jsonl"
    if not f.exists():
        return UTF8JSONResponse(status_code=404, content={"error": "not_found", "detail": "建议文件不存在"})
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
                    return UTF8JSONResponse(status_code=404, content={"error": "no_diff", "detail": "已拒绝建议无 diff。"})
                actions = d.get("actions") or []
                impact_files = d.get("impact_files") or []
                if not actions and not impact_files:
                    return UTF8JSONResponse(status_code=404, content={"error": "no_diff", "detail": "该建议无关联改动。"})
                return JSONResponse(content={
                    "id": id,
                    "impact_files": impact_files,
                    "actions": [a for a in actions if isinstance(a, dict)][:20],
                    "note": "只读摘要（不含 prompt/密钥）",
                })
        return UTF8JSONResponse(status_code=404, content={"error": "not_found", "detail": f"未找到 {id}"})
    except OSError:
        return UTF8JSONResponse(status_code=500, content={"error": "read_failed", "detail": "建议文件读取失败。"})


def _find_suggestion(store: Any, evo_id: str) -> dict | None:
    """按 id 在演进存储中查找建议（web 审批执行触发用）."""
    try:
        for s in store.list() or []:
            if s.get("id") == evo_id:
                return s
    except Exception:  # noqa: BLE001
        return None
    return None


def _stats_for_loaded_session(engine: Any, session_id: str, sess: Any) -> dict[str, Any]:
    """One session only: no implicit parent/child cost mixing or semantic role guess.

    双源聚合（只读，不触发 run）：
    - turns/steps：会话消息计数（assistant/tool）
    - tokens/耗时/缓存：优先从 request.usage 事件聚合（消息 payload 不含统计字段，
      message.appended 只存基础字段；request.usage 有 tokens_in/out/cache_hit/耗时）。
      事件缺失时回退消息字段（内存态兼容）。
    - SubAgent 独立 child：实际物理成本来自 provider.transport.settled，
      而非逻辑回答次数；hidden retry 也计入。
    """
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
    events = []
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
            events = []
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
            if _b["tokens_in"] > 0 else 0.0,
        }
        for _mdl, _b in sorted(by_model.items())
    }
    result: dict[str, Any] = {
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
    parent_id = str(getattr(sess, "parent_id", "") or "")
    is_subagent = bool(parent_id and session_id.startswith("subagent_"))
    result["agent_scope"] = {
        "kind": "subagent" if is_subagent else "session",
        "parent_session_id": parent_id if is_subagent else None,
    }
    result["usage_source"] = "request.usage" if usage_events else "message_legacy"
    if is_subagent:
        from llm_loop.core.provider_transport_usage_stats import (
            summarize_physical_provider_usage,
        )

        # Reuse the exact same append-only snapshot already read for request.usage:
        # double reads could combine inconsistent accounting boundaries mid-run.
        physical = summarize_physical_provider_usage(events)
        result["physical_provider_usage"] = physical
        if physical is not None:
            result.update(
                tokens_in=physical["input_tokens"],
                tokens_out=physical["output_tokens"],
                cache_hit=physical["cached_input_tokens"],
                cache_hit_rate=physical["cache_hit_rate"],
                by_model={
                    name: {
                        "tokens_in": value["input_tokens"],
                        "cache_hit": value["cached_input_tokens"],
                        "cache_hit_rate": value["cache_hit_rate"],
                    }
                    for name, value in physical["by_model"].items()
                },
                llm_ms=physical["transport_duration_ms"],
                tok_s=(
                    round(physical["output_tokens"] / (physical["transport_duration_ms"] / 1000), 1)
                    if physical["transport_duration_ms"] > 0 else 0.0
                ),
                usage_source=physical["usage_source"],
            )
        else:
            # Legacy child messages often serialize all token/cache fields as
            # zero even with real Provider usage; "unknown" is not "all miss".
            result["cache_hit_rate"] = None
            result["usage_source"] = "unavailable"
    return result


@router.get("/api/v1/sessions/{session_id}/stats")
def session_stats(
    session_id: str, request: Request, child_id: str | None = None,
) -> Any:
    """Read-only per-agent usage; exact child_id optionally compares two scopes.

    A child is not labelled Reviewer without a trusted role declaration.
    No auto-enumeration, semantic guessing, or charge aggregation across agents.
    """
    engine = _engine_from(request)
    if not engine.session.exists(session_id):
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": f"会话不存在: {session_id}"},
        )
    sess = engine.session.load(session_id)
    result = _stats_for_loaded_session(engine, session_id, sess)
    if child_id is not None:
        if (
            not child_id.startswith("subagent_")
            or not engine.session.exists(child_id)
        ):
            return UTF8JSONResponse(
                status_code=404, content={"error": "child_session_not_found"},
            )
        child = engine.session.load(child_id)
        if child.parent_id != session_id:
            return UTF8JSONResponse(
                status_code=404, content={"error": "child_session_not_found"},
            )
        child_stats = _stats_for_loaded_session(engine, child_id, child)
        result["agent_comparison"] = {
            "parent": dict(result),
            "child": child_stats,
            "child_session_id": child_id,
            "reviewer_role": "unverified",
        }
    return result

@router.get("/api/v1/interop/messages")
def list_interop_messages(request: Request) -> dict:
    """协调通道消息（只读，不触发 run）——web 端展示给用户看.

    读 data/interop/{lfl_to_dsh,dsh_to_lfl}/pending/ 的 JSON 消息（协议见 INTEROP.md），
    返回两个方向的待处理消息摘要。只读文件系统，不触发 agent run、不占会话锁。
    """
    del request  # 纯文件读取，无引擎依赖
    base = Path(os.environ.get("LFL_DATA_DIR", "data")) / "interop"
    result: dict[str, dict] = {"lfl_to_dsh": {"pending": [], "recent_done": []},
                               "dsh_to_lfl": {"pending": [], "recent_done": []}}
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
    default_model = getattr(getattr(engine, "llm", None), "model", None)
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
            origin_channel=m.origin_channel,
            web_reusable=_web_session_reusable_meta(m),
            model=m.model_override or default_model,
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
    responses={409: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
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
    responses={409: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
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
        ok = engine.session.archive(session_id) if archived else engine.session.unarchive(session_id)
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
    return UTF8JSONResponse(content={"status": "ok", "session_id": session_id, "archived": archived})


@router.post(
    "/api/v1/sessions/{session_id}/fork",
    response_model=None,
    responses={409: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
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


# 2026-09-23 CPU #1：delta 中继合并窗口——窗口内同通道 delta 合并为一帧 SSE，
# 逐 chunk 的 json.dumps+socket write 按合并比下降（长 reasoning 流的主线程残余负载大头）。
# 40ms 兼顾流畅度（人眼无感）与合并率；终态/工具事件经 pending 保序立即穿透。
_DELTA_COALESCE_S = 0.04


def _sse_event(name: str, payload: dict) -> str:
    """SSE 命名事件帧（2026-08-15 修复）：必须带 `event: <type>` 行浏览器才按命名事件分发。

    此前只发 `data: {"type": ...}` → 浏览器按默认 message 处理，前端
    addEventListener("sessions_updated") 永不触发（Web 端必须手动刷新）。
    """
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


def _sessions_fingerprint(sessions_dir: str | Path) -> str:
    """会话目录轻量指纹：文件数 + 最新文件 mtime + 文件名（任一变化即事件）.

    2026-09-23 CPU 诊断（SIGUSR1 栈抓现行）：原实现对每文件 stat 两次
    （max key + newest 复查）× 每条 SSE 连接 × 每 1.5s——460 会话 × 多连接
    在事件循环主线程上形成 stat 风暴。改为每文件单次 stat（结果复用），
    轮询节拍同步放缓至 3s（见 gen()）。
    """
    try:
        newest_mtime = 0
        newest_name = ""
        count = 0
        # Avoid pathlib.glob's wildcard selector here.  This path is polled by
        # every open SSE client and may sit on a directory with thousands of
        # session files; scandir gives us the name + stat handle in one pass.
        with os.scandir(sessions_dir) as entries:
            for entry in entries:
                if not entry.name.endswith(".json"):
                    continue
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    mtime = entry.stat(follow_symlinks=False).st_mtime_ns
                except OSError:
                    continue
                count += 1
                if mtime > newest_mtime:
                    newest_mtime = mtime
                    newest_name = entry.name
        if not count:
            return "0"
        return f"{count}:{newest_mtime}:{newest_name}"
    except OSError:
        return "err"


def _session_events_fingerprint(engine: Any) -> str:
    """当前SessionStore根 + 内容指纹；workspace切换本身也视为会话视图变化。"""
    session = getattr(engine, "session", None)
    sessions_dir = getattr(session, "root", None)
    if sessions_dir is None:
        sessions_dir = (
            getattr(getattr(engine, "settings", None), "sessions_dir", None)
            or "./data/sessions"
        )
    root = Path(sessions_dir)
    return f"{root}:{_sessions_fingerprint(root)}"


async def _session_events_fingerprint_async(engine: Any) -> str:
    """Read the session-directory fingerprint without blocking the event loop.

    Fingerprinting is intentionally filesystem-backed.  Even a normally cheap
    directory scan can become slow under large session sets, GC pressure, or
    storage contention; running it on the asyncio thread would stall unrelated
    requests such as /login and /auth/status.
    """
    return await asyncio.to_thread(_session_events_fingerprint, engine)


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
    initial = await _session_events_fingerprint_async(engine)

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
            await asyncio.sleep(3.0)  # 2026-09-23: 1.5→3s，指纹扫描成本减半再减半
            now = loop.time()
            # keepalive：20s 无事件也保活（注释行，浏览器忽略内容仅感知存活）
            if now - last_beat >= 20.0:
                last_beat = now
                yield ": keepalive\n\n"
                continue
            current = await _session_events_fingerprint_async(engine)
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


def _schedule_store(request: Request):
    """Per-app ScheduleStore（与 factory._schedule_store 同一路径派生，同文件即同事实源）.

    ScheduleStore 读侧以磁盘为 SoT（list() 先 refresh）、写侧跨进程文件锁，
    多实例指向同一 schedule.json 是 scheduler.py 明确支持的使用方式。
    """
    from llm_loop.core.scheduler import ScheduleStore

    store = getattr(request.app.state, "schedule_store", None)
    if store is not None:
        return store
    engine = _engine_from(request)
    settings = getattr(engine, "settings", None)
    data_dir = Path(getattr(settings, "data_dir", "./data"))
    store = ScheduleStore((data_dir).resolve() / "schedule.json")
    request.app.state.schedule_store = store
    return store


def _schedule_row(
    entry: dict,
    delivery_facts: dict | None = None,
    pool_facts: dict | None = None,
) -> dict:
    """会话级只读投影：保留展示所需的机械事实，剥宿主/租约/wake 授权内部字段."""
    repeat_interval = float(entry.get("repeat_interval") or 0.0)
    return {
        "sid": entry.get("sid", ""),
        "session_id": entry.get("session_id", ""),
        "message": entry.get("message", ""),
        "trigger_at": float(entry.get("trigger_at") or 0.0),
        "kind": "every" if repeat_interval > 0 else "once",
        "every_seconds": int(repeat_interval) if repeat_interval > 0 else None,
        "repeat_interval": repeat_interval,
        "max_count": int(entry.get("max_count") or 1),
        "count": int(entry.get("count") or 0),
        "wake": bool(entry.get("wake")),
        # 任务语义（设计 20261019）：常驻授权的额度/有效期/落点，供面板显示
        "task_mode": str(
            entry.get("task_mode") or ("task_once" if entry.get("wake") else "remind")
        ),
        "wake_fires_total": int(
            (pool_facts or {}).get("fires_total") or entry.get("wake_fires_total") or 0
        ),
        "wake_fires_used": int(
            (pool_facts or {}).get("fires_used") or entry.get("wake_fires_used") or 0
        ),
        "wake_expires_at": float(
            (pool_facts or {}).get("expires_at") or entry.get("wake_expires_at") or 0.0
        ),
        "wake_child_session_id": str(entry.get("wake_child_session_id") or ""),
        "created_at": float(entry.get("created_at") or 0.0),
        "scheduled_trigger_at": float(entry.get("scheduled_trigger_at") or entry.get("trigger_at") or 0.0),
        **(delivery_facts or {}),
    }


@router.get("/api/v1/sessions/{session_id}/schedule")
def list_session_schedule(session_id: str, request: Request) -> Response:
    """List owner-scoped schedule reminder facts (no derived semantics, no host internals)."""
    engine = _engine_from(request)
    if not engine.session.exists(session_id):
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": session_not_found_message(session_id)},
        )
    store = _schedule_store(request)
    # 池成员共用一份额度：展示层投影池的权威计数，避免同池条目各显示各自开火次数。
    rows = [
        _schedule_row(
            entry,
            store.wake_delivery_facts(entry),
            store.pool_facts(str(entry.get("wake_pool") or "")),
        )
        for entry in store.list()
        if str(entry.get("session_id") or "") == session_id
    ]
    rows.sort(key=lambda row: (row["trigger_at"], row["sid"]))
    return UTF8JSONResponse(content={"schedule": rows, "count": len(rows)})


@router.post("/api/v1/sessions/{session_id}/schedule/{sid}/cancel")
def cancel_session_schedule(session_id: str, sid: str, request: Request) -> Response:
    """Explicit authenticated-user cancellation of one owner-scoped reminder."""
    from llm_loop.core.scheduler import ScheduleCommitUncertainError, SchedulePersistError

    engine = _engine_from(request)
    if not engine.session.exists(session_id):
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "session_not_found", "detail": session_not_found_message(session_id)},
        )
    store = _schedule_store(request)
    target = next(
        (
            entry
            for entry in store.list()
            if entry.get("sid") == sid
            and str(entry.get("session_id") or "") == session_id
        ),
        None,
    )
    if target is None:
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "schedule_not_found", "detail": "该提醒不存在或不属于当前会话"},
        )
    try:
        store.cancel(sid)
    except ScheduleCommitUncertainError as exc:
        return UTF8JSONResponse(
            status_code=503,
            content={
                "error": "schedule_commit_uncertain",
                "sid": sid,
                "outcome": exc.outcome,
                "visible_state": exc.visible_state,
                "durability_confirmed": False,
                "retry_safe": bool(exc.retry_safe),
            },
        )
    except SchedulePersistError as exc:
        return UTF8JSONResponse(
            status_code=503,
            content={
                "error": "schedule_persist_failed",
                "sid": sid,
                "outcome": exc.outcome,
                "durability_confirmed": False,
                "retry_safe": bool(exc.retry_safe),
            },
        )
    return UTF8JSONResponse(content={"status": "ok", "sid": sid})


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
        events = list(getattr(estore, "read_cached", estore.read)(session_id) or [])
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
            "source": (
                "open_stream_checkpoint" if chosen is not None else "open_execution_state"
            ),
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
    source_messages = session.messages
    total = len(source_messages)
    start = 0
    end = total
    if limit is not None:
        start = max(0, total - offset - limit)
        end = max(0, total - offset)
        source_messages = source_messages[start:end]
    # Program-final assistant rows intentionally persist an empty protocol placeholder so
    # subsequent provider prompts never ingest program-authored terminal prose.  The exact
    # UI text is durably stored in EventStore; hydrate only this Web response by the seq
    # recorded in provider-invisible Message.metadata.
    _program_final_text_by_seq: dict[int, str] = {}
    _wanted_program_final_seqs = {
        int((getattr(m, "metadata", {}) or {}).get("program_final_event_seq") or 0)
        for m in source_messages
        if (getattr(m, "metadata", {}) or {}).get("program_final_placeholder") is True
    }
    _wanted_program_final_seqs.discard(0)
    if _wanted_program_final_seqs:
        try:
            _event_store = getattr(engine, "_event_store", None)
            _events = (
                _event_store.read_cached(session_id)
                if _event_store is not None and getattr(_event_store, "enabled", False)
                else []
            )
            for _event in _events:
                _seq = int(getattr(_event, "seq", 0) or 0)
                if _seq not in _wanted_program_final_seqs:
                    continue
                if str(getattr(_event, "type", "") or "") != "program.final":
                    continue
                _payload = getattr(_event, "payload", None)
                if isinstance(_payload, dict):
                    _text = str(_payload.get("full_text") or "")
                    if _text:
                        _program_final_text_by_seq[_seq] = _text
        except Exception:  # noqa: BLE001 — history stays truthful empty placeholder on failure
            logger.warning("program.final UI hydration failed (fail-open)", exc_info=True)

    def _history_content(message) -> str:
        _md = getattr(message, "metadata", {}) or {}
        if _md.get("program_final_placeholder") is True:
            _seq = int(_md.get("program_final_event_seq") or 0)
            if _seq > 0 and _seq in _program_final_text_by_seq:
                return _program_final_text_by_seq[_seq]
        return str(getattr(message, "content", "") or "")

    # Project only the requested page. Previously limit=100 still constructed
    # MessageItem objects for every message in multi-thousand-message sessions and
    # sliced afterwards, amplifying CPU/GIL pressure during Web polling.
    messages = [
        MessageItem(
            role=m.role,
            content=_history_content(m),
            tool_call_id=m.tool_call_id,
            status=getattr(getattr(m, "status", None), "value", None),
            tool_name=getattr(m, "tool_name", None),
            duration_ms=float(getattr(m, "duration_ms", 0.0) or 0.0),
            reasoning_content=getattr(m, "reasoning_content", None),  # P1-1: 历史思考链透传
            model_used=getattr(m, "model_used", ""),  # M51: 历史模型标签透传（页脚）
            tokens_in=getattr(m, "tokens_in", 0),  # M52: 历史 token 消耗透传
            tokens_out=getattr(m, "tokens_out", 0),  # M52
            tokens_cache_hit=getattr(m, "tokens_cache_hit", 0),  # M58: 历史命中透传（页脚 ⚡——漏了显示 0）
            **_history_runtime_receipt_fields(m),
            ts=getattr(m, "ts", 0.0),  # 时间戳透传（web 端消息时间显示）
            tool_calls=getattr(m, "tool_calls", None),  # 工具声明透传（历史出产物/正文链接）
            attachments=list((getattr(m, "metadata", {}) or {}).get("attachments", []))
            if getattr(m, "role", "") == "user"
            else [],
        )
        for m in source_messages
    ]
    if limit is not None:
        return SessionMessagesResponse(
            session_id=session_id, messages=messages, has_more=start > 0, total=total
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
    return UTF8JSONResponse(
        content={"attachments": [record.public_facts() for record in records]}
    )


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
                        "error": "upload_too_large" if size > MAX_UPLOAD_BYTES else "file_unreadable",
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
        Path(engine.settings.sessions_dir) / ws.id
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
    prepared_sessions_dir: Path | None = None

    def prepare_runtime(ws: Any) -> None:
        nonlocal prepared_sessions_dir
        prepared_sessions_dir = engine.prepare_workspace(ws.path, ws.id)

    try:
        with engine.workspace_transition():
            ws = store.register_and_switch(path, precommit=prepare_runtime)
            engine.set_workspace(
                ws.path, ws.id, prepared_sessions_dir=prepared_sessions_dir
            )
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
            engine.set_workspace(
                ws.path, ws.id, prepared_sessions_dir=prepared_sessions_dir
            )
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
    "learning": (("GET", "/api/v1/learning/status"),),
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
    "schedule": (
        ("GET", "/api/v1/sessions/{session_id}/schedule"),
        ("POST", "/api/v1/sessions/{session_id}/schedule/{sid}/cancel"),
    ),
    "continuity": (("GET", "/api/v1/sessions/{session_id}/continuity"),),
    "providerAdmin": (
        ("GET", "/api/v1/providers"),
        ("POST", "/api/v1/providers"),
        ("POST", "/api/v1/providers/reload"),
        ("POST", "/api/v1/providers/default-model"),
    ),
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
        key: all(pair in registered for pair in pairs)
        for key, pairs in _CAPABILITY_ROUTES.items()
    }
    return UTF8JSONResponse(content={"capabilities": capabilities})

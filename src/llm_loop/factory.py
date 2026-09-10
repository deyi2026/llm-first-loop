"""组件装配工厂（供 CLI 与测试复用）.

将 Settings + LLMClient + ToolRegistry(基础工具+自省/修正/检索工具) +
MemoryStore + ArchiveStore + SessionStore + ArchitectureStatusProvider +
DeclarationValidator + RecordSearcher 装配为 LoopEngine。
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import os
import shutil
from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_loop.config import Settings
from llm_loop.core.history import converge_history_budget
from llm_loop.core.loop import LoopEngine
from llm_loop.core.message import ToolResult
from llm_loop.core.run_context import (
    current_session_id as current_session_id_ctx,
)
from llm_loop.core.run_context import (
    workspace_base as runtime_workspace_base,
)
from llm_loop.core.scheduler import ScheduleStore  # 2026-08-27 BUGFIX: 共享实例装配
from llm_loop.core.session import SessionStore, _validate_session_id
from llm_loop.feedback.honesty import delete_feedback_for_session
from llm_loop.feedback.validator import DeclarationValidator
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.docs_search import DocsSearcher
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.status import ArchitectureStatusProvider
from llm_loop.introspection.task_evidence import TaskEvidenceVerifier
from llm_loop.llm.client import LLMClient
from llm_loop.memory.archive import ArchiveStore
from llm_loop.memory.attachments import AttachmentStore
from llm_loop.memory.episode import EpisodeStore
from llm_loop.memory.evidence import EvidenceError
from llm_loop.memory.store import MemoryStore
from llm_loop.memory.synopsis import (
    MAX_SOURCE_SNAPSHOT_CHARS,
    SourceSnapshot,
    SynopsisError,
    SynopsisStore,
)
from llm_loop.methods.learning_journal import LearningJournal
from llm_loop.methods.learning_plane import LearningPlane
from llm_loop.methods.store import (
    MethodStore,  # Method Learning v1：方法卡存储（顶层装配供 corrections/检索共享）
)
from llm_loop.resources.foreground import ForegroundActivityProbe
from llm_loop.resources.governor import ResourceGovernor
from llm_loop.resources.ledger_projection import ProviderSettlementProjectionIndex
from llm_loop.resources.local_runtime import LocalRuntimeConcurrencyAdapter
from llm_loop.resources.provider_calls import ProviderCallCoordinator
from llm_loop.resources.provider_settlement import ProviderCallSettlementJournal
from llm_loop.resources.transport_observation import ShadowTransportRecorder
from llm_loop.runtime.causal_diagnose import diagnose_event_store
from llm_loop.runtime.causality import build_runtime_causal_snapshot
from llm_loop.runtime.route_context import get_route_context, set_route_audit_fn
from llm_loop.runtime.tool_octet import register_octet_sink
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.builtin.agent_message import AgentMessageTool
from llm_loop.tools.builtin.dsh_session_read import DshSessionReadTool
from llm_loop.tools.builtin.dsh_task import DshTaskTool
from llm_loop.tools.builtin.edit_file import EditFileTool
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.builtin.inspect_code import InspectCodeTool
from llm_loop.tools.builtin.job_kill import JobKillTool
from llm_loop.tools.builtin.job_output import JobOutputTool
from llm_loop.tools.builtin.job_registry import JobRegistry
from llm_loop.tools.builtin.read_attachment import ReadAttachmentTool
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.builtin.read_image import ReadImageTool
from llm_loop.tools.builtin.schedule import ScheduleCancelTool, ScheduleTool
from llm_loop.tools.builtin.search_files import SearchFilesTool
from llm_loop.tools.builtin.source_synopsis import SourceSynopsisTool
from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool
from llm_loop.tools.builtin.subagent_result import SubAgentResultTool
from llm_loop.tools.builtin.web_fetch import WebFetchTool
from llm_loop.tools.builtin.web_search import WebSearchTool
from llm_loop.tools.builtin.workflow import WorkflowRunTool
from llm_loop.tools.registry import ToolRegistry
from llm_loop.workspace.artifacts import WorkspaceArtifactStore
from llm_loop.workspace.file_effect_query import FileEffectQueryService
from llm_loop.workspace.file_service import FileService
from llm_loop.workspace.human_file_ops import HumanFileOperationService

# EVO-20260814 P1-A: RUN_MODE 运行模式（对齐 Harness 四种运行模式）
# standard: 全工具集（默认零回归）; ptc: 命令执行为主路径（web 外围降级）;
# minimal: 精简工具集（只读+必要执行）; creative: 宽松默认参数（超时/输出/检索放大）
_RUN_MODE_HIDDEN_TOOLS: dict[str, set[str]] = {
    # minimal: 外围/重工具禁用（web 检索、飞书出站、playwright、record_skill 等）
    "minimal": {
        "web_fetch",
        "web_search",
        "send_feishu_message",
        "create_feishu_doc",
        "send_feishu_attachment",
        "playwright_test",
        "playwright_exec",
        "record_skill",
    },
    # ptc: 命令执行主路径——web 检索类降级（LLM 少走低效 web 往返）；
    # playwright 隐藏（EVO-20260816-96215428 阶段一门控：浏览器执行类工具仅 standard/creative 可见，
    # 对齐 Hermes"仅 terminal 权限会话注册 browser_exec"的注册层门控精神，为单 exec 演进扫清安全前提）
    "ptc": {"web_fetch", "web_search", "playwright_test", "playwright_exec"},
    # creative/standard: 全工具集
    "creative": set(),
    "standard": set(),
}


def _run_mode_hidden(run_mode: str) -> set[str]:
    return _RUN_MODE_HIDDEN_TOOLS.get(run_mode, set())


logger = logging.getLogger(__name__)


class _CorrectionAdapterTool:
    """把修正/检索工具包装为 Tool 协议（注册进 ToolRegistry，LLM 可见可调）."""

    def __init__(
        self, corrections: CorrectionToolRegistry, name: str, description: str, parameters: dict
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self._corrections = corrections

    def execute(self, **kwargs: Any) -> ToolResult:
        return self._corrections.execute(self.name, kwargs)


def _read_workspace_changed_flag(data_dir: str) -> dict | None:
    """P1-12: 读 guard 写的工作区变更 flag（data/workspace_changed.json）.

    存在且合法 → 返回 {changed_at, changed_files, note, action}; 不存在/损坏 → None。
    fail-open（读失败不影响 architecture_status）。
    """
    import json
    from pathlib import Path

    p = Path(data_dir) / "workspace_changed.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def build_engine(settings: Settings) -> LoopEngine:
    """装配全部组件并返回 LoopEngine."""
    # ERC rollout is explicit.  ``off`` remains the default; shadow/enforce stores are only
    # constructed when the corresponding mode is requested.  No provider call occurs here.
    settings.ensure_dirs()

    # M47（design §5.1/§5.5）: 从注册表查思考支持（消除 _thinking_supported() 硬编码 deepseek.com）.
    # 当前模型不在注册表（如显式使用未注册的模型）→ 保持 LLMClient 默认（向后兼容）.
    # M48（design §5.3）: 注册表同时为 ModelClientPool 提供服务（路由/缓存/思考查询）。
    # P1-4（审计 #13）: resolve 失败不再静默吞掉——warning 如实告警（含用户配置的模型名与
    # 失败原因）+ config_status 暴露 model_registry_resolved=false, 让 AI 经
    # architecture_status 感知"模型配置未生效"（程序故障对 AI 可见原则）.
    thinking_supported: bool | None = None
    reasoning_capable: bool | None = None
    reasoning_control = "legacy"
    resolved_provider_id = ""
    model_registry_resolved = False
    # P1-8(2026-08-15): 默认模型支持 "provider/model" 全限定（如 kimi/k3-256k）——
    # 全限定 → 默认 client 按注册表 provider 参数装配（base_url/api_key 来自 provider 配置,
    # 模型名用裸名发送——OpenAI 兼容端点不接受全限定）; 裸名（如 deepseek-v4-flash）→
    # 保持 env 三件套（LLM_BASE_URL/LLM_API_KEY/LLM_MODEL, 零回归）。
    llm_params: dict | None = None
    try:
        from llm_loop.llm.providers import load_registry

        registry = load_registry(settings)
        provider_id, model_id = registry.resolve(settings.llm_model)
        resolved_provider_id = provider_id
        # 2026-09-04: history_max_chars=None 是“未配置独立全局 cap”的真实状态，
        # 不能在装配时冻结成默认模型的 100K/160K 预算；否则会话随后切换到更大窗口
        # 模型仍被启动模型的旧预算限制。None 保持 None，执行期由当前路由模型物理窗口
        # + output reserve/provider cap 决定。仅显式非法值仍做兼容纠错。
        if settings.history_max_chars is None:
            _limit: int | None = None
            try:
                _spec = registry.providers[provider_id].models.get(model_id)
                _limit = _spec.context if _spec else None
            except Exception:  # noqa: BLE001 — 窗口未知兜底旧默认
                _limit = None
            _budget, _note = converge_history_budget(None, model_window=_limit)
            if _note:
                logger.info(
                    "history_max_chars 未配置（无独立全局 cap）；%s，诊断预算=%d",
                    _note, _budget,
                )
            else:
                logger.info(
                    "history_max_chars 未配置（无独立全局 cap）；默认模型物理预算估算=%d 字符",
                    _budget,
                )
        else:
            _budget, _note = converge_history_budget(settings.history_max_chars, model_window=None)
            if _note:
                logger.warning("%s（当前生效: %d）", _note, _budget)
                # 非法输入兜底 → 写回纠错；合法显式 cap 原样保留。
                if _budget != settings.history_max_chars:
                    settings = dataclasses.replace(settings, history_max_chars=_budget)
        thinking_supported = registry.supports_thinking(provider_id, model_id)
        reasoning_capable, reasoning_control = registry.reasoning_contract(
            provider_id, model_id
        )
        model_registry_resolved = True
        if "/" in settings.llm_model:
            llm_params = registry.client_params(provider_id, model_id)
    except ValueError as exc:
        # 当前模型不在注册表 → 保持 LLMClient 默认（向后兼容 _thinking_supported）
        # P1-4: 不再静默吞错——如实告警（含模型名与失败原因）供人工/AI 排查
        logger.warning(
            "模型注册表 resolve 失败: 配置模型 '%s' 未生效（能力元数据按默认处理, "
            "可能致 thinking-mode 等模式错配）: %s",
            settings.llm_model,
            exc,
        )

    # RG-3B shadow observation: one bounded process-local recorder is shared by
    # the default client and every routed client. It is not an admission input.
    transport_observer = ShadowTransportRecorder()

    # LLM 客户端（全限定默认模型走注册表参数, 否则 env 三件套）
    llm = LLMClient(
        api_key=(llm_params or {}).get("api_key", settings.llm_api_key),
        base_url=(llm_params or {}).get("base_url", settings.llm_base_url),
        model=(llm_params or {}).get("model", settings.llm_model),
        timeout_s=(llm_params or {}).get("timeout_s", settings.llm_timeout_s),
        max_tokens=(llm_params or {}).get("max_tokens", settings.llm_max_tokens),
        wire_protocol=(
            (llm_params.get("wire_protocol") or "openai")
            if llm_params is not None
            else settings.llm_wire_protocol
        ),
        # M20 THK-01: 思考参数装配一次，三条 LLM 路径统一受益（VAL-02）
        thinking_mode=settings.thinking_mode,
        reasoning_effort=settings.reasoning_effort,
        reasoning_effort_map=(llm_params or {}).get("reasoning_effort_map"),
        # M47 §5.5: 元数据驱动的思考支持判定（None 时退回硬编码，向后兼容）
        thinking_supported=thinking_supported,
        reasoning_capable=reasoning_capable,
        reasoning_control=reasoning_control,
        provider=resolved_provider_id,
        send_tool_choice=bool((llm_params or {}).get("send_tool_choice", True)),
        reasoning_split=bool((llm_params or {}).get("reasoning_split", False)),
        transport_observer=transport_observer,
    )

    # M48（design §5.3）: 模型客户端路由池（会话级 model_override 路由 + provider 级缓存）
    # 未配置 MODEL_PROVIDERS（仅 L0 单 provider 合成）→ 池仅有默认 client，行为与现状一致
    # M49（design §5.4）: 注入 MODEL_FALLBACKS 原始字符串，池在 fallback_candidates() 中按需解析
    from llm_loop.llm.pool import ModelClientPool

    model_pool = ModelClientPool(
        registry=registry,
        default_client=llm,
        model_fallbacks_raw=settings.model_fallbacks_raw,
        base_timeout_s=settings.llm_timeout_s,
        base_max_tokens=settings.llm_max_tokens,
        transport_observer=transport_observer,
    )

    # 存储（记忆 + 压缩档案 + 会话 + fail-open恢复备份）
    from llm_loop.recovery.backup import BackupStore

    memory = MemoryStore(settings.memory_dir)
    backup_store = BackupStore(settings.recovery_dir)
    # INJECTION-GOVERNANCE R8.5: resolved episodes require a durable retrieval
    # surface independent from ArchiveStore compaction/GC. Session ids already
    # live in one global identity namespace, so a data-dir scoped store is safe.
    episode_store = EpisodeStore(Path(settings.data_dir) / "episodes")

    def archive_known_session_id(session_id: str) -> bool:
        """legacy flat archive段的外部owner证据；无法判定时按已占用处理。"""
        base = Path(settings.sessions_dir)
        if Path(session_id).name != session_id:
            return True
        if (base / ".identity" / f"{session_id}.json").is_file():
            return True
        if (base / f"{session_id}.json").is_file():
            return True
        try:
            for child in base.iterdir():
                if child.name == ".identity" or not child.is_dir():
                    continue
                if (child / f"{session_id}.json").is_file():
                    return True
        except OSError:
            return True
        return False

    archive = (
        ArchiveStore(
            settings.archive_dir,
            segment_bytes=settings.archive_segment_bytes,
            known_session_id_fn=archive_known_session_id,
        )
        if settings.archive_enabled
        else None
    )
    # R7: 启动时清理一次过期/超量档案（fail-open，不影响启动）
    if archive is not None:
        try:
            gc_result = archive.cleanup(
                max_entries=settings.archive_max_entries,
                ttl_days=settings.archive_ttl_days,
            )
            if gc_result.get("pruned_entries", 0) > 0:
                logger.info(
                    "档案 GC: 清理 %s 条目 / %s 文件",
                    gc_result["pruned_entries"],
                    gc_result["pruned_files"],
                )
        except Exception:  # noqa: BLE001 — GC 失败不影响启动
            logger.warning("档案 GC 启动清理失败（fail-open）", exc_info=True)
    event_store = _build_event_store(settings)
    # RG-3D: global SQLite state is a rebuildable cross-session projection only.
    # EventStore remains the durable SoT; startup never scans historical sessions.
    provider_settlement_projection_index = ProviderSettlementProjectionIndex(
        settings.audit_dir / "resource_governor" / "provider_settlement_projection.sqlite3"
    )
    # RG-3C: EventStore is the durable shadow settlement SoT. The RG-3B
    # recorder only writes normalized mechanical facts into this journal.
    provider_call_settlement_journal = ProviderCallSettlementJournal(
        event_store, projection_sink=provider_settlement_projection_index
    )
    transport_observer.set_settlement_journal(provider_call_settlement_journal)

    def identity_history_exists(session_id: str) -> bool:
        if archive is None:
            return False
        return int(archive.stats(session_id).get("archived_count", 0)) > 0

    def external_resource_delete_blocker(session_id: str) -> str | None:
        """ST2-D0: fence unfinished execution facts; delete never auto-cancels/reclaims."""
        sid = _validate_session_id(session_id)
        from llm_loop.core.external_execution import ExternalExecutionJournal

        durable = ExternalExecutionJournal(event_store).nonterminal(sid)
        local = JobRegistry.instance().active_for_session(sid)
        job_ids = sorted({state.job_id for state in durable} | {entry.id for entry in local})
        if not job_ids:
            return None
        visible = ", ".join(job_ids[:3])
        suffix = "…" if len(job_ids) > 3 else ""
        return (
            f"会话仍拥有 {len(job_ids)} 个未终态外部执行（{visible}{suffix}）；"
            "为保留执行归属/终态事实，拒绝物理删除。请先等待结束或显式终止后重试。"
        )

    def delete_session_sidecars(session_id: str) -> None:
        sid = _validate_session_id(session_id)
        if archive is not None:
            archive.delete_session(sid)
        backup_store.delete_source(sid, target_type="session")
        delete_feedback_for_session(Path(settings.data_dir) / "feedback.jsonl", sid)
        long_answer_dir = Path(settings.data_dir) / "audit" / "long_answers" / sid
        if long_answer_dir.is_symlink():
            long_answer_dir.unlink()
        elif long_answer_dir.exists():
            shutil.rmtree(long_answer_dir)
        # Evidence ownership outlives the current rollout mode.  Deleting a session while
        # EVIDENCE_MODE=off must still retire any records created by a previous shadow/enforce run.
        evidence_root = settings.evidence_dir
        if (evidence_root / "ledger").exists():
            from llm_loop.memory.evidence import BlobStore, EvidenceLedgerStore
            from llm_loop.memory.evidence_legacy import EvidenceLifecycle

            EvidenceLifecycle(
                BlobStore(evidence_root / "blobs"),
                EvidenceLedgerStore(evidence_root / "ledger"),
            ).delete_session(sid)
        # Model-authored synopses never widen beyond the producing session, even when
        # their cited source is workspace-scoped. Session deletion retires those
        # derived records and safely GCs source snapshots that no remaining record uses.
        SynopsisStore(settings.data_dir).delete_session(sid)

    session_store = SessionStore(
        settings.sessions_dir,
        event_store=event_store,
        read_path_source=getattr(settings, "read_path_source", "session_json"),
        identity_root=settings.sessions_dir,
        identity_history_exists_fn=identity_history_exists,
        delete_sidecars_fn=delete_session_sidecars,
        delete_resource_blocker_fn=external_resource_delete_blocker,
    )

    # 工具注册表（3 基础工具 + 自省/修正/检索工具）
    registry = ToolRegistry(
        tool_timeout_s=settings.tool_timeout_s,
        max_output_chars=settings.tool_max_output_chars,
        # EVO-20260822-b3e7105e: local 模型预算联动收紧参数（默认 0=未启用，云端零回归）
        archive_store=archive,  # T22: 超长工具结果另存
        exec_mode=settings.exec_mode,  # EVO-20260810-2549e9b6: EXEC_MODE 命令分级
        exec_allowlist=settings.exec_allowlist,
        memory_store=memory,  # EVO-d78b270c: 经验驱动注入（M41 升级，失败回执检索经验库）
        approval_audit_path=settings.audit_dir / "approval_audit.jsonl",  # T5a: 审批审计落盘
        safety_audit_dir=settings.audit_dir,  # P0-1: 灾难性阻断审计 safety_blocks.jsonl
    )
    # EW2-A: background external executions keep process-local handles, while the
    # shared EventStore owns durable launch/terminal/cancel facts.  Session cancellation
    # only signals currently local handles; normal model final remains unaffected.
    _job_registry = JobRegistry.instance()
    _job_registry.configure(event_store=event_store)
    registry.add_session_cancel_hook(_job_registry.cancel_session)

    # ERC v1.1 rollout: explicit opt-in only.  Default ``off`` creates no Evidence store
    # and installs no hook.  ``shadow`` dual-writes legacy bytes; ``enforce`` performs
    # capture-before-projection and emits a bounded recovery capsule.
    _legacy_evidence_migrate_workspace_fn: Callable[[str], object] | None = None
    task_evidence_verifier: Any | None = None
    evidence_blobs: Any | None = None
    evidence_ledger: Any | None = None
    evidence_owner_resolver: Callable[[], Any] | None = None
    if settings.evidence_mode in {"shadow", "enforce"}:
        from llm_loop.core.run_context import current_session_id, workspace_base
        from llm_loop.memory.evidence import (
            BlobStore,
            EvidenceCapture,
            EvidenceLedgerStore,
            OwnerScope,
            ProjectionEngine,
        )

        evidence_root = settings.evidence_dir
        evidence_blobs = BlobStore(evidence_root / "blobs")
        evidence_ledger = EvidenceLedgerStore(evidence_root / "ledger")
        evidence_capture = EvidenceCapture(evidence_blobs, evidence_ledger)

        def _evidence_owner_for_session(session_id: str) -> OwnerScope:
            if not session_id:
                raise RuntimeError("evidence capture 缺少 current session id")
            return OwnerScope(
                workspace_id=os.path.abspath(workspace_base()),
                session_id=session_id,
            )

        def _evidence_owner() -> OwnerScope:
            sid = current_session_id.get() or registry._session_id
            return _evidence_owner_for_session(sid)

        evidence_owner_resolver = _evidence_owner

        task_evidence_verifier = TaskEvidenceVerifier(
            evidence_blobs,
            evidence_ledger,
            owner_resolver=_evidence_owner,
        )

        if settings.evidence_mode == "shadow":
            from llm_loop.tools.evidence_shadow import EvidenceShadowRecorder

            registry.set_evidence_shadow_hook(
                EvidenceShadowRecorder(evidence_capture, owner_resolver=_evidence_owner)
            )
            logger.info(
                "Evidence Recoverability shadow dual-write 已启用（不改变 prompt/tool 可见输出）"
            )
        else:
            from llm_loop.memory.evidence import (
                Coverage,
                EvidenceFreshness,
                EvidenceRef,
                EvidenceSearch,
                ManifestProjector,
                Provenance,
                SourceIdentity,
                SourceKind,
                SourceVersionPolicy,
                make_capture_request,
                render_recovery_manifest,
            )
            from llm_loop.tools.evidence_enforce import EvidenceEnforcer
            from llm_loop.tools.evidence_source_resolver import EvidenceSourceResolver
            from llm_loop.tools.evidence_tools import (
                EvidenceListTool,
                EvidenceReadTool,
                EvidenceSearchTool,
                SearchArchiveCompatTool,
            )

            evidence_freshness = EvidenceFreshness(evidence_ledger)
            evidence_search = EvidenceSearch(evidence_blobs, evidence_ledger)
            evidence_manifest = ManifestProjector(evidence_ledger)
            registry.set_evidence_enforcer(
                EvidenceEnforcer(
                    evidence_capture,
                    projection=ProjectionEngine(),
                    owner_resolver=_evidence_owner,
                    projection_budget_chars=min(settings.tool_max_output_chars, 5000),
                )
            )
            registry.set_evidence_source_resolver(
                EvidenceSourceResolver(
                    evidence_ledger,
                    freshness=evidence_freshness,
                    owner_resolver=_evidence_owner,
                    # R8.24-C C-D9: 复用命中内联正文所需 blob 面 + 内联预算（与 enforcer
                    # projection budget 同源）；缺 blob 面时命中如实 failure（不静默吞正文）。
                    blobs=evidence_blobs,
                    inline_budget_chars=min(settings.tool_max_output_chars, 5000),
                )
            )
            registry.register(
                EvidenceReadTool(
                    evidence_blobs,
                    evidence_ledger,
                    freshness=evidence_freshness,
                    owner_resolver=_evidence_owner,
                )
            )
            registry.register(
                EvidenceSearchTool(
                    evidence_search,
                    freshness=evidence_freshness,
                    owner_resolver=_evidence_owner,
                )
            )
            registry.register(
                SearchArchiveCompatTool(
                    evidence_search,
                    freshness=evidence_freshness,
                    owner_resolver=_evidence_owner,
                )
            )
            registry.register(
                EvidenceListTool(
                    evidence_ledger,
                    freshness=evidence_freshness,
                    owner_resolver=_evidence_owner,
                    recovery_manifest_provider=lambda limit: _evidence_manifest_provider(limit),
                )
            )

            def _evidence_manifest_provider(limit: int) -> str:
                owner = _evidence_owner()
                manifest = evidence_manifest.build_recent(owner=owner, limit=max(1, limit))
                for entry in manifest.entries:
                    evidence_freshness.refresh(owner=owner, evidence_ref=entry.evidence_ref)
                return render_recovery_manifest(
                    evidence_manifest.build_recent(owner=owner, limit=max(1, limit))
                )

            def _capture_compressed_history(
                session_id: str, msg, msg_seq: int | None, archive_id: str | None
            ) -> str | None:
                owner = _evidence_owner_for_session(session_id)
                existing = str((msg.metadata or {}).get("evidence_ref", "") or "")
                if existing:
                    try:
                        existing_ref = EvidenceRef(existing)
                        evidence_ledger.require_authorized(owner, existing_ref)
                        return existing_ref.ref
                    except Exception:  # noqa: BLE001 - invalid/stale metadata falls through to capture
                        logger.debug(
                            "compressed message evidence_ref 无法复用，重新建立记录", exc_info=True
                        )
                if msg.tool_call_id:
                    for prior in evidence_ledger.find_by_tool_call_id(owner, msg.tool_call_id):
                        if not msg.tool_name or prior.tool_name == msg.tool_name:
                            return prior.evidence_ref.ref
                digest = hashlib.sha256(
                    f"{msg.role}\0{msg.tool_call_id or ''}\0{msg.content}".encode()
                ).hexdigest()
                if msg_seq is not None:
                    stable_capture_id = f"history-msg:{msg_seq}"
                    source_slot = str(msg_seq)
                elif archive_id:
                    stable_capture_id = f"history-archive:{archive_id}"
                    source_slot = archive_id
                else:
                    # `Message.ts` is persisted session identity.  Include it so two distinct
                    # observations with identical text do not collapse into one logical record,
                    # while provider replay of the same Message remains deterministic.
                    ts_ns = int(float(getattr(msg, "ts", 0.0) or 0.0) * 1_000_000_000)
                    stable_capture_id = f"history-ts:{ts_ns}:{msg.role}:{digest}"
                    source_slot = f"ts-{ts_ns}"
                acquired_at = datetime.fromtimestamp(float(getattr(msg, "ts", 0.0) or 0.0), UTC)
                result = evidence_capture.capture(
                    make_capture_request(
                        owner=owner,
                        stable_capture_id=stable_capture_id,
                        raw_observation=msg.content,
                        acquired_at=acquired_at,
                        tool_name=msg.tool_name or f"history_{msg.role}",
                        tool_call_id=msg.tool_call_id,
                        source=SourceIdentity(
                            kind=SourceKind.CONVERSATION,
                            locator=f"conversation:{msg.role}:{source_slot}",
                            version_policy=SourceVersionPolicy.SNAPSHOT_ONLY,
                        ),
                        coverage=Coverage(
                            unit="message", start=0, end_exclusive=None, source_complete=True
                        ),
                        provenance=Provenance(
                            producer="history_compression",
                            authority="session_message",
                            scope=msg.role,
                        ),
                    )
                )
                return result.evidence_ref.ref

            registry.set_evidence_manifest_provider(_evidence_manifest_provider)
            registry.set_evidence_history_capture_hook(_capture_compressed_history)

            from llm_loop.memory.evidence_legacy import LegacySidecarMigrator

            def _migrate_legacy_evidence_for_workspace(workspace_root: str) -> object:
                return LegacySidecarMigrator(
                    data_dir=settings.data_dir,
                    sessions=session_store,
                    capture=evidence_capture,
                    ledger=evidence_ledger,
                    workspace_id=os.path.abspath(workspace_root),
                ).migrate_all()

            _legacy_evidence_migrate_workspace_fn = _migrate_legacy_evidence_for_workspace
            logger.info(
                "Evidence Recoverability enforce 已启用（capture-before-projection + read/search/list + manifest）"
            )

    # EVO-20260813-9ced1f4c: 工具执行瀑布装配（默认全关零回归；开关经 .env 启用）
    from llm_loop.tools.pipeline import PipelineConfig, ToolExecutionPipeline

    _pipe_cfg = PipelineConfig(
        enabled=settings.tool_pipeline_enabled,
        materialize=settings.tool_materialize_enabled,
        guard=settings.tool_guard_enabled,
    )
    if _pipe_cfg.enabled:
        registry.set_pipeline(ToolExecutionPipeline(_pipe_cfg))
        logger.info(
            "工具执行瀑布已启用 materialize=%s guard=%s",
            _pipe_cfg.materialize,
            _pipe_cfg.guard,
        )
    # R1(2026-08-14): 基础工具注册统一走下方 `_register_basic`（RUN_MODE hidden 过滤生效；
    # 此处不再重复注册——历史残留双注册导致重名覆盖告警 + minimal 模式过滤失效）
    # EVO-20260814 P1-A: RUN_MODE 装配（creative 放宽默认参数）
    _run_mode = getattr(settings, "run_mode", "standard")
    _hidden = _run_mode_hidden(_run_mode)
    if _run_mode == "creative":
        _tool_timeout = settings.tool_timeout_s * 1.5
        _max_output = settings.tool_max_output_chars * 2
    else:
        _tool_timeout = settings.tool_timeout_s
        _max_output = settings.tool_max_output_chars

    def _register_basic(name: str, tool: Any) -> None:
        if name not in _hidden:
            registry.register(tool)

    # EW2-C: one workspace-scoped immutable artifact store is shared by deterministic
    # file producers and readers.  It records only exact bytes/path/hash/owner facts.
    try:
        _artifact_store: WorkspaceArtifactStore | None = WorkspaceArtifactStore(settings.data_dir)
    except OSError:
        # Artifact identity is a continuity aid, not permission to make the whole
        # runtime unavailable.  Tools remain usable and report ref unavailability.
        _artifact_store = None
        logger.warning("workspace artifact store unavailable; artifact refs disabled", exc_info=True)
    _file_service = FileService(
        artifact_store=_artifact_store,
        lock_root=Path(settings.data_dir) / "file_locks",
    )
    _file_effect_query = FileEffectQueryService(event_store)
    _human_file_operations = HumanFileOperationService(
        session_store=session_store,
        event_store=event_store,
        file_service=_file_service,
        query_service=_file_effect_query,
    )
    _register_basic(
        "read_file",
        ReadFileTool(artifact_store=_artifact_store, file_service=_file_service),
    )
    try:
        _attachment_store_for_tools = AttachmentStore(settings.data_dir)
    except OSError:
        _attachment_store_for_tools = None
        logger.warning("attachment store unavailable; read_attachment disabled", exc_info=True)
    if _attachment_store_for_tools is not None:
        _register_basic("read_attachment", ReadAttachmentTool(_attachment_store_for_tools))

    # Long-source synopsis substrate: exact source identity/integrity is program-owned;
    # synopsis text remains model-authored. No automatic producer or prompt injection.
    _synopsis_store = SynopsisStore(settings.data_dir)

    def _resolve_synopsis_source(source_ref: str) -> SourceSnapshot:
        ref = str(source_ref or "").strip()
        scope = runtime_workspace_base()
        sid = current_session_id_ctx.get() or registry._session_id
        if ref.startswith("attachment://"):
            if _attachment_store_for_tools is None:
                raise SynopsisError("attachment store 当前不可用。")
            record, text = _attachment_store_for_tools.ensure_full_text(
                ref, workspace_scope=scope
            )
            return SourceSnapshot(
                source_ref=ref,
                source_kind="attachment",
                text=text,
                source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                source_chars=len(text),
                source_complete=record.extraction_complete,
                representation=record.extraction_kind or "attachment_text",
                access_scope="workspace",
                origin_sha256=record.sha256,
            )
        if ref.startswith("artifact://v1/"):
            if _artifact_store is None:
                raise SynopsisError("artifact store 当前不可用。")
            snapshot, data = _artifact_store.hydrate(ref, workspace_scope=scope)
            text = data.decode("utf-8", errors="replace")
            return SourceSnapshot(
                source_ref=ref,
                source_kind="artifact",
                text=text,
                source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                source_chars=len(text),
                source_complete=True,
                representation="artifact_utf8_text",
                access_scope="workspace",
                origin_sha256=snapshot.record.sha256,
            )
        if ref.startswith("evidence://v1/"):
            if evidence_blobs is None or evidence_ledger is None or evidence_owner_resolver is None:
                raise SynopsisError("Evidence store 当前不可用。")
            owner = evidence_owner_resolver()
            evidence_ref = EvidenceRef(ref)
            try:
                record = evidence_ledger.require_authorized(owner, evidence_ref)
                text = evidence_blobs.read_text(record.blob_ref)
            except EvidenceError as exc:
                raise SynopsisError("Evidence source 当前不可访问或完整性校验失败。") from exc
            return SourceSnapshot(
                source_ref=ref,
                source_kind="evidence",
                text=text,
                source_sha256=record.blob_ref.sha256,
                source_chars=len(text),
                source_complete=bool(record.coverage.source_complete),
                representation="evidence_exact_observation",
                access_scope="session",
                origin_sha256=record.blob_ref.sha256,
            )
        if ref.startswith("truncated:"):
            if not sid:
                raise SynopsisError("truncated source 缺少当前 session。")
            offset = 0
            chunks: list[str] = []
            exact = False
            while True:
                page = episode_store.hydrate_truncated(
                    sid, ref, offset=offset, max_chars=100_000
                )
                if page is None:
                    raise SynopsisError("truncated source 不存在或当前 session 无权访问。")
                total = int(page.get("total_chars") or 0)
                if total > MAX_SOURCE_SNAPSHOT_CHARS:
                    raise SynopsisError(
                        f"source 超过 synopsis snapshot 物理上限 {MAX_SOURCE_SNAPSHOT_CHARS} chars。"
                    )
                chunks.append(str(page.get("content") or ""))
                exact = bool(page.get("exact_artifact"))
                next_offset = page.get("next_offset")
                if next_offset is None:
                    break
                next_int = int(next_offset)
                if next_int <= offset:
                    raise SynopsisError("truncated source 分页未前进。")
                offset = next_int
            text = "".join(chunks)
            return SourceSnapshot(
                source_ref=ref,
                source_kind="truncated",
                text=text,
                source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                source_chars=len(text),
                # The exact bytes captured before interruption are complete as a
                # snapshot, but the underlying generation itself was interrupted.
                source_complete=False,
                representation=(
                    "provider_partial_exact_artifact" if exact else "legacy_truncated_tail"
                ),
                access_scope="session",
                origin_sha256=str(page.get("partial_sha256") or ""),
            )
        raise SynopsisError("source_ref scheme 不受 synopsis exact-source contract 支持。")

    _register_basic(
        "source_synopsis",
        SourceSynopsisTool(_synopsis_store, _resolve_synopsis_source),
    )
    # EVO-20260820-5d0a7b99: 图像转结构化文本证据（元信息 + 内容识别，借鉴 DSH rc.8 工具层视觉）
    _register_basic("read_image", ReadImageTool())
    # EVO-20260817: 代码结构概览（AST 索引，最高 ROI 能力工具——大项目定位提速）
    _register_basic("inspect_code", InspectCodeTool())
    # M51: 四段式文件修改（read→match→diff→apply+verify，替代 sed/heredoc 盲替换）
    _register_basic(
        "edit_file",
        EditFileTool(artifact_store=_artifact_store, file_service=_file_service),
    )
    # EVO-d5db88d9: 按需读取工具完整 Schema（懒加载配套；零副作用可始终注册）
    from llm_loop.tools.registry import GetToolSchemaTool

    registry.register(GetToolSchemaTool(registry))
    # M18 AA8: 工具内兜底超时读配置值（注册表另有线程级超时兜底）
    _register_basic("execute_command", ExecuteCommandTool(timeout_s=_tool_timeout))
    # EVO-20260814: 后台任务查询/终止（配合 execute_command run_in_background=true）
    _register_basic("job_output", JobOutputTool())
    _register_basic("job_kill", JobKillTool())
    # DSH-PLUGINS-20260816 ③: 文件搜索（glob + 内容 grep，工具优先免碎调用）
    _register_basic("search_files", SearchFilesTool())
    # DSH-PLUGINS-20260816 ②: 定时提醒（at/after/rate → interop notify 注入会话）
    # BUGFIX(2026-08-27 双Store分裂): 注册工具与 SchedulerThread 共享同一
    # ScheduleStore 实例——原 ScheduleTool() 惰性自建与下方 engine.scheduler
    # 装配处 ScheduleStore() 分裂为两个实例，due() 只扫内存互不可见 → 永不触发；
    # 路径从 settings.data_dir 绝对化派生，消除 LFL_DATA_DIR env 与进程 cwd
    # 双基准导致的落点分裂（实证：注册与调度写读不同 schedule.json）。
    _schedule_store = ScheduleStore(
        Path(settings.data_dir).resolve() / "schedule.json"
    )
    _register_basic("schedule", ScheduleTool(store=_schedule_store))
    _register_basic("schedule_cancel", ScheduleCancelTool(store=_schedule_store))
    _register_basic("web_fetch", WebFetchTool(timeout_s=_tool_timeout))
    # M48: 网络搜索（Bing/百度双后端降级）
    _register_basic("web_search", WebSearchTool(timeout_s=_tool_timeout))

    # P3-1(2026-08-15): MCP 客户端接入（MCP_SERVERS env；stdio 连接 + schema 透传 +
    # 五态包装 + 超时/审计复用；单服务器 fail-open）
    try:
        from llm_loop.tools.mcp_client import register_mcp_tools

        _mcp_tools = register_mcp_tools(registry, settings.mcp_servers_raw)
        if _mcp_tools:
            logger.info("MCP 工具注册 %d 个: %s", len(_mcp_tools), ", ".join(_mcp_tools[:6]))
    except Exception:  # noqa: BLE001 — MCP 装配失败不影响核心链路
        logger.exception("MCP 工具装配失败（fail-open）")

    # EVO-20260811-f94e5306: 变更通告（修改类工具调用记录，多会话协调）
    def _change_log_hook(call):
        from llm_loop.introspection.proc_version import record_change_log

        if call.name in (
            "execute_command",
            "write_file",
            "edit_file",
            "delete_file",
            "append_file",
        ):
            record_change_log(
                call.name, f"arguments={str(call.arguments)[:200]}", session_id=registry._session_id
            )

    registry.add_pre_execute_hook(_change_log_hook)

    # P1: 嵌入服务（EMBEDDING_PROVIDER, §3.6）
    embedder = None
    if settings.embedding_provider == "hash":
        from llm_loop.memory.embedder import HashEmbedder

        embedder = HashEmbedder(dim=settings.embedding_dim)
    elif settings.embedding_provider == "api":
        from llm_loop.memory.embedder import APIEmbedder

        embedder = APIEmbedder(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
        )
    # none → embedder 保持 None（SemanticRetriever.semantic_available()=False → 关键词路径）

    # P1: 语义检索器（RETRIEVE_*, §3.6）
    semantic_retriever = None
    if embedder is not None:
        from llm_loop.memory.retriever import SemanticRetriever

        semantic_retriever = SemanticRetriever(
            embedder,
            timeout_s=settings.retrieve_timeout_s,
            semantic_top_k=settings.retrieve_semantic_top_k,
            memory_dir=settings.memory_dir,
            archive_dir=settings.archive_dir,
        )

    # 架构自省（M17 FR-REVIEW-AI-05: config_status 闭包含演进状态摘要，fail-open;
    # M18 AA10: memory_stats_fn 补记忆真实数据）
    status_provider = ArchitectureStatusProvider(
        audit_dir=settings.audit_dir,
        cooldown_s=settings.status_report_cooldown_s,
        enabled=settings.self_inspection_enabled,
        config_status=_build_config_status_with_evolution(settings, model_registry_resolved),
        archive_stats_fn=(
            (lambda: {"archived_total": 0})
            if archive is None
            else lambda: _sum_archive_stats(archive)
        ),
        memory_stats_fn=_build_memory_stats_fn(memory),
        # P1-12(2026-08-16): 工作区变更检测——guard 检测 .env/providers.json/src/skills
        # 变化后写 data/workspace_changed.json, AI 经 architecture_status 自查可见
        workspace_changed_fn=lambda: _read_workspace_changed_flag(settings.data_dir),
        # spec 5.3.1/D6: 路由三元组（进程级一次解析，随审计行顺带落盘）
        route_fn=lambda: get_route_context().__dict__,
    )

    # spec 6.5.4/D6: route.missing 留痕回调接既有审计单口（C-G1 遗留接线，恰一次）
    set_route_audit_fn(status_provider.record_action)

    # M2-G1.1: tool_octet 观测流 sink 一次性接线（沿用 set_route_audit_fn 装配模式；
    # writer 仍为 status_provider._write_audit 单一 SoT；开关门控在 observer 首行，装配不判环境）
    register_octet_sink(status_provider.append_audit_line)

    # M56 B5（ANALYSIS-20260811）: 当前模型窗口注入 architecture_status（AI 可查后
    # 自主决策上下文压缩；resolve 失败/未知模型如实返回 label+context=None，不伪造）
    def _model_window_snapshot() -> dict:
        try:
            registry_snapshot = model_pool.default_registry_snapshot()
            pid, mid = registry_snapshot.resolve(settings.llm_model)
            spec = registry_snapshot.providers[pid].models.get(mid)
            return {"label": f"{pid}/{mid}", "context": spec.context if spec else None}
        except Exception:  # noqa: BLE001 — 窗口查询失败如实降级
            return {"label": settings.llm_model, "context": None}

    status_provider.set_model_context_fn(_model_window_snapshot)

    # 修正/检索工具注册表（M12 T50: RuntimeParams 与 ctx.strategy 共享 dict 引用）
    from llm_loop.core.runtime_params import RuntimeParams

    correction_ctx = CorrectionContext()
    correction_ctx.task_evidence_verifier = task_evidence_verifier
    runtime = RuntimeParams(settings, strategy=correction_ctx.strategy)
    runtime.set_persist_path(settings.audit_dir / "param_adjust_history.jsonl")
    runtime.set_max_adjust_per_round(settings.param_adjust_per_round)
    correction_ctx.runtime = runtime  # T50: adjust_strategy 消费/计数经 runtime
    # M57 配置面收敛: architecture_status 展示 adjust_strategy 当前生效值（AI 可查可验证）
    status_provider.set_runtime_params_fn(lambda: runtime.current())
    # M59 配置面收敛: 语义检索召回上限接 runtime（AI 经 adjust_strategy 可调）
    if semantic_retriever is not None:
        semantic_retriever.set_top_k_provider(lambda: runtime.retrieve_semantic_top_k)
    corrections = CorrectionToolRegistry(
        correction_ctx,
        audit_dir=settings.audit_dir,
        status_provider=status_provider,
        archive_store=archive,  # T22: search_archive
    )
    correction_ctx.retry_executor = lambda name, args: registry.execute(_make_tool_call(name, args))
    # M50（design §5.6）: refresh_config 扩展 — 重载 env 同时重读 data/providers.json，重建注册表
    # 失败保持旧 registry + 如实标注 (DFX-REL-08 fail-open)
    # 实现提取至 introspection/providers_registry_reload.py 以便于独立测试
    from llm_loop.introspection.providers_registry_reload import install_refresh_executor

    # 临时初始化为占位 (factory 尚未构造 engine 上下文, install 时机选在 LoopEngine 构造后)
    correction_ctx.refresh_executor = lambda: "配置重载执行器待 install (M50)"

    # M12 T52: 演进建议存储装配
    from llm_loop.introspection.evolution import EvolutionStore

    correction_ctx.evolution_store = (
        EvolutionStore(settings.audit_dir) if settings.evolve_enabled else None
    )
    correction_ctx.evolve_local_exec = settings.evolve_local_exec
    correction_ctx.evolve_exec_whitelist = settings.evolve_exec_whitelist
    # M16 审计（FR-AUDIT-AI-01/05/06）: 验证/回滚经 RULE-AI-06 移交 AI（程序不代验证/回滚），
    # 不装配 EvolutionVerifier/ExecutionRollback（模块已删除）
    # M12 深化 T64: 自我评估器装配（EVAL-01/04，数据源复用 status + audit JSONL）
    from llm_loop.introspection.evaluator import SelfEvaluator

    correction_ctx.evaluator = SelfEvaluator(
        status_provider=status_provider,
        audit_dir=settings.audit_dir,
        min_samples=getattr(settings, "self_eval_min_samples", 5),
        span=getattr(settings, "self_eval_span", 50),
        # EVO-20260816-f1f73a0d: 采样时间窗 24h（防历史异常污染当前评估）
        window_hours=24.0,
    )
    # M48（design §5.3）: 模型路由池注入；session_set_override 回调在 run() 内动态绑定，
    # 此处先注入 pool 让 tool_defs() 完整（让 LLM 在工具列表中看到 model_catalog/switch_model）
    correction_ctx.model_pool = model_pool

    # T23: 统一检索实现注入（search_records）+ T31 语义路径
    # P1-2: 经验库装配（fail-open，目录不存在时检索如实返回未命中）
    from llm_loop.experiences.store import ExperienceStore

    experience_store = ExperienceStore(
        settings.experiences_dir, embedder=embedder
    )  # T5: 注入 embedder 供语义检索
    method_store = MethodStore(settings.methods_dir, seed_dir=settings.method_seed_dir)
    searcher = RecordSearcher(
        audit_dir=settings.audit_dir,
        memory_store=memory,
        archive_store=archive,
        episode_store=episode_store,
        experience_store=experience_store,  # P1-2: 经验库检索接入
        method_store=method_store,
        semantic_retriever=semantic_retriever,  # T31: 语义召回
        file_effect_query=_file_effect_query,
        synopsis_store=_synopsis_store,
        synopsis_source_resolver=_resolve_synopsis_source,
    )

    # EVO-20260814: 适配器同时支持 search_records（可调用）与 event_stream（对象方法）
    class _RecordSearcherAdapter:
        """可调用 + 方法双接口（search 走调用，event_stream 走方法）."""

        def __init__(self, searcher: Any) -> None:
            self._searcher = searcher

        def __call__(self, **kw: Any) -> list[dict]:
            return self._searcher.search(**kw)

        def event_stream(self, **kw: Any) -> list[dict]:
            return self._searcher.event_stream(**kw)

        def hydrate_episode(self, **kw: Any) -> dict | None:
            return self._searcher.hydrate_episode(**kw)

        @property
        def last_diagnostics(self) -> Any:
            """R3(P0-3): experience 检索诊断透传（工具层 duck-typing 读取；缺失 None）."""

            return getattr(self._searcher, "last_diagnostics", None)

    corrections._search_records_fn = _RecordSearcherAdapter(searcher)  # noqa: SLF001
    corrections._experience_store = experience_store  # noqa: SLF001 — P1-2: 工具分派注入
    corrections._method_store = method_store  # noqa: SLF001 — Method lifecycle/tool actions

    # P2-3: docs/ 文档语义检索装配（fail-open，不阻断启动）
    try:
        docs_searcher = DocsSearcher(
            docs_dir=settings.docs_dir,
            semantic_retriever=semantic_retriever,
        )

        class _DocsSearcherAdapter:
            """A4: 包装 DocsSearcher（search + recent_docs 通道，供 search_docs 未命中引导）."""

            def __init__(self, searcher: DocsSearcher) -> None:
                self._searcher = searcher

            def __call__(self, **kw: Any) -> list[dict]:
                return self._searcher.search(**kw)

            def recent_docs(self, limit: int = 5) -> list[dict]:
                return self._searcher.recent_docs(limit=limit)

        corrections._search_docs_fn = _DocsSearcherAdapter(docs_searcher)  # noqa: SLF001
    except Exception:  # noqa: BLE001 — 装配失败不阻断启动
        logger.warning(
            "docs/ 检索装配失败（fail-open），search_docs 将回执'检索不可用'", exc_info=True
        )

    # P2-2: fail-open 数据丢失恢复通道装配
    from llm_loop.recovery.channel import RecoveryChannel

    def _recovery_action_trace(action_type: str, detail: str) -> None:
        with suppress(Exception):
            status_provider.record_action("recovery", action_type, detail)

    recovery_channel = RecoveryChannel(
        backup_store=backup_store,
        action_trace_fn=_recovery_action_trace,
    )
    # 启动时清理超期超量备份（fail-open，不影响启动）
    try:
        cleanup_result = backup_store.cleanup()
        if cleanup_result.get("pruned", 0) > 0:
            logger.info("恢复备份 GC: 清理 %s 份过期/超量备份", cleanup_result["pruned"])
    except Exception:  # noqa: BLE001 — GC 失败不影响启动
        logger.warning("恢复备份 GC 启动清理失败（fail-open）", exc_info=True)
    corrections._recovery_channel = recovery_channel  # noqa: SLF001 — P2-2: 工具分派注入
    corrections._recovery_sessions_dir = settings.sessions_dir  # noqa: SLF001 — 兼容fallback
    corrections._recovery_sessions_dir_fn = lambda: session_store.root  # noqa: SLF001 — workspace动态根
    corrections._recovery_session_store = session_store  # noqa: SLF001 — 复用全局sid归属/原子恢复
    corrections._recovery_memory_dir = settings.memory_dir  # noqa: SLF001
    corrections._skills_dir = settings.skills_dir or None  # noqa: SLF001 — B3: 插件化 Skill 目录注入
    status_provider.set_recovery_status_fn(backup_store.status_summary)

    # 自省/修正/检索工具注册进 ToolRegistry（LLM 可见）
    # EVO-20260814 P1-A: RUN_MODE=minimal 时过滤外围工具（飞书出站/playwright/record_skill）
    _corr_hidden = set(_run_mode_hidden(_run_mode))
    if settings.evidence_mode == "enforce":
        _corr_hidden.add("search_archive")
    for td in corrections.tool_defs():
        if td["name"] in _corr_hidden:
            continue
        registry.register(
            _CorrectionAdapterTool(
                corrections,
                name=td["name"],
                description=td["description"],
                parameters=td["parameters"],
            )
        )

    # 架构自省：动作轨迹采集挂钩到工具执行前
    registry.add_pre_execute_hook(
        lambda call: status_provider.record_action("action.tool_loop", "tool_call", f"{call.name}")
    )

    # P1: 声明-回执语义匹配（VALIDATE_SEMANTIC=1 时注入，默认关 → P0 行为）
    semantic_matcher: Callable[[str, str], float] | None = None
    if settings.validate_semantic and embedder is not None:
        from llm_loop.memory.embedder import cosine_similarity

        def _semantic_matcher_fn(a: str, b: str) -> float:
            va = embedder.embed(a)
            vb = embedder.embed(b)
            if va is None or vb is None:
                return 0.0
            return cosine_similarity(va, vb)

        semantic_matcher = _semantic_matcher_fn

    validator = DeclarationValidator(
        audit_dir=settings.audit_dir,
        semantic_matcher=semantic_matcher,
        semantic_threshold=settings.validate_semantic_threshold,
    )

    # P1: LLM 摘要器（SUMMARY_MODE，§3.6）
    # R6: SUMMARY_MODEL 指定独立摘要模型（成本隔离）；未配置/构造失败 → 回退主模型（fail-open）
    summarizer = None
    if settings.summary_mode in {"sync", "async"}:
        from llm_loop.memory.summarize import Summarizer

        summary_client = llm
        if settings.summary_model:
            try:
                summary_client = model_pool.get_client(settings.summary_model)
            except Exception as exc:  # noqa: BLE001 — 独立摘要模型不可用如实 warning + 回退主模型
                logger.warning(
                    "独立摘要模型 %s 不可用，回退主模型（fail-open）: %s",
                    settings.summary_model,
                    exc,
                )
                summary_client = llm

        summarizer = Summarizer(
            llm_client=summary_client,
            mode=settings.summary_mode,
            timeout_s=settings.summary_timeout_s,
            max_input_chars=settings.summary_max_input_chars,
        )

    # R2: search_archive(with_summary=true) 时生成 LLM 语义摘要
    correction_ctx.summarizer = summarizer

    # P1: 独立记忆提取器（EXTRACT_*, §3.6）
    extractor = None
    if settings.extract_enabled:
        from llm_loop.memory.extractor import MemoryExtractor

        extractor = MemoryExtractor(
            llm_client=llm,
            memory=memory,
            session_store=session_store,
            enabled=True,
            interval_msgs=settings.extract_interval_msgs,
            cooldown_s=settings.extract_cooldown_s,
            max_input_chars=settings.extract_max_input_chars,
            timeout_s=settings.extract_timeout_s,
            audit_dir=settings.audit_dir,
        )

    engine = LoopEngine(
        llm_client=llm,
        registry=registry,
        memory=memory,
        session=session_store,
        settings=settings,
        validator=validator,
        status_provider=status_provider,
        correction_registry=corrections,
        correction_ctx=correction_ctx,
        archive=archive,  # T22: 压缩档案（history sink）
        summarizer=summarizer,  # T28: LLM 摘要
        extractor=extractor,  # T33: 独立记忆提取
        semantic_retriever=semantic_retriever,  # M11 T45: 语义接线
        runtime=runtime,  # M12 T50: 动态参数视图
        fault_classifier=_build_fault_classifier(),
        selfheal_budget=_build_selfheal_budget(settings),
        loop_signal_detector=_build_loop_signal_detector(),
        llm_pool=model_pool,  # M48（design §5.3）: 会话级模型路由
        recovery=recovery_channel,  # P2-2: fail-open 写失败恢复通道
        event_store=_build_event_store(settings),  # D1: 事件源化（共享同一实例）
        episode_store=episode_store,  # R8.5: resolved episode durable retrieval
    )

    engine.file_effect_query = _file_effect_query
    engine.human_file_operations = _human_file_operations

    if _legacy_evidence_migrate_workspace_fn is not None:
        engine._evidence_legacy_migrate_workspace_fn = _legacy_evidence_migrate_workspace_fn

    # M50（design §5.6）: 注入增强版 refresh_config executor — 重读 providers.json
    install_refresh_executor(engine)

    # Learning Plane（design §5.3）: durable journal + 后台 ReflectionRun 消费者。
    # 默认关闭（LEARNING_PLANE_ENABLED）；关闭时不挂载 engine.learning_journal，
    # post_run 反射检查保持静默 —— 零行为变化、无队列积压。
    engine.learning_plane = None
    foreground_probe = ForegroundActivityProbe(engine, settings.sessions_dir)
    resource_governor = ResourceGovernor(foreground_probe=foreground_probe.active)
    engine.resource_governor = resource_governor
    provider_call_coordinator = ProviderCallCoordinator(
        resource_governor,
        local_runtime=LocalRuntimeConcurrencyAdapter(),
        settlement_journal=provider_call_settlement_journal,
    )
    engine.provider_call_coordinator = provider_call_coordinator
    engine.provider_call_settlement_journal = provider_call_settlement_journal
    engine.provider_settlement_projection_index = provider_settlement_projection_index
    # RG-3C shadow accounting reaches auxiliary provider users without changing
    # their scheduling/admission behavior in this phase.
    if summarizer is not None:
        summarizer.provider_call_coordinator = provider_call_coordinator
    if extractor is not None:
        extractor.provider_call_coordinator = provider_call_coordinator
    if settings.learning_plane_enabled:
        learning_journal = LearningJournal(
            path=Path(settings.sessions_dir) / "learning" / "journal.jsonl",
            candidate_lookup=method_store.find_by_evidence,
        )
        engine.learning_journal = learning_journal

        def _resolve_learning_resource_target(model_ref: str) -> tuple[str, str]:
            return model_pool.registry.resolve(model_ref or settings.llm_model)

        learning_plane = LearningPlane(
            journal=learning_journal,
            episode_store=episode_store,
            method_store=method_store,
            engine=engine,
            model_resolver=model_pool.get_client,
            resource_governor=resource_governor,
            resource_target_resolver=_resolve_learning_resource_target,
            provider_call_coordinator=provider_call_coordinator,
        )
        learning_plane.start()
        engine.learning_plane = learning_plane
        logger.info("Learning Plane 已装配并启动 journal=%s", learning_journal._path)
    else:
        logger.debug("Learning Plane 未启用（LEARNING_PLANE_ENABLED）")

    # EVO 后台 run 改造（对齐 DSH 后台任务）：装配后台 run 执行器——SSE 端点改订阅，
    # run 在后台 daemon 线程执行，断连只停订阅、结果落盘；RUNNER_BACKGROUND=0 回退旧直驱
    from llm_loop.core.loop.runner import BackgroundRunner

    background_runner = BackgroundRunner(engine, enabled=settings.runner_background)
    engine.runner = background_runner
    logger.info("后台 run 执行器已装配 enabled=%s", settings.runner_background)

    # 调度提醒线程：到点写 interop；R8.12/R8.13 后仅进入 interop UI/action，
    # 不再自动回显给 LLM 或触发模型 run。
    # BUGFIX(2026-08-27): 复用上方工具注册处的 _schedule_store（原此处再建
    # 新实例，双 Store 内存互不可见 → 提醒永不触发）
    try:
        from llm_loop.core.scheduler import ScheduleEntry, SchedulerThread

        def _deliver_schedule(entry: ScheduleEntry) -> bool:
            """提醒交付：普通通知；或持有效 one-shot grant 的同会话续跑。"""
            if not getattr(entry, "wake", False):
                SchedulerThread._notify_via_interop(entry)
                return True

            grant = _schedule_store.wake_grant(entry.sid)
            session_id = str(getattr(entry, "session_id", "") or "")
            if grant is None or not session_id:
                # grant 不持久化：进程重启/owner 退出后安全降级为通知，不伪造授权。
                SchedulerThread._notify_via_interop(entry)
                engine._record_action(
                    "schedule.wake",
                    "degraded_to_notify",
                    f"sid={entry.sid};reason=grant_unavailable;prompt_chars=0",
                )
                return True

            handle, _q = background_runner.start(
                session_id,
                f"[定时续跑·先前真人授权的程序委派·非新真人输入] {entry.message}",
                ingress=grant,
            )
            if handle is not None:
                # Consume the one-shot capability immediately after a real run starts.
                # If schedule ack persistence later fails, a stale entry may notify again
                # but can never launch a second autonomous model run.
                _schedule_store.clear_wake_grant(entry.sid)
                engine._record_action(
                    "schedule.wake",
                    "started",
                    f"sid={entry.sid};session={session_id};delegated=1",
                )
                return True
            if background_runner.is_running(session_id) or background_runner.is_sync_active(session_id):
                engine._record_action(
                    "schedule.wake",
                    "session_busy_retry",
                    f"sid={entry.sid};session={session_id}",
                )
                return False

            # runner disabled/不可启动时不丢提醒，退化为可见通知。
            SchedulerThread._notify_via_interop(entry)
            engine._record_action(
                "schedule.wake",
                "degraded_to_notify",
                f"sid={entry.sid};reason=runner_unavailable;prompt_chars=0",
            )
            return True

        engine.scheduler = SchedulerThread(_schedule_store, notify=_deliver_schedule)
        engine.scheduler.start()
    except Exception:  # noqa: BLE001 — 调度装配失败不影响核心链路
        logger.exception("调度提醒线程装配失败（fail-open）")
        engine.scheduler = None

    # 协调 inbox 主动感知：新 pending 只进入 interop UI/action observability。
    # R8.13/E26 禁止把未绑定外部消息归因到“最近会话”，也禁止 watcher 伪造
    # user_text 自动启动模型。未来由输入侧显式“接受/插入”动作完成用户授权。
    try:
        from llm_loop.core.interop_watch import InboxWatcher

        def _on_inbox_notify(names: Sequence[str]) -> None:
            """Record inbox state without guessing a target conversation."""
            try:
                engine._record_action(
                    "interop.pending_notify",
                    "awaiting_user_authorization",
                    f"count={len(names)};files={', '.join(names)};prompt_chars=0",
                )
            except Exception:  # noqa: BLE001 — observability failure must not block watcher
                logger.warning("interop.pending_notify 审计写入失败（fail-open）")

        def _inbox_wakeup(names: Sequence[str]) -> None:
            """Legacy INBOX_WAKEUP callback: intentionally no model run after R8.13."""
            try:
                engine._record_action(
                    "interop.coordinate_wakeup",
                    "blocked_no_user_authorization",
                    f"files={', '.join(names)};prompt_chars=0",
                )
            except Exception:  # noqa: BLE001 — observability only
                logger.warning("interop.coordinate_wakeup 审计写入失败（fail-open）")

        engine.inbox_watcher = InboxWatcher(
            on_notify=_on_inbox_notify,
            wakeup_fn=_inbox_wakeup,
        )
        engine.inbox_watcher.start()
    except Exception:  # noqa: BLE001 — 监视装配失败不影响核心链路
        logger.exception("协调 inbox 监视装配失败（fail-open）")
        engine.inbox_watcher = None

    # 工作区管理（对齐 DSH Workspace）：注册表 + 旧会话迁移 + 引擎挂载当前工作区。
    # 默认工作区 = 启动 cwd（当前行为一致：工具/会话根=项目根，零回归）。
    from llm_loop.workspace.store import WorkspaceMigrationConflictError, WorkspaceStore

    workspace_store = WorkspaceStore(settings.data_dir)
    default_ws = workspace_store.register(os.getcwd())  # 幂等注册
    try:
        workspace_store.migrate_legacy_sessions(settings.data_dir, default_ws)
    except WorkspaceMigrationConflictError:
        logger.error(
            "工作区旧会话迁移存在数据冲突，拒绝自动选择任一副本；请人工核对后再启动",
            exc_info=True,
        )
        raise
    except Exception:  # noqa: BLE001 — 非数据冲突的迁移异常仍保留启动兼容
        logger.warning("工作区旧会话迁移失败（fail-open）；未完成文件保留在旧根", exc_info=True)
    # 首次装配（注册表无 current）→ 默认工作区设为 current 并持久化
    if workspace_store.get_current() is None:
        workspace_store.switch(default_ws.id)
    current_ws = workspace_store.get_current() or default_ws
    engine.workspace_store = workspace_store  # 先挂注册表，set_workspace 可精确按path/id分区
    engine.set_workspace(current_ws.path, current_ws.id)

    # R1: 上下文占用分解注入 architecture_status（AI 每轮可见，自主决策压缩/切换）
    status_provider.set_context_breakdown_fn(lambda: engine._run_state().last_breakdown)
    # EVO-20260827-ed4c1350（P0-B）: 有效预算归因（engine 每 round 刷新 last_budget_info）
    status_provider.set_budget_fn(lambda: engine._run_state().last_budget_info)
    # 2026-09-04 P1: 最近一次真实 provider request 的 context/cache 事实按需可查，
    # 不再靠 prompt 注入让模型猜 headroom / prefix 漂移。
    status_provider.set_request_usage_fn(
        lambda: engine._run_state().last_request_usage
    )
    status_provider.set_causality_fn(
        lambda sid: diagnose_event_store(engine._event_store, sid)
    )
    # EVO-20260818（spec §5.4.1-2）: cache_health/cache_guard 对外可观测注入——
    # cache_guard 回调透传 session_id（guard 窗口 per-session，grill-me Q11）；fail-open
    try:
        llm.ensure_guard()  # 预创建 guard——快照进程启动即可用（懒创建会让端点首请求前无数据）

        def _cache_health_with_window() -> dict | None:
            """cache_health 快照 + 缓存窗口镜像（2026-08-24: cache.window 可观测）."""
            snap = engine._cache_monitor.snapshot()
            if snap is None:
                return None
            win = getattr(engine._run_state(), "last_cache_window", None)
            if win is None:
                return snap
            snap = dict(snap)
            snap["window"] = {
                "summary": win.summary(),
                "cached_tokens": win.cached_tokens,
                "prompt_tokens": win.prompt_tokens,
                "hit_ratio": round(win.hit_ratio, 4),
                "boundary_chars": win.boundary_chars,
                "boundary_msg_index": win.boundary_msg_index,
                "boundary_mapping": "estimated_message_chars",
                "boundary_exact": bool(getattr(win, "boundary_exact", False)),
                "stable_prefix_fp": engine._run_state().last_cache_window_stable_fp,
                "cache_prefix_epoch": engine._run_state().cache_prefix_epoch,
                "compaction_epoch": engine._run_state().compact_event_seq,
                "cached_msgs": win.cached_msgs[-8:],  # 展示截断（完整见事件日志）
                "new_msgs": win.new_msgs[-8:],
            }
            return snap

        status_provider.set_cache_health_fn(_cache_health_with_window)
        status_provider.set_cache_guard_fn(
            lambda sid: llm.guard.snapshot(session_id=sid) if llm.guard is not None else None
        )
    except Exception:  # noqa: BLE001 — 注入失败 fail-open（字段 None，不影响 engine）
        logger.warning("cache_health/cache_guard 可观测注入失败（fail-open）")

    # T3: 上下文占用率注入 runtime（memory_top_k 自适应消费；breakdown 不可用时走默认值零回归）
    def _context_usage_ratio() -> float:
        bd = engine._run_state().last_breakdown
        if bd is None:
            return 0.0
        total = getattr(bd, "total_chars", 0) or 0
        cap = getattr(bd, "max_chars", 0) or 0
        return total / cap if cap > 0 else 0.0

    runtime.set_context_usage_fn(_context_usage_ratio)
    # T4（spec.md 5.3.1）: 待办聚合注入 architecture_status（AI 一站式感知系统待办）
    status_provider.set_pending_actions_fn(_build_pending_actions_fn(settings))

    # 子代理继承父工具执行域；不因 child 身份维护第二套静态工具能力表。
    # 轮数默认跟随 operator/main resource budget；有限 recursion depth 仍是并发资源边界。
    subagent_runner = SubAgentRunner(
        llm=llm,
        registry=registry,
        session_store=session_store,
        max_iterations=settings.max_iterations,
        tool_execution_root=str(settings.audit_dir / "tool_execution"),
        artifact_store=_artifact_store,
        provider_call_coordinator=provider_call_coordinator,
    )
    # nonblocking child 在 spawn 工具返回后仍属于 parent lifecycle；Stop 必须
    # 通过 session-level hook 继续精确取消，不能依赖 spawn tool active future。
    registry.add_session_cancel_hook(subagent_runner.cancel_parent)
    registry.add_async_obligation_hook(subagent_runner.pending_obligations)
    registry.register(SpawnSubAgentTool(subagent_runner))
    # Agent Communication Contract：统一 agent↔agent 通信 + 显式 child result 查询。
    # 旧 subagent_report 公共工具已退休，不保留第二套投递路径。
    registry.register(AgentMessageTool(subagent_runner))
    registry.register(SubAgentResultTool(subagent_runner))
    engine._tool_receipt_committed_hook = subagent_runner.settle_committed_receipt

    # task_quality 六路径装配（2026-08-17，D3 定案: 动态开关默认关零回归）:
    # 路径 A 预检层注入 ToolRegistry（安全检查前拦截参数错误）；
    # 路径 I FixLoopTool 注册（子代理内修复，P0-D1）。
    from llm_loop.task_quality.error_locate import ErrorLocator
    from llm_loop.task_quality.fix_loop import FixLoopTool
    from llm_loop.task_quality.precheck import PreCheckLayer

    _event_store = _build_event_store(settings)
    # 预检层（动态开关读取 runtime；关闭时 check 恒放行 = 零回归）
    registry.precheck_layer = PreCheckLayer(
        event_store=_event_store,
        session_id="",
        enabled_fn=lambda: getattr(runtime, "precheck_enabled", False),
    )
    # FixLoopTool（动态开关：关闭时 execute 回执未启用）
    registry.register(
        FixLoopTool(
            registry=registry,
            subagent_runner=subagent_runner,
            error_locator=ErrorLocator(event_store=_event_store),
            event_store=_event_store,
            audit_dir=settings.audit_dir,
            enabled_fn=lambda: getattr(runtime, "fix_loop_enabled", False),
        )
    )
    logger.info(
        "task_quality 装配完成: precheck_layer + fix_loop 已注册（开关经 adjust_strategy 动态控制）"
    )
    # EVO-20260814 P1-B: 工作流编排（parallel 聚合 / pipeline 串联，对齐 Harness 多 Agent 编排）
    workflow_tool = WorkflowRunTool(subagent_runner)
    registry.register(workflow_tool)
    # DSH-ORCHESTRATION（2026-08-16）: 调度 DeepSeek Harness headless 执行任务（进程级子代理）
    registry.register(DshTaskTool())
    registry.register(DshSessionReadTool())

    # CodeArts 子 Agent 调度集成（design.md §2.1.2，缺省 fail-open 零装配）
    # CODEARTS_ENABLED=false 或凭证缺失/校验失败 → 跳过装配 + 日志标注，主运行时零回归
    _assemble_codearts(settings, registry, session_store, engine, workflow_tool)

    # 任务12（§5.12）: 启动时残留 run 巡检——超过 STALE_RUN_INSPECT_HOURS 无活跃的后台
    # run 输出 WARN 清单供运维决策（压测残留清理入口 runner.stop）。fail-open 不阻断启动。
    try:
        runner = getattr(engine, "runner", None)
        if runner is not None and getattr(runner, "enabled", False):
            runner.inspect_stale_runs()
    except Exception:  # noqa: BLE001 — 巡检失败不影响启动
        logger.debug("启动残留 run 巡检失败（忽略）", exc_info=True)

    # Runtime causality snapshot is process/startup observability only.  It is
    # computed after the complete tool registry is assembled and never injected into prompts.
    try:
        engine._runtime_causal_snapshot = build_runtime_causal_snapshot(settings, registry)
    except Exception:  # noqa: BLE001 - observability must never block engine startup
        engine._runtime_causal_snapshot = None

    return engine


def _assemble_codearts(
    settings: Settings,
    registry: ToolRegistry,
    session_store: Any,
    engine: Any,
    workflow_tool: Any = None,
) -> None:
    """装配 CodeArts 子 Agent 调度集成（fail-open 全分支覆盖）.

    分支:
    1. settings.codearts.enabled == False → 跳过 + 日志标注"总开关关闭"
    2. 凭证缺失 → 跳过 + 日志标注"缺凭证"
    3. 凭证校验失败 → 跳过 + 日志标注"凭证校验失败: <原因>"
    4. 校验通过 → 构造调度核心 + 注册 4 工具 + 接管在途委派

    全分支 fail-open 不阻断主运行时启动。
    """
    ca = settings.codearts
    if not ca.enabled:
        logger.info("CodeArts 集成未装配（总开关关闭）")
        return
    if not ca.has_credential():
        logger.info("CodeArts 集成未装配（缺凭证：未配置 AK/SK 或 IAM token）")
        return
    try:
        from llm_loop.codearts.audit import AuditLogger
        from llm_loop.codearts.client import HttpxCodeArtsClient
        from llm_loop.codearts.collector import ResultCollector
        from llm_loop.codearts.credential import CredentialError, EnvCredentialProvider
        from llm_loop.codearts.handle import HandleRegistry
        from llm_loop.codearts.risk import PatternRiskClassifier
        from llm_loop.codearts.scheduler import CodeArtsScheduler
        from llm_loop.codearts.sync import PollingSynchronizer
        from llm_loop.tools.builtin.codearts_cancel import CodeArtsCancelTool
        from llm_loop.tools.builtin.codearts_capability import CodeArtsCapabilityTool
        from llm_loop.tools.builtin.codearts_dispatch import CodeArtsDispatchTool
        from llm_loop.tools.builtin.codearts_status import CodeArtsStatusTool
    except ImportError as exc:
        logger.warning("CodeArts 集成模块导入失败（fail-open）: %s", exc)
        return

    try:
        credential_provider = EnvCredentialProvider(ca)
        client = HttpxCodeArtsClient(ca)
        # 凭证轻量校验
        if not credential_provider.validate(ca.region):
            logger.warning("CodeArts 凭证校验失败: region=%s（跳过装配）", ca.region)
            return
        event_store = _build_event_store(settings)
        handle_registry = HandleRegistry(event_store, max_concurrent=ca.max_concurrent)
        risk_classifier = PatternRiskClassifier(registry.safety)
        audit_logger = AuditLogger(settings.audit_dir)
        state_synchronizer = PollingSynchronizer(
            client, credential_provider, handle_registry, event_store, ca
        )
        result_collector = ResultCollector(
            client,
            event_store,
            result_max_bytes=ca.result_max_bytes,
            max_retries=ca.max_retries,
        )
        # 审批回调：CLI 交互模式注入 notify.confirm；Web/飞书/测试不注入 → fail-closed
        approval_callback = _build_codearts_approval_callback(settings)
        scheduler = CodeArtsScheduler(
            config=ca,
            credential_provider=credential_provider,
            client=client,
            handle_registry=handle_registry,
            state_synchronizer=state_synchronizer,
            result_collector=result_collector,
            risk_classifier=risk_classifier,
            audit_logger=audit_logger,
            event_store=event_store,
            safety_guard=registry.safety,
            approval_callback=approval_callback,
        )
        registry.register(CodeArtsDispatchTool(scheduler))
        registry.register(CodeArtsStatusTool(scheduler))
        registry.register(CodeArtsCancelTool(scheduler))
        registry.register(CodeArtsCapabilityTool(scheduler))
        # 进程重启接管在途委派（spec §4.2.2，接管时延上限 60s）
        recovered = scheduler.recover_in_flight()
        if recovered > 0:
            logger.info("CodeArts 集成已装配，接管 %d 个在途委派", recovered)
        else:
            logger.info("CodeArts 集成已装配（4 工具已注册）")
        # 挂载到 engine 供自省/热加载
        engine.codearts_scheduler = scheduler  # type: ignore[attr-defined]
        # 注入 workflow_run 工具以支持 executor="codearts" 步骤
        if workflow_tool is not None:
            workflow_tool._codearts_scheduler = scheduler  # noqa: SLF001
    except CredentialError as exc:
        logger.warning("CodeArts 凭证校验失败: %s（跳过装配）", exc)
    except Exception as exc:  # noqa: BLE001 — 装配失败不阻断启动
        logger.warning("CodeArts 集成装配失败（fail-open）: %s", exc, exc_info=True)


def _build_codearts_approval_callback(settings: Settings) -> Any:
    """构造 CodeArts 高风险动作审批回调.

    CLI 交互模式 → 注入 notify.confirm 回调（osascript 授权弹窗）。
    Web/飞书/测试模式 → 返回 None（fail-closed，灾难性动作默认拒绝）。
    """
    # 仅 CLI 模式注入回调（RUN_MODE != standard 时也可注入，但 Web/飞书不注入）
    # 判定依据：是否有交互终端 + 非 Web/飞书进程
    import sys

    if not sys.stdin.isatty():
        return None  # 无人值守模式 fail-closed
    try:
        from llm_loop.notify import confirm

        def _approval(action_desc: str, risk_reason: str) -> bool:
            message = f"CodeArts 高风险动作审批:\n动作: {action_desc[:200]}\n风险: {risk_reason[:200]}\n是否放行?"
            return confirm("CodeArts 审批", message)

        return _approval
    except ImportError:
        return None


def _build_event_store(settings: Settings) -> Any:
    """装配 D1 事件日志存储（EventStore，单一真相源）.

    默认开启（EVENT_LOG_ENABLED=1）；关闭时事件写入零行为零回归。
    会话存储与 engine 共享同一实例，保证事件 seq 续号一致。

    P1-1(2026-08-15，审计发现 #9)：接线 RotateManager——append 在同一把会话锁内
    自动检查大小/天数触发滚动（此前仅 CLI event-rotate-status 读段清单，生产
    永不滚动）。rotate_on_session_end 保留为 RotateManager 能力（当前无"会话
    结束"信号源，引擎在 run 末做检查钩子，不做强制滚动——如实标注）。
    """
    from llm_loop.event_log.rotate import RotateManager
    from llm_loop.event_log.store import EventStore

    store = EventStore(settings.event_logs_dir, enabled=settings.event_log_enabled)
    if settings.event_log_enabled:
        store.set_rotate_manager(
            RotateManager(
                store,
                rotate_bytes=settings.event_log_rotate_bytes,
                rotate_days=settings.event_log_rotate_days,
                rotate_on_session_end=settings.event_log_rotate_on_session_end,
            )
        )
    return store


def _build_fault_classifier() -> Any:
    """装配故障可自愈性分类器（M12 T49 / design 5.1，FR-AUTO-SELFHEAL-02）.

    M22 config 审计补齐: 生产路径此前未装配（loop 构造参数恒 None → 故障反馈降级），
    与 tests/conftest.py 测试路径一致装配，故障反馈含分类建议（M18 AA12 保留语义）。
    """

    from llm_loop.feedback.fault_classifier import FaultClassifier

    return FaultClassifier()


def _build_selfheal_budget(settings) -> Any:
    """装配自愈尝试预算（M12 T49 / design 5.1，FR-AUTO-SELFHEAL-03）.

    预算上限读 config: selfheal_max_attempts（SELFHEAL_MAX_ATTEMPTS）/ selfheal_max_per_round
    （SELFHEAL_MAX_PER_ROUND，tasks.md:852 权威命名）。生产路径补齐装配（与 conftest 一致）。
    """
    from llm_loop.feedback.selfheal_budget import SelfHealBudget

    return SelfHealBudget(
        max_attempts=getattr(settings, "selfheal_max_attempts", 3),
        max_per_round=getattr(settings, "selfheal_max_per_round", 6),
    )


def _build_memory_stats_fn(memory) -> Any:
    """构造 memory_stats_fn 闭包（M18 AA10: 记忆统计真实数据，fail-open）.

    memory 为 MemoryStore（count/all 接口）；闭包内 try/except：异常 → 如实标注"读取失败"，
    不抛穿 architecture_status（DFX-REL-09）。
    """

    def _memory_stats() -> dict:
        try:
            entries = memory.all()
            stats = {
                "entries": memory.count(),
                "recent": [
                    {"content": str(e.content)[:80], "type": getattr(e, "entry_type", "")}
                    for e in entries[-3:]
                ],
            }
            # EVO-20260816-fcdbe2e9: 升格判据量化事实源（实际注入次数降序，无注入记录→空列表如实）
            try:
                stats["top_injected"] = memory.top_injected(limit=5)
            except AttributeError:
                stats["top_injected"] = []  # 旧 store 无该方法 → 如实空列表（不伪造）
            return stats
        except Exception as exc:  # noqa: BLE001 — 读取失败如实标注（fail-open）
            return {"note": f"读取失败: {type(exc).__name__}: {exc}", "entries_hint": None}

    return _memory_stats


def _build_config_status_with_evolution(settings, model_registry_resolved: bool) -> Any:
    """构造 config_status 闭包: to_status_dict + evolution_summary（M17 FR-REVIEW-AI-05）.

    演进状态摘要（executing/pending_review 计数 + recent 摘要）为信息提供（非约束）；
    store.list() 异常 → evolution_summary.error 如实标注（fail-open，DFX-REL-08），不抛穿。
    P1-4（审计 #13）: model_registry_resolved 由 build_engine 装配期 resolve 结果注入
    （不在闭包内重算, 避免与装配期结果不一致）——resolve 失败时 AI 可经 architecture_status
    感知"配置模型未生效", 成功时为 true（如实标注, 不伪造）.
    """
    from llm_loop.introspection.evolution import EvolutionStore

    def _config_status() -> dict:
        base = settings.to_status_dict()
        # P1-4: 模型注册表 resolve 结果如实标注（AI 可经 architecture_status 自查）
        base["model_registry_resolved"] = model_registry_resolved
        try:
            store = EvolutionStore(settings.audit_dir)
            items = store.list()
            counts = {"total": 0, "pending_review": 0, "accepted": 0, "executing": 0, "executed": 0}
            for it in items:
                counts["total"] += 1
                st = it.get("status", "")
                if st in counts:
                    counts[st] += 1
            base["evolution_summary"] = {
                "total": counts["total"],
                "pending_review": counts["pending_review"],
                "accepted": counts["accepted"],
                "executing": counts["executing"],
                "executed": counts["executed"],
                "recent": [
                    {
                        "id": it.get("id", ""),
                        "status": it.get("status", ""),
                        "content": str(it.get("content", ""))[:80],
                    }
                    for it in items[-3:]
                ],
            }
        except Exception as exc:  # noqa: BLE001 — 读取失败如实标注不抛穿（fail-open）
            base["evolution_summary"] = {
                "error": f"读取失败: {type(exc).__name__}: {exc}",
                "note": "演进状态摘要不可用，请改用 search_records(kind=evolution) 查询。",
            }
        return base

    return _config_status


def _build_pending_actions_fn(settings) -> Any:
    """构造待办聚合闭包（T4: 纯聚合无判断，spec.md 5.3.1 / design.md §2.4.3）.

    聚合 evolution_summary（executing/pending_review 计数）为 pending_actions 维度；
    只计数 + 拼接 hint，不做决策；读取失败 fail-open 计数字段 null + note 标注。
    """
    from llm_loop.introspection.evolution import EvolutionStore

    def _aggregate() -> dict:
        try:
            from llm_loop.core.run_context import current_session_id as _current_session_id

            store = EvolutionStore(settings.audit_dir)
            items = store.list()
            _sid = str(_current_session_id.get() or "")
            # Capability-bearing executing hints are session-owned facts.  Human
            # pending-review count may remain global because it does not grant a model tool.
            executing = sum(
                1
                for it in items
                if it.get("status") == "executing"
                and _sid
                and str(it.get("session_id", "") or "") == _sid
            )
            pending_review = sum(1 for it in items if it.get("status") == "pending_review")
        except Exception as exc:  # noqa: BLE001 — 聚合失败如实标注（fail-open）
            return {
                "executing_evolutions": None,
                "pending_reviews": None,
                "pending_self_evals": None,
                "hint": None,
                "capability_requirements": (),
                "note": f"演进待办聚合失败: {type(exc).__name__}: {exc}",
            }
        hint_parts: list[str] = []
        if executing:
            hint_parts.append(f"{executing} 项演进执行中（可经 evolution_complete 登记）")
        if pending_review:
            hint_parts.append(f"{pending_review} 项演进待审阅")
        return {
            "executing_evolutions": executing,
            "pending_reviews": pending_review,
            "pending_self_evals": 0,
            "hint": "；".join(hint_parts) if hint_parts else None,
            # R2 P0-1: hint 文案与结构化字段同一函数产出（§5.7.1-2a；executing>0 → evolution_complete）
            "capability_requirements": ("evolution_complete",) if executing else (),
            "note": None,
        }

    return _aggregate


def _build_loop_signal_detector() -> Any:
    """Build the opt-in operator pending-review helper; ordinary runs do not scan it."""
    from llm_loop.introspection.loop_signals import LoopSignalDetector

    return LoopSignalDetector()


def _make_tool_call(name: str, arguments: dict):
    import time

    from llm_loop.core.message import ToolCall

    # M18 AA14: time_ns 唯一后缀（协议 C3: tool_call_id 不得重复；参考 M16 eval_id 唯一性修复）
    return ToolCall(id=f"retry-{name}-{time.time_ns()}", name=name, arguments=arguments or {})


def _sum_archive_stats(archive: Any) -> dict:
    """汇总全部会话压缩档案统计（供 architecture_status context_usage）."""
    total_count = 0
    total_chars = 0
    try:
        for sid in archive.session_ids():
            stats = archive.stats(sid)
            total_count += stats["archived_count"]
            total_chars += stats["archived_chars"]
    except Exception:
        return {"archived_count": total_count, "archived_chars": total_chars}
    return {"archived_count": total_count, "archived_chars": total_chars}

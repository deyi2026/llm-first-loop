"""组件装配工厂（供 CLI 与测试复用）.

将 Settings + LLMClient + ToolRegistry(基础工具+自省/修正/检索工具) +
MemoryStore + ArchiveStore + SessionStore + ArchitectureStatusProvider +
DeclarationValidator + RecordSearcher 装配为 LoopEngine。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from llm_loop.config import Settings
from llm_loop.core.loop import LoopEngine
from llm_loop.core.message import ToolResult
from llm_loop.core.session import SessionStore
from llm_loop.feedback.validator import DeclarationValidator
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.docs_search import DocsSearcher
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.status import ArchitectureStatusProvider
from llm_loop.llm.client import LLMClient
from llm_loop.memory.archive import ArchiveStore
from llm_loop.memory.store import MemoryStore
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.builtin.dsh_session_read import DshSessionReadTool
from llm_loop.tools.builtin.dsh_task import DshTaskTool
from llm_loop.tools.builtin.edit_file import EditFileTool
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.builtin.job_kill import JobKillTool
from llm_loop.tools.builtin.job_output import JobOutputTool
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool
from llm_loop.tools.builtin.web_fetch import WebFetchTool
from llm_loop.tools.builtin.web_search import WebSearchTool
from llm_loop.tools.builtin.workflow import WorkflowRunTool
from llm_loop.tools.registry import ToolRegistry

# EVO-20260814 P1-A: RUN_MODE 运行模式（对齐 Harness 四种运行模式）
# standard: 全工具集（默认零回归）; ptc: 命令执行为主路径（web 外围降级）;
# minimal: 精简工具集（只读+必要执行）; creative: 宽松默认参数（超时/输出/检索放大）
_RUN_MODE_HIDDEN_TOOLS: dict[str, set[str]] = {
    # minimal: 外围/重工具禁用（web 检索、飞书出站、playwright、record_skill 等）
    "minimal": {
        "web_fetch", "web_search",
        "send_feishu_message", "create_feishu_doc", "send_feishu_attachment",
        "playwright_test", "playwright_exec", "record_skill",
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
    settings.ensure_dirs()

    # M47（design §5.1/§5.5）: 从注册表查思考支持（消除 _thinking_supported() 硬编码 deepseek.com）.
    # 当前模型不在注册表（如显式使用未注册的模型）→ 保持 LLMClient 默认（向后兼容）.
    # M48（design §5.3）: 注册表同时为 ModelClientPool 提供服务（路由/缓存/思考查询）。
    # P1-4（审计 #13）: resolve 失败不再静默吞掉——warning 如实告警（含用户配置的模型名与
    # 失败原因）+ config_status 暴露 model_registry_resolved=false, 让 AI 经
    # architecture_status 感知"模型配置未生效"（程序故障对 AI 可见原则）.
    thinking_supported: bool | None = None
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
        thinking_supported = registry.supports_thinking(provider_id, model_id)
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

    # LLM 客户端（全限定默认模型走注册表参数, 否则 env 三件套）
    llm = LLMClient(
        api_key=(llm_params or {}).get("api_key", settings.llm_api_key),
        base_url=(llm_params or {}).get("base_url", settings.llm_base_url),
        model=(llm_params or {}).get("model", settings.llm_model),
        timeout_s=settings.llm_timeout_s,
        max_tokens=settings.llm_max_tokens,  # 2026-08-15 显式输出预算
        wire_protocol=settings.llm_wire_protocol,  # P3-5 协议分发
        # M20 THK-01: 思考参数装配一次，三条 LLM 路径统一受益（VAL-02）
        thinking_mode=settings.thinking_mode,
        reasoning_effort=settings.reasoning_effort,
        # M47 §5.5: 元数据驱动的思考支持判定（None 时退回硬编码，向后兼容）
        thinking_supported=thinking_supported,
    )

    # M48（design §5.3）: 模型客户端路由池（会话级 model_override 路由 + provider 级缓存）
    # 未配置 MODEL_PROVIDERS（仅 L0 单 provider 合成）→ 池仅有默认 client，行为与现状一致
    # M49（design §5.4）: 注入 MODEL_FALLBACKS 原始字符串，池在 fallback_candidates() 中按需解析
    from llm_loop.llm.pool import ModelClientPool

    model_pool = ModelClientPool(
        registry=registry,
        default_client=llm,
        model_fallbacks_raw=settings.model_fallbacks_raw,
    )

    # 存储（记忆 + 压缩档案 + 会话）
    memory = MemoryStore(settings.memory_dir)
    archive = (
        ArchiveStore(settings.archive_dir, segment_bytes=settings.archive_segment_bytes)
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
    session_store = SessionStore(
        settings.sessions_dir,
        event_store=_build_event_store(settings),
        read_path_source=getattr(settings, "read_path_source", "session_json"),
    )

    # 工具注册表（3 基础工具 + 自省/修正/检索工具）
    registry = ToolRegistry(
        tool_timeout_s=settings.tool_timeout_s,
        max_output_chars=settings.tool_max_output_chars,
        summary_threshold=settings.tool_summary_threshold,
        archive_store=archive,  # T22: 超长工具结果另存
        exec_mode=settings.exec_mode,  # EVO-20260810-2549e9b6: EXEC_MODE 命令分级
        exec_allowlist=settings.exec_allowlist,
        memory_store=memory,  # EVO-d78b270c: 经验驱动注入（M41 升级，失败回执检索经验库）
        approval_audit_path=settings.audit_dir / "approval_audit.jsonl",  # T5a: 审批审计落盘
        safety_audit_dir=settings.audit_dir,  # P0-1: 灾难性阻断审计 safety_blocks.jsonl
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

    _register_basic("read_file", ReadFileTool())
    # M51: 四段式文件修改（read→match→diff→apply+verify，替代 sed/heredoc 盲替换）
    _register_basic("edit_file", EditFileTool())
    # EVO-d5db88d9: 按需读取工具完整 Schema（懒加载配套；零副作用可始终注册）
    from llm_loop.tools.registry import GetToolSchemaTool

    registry.register(GetToolSchemaTool(registry))
    # M18 AA8: 工具内兜底超时读配置值（注册表另有线程级超时兜底）
    _register_basic("execute_command", ExecuteCommandTool(timeout_s=_tool_timeout))
    # EVO-20260814: 后台任务查询/终止（配合 execute_command run_in_background=true）
    _register_basic("job_output", JobOutputTool())
    _register_basic("job_kill", JobKillTool())
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

        if call.name in ("execute_command", "write_file", "edit_file", "delete_file", "append_file"):
            record_change_log(call.name, f"arguments={str(call.arguments)[:200]}", session_id=registry._session_id)

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
    )
    # M56 B5（ANALYSIS-20260811）: 当前模型窗口注入 architecture_status（AI 可查后
    # 自主决策上下文压缩；resolve 失败/未知模型如实返回 label+context=None，不伪造）
    def _model_window_snapshot() -> dict:
        try:
            pid, mid = model_pool.registry.resolve(settings.llm_model)
            spec = model_pool.registry.providers[pid].models.get(mid)
            return {"label": f"{pid}/{mid}", "context": spec.context if spec else None}
        except Exception:  # noqa: BLE001 — 窗口查询失败如实降级
            return {"label": settings.llm_model, "context": None}

    status_provider.set_model_context_fn(_model_window_snapshot)

    # 修正/检索工具注册表（M12 T50: RuntimeParams 与 ctx.strategy 共享 dict 引用）
    from llm_loop.core.runtime_params import RuntimeParams

    correction_ctx = CorrectionContext()
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
    )
    # M48（design §5.3）: 模型路由池注入；session_set_override 回调在 run() 内动态绑定，
    # 此处先注入 pool 让 tool_defs() 完整（让 LLM 在工具列表中看到 model_catalog/switch_model）
    correction_ctx.model_pool = model_pool

    # T23: 统一检索实现注入（search_records）+ T31 语义路径
    # P1-2: 经验库装配（fail-open，目录不存在时检索如实返回未命中）
    from llm_loop.experiences.store import ExperienceStore

    experience_store = ExperienceStore(settings.experiences_dir, embedder=embedder)  # T5: 注入 embedder 供语义检索
    searcher = RecordSearcher(
        audit_dir=settings.audit_dir,
        memory_store=memory,
        archive_store=archive,
        experience_store=experience_store,  # P1-2: 经验库检索接入
        semantic_retriever=semantic_retriever,  # T31: 语义召回
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

    corrections._search_records_fn = _RecordSearcherAdapter(searcher)  # noqa: SLF001
    corrections._experience_store = experience_store  # noqa: SLF001 — P1-2: 工具分派注入

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
        logger.warning("docs/ 检索装配失败（fail-open），search_docs 将回执'检索不可用'", exc_info=True)

    # P2-2: fail-open 数据丢失恢复通道装配
    from llm_loop.recovery.backup import BackupStore
    from llm_loop.recovery.channel import RecoveryChannel

    backup_store = BackupStore(settings.recovery_dir)

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
    corrections._recovery_sessions_dir = settings.sessions_dir  # noqa: SLF001
    corrections._recovery_memory_dir = settings.memory_dir  # noqa: SLF001
    corrections._skills_dir = settings.skills_dir or None  # noqa: SLF001 — B3: 插件化 Skill 目录注入
    status_provider.set_recovery_status_fn(backup_store.status_summary)

    # 自省/修正/检索工具注册进 ToolRegistry（LLM 可见）
    # EVO-20260814 P1-A: RUN_MODE=minimal 时过滤外围工具（飞书出站/playwright/record_skill）
    _corr_hidden = _run_mode_hidden(_run_mode)
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
        eval_trigger_detector=_build_eval_trigger_detector(settings),
        evolution_store=correction_ctx.evolution_store,  # M17 FR-REVIEW-AI-02: executing 提醒数据源
        loop_signal_detector=_build_loop_signal_detector(settings, status_provider, corrections),
        llm_pool=model_pool,  # M48（design §5.3）: 会话级模型路由
        recovery=recovery_channel,  # P2-2: fail-open 写失败恢复通道
        event_store=_build_event_store(settings),  # D1: 事件源化（共享同一实例）
    )

    # M50（design §5.6）: 注入增强版 refresh_config executor — 重读 providers.json
    install_refresh_executor(engine)

    # 工作区管理（对齐 DSH Workspace）：注册表 + 旧会话迁移 + 引擎挂载当前工作区。
    # 默认工作区 = 启动 cwd（当前行为一致：工具/会话根=项目根，零回归）。
    from llm_loop.workspace.store import WorkspaceStore

    workspace_store = WorkspaceStore(settings.data_dir)
    default_ws = workspace_store.register(os.getcwd())  # 幂等注册
    try:
        workspace_store.migrate_legacy_sessions(settings.data_dir, default_ws)
    except Exception:  # noqa: BLE001 — 迁移失败不影响启动（旧会话仍在原目录可读）
        logger.warning("工作区旧会话迁移失败（fail-open），旧会话留在原目录", exc_info=True)
    # 首次装配（注册表无 current）→ 默认工作区设为 current 并持久化
    if workspace_store.get_current() is None:
        workspace_store.switch(default_ws.id)
    current_ws = workspace_store.get_current() or default_ws
    engine.set_workspace(current_ws.path)
    engine.workspace_store = workspace_store  # web 层切换工作区入口

    # R1: 上下文占用分解注入 architecture_status（AI 每轮可见，自主决策压缩/切换）
    status_provider.set_context_breakdown_fn(lambda: getattr(engine, "_last_breakdown", None))
    # T3: 上下文占用率注入 runtime（memory_top_k 自适应消费；breakdown 不可用时走默认值零回归）
    def _context_usage_ratio() -> float:
        bd = getattr(engine, "_last_breakdown", None)
        if bd is None:
            return 0.0
        total = getattr(bd, "total_chars", 0) or 0
        cap = getattr(bd, "max_chars", 0) or 0
        return total / cap if cap > 0 else 0.0
    runtime.set_context_usage_fn(_context_usage_ratio)
    # T4（spec.md 5.3.1）: 待办聚合注入 architecture_status（AI 一站式感知系统待办）
    status_provider.set_pending_actions_fn(_build_pending_actions_fn(settings))

    # EVO 第五项: 递归子代理（参考 OpenRSI 四算子 + 执行反馈）— 独立会话隔离 + 受限工具 + 深度/预算边界
    subagent_runner = SubAgentRunner(
        llm=llm,
        registry=registry,
        session_store=session_store,
    )
    registry.register(SpawnSubAgentTool(subagent_runner))
    # EVO-20260814 P1-B: 工作流编排（parallel 聚合 / pipeline 串联，对齐 Harness 多 Agent 编排）
    workflow_tool = WorkflowRunTool(subagent_runner)
    registry.register(workflow_tool)
    # DSH-ORCHESTRATION（2026-08-16）: 调度 DeepSeek Harness headless 执行任务（进程级子代理）
    registry.register(DshTaskTool())
    registry.register(DshSessionReadTool())

    # CodeArts 子 Agent 调度集成（design.md §2.1.2，缺省 fail-open 零装配）
    # CODEARTS_ENABLED=false 或凭证缺失/校验失败 → 跳过装配 + 日志标注，主运行时零回归
    _assemble_codearts(settings, registry, session_store, engine, workflow_tool)

    return engine


def _assemble_codearts(settings: Settings, registry: ToolRegistry, session_store: Any, engine: Any, workflow_tool: Any = None) -> None:
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
            client, event_store,
            result_max_bytes=ca.result_max_bytes, max_retries=ca.max_retries,
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
            store = EvolutionStore(settings.audit_dir)
            items = store.list()
            executing = sum(1 for it in items if it.get("status") == "executing")
            pending_review = sum(1 for it in items if it.get("status") == "pending_review")
        except Exception as exc:  # noqa: BLE001 — 聚合失败如实标注（fail-open）
            return {
                "executing_evolutions": None,
                "pending_reviews": None,
                "pending_self_evals": None,
                "hint": None,
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
            "note": None,
        }

    return _aggregate


def _build_loop_signal_detector(settings, status_provider, corrections) -> Any:
    """装配每轮末信号检测统一壳（M17 FR-REVIEW-AI-02/03; M18 AA1 收敛）.

    M18 审计（FR-AUDIT3-AI-01）: 参数信号检测已移除并移交 RULE-AI-02；本壳仅
    eval_trigger/executing（executing 经 evolution_store 由 LoopEngine 薄壳调用）。
    """
    from llm_loop.introspection.loop_signals import LoopSignalDetector

    return LoopSignalDetector(
        eval_trigger_detector=_build_eval_trigger_detector(settings),
        status=status_provider,
        settings=settings,
    )


def _build_eval_trigger_detector(settings) -> Any:
    """装配自我评估触发检测器（T65，SELF_EVAL_ENABLED=0 时返回 None）."""
    if not getattr(settings, "self_eval_enabled", True):
        return None
    from llm_loop.introspection.evaluator import EvalTriggerDetector

    return EvalTriggerDetector(
        interval_rounds=getattr(settings, "self_eval_interval_rounds", 50),
    )


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
        for p in archive._dir.glob("*.jsonl"):  # noqa: SLF001
            s = archive.stats(p.stem)
            total_count += s["archived_count"]
            total_chars += s["archived_chars"]
    except Exception:
        return {"archived_count": total_count, "archived_chars": total_chars}
    return {"archived_count": total_count, "archived_chars": total_chars}

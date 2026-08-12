"""组件装配工厂（供 CLI 与测试复用）.

将 Settings + LLMClient + ToolRegistry(基础工具+自省/修正/检索工具) +
MemoryStore + ArchiveStore + SessionStore + ArchitectureStatusProvider +
DeclarationValidator + RecordSearcher 装配为 LoopEngine。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from llm_loop.config import Settings
from llm_loop.core.loop import LoopEngine
from llm_loop.core.message import ToolResult
from llm_loop.core.session import SessionStore
from llm_loop.feedback.validator import DeclarationValidator
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.status import ArchitectureStatusProvider
from llm_loop.llm.client import LLMClient
from llm_loop.memory.archive import ArchiveStore
from llm_loop.memory.store import MemoryStore
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.builtin.edit_file import EditFileTool
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool
from llm_loop.tools.builtin.web_fetch import WebFetchTool
from llm_loop.tools.builtin.web_search import WebSearchTool
from llm_loop.tools.registry import ToolRegistry

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


def build_engine(settings: Settings) -> LoopEngine:
    """装配全部组件并返回 LoopEngine."""
    settings.ensure_dirs()

    # M47（design §5.1/§5.5）: 从注册表查思考支持（消除 _thinking_supported() 硬编码 deepseek.com）.
    # 当前模型不在注册表（如显式使用未注册的模型）→ 保持 LLMClient 默认（向后兼容）.
    # M48（design §5.3）: 注册表同时为 ModelClientPool 提供服务（路由/缓存/思考查询）。
    thinking_supported: bool | None = None
    try:
        from llm_loop.llm.providers import load_registry

        registry = load_registry(settings)
        provider_id, model_id = registry.resolve(settings.llm_model)
        thinking_supported = registry.supports_thinking(provider_id, model_id)
    except ValueError:
        # 当前模型不在注册表 → 保持 LLMClient 默认（向后兼容 _thinking_supported）
        pass

    # LLM 客户端
    llm = LLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_s=settings.llm_timeout_s,
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
    archive = ArchiveStore(settings.archive_dir) if settings.archive_enabled else None
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
    session_store = SessionStore(settings.sessions_dir)

    # 工具注册表（3 基础工具 + 自省/修正/检索工具）
    registry = ToolRegistry(
        tool_timeout_s=settings.tool_timeout_s,
        max_output_chars=settings.tool_max_output_chars,
        summary_threshold=settings.tool_summary_threshold,
        archive_store=archive,  # T22: 超长工具结果另存
        exec_mode=settings.exec_mode,  # EVO-20260810-2549e9b6: EXEC_MODE 命令分级
        exec_allowlist=settings.exec_allowlist,
    )
    registry.register(ReadFileTool())
    # M51: 四段式文件修改（read→match→diff→apply+verify，替代 sed/heredoc 盲替换）
    registry.register(EditFileTool())
    # EVO-d5db88d9: 按需读取工具完整 Schema（懒加载配套；零副作用可始终注册）
    from llm_loop.tools.registry import GetToolSchemaTool

    registry.register(GetToolSchemaTool(registry))
    # M18 AA8: 工具内兜底超时读配置值（注册表另有线程级超时兜底）
    registry.register(ExecuteCommandTool(timeout_s=settings.tool_timeout_s))
    registry.register(WebFetchTool(timeout_s=settings.tool_timeout_s))
    registry.register(WebSearchTool(timeout_s=settings.tool_timeout_s))  # M48: 网络搜索（Bing/百度双后端降级）

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
        config_status=_build_config_status_with_evolution(settings),
        archive_stats_fn=(
            (lambda: {"archived_total": 0})
            if archive is None
            else lambda: _sum_archive_stats(archive)
        ),
        memory_stats_fn=_build_memory_stats_fn(memory),
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
    searcher = RecordSearcher(
        audit_dir=settings.audit_dir,
        memory_store=memory,
        archive_store=archive,
        semantic_retriever=semantic_retriever,  # T31: 语义召回
    )
    corrections._search_records_fn = lambda **kw: searcher.search(**kw)  # noqa: SLF001

    # 自省/修正/检索工具注册进 ToolRegistry（LLM 可见）
    for td in corrections.tool_defs():
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
    )

    # M50（design §5.6）: 注入增强版 refresh_config executor — 重读 providers.json
    install_refresh_executor(engine)
    # R1: 上下文占用分解注入 architecture_status（AI 每轮可见，自主决策压缩/切换）
    status_provider.set_context_breakdown_fn(lambda: getattr(engine, "_last_breakdown", None))

    # EVO 第五项: 递归子代理（参考 OpenRSI 四算子 + 执行反馈）— 独立会话隔离 + 受限工具 + 深度/预算边界
    subagent_runner = SubAgentRunner(
        llm=llm,
        registry=registry,
        session_store=session_store,
    )
    registry.register(SpawnSubAgentTool(subagent_runner))
    return engine


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
            return {
                "entries": memory.count(),
                "recent": [
                    {"content": str(e.content)[:80], "type": getattr(e, "entry_type", "")}
                    for e in entries[-3:]
                ],
            }
        except Exception as exc:  # noqa: BLE001 — 读取失败如实标注（fail-open）
            return {"note": f"读取失败: {type(exc).__name__}: {exc}", "entries_hint": None}

    return _memory_stats


def _build_config_status_with_evolution(settings) -> Any:
    """构造 config_status 闭包: to_status_dict + evolution_summary（M17 FR-REVIEW-AI-05）.

    演进状态摘要（executing/pending_review 计数 + recent 摘要）为信息提供（非约束）；
    store.list() 异常 → evolution_summary.error 如实标注（fail-open，DFX-REL-08），不抛穿。
    """
    from llm_loop.introspection.evolution import EvolutionStore

    def _config_status() -> dict:
        base = settings.to_status_dict()
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

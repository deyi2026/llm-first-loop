"""五阶段核心循环 LoopEngine（design.md §2.1.3.1 / FR-LOOP 系列）.

架构主轴: 消息进 → 理解 → 行动 → 真诚回答 → 记住。

- 工具反馈子循环: 工具消息作为独立消息再入理解（FR-LOOP-04）
- 严格 function calling: tool_call_id 由程序统一管理（约束 C1-C6）
- 声明-回执校验（FR-FBK-01，不一致如实反馈，最多更正 1 次）
- 停滞检测 + 轮数上限（如实结束）
- 架构自省: 阶段/动作轨迹/工具历史/异常采集 + [架构上报] 推送（AI-serving）
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, cast

from llm_loop.config import Settings
from llm_loop.core.history import (  # noqa: F401 (history 工具)
    projection_check,
    projection_ver,
    stable_digest,
)
from llm_loop.core.injection_labels import (
    InjectionLayer,
    origin_metadata,
)
from llm_loop.core.loop.build import _BuildMixin  # EVO-20260817-e63f712f: 消息构建拆分

# M53 拆分: 职责 mixin（signals 信号检查 / runtime 运行时参数 / fallback 模型降级链 / routing 模型路由 / overflow overflow 处理 / tool_exec 工具执行）
from llm_loop.core.loop.engine_services.archive import ArchiveService
from llm_loop.core.loop.engine_services.attempt_executor import AttemptExecutor
from llm_loop.core.loop.engine_services.fallback import FallbackService
from llm_loop.core.loop.engine_services.interop import InteropService
from llm_loop.core.loop.engine_services.interrupted_capture import InterruptedCapture
from llm_loop.core.loop.engine_services.recovery_controller import RecoveryController
from llm_loop.core.loop.engine_services.routing import (
    _CHARS_PER_TOKEN_EST,  # noqa: F401 — M53 拆分 re-export（原路径可导入，REQ-REF-06）
    _CONTEXT_SAFETY_MARGIN,  # noqa: F401 — M53 拆分 re-export（原路径可导入，REQ-REF-06）
    RoutingService,
)
from llm_loop.core.loop.engine_services.run_finalizer import RunFinalizer
from llm_loop.core.loop.engine_services.run_state import RunStateManager
from llm_loop.core.loop.engine_services.runtime_params import RuntimeParamsService
from llm_loop.core.loop.engine_services.session_lifecycle import SessionLifecycle
from llm_loop.core.loop.engine_services.termination_controller import TerminationController
from llm_loop.core.loop.engine_services.tool_cycle import ToolCycleService
from llm_loop.core.loop.events import _EventsMixin
from llm_loop.core.loop.kpi import _KpiMixin
from llm_loop.core.loop.lifecycle import _RunEntrypointMixin
from llm_loop.core.loop.runstate import _RunState
from llm_loop.core.loop.tool_exec import (
    _json_dumps_args,
    _tool_args_summary,  # noqa: F401 — M53 拆分 re-export（原路径可导入，REQ-REF-06）
)
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.prompt_eligibility import LEGACY_PROGRAM_FINAL_MARKER
from llm_loop.core.run_context import (
    current_reasoning_effort as _current_reasoning_effort,
)
from llm_loop.core.run_context import (
    current_reasoning_mode as _current_reasoning_mode,
)
from llm_loop.core.session import SessionStore
from llm_loop.core.trace_leak import leak_events
from llm_loop.core.trace_leak.invariant import (
    correct_mislabeled_metadata,
    metadata_satisfies_invariant,
)
from llm_loop.feedback.honesty import max_iterations_feedback
from llm_loop.feedback.validator import DeclarationValidator, build_discrepancy_feedback
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.status import ArchitectureStatusProvider
from llm_loop.llm.client import GuardRequestContext, LLMClient, StreamDelta
from llm_loop.llm.errors import LLMError
from llm_loop.llm.pool import ModelClientPool
from llm_loop.memory.store import MemoryStore
from llm_loop.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_CANCELLED_ANSWER = "（已停止——用户点击停止按钮，本轮回答终止）"


def _background_cancelled(engine: Any, session_id: str) -> bool:
    runner = getattr(engine, "runner", None)
    return bool(runner is not None and runner.enabled and runner.is_cancelled(session_id))


def _background_cancel_reason(engine: Any, session_id: str) -> str:
    """该会话取消原因（""=未取消；与 _background_cancelled 同构，双路径：registry 命中
    读 handle.cancel_reason，未命中读同步登记值）——检查点原因捕获与伴生异常归因
    拦截的判定依据（标记位查询，禁止匹配错误文本）."""
    runner = getattr(engine, "runner", None)
    if runner is None or not runner.enabled:
        return ""
    fn = getattr(runner, "cancel_reason", None)
    return str(fn(session_id) or "") if callable(fn) else ""


def _background_note_active(engine: Any, session_id: str, round_no: int) -> None:
    """任务12（§5.12）: 每轮刷新后台 run 活跃时间（残留 run 巡检数据源）."""
    runner = getattr(engine, "runner", None)
    if runner is not None:
        try:
            runner.note_active(session_id, round_no)
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("runner.note_active 失败（忽略）", exc_info=True)


# M53 拆分: _json_dumps_args/_tool_args_summary → llm_loop/core/loop/tool_exec.py（_ToolExecMixin）
# 迁移注释保留（REQ-REF-06）: 原路径可导入（对齐 test_tool_round_visible.py），行为与迁移前一致。
# 模块级函数随工具执行职责单元迁移，经此 re-export 保持 `engine._tool_args_summary` 等可导入。


def format_tokens(n: int) -> str:
    """M52: token 计数人性化显示（1234 → "1.2k"）；0 = 未提供，如实返回 "0"."""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


# M53: 上下文守卫估算常量 → engine_services/routing.py（W4-02b 起 RoutingService）
# 迁移注释保留（REQ-REF-06）: 原路径可导入（engine._CHARS_PER_TOKEN_EST/_CONTEXT_SAFETY_MARGIN），取值与迁移前一致。
# 估算口径（chars/token 保守估计, 中文混合内容约 2 字符/token；安全边距预留 10% 给响应生成）已随迁至 routing.py。


@dataclass
class LoopResult:
    """一次 run() 的完整结果（如实交付用户，design.md §2.2.2.3）."""

    session_id: str
    final_answer: str
    verification_note: str | None = None  # 声明-回执校验差异说明
    rounds: int = 0
    tool_calls: list[dict] = field(default_factory=list)  # 工具声明轨迹（审计）
    truncated: bool = False
    # M51: 实际生成本次回复的模型标签（provider/model 全限定，如实透传；降级后为降级模型 ref）
    model_used: str = ""
    # M52: 本次 run 的 token 用量（工具循环多次调用累加；provider 未返回 usage 时为 0，如实不伪造）
    tokens_in: int = 0
    tokens_out: int = 0
    # M58: 本次 run 前缀缓存命中 token（provider 返回 prompt_cache_hit_tokens/cached_tokens；未返回为 0）
    tokens_cache_hit: int = 0
    # P1-1: 最终回答轮完整思考链（供 Web done 事件透传前端渲染）；工具轮思考链不在此字段
    reasoning_content: str | None = None
    # reasoning 观测四层：配置意图 / 能力支持 / 实际产生 / provider 精确 token（若可得）
    reasoning_mode: str = "auto"
    reasoning_capable: bool = False
    reasoning_control: str = "unknown"
    # Backward-compatible name: this means explicit control is supported, not
    # generic reasoning capability.
    reasoning_supported: bool = False
    reasoning_effective: bool = False
    reasoning_tokens: int | None = None
    # 取消原因标记位（""=未取消；值域 user_stop/runner_stop，结构化可审计，spec 6.1.2）
    cancel_reason: str = ""
    # Emergency MODEL_FALLBACKS fact for the current user/UI only; never persisted as assistant prompt text.
    fallback_receipt: dict[str, str] | None = None


class LoopEngine(_BuildMixin, _EventsMixin, _KpiMixin, _RunEntrypointMixin):
    """五阶段核心循环控制器."""

    # EVO 后台 run 执行器（factory 动态装配 BackgroundRunner；声明类型供 pyright 静态检查）

    def _run_state(self) -> _RunState:
        """当前会话状态桶（B5-W4-03：解析逻辑在 RunStateManager.bucket，薄委托）."""
        return self._run_state_mgr.bucket()

    runner: Any | None = None
    # DSH-PLUGINS-20260816 ②: 调度提醒线程（factory 装配；声明类型供 pyright 静态检查）
    scheduler: Any | None = None
    # ERR1210 per-engine/session attempt ledger; actual lifecycle owned by RecoveryController.
    _err1210_attempted: dict[str, int]
    # ERC Phase6: optional workspace-activation legacy sidecar migration hook.
    _evidence_legacy_migrate_workspace_fn: Callable[[str], object] | None = None

    def __init__(
        self,
        llm_client: LLMClient,
        registry: ToolRegistry,
        memory: MemoryStore,
        session: SessionStore,
        settings: Settings,
        *,
        validator: DeclarationValidator | None = None,
        status_provider: ArchitectureStatusProvider | None = None,
        correction_registry: CorrectionToolRegistry | None = None,
        correction_ctx: CorrectionContext | None = None,
        archive: Any | None = None,
        summarizer: Any | None = None,  # T28: Summarizer（LLM 摘要，可 None 走确定性）
        extractor: Any | None = None,  # T33: MemoryExtractor（独立记忆提取）
        semantic_retriever: Any | None = None,  # M11 T45: 语义检索器（主循环记忆注入接线）
        fault_classifier: Any | None = None,  # M12 T49: 故障可自愈性分类器
        selfheal_budget: Any | None = None,  # M12 T49: 自愈尝试预算
        runtime: Any | None = None,  # M12 T50: RuntimeParams 动态参数视图
        loop_signal_detector: Any
        | None = None,  # M17 FR-REVIEW-AI-02/03: LoopSignalDetector 三合一
        llm_pool: ModelClientPool | None = None,  # M48（design §5.3）: 会话级模型路由
        recovery: Any | None = None,  # P2-2: RecoveryChannel（fail-open 写失败恢复通道）
        event_store: Any | None = None,  # D1: EventStore（事件源化，默认 None 零行为）
        episode_store: Any | None = None,  # R8.5: resolved episode durable index（None=零回归）
    ) -> None:
        self.llm = llm_client
        self.registry = registry
        self.memory = memory
        self.session = session
        self.settings = settings
        self.validator = validator
        self.status = status_provider
        self.correction_ctx = correction_ctx
        self.corrections = correction_registry
        # P0-5: 每会话 override 绑定解析器（一次性装配；registry_model 经 contextvar
        # 定位本会话 sess，并发 run 不互踩 switch_model 回调）
        if correction_ctx is not None:
            correction_ctx.session_binding_resolver = self._resolve_session_binding
        self.archive = archive  # ArchiveStore（T22 压缩档案，可 None 降级）
        self.summarizer = summarizer
        self.extractor = extractor
        self.semantic_retriever = semantic_retriever
        self.fault_classifier = fault_classifier
        self.selfheal_budget = selfheal_budget
        self.runtime = runtime
        self.loop_signal_detector = loop_signal_detector
        # M48（design §5.3）: 会话级模型路由池；None 时使用装配默认 client（零回归）
        self.llm_pool = llm_pool
        # P2-2: fail-open 写失败恢复通道；None 时三个 fail-open 点行为不变（零回归）
        self.recovery = recovery
        # D1: 事件源化 EventStore（默认 None 零行为；注入时消息/元数据/压缩事件落事件日志）
        self._event_store = event_store
        # INJECTION-GOVERNANCE R8.5: completed conversation episodes become
        # retrievable history before they may retire from provider working context.
        self.episode_store = episode_store
        # 工作区管理（对齐 DSH Workspace）：当前工作区根（空 = 进程 cwd 零回归）；
        # run 入口注入 contextvar 供工具相对路径/命令默认 cwd 跟随
        self.workspace_root: str = ""
        # 工作区注册表（factory 装配注入；web 层切换工作区入口）
        self.workspace_store: Any | None = None
        # 协调 inbox 监视器由 factory 可选装配；显式声明避免运行时 shape 依赖动态属性。
        self.inbox_watcher: Any | None = None
        # B5-W4-03: per-session 运行状态桶对象化（_RunStateMixin 退役）——
        # 桶生命周期/会话解析/一致性锁 authority 在 RunStateManager（自足服务）
        self._run_state_mgr = RunStateManager()
        # P0-5: 每会话 in-memory Session 绑定表（switch_model 等按 contextvar 解析
        # 本会话 sess，避免并发 run 互踩 override 回调；run finally 立即清理完整Session引用）
        self._run_sessions: dict[str, Any] = {}
        # EVO-20260817 审查 P0-3: 同步 run 活跃会话集合——双向互斥防双 run 竞写
        # 会话文件（后台 start 检查不到同步 run → last-write-wins 丢消息）。
        self._sync_active: set[str] = set()
        self._sync_guard = threading.Lock()
        self._workspace_transition_guard = threading.RLock()  # run admission / workspace切换同门
        self._workspace_epoch = 0
        # accepted-boundary callback不扩展public API，也不依赖ContextVar。
        self._run_acquired_callbacks: dict[str, Any] = {}
        self._run_acquired_callbacks_guard = threading.Lock()
        # R9 Phase 5 T6-A: 终止域 service（B5-W1-02 迁入 _SignalsMixin/_OverflowMixin 职责）
        self._termination = TerminationController(self)
        # R9 Phase 5 T6-A: 恢复域 service（B5-W1-03 迁入 _Err1210Mixin 职责；实例态留宿主经 _host 读写）
        self._recovery = RecoveryController(self)
        # R9-B5-W2-01: SessionLifecycle——会话前段 reconcile / workspace 职责面 / 收尾持久化
        self._runtime_params = RuntimeParamsService(self)
        self._routing = RoutingService(self)  # W4-02b: _RoutingMixin 退役（模型路由职责服务）
        self._fallback = FallbackService(self)  # W4-02c: _FallbackMixin 退役（模型降级链职责服务）
        self._archive = ArchiveService(self)  # W4-02d: _ArchiveMixin 退役（压缩另存职责服务）
        self._interop = InteropService(self)  # W4-02e: _InteropMixin 退役（协调通道注入职责服务）
        self._session_lifecycle = SessionLifecycle(self)
        self._attempt_executor = AttemptExecutor(self)
        # R9-B5-W3-01: ToolCycleService——工具执行循环职责面（_ToolExecMixin/_ToolEligibilityMixin 迁入）
        self._tool_cycle = ToolCycleService(self)
        self._run_finalizer = RunFinalizer(self)
        # EVO-20260817-cef296f8 L2: 缓存命中率窗口监控（跨 run 累计，实例级；
        # 低命中率 → final_answer 注入诊断 + action_trace 审计，fail-open）
        # EVO-20260817-72fcd94a L3（闭环）: 缓存健康监控 + 发送前门禁（独立模块，程序常态锚点管理）
        from llm_loop.core.cache_health import CacheHealthMonitor

        self._cache_monitor = CacheHealthMonitor()
        self._recovery._err1210_init()  # err1210 P0 恢复状态字段（tasks 4.2；字段语义见 err1210.py）
        # 2026-08-22 任务聚焦状态（focus 模块: 单向切换锁定 + 任务锚点数据源）
        # EVO-20260818（spec §5.4.1-3 注记，grill-me C1）: 模型切换检测——每轮对比实际
        # 模型，变化时 reset cache_health 窗口（防跨模型归因污染）
        self._cache_last_model: str | None = None  # 最近活跃模型（兼容诊断；切换判定不再用全局值）
        self._cache_last_model_by_session: dict[str, str] = {}  # 2026-08-27: 防跨会话模型状态污染
        # EVO-20260817-b6554376: 投影一致性门闸最近状态（ok/miss/mismatch；构建后更新）
        self._projection_guard_state: str = "miss"
        # M50: CLI --model 启动参数装配通道（cli.py 注入，_run_single/_run_interactive 消费）
        self._cli_startup_model: str | None = None
        # H-UI(2026-08-14): 动作观察者（实时 UI 状态条：thinking/tool_call/tool_result/answer/done）
        # None = 不通知（零回归）；观察者异常 fail-open 不影响主循环
        self._action_observer: Callable[[str, dict], None] | None = None

    # ---- 运行时参数委托壳（W4-02a：_RuntimeParamsMixin → RuntimeParamsService；
    #      公开面签名不变——build/routing/turn_context/attempt_executor/tests 零改动）----
    def _runtime_max_iterations(self) -> int:
        return self._runtime_params._runtime_max_iterations()

    def _runtime_history_budget(self) -> int:
        return self._runtime_params._runtime_history_budget()

    def _runtime_extract_interval(self) -> int:
        return self._runtime_params._runtime_extract_interval()

    def _runtime_memory_top_k(self) -> int:
        return self._runtime_params._runtime_memory_top_k()

    def _runtime_timeout(self) -> float | None:
        return self._runtime_params._runtime_timeout()

    # ---- 模型路由委托壳（W4-02b：_RoutingMixin → RoutingService；签名面为运行时参数形（类型标注见 RoutingService 真身），kwonly 默认值保留且按名转发实值——公开面调用兼容零变化）----
    def _pool_registry_snapshot(self):
        return self._routing._pool_registry_snapshot()

    def _pool_default_registry_snapshot(self):
        return self._routing._pool_default_registry_snapshot()

    def _round_registry_snapshots(self, model, sess):
        return self._routing._round_registry_snapshots(model, sess)

    def _route_model(self, model, sess, *, registry_snapshot=None, default_registry_snapshot=None):
        return self._routing._route_model(
            model,
            sess,
            registry_snapshot=registry_snapshot,
            default_registry_snapshot=default_registry_snapshot,
        )

    def _default_model_label(self, *, registry_snapshot=None):
        return self._routing._default_model_label(registry_snapshot=registry_snapshot)

    def _current_context_limit(self, model_label, *, registry_snapshot=None):
        return self._routing._current_context_limit(
            model_label, registry_snapshot=registry_snapshot
        )

    def _planned_model_label(self, model, sess, *, registry_snapshot=None):
        return self._routing._planned_model_label(model, sess, registry_snapshot=registry_snapshot)

    def _provider_chars_per_token(self, model_label, *, registry_snapshot=None):
        return self._routing._provider_chars_per_token(
            model_label, registry_snapshot=registry_snapshot
        )

    def _resolve_history_budget(self, model_label, *, registry_snapshot=None):
        return self._routing._resolve_history_budget(
            model_label, registry_snapshot=registry_snapshot
        )

    def _effective_history_budget_detail(self, model_label, *, registry_snapshot=None):
        return self._routing._effective_history_budget_detail(
            model_label, registry_snapshot=registry_snapshot
        )

    def _effective_history_budget(self, model_label, *, registry_snapshot=None):
        return self._routing._effective_history_budget(
            model_label, registry_snapshot=registry_snapshot
        )

    # ---- 模型降级链委托壳（W4-02c：_FallbackMixin → FallbackService；签名面为运行时参数形（类型标注见 FallbackService 真身），kwonly 默认值保留且按名转发实值——公开面调用兼容零变化）----
    def _is_fallback_eligible_error(self, exc):
        return FallbackService._is_fallback_eligible_error(exc)

    def _merge_fallback_metadata(self, metadata, context_limit, chars_per_token):
        return FallbackService._merge_fallback_metadata(metadata, context_limit, chars_per_token)

    def _try_fallback_chain(
        self,
        *,
        messages,
        tools,
        timeout_s,
        primary_error,
        session_id,
        from_model=None,
        run_round=None,
        metadata_out=None,
        request_builder=None,
    ):
        return self._fallback._try_fallback_chain(
            messages=messages,
            tools=tools,
            timeout_s=timeout_s,
            primary_error=primary_error,
            session_id=session_id,
            from_model=from_model,
            run_round=run_round,
            metadata_out=metadata_out,
            request_builder=request_builder,
        )

    def _fallback_reason_label(self, exc):
        return FallbackService._fallback_reason_label(exc)

    def _build_fallback_all_failed_message(self, *, from_model, primary_error, candidate_lines):
        return FallbackService._build_fallback_all_failed_message(
            from_model=from_model, primary_error=primary_error, candidate_lines=candidate_lines
        )

    # ---- 压缩另存委托壳（W4-02d：_ArchiveMixin → ArchiveService；签名面为运行时参数形（类型标注见 ArchiveService 真身）——公开面调用兼容零变化）----
    def _archive_feedback_session(self, session_id):
        return self._archive._archive_feedback_session(session_id)

    def _archive_sink(self, session_id, msg):
        return self._archive._archive_sink(session_id, msg)

    # ---- 协调通道委托壳（W4-02e：_InteropMixin → InteropService；签名面保真——build.py 以绑定方法传递 _inject_interop_messages、tests 直调 _interop_inbox_messages；公开面调用兼容零变化）----
    def _interop_svc(self) -> InteropService:
        """服务惰性兜底：tests 以 __new__ 裸构造绕过 __init__ 挂载时补建（fail-open 契约沿 mixin 时代）."""
        svc = getattr(self, "_interop", None)
        if svc is None:
            svc = self._interop = InteropService(self)
        return svc

    def _interop_inbox_messages(self):
        return self._interop_svc()._interop_inbox_messages()

    def _inject_interop_messages(self, base, prefix_len, session_id=""):
        return self._interop_svc()._inject_interop_messages(base, prefix_len, session_id)

    def _inject_switch_notice(self, switch_from, switch_to, sess=None):
        return self._interop_svc()._inject_switch_notice(switch_from, switch_to, sess)

    # ── 主循环本体（public run_stream 生命周期包装见 lifecycle.py）──
    def _llm_error_round_exit(self, sess, cap, exc, session_id, n_messages, rounds, flavor):
        """LLMError 轮统一出口（D-B5-14 去重：fallback 链全失败/恢复失败两分支逐字重复段）.

        中断半截产物落盘（cap 防重）+ e1210 程序反馈收尾；resp 恒 None——
        程序反馈不得继承上一轮成功响应的 reasoning（GPT 审计 P0：stale reasoning 嫁接）。
        """
        cap.fire(sess, "llm_error", rounds, exc)
        final = self._recovery._e1210_llm_error_finalize(session_id, exc, n_messages, flavor)
        return final, None

    def _run_stream_inner(
        self,
        session_id: str,
        user_text: str,
        model: str | None = None,
        *,
        run_save_token: object | None = None,
        on_run_acquired: Any = None,
        ingress: object | None = None,
    ) -> Iterator[StreamDelta]:
        """run_stream 的循环本体（P0-5 包装层拆出；逻辑与拆分前逐行一致）.

        agent_trace_leak 3.5: ingress 为人类输入通道凭据（B2 双因子判定——
        user_instruction 判定从"调用方传参"升级为"调用方凭据 + 通道白名单"）。
        """
        # P0-5: 记录最近活跃会话（out-of-run 桶解析的回退锚点，保持测试复查语义）
        self._run_state_mgr.last_active_sid = session_id
        tool_trace: list[dict] = []
        # P2-A Rule-first: run 级只重置工具重复/空结果事实观测；不恢复任何
        # cross-run blocked/prewarm/no-progress 决策状态。
        _bucket = self._run_state()
        _bucket.fallback_receipt = None
        _bucket.stagnation_state = {
            "fp": None,
            "count": 0,
            "reminded": False,
            "empty_count": 0,
            "empty_reminded": False,
        }
        _bucket.interruption_resume = (
            None  # rebuilt from durable interruption/checkpoint facts after ingress append
        )
        # P1-A/P1-B: runtime does not parse current-user semantics into task or
        # tool-selection authority. Delegated wakes remain explicitly attributable.
        if bool(getattr(ingress, "delegated", False)):
            self._record_action("schedule.wake", "delegated_ingress", f"session={session_id}")
        # HARNESS-04(2026-08-14): 上下文预算预警——每次 run 独立判断（上下文随 run 累积）
        self._run_state().context_warning_injected = False

        plan = self._session_lifecycle.reconcile(
            session_id, run_save_token=run_save_token, on_run_acquired=on_run_acquired
        )
        sess = plan.sess
        self._recover_pre_ingress_runtime_state(session_id, sess)

        # T22/T23: 注入当前会话到注册表与修正上下文（压缩档案/检索关联）
        from contextlib import suppress

        with suppress(AttributeError):
            self.registry.set_session_id(session_id)
        if self.correction_ctx is not None:
            self.correction_ctx.session_id = session_id
            # M48（design §5.3）: switch_model 写入会话级 override 的回调（直接修改 in-memory sess）
            # loop 结束时 self.session.save(sess) 会持久化该字段（向后兼容，旧会话缺该字段 → None）
            self.correction_ctx.session_model_override = sess.model_override
            self.correction_ctx.session_set_override = lambda value: self._set_session_override(
                sess, value
            )
            # P0-5: 每会话绑定表——并发 run 各自 sess 不互踩（registry_model 经
            # contextvar 解析本会话绑定，上方 ctx 字段保留为无上下文回退）
            with self._run_state_mgr.guard:
                self._run_sessions[session_id] = sess

        # R8.5/R8.20 lifecycle migration-on-use. Whole episodes retire only with
        # resolution proof. Independently, complete raw tool spans may retire after a
        # later non-tool model assistant has consumed them and the exact visible span
        # is durably indexed. This happens before the new user message is appended, so
        # the current tool-followup protocol can never be mistaken for historical.
        try:
            from llm_loop.core.episode_history import (
                backfill_closed_tool_attempts,
                backfill_completed_episodes,
                backfill_consumed_tool_spans,
            )

            backfill_completed_episodes(self.episode_store, sess, event_store=self._event_store)
            backfill_consumed_tool_spans(self.episode_store, sess)
            # A failed tool attempt remains useful to delegated/automatic recovery
            # until a new genuine human ingress arrives. Only at that boundary may
            # event-proven closed raw tool protocol retire from the default provider
            # view; it is indexed as closed (not consumed/resolved) first.
            if not bool(getattr(ingress, "delegated", False)):
                backfill_closed_tool_attempts(
                    self.episode_store, sess, event_store=self._event_store
                )
        except Exception:  # noqa: BLE001 — retrieval indexing must not block a run
            logger.warning("history lifecycle 索引失败（fail-open，不退休）", exc_info=True)

        # ── 消息进：构造用户消息并落库 ──
        user_msg = Message(
            role="user",
            content=user_text,
            source=MessageSource.USER,
            metadata=origin_metadata(InjectionLayer.USER_INSTRUCTION),
        )
        # agent_trace_leak 3.5: user_instruction 判定双因子收口（凭据 + 白名单；
        # 合法凭据路径落盘字节零变化——metadata 仅固化 ingress 通道快照两键）。
        # guard 异常 fail-open 放行 + leak.guard_fault 告警（spec 4.2-1）。
        try:
            from llm_loop.core.trace_leak.user_ingress_guard import (
                GuardAction,
                guard_user_write,
            )

            _verdict = guard_user_write(sess, user_msg, ingress, entry="engine.run")
            if _verdict.action is GuardAction.DENY:
                # enforce 拒绝：不落盘不执行循环，如实返回拒绝回执（事件/隔离已留痕）
                return LoopResult(
                    session_id=session_id,
                    final_answer=(
                        "[写入被拒] 本次 user 身份写入未通过通道白名单校验"
                        "（leak.channel_denied 事件已留痕，内容已隔离记录）。"
                    ),
                    rounds=0,
                )
            user_msg = _verdict.message
        except ImportError:  # pragma: no cover - 装配异常 fail-open
            logger.warning("user_ingress_guard 不可用（fail-open 放行）", exc_info=True)
        # agent_trace_leak 2.3: 落盘前恒等式校验（fail-open——异常放行 + 告警；
        # 违反即纠正为程序附录层标记 + mislabel 事件；仅作用新写入，spec 4.5-1）
        try:
            if metadata_satisfies_invariant(user_msg.metadata) is False:
                leak_events.emit_leak_event(
                    leak_events.LEAK_MISLABEL_DETECTED,
                    entry="engine.persist_user_message",
                    session_id=session_id,
                    content=user_msg.content,
                    basis="恒等式违反: program_origin != (origin_layer != user_instruction)",
                    sink=self._event_append,
                )
                user_msg.metadata = correct_mislabeled_metadata(user_msg.metadata)
        except Exception:  # noqa: BLE001 — fail-open（spec 4.2-1）
            logger.warning("user 消息落盘恒等式校验异常（fail-open 放行）", exc_info=True)
        sess.messages.append(user_msg)
        # D1: 会话首次落库生成 session.created + 用户消息事件（fail-open）
        self._ensure_session_created(sess)
        self._append_message_event(sess, user_msg)
        self._prepare_interruption_resume(session_id, sess)
        _turn_ref = len(sess.messages) - 1  # user_msg seq（turn 身份）
        # T5: per-session RunState 分桶（串台修复）；tip 判断改 SoT 派生（tool_exec）
        self._run_state().current_turn_ref = _turn_ref
        # Agency-first: memory/history is retrieved explicitly by the model when needed.
        # Ordinary user turns do not trigger automatic retrieval or persisted snapshots.
        _turn_memory_msgs: list[Message] = []
        self._phase("ingress")

        final_answer = ""
        verification_note: str | None = None
        truncation_noted = False
        rounds = 0
        # DSH 借鉴(2026-08-17): run 结束原因（统一出口 run.end 事件用；各结束分支标记，
        # 默认 completed——未标记即正常完成。fail-open 不阻断）
        _run_end_reason = "completed"
        _cancel_reason = (
            ""  # 取消原因标记位（user_stop/runner_stop；""=未取消，收口贯穿 LoopResult）
        )
        _run_started_at = time.monotonic()
        self._termination._reset_overflow_state()  # R4: 每次 run 重置 overflow 注入计数
        self._recovery._err1210_run_begin()  # 修复A: per-run 降级机会（attempted 键 = run seq）
        self._last_interrupted = (
            None  # B1/B2(EVO-20260902-41898b20): 本 run 中断半截产物缓存（新 run 重置防陈旧串台）
        )
        model_used = ""  # M51: 本轮实际使用的模型标签（每轮 LLM 调用时刷新）
        tokens_in = 0  # M52: 本次 run 累计 prompt tokens
        tokens_out = 0
        tokens_cache_hit = 0  # M58: 本次 run 前缀缓存命中 token（省钱可观测）
        reasoning_mode_used = _current_reasoning_mode.get() or "auto"
        reasoning_capable = False
        reasoning_control = "unknown"
        reasoning_supported = False
        reasoning_effective = False
        reasoning_tokens: int | None = None
        llm_ms_total = 0.0  # M59: 本次 run LLM 调用总耗时（首 token 埋点聚合）
        ttft_first_ms: float | None = None  # M59: 首个 token 延迟（首 token 平均数据源）
        self._kpi_reset()  # EVO-20260822-9fde48f1 第 10 条: KPI 三件套重置（对比基线用）
        resp: Any = None  # M20 THK-04: 最终回答轮思考链来源（LLM 异常/停滞路径为 None）
        # 2026-09-03: leaked historical [program-final] markers can be imitated by the
        # model.  One in-process retry is allowed without persisting the echo; a second
        # exact echo is a truthful output fault, never a completed answer.
        _program_final_echo_retries = 0

        while True:
            # 后台 Stop：轮次边界兜底；LLM 流内另有细粒度检查（原因捕获，2.3）。
            _cancel_reason = _background_cancel_reason(self, session_id)
            if _cancel_reason:
                _run_end_reason = "cancelled"
                final_answer = _CANCELLED_ANSWER
                break
            rounds += 1
            # CR-R1.1（审查项7）: 轮次入 contextvar——cognitive telemetry 等 build 期
            # 组件归因 round 用（此前 packet_compile 的 round 恒 0）
            with contextlib.suppress(Exception):
                from llm_loop.core.run_context import current_round_no

                current_round_no.set(rounds)
            _background_note_active(self, session_id, rounds)
            if self.runtime is not None:
                self.runtime.reset_round()
            # H-UI: 每轮思考开始（实时状态条）
            self._notify_action("thinking", round=rounds)
            self._phase("comprehension")
            if self.status:
                self.status.record_llm_round()

            # ── 理解：上下文构造（memory 已上移 run 入口；_turn_memory_msgs 仅 build 回退）──

            # 热重载一致性：每个 LLM round 捕获一次 current/default/planning 不可变 registry 快照。
            _round_registry, _default_registry, _planning_registry = self._round_registry_snapshots(
                model, sess
            )

            # Resolve the requested provider/model before any prompt/history mutation.
            # A missing model/key is a routing fact, not a reason to compact or project history.
            routing = self._route_model(
                model,
                sess,
                registry_snapshot=_round_registry,
                default_registry_snapshot=_default_registry,
            )
            llm_client = routing.llm_client
            model_used = routing.model_used
            chat_model_arg = routing.chat_model_arg
            _response_context_limit = routing.context_limit
            _response_chars_per_token = routing.chars_per_token
            _response_max_output_tokens = max(0, int(getattr(llm_client, "max_tokens", 0) or 0))
            if routing.final_answer_override is not None:
                self._tool_cycle._reachability_finalize("route_rejected_before_provider")
                _run_end_reason = "routing_override"
                final_answer = routing.final_answer_override
                break

            # Model-switch observability is session-scoped and does not write prompt text.
            _sid = sess.session_id
            _switch_from = self._cache_last_model_by_session.get(_sid)
            if model_used and model_used != _switch_from:
                if _switch_from is not None:
                    self._cache_monitor.reset(
                        reason=f"model_switch:{model_used}", clear_buckets=False
                    )
                self._cache_last_model_by_session[_sid] = model_used
                self._cache_last_model = model_used
                self._inject_switch_notice(_switch_from or "", model_used, sess)
            elif model_used:
                self._cache_last_model = model_used

            # M54: 模型窗口感知的主动压缩 — 规划段归装 AttemptExecutor（B5-W2-02；
            # planned_label/budget 预取链/工具轮零历史判定 → AttemptResult，
            # build 传参面零变化）
            _plan = self._attempt_executor.plan(model, sess, _planning_registry)
            planned_label = _plan.planned_label
            effective_budget = _plan.effective_budget
            # P0 压缩风暴熔断（2026-08-25 规格）: 冻结期超安全水位 → context_pressure
            # （实现在 _BuildMixin._breaker_pressure_block——engine 只接线）
            _pressure_block = self._breaker_pressure_block(sess, effective_budget, planned_label)
            if _pressure_block:
                _run_end_reason = "breaker_context_pressure"
                final_answer = _pressure_block
                break
            # R3-MR-4: tool projection must precede prompt build so any structured
            # unavailable facts enter the governed dynamic-injection budget and R6 tail.
            tool_schemas, tools_param = self._project_request_tools(
                session_id=session_id,
                user_text=user_text,
                planned_label=planned_label,
                session_messages=sess.messages,
                logical_round=rounds,
            )
            messages = self._build_llm_messages(
                sess,
                _turn_memory_msgs,
                max_chars=effective_budget,
                model=model,
                planned_label=planned_label,
                registry_snapshot=_planning_registry,
            )
            self._kpi_accumulate_inject()
            if getattr(self, "_last_history_compacted", False):
                truncation_noted = True

            # R1: 组件级占用分解（实际发送载荷口径；压缩归档历史不计入当前占用）
            # 供 architecture_status.context_usage.breakdown 注入；last_build_info 入桶保留。
            from llm_loop.core.history import compute_breakdown_from_dicts

            self._run_state().last_breakdown = compute_breakdown_from_dicts(
                messages,
                tool_schema_chars=len(_json_dumps_args({"tools": tools_param})),
                budget=effective_budget,
            )
            # EVO-20260818: 预算归属模型标注（防误读——provider 级预算如 minimax 40K
            # 与全局 1M 并存，AI 看到 ratio>1 需知 budget 属于哪个模型）
            self._run_state().last_breakdown["model"] = planned_label

            # ── 行动：LLM 决策 ──
            self._phase("action.llm_decide")
            # HARNESS-02(2026-08-14): 每轮请求快照进事件日志（fail-open）——routing/fallback
            # 可能中途换模型，事件回放据此确知"当时用的哪个模型/挂了哪些工具/预算多少"，
            # 对 self_evaluate 溯源与回放诊断有帮助
            try:
                _reasoning_contract_fn = getattr(llm_client, "reasoning_contract_state", None)
                if callable(_reasoning_contract_fn):
                    (
                        _round_reasoning_mode,
                        _round_reasoning_capable,
                        _round_reasoning_control,
                        _round_reasoning_supported,
                        _round_reasoning_requested,
                    ) = cast(
                        tuple[str, bool, str, bool, bool],
                        _reasoning_contract_fn(),
                    )
                else:
                    _reasoning_state_fn = getattr(llm_client, "reasoning_control_state", None)
                if not callable(_reasoning_contract_fn) and callable(_reasoning_state_fn):
                    (
                        _round_reasoning_mode,
                        _round_reasoning_supported,
                        _round_reasoning_requested,
                    ) = cast(
                        tuple[str, bool, bool],
                        _reasoning_state_fn(),
                    )
                    _round_reasoning_capable = bool(
                        getattr(llm_client, "reasoning_capable", _round_reasoning_supported)
                    )
                    _round_reasoning_control = "legacy" if _round_reasoning_supported else "unknown"
                elif not callable(_reasoning_contract_fn):
                    # 兼容测试桩/第三方 client：telemetry 绝不能因缺新方法而整条消失。
                    _round_reasoning_mode = _current_reasoning_mode.get() or "auto"
                    _round_reasoning_supported = bool(
                        getattr(llm_client, "thinking_supported", False)
                    )
                    _round_reasoning_capable = bool(
                        getattr(llm_client, "reasoning_capable", _round_reasoning_supported)
                    )
                    _round_reasoning_control = (
                        str(getattr(llm_client, "reasoning_control", "legacy") or "legacy")
                        if _round_reasoning_supported
                        else "unknown"
                    )
                    _round_reasoning_requested = None
                reasoning_mode_used = _round_reasoning_mode
                reasoning_capable = _round_reasoning_capable
                reasoning_control = _round_reasoning_control
                reasoning_supported = _round_reasoning_supported
                _history_chars = sum(len(str(m.get("content", "") or "")) for m in messages)
                _reasoning_chars = sum(
                    len(str(m.get("reasoning_content", "") or "")) for m in messages
                )
                try:
                    # Major provider-visible structures only: message payload + tool schemas.
                    # This deliberately excludes transport-only headers/credentials while making
                    # hidden historical reasoning visible in telemetry.
                    _provider_visible_chars = len(
                        json.dumps(
                            {"messages": messages, "tools": tools_param},
                            ensure_ascii=False,
                            separators=(",", ":"),
                            default=str,
                        )
                    )
                except (TypeError, ValueError):
                    _provider_visible_chars = _history_chars + _reasoning_chars
                self._event_append(
                    session_id,
                    "request.meta",
                    {
                        "round": rounds,
                        # model_used 在无 pool 场景可能为空 → 回退装配模型名（如实标注）
                        "model": model_used or getattr(self.settings, "llm_model", ""),
                        # legacy 字段保留，但改为真实“本请求是否显式请求 reasoning”；
                        # auto+本地 provider 默认未知时为 None，不再伪装成 True。
                        "thinking": _round_reasoning_requested,
                        "reasoning_mode": _round_reasoning_mode,
                        "reasoning_capable": _round_reasoning_capable,
                        "reasoning_control": _round_reasoning_control,
                        "reasoning_supported": _round_reasoning_supported,
                        "reasoning_requested": _round_reasoning_requested,
                        "reasoning_effort": str(
                            _current_reasoning_effort.get()
                            or getattr(llm_client, "reasoning_effort", "")
                        ),
                        "tools_count": len(tools_param),
                        "history_chars": _history_chars,
                        "reasoning_chars": _reasoning_chars,
                        "provider_visible_chars": _provider_visible_chars,
                        "budget": effective_budget,
                        "projection_guard": getattr(self, "_projection_guard_state", "miss"),
                    },
                )
            except Exception:  # noqa: BLE001 — 快照失败 fail-open（不影响主循环）
                logger.debug("request.meta 事件写入失败（fail-open）")
            self._tool_cycle._reachability_begin_attempt(
                kind="primary",
                attempt_index=0,
                model=model_used or chat_model_arg or getattr(llm_client, "model", ""),
                provider=getattr(llm_client, "provider", ""),
            )
            cap = InterruptedCapture(
                self,
                sess=sess,
                round_no=rounds,
                provider=getattr(llm_client, "provider", ""),
                model=model_used or chat_model_arg or getattr(llm_client, "model", ""),
            )  # B1: 轮级重置 + durable in-flight checkpoint for restart continuity
            try:
                stream_fn = getattr(llm_client, "chat_stream", None)
                _llm_round_ms = 0.0
                if stream_fn is not None:
                    _llm_start = time.perf_counter()
                    _ttft_done = False
                    # cache_guard 每请求上下文：只对真实 LLMClient 显式传参，FakeLLM/
                    # 第三方 duck-typed client 保持旧签名兼容。绝不写 provider 级共享
                    # client.guard_* 字段，避免并发 session 在流开始/结束时串台。
                    _guard_ctx = (
                        GuardRequestContext(
                            session_id=session_id,
                            system_text=(
                                messages[0].get("content", "")
                                if messages and messages[0].get("role") == "system"
                                else None
                            ),
                            compress_count_this_run=getattr(self, "_compress_count_this_run", 0),
                            history_budget=int(effective_budget or 0),
                            breaker_active=self._cache_monitor.breaker_active_for(session_id),
                            run_round=rounds,
                            provider=getattr(llm_client, "provider", ""),
                            model=chat_model_arg or getattr(llm_client, "model", ""),
                            stream_state_hook=cap.on_provider_state,
                        )
                        if isinstance(llm_client, LLMClient)
                        else None
                    )
                    _stream_kwargs: dict[str, Any] = {
                        "messages": messages,
                        "tools": tools_param,
                        "timeout_s": self._runtime_timeout(),
                        "model": chat_model_arg,
                    }
                    if _guard_ctx is not None:
                        _stream_kwargs["guard_context"] = _guard_ctx
                    it = stream_fn(**_stream_kwargs)
                    while True:
                        try:
                            d = next(it)
                            _cancel_reason = _background_cancel_reason(self, session_id)
                            if _cancel_reason:
                                cap.cancelled = True
                                _llm_round_ms = (time.perf_counter() - _llm_start) * 1000.0
                                cap.fire(
                                    sess, "cancelled", rounds
                                )  # B1: 半截产物限量落盘（防重内聚）
                                close_stream = getattr(it, "close", None)
                                if callable(close_stream):
                                    try:
                                        close_stream()
                                    except Exception:  # noqa: BLE001 — 取消时释放流 fail-open
                                        logger.debug(
                                            "LLM stream close 失败（fail-open）", exc_info=True
                                        )
                                break
                            if not _ttft_done and getattr(d, "text", ""):
                                _ttft_done = True
                                ttft_first_ms = (time.perf_counter() - _llm_start) * 1000.0
                            cap.on_delta(d)
                            yield d
                        except StopIteration as exc:
                            resp = exc.value
                            _llm_round_ms = (time.perf_counter() - _llm_start) * 1000.0
                            break
                        except GeneratorExit:
                            # P1-6(2026-08-15，审计发现 #17)：客户端断连——部分回答如实
                            # 落会话（中断标注不伪装完整）并立即保存，闭合"事件日志已追加
                            # 而 session JSON 未保存"的双轨漂移。
                            self._on_stream_disconnect(sess, cap.text_parts)
                            raise
                else:
                    # 无 chat_stream 的客户端（如测试 FakeLLM）→ 同步 chat（不 yield，行为与 run 一致）
                    _llm_sync_start = time.perf_counter()
                    _chat_kwargs: dict[str, Any] = {
                        "messages": messages,
                        "tools": tools_param,
                        "timeout_s": self._runtime_timeout(),
                        "model": chat_model_arg,
                    }
                    if isinstance(llm_client, LLMClient):
                        _chat_kwargs["guard_context"] = GuardRequestContext(
                            session_id=session_id,
                            system_text=(
                                messages[0].get("content", "")
                                if messages and messages[0].get("role") == "system"
                                else None
                            ),
                            compress_count_this_run=getattr(self, "_compress_count_this_run", 0),
                            history_budget=int(effective_budget or 0),
                            breaker_active=self._cache_monitor.breaker_active_for(session_id),
                            run_round=rounds,
                            provider=getattr(llm_client, "provider", ""),
                            model=chat_model_arg or getattr(llm_client, "model", ""),
                        )
                    resp = llm_client.chat(**_chat_kwargs)
                    _llm_round_ms = (time.perf_counter() - _llm_sync_start) * 1000.0
                _cancel_reason = _background_cancel_reason(self, session_id)
                if _cancel_reason:
                    cap.cancelled = True
            except LLMError as exc:
                # 取消伴生异常归因拦截（2.4）：取消标记置位后 LLM 抛出的中断异常
                # （"Operation canceled"/"Model unloaded" 等，文本随运行时漂移）是
                # 用户主动取消的伴生现象——按标记位归因取消收口（禁止文本匹配，
                # spec 4.4.1），短路 guard/overflow/err1210/fallback/R9/故障反馈
                # 全部真实故障路径（spec 5.1.1-6）；标记未置位时行为与现状一致。
                _cancel_reason = _background_cancel_reason(self, session_id)
                self._tool_cycle._reachability_finalize(
                    "cancelled_provider" if _cancel_reason else "provider_error"
                )
                if _cancel_reason:
                    _run_end_reason = "cancelled"
                    final_answer = _CANCELLED_ANSWER
                    resp = None
                    break
                # 拷问⑥（2026-08-18）: cache_guard BLOCK——直接如实反馈 AI
                # （不重试/不走 overflow reinject——重试同样被拦=浪费循环；AI 需先
                # 压缩/换会话自救）
                from llm_loop.cache_guard.guard import CacheGuardBlockedError

                if isinstance(exc, CacheGuardBlockedError):
                    self._record_action("action.llm_decide", "guard_block", str(exc)[:200])
                    if self.status:
                        self.status.record_exception("guard_block", exc)
                    _run_end_reason = "guard_blocked"
                    final_answer = (
                        f"[缓存守卫拦截] {exc}\n\n建议：压缩 checkpoint 或换新会话后重试。"
                    )
                    break
                self._record_action("action.llm_decide", "llm_error", str(exc)[:200])
                if self.status:
                    self.status.record_exception("llm_call", exc)
                self._record_program_fault("llm_call")
                # Actual provider overflow is the authority: one deterministic budget shrink +
                # lossless normal compaction retry, then factual termination if it still overflows.
                # → _OverflowMixin._handle_overflow（move 语义，行为零变化）
                overflow_action, overflow_final = self._termination._handle_overflow(
                    exc,
                    sess,
                    model_used,
                    model_window={"label": model_used, "context": _response_context_limit},
                )
                if overflow_action == "reinject":
                    # R8.24-B B-D5: 首次 overflow——预算已确定性收缩
                    # （_overflow_shrink_factor），continue 后下一轮 build 以收紧
                    # 预算重组（超出部分 lossless 归档），零 prompt 注入。
                    continue
                if overflow_action == "end" and overflow_final is not None:
                    _run_end_reason = "overflow"
                    final_answer = overflow_final
                    break
                # ── err1210 P0（tasks 4.3）: compact 首请求 1210 定向降级重试（mixin 封装，
                # 编排与控制流语义见 err1210.py；恢复成功 → 新 resp 走下方正常路径，
                # 失败 → 原样继续既有错误链；env ERR1210_RECOVERY=0 完全旁路）──
                _e1210_recovered, resp, _llm_round_ms, _ = (
                    self._recovery._err1210_attempt_recovery(
                        exc=exc,
                        sess=sess,
                        messages=messages,
                        tools_param=tools_param,
                        llm_client=llm_client,
                        chat_model_arg=chat_model_arg,
                        session_id=session_id,
                        current_resp=resp,
                        current_round_ms=_llm_round_ms,
                        model_label=model_used or getattr(self.settings, "llm_model", ""),
                        metadata_registry=routing.metadata_registry,
                        round_no=rounds,
                    )
                )
                # ── M49（design §5.4）: 降级逻辑 ──
                # 仅当当前模型为默认装配（sess.model_override is None 且 per-call override 也为 None）
                # 才沿 fallback 链尝试；会话显式 override（含用户/AI 经 switch_model 选择）=
                # 严格模式,失败直接如实反馈不降级（design §5.4 行为规则表核心）。
                # 4xx (非 429) 不降级：请求本身有问题,换模型无用（design §5.4 行为表注）。
                # D'-2.3 ③（R8.24 D-D6-3）: strict override 强化——用户选择权 >
                # 能力下限（floor 只作用于自动链；显式选定模型照执行不静默换链）。
                is_default_assembled = sess.model_override is None and chat_model_arg is None
                # P2-B: no program-side WIP/quality retry heuristic; mechanical
                # transport retry stays inside LLMClient.
                if (
                    not _e1210_recovered
                    and is_default_assembled
                    and self._is_fallback_eligible_error(exc)
                ):
                    _fallback_metadata: dict[str, Any] = {}

                    def _fallback_request_builder(
                        fallback_label: str, fallback_registry: Any, _round: int = rounds
                    ) -> tuple[list[dict], list[dict]]:
                        fallback_budget = self._effective_history_budget(
                            fallback_label, registry_snapshot=fallback_registry
                        )
                        fallback_schemas, fallback_tools = self._project_request_tools(
                            session_id=session_id,
                            user_text=user_text,
                            planned_label=fallback_label,
                            session_messages=sess.messages,
                            advance_state_round=False,
                            logical_round=_round,
                        )
                        fallback_messages = self._build_llm_messages(
                            sess,
                            _turn_memory_msgs,
                            max_chars=fallback_budget,
                            planned_label=fallback_label,
                            registry_snapshot=fallback_registry,
                        )
                        return fallback_messages, fallback_tools

                    fallback_resp, inject_msgs, fallback_ref = self._try_fallback_chain(
                        messages=messages,
                        tools=tools_param,
                        timeout_s=self._runtime_timeout(),
                        primary_error=exc,
                        session_id=sess.session_id,
                        from_model=model_used or getattr(self.settings, "llm_model", ""),
                        run_round=rounds,
                        metadata_out=_fallback_metadata,
                        request_builder=_fallback_request_builder,
                    )
                    # Successful fallback facts are carried by RunState/LoopResult, not
                    # model-visible Message objects. inject_msgs is all-failed facts only.
                    if fallback_resp is not None:
                        # 降级成功: 响应以新模型运行, 进入后续正常路径
                        resp = fallback_resp
                        if fallback_ref:
                            model_used = fallback_ref  # M51: 如实标注为降级后的模型
                        _response_context_limit, _response_chars_per_token = (
                            self._merge_fallback_metadata(
                                _fallback_metadata,
                                _response_context_limit,
                                _response_chars_per_token,
                            )
                        )
                        _response_max_output_tokens = max(
                            0,
                            int(
                                _fallback_metadata.get(
                                    "max_output_tokens", _response_max_output_tokens
                                )
                                or 0
                            ),
                        )
                    else:
                        # 链全失败 → 已注入汇总提示, 走原异常如实反馈路径
                        _run_end_reason = "llm_error"
                        final_answer, resp = self._llm_error_round_exit(
                            sess, cap, exc, session_id, len(messages), rounds, "fallback_exhausted"
                        )
                        if inject_msgs:
                            # The all-failed summary is useful to the current user, not
                            # to a future model turn. Surface it in this program result.
                            final_answer = f"{final_answer}\n\n{inject_msgs[-1].content}"
                        break
                elif not _e1210_recovered:
                    # P2-B: if no mechanical payload transform recovered the request,
                    # report the provider failure. No second exact resend/rebuild loop.
                    _run_end_reason = "llm_error"
                    final_answer, resp = self._llm_error_round_exit(
                        sess, cap, exc, session_id, len(messages), rounds, "llm_error"
                    )
                    break

            if cap.cancelled:
                self._tool_cycle._reachability_finalize("cancelled_provider")
                _run_end_reason = "cancelled"
                final_answer = _CANCELLED_ANSWER
                resp = None  # 防止上一轮响应残留参与 usage/reasoning/finalize
                break

            self._tool_cycle._reachability_record_response(resp)
            self._record_action(
                "action.llm_decide", "llm_response", self._tool_cycle._resp_summary(resp)
            )
            # M52: 聚合本轮 token 用量（含 fallback 成功响应；0 = provider 未提供）
            tokens_in += resp.prompt_tokens
            tokens_out += resp.completion_tokens
            tokens_cache_hit += resp.prompt_cache_hit_tokens
            if resp.reasoning_content:
                reasoning_effective = True
            if resp.reasoning_tokens is not None:
                reasoning_tokens = (reasoning_tokens or 0) + resp.reasoning_tokens
            llm_ms_total += _llm_round_ms
            self._kpi_accumulate_llm(planned_label, _llm_round_ms)
            _cache_state = self._run_state()
            _current_prefix_fp = _cache_state.cache_gate_stable_fp
            _previous_prefix_fp = _cache_state.last_cache_window_stable_fp
            _previous_prefix_model = _cache_state.last_cache_window_model
            _prefix_change_reason = ""
            if _cache_state.last_cache_window is not None:
                if _previous_prefix_model and _previous_prefix_model != model_used:
                    _prefix_change_reason = "model_changed"
                elif _previous_prefix_fp and _previous_prefix_fp != _current_prefix_fp:
                    _prefix_change_reason = "stable_prefix_changed"
            if _prefix_change_reason:
                _cache_state.cache_prefix_epoch += 1
            # DSH 借鉴(2026-08-17): 本轮响应 usage 明细落盘（fail-open）——命中/miss
            # token 逐轮可审计，命中率实时可算（不依赖 CSV 账单/流式 M58 盲区）。
            try:
                _req_usage_available = bool(resp.prompt_tokens)
                _cache_miss_tokens = max(0, resp.prompt_tokens - resp.prompt_cache_hit_tokens)
                _cache_hit_rate = (
                    resp.prompt_cache_hit_tokens / resp.prompt_tokens
                    if _req_usage_available
                    else None
                )
                _context_window = int(_response_context_limit) if _response_context_limit else None
                _context_headroom = (
                    _context_window - int(resp.prompt_tokens) - _response_max_output_tokens
                    if _context_window is not None and _req_usage_available
                    else None
                )
                _context_used_ratio = (
                    (int(resp.prompt_tokens) + _response_max_output_tokens) / _context_window
                    if _context_window and _req_usage_available
                    else None
                )
                _request_usage_payload = {
                    "round": rounds,
                    "model": model_used or getattr(self.settings, "llm_model", ""),
                    "tokens_in": resp.prompt_tokens,
                    "tokens_out": resp.completion_tokens,
                    "reasoning_effective": bool(resp.reasoning_content),
                    "reasoning_tokens": resp.reasoning_tokens,
                    "cache_hit": resp.prompt_cache_hit_tokens,
                    "cache_miss": _cache_miss_tokens,
                    "cache_read_tokens": resp.prompt_cache_hit_tokens,
                    "uncached_prompt_tokens": (
                        _cache_miss_tokens if _req_usage_available else None
                    ),
                    "cache_hit_rate": _cache_hit_rate,
                    "context_window": _context_window,
                    "output_reserve_tokens": _response_max_output_tokens,
                    "context_headroom_tokens": _context_headroom,
                    "context_used_ratio": _context_used_ratio,
                    "stable_prefix_fp": _current_prefix_fp,
                    "prefix_changed": bool(_prefix_change_reason),
                    "prefix_change_reason": _prefix_change_reason,
                    "cache_prefix_epoch": _cache_state.cache_prefix_epoch,
                    "compaction_epoch": _cache_state.compact_event_seq,
                    "runtime_pid": os.getpid(),
                    "usage_available": _req_usage_available,
                }
                _cache_state.last_request_usage = dict(_request_usage_payload)
                self._event_append(session_id, "request.usage", _request_usage_payload)
            except Exception:  # noqa: BLE001 — usage 明细失败 fail-open（不影响主循环）
                logger.debug("request.usage 事件写入失败（fail-open）")

            # 2026-08-24 缓存窗口镜像（cache.window 事件）: 把服务端 cached_tokens
            # （前缀命中 token 数）映射回提交载荷的消息级窗口——缓存覆盖到哪条消息、
            # 哪些是新增（miss 区）。供 architecture_status 观察 + 信息补充决策
            # （引用缓存区内信息零额外 prefill; 新增信息尾部追加保持命中; 中插/压缩断前缀）。
            try:
                from llm_loop.core.cache_window import describe_cache_window

                _win = describe_cache_window(
                    messages,
                    resp.prompt_cache_hit_tokens,
                    resp.prompt_tokens,
                    # EVO-20260824: 缓存边界换算与估算同源（provider 级 chars_per_token）
                    chars_per_token=_response_chars_per_token,
                )
                _cache_state.last_cache_window = _win
                _cache_state.last_cache_window_model = model_used or getattr(
                    self.settings, "llm_model", ""
                )
                _cache_state.last_cache_window_turn_ref = _cache_state.current_turn_ref
                _cache_state.last_cache_window_stable_fp = _cache_state.cache_gate_stable_fp
                self._event_append(
                    session_id,
                    "cache.window",
                    {
                        "round": rounds,
                        "model": model_used or getattr(self.settings, "llm_model", ""),
                        "cached_tokens": _win.cached_tokens,
                        "prompt_tokens": _win.prompt_tokens,
                        "hit_ratio": round(_win.hit_ratio, 4),
                        "cache_read_tokens": _win.cached_tokens,
                        "uncached_prompt_tokens": max(0, _win.prompt_tokens - _win.cached_tokens)
                        if _win.prompt_tokens > 0
                        else None,
                        "boundary_chars": _win.boundary_chars,
                        "boundary_msg_index": _win.boundary_msg_index,
                        "boundary_mapping": "estimated_message_chars",
                        "boundary_exact": bool(getattr(_win, "boundary_exact", False)),
                        "stable_prefix_fp": _current_prefix_fp,
                        "prefix_changed": bool(_prefix_change_reason),
                        "prefix_change_reason": _prefix_change_reason,
                        "cache_prefix_epoch": _cache_state.cache_prefix_epoch,
                        "compaction_epoch": _cache_state.compact_event_seq,
                        "runtime_pid": os.getpid(),
                        "cached_msgs": _win.cached_msgs,
                        "new_msgs": _win.new_msgs,
                        "summary": _win.summary(),
                    },
                )
            except Exception:  # noqa: BLE001 — 窗口镜像失败 fail-open（不影响主循环）
                logger.debug("cache.window 事件写入失败（fail-open）")

            # 无工具调用 → 最终回答 → 真诚回答阶段
            if not resp.tool_calls:
                final_answer = resp.content or ""
                # Internal protocol tokens are not model answers.  Historical builds
                # leaked ``[program-final]`` into provider-visible assistant content;
                # when a model imitates it, do not persist it or report completed.
                if final_answer.strip() == LEGACY_PROGRAM_FINAL_MARKER:
                    with contextlib.suppress(Exception):
                        self._record_action(
                            "action.llm_decide",
                            "program_final_echo",
                            f"round={rounds}; retry={_program_final_echo_retries}",
                        )
                    if _program_final_echo_retries < 1:
                        self._tool_cycle._reachability_finalize("program_final_echo_retry")
                        _program_final_echo_retries += 1
                        final_answer = ""
                        resp = None
                        continue
                    self._tool_cycle._reachability_finalize("program_final_echo_error")
                    _run_end_reason = "llm_error"
                    final_answer = "[LLM 输出异常] 模型连续返回内部协议标记，未获得正常最终回答。"
                    resp = None
                    break
                # 模型已经选择正常 final 时，程序不得强制其读取 child 结果或重开一轮。
                # 但仍在运行的异步 child 是机械副作用资源：在 parent final 前取消并收束，
                # 防止用户已收到最终答复后后台继续产生新副作用。terminal-but-unread
                # child result 不属于 completion gate，模型可自行决定是否读取。
                try:
                    _async_pending = self.registry.async_obligations(session_id)
                except Exception:  # noqa: BLE001 — registry 已 fail-open，此处再兜底
                    _async_pending = []
                if _async_pending:
                    with contextlib.suppress(Exception):
                        self._record_action(
                            "async.obligation",
                            "cancelled_on_model_final",
                            f"count={len(_async_pending)}; ids="
                            + ",".join(str(row.get("id", "")) for row in _async_pending)
                            + "; prompt_chars=0",
                        )
                    with contextlib.suppress(Exception):
                        self.registry.cancel_session(session_id)
                self._tool_cycle._reachability_finalize("completed_no_tools")
                self._kpi_note_no_tool()
                self._phase("honest_answer")
                # H-UI: 进入回答生成
                self._notify_action("answer")
                # M41 修复: 回答被截断（truncated=True）时不执行声明-回执校验——
                # 不完整内容校验不可靠（会误报"声明与回执不符"），截断如实透传标注
                if resp.truncated:
                    truncation_noted = True
                # ── 声明-回执轻量提醒（T38: 诚实性交 AI 自主，程序仅提供事实提醒，不强制更正重入）──
                if final_answer.strip() and not resp.truncated:
                    tool_msgs = [m for m in sess.messages if m.role == "tool"]
                    if self.validator:
                        # advisory 层异常不得拖垮已产出的最终回答（fail-open，
                        # 同 user_ingress_guard 惯用法）：崩溃时如实留痕
                        # （warning 日志 + action trace），跳过不一致提醒。
                        try:
                            check = self.validator.check(final_answer, tool_msgs)
                        except Exception as exc:  # noqa: BLE001 — 校验不可用≠回答无效
                            logger.warning(
                                "declaration validator.check 异常（fail-open，跳过提醒）",
                                exc_info=True,
                            )
                            with contextlib.suppress(Exception):
                                self._record_action(
                                    "declaration.check",
                                    "validator_error",
                                    repr(exc)[:200],
                                )
                            check = None
                        if check is not None and not check.consistent:
                            verification_note = build_discrepancy_feedback(check)
                            # R8.9: this check runs after the model has already produced
                            # its final answer, so a prompt message cannot repair that answer.
                            # Keep the discrepancy in LoopResult/UI + action telemetry only;
                            # do not create future conversational authority.
                            with contextlib.suppress(Exception):
                                self._record_action(
                                    "declaration.check",
                                    "discrepancy",
                                    verification_note[:200],
                                )
                break

            # ── 行动：执行工具（tool_calls）──
            # M53 拆分: 工具段 → _ToolExecMixin._execute_tools（yield from 保持 tool_round 外泄次序）
            yield from self._tool_cycle._execute_tools(resp, sess, rounds, tool_trace)

            # ── R10 → R8.24-B B-2.1（B-D6）: 轮数预警注入路径删除（E18 分量）──
            # 模型可见面零预警（B-G8）；剩余轮数事实只落观测事件。"继续/调大/收尾"
            # 决策不再询问模型——到达硬限后直接结束（见下方 exhaustion 段）。
            _budget = self._runtime_max_iterations()
            if (
                not self._run_state().round_warning_injected
                and _budget >= 10
                and rounds >= int(_budget * 0.8)
            ):
                self._run_state().round_warning_injected = True
                self._record_action(
                    "round.warning",
                    "suppressed",
                    f"{rounds}/{_budget}; prompt_chars=0",
                )

            # Context pressure is runtime observability, not a model instruction.
            # The old injected_system Message was always removed by provider projection;
            # keep one-shot telemetry without polluting durable session history.
            _bd = self._run_state().last_breakdown
            _ratio = (_bd or {}).get("ratio")
            if (
                not self._run_state().context_warning_injected
                and _ratio is not None
                and _ratio >= 0.8
            ):
                self._run_state().context_warning_injected = True
                _used = (_bd or {}).get("total", {}).get("chars", 0)
                _budget_chars = (_bd or {}).get("budget", 0)
                _pct = round(_ratio * 100)
                self._record_action(
                    "context.warning",
                    "observed_only",
                    f"{_pct}%;used={_used};budget={_budget_chars};prompt_chars=0",
                )

            # ── 轮数上限（R8.24-B B-2.1/B-D6: 硬边界直接结束）──
            # 删除 N+1 决策轮（不再花一轮 LLM 调用问模型"是否继续"——P0-6：
            # 到边界就停，等用户）。第 N+1 轮 LLM call=0（B-G4）；终态以 run 终态
            # 元数据 + UI"用户可继续"提示呈现（衔接 E 包 task_active 授权恢复）。
            # LFL_E18_HARD_STOP=0 时终态去掉"可继续"提示行（纯事实），硬停行为不变；
            # 回滚整体语义靠 git revert（enforce 态落地——静态断言要求注入路径
            # 无生产调用点，开关不再保留旧注入行为）。
            if rounds >= _budget:
                self._phase("terminate.max_iterations")
                _run_end_reason = "max_iterations"
                final_answer = max_iterations_feedback([t["name"] for t in tool_trace]).content
                if os.environ.get("LFL_E18_HARD_STOP", "1") == "1":
                    final_answer += (
                        '\n（已达轮数硬边界，run 已结束；发送"继续"可开新 run 接续任务。）'
                    )
                break
        # B5-W4-01: 收尾段归装 RunFinalizer.persist_and_settle（A/B 段拆分 + AST 反替自证；
        # LoopResult 组装留 engine——run_finalizer 不持 engine 运行时回边，沿 engine<->build
        # 断环先例保持 runtime 环空态锚定）
        # Structured concurrency abnormal-exit rule: parent 不是正常 completed 时，
        # 未结算 background children 不能继续产生副作用。session-level cancel hook
        # 会级联 child/descendants；正常 completed 已由上面的 obligation gate 保证结算。
        if _run_end_reason != "completed":
            with contextlib.suppress(Exception):
                self.registry.cancel_session(session_id)

        final_answer, _run_end_reason = self._run_finalizer.persist_and_settle(
            sess=sess,
            session_id=session_id,
            final_answer=final_answer,
            _run_end_reason=_run_end_reason,
            _cancel_reason=_cancel_reason,
            resp=resp,
            rounds=rounds,
            tool_trace=tool_trace,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_cache_hit=tokens_cache_hit,
            llm_ms_total=llm_ms_total,
            ttft_first_ms=ttft_first_ms,
            model_used=model_used,
            truncation_noted=truncation_noted,
            verification_note=verification_note,
            _run_started_at=_run_started_at,
        )
        return LoopResult(
            session_id=session_id,
            final_answer=final_answer,
            verification_note=verification_note,
            rounds=rounds,
            tool_calls=tool_trace,
            truncated=truncation_noted,
            model_used=model_used,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_cache_hit=tokens_cache_hit,
            reasoning_content=resp.reasoning_content if resp is not None else None,
            reasoning_mode=reasoning_mode_used,
            reasoning_capable=reasoning_capable,
            reasoning_control=reasoning_control,
            reasoning_supported=reasoning_supported,
            reasoning_effective=reasoning_effective,
            reasoning_tokens=reasoning_tokens,
            cancel_reason=_cancel_reason,
            fallback_receipt=self._run_state().fallback_receipt,
        )

    def _project_request_tools(
        self,
        *,
        session_id: str,
        user_text: str,
        planned_label: str,
        session_messages: list[Message],
        advance_state_round: bool = True,
        logical_round: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Build the stable owner tool surface, then apply mechanical runtime health."""
        # P1-B: provider schema representation may be compact/lazy, but user text
        # never chooses which tools receive callable parameter schemas.
        schemas = self.registry.schemas(lazy=self.settings.tool_schema_lazy)
        projected = self._tool_cycle._project_tool_schemas_for_round(
            schemas,
            planned_label=planned_label,
            user_text=user_text,
            session_messages=session_messages,
            advance_state_round=advance_state_round,
            logical_round=logical_round,
        )
        tools = [self._tool_cycle._schema_to_param(schema) for schema in projected]
        # Cache stability must include the exact tool array/order actually offered
        # to this attempt. This is observational only; it never changes which tools
        # are eligible or callable.
        self._run_state().cache_gate_tools_fp = stable_digest(tools)
        return projected, tools

    # 生命周期/持久化职责面已迁 SessionLifecycle（B5-W2-01）；编排入口留 lifecycle.py（_RunEntrypointMixin）。

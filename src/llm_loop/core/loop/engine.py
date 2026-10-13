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
import contextvars
import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
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
from llm_loop.core.loop.engine_services.interjection_consume import (
    _consume_live_interjections,
)
from llm_loop.core.loop.engine_services.interop import InteropService
from llm_loop.core.loop.engine_services.interrupted_capture import InterruptedCapture
from llm_loop.core.loop.engine_services.nonconvergence_guard import (
    NonconvergenceFuseError,
)
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
from llm_loop.core.loop.method_learning import (
    MethodLearningService,  # Method Learning v1：usage 遥测 + post-run reflection（组合，R9-P5-01）
)
from llm_loop.core.loop.runstate import _RunState
from llm_loop.core.loop.tool_exec import (
    _json_dumps_args,
    _tool_args_summary,  # noqa: F401 — M53 拆分 re-export（原路径可导入，REQ-REF-06）
)
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.prompt_eligibility import LEGACY_PROGRAM_FINAL_MARKER
from llm_loop.core.recent_continuity import attach_recent_continuity_anchor
from llm_loop.core.reference_injection import is_active_run_ingress_message
from llm_loop.core.run_context import current_reasoning_effort as _current_reasoning_effort
from llm_loop.core.run_context import current_reasoning_mode as _current_reasoning_mode
from llm_loop.core.run_context import current_round_no
from llm_loop.core.session import SessionStore, first_human_ingress_channel
from llm_loop.core.trace_leak import leak_events
from llm_loop.core.trace_leak.invariant import (
    correct_mislabeled_metadata,
    metadata_satisfies_invariant,
)
from llm_loop.feedback.honesty import max_iterations_feedback
from llm_loop.feedback.validator import DeclarationValidator, build_discrepancy_feedback
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.status import ArchitectureStatusProvider
from llm_loop.llm.client import (
    GuardRequestContext,
    LLMClient,
    LLMResponse,
    StreamDelta,
    provider_structure_violations,
)
from llm_loop.llm.errors import LLMError, LLMProjectionError, LLMRequestTooLargeError
from llm_loop.llm.pool import ModelClientPool
from llm_loop.memory.store import MemoryStore
from llm_loop.resources.contracts import ExecutionClass, ServicePriority
from llm_loop.resources.provider_calls import (
    foreground_task_provider_chat,
    foreground_task_provider_stream,
)
from llm_loop.resources.provider_settlement import (
    ProviderAttemptKind,
    ProviderCallOutcome,
    ProviderCallPurpose,
)
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError
from llm_loop.runtime.causality import (
    background_run_generation_fact,
    build_run_integrity_receipt,
    effective_generation_contract,
    provider_message_shape,
)
from llm_loop.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_CANCELLED_ANSWER = "（已停止——用户点击停止按钮，本轮回答终止）"

# Phase5 M2（设计 §2.2.1/§2.3）：LLM 流内插话检查点节流间隔。
# 开关经 settings.tool_runtime.llm_stream_interject_checkpoint（config.py 集中
# 装配 LLM_STREAM_INTERJECT_CHECKPOINT，缺省开）——关闭即回退保守 final_gate
# 路径（流内不检查插话，等流自然结束），配置级回滚无需改代码。
_STREAM_INTERJECT_CHECK_MIN_GAP_S = 0.04  # 每 delta peek 会持 mailbox 锁，节流

# Phase6 M1：同步 chat 通道轮询间隔（worker 线程承载 provider 调用，run 线程轮询
# Stop/插话检查点）。0.04s 与流式通道检查节流对齐；t_effect 上界 ≈ 该间隔 + 调度。
_SYNC_INTERJECT_POLL_GAP_S = 0.04


def _interjection_peek(
    engine: Any,
    session_id: str,
    *,
    warned: list[bool] | None = None,
    where: str = "sync_window",
) -> bool:
    """插话到达探视（§4.4 保守降级：peek 失败不收割）。

    同步窗口轮询（Phase6 M1）与流式检查点（遗留处置 L1）共用；
    与 tool_cycle 的 gap peek 同契约：peek 管道故障时视为无插话
    （不收割、不冒泡），收割兜底交给轮首/gap/final_gate 既有边界。
    观测：per-window 至多一条 warning（warned 为同窗口共享的一次性旗标；
    40ms 轮询频率下逐次 warning 会刷屏，静默 debug 又会掩盖持续降级）。
    where 标注调用通道（sync_window / llm_stream），供分桶诊断。
    """
    try:
        runner = getattr(engine, "runner", None)
        if runner is None or not getattr(runner, "enabled", False):
            return False
        return bool(runner.interjections_pending(session_id))
    except Exception:  # noqa: BLE001 - peek 失败不收割（fail-open）
        if warned is not None and not warned:
            warned.append(True)
            logger.warning(
                "interjection peek failed (channel=%s, fail-open, no harvest; once per window)",
                where,
                exc_info=True,
            )
        else:
            logger.debug("interjection peek failed (channel=%s)", where, exc_info=True)
        return False


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


def _fire_interject_applied(
    engine: Any, detail: str, *, also_cbf: bool = False, fire_applied: bool = True
) -> int:
    """G1 applied/CBF 回执触发点（Phase3 §7.1 机械判据）.

    调用点：首个工具派发（tool_dispatched_round=N）、终答出口
    （final_answer_after_interjection）、终答结算边界（also_cbf=True 且
    fire_applied=False——拦截只兑现 cbf，applied 留给续跑轮真实出口）。
    回执失败一律 fail-open（不变量 6）；detail 不含插话正文（D6）。
    取消路径不触发——未被决策采用即不标 applied（诚实优先）。
    """
    fired = 0
    try:
        rs = engine._run_state()
    except Exception:  # noqa: BLE001 — 无活跃 run 状态时静默放弃回执
        return 0
    if fire_applied:
        targets, rs.interject_applied_callbacks = rs.interject_applied_callbacks, []
    else:
        targets = []
    for ent in targets:
        cb = ent.get("cb")
        qid = str(ent.get("queue_id") or "")
        if callable(cb):
            try:
                cb(detail)
                fired += 1
            except Exception:  # noqa: BLE001
                logger.warning("interjection applied-receipt failed (fail-open)", exc_info=True)
        with contextlib.suppress(Exception):
            engine._record_action(
                "human.interjection", "applied", f"queue_id={qid}; {detail}"
            )
    if also_cbf:
        cbs, rs.interject_cbf_pending = rs.interject_cbf_pending, []
        for ent in cbs:
            cb = ent.get("cb")
            qid = str(ent.get("queue_id") or "")
            if callable(cb):
                try:
                    cb(detail)
                except Exception:  # noqa: BLE001
                    logger.warning("interjection cbf-receipt failed (fail-open)", exc_info=True)
            with contextlib.suppress(Exception):
                engine._record_action(
                    "human.interjection", "continued_before_final", f"queue_id={qid}"
                )
    return fired


# M53 拆分: _json_dumps_args/_tool_args_summary → llm_loop/core/loop/tool_exec.py（_ToolExecMixin）
# 迁移注释保留（REQ-REF-06）: 原路径可导入（对齐 test_tool_round_visible.py），行为与迁移前一致。
# 模块级函数随工具执行职责单元迁移，经此 re-export 保持 `engine._tool_args_summary` 等可导入。


def _settlement_join_ids_for_usage(
    call: Any, coordinator: Any
) -> tuple[str, str]:
    """P0-2 B3 (GAP-REQ-2): settlement join keys for a request.usage row.

    Module-level helper so the giant round loop adds zero branch complexity:
    ``provider_call_id`` names the logical shadow call, ``provider_attempt_id``
    the latest transport attempt the settlement journal recorded for it.
    request.meta is emitted before the physical send, so the attempt-level key
    can only be honest here (post-response). "" means no binding this round —
    never invented, never dropped from the payload.
    """
    try:
        call_id = str(getattr(call, "call_id", "") or "")
        attempt_id = str(coordinator.last_provider_attempt_id(call) or "") if (
            call is not None and coordinator is not None
        ) else ""
        return call_id, attempt_id
    except Exception:
        return "", ""


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
    history_compacted: bool = False
    provider_output_truncated: bool = False
    run_incomplete: bool = False
    projection_validator_failed: bool = False
    projection_rebuilt: bool = False
    projection_cannot_fit: bool = False
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

    def _phase4_interrupt_gate(self, session_id: str, tool_name: str) -> bool:
        """Phase4 CK-B 打断判定（§4.2 固定序；§4.4 全链保守降级）.

        注册表分段等待（τ 片）在引擎工作线程内逐片调用；判定顺序固定：
        1) stop 链优先：背景取消原因非空 → False（检查点放弃，停止通道接管）；
        2) mailbox 真值 peek（CK-A interjections_pending，不引入内存标志）；
        3) 工具 ∈ 可中断闭集（registry.INTERRUPTIBLE_TOOLS，不解释）；
        4) 无未结算 revocable=False 副作用登记（SideEffectRegistry 四态快照，
           查询失败 → 保守 False）。
        任何异常 → False（不打断；退化为自然完成/超时路径）。
        """
        try:
            if _background_cancel_reason(self, session_id):
                return False
            runner = getattr(self, "runner", None)
            if runner is None or not getattr(runner, "enabled", False):
                return False
            if not runner.interjections_pending(session_id):
                return False
            if tool_name not in getattr(
                self.registry, "INTERRUPTIBLE_TOOLS", frozenset()
            ):
                return False
            try:
                from llm_loop.core.loop.side_effects import SideEffectRegistry

                # §4.2 CK-B④（审查 P1-2）：副作用面限定当前 run_generation——
                # 跨 run 陈旧未结算项不静默阻断打断；无代次（老数据/直跑）按
                # 会话全量保守。
                cur_gen = (
                    (runner.get_handle(session_id) or {}).get("run_generation") or ""
                )
                for it in SideEffectRegistry.instance().snapshot(session_id):
                    if not it.get("revocable") and not it.get("settled_at"):
                        it_gen = it.get("run_generation") or ""
                        if not cur_gen or not it_gen or it_gen == cur_gen:
                            return False
            except Exception:  # noqa: BLE001 — 副作用面查询失败保守
                return False
            return True
        except Exception:  # noqa: BLE001 — §4.4 判定失败保守
            return False

    def _run_state(self) -> _RunState:
        """当前会话状态桶（B5-W4-03：解析逻辑在 RunStateManager.bucket，薄委托）."""
        return self._run_state_mgr.bucket()

    runner: Any | None = None
    # DSH-PLUGINS-20260816 ②: 调度提醒线程（factory 装配；声明类型供 pyright 静态检查）
    scheduler: Any | None = None
    # 子代理 runner（factory 装配；Web 谱系面读 topology 机械事实，缺省 None 不伪造）
    subagent_runner: Any | None = None
    # EVO-20260919-f119847d: factory 装配的 wake grant 重铸钩子（lifecycle 以 getattr
    # 消费，缺省 None 即无钩子；钩子自身异常 fail-open，绝不阻断真人 run）。
    rearm_wake_grants: Callable[[str, object], None] | None = None
    # Human-AI Continuity P3: optional mechanical file collaboration/query services.
    # They are transport/fact handles only; the model run loop never consumes them implicitly.
    file_effect_query: Any | None = None
    human_file_operations: Any | None = None
    # Learning Plane（design §5.3）: factory 动态装配 durable journal + ReflectionRun 消费者；
    # 默认关闭时保持 None —— post_run 反射静默，零行为变化。
    learning_journal: Any | None = None
    learning_plane: Any | None = None
    # RG-1: shared mechanical lease/concurrency governor.
    resource_governor: Any | None = None
    # RG-2: qualified provider-call coordinator; never chooses a model or task.
    provider_call_coordinator: Any | None = None
    provider_call_settlement_journal: Any | None = None
    # RG-3D: rebuildable cross-session settlement projection; shadow facts only.
    provider_settlement_projection_index: Any | None = None
    # ERR1210 per-engine/session attempt ledger; actual lifecycle owned by RecoveryController.
    _err1210_attempted: dict[str, int]
    # ERC Phase6: optional workspace-activation legacy sidecar migration hook.
    _evidence_legacy_migrate_workspace_fn: Callable[[str], object] | None = None
    _runtime_causal_snapshot: Any | None = None

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
        # Phase4 M2 CK-B（§4.2）：在途打断判定钩子装配（stop 链优先 + mailbox
        # peek 真值 + 闭集 + 副作用面；gate 内自含 §4.4 保守降级）。
        try:
            registry.set_interrupt_gate(self._phase4_interrupt_gate)
        except Exception:  # noqa: BLE001 — 装配失败 = 无打断通道（零回归）
            logger.warning("phase4 interrupt gate 装配失败（无打断通道）", exc_info=True)
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
            correction_ctx.current_episode_ref_resolver = self._resolve_current_episode_ref
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
        # Set only at Web bootstrap after an administrator's one-Run config
        # is verified. Alternate ingress paths for that exact session must
        # not bypass the durable CAS simply by omitting a Web request scope.
        self._task_budget_restricted_session_id: str | None = None
        # Mechanical post-tool-receipt hook; factory binds SubAgent settlement only.
        self._tool_receipt_committed_hook: Callable[[str, Message], object] | None = None
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
        self._method_learning = MethodLearningService(self)  # v1: 组合持有（不走继承）
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

        self._cache_monitor = CacheHealthMonitor(
            breaker_audit_file=Path(settings.data_dir).resolve() / "audit" / "cache_breaker.jsonl"
        )
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

    def _runtime_reasoning_effort(self) -> str | None:
        return self._runtime_params._runtime_reasoning_effort()

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
        provider_call=None,
        site_index_offset=1,
        active_run_ingress_ref="",
        active_run_ingress_kind="none",
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
            provider_call=provider_call,
            site_index_offset=site_index_offset,
            active_run_ingress_ref=active_run_ingress_ref,
            active_run_ingress_kind=active_run_ingress_kind,
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

    # R2（antidrift_impl 批1）: 收敛回执队列压力 probe——装配期可选注入（web 生产
    # 装配注册；缺省 None=CLI/feishu 装配，回执段如实 unavailable(no_queue_binding)）。
    # tool_cycle 经 getattr duck-typing 读取，无注入即零行为差异。
    interjection_pressure_probe: Callable[[str], dict | None] | None = None
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
        user_metadata: dict[str, Any] | None = None,
        on_human_event_appended: Any = None,
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
        # Phase3 G1 审查 P1-1：run 入口清空插话回执桶（per-session 桶字段跨 run
        # 保留——上一 run 残留回调若不清，会在下一 run 的首个工具派发点被误触发，
        # 把未被本 run 决策采用的插话误标 applied）。与 fallback_receipt 同款纪律。
        _bucket.interject_applied_callbacks = []
        _bucket.interject_cbf_pending = []
        self._routing._begin_run_routing_epoch()
        _bucket.stagnation_state = {
            "fp": None,
            "count": 0,
            "reminded": False,
            "empty_count": 0,
            "empty_reminded": False,
        }
        _bucket.convergence_boundary_pending = False
        _bucket.convergence_boundary_evidence = {}
        _bucket.interruption_resume = (
            None  # rebuilt from durable interruption/checkpoint facts after ingress append
        )
        _bucket.ingress_pressure_compact_count = 0
        _bucket.ingress_pressure_facts = {}
        _bucket.ingress_history_budget_cap = None
        _bucket.longrun_read_cache = {}
        _bucket.longrun_continuity_manifest = None
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
        # Adjacent overflow handoff is durable provider-invisible metadata on the prior
        # program-final placeholder.  Restore only mechanical read/frontier facts; the
        # new human ingress remains the sole active instruction authority.
        try:
            from llm_loop.core.longrun_continuity import (
                previous_overflow_manifest,
                restore_read_cache,
            )

            _longrun_manifest = previous_overflow_manifest(sess.messages)
            if _longrun_manifest is not None:
                _bucket.longrun_continuity_manifest = _longrun_manifest
                _bucket.longrun_read_cache = restore_read_cache(_longrun_manifest)
                self._record_action(
                    "run.longrun_continuity",
                    "restored",
                    f"read_anchors={len(_bucket.longrun_read_cache)}",
                )
        except Exception:  # noqa: BLE001 — continuity optimization must not block ingress
            logger.warning("longrun continuity restore failed (fail-open)", exc_info=True)

        # Read-only correction/introspection compatibility may still expose the most
        # recent session on CorrectionContext.  Tool mutation ownership itself is
        # ContextVar-bound and must not maintain a registry-level last-session fallback.
        if self.correction_ctx is not None:
            self.correction_ctx.session_id = session_id
            # P0-5/P6: model mutation authority is the per-session binding resolver below.
            # Do not refresh shared session_model_override/session_set_override here;
            # explicit CLI/Feishu control-plane commands bind their concrete Session
            # independently, while model-facing registry_model must use this exact map.
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
                backfill_completed_delegated_spans,
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
                backfill_completed_delegated_spans(self.episode_store, sess)
                backfill_closed_tool_attempts(
                    self.episode_store, sess, event_store=self._event_store
                )
        except Exception:  # noqa: BLE001 — retrieval indexing must not block a run
            logger.warning("history lifecycle 索引失败（fail-open，不退休）", exc_info=True)

        # ── 消息进：构造用户消息并落库 ──
        _user_metadata: dict[str, Any] = {}
        raw_attachments = (user_metadata or {}).get("attachments")
        if isinstance(raw_attachments, list):
            _user_metadata["attachments"] = [
                dict(item) for item in raw_attachments if isinstance(item, dict)
            ]
        raw_queue_id = (user_metadata or {}).get("human_turn_queue_id")
        if isinstance(raw_queue_id, str) and 0 < len(raw_queue_id) <= 128:
            # Mechanical provenance only. It is persisted in Message/Event metadata and is
            # never rendered into provider-visible message content or tool schemas.
            _user_metadata["human_turn_queue_id"] = raw_queue_id
        raw_source_id = (user_metadata or {}).get("human_turn_source_id")
        if isinstance(raw_source_id, str) and 0 < len(raw_source_id) <= 256:
            # Transport identity only (e.g. Feishu message_id).  It is never rendered into
            # provider-visible prose; append-only retraction uses it as an exact target key.
            _user_metadata["human_turn_source_id"] = raw_source_id
        # Provenance/ingress are program-owned truth; arbitrary caller metadata never enters a
        # genuine human message through this transport-only extension.
        _user_metadata.update(origin_metadata(InjectionLayer.USER_INSTRUCTION))
        user_msg = Message(
            role="user",
            content=user_text,
            source=MessageSource.USER,
            metadata=_user_metadata,
        )
        # agent_trace_leak 3.5: user_instruction 判定双因子收口（凭据 + 白名单；
        # 合法凭据路径落盘字节零变化——metadata 仅固化 ingress 通道快照两键）。
        # guard 异常 fail-open 放行 + leak.guard_fault 告警（spec 4.2-1）。
        try:
            from llm_loop.core.trace_leak.user_ingress_guard import (
                GuardAction,
                guard_user_write,
            )

            _verdict = guard_user_write(
                sess, user_msg, ingress, entry="engine.run", data_dir=self.settings.data_dir
            )
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
        # EVO-20260924-8266b693 B：会话开场（首个 genuine human turn）注入
        # "failed 服务控制动作待确认"状态提醒一次。每 session 只此一次、
        # fail-open、STATUS 层非祈使；提醒位于用户原文之前（L2 尾位不变量：
        # 程序生成 user-role 内容不追加在本轮真实用户原文之后）。
        # 被新代接管（superseded）的 failed 不抹除，直到 verify_acknowledge(accept) 确认。
        # 背景：2026-09-24 restart failed 只落私有台账，下一会话（含发起模型自身）
        # 无可见反馈通道。判定必须发生在 user_msg 落库之前——否则首 turn
        # 恒不触发（user_instruction 已存在）。
        try:
            if not any(
                (m.metadata or {}).get("origin_layer") == "user_instruction"
                for m in sess.messages
                if m.role == "user"
            ):
                from llm_loop.core.loop.engine_services.service_action_notice import (
                    build_failed_action_notice_message,
                )

                _svc_notice = build_failed_action_notice_message(self.settings.data_dir)
                if _svc_notice is not None:
                    sess.messages.append(_svc_notice)
                    self._append_message_event(sess, _svc_notice)
        except Exception:  # noqa: BLE001 — 开场提醒 fail-open
            logger.warning("service_action_notice 开场注入失败（fail-open 跳过）", exc_info=True)
        # EVO-20260924-62221fd4：轮级注入——每个 human turn 检查**新出现**的未确认
        # failed 服务控制动作（开场注入之后的增量）。异步拒绝/终止从"下次碰巧
        # 查到"变成"下一轮必然看到"。幂等：同一 action_id 本会话只注入一次
        # （开场卡与轮卡共用 metadata.service_action_ids 去重）；闭合即停
        # （verify_acknowledge 后扫描不再返回）；提示非指令——被注入不等于
        # 必须 verify_acknowledge，语义保持"待确认待消费"；fail-open。
        try:
            from llm_loop.core.loop.engine_services.service_action_notice import (
                build_failed_action_turn_notice,
                injected_turn_action_ids,
            )

            _turn_notice = build_failed_action_turn_notice(
                self.settings.data_dir,
                injected_turn_action_ids(sess.messages),
            )
            if _turn_notice is not None:
                sess.messages.append(_turn_notice)
                self._append_message_event(sess, _turn_notice)
        except Exception:  # noqa: BLE001 — 轮级提醒 fail-open
            logger.warning("service_action_turn_notice 注入失败（fail-open 跳过）", exc_info=True)
        sess.messages.append(user_msg)
        # Persist the already-eligible recent answer's exact identity before dispatch.
        # A crash with no output must not turn this ingress into an accidental barrier
        # on restart. Only runtime metadata is added; historical authority is unchanged.
        attach_recent_continuity_anchor(sess.messages, len(sess.messages) - 1)
        # D1: 会话首次落库生成 session.created + 用户消息事件（fail-open）
        self._ensure_session_created(sess)
        _user_event = self._append_message_event(
            sess, user_msg, require_durable=on_human_event_appended is not None,
        )
        # I5-E: the signed authority must name this *actual* persisted user
        # message event_id/seq. The optional operator callback is strictly
        # after EventStore append and before even one model/tool side effect.
        # No production Web route installs the callback; absent it, no change.
        if on_human_event_appended is not None:
            if _user_event is None:
                raise TaskBudgetDeniedError("operator_human_event_not_persisted")
            on_human_event_appended(_user_event)
        if raw_queue_id:
            # A queued human turn is replay-sensitive: after a dispatcher/process crash the
            # queue may re-dispatch only when it can prove this ingress never started. Make
            # EventStore the single durable execution boundary; without the exact ingress
            # event no LLM/tool side effect is allowed to begin. Ordinary human turns keep
            # the repository's historical fail-open event behavior.
            _event_store = getattr(self, "_event_store", None)
            if (
                _event_store is None
                or getattr(_event_store, "enabled", False) is False
                or _user_event is None
            ):
                # The exact queued ingress did not become durable, so restore the in-memory
                # Session snapshot before unwinding; the dispatcher may safely retry later.
                if sess.messages and sess.messages[-1] is user_msg:
                    sess.messages.pop()
                from llm_loop.core.loop.runner import QueuedIngressDurabilityError

                raise QueuedIngressDurabilityError(
                    "queued human turn ingress durability unavailable; run not started"
                )
        self._prepare_interruption_resume(session_id, sess)
        _turn_ref = len(sess.messages) - 1  # user_msg seq（turn 身份）
        # T5: per-session RunState 分桶（串台修复）；tip 判断改 SoT 派生（tool_exec）
        self._run_state().current_turn_ref = _turn_ref
        # antidrift R3: run 入口冻结 ingress 消息对象（压缩豁免退化路径第二候选身份源）
        self._run_state().active_run_ingress_message = sess.messages[_turn_ref]
        # EVO-20260923-618f7fd1 ③（2026-09-24 退役）: 会话开场 active 方法卡清单注入。
        # 实测干扰（弱本地模型对照实验，同模型 cognilocal/qwen3.8-flash-next 同一
        # 身份问答）：无附录会话按证据路径调 model_catalog 正确自报路由；有附录会话
        # （6aec21cb）被带偏为"身份问题凭原生知识直答、不调工具"，凭空自称
        # DeepSeek-V4；对照组（f66027f9）行为正确。无条件正文投喂同时违背 L2-2
        # （retrievable != injectable）。方法可见性保留在 search_records(kind=method)
        # 的 schema 入口；方法 use 回记提醒（状态层，仅在本 run 已精确水合时触发）
        # 不受影响，见 method_injection.py。
        # Agency-first: memory/history is retrieved explicitly by the model when needed.
        # Ordinary user turns do not trigger automatic retrieval or persisted snapshots.
        _turn_memory_msgs: list[Message] = []
        # （EVO-20260924-8266b693 B 开场注入已上移至 user_msg 落库之前——
        # 见上方注入块；此处保留占位注释防回插到错误位置。）
        self._phase("ingress")

        final_answer = ""
        verification_note: str | None = None
        history_compacted_noted = False
        provider_output_truncated = False
        projection_validator_failed = False
        projection_rebuilt_noted = False
        projection_cannot_fit_noted = False
        _projection_rebuild_requested = False
        _projection_rebuild_round = -1
        rounds = 0
        # DSH 借鉴(2026-08-17): run 结束原因（统一出口 run.end 事件用；各结束分支标记，
        # 默认 completed——未标记即正常完成。fail-open 不阻断）
        _run_end_reason = "completed"
        _cancel_reason = (
            ""  # 取消原因标记位（user_stop/runner_stop；""=未取消，收口贯穿 LoopResult）
        )
        _run_started_at = time.monotonic()
        # R2（antidrift_impl 批1）: 收敛回执事实面 run 级重置（OQ3 复活即重置；
        # stagnation_state「run 开始重置」同款纪律）
        _vitals_bucket = self._run_state()
        _vitals_bucket.convergence_history = []
        _vitals_bucket.vitals_rounds = 0
        _vitals_bucket.vitals_tokens_in = 0
        _vitals_bucket.vitals_tokens_out = 0
        _vitals_bucket.vitals_started_monotonic = _run_started_at
        self._termination._reset_overflow_state()  # R4: 每次 run 重置 overflow 注入计数
        self._recovery._err1210_run_begin()  # 修复A: per-run 降级机会（attempted 键 = run seq）
        self._last_interrupted = (
            None  # B1/B2(EVO-20260902-41898b20): 本 run 中断半截产物缓存（新 run 重置防陈旧串台）
        )
        model_used = ""  # M51: 本轮实际使用的模型标签（每轮 LLM 调用时刷新）
        _model_route_source = "unknown"
        _model_route_authority = "none"
        _run_effort_baseline = None  # EVO-20260923-5342bf75: 首轮捕获的启动档（reset 回滚用）
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
        # EVO-20260923-618f7fd1 ①: 收尾 use 回记提醒，每 run 至多触发一次（不阻塞）
        _method_use_reminder_fired = False

        while True:
            # 后台 Stop：轮次边界兜底；LLM 流内另有细粒度检查（原因捕获，2.3）。
            _cancel_reason = _background_cancel_reason(self, session_id)
            if _cancel_reason:
                _run_end_reason = "cancelled"
                final_answer = _CANCELLED_ANSWER
                break
            _interjected = _consume_live_interjections(self, session_id, sess)
            # Phase4 M1 间隙收割（§4.2）：序列间隙消费点已收割的文本在此合并进
            # user_text 辅助视图（单读单清；与轮首消费同口径，不改写原始入语）。
            with contextlib.suppress(Exception):
                _harvest_bucket = self._run_state().interject_harvest_user_texts
                if _harvest_bucket:
                    _interjected = [*_harvest_bucket, *_interjected]
                    _harvest_bucket.clear()
            if _interjected:
                # user_text is used by model-visible tool projection/routing in addition to
                # Session history. Keep that auxiliary view aligned with the newest genuine
                # human steer without rewriting the original run ingress.
                _nonempty_interjected = [row for row in _interjected if row.strip()]
                if _nonempty_interjected:
                    user_text = "\n\n".join(_nonempty_interjected)
            # Phase5 M2（P2-5，设计 §2.2.4 修订，见 §10）：复位置于轮内消费点
            # **之后**——消费点读上一轮工具打断置位（interruptible 桶口径，
            # Phase4 M3 S13 形态）必须保留；复位只消除其后（本轮 LLM 流、
            # final_gate、下一 run）读到的跨轮/跨 run 残值。
            self._run_state().last_receipt_interrupted = False
            rounds += 1
            _projection_mandatory_only = False
            # CR-R1.1（审查项7）: 轮次入 contextvar——cognitive telemetry 等 build 期
            # 组件归因 round 用（此前 packet_compile 的 round 恒 0）
            with contextlib.suppress(Exception):

                current_round_no.set(rounds)
            _background_note_active(self, session_id, rounds)
            if self.runtime is not None:
                self.runtime.reset_round()
            # EVO-20260923-5342bf75: 显式调整过的推理档位每轮应用——client 每请求读
            # current_reasoning_effort，engine 在轮首把动态值压入 contextvar；动态档被
            # reset 清除时恢复首轮捕获的启动档（防上轮 set 值滞留）；run 结束由
            # lifecycle 的 effort token 再兜底恢复（不跨 run 泄漏）。
            if rounds == 1 and _run_effort_baseline is None:
                _run_effort_baseline = _current_reasoning_effort.get()
            _runtime_effort = self._runtime_reasoning_effort()
            if _runtime_effort is not None:
                _current_reasoning_effort.set(_runtime_effort)
            elif _run_effort_baseline is not None:
                _current_reasoning_effort.set(_run_effort_baseline)
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
            if model is not None:
                _model_route_source = "per_call"
                _model_route_authority = "request_ephemeral"
            elif sess.model_override:
                _model_route_source = "session_override"
                _model_route_authority = "session_persisted"
            else:
                _model_route_source = "default"
                _model_route_authority = "runtime_default"
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
            _tool_schema_chars = len(_json_dumps_args({"tools": tools_param}))
            _tool_schema_tokens: int | None = None
            _schema_counter = getattr(llm_client, "count_tool_schema_tokens", None)
            if callable(_schema_counter):
                try:
                    _measured_schema_tokens = _schema_counter(tools_param)
                    if (
                        isinstance(_measured_schema_tokens, int)
                        and _measured_schema_tokens >= 0
                    ):
                        _tool_schema_tokens = _measured_schema_tokens
                except Exception:  # noqa: BLE001 — optional tokenizer authority is fail-soft
                    logger.debug("tool-schema token measurement failed; using fallback", exc_info=True)
            _budget_info = dict(self._run_state().last_budget_info or {})
            _pre_tool_budget = effective_budget
            effective_budget = self._routing.reserve_tool_schema_from_history_budget(
                effective_budget,
                _budget_info,
                _tool_schema_chars,
                tool_schema_tokens=_tool_schema_tokens,
            )
            _ingress_budget_cap = self._run_state().ingress_history_budget_cap
            if isinstance(_ingress_budget_cap, int) and _ingress_budget_cap > 0:
                effective_budget = min(effective_budget, _ingress_budget_cap)
                _budget_info["ingress_history_budget_cap"] = _ingress_budget_cap
            _budget_info["pre_tool_history_budget"] = _pre_tool_budget
            _budget_info["tool_schema_reserve_chars"] = _tool_schema_chars
            _budget_info["effective_budget"] = effective_budget
            self._run_state().last_budget_info = _budget_info
            # A final-client rejection has not sent bytes. Re-enter this same
            # logical round using current durable truth, bypassing the projection
            # that failed; never retry a saved provider wire.
            if _projection_rebuild_requested:
                messages = []
                _projection_rebuild_requested = False
            else:
                messages = self._build_llm_messages(
                    sess,
                    _turn_memory_msgs,
                    max_chars=effective_budget,
                    model=model,
                    planned_label=planned_label,
                    registry_snapshot=_planning_registry,
                    logical_round=rounds,
                )
            self._kpi_accumulate_inject()
            if getattr(self, "_last_history_compacted", False):
                history_compacted_noted = True

            # Current run ingress is provider-protocol ownership, not human provenance.
            # Bind the exact persisted turn identity for both genuine-human and explicit
            # delegated ingress without changing either message's provenance.
            _active_run_ingress_ref = ""
            _active_run_ingress_kind = "none"
            _active_turn_ref = self._run_state().current_turn_ref
            if (
                _active_turn_ref is not None
                and 0 <= _active_turn_ref < len(sess.messages)
                and is_active_run_ingress_message(sess.messages[_active_turn_ref])
            ):
                _active_run_ingress_ref = str(_active_turn_ref)
                _active_md = getattr(sess.messages[_active_turn_ref], "metadata", None)
                _active_run_ingress_kind = (
                    "delegated"
                    if isinstance(_active_md, dict)
                    and _active_md.get("ingress_delegated") is True
                    else "human"
                )

            # Ingress-only preflight runs before a provider call identity/transport is
            # opened.  The full validator intentionally remains in LLMClient after its
            # existing provider replay/tool sanitization so repairable legacy tool-pair
            # shapes are not prematurely blocked here.
            if isinstance(llm_client, LLMClient) and _active_run_ingress_ref:
                _preflight_violations = [
                    item
                    for item in provider_structure_violations(
                        messages,
                        expected_active_ingress_ref=_active_run_ingress_ref,
                    )
                    if item.startswith("active_run_ingress_")
                ]
                if _preflight_violations:
                    projection_validator_failed = True
                    self._event_append(
                        session_id,
                        "provider.structure.validated",
                        {
                            "round": rounds,
                            "stage": "pre_transport_ingress",
                            "valid": False,
                            "violations": _preflight_violations,
                            "active_run_ingress_ref": _active_run_ingress_ref,
                            "active_run_ingress_kind": _active_run_ingress_kind,
                        },
                    )
                    _projection_rebuild_round = rounds
                    _rebuild = self._build_conservative_active_run_messages(
                        sess,
                        max_chars=effective_budget,
                        model=model,
                        planned_label=planned_label,
                        logical_round=rounds,
                    )
                    self._event_append(
                        session_id,
                        "provider.projection.rebuild",
                        {
                            "round": rounds,
                            "state": _rebuild.state,
                            "trigger_violations": _preflight_violations,
                            "projected_chars": _rebuild.projected_chars,
                            "budget_chars": _rebuild.budget_chars,
                            "total_groups": _rebuild.total_groups,
                            "retired_groups": _rebuild.retired_groups,
                            "mandatory_only": (
                                _rebuild.state == "rebuilt"
                                and (_rebuild.total_groups - _rebuild.retired_groups)
                                == (1 if _rebuild.total_groups <= 1 else 2)
                            ),
                            "detail": _rebuild.detail,
                            "active_run_ingress_ref": _active_run_ingress_ref,
                            "active_run_ingress_kind": _active_run_ingress_kind,
                        },
                    )
                    if _rebuild.state == "rebuilt":
                        _rebuilt_messages = list(_rebuild.messages)
                        _rebuilt_violations = [
                            item
                            for item in provider_structure_violations(
                                _rebuilt_messages,
                                expected_active_ingress_ref=_active_run_ingress_ref,
                            )
                            if item.startswith("active_run_ingress_")
                        ]
                        if not _rebuilt_violations:
                            messages = _rebuilt_messages
                            projection_rebuilt_noted = True
                            _selected_group_count = (
                                _rebuild.total_groups - _rebuild.retired_groups
                            )
                            _mandatory_group_count = (
                                1 if _rebuild.total_groups <= 1 else 2
                            )
                            _projection_mandatory_only = (
                                _selected_group_count == _mandatory_group_count
                            )
                            self._record_action(
                                "action.llm_decide",
                                "projection_rebuilt",
                                (
                                    f"retired_groups={_rebuild.retired_groups};"
                                    f"chars={_rebuild.projected_chars}/{_rebuild.budget_chars}"
                                ),
                            )
                            _influence = dict(self._run_state().last_request_influence or {})
                            _influence["conservative_rebuild"] = {
                                "state": "rebuilt",
                                "retired_groups": _rebuild.retired_groups,
                                "projected_chars": _rebuild.projected_chars,
                                "budget_chars": _rebuild.budget_chars,
                                "mandatory_only": _projection_mandatory_only,
                            }
                            self._run_state().last_request_influence = _influence
                        else:
                            _rebuild = type(_rebuild)(
                                state="projection_invalid",
                                messages=(),
                                projected_chars=_rebuild.projected_chars,
                                budget_chars=_rebuild.budget_chars,
                                total_groups=_rebuild.total_groups,
                                retired_groups=_rebuild.retired_groups,
                                detail=";".join(_rebuilt_violations),
                            )

                    if _rebuild.state != "rebuilt":
                        # Runtime cannot infer physical non-fit from a local estimate.
                        # projection_cannot_fit is reserved for an actual provider
                        # overflow on a conservative mandatory-only projection.
                        self._record_action(
                            "action.llm_decide",
                            "projection_invalid",
                            (_rebuild.detail or ";".join(_preflight_violations))[:200],
                        )
                        _run_end_reason = "projection_invalid"
                        final_answer = (
                            "[上下文投影失败] 无法从当前 durable state 重建合法 provider 请求；"
                            "已阻止发送，未用旧请求或伪造摘要替代。"
                        )
                        break

            # Browser providers can expose an exact request-envelope preflight.  Run it
            # after final message/tool projection but before provider-call identity or
            # BrowserSurface work.  A hard rendered-wire overflow is a send invariant:
            # it MUST converge locally or terminate before transport.  Fitting is driven
            # by the exact wire deficit and an absolute post-schema history budget cap;
            # fixed protocol/schema/mandatory bytes are therefore not incorrectly scaled
            # as if the whole request were compressible.
            _request_preflight = getattr(llm_client, "request_envelope_preflight", None)
            if callable(_request_preflight):
                try:
                    _pf = dict(
                        cast(
                            Mapping[str, Any],
                            _request_preflight(messages, tools_param, model=chat_model_arg) or {},
                        )
                    )
                except Exception:  # noqa: BLE001 — optional preflight fail-open to hard guard
                    logger.warning("request envelope preflight failed (fail-open)", exc_info=True)
                    _pf = {}
                _observed = int(_pf.get("observed_chars", 0) or 0)
                _soft = int(_pf.get("soft_limit_chars", 0) or 0)
                _hard = int(_pf.get("hard_limit_chars", 0) or 0)
                _soft_pressure = bool(_pf.get("soft_pressure", False))
                _hard_overflow = bool(_pf.get("hard_overflow", False))
                _pressure_count = int(self._run_state().ingress_pressure_compact_count or 0)
                if _soft_pressure and _observed > 0:
                    _target = _soft if _soft > 0 else _hard
                    _max_fit_rebuilds = 4
                    _current_budget = max(1, int(effective_budget or 0))
                    _can_fit_more = _pressure_count < _max_fit_rebuilds
                    if _target > 0 and _can_fit_more and _current_budget > 1:
                        _deficit = max(1, _observed - _target)
                        _safety = max(1024, int(_target * 0.01))
                        _min_step = max(1024, int(_current_budget * 0.05))
                        _new_cap = max(
                            1,
                            min(
                                _current_budget - _min_step,
                                _current_budget - _deficit - _safety,
                            ),
                        )
                        self._run_state().ingress_history_budget_cap = _new_cap
                        self._run_state().ingress_pressure_compact_count = _pressure_count + 1
                        self._run_state().ingress_pressure_facts = {
                            "observed_chars": _observed,
                            "soft_limit_chars": _soft,
                            "hard_limit_chars": _hard,
                            "rebuild_count": _pressure_count + 1,
                            "history_budget_before": _current_budget,
                            "history_budget_cap": _new_cap,
                            "wire_deficit_chars": _deficit,
                        }
                        self._event_append(
                            session_id,
                            "request.ingress_pressure",
                            {
                                "round": rounds,
                                **self._run_state().ingress_pressure_facts,
                                "action": "exact_wire_fit_rebuild",
                                "hard_overflow": _hard_overflow,
                            },
                        )
                        self._record_action(
                            "request.ingress_pressure",
                            "exact_wire_fit_rebuild",
                            (
                                f"chars={_observed};soft={_soft};hard={_hard};"
                                f"budget={_current_budget}->{_new_cap};deficit={_deficit}"
                            ),
                        )
                        # No provider call occurred, so this is not a logical model round.
                        rounds -= 1
                        continue

                    if _hard_overflow:
                        # Exact fitting did not converge.  Before declaring non-fit,
                        # rebuild the mechanical minimum directly from durable Session
                        # truth (system + exact active ingress + newest complete atomic
                        # group) and measure *that exact browser wire* with the same
                        # canonical renderer.  Provider send remains impossible while
                        # hard_overflow is true.
                        _minimal = self._build_conservative_active_run_messages(
                            sess,
                            max_chars=1,
                            model=model,
                            planned_label=planned_label,
                            logical_round=rounds,
                        )
                        if _minimal.state != "rebuilt":
                            self._record_action(
                                "request.ingress_pressure",
                                "minimum_projection_invalid",
                                _minimal.detail[:200],
                            )
                            _run_end_reason = "projection_invalid"
                            final_answer = (
                                "[上下文投影失败] 无法从当前 durable state 重建机械最小合法 "
                                "provider 请求；已阻止发送。"
                            )
                            break
                        _minimal_messages = list(_minimal.messages)
                        _minimal_pf = dict(
                            cast(
                                Mapping[str, Any],
                                _request_preflight(
                                    _minimal_messages,
                                    tools_param,
                                    model=chat_model_arg,
                                )
                                or {},
                            )
                        )
                        _minimal_observed = int(_minimal_pf.get("observed_chars", 0) or 0)
                        _minimal_hard = int(_minimal_pf.get("hard_limit_chars", _hard) or _hard)
                        _minimal_hard_overflow = bool(
                            _minimal_pf.get("hard_overflow", False)
                        )
                        self._event_append(
                            session_id,
                            "request.ingress_pressure",
                            {
                                "round": rounds,
                                "observed_chars": _minimal_observed,
                                "soft_limit_chars": int(
                                    _minimal_pf.get("soft_limit_chars", _soft) or _soft
                                ),
                                "hard_limit_chars": _minimal_hard,
                                "rebuild_count": _pressure_count,
                                "action": "minimum_projection_preflight",
                                "hard_overflow": _minimal_hard_overflow,
                                "mandatory_only": True,
                            },
                        )
                        if _minimal_hard_overflow:
                            _cannot_fit_exc = LLMRequestTooLargeError(
                                "request_too_large: mechanical minimum rendered request "
                                "exceeds qualified text ingress limit "
                                f"(rendered_chars={_minimal_observed}, "
                                f"max_request_chars={_minimal_hard})",
                                observed_chars=_minimal_observed,
                                limit_chars=_minimal_hard,
                                provider=getattr(llm_client, "provider", ""),
                            )
                            _overflow_action, _overflow_final = self._termination._handle_overflow(
                                _cannot_fit_exc,
                                sess,
                                model_used,
                                model_window={
                                    "label": model_used,
                                    "context": _response_context_limit,
                                },
                                projection_mandatory_only=True,
                            )
                            self._record_action(
                                "request.ingress_pressure",
                                "mandatory_projection_cannot_fit",
                                (
                                    f"chars={_minimal_observed};hard={_minimal_hard};"
                                    "provider_send=blocked"
                                ),
                            )
                            _run_end_reason = "projection_cannot_fit"
                            final_answer = _overflow_final or (
                                "[文本入口超限] 当前机械最小合法投影仍超过 provider 文本入口限制；"
                                "已阻止发送。"
                            )
                            break

                        # The ordinary projection failed to fit but the mechanical
                        # minimum is below the hard ingress limit.  Use that exact
                        # current-truth projection for this call; no stale saved wire is
                        # reused and no semantic summary is fabricated.
                        messages = _minimal_messages
                        _projection_mandatory_only = True
                        _observed = _minimal_observed
                        _soft = int(_minimal_pf.get("soft_limit_chars", _soft) or _soft)
                        _hard = _minimal_hard
                        _soft_pressure = bool(_minimal_pf.get("soft_pressure", False))
                        _hard_overflow = False
                        self._record_action(
                            "request.ingress_pressure",
                            "minimum_projection_selected",
                            f"chars={_minimal_observed};hard={_minimal_hard}",
                        )
                    else:
                        # Soft target is headroom, not a correctness boundary.  After
                        # bounded exact fitting, a request that is proven <= hard limit
                        # may proceed; record the fact instead of pretending convergence.
                        self._event_append(
                            session_id,
                            "request.ingress_pressure",
                            {
                                "round": rounds,
                                "observed_chars": _observed,
                                "soft_limit_chars": _soft,
                                "hard_limit_chars": _hard,
                                "rebuild_count": _pressure_count,
                                "action": "soft_fit_exhausted_safe_to_send",
                                "hard_overflow": False,
                            },
                        )

            # R1: 组件级占用分解（实际发送载荷口径；压缩归档历史不计入当前占用）
            # 供 architecture_status.context_usage.breakdown 注入；last_build_info 入桶保留。
            from llm_loop.core.history import compute_breakdown_from_dicts

            self._run_state().last_breakdown = compute_breakdown_from_dicts(
                messages,
                tool_schema_chars=_tool_schema_chars,
                budget=effective_budget,
            )
            # EVO-20260818: 预算归属模型标注（防误读——provider 级预算如 minimax 40K
            # 与全局 1M 并存，AI 看到 ratio>1 需知 budget 属于哪个模型）
            self._run_state().last_breakdown["model"] = planned_label

            # ── 行动：LLM 决策 ──
            self._phase("action.llm_decide")
            _primary_attempt_id = self._tool_cycle._reachability_begin_attempt(
                kind="primary",
                attempt_index=0,
                model=model_used or chat_model_arg or getattr(llm_client, "model", ""),
                provider=getattr(llm_client, "provider", ""),
            )
            _provider_call_coordinator = getattr(self, "provider_call_coordinator", None)
            _provider_call = (
                _provider_call_coordinator.open_shadow_call_for_client(
                    llm_client,
                    session_id=session_id,
                    idempotency_key=(
                        f"task:{session_id}:turn:{self._run_state().current_turn_ref}:round:{rounds}"
                    ),
                    owner_ref=(
                        f"task:{session_id}:turn:{self._run_state().current_turn_ref}:round:{rounds}"
                    ),
                    execution_class=ExecutionClass.FOREGROUND_TASK,
                    service_priority=ServicePriority.P0_FOREGROUND,
                    purpose=ProviderCallPurpose.TASK,
                )
                if _provider_call_coordinator is not None
                else None
            )

            def _structure_state_hook(state: dict[str, Any], *, _round: int = rounds) -> None:
                self._event_append(
                    session_id,
                    "provider.structure.validated",
                    {
                        "round": _round,
                        "stage": "final_client_projection",
                        **dict(state),
                    },
                )
            # HARNESS-02(2026-08-14): 每轮请求快照进事件日志（fail-open）——routing/fallback
            # 可能中途换模型，事件回放据此确知"当时用的哪个模型/挂了哪些工具/预算多少"，
            # 对 self_evaluate 溯源与回放诊断有帮助
            _provider_visible_chars: int | None = None
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
                _provider_meta_messages = [
                    (
                        {k: v for k, v in m.items() if k != "_active_run_ingress_ref"}
                        if "_active_run_ingress_ref" in m
                        else m
                    )
                    for m in messages
                ]
                try:
                    # Major provider-visible structures only: message payload + tool schemas.
                    # This deliberately excludes transport-only headers/credentials while making
                    # hidden historical reasoning visible in telemetry.
                    _provider_structure_json = json.dumps(
                        {"messages": _provider_meta_messages, "tools": tools_param},
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    )
                    _provider_visible_chars = len(_provider_structure_json)
                    _provider_structure_fp = hashlib.sha256(
                        _provider_structure_json.encode("utf-8")
                    ).hexdigest()[:24]
                except (TypeError, ValueError):
                    _provider_visible_chars = _history_chars + _reasoning_chars
                    _provider_structure_fp = ""
                _message_shape = provider_message_shape(_provider_meta_messages)
                _routing_identity = self._routing._routing_identity()
                _runtime_snapshot_dict = (
                    self._runtime_causal_snapshot.to_dict()
                    if self._runtime_causal_snapshot is not None
                    else {}
                )
                _turn_md: dict[str, Any] = {}
                _turn_ref = self._run_state().current_turn_ref
                if _turn_ref is not None and 0 <= _turn_ref < len(sess.messages):
                    _raw_md = getattr(sess.messages[_turn_ref], "metadata", None)
                    if isinstance(_raw_md, dict):
                        _turn_md = _raw_md
                _actual_provider = str(getattr(llm_client, "provider", "") or "")
                _actual_model = str(chat_model_arg or getattr(llm_client, "model", "") or "")
                _generation_contract = effective_generation_contract(llm_client)
                _run_integrity_receipt = build_run_integrity_receipt(
                    session_id=session_id,
                    background_run=background_run_generation_fact(self, session_id),
                    origin_ingress_channel=first_human_ingress_channel(sess.messages),
                    current_ingress_channel=str(_turn_md.get("ingress_channel") or ""),
                    current_ingress_entry=str(_turn_md.get("ingress_entry") or ""),
                    workspace_epoch=int(getattr(self, "_workspace_epoch", 0) or 0),
                    queue_id=str(_turn_md.get("human_turn_queue_id") or ""),
                    routing_identity=_routing_identity,
                    provider=_actual_provider,
                    model=_actual_model,
                    generation_contract=_generation_contract,
                    provider_call_id=str(getattr(_provider_call, "call_id", "") or ""),
                    attempt_id=str(_primary_attempt_id or ""),
                    system_fp=self._run_state().cache_gate_system_fp,
                    tools_fp=self._run_state().cache_gate_tools_fp,
                    runtime_snapshot=_runtime_snapshot_dict,
                )
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
                        **_message_shape,
                        "history_chars": _history_chars,
                        "reasoning_chars": _reasoning_chars,
                        "provider_visible_chars": _provider_visible_chars,
                        "budget": effective_budget,
                        "input_budget": {
                            "requested_input_tokens": _budget_info.get("input_token_budget"),
                            "allowed_input_tokens": _budget_info.get("allowed_input_tokens"),
                            "tool_schema_reserve_tokens": _budget_info.get("tool_schema_reserve_tokens"),
                            "tool_schema_reserve_source": _budget_info.get("tool_schema_reserve_source"),
                            "effective_history_budget_tokens": _budget_info.get("effective_history_budget_tokens"),
                            "projection_chars_per_token": _budget_info.get("projection_chars_per_token"),
                            "projection_density_source": _budget_info.get("projection_density_source"),
                            "projection_density_samples": _budget_info.get("projection_density_samples", 0),
                            "pre_tool_history_budget_chars": _budget_info.get("pre_tool_history_budget"),
                            "tool_schema_reserve_chars": _budget_info.get("tool_schema_reserve_chars", 0),
                            "effective_history_budget_chars": effective_budget,
                            "limited_by": _budget_info.get("limited_by"),
                        },
                        "projection_guard": getattr(self, "_projection_guard_state", "miss"),
                        "attempt_id": _primary_attempt_id,
                        "provider_call_id": getattr(_provider_call, "call_id", ""),
                        "attempt_kind": "primary",
                        "attempt_index": 0,
                        "provider_structure_fp": _provider_structure_fp,
                        "runtime_snapshot": _runtime_snapshot_dict,
                        "generation_contract": _generation_contract,
                        "run_integrity_receipt": _run_integrity_receipt,
                        "routing_epoch": _routing_identity["epoch"],
                        "routing_registry_fp": _routing_identity["registry_fp"],
                        "routing_transition": _routing_identity["transition"],
                        "active_run_ingress_ref": _active_run_ingress_ref,
                        "active_run_ingress_kind": _active_run_ingress_kind,
                        "influence": dict(self._run_state().last_request_influence or {}),
                    },
                )
            except Exception:  # noqa: BLE001 — 快照失败 fail-open（不影响主循环）
                logger.debug("request.meta 事件写入失败（fail-open）")
            _density_observation_eligible = True
            cap = InterruptedCapture(
                self,
                sess=sess,
                round_no=rounds,
                provider=getattr(llm_client, "provider", ""),
                model=model_used or chat_model_arg or getattr(llm_client, "model", ""),
                nonconvergence_windows=self.settings.tool_runtime.nonconvergence_fuse_windows,
                nonconvergence_jaccard=self.settings.tool_runtime.nonconvergence_fuse_jaccard,
                nonconvergence_min_delta=self.settings.tool_runtime.nonconvergence_fuse_min_delta,
            )  # B1: 轮级重置 + durable in-flight checkpoint for restart continuity
            # Phase5 M2（设计 §2.2.1/§2.2.2）：流内插话检查点每轮局部状态——
            # _interject_interrupted 打断收割 flag（run 不终止，流后收割分支消费）；
            # _stream_icheck_last 节流时间戳（≥间隔才 peek mailbox）。
            _interject_interrupted = False
            _stream_icheck_last = 0.0
            # 遗留处置 L1：流式检查点 peek 故障一次性 warning 旗标（per-run 轮状态，
            # 与同步窗口 _peek_warned 同语义；一 run 内至多一条，避免 40ms 节流刷屏）。
            _stream_peek_warned: list[bool] = []
            # Phase6 M1：打断收割的 via 口径——流式检查点命中保持 llm_stream_interrupt；
            # 同步窗口轮询命中为 sync_window_poll（度量分桶区分两通道，T1/T3 依据）。
            _interrupt_via = "llm_stream_interrupt"
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
                            stable_prefix_fp=self._run_state().cache_gate_stable_fp,
                            cache_prefix_epoch=self._run_state().cache_prefix_epoch,
                            compaction_epoch=self._run_state().compact_event_seq,
                            active_run_ingress_ref=_active_run_ingress_ref,
                            active_run_ingress_kind=_active_run_ingress_kind,
                            structure_state_hook=_structure_state_hook,
                            knowledge_reference_probe=getattr(self._run_state().knowledge_runtime, "provider_reference_facts", None),
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
                    it = foreground_task_provider_stream(
                        self,
                        llm_client,
                        stream_fn,
                        _stream_kwargs,
                        owner_ref=f"task:{session_id}:round:{rounds}:primary:{_primary_attempt_id}",
                        provider_id=str(getattr(llm_client, "provider", "") or ""),
                        model_id=chat_model_arg or getattr(llm_client, "model", ""),
                        before_call=cap.mark_provider_send,
                        provider_call=_provider_call,
                        attempt_kind=ProviderAttemptKind.PRIMARY,
                        site_index=0,
                    )
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
                            # Phase5 M2（设计 §2.2.1/§2.2.2）：流内插话检查点——
                            # Stop 优先（上分支），插话次之；节流（≥间隔才 peek，
                            # 检查位=next(it) 返回后、on_delta 前，命中即丢弃本
                            # delta）。命中打断收割：半截产物如实限量落盘（P1-6
                            # 同款，不伪装完整）→ close → 置 flag → 流后收割分支。
                            if (
                                getattr(
                                    self.settings.tool_runtime,
                                    "llm_stream_interject_checkpoint",
                                    True,
                                )
                                and (time.monotonic() - _stream_icheck_last)
                                >= _STREAM_INTERJECT_CHECK_MIN_GAP_S
                            ):
                                _stream_icheck_last = time.monotonic()
                                # 遗留处置 L1：peek 经 _interjection_peek fail-open
                                # （§4.4 peek 失败不收割；此前裸调，管道故障会冒泡 run error）
                                if _interjection_peek(
                                    self,
                                    session_id,
                                    warned=_stream_peek_warned,
                                    where="llm_stream",
                                ):
                                    _interject_interrupted = True
                                    _llm_round_ms = (time.perf_counter() - _llm_start) * 1000.0
                                    cap.fire(
                                        sess, "interjection_interrupted", rounds
                                    )  # 半截产物限量落盘 + llm.interrupted 审计（防重内聚）
                                    _icheck_close = getattr(it, "close", None)
                                    if callable(_icheck_close):
                                        try:
                                            _icheck_close()
                                        except Exception:  # noqa: BLE001 — 收割释放流 fail-open
                                            logger.debug(
                                                "LLM stream close 失败（fail-open）",
                                                exc_info=True,
                                            )
                                    break
                            if not _ttft_done and getattr(d, "text", ""):
                                _ttft_done = True
                                ttft_first_ms = (time.perf_counter() - _llm_start) * 1000.0
                            cap.on_delta(d)
                            if cap.fuse_tripped:
                                # EVO-20260915-789eb9d5：机械非收敛熔断——先落半截产物
                                # 与 llm.interrupted 审计，再终态终止本生成（不再 yield）。
                                cap.fire(sess, "nonconvergence_fuse", rounds)
                                close_stream = getattr(it, "close", None)
                                if callable(close_stream):
                                    try:
                                        close_stream()
                                    except Exception:  # noqa: BLE001 — 熔断释放流 fail-open
                                        logger.debug(
                                            "LLM stream close 失败（fail-open）", exc_info=True
                                        )
                                raise NonconvergenceFuseError(cap.fuse_evidence)
                            yield d
                        except StopIteration as exc:
                            resp = exc.value
                            _llm_round_ms = (time.perf_counter() - _llm_start) * 1000.0
                            if resp is not None:
                                cap.on_response(resp)
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
                            stable_prefix_fp=self._run_state().cache_gate_stable_fp,
                            cache_prefix_epoch=self._run_state().cache_prefix_epoch,
                            compaction_epoch=self._run_state().compact_event_seq,
                            active_run_ingress_ref=_active_run_ingress_ref,
                            active_run_ingress_kind=_active_run_ingress_kind,
                            structure_state_hook=_structure_state_hook,
                            knowledge_reference_probe=getattr(self._run_state().knowledge_runtime, "provider_reference_facts", None),
                        )
                    _sync_gate = bool(
                        getattr(self.settings.tool_runtime, "sync_chat_interject_checkpoint", True)
                    )
                    if not _sync_gate:
                        # 配置门关（逃生舱）→ 原内联路径：窗口形态（final_gate 保守收割），行为可回滚
                        resp = foreground_task_provider_chat(
                            self,
                            llm_client,
                            llm_client.chat,
                            _chat_kwargs,
                            owner_ref=f"task:{session_id}:round:{rounds}:primary:{_primary_attempt_id}",
                            provider_id=str(getattr(llm_client, "provider", "") or ""),
                            model_id=chat_model_arg or getattr(llm_client, "model", ""),
                            before_call=cap.mark_provider_send,
                            provider_call=_provider_call,
                            attempt_kind=ProviderAttemptKind.PRIMARY,
                            site_index=0,
                        )
                        _llm_round_ms = (time.perf_counter() - _llm_sync_start) * 1000.0
                        if resp is not None:
                            cap.on_response(resp)
                    else:
                        # Phase6 M1（设计 §3A）：同步 chat 通道异步化——provider 调用移入
                        # worker 线程，run 线程轮询 Stop/插话检查点。无 chat_stream 的
                        # client（FakeLLM 同步形态 / deepseek-web / chatgpt-web）在 LLM
                        # 窗口内获得与流式通道同口径的打断：消费即时（sync_window_poll）
                        # + INTERRUPTED 结算 + 下一轮全量消费；Stop 即时终态不等 worker
                        # （daemon 残余后台自然结束，lease/site 晚退可接受）。worker 晚到
                        # 结果被丢弃——打断轮不进下一轮 provider 投影（P1-6 退役纪律）。
                        # 命中优先于 worker 完成（设计 §8.6）；client.cancel() 协作钩子
                        # 尽力调用，异常降级残余等待（§8.2）。
                        _sync_icheck_last = 0.0
                        _sync_cancel_hook = getattr(llm_client, "cancel", None)
                        _sync_result: dict[str, Any] = {}
                        _peek_warned: list[bool] = []  # 本窗口 peek 失败告警旗标（至多一条）

                        # 默认参数在定义时求值：worker 线程绑定本轮快照
                        # （B023 语义——闭包经默认参固化，不受后续轮次重绑定影响）。
                        def _sync_worker(
                            *,
                            _result: dict[str, Any] = _sync_result,
                            _client: Any = llm_client,
                            _chat_kw: dict[str, Any] = _chat_kwargs,
                            _owner_ref: str = f"task:{session_id}:round:{rounds}:primary:{_primary_attempt_id}",
                            _provider_id: str = str(getattr(llm_client, "provider", "") or ""),
                            _model_id: str = chat_model_arg or getattr(llm_client, "model", ""),
                            _before_call: Any = cap.mark_provider_send,
                            _provider_call_id: Any = _provider_call,
                        ) -> None:
                            try:
                                _result["resp"] = foreground_task_provider_chat(
                                    self,
                                    _client,
                                    _client.chat,
                                    _chat_kw,
                                    owner_ref=_owner_ref,
                                    provider_id=_provider_id,
                                    model_id=_model_id,
                                    before_call=_before_call,
                                    provider_call=_provider_call_id,
                                    attempt_kind=ProviderAttemptKind.PRIMARY,
                                    site_index=0,
                                )
                            except BaseException as exc:  # noqa: BLE001 - 经结果槽传回 run 线程
                                _result["exc"] = exc

                        # contextvars 拷贝进 worker：预算门控（active_task_budget）、
                        # reasoning effort 等上下文绑定在 run 线程，新线程默认不继承
                        # （回归实证：task_budget 系列门控曾因此失效）。provider 调用
                        # 内部对 contextvar 的写仅落在拷贝内（隔离），与内联语义一致。
                        _sync_ctx = contextvars.copy_context()
                        _sync_thread = threading.Thread(
                            target=_sync_ctx.run,
                            args=(_sync_worker,),
                            name=f"phase6-syncchat:{session_id}:round:{rounds}",
                            daemon=True,
                        )
                        _sync_thread.start()
                        while True:
                            _cancel_reason = _background_cancel_reason(self, session_id)
                            if _cancel_reason:
                                # Stop 即时终态：请求协作取消（尽力）后不等 worker
                                cap.cancelled = True
                                if callable(_sync_cancel_hook):
                                    try:
                                        _sync_cancel_hook()
                                    except Exception:  # noqa: BLE001 - 钩子异常降级
                                        logger.debug("sync chat cancel hook raised", exc_info=True)
                                break
                            if (time.monotonic() - _sync_icheck_last) >= _SYNC_INTERJECT_POLL_GAP_S:
                                _sync_icheck_last = time.monotonic()
                                if _interjection_peek(self, session_id, warned=_peek_warned):
                                    # 窗口内插话命中 → 即时打断（复用流式打断收割分支）
                                    _interject_interrupted = True
                                    _interrupt_via = "sync_window_poll"
                                    if callable(_sync_cancel_hook):
                                        try:
                                            _sync_cancel_hook()
                                        except Exception:  # noqa: BLE001 - 钩子异常降级
                                            logger.debug("sync chat cancel hook raised", exc_info=True)
                                    break
                            if not _sync_thread.is_alive():
                                _sync_thread.join()
                                # 命中优先（设计 §8.6）：worker 完成检测点补一次
                                # 无节流终检——节流跳过期间到达的窗口内插话仍应
                                # 打断，晚到的完整响应按打断轮丢弃（不进投影）。
                                if _interjection_peek(self, session_id, warned=_peek_warned):
                                    _interject_interrupted = True
                                    _interrupt_via = "sync_window_poll"
                                    if callable(_sync_cancel_hook):
                                        try:
                                            _sync_cancel_hook()
                                        except Exception:  # noqa: BLE001 - 钩子异常降级
                                            logger.debug("sync chat cancel hook raised", exc_info=True)
                                break
                            time.sleep(_SYNC_INTERJECT_POLL_GAP_S / 2)
                        _llm_round_ms = (time.perf_counter() - _llm_sync_start) * 1000.0
                        if not cap.cancelled and not _interject_interrupted:
                            _sync_exc = _sync_result.get("exc")
                            if _sync_exc is not None:
                                raise _sync_exc
                            resp = _sync_result.get("resp")
                            if resp is not None:
                                cap.on_response(resp)
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
                if isinstance(exc, NonconvergenceFuseError):
                    # EVO-20260915-789eb9d5：机械非收敛熔断——终态化收口，短路
                    # guard/overflow/err1210/fallback 全部重试环（绝不无限重试）。
                    self._tool_cycle._reachability_finalize("nonconvergence_fuse")
                    if _provider_call_coordinator is not None:
                        _provider_call_coordinator.settle_shadow_call(
                            _provider_call, ProviderCallOutcome.INTERRUPTED
                        )
                    self._record_action(
                        "action.llm_decide", "nonconvergence_fuse", str(exc)[:200]
                    )
                    if self.status:
                        self.status.record_exception("nonconvergence_fuse", exc)
                    try:
                        self._event_append(
                            sess.session_id,
                            "llm.nonconvergence_fuse",
                            {
                                "round": int(rounds or 0),
                                **(getattr(exc, "evidence", None) or {}),
                            },
                        )
                    except Exception:  # noqa: BLE001 — 审计事件 fail-open
                        logger.debug("llm.nonconvergence_fuse 事件写入失败（fail-open）")
                    _run_end_reason = "nonconvergence_fuse"
                    final_answer = (
                        "[非收敛熔断 EVO-20260915-789eb9d5] 模型生成连续 "
                        f"{int((getattr(exc, 'evidence', None) or {}).get('streak', 0) or 0)} 个"
                        "检查点窗口无新工具草稿、无持久状态写入且推理同语义复读，"
                        "已机械熔断终止；半截产物与窗口证据见 llm.interrupted 与 "
                        "llm.nonconvergence_fuse 事件。请上层策略决定下一步。"
                    )
                    resp = None
                    break
                self._tool_cycle._reachability_finalize(
                    "cancelled_provider" if _cancel_reason else "provider_error"
                )
                if _cancel_reason:
                    if _provider_call_coordinator is not None:
                        _provider_call_coordinator.settle_shadow_call(
                            _provider_call, ProviderCallOutcome.INTERRUPTED
                        )
                    _run_end_reason = "cancelled"
                    final_answer = _CANCELLED_ANSWER
                    resp = None
                    break
                if isinstance(exc, LLMProjectionError):
                    projection_validator_failed = True
                    if _provider_call_coordinator is not None:
                        _provider_call_coordinator.settle_shadow_call(
                            _provider_call, ProviderCallOutcome.BLOCKED_BEFORE_TRANSPORT
                        )
                    if _active_run_ingress_ref and _projection_rebuild_round != rounds:
                        # At most one rebuild per logical model round. A second
                        # rejection remains fail-closed, with no provider fallback.
                        _projection_rebuild_requested = True
                        rounds -= 1
                        resp = None
                        continue
                    self._record_action(
                        "action.llm_decide", "projection_invalid", str(exc)[:200]
                    )
                    if self.status:
                        self.status.record_exception("projection_invalid", exc)
                    _run_end_reason = "projection_invalid"
                    final_answer = (
                        "[上下文投影失败] provider wire 未通过机械结构校验；"
                        "已在外部请求前阻止继续，本轮未复用陈旧 provider projection。"
                    )
                    break
                # 拷问⑥（2026-08-18）: cache_guard BLOCK——直接如实反馈 AI
                # （不重试/不走 overflow reinject——重试同样被拦=浪费循环；AI 需先
                # 压缩/换会话自救）
                from llm_loop.cache_guard.guard import CacheGuardBlockedError

                if isinstance(exc, CacheGuardBlockedError):
                    if _provider_call_coordinator is not None:
                        _provider_call_coordinator.settle_shadow_call(
                            _provider_call, ProviderCallOutcome.BLOCKED_BEFORE_TRANSPORT
                        )
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
                    projection_mandatory_only=_projection_mandatory_only,
                )
                if overflow_action == "cannot_fit" and overflow_final is not None:
                    if _provider_call_coordinator is not None:
                        _provider_call_coordinator.settle_shadow_call(
                            _provider_call, ProviderCallOutcome.ERROR
                        )
                    projection_cannot_fit_noted = True
                    self._record_action(
                        "action.llm_decide",
                        "projection_cannot_fit",
                        "provider_rejected_mandatory_projection",
                    )
                    _run_end_reason = "projection_cannot_fit"
                    final_answer = overflow_final
                    break
                if overflow_action == "reinject":
                    if _provider_call_coordinator is not None:
                        _provider_call_coordinator.settle_shadow_call(
                            _provider_call, ProviderCallOutcome.ERROR
                        )
                    # R8.24-B B-D5: 首次 overflow——预算已确定性收缩
                    # （_overflow_shrink_factor），continue 后下一轮 build 以收紧
                    # 预算重组（超出部分 lossless 归档），零 prompt 注入。
                    continue
                if overflow_action == "end" and overflow_final is not None:
                    if _provider_call_coordinator is not None:
                        _provider_call_coordinator.settle_shadow_call(
                            _provider_call, ProviderCallOutcome.ERROR
                        )
                    _run_end_reason = "overflow"
                    final_answer = overflow_final
                    break
                # ── err1210 P0（tasks 4.3）: compact 首请求 1210 定向降级重试（mixin 封装，
                # 编排与控制流语义见 err1210.py；恢复成功 → 新 resp 走下方正常路径，
                # 失败 → 原样继续既有错误链；env ERR1210_RECOVERY=0 完全旁路）──
                _e1210_recovered, resp, _llm_round_ms, _e1210_retry_count = (
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
                        provider_call=_provider_call,
                    )
                )
                if _e1210_recovered:
                    # Recovery may send a mechanically transformed payload; the pre-call
                    # provider_visible_chars no longer describes the successful request.
                    _density_observation_eligible = False
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
                        fallback_label: str,
                        fallback_registry: Any,
                        _round: int = rounds,
                        _user_text: str = user_text,
                    ) -> tuple[list[dict], list[dict]]:
                        fallback_budget_info = self._effective_history_budget_detail(
                            fallback_label, registry_snapshot=fallback_registry
                        )
                        fallback_budget = int(
                            fallback_budget_info.get("effective_budget", 0) or 0
                        )
                        fallback_schemas, fallback_tools = self._project_request_tools(
                            session_id=session_id,
                            user_text=_user_text,
                            planned_label=fallback_label,
                            session_messages=sess.messages,
                            advance_state_round=False,
                            logical_round=_round,
                        )
                        fallback_tool_chars = len(
                            _json_dumps_args({"tools": fallback_tools})
                        )
                        fallback_budget = (
                            self._routing.reserve_tool_schema_from_history_budget(
                                fallback_budget,
                                fallback_budget_info,
                                fallback_tool_chars,
                            )
                        )
                        fallback_messages = self._build_llm_messages(
                            sess,
                            _turn_memory_msgs,
                            max_chars=fallback_budget,
                            planned_label=fallback_label,
                            registry_snapshot=fallback_registry,
                            logical_round=_round,
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
                        provider_call=_provider_call,
                        site_index_offset=1 + int(_e1210_retry_count or 0),
                        active_run_ingress_ref=_active_run_ingress_ref,
                        active_run_ingress_kind=_active_run_ingress_kind,
                    )
                    # Successful fallback facts are carried by RunState/LoopResult, not
                    # model-visible Message objects. inject_msgs is all-failed facts only.
                    if fallback_resp is not None:
                        # 降级成功: 响应以新模型运行, 进入后续正常路径
                        # Primary request chars do not describe the fallback wire.
                        _density_observation_eligible = False
                        resp = fallback_resp
                        if fallback_ref:
                            model_used = fallback_ref  # M51: 如实标注为降级后的模型
                        _model_route_source = "fallback"
                        _model_route_authority = "runtime_fallback_policy"
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
                        if _provider_call_coordinator is not None:
                            _provider_call_coordinator.settle_shadow_call(
                                _provider_call, ProviderCallOutcome.ERROR
                            )
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
                    if _provider_call_coordinator is not None:
                        _provider_call_coordinator.settle_shadow_call(
                            _provider_call, ProviderCallOutcome.ERROR
                        )
                    _run_end_reason = "llm_error"
                    final_answer, resp = self._llm_error_round_exit(
                        sess, cap, exc, session_id, len(messages), rounds, "llm_error"
                    )
                    break

            if cap.cancelled:
                if _provider_call_coordinator is not None:
                    _provider_call_coordinator.settle_shadow_call(
                        _provider_call, ProviderCallOutcome.INTERRUPTED
                    )
                self._tool_cycle._reachability_finalize("cancelled_provider")
                _run_end_reason = "cancelled"
                final_answer = _CANCELLED_ANSWER
                resp = None  # 防止上一轮响应残留参与 usage/reasoning/finalize
                break

            if _interject_interrupted:
                # Phase5 M2（设计 §2.2.2）：流内插话打断收割——run 不终止，轮边界
                # 收割：settle INTERRUPTED + attempt 收口 → 消费插话（via=
                # llm_stream_interrupt，interrupt_receipt 恒 False）→ 下一轮 LLM
                # 请求历史含插话 user 消息（半截行按 P1-6 退役纪律不进 provider
                # 投影）。usage/reasoning 归集跳过（打断固有，与 cancelled 同口径）。
                if _provider_call_coordinator is not None:
                    _provider_call_coordinator.settle_shadow_call(
                        _provider_call, ProviderCallOutcome.INTERRUPTED
                    )
                self._tool_cycle._reachability_finalize("interjection_interrupted_provider")
                resp = None  # 打断轮无完整响应，防残留参与 usage/reasoning/finalize
                _interrupted_texts = _consume_live_interjections(
                    self, session_id, sess, via=_interrupt_via
                )
                if _interrupted_texts:
                    # 收割文本并入轮首合并桶（设计 Q2：否则下一轮轮首消费点空取，
                    # user_text 辅助视图错过本轮插话）。
                    with contextlib.suppress(Exception):
                        self._run_state().interject_harvest_user_texts.extend(
                            t for t in _interrupted_texts if t.strip()
                        )
                continue

            # All paths reaching this boundary have a completed provider response:
            # normal return, successful fallback, or successful ERR1210 recovery.
            # Error/cancel paths break above.
            if _provider_call_coordinator is not None:
                _provider_call_coordinator.settle_shadow_call(
                    _provider_call, ProviderCallOutcome.SUCCESS
                )
            # Cast only communicates that control-flow
            # invariant to static analysis; it does not change runtime behavior.
            resp = cast(LLMResponse, resp)
            if (
                _density_observation_eligible
                and isinstance(_provider_visible_chars, int)
                and _provider_visible_chars > 0
                and int(resp.prompt_tokens or 0) > 0
            ):
                try:
                    self._routing._observe_projection_density(
                        planned_label,
                        provider_visible_chars=_provider_visible_chars,
                        prompt_tokens=int(resp.prompt_tokens),
                        registry_snapshot=_planning_registry,
                    )
                except Exception:  # noqa: BLE001 — calibration is observational/fail-open
                    logger.debug("projection density observation failed", exc_info=True)
            provider_output_truncated = provider_output_truncated or bool(resp.truncated)
            self._tool_cycle._reachability_record_response(resp)
            self._record_action(
                "action.llm_decide", "llm_response", self._tool_cycle._resp_summary(resp)
            )
            # M52: 聚合本轮 token 用量（含 fallback 成功响应；0 = provider 未提供）
            tokens_in += resp.prompt_tokens
            tokens_out += resp.completion_tokens
            # R2（antidrift_impl 批1）: vitals 桶侧机械镜像（真相源=上方局部累加；
            # 回执组装点只读桶，不经局部变量——B5-W1 接管前局部即真相源）
            _vitals_bucket.vitals_rounds = rounds
            _vitals_bucket.vitals_tokens_in = tokens_in
            _vitals_bucket.vitals_tokens_out = tokens_out
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
                # P0-2 B3 (GAP-REQ-2): settlement join keys via module-level
                # helper (zero added branch complexity in this function).
                _provider_call_join_id, _provider_attempt_join_id = (
                    _settlement_join_ids_for_usage(
                        _provider_call, _provider_call_coordinator
                    )
                )
                _request_usage_payload = {
                    "round": rounds,
                    "model": model_used or getattr(self.settings, "llm_model", ""),
                    # P1-B: prompt-neutral routing authority facts. Per-call selection is
                    # deliberately labelled ephemeral and never implies session persistence.
                    "effective_model_this_run": (
                        model_used or getattr(self.settings, "llm_model", "")
                    ),
                    "model_source": _model_route_source,
                    "model_authority": _model_route_authority,
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
                    "provider_call_id": _provider_call_join_id,
                    "provider_attempt_id": _provider_attempt_join_id,
                    "usage_available": _req_usage_available,
                    "timing": cap.timing(total_ms=_llm_round_ms),
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
                # A human steer may arrive while this provider response is in flight.  A
                # no-tool response is only terminal if the mailbox is still empty at the
                # settlement boundary; otherwise continue the same run so the next model
                # decision includes the newly persisted genuine-human turn.
                _late_interjected = _consume_live_interjections(
                    self, session_id, sess, at_final_gate=True, via="final_gate"
                )
                if _late_interjected:
                    _nonempty_interjected = [row for row in _late_interjected if row.strip()]
                    if _nonempty_interjected:
                        user_text = "\n\n".join(_nonempty_interjected)
                    with contextlib.suppress(Exception):
                        self._record_action(
                            "human.interjection",
                            "continued_before_final",
                            f"round={rounds}; count={len(_late_interjected)}",
                        )
                    # Phase3 G1（审查 P1-2 修正）：本次消费是终答结算边界拦截——
                    # 只触发 cbf 回执（拦截本身即决策改变：run 从「要终答」变为
                    # 「继续」）。applied 不在此处触发：其回调保留在 stash，由续跑
                    # 轮的真实出口（首个工具派发/终答出口）触发；若续跑被取消或
                    # 出错，则不标 applied（未被后续决策采用，诚实优先）。
                    _fire_interject_applied(
                        self, "continued_before_final_gate", also_cbf=True, fire_applied=False
                    )
                    final_answer = ""
                    resp = None
                    continue
                # EVO-20260923-618f7fd1 ①: 收尾 use 回记提醒（fail-open、每 run 一次、
                # 不阻塞——模型再次无工具调用即放行最终答复）
                if not _method_use_reminder_fired:
                    try:
                        from llm_loop.core.loop.engine_services.method_injection import (
                            build_use_reminder_message,
                            scan_method_use_ledger,
                        )

                        _unrecorded = scan_method_use_ledger(tool_trace).unrecorded()
                        if _unrecorded:
                            _method_use_reminder_fired = True
                            sess.messages.append(build_use_reminder_message(_unrecorded))
                            with contextlib.suppress(Exception):
                                self._record_action(
                                    "method.use_reminder",
                                    "continued_before_final",
                                    f"round={rounds}; refs={','.join(_unrecorded[:6])}",
                                )
                            final_answer = ""
                            resp = None
                            continue
                    except Exception:  # noqa: BLE001 — fail-open：提醒失败不阻塞收尾
                        logger.debug(
                            "method use reminder skipped (fail-open)", exc_info=True
                        )
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
                # Phase3 G1 applied 判据①：终答出口（非取消路径完成终答；取消路径
                # 不触发——未被决策采用即不标 applied，诚实优先）。
                _fire_interject_applied(self, "final_answer_after_interjection")
                break

            # ── 行动：执行工具（tool_calls）──
            # M53 拆分: 工具段 → _ToolExecMixin._execute_tools（yield from 保持 tool_round 外泄次序）
            # Phase3 G1 applied 判据②：首个工具派发（包含插话消息的模型决策产生了动作）。
            _fire_interject_applied(self, f"tool_dispatched_round={rounds}")
            yield from self._tool_cycle._execute_tools(resp, sess, rounds, tool_trace)

            # P0-B: after durable tool receipts, evaluate only mechanical convergence
            # facts. The boundary changes the *next provider tool surface*; it injects
            # no system/user message and never decides that the user's task is complete.
            self._tool_cycle._maybe_arm_convergence_boundary(sess, rounds)

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
                if self.settings.tool_runtime.e18_hard_stop:
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

        _fallback_receipt = self._run_state().fallback_receipt
        _runtime_receipt = {
            # UI/history observability only. RunFinalizer stores this under Message.metadata,
            # which Message.to_llm_dict() never projects onto the provider wire.
            "fallback_receipt": (
                {str(k): str(v) for k, v in _fallback_receipt.items()}
                if isinstance(_fallback_receipt, dict)
                else None
            ),
            "reasoning_mode": str(reasoning_mode_used or "auto"),
            "reasoning_capable": bool(reasoning_capable),
            "reasoning_control": str(reasoning_control or "unknown"),
            "reasoning_supported": bool(reasoning_supported),
            "reasoning_effective": bool(reasoning_effective),
            "reasoning_tokens": int(reasoning_tokens) if reasoning_tokens is not None else None,
        }
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
            history_compacted=history_compacted_noted,
            provider_output_truncated=provider_output_truncated,
            projection_validator_failed=projection_validator_failed,
            projection_rebuilt=projection_rebuilt_noted,
            projection_cannot_fit=projection_cannot_fit_noted,
            verification_note=verification_note,
            _run_started_at=_run_started_at,
            runtime_receipt=_runtime_receipt,
        )
        # Method Learning v1：post-run 钩子（fail-open：usage 遥测 + auto 模式 friction 触发的 self-distill reflection）。
        # 位置与 feature 原点等价：run.end/长回答落盘已并入 _run_finalizer.persist_and_settle，故在其返回后、LoopResult 前调用。
        self._method_learning.post_run(
            session_id, sess, rounds, tool_trace, _run_end_reason, final_answer or "", model_used
        )
        _run_incomplete = _run_end_reason != "completed" or provider_output_truncated
        return LoopResult(
            session_id=session_id,
            final_answer=final_answer,
            verification_note=verification_note,
            rounds=rounds,
            tool_calls=tool_trace,
            truncated=_run_incomplete,
            history_compacted=history_compacted_noted,
            provider_output_truncated=provider_output_truncated,
            run_incomplete=_run_incomplete,
            projection_validator_failed=projection_validator_failed,
            projection_rebuilt=projection_rebuilt_noted,
            projection_cannot_fit=projection_cannot_fit_noted,
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
            fallback_receipt=_fallback_receipt,
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

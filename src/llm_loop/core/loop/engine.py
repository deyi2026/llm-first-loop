"""五阶段核心循环 LoopEngine（design.md §2.1.3.1 / FR-LOOP 系列）.

架构主轴: 消息进 → 理解 → 行动 → 真诚回答 → 记住。

- 工具反馈子循环: 工具消息作为独立消息再入理解（FR-LOOP-04）
- 严格 function calling: tool_call_id 由程序统一管理（约束 C1-C6）
- 声明-回执校验（FR-FBK-01，不一致如实反馈，最多更正 1 次）
- 停滞检测 + 轮数上限（如实结束）
- 架构自省: 阶段/动作轨迹/工具历史/异常采集 + [架构上报] 推送（AI-serving）
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from llm_loop.config import Settings
from llm_loop.core.history import (  # noqa: F401 (history 工具)
    projection_check,
    projection_ver,
    stable_digest,
)

# M53 拆分: 职责 mixin（signals 信号检查 / runtime 运行时参数 / fallback 模型降级链 / routing 模型路由 / overflow overflow 处理 / tool_exec 工具执行）
from llm_loop.core.loop.archive import _ArchiveMixin
from llm_loop.core.loop.build import _BuildMixin  # EVO-20260817-e63f712f: 消息构建拆分
from llm_loop.core.loop.err1210 import (
    _Err1210Mixin,  # err1210 P0 恢复（tasks 4.2/4.3；状态字段/接线方法均在 err1210.py）
)
from llm_loop.core.loop.events import _EventsMixin
from llm_loop.core.loop.fallback import _FallbackMixin
from llm_loop.core.loop.interop import _InteropMixin
from llm_loop.core.loop.kpi import _KpiMixin
from llm_loop.core.loop.lifecycle import _LifecycleMixin
from llm_loop.core.loop.overflow import _OverflowMixin
from llm_loop.core.loop.routing import (
    _CHARS_PER_TOKEN_EST,  # noqa: F401 — M53 拆分 re-export（原路径可导入，REQ-REF-06）
    _CONTEXT_SAFETY_MARGIN,  # noqa: F401 — M53 拆分 re-export（原路径可导入，REQ-REF-06）
    _RoutingMixin,
)
from llm_loop.core.loop.runstate import _RunState, _RunStateMixin
from llm_loop.core.loop.runtime import _RuntimeParamsMixin
from llm_loop.core.loop.signals import _SignalsMixin
from llm_loop.core.loop.tool_exec import (
    _json_dumps_args,
    _tool_args_summary,  # noqa: F401 — M53 拆分 re-export（原路径可导入，REQ-REF-06）
    _ToolExecMixin,
)
from llm_loop.core.loop.turn_context import _TurnContextMixin
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.run_context import (
    current_reasoning_effort as _current_reasoning_effort,
)
from llm_loop.core.session import SessionStore
from llm_loop.feedback.honesty import (
    max_iterations_decision_message,
    max_iterations_feedback,
    max_iterations_warning_message,
    stagnation_feedback,
)
from llm_loop.feedback.validator import DeclarationValidator, build_discrepancy_feedback
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.status import ArchitectureStatusProvider
from llm_loop.llm.client import GuardRequestContext, LLMClient, StreamDelta
from llm_loop.llm.errors import LLMError
from llm_loop.memory.store import MemoryStore
from llm_loop.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_CANCELLED_ANSWER = "（已停止——用户点击停止按钮，本轮回答终止）"


def _background_cancelled(engine: Any, session_id: str) -> bool:
    runner = getattr(engine, "runner", None)
    return bool(runner is not None and runner.enabled and runner.is_cancelled(session_id))


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

# M53: 上下文守卫估算常量 → llm_loop/core/loop/routing.py（_RoutingMixin）
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

def build_session_snapshot_text(
    message_count: int, memory_count: int, evolution_summary: dict | None = None
) -> str:
    """会话状态快照文本（EVO-20260811-9ccdec97）: 客观指标 + 定位校准引导.

    作为 system 消息注入，帮助 AI 在长会话中保有"我在哪、要去哪"的定位锚点；
    客观指标取实时值，语义部分（当前任务/下一步）由 AI 以本条为锚点自行校准。
    """
    parts = [f"[会话状态快照] 消息 {message_count} 条；记忆 {memory_count} 条"]
    if evolution_summary:
        parts.append(
            "演进待办: "
            + ", ".join(
                f"{k}={v}" for k, v in evolution_summary.items() if k in ("pending_review", "executed", "executing")
            )
        )
    parts.append("若你对当前任务/已完成/下一步/未决事项的定位漂移，以本条为锚点重新校准。")
    return "；".join(parts)

class LoopEngine(_RunStateMixin, _SignalsMixin, _RuntimeParamsMixin, _FallbackMixin, _RoutingMixin, _OverflowMixin, _Err1210Mixin, _ToolExecMixin, _InteropMixin, _ArchiveMixin, _BuildMixin, _EventsMixin, _KpiMixin, _LifecycleMixin, _TurnContextMixin):
    """五阶段核心循环控制器."""

    # EVO 后台 run 执行器（factory 动态装配 BackgroundRunner；声明类型供 pyright 静态检查）
    runner: Any | None = None
    # DSH-PLUGINS-20260816 ②: 调度提醒线程（factory 装配；声明类型供 pyright 静态检查）
    scheduler: Any | None = None
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
        eval_trigger_detector: Any | None = None,  # M12 深化 T63: EvalTriggerDetector 自我评估提醒
        evolution_store: Any
        | None = None,  # M17 FR-REVIEW-AI-02: EvolutionStore（executing 提醒检测）
        loop_signal_detector: Any
        | None = None,  # M17 FR-REVIEW-AI-02/03: LoopSignalDetector 三合一
        llm_pool: Any | None = None,  # M48（design §5.3）: ModelClientPool（会话级模型路由）
        recovery: Any | None = None,  # P2-2: RecoveryChannel（fail-open 写失败恢复通道）
        event_store: Any | None = None,  # D1: EventStore（事件源化，默认 None 零行为）
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
        self.eval_trigger_detector = eval_trigger_detector
        self.evolution_store = evolution_store
        self.loop_signal_detector = loop_signal_detector
        # M48（design §5.3）: 会话级模型路由池；None 时使用装配默认 client（零回归）
        self.llm_pool = llm_pool
        # P2-2: fail-open 写失败恢复通道；None 时三个 fail-open 点行为不变（零回归）
        self.recovery = recovery
        # D1: 事件源化 EventStore（默认 None 零行为；注入时消息/元数据/压缩事件落事件日志）
        self._event_store = event_store
        # 工作区管理（对齐 DSH Workspace）：当前工作区根（空 = 进程 cwd 零回归）；
        # run 入口注入 contextvar 供工具相对路径/命令默认 cwd 跟随
        self.workspace_root: str = ""
        # 工作区注册表（factory 装配注入；web 层切换工作区入口）
        self.workspace_store: Any | None = None
        # 协调 inbox 监视器由 factory 可选装配；显式声明避免运行时 shape 依赖动态属性。
        self.inbox_watcher: Any | None = None
        # P0-5: per-session 运行状态表（停滞指纹/overflow/预警/快照/breakdown 按
        # session_id 分桶防并发污染；属性 shim 保持接口不变）。
        self._run_states: dict[str, _RunState] = {}
        self._run_states_guard = threading.Lock()
        # P0-5: 每会话 in-memory Session 绑定表（switch_model 等按 contextvar 解析
        # 本会话 sess，避免并发 run 互踩 override 回调；run finally 立即清理完整Session引用）
        self._run_sessions: dict[str, Any] = {}
        # P0-5: 最近活跃会话（out-of-run 时属性 shim 的回退锚点，保持 run 后复查语义）
        self._last_active_sid: str = ""
        # EVO-20260817 审查 P0-3: 同步 run 活跃会话集合——双向互斥防双 run 竞写
        # 会话文件（后台 start 检查不到同步 run → last-write-wins 丢消息）。
        self._sync_active: set[str] = set()
        self._sync_guard = threading.Lock()
        self._workspace_transition_guard = threading.RLock()  # run admission / workspace切换同门
        self._workspace_epoch = 0
        # accepted-boundary callback不扩展public API，也不依赖ContextVar。
        self._run_acquired_callbacks: dict[str, Any] = {}
        self._run_acquired_callbacks_guard = threading.Lock()
        # EVO-20260811-9ccdec97: 会话状态快照节流（上次快照注入时的消息数）—— P0-5 起经 shim 入 per-session 桶
        self._last_snapshot_count = 0
        # R4 增强: overflow 反馈注入次数（同一 run 内最多注入 1 次后让 AI 决策，第二次直接结束）
        self._overflow_reinject_count = 0
        # EVO-20260817-cef296f8 L2: 缓存命中率窗口监控（跨 run 累计，实例级；
        # 低命中率 → final_answer 注入诊断 + action_trace 审计，fail-open）
        # EVO-20260817-72fcd94a L3（闭环）: 缓存健康监控 + 发送前门禁（独立模块，程序常态锚点管理）
        from llm_loop.core.cache_health import CacheHealthMonitor
        self._cache_monitor = CacheHealthMonitor()
        self._err1210_init()  # err1210 P0 恢复状态字段（tasks 4.2；字段语义见 err1210.py）
        # 2026-08-22 任务聚焦状态（focus 模块: 单向切换锁定 + 任务锚点数据源）
        from llm_loop.core.loop.focus import TaskFocusState

        self._focus = TaskFocusState()
        # EVO-20260818（spec §5.4.1-3 注记，grill-me C1）: 模型切换检测——每轮对比实际
        # 模型，变化时 reset cache_health 窗口（防跨模型归因污染）
        self._cache_last_model: str | None = None  # 最近活跃模型（兼容诊断；切换判定不再用全局值）
        self._cache_last_model_by_session: dict[str, str] = {}  # 2026-08-27: 防跨会话模型状态污染
        self._cache_gate_stable_fp = ""  # 门禁: 本次稳定段指纹（system+注入）
        self._cache_gate_hint: str | None = None  # 门禁: 后检漂移提示（run 末注入 final_answer）
        # EVO-20260817-b6554376: 投影一致性门闸最近状态（ok/miss/mismatch；构建后更新）
        self._projection_guard_state: str = "miss"
        # M50: CLI --model 启动参数装配通道（cli.py 注入，_run_single/_run_interactive 消费）
        self._cli_startup_model: str | None = None
        # H-UI(2026-08-14): 动作观察者（实时 UI 状态条：thinking/tool_call/tool_result/answer/done）
        # None = 不通知（零回归）；观察者异常 fail-open 不影响主循环
        self._action_observer: Callable[[str, dict], None] | None = None


    # ── 主循环本体（public run_stream 生命周期包装见 lifecycle.py）──
    def _run_stream_inner(
        self, session_id: str, user_text: str, model: str | None = None,
        *, run_save_token: object | None = None, on_run_acquired: Any = None,
    ) -> Iterator[StreamDelta]:
        """run_stream 的循环本体（P0-5 包装层拆出；逻辑与拆分前逐行一致）."""
        # P0-5: 记录最近活跃会话（out-of-run 的属性 shim 回退锚点，保持测试复查语义）
        self._last_active_sid = session_id
        tool_trace: list[dict] = []
        # EVO-20260814-aab7eb0b P2: 每次 run/run_stream 重置实时停滞检测状态（跨会话不泄漏）
        # EVO-20260823-9bb27899: 增加搜索空结果计数字段
        self._stagnation_state = {
            "fp": None, "count": 0, "reminded": False,
            "empty_count": 0, "empty_reminded": False,
        }
        # HARNESS-04(2026-08-14): 上下文预算预警——每次 run 独立判断（上下文随 run 累积）
        self._context_warning_injected = False

        # 会话恢复（重启继续对话，DFX-REL-03）
        session_existed = self.session.exists(session_id)
        sess = self.session.load(session_id)
        if run_save_token is not None:
            self.session._bind_run_save_token(sess, run_save_token)
        accepted_changed = False
        if on_run_acquired is not None:
            try:
                on_run_acquired(sess)
                accepted_changed = True
            except TypeError:
                # BackgroundRunner.before_start 历史兼容：旧内部调用方可能仍传零参 callback。
                try:
                    on_run_acquired()
                    accepted_changed = True
                except Exception:  # noqa: BLE001 — accepted 辅助动作 fail-open
                    logger.warning("run accepted callback 失败（fail-open）", exc_info=True)
            except Exception:  # noqa: BLE001 — accepted 辅助动作 fail-open
                logger.warning("run accepted callback 失败（fail-open）", exc_info=True)

        if not session_existed:
            # 2026-08-20 (EVO-20260820-0b96348d, 用户决策): 新会话首轮仅重置活动窗口与
            # 模型游标（note_new_session），**保留模型桶**——桶是模型生命周期统计，
            # 跨会话/跨切换持久，保证连续切换模型对话时各模型命中率统计稳定连续。
            try:
                if self._cache_monitor is not None:
                    self._cache_monitor.note_new_session(session_id=session_id)
            except Exception:  # noqa: BLE001 — fail-open
                logger.debug("新会话缓存健康重置异常（fail-open）", exc_info=True)
            try:
                self.session.save(sess)
            except Exception as exc:
                # C1（PREFERENCE_1）: 会话持久化失败如实告知 AI，不静默——消息可能未落盘
                logger.warning("初始会话保存失败（fail-open）", exc_info=True)
                recovery_note = self._persist_with_recovery_note(
                    target_type="session",
                    source_id=sess.session_id,
                    write_fn=lambda: self.session.save(sess),
                    payload=self._session_payload(sess),
                    trigger_point="initial_save",
                )
                msg = self._fault_feedback("session_persistence", exc)
                if recovery_note:
                    msg = Message(
                        role=msg.role,
                        content=msg.content + f"\n{recovery_note}",
                        source=msg.source,
                    )
                sess.messages.append(msg)
                # D1: 系统注入消息事件（fail-open）
                self._append_message_event(sess, msg)
        elif accepted_changed:
            try:
                self.session.save(sess)
            except Exception:  # noqa: BLE001 — accepted 辅助持久化失败不阻断本次 run
                logger.warning("run accepted 状态持久化失败（fail-open）", exc_info=True)
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
            with self._run_states_guard:
                self._run_sessions[session_id] = sess

        # ── 消息进：构造用户消息并落库 ──
        user_msg = Message(role="user", content=user_text, source=MessageSource.USER)
        sess.messages.append(user_msg)
        # D1: 会话首次落库生成 session.created + 用户消息事件（fail-open）
        self._ensure_session_created(sess)
        self._append_message_event(sess, user_msg)
        self._inject_interruption_recovery(session_id, sess)
        _turn_ref = len(sess.messages) - 1  # user_msg seq（turn 身份）
        # T5: per-session RunState 分桶（串台修复）；tip 判断改 SoT 派生（tool_exec）
        self._current_turn_ref = _turn_ref
        _turn_memory_msgs = self._inject_turn_memory_snapshot(sess, user_text, _turn_ref)
        self._phase("ingress")

        final_answer = ""
        verification_note: str | None = None
        truncation_noted = False
        rounds = 0
        # DSH 借鉴(2026-08-17): run 结束原因（统一出口 run.end 事件用；各结束分支标记，
        # 默认 completed——未标记即正常完成。fail-open 不阻断）
        _run_end_reason = "completed"
        _run_started_at = time.monotonic()
        self._reset_overflow_state()  # R4: 每次 run 重置 overflow 注入计数
        self._focus.reset()  # 2026-08-22 单向切换锁定重置
        model_used = ""  # M51: 本轮实际使用的模型标签（每轮 LLM 调用时刷新）
        tokens_in = 0  # M52: 本次 run 累计 prompt tokens
        tokens_out = 0
        tokens_cache_hit = 0  # M58: 本次 run 前缀缓存命中 token（省钱可观测）
        llm_ms_total = 0.0  # M59: 本次 run LLM 调用总耗时（首 token 埋点聚合）
        ttft_first_ms: float | None = None  # M59: 首个 token 延迟（首 token 平均数据源）
        self._kpi_reset()  # EVO-20260822-9fde48f1 第 10 条: KPI 三件套重置（对比基线用）
        resp: Any = None  # M20 THK-04: 最终回答轮思考链来源（LLM 异常/停滞路径为 None）

        while True:
            # 后台 Stop：轮次边界兜底；LLM 流内另有细粒度检查。
            if _background_cancelled(self, session_id):
                _run_end_reason = "cancelled"
                final_answer = _CANCELLED_ANSWER
                break
            rounds += 1
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
            _round_registry, _default_registry, _planning_registry = (
                self._round_registry_snapshots(model, sess)
            )

            # M54: 模型窗口感知的主动压缩 — 先定模型标签, 再按其同一快照窗口收紧历史预算
            planned_label = self._planned_model_label(
                model, sess, registry_snapshot=_planning_registry
            )
            self._set_model_label_ctx(planned_label)
            effective_budget = self._effective_history_budget(
                planned_label, registry_snapshot=_planning_registry
            )
            # P0-B: 预算归因（architecture_status.context_usage.budget 消费）
            self._last_budget_info = self._effective_history_budget_detail(
                planned_label, registry_snapshot=_planning_registry
            )
            _tb = int(os.environ.get("TOOL_ROUND_BUDGET", "8000"))
            _last_tool = next((bool(getattr(m, "tool_calls", None))
                               for m in reversed(sess.messages) if m.role == "assistant"), False)
            _is_local_tool = _last_tool and planned_label.split("/", 1)[0] == "local"
            # 2026-08-24: 工具轮零历史开关 = env TOOL_ROUND_ZERO_HISTORY 显式 > provider 级
            # tool_round_zero_history 配置（local 已配 true → 工具轮极小窗口默认启用;
            # 云端不配 → False 零回归）。零历史 = 只发 system+工具 schema+最近完整协议
            # 配对组 → KV 前缀稳定命中 + prefill 秒级（本地实测 4-13 tokens prefill 0.2-0.8s）
            _zero_env = os.environ.get("TOOL_ROUND_ZERO_HISTORY")
            if _zero_env is None and _planning_registry is not None and "/" in planned_label:
                _spec_tmp = _planning_registry.providers.get(planned_label.split("/", 1)[0])
                _zero_env = "1" if (_spec_tmp is not None and _spec_tmp.tool_round_zero_history) else "0"
            _tool_round_zero = _is_local_tool and (_zero_env or "0") == "1"  # noqa: E501
            if _tool_round_zero:
                effective_budget = min(effective_budget, 4000)
            elif _tb > 0 and _is_local_tool:
                effective_budget = min(effective_budget, _tb)
            self._note_tool_round_budget(
                _tool_round_zero, _is_local_tool, _tb, effective_budget
            )
            if effective_budget < self._runtime_history_budget():
                self._record_action(
                    "understand.build_messages",
                    "model_aware_budget",
                    f"{planned_label}: {self._runtime_history_budget()}→{effective_budget}",
                )
            self._focus.anchor_sess = sess  # 2026-08-22 任务锚点数据源（build 注入包装用）
            # P0 压缩风暴熔断（2026-08-25 规格）: 冻结期超安全水位 → context_pressure
            # （实现在 _BuildMixin._breaker_pressure_block——engine 只接线）
            _pressure_block = self._breaker_pressure_block(
                sess, effective_budget, planned_label
            )
            if _pressure_block:
                _run_end_reason = "breaker_context_pressure"
                final_answer = _pressure_block
                break
            messages = self._build_llm_messages(
                sess, _turn_memory_msgs, max_chars=effective_budget, model=model,
                planned_label=planned_label, tool_round_zero=_tool_round_zero,
            )
            self._kpi_accumulate_inject()
            if getattr(self, "_last_history_compacted", False):
                truncation_noted = True
            tool_schemas = self.registry.schemas(lazy=self.settings.tool_schema_lazy)
            # EVO-20260817 本地模型工具精简（用户需求）: local provider 只注入
            # 固化白名单核心工具（固定前缀稳定 + prefill 大减），完整目录按需读取。
            tool_schemas = self._filter_local_tools(tool_schemas, planned_label)
            tools_param = [self._schema_to_param(t) for t in tool_schemas]

            # R1: 组件级占用分解（实际发送载荷口径；压缩归档历史不计入当前占用）
            # 供 architecture_status.context_usage.breakdown 注入；_last_build_info 保留。
            from llm_loop.core.history import compute_breakdown_from_dicts

            self._last_breakdown = compute_breakdown_from_dicts(
                messages,
                tool_schema_chars=len(_json_dumps_args({"tools": tools_param})),
                budget=effective_budget,
            )
            # EVO-20260818: 预算归属模型标注（防误读——provider 级预算如 minimax 40K
            # 与全局 1M 并存，AI 看到 ratio>1 需知 budget 属于哪个模型）
            self._last_breakdown["model"] = planned_label

            # ── 行动：LLM 决策 ──
            self._phase("action.llm_decide")
            # M53 拆分: 路由决策 + 上下文守卫 → _RoutingMixin._route_model（move 语义，行为零变化）
            routing = self._route_model(
                model, sess, messages, tools_param,
                registry_snapshot=_round_registry,
                default_registry_snapshot=_default_registry,
            )
            llm_client = routing.llm_client
            model_used = routing.model_used
            chat_model_arg = routing.chat_model_arg
            _response_context_limit = routing.context_limit
            _response_chars_per_token = routing.chars_per_token
            # EVO-20260818（spec §5.4.1-3 注记）: 模型切换 → cache_health 窗口重置
            # （PromptGuard 按 session/model 重置；cache_health 侧防跨模型归因污染）
            # 2026-08-20 (EVO-20260820-0b96348d, 用户决策): clear_buckets=False 保留模型桶——
            # 桶是模型生命周期统计，切换时不清（切回热检查、模型级累计跨切换持久）。
            # 2026-08-27: 模型切换必须按 session 判定。旧 `_cache_last_model` 是 Engine
            # 全局值，多会话交错使用不同模型时会把“别的会话刚用了 DeepSeek”误判成
            # “本会话从 DeepSeek 切到 GLM”，导致新会话也被塞入瞬时切换通知并断前缀。
            _sid = sess.session_id
            _switch_from = self._cache_last_model_by_session.get(_sid)
            if model_used and model_used != _switch_from:
                if _switch_from is not None:
                    self._cache_monitor.reset(
                        reason=f"model_switch:{model_used}", clear_buckets=False
                    )
                self._cache_last_model_by_session[_sid] = model_used
                self._cache_last_model = model_used  # 仅兼容最近活跃模型诊断
                self._inject_switch_notice(_switch_from or "", model_used, sess)
            elif model_used:
                self._cache_last_model = model_used
            if routing.final_answer_override is not None:
                # EVO-20260818（M53 拒绝逃生，防死循环）: 提交超模型窗口被拒时，AI 无 LLM
                # 调用无法自救（无法 switch_model/开新会话/调工具）——现场: 2a3385da 会话
                # 107 万字符超限连续拒绝 3+ 轮卡死。自动执行一次紧急压缩（emergency_compact:
                # head_keep=0 → 锚点前移归档，历史真正缩小），本轮如实告知，下轮提交正常。
                _escape_note = ""
                try:
                    self._build_llm_messages(
                        sess, _turn_memory_msgs, max_chars=effective_budget,
                        model=model, planned_label=planned_label, emergency_compact=True,
                    )
                    # EVO-20260825 任务8（§5.8）: 记录紧急压缩——供 switch_model 覆盖
                    # 检测（60s 内切模型 → wasted 审计：锚点前移归档白做）。
                    try:
                        self._cache_monitor.note_emergency_compact(
                            sess.session_id, effective_budget
                        )
                    except Exception:  # noqa: BLE001 — fail-open
                        logger.debug("emergency_compact 审计注入异常（fail-open）", exc_info=True)
                    _escape_note = (
                        "\n[自动压缩] 本次提交超模型窗口被守卫拦截——已自动执行紧急压缩"
                        "（放弃头部保留、锚点前移归档，信息零丢失可 search_archive 检索）；"
                        "下次请求将基于缩小后的历史正常发送。若仍超限建议 /model 切换更大窗口。"
                    )
                except Exception:  # noqa: BLE001 — 自动压缩失败 fail-open（保留原建议）
                    _escape_note = (
                        "\n[自动压缩失败] 紧急压缩未生效——请手动 /model 切换更大窗口模型"
                        "或 /new 开新会话（历史可经 search_archive 找回）。"
                    )
                _run_end_reason = "routing_override"
                final_answer = routing.final_answer_override + _escape_note
                break
            # HARNESS-02(2026-08-14): 每轮请求快照进事件日志（fail-open）——routing/fallback
            # 可能中途换模型，事件回放据此确知"当时用的哪个模型/挂了哪些工具/预算多少"，
            # 对 self_evaluate 溯源与回放诊断有帮助
            try:
                self._event_append(
                    session_id,
                    "request.meta",
                    {
                        "round": rounds,
                        # model_used 在无 pool 场景可能为空 → 回退装配模型名（如实标注）
                        "model": model_used or getattr(self.settings, "llm_model", ""),
                        "thinking": bool(self.settings.thinking_mode),
                        "reasoning_effort": str(
                            _current_reasoning_effort.get()
                            or getattr(llm_client, "reasoning_effort", "")
                        ),
                        "tools_count": len(tools_param),
                        "history_chars": sum(len(str(m.get("content", ""))) for m in messages),
                        "budget": effective_budget,
                        "projection_guard": getattr(self, "_projection_guard_state", "miss"),
                    },
                )
            except Exception:  # noqa: BLE001 — 快照失败 fail-open（不影响主循环）
                logger.debug("request.meta 事件写入失败（fail-open）")

            _cancelled_during_llm = False
            try:
                stream_fn = getattr(llm_client, "chat_stream", None)
                _llm_round_ms = 0.0
                # EVO-20260821-e172ed11 P0: 本地模型工具轮 thinking 降档（隐藏耗时大头——
                # thinking token 按 decode 逐 token 生成；工具轮仅需执行而非深度推理）。
                # _is_local_tool 已在循环内判定（本地 provider + 上轮 tool_calls）；仅本地生效，云端零影响。
                _effort_ctx_saved: str | None = None
                if stream_fn is not None and _is_local_tool and os.environ.get(
                    "TOOL_ROUND_THINKING_LOW", "1"
                ) == "1":
                    _effort_ctx_saved = _current_reasoning_effort.get()
                    _current_reasoning_effort.set("low")
                try:
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
                                compress_count_this_run=getattr(
                                    self, "_compress_count_this_run", 0
                                ),
                                history_budget=int(effective_budget or 0),
                                breaker_active=self._cache_monitor.breaker_active_for(
                                    session_id
                                ),
                                run_round=rounds,
                                provider=getattr(llm_client, "provider", ""),
                                model=chat_model_arg or getattr(llm_client, "model", ""),
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
                        partial_parts: list[str] = []  # P1-6: 流式部分回答累积（断连落盘用）
                        while True:
                            try:
                                d = next(it)
                                if _background_cancelled(self, session_id):
                                    _cancelled_during_llm = True
                                    _llm_round_ms = (time.perf_counter() - _llm_start) * 1000.0
                                    close_stream = getattr(it, "close", None)
                                    if callable(close_stream):
                                        try:
                                            close_stream()
                                        except Exception:  # noqa: BLE001 — 取消时释放流 fail-open
                                            logger.debug("LLM stream close 失败（fail-open）", exc_info=True)
                                    break
                                if not _ttft_done and getattr(d, "text", ""):
                                    _ttft_done = True
                                    ttft_first_ms = (time.perf_counter() - _llm_start) * 1000.0
                                if getattr(d, "text", ""):
                                    partial_parts.append(d.text)
                                yield d
                            except StopIteration as exc:
                                resp = exc.value
                                _llm_round_ms = (time.perf_counter() - _llm_start) * 1000.0
                                break
                            except GeneratorExit:
                                # P1-6(2026-08-15，审计发现 #17)：客户端断连——部分回答如实
                                # 落会话（中断标注不伪装完整）并立即保存，闭合"事件日志已追加
                                # 而 session JSON 未保存"的双轨漂移。
                                self._on_stream_disconnect(sess, partial_parts)
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
                                compress_count_this_run=getattr(
                                    self, "_compress_count_this_run", 0
                                ),
                                history_budget=int(effective_budget or 0),
                                breaker_active=self._cache_monitor.breaker_active_for(
                                    session_id
                                ),
                                run_round=rounds,
                                provider=getattr(llm_client, "provider", ""),
                                model=chat_model_arg or getattr(llm_client, "model", ""),
                            )
                        resp = llm_client.chat(**_chat_kwargs)
                        _llm_round_ms = (time.perf_counter() - _llm_sync_start) * 1000.0
                    if _background_cancelled(self, session_id):
                        _cancelled_during_llm = True
                finally:
                    # 恢复本请求的推理等级 context（无论正常/异常/断连）；不改共享 client。
                    if _effort_ctx_saved is not None:
                        _current_reasoning_effort.set(_effort_ctx_saved)
            except LLMError as exc:
                # 拷问⑥（2026-08-18）: cache_guard BLOCK——直接如实反馈 AI
                # （不重试/不走 overflow reinject——重试同样被拦=浪费循环；AI 需先
                # 压缩/换会话自救）
                from llm_loop.cache_guard.guard import CacheGuardBlockedError

                if isinstance(exc, CacheGuardBlockedError):
                    self._record_action("action.llm_decide", "guard_block", str(exc)[:200])
                    if self.status:
                        self.status.record_exception("guard_block", exc)
                    _run_end_reason = "guard_blocked"
                    final_answer = f"[缓存守卫拦截] {exc}\n\n建议：压缩 checkpoint 或换新会话后重试。"
                    break
                self._record_action("action.llm_decide", "llm_error", str(exc)[:200])
                if self.status:
                    self.status.record_exception("llm_call", exc)
                self._record_program_fault("llm_call")
                # M53 拆分: overflow 如实反馈（不自动重试/不自动压缩，决策权归 AI）
                # → _OverflowMixin._handle_overflow（move 语义，行为零变化）
                overflow_action, overflow_final = self._handle_overflow(
                    exc, sess, model_used,
                    model_window={"label": model_used, "context": _response_context_limit},
                )
                if overflow_action == "reinject":
                    continue  # 首次注入 system 消息让 AI 自主决策
                if overflow_action == "end" and overflow_final is not None:
                    _run_end_reason = "overflow"
                    final_answer = overflow_final
                    self._err1210_note_defer_lost(session_id, "overflow")  # 二阶失败观测
                    break
                # ── err1210 P0（tasks 4.3）: compact 首请求 1210 定向降级重试（mixin 封装，
                # 编排与控制流语义见 err1210.py；恢复成功 → 新 resp 走下方正常路径，
                # 失败 → 原样继续既有错误链；env ERR1210_RECOVERY=0 完全旁路）──
                _e1210_recovered, resp, _llm_round_ms = self._err1210_attempt_recovery(
                    exc=exc, sess=sess, messages=messages, tools_param=tools_param,
                    llm_client=llm_client, chat_model_arg=chat_model_arg,
                    session_id=session_id, current_resp=resp, current_round_ms=_llm_round_ms,
                )
                # ── M49（design §5.4）: 降级逻辑 ──
                # 仅当当前模型为默认装配（sess.model_override is None 且 per-call override 也为 None）
                # 才沿 fallback 链尝试；会话显式 override（含用户/AI 经 switch_model 选择）=
                # 严格模式,失败直接如实反馈不降级（design §5.4 行为规则表核心）。
                # 4xx (非 429) 不降级：请求本身有问题,换模型无用（design §5.4 行为表注）。
                is_default_assembled = (
                    sess.model_override is None and chat_model_arg is None
                )
                if not _e1210_recovered and is_default_assembled and self._is_fallback_eligible_error(exc):
                    _fallback_metadata: dict[str, Any] = {}
                    fallback_resp, inject_msgs, fallback_ref = self._try_fallback_chain(
                        messages=messages, tools=tools_param,
                        timeout_s=self._runtime_timeout(), primary_error=exc,
                        session_id=sess.session_id, run_round=rounds,
                        metadata_out=_fallback_metadata,
                    )
                    # 注入降级提示到主消息流（AI 可见, design 原则 2）
                    for m in inject_msgs:
                        sess.messages.append(m)
                        # D1: 系统注入消息事件（fail-open）
                        self._append_message_event(sess, m)
                    if fallback_resp is not None:
                        # 降级成功: 响应以新模型运行, 进入后续正常路径
                        resp = fallback_resp
                        if fallback_ref:
                            model_used = fallback_ref  # M51: 如实标注为降级后的模型
                        _response_context_limit, _response_chars_per_token = self._merge_fallback_metadata(
                            _fallback_metadata, _response_context_limit, _response_chars_per_token
                        )
                    else:
                        # 链全失败 → 已注入汇总提示, 走原异常如实反馈路径
                        from llm_loop.feedback.honesty import llm_error_text

                        _run_end_reason = "llm_error"
                        final_answer = llm_error_text(exc)
                        resp = None  # 程序反馈不得继承上一轮成功响应的 reasoning（GPT 审计 P0：stale reasoning 嫁接）
                        self._err1210_note_defer_lost(session_id, "fallback_exhausted")  # 二阶失败观测
                        break
                elif not _e1210_recovered:
                    # 严格模式 / 非降级错误 → 如实反馈（DFX-REL-02）
                    from llm_loop.feedback.honesty import llm_error_text

                    _run_end_reason = "llm_error"
                    final_answer = llm_error_text(exc)
                    resp = None  # 程序反馈不得继承上一轮成功响应的 reasoning（GPT 审计 P0：stale reasoning 嫁接）
                    self._err1210_note_defer_lost(session_id, "llm_error")  # 二阶失败观测（spec 5.1.3-5）
                    break

            if _cancelled_during_llm:
                _run_end_reason = "cancelled"
                final_answer = _CANCELLED_ANSWER
                resp = None  # 防止上一轮响应残留参与 usage/reasoning/finalize
                break

            self._record_action("action.llm_decide", "llm_response", self._resp_summary(resp))
            self._err1210_note_request_count(session_id, len(messages))  # T4.2: 骤降兜底数据源（仅成功轮更新，语义见 err1210.py）
            # M52: 聚合本轮 token 用量（含 fallback 成功响应；0 = provider 未提供）
            tokens_in += resp.prompt_tokens
            tokens_out += resp.completion_tokens
            tokens_cache_hit += resp.prompt_cache_hit_tokens
            llm_ms_total += _llm_round_ms
            self._kpi_accumulate_llm(planned_label, _llm_round_ms)
            # DSH 借鉴(2026-08-17): 本轮响应 usage 明细落盘（fail-open）——命中/miss
            # token 逐轮可审计，命中率实时可算（不依赖 CSV 账单/流式 M58 盲区）。
            try:
                _req_usage_available = bool(resp.prompt_tokens)
                self._event_append(
                    session_id,
                    "request.usage",
                    {
                        "round": rounds,
                        "model": model_used or getattr(self.settings, "llm_model", ""),
                        "tokens_in": resp.prompt_tokens,
                        "tokens_out": resp.completion_tokens,
                        "cache_hit": resp.prompt_cache_hit_tokens,
                        "cache_miss": max(0, resp.prompt_tokens - resp.prompt_cache_hit_tokens),
                        "usage_available": _req_usage_available,
                    },
                )
            except Exception:  # noqa: BLE001 — usage 明细失败 fail-open（不影响主循环）
                logger.debug("request.usage 事件写入失败（fail-open）")

            # 2026-08-24 缓存窗口镜像（cache.window 事件）: 把服务端 cached_tokens
            # （前缀命中 token 数）映射回提交载荷的消息级窗口——缓存覆盖到哪条消息、
            # 哪些是新增（miss 区）。供 architecture_status 观察 + 信息补充决策
            # （引用缓存区内信息零额外 prefill; 新增信息尾部追加保持命中; 中插/压缩断前缀）。
            try:
                from llm_loop.core.cache_window import describe_cache_window

                _win = describe_cache_window(
                    messages, resp.prompt_cache_hit_tokens, resp.prompt_tokens,
                    # EVO-20260824: 缓存边界换算与估算同源（provider 级 chars_per_token）
                    chars_per_token=_response_chars_per_token,
                )
                self._last_cache_window = _win
                self._event_append(
                    session_id,
                    "cache.window",
                    {
                        "round": rounds,
                        "model": model_used or getattr(self.settings, "llm_model", ""),
                        "cached_tokens": _win.cached_tokens,
                        "prompt_tokens": _win.prompt_tokens,
                        "hit_ratio": round(_win.hit_ratio, 4),
                        "boundary_chars": _win.boundary_chars,
                        "boundary_msg_index": _win.boundary_msg_index,
                        "cached_msgs": _win.cached_msgs,
                        "new_msgs": _win.new_msgs,
                        "summary": _win.summary(),
                    },
                )
            except Exception:  # noqa: BLE001 — 窗口镜像失败 fail-open（不影响主循环）
                logger.debug("cache.window 事件写入失败（fail-open）")

            # 无工具调用 → 最终回答 → 真诚回答阶段
            if not resp.tool_calls:
                self._kpi_note_no_tool()
                self._phase("honest_answer")
                # H-UI: 进入回答生成
                self._notify_action("answer")
                final_answer = resp.content or ""
                # M41 修复: 回答被截断（truncated=True）时不执行声明-回执校验——
                # 不完整内容校验不可靠（会误报"声明与回执不符"），截断如实透传标注
                if resp.truncated:
                    truncation_noted = True
                # ── 声明-回执轻量提醒（T38: 诚实性交 AI 自主，程序仅提供事实提醒，不强制更正重入）──
                if final_answer.strip() and not resp.truncated:
                    tool_msgs = [m for m in sess.messages if m.role == "tool"]
                    if self.validator:
                        check = self.validator.check(final_answer, tool_msgs)
                        if not check.consistent:
                            verification_note = build_discrepancy_feedback(check)
                            # 注入一条如实提示（不重入循环），最终回答直接输出
                            reminder = Message(
                                # 可见化（EVO-20260823-xxx）: system+injected_system 标记会被
                                # history.py _is_injected_system/skip_injected_system 剔除——
                                # 程序自我提醒但 LLM 不可见（诚实率上不去根因）。改 user role
                                # 尾部追加（对齐 GATE_NOTE 转 user 模式），user role 天然绕过
                                # 过滤（_is_injected_system 只判 system），LLM 可见且前缀稳定。
                                role="user",
                                content=f"[声明提醒] 你的最终回答中存在与工具回执不符的完成声明，请知悉（不影响本次输出，后续请如实声明）。\n{verification_note}",
                                source=MessageSource.USER,
                                metadata={},  # 不再打推送式注入标记（user role 已天然可见）
                            )
                            sess.messages.append(reminder)
                            # D1: 系统注入消息事件（fail-open）
                            self._append_message_event(sess, reminder)
                break

            # ── 行动：执行工具（tool_calls）──
            # M53 拆分: 工具段 → _ToolExecMixin._execute_tools（yield from 保持 tool_round 外泄次序）
            yield from self._execute_tools(resp, sess, rounds, tool_trace)

            # ── EVO-20260814-aab7eb0b P2: 实时停滞熔断（连续同指纹工具调用，如实结束）──
            _should_break, _tool_name, _streak = self._stagnation_should_break()
            if _should_break:
                self._phase("terminate.stagnation")
                _run_end_reason = "stagnation"
                final_answer = stagnation_feedback(
                    _tool_name, _streak, [t["name"] for t in tool_trace]
                ).content
                self._record_action("stagnation.break", "terminated", f"{_tool_name} x{_streak}")
                break

            # ── M56 收敛（ANALYSIS-20260811-loop-strategy-branch-inventory）:
            # 每轮末信号检测统一为一次调用（自评/演进待办/待审提醒，均仅提示不强制，
            # 触发判断与决策交 AI 自主——RULE-AI-10 每轮自主检查清单）──
            self._check_loop_signals(sess, rounds)

            # ── R10: 轮数预警（达 80% 注入一次，AI 可 adjust_strategy 调大自救）──
            # 程序只如实告知事实（剩余轮数），"继续/调大/收尾"决策归 AI（RULE-AI-00）
            _budget = self._runtime_max_iterations()
            if (
                not getattr(self, "_round_warning_injected", False)
                and _budget >= 10
                and rounds >= int(_budget * 0.8)
            ):
                self._round_warning_injected = True
                warning = max_iterations_warning_message(rounds, _budget)
                warning.metadata = {**warning.metadata, "injected_system": True}  # P1-7: 推送式注入标记
                sess.messages.append(warning)
                # D1: 系统注入消息事件（fail-open）
                self._append_message_event(sess, warning)
                self._record_action("round.warning", "injected", f"{rounds}/{_budget}")

            # ── HARNESS-04(2026-08-14): 上下文预算预警（占用率≥80% 注入一次）──
            # 程序只如实告知事实（占用率/预算），"压缩/收尾"决策归 AI（RULE-AI-00，
            # 程序不自动压缩历史——压缩只由 AI 主动触发）
            _bd = getattr(self, "_last_breakdown", None)
            _ratio = (_bd or {}).get("ratio")
            # 2026-08-22: 快模型（9B fast_model 轮）不注入预警——其上下文本就精简,
            # 预警是噪音（实证 98605ad7: 9B 收到预警后分心"处理预算"导致任务漂移）
            _is_fast_round = (
                "qwythos" in str(model_used)
                or (model_used or "").split("/", 1)[-1].startswith("qwythos")
            )
            if (
                not self._context_warning_injected
                and _ratio is not None
                and _ratio >= 0.8
                and not _is_fast_round
            ):
                self._context_warning_injected = True
                _used = (_bd or {}).get("total", {}).get("chars", 0)
                _budget_chars = (_bd or {}).get("budget", 0)
                _pct = round(_ratio * 100)
                warning = Message(
                    role="system",
                    content=(
                        f"[预算预警] 当前上下文组装占用已达注入预算的 {_pct}%"
                        f"（约 {_used:,}/{_budget_chars:,} 字符）。注：此为历史/工具结果"
                        "组装上限（非模型窗口，模型窗口远大于此，见 architecture_status."
                        "context_usage.model_window），推理能力不受限；超出部分已归档可检索、"
                        "信息零丢失。程序不会自动压缩历史；是否压缩归档/收尾由你自主决策"
                        "（RULE-AI-00）。"
                    ),
                    source=MessageSource.SYSTEM,
                    metadata={"injected_system": True},  # P1-7: 推送式注入标记
                )
                sess.messages.append(warning)
                # D1: 系统注入消息事件（fail-open）
                self._append_message_event(sess, warning)
                self._record_action("context.warning", "injected", f"{_pct}%")

            # ── 轮数上限（2026-08-15 强化：耗尽先给 AI 一次归因/续跑决策轮）──
            # 决策轮仅一次（per-session 标志）：AI 调 adjust_strategy 调大（≤500）→
            # 下轮预算重估自然续跑；AI 纯文本归因 → 走正常最终回答路径收尾；
            # AI 未调大仍耗竭 → 罐装 [已达轮数上限] 如实终止（程序兜底边界不变）。
            if rounds >= _budget:
                if not self._exhaustion_decision_used:
                    self._exhaustion_decision_used = True
                    decision = max_iterations_decision_message(rounds, _budget)
                    sess.messages.append(decision)
                    # D1: 系统注入消息事件（fail-open）
                    self._append_message_event(sess, decision)
                    self._record_action(
                        "round.exhaustion", "decision_requested", f"{rounds}/{_budget}"
                    )
                    continue  # 给 AI 一个决策轮（下一轮 LLM 调用可见该消息）
                self._phase("terminate.max_iterations")
                _run_end_reason = "max_iterations"
                final_answer = max_iterations_feedback([t["name"] for t in tool_trace]).content
                break

        # ── 记住：沉淀记忆（不阻塞回答输出，FR-LOOP-03）──
        self._phase("remember")
        self._remember(final_answer, session_id, sess)
        # T33: 独立记忆提取定期触发（异步，不阻塞回答输出 DFX-PERF-04）
        if self.extractor is not None:
            try:
                self.extractor.maybe_trigger(session_id)
            except Exception:
                logger.warning("独立提取触发失败（fail-open）", exc_info=True)

        # P0-B1（2026-08-28 批准）: 程序反馈语义分离——错误/熔断/守卫/耗尽类文本
        # source=SYSTEM（非模型产出的如实标注；防下轮模型误读"assistant 已回答过"，
        # 并作为 extractor 过滤/投影标记的判定依据）。正常回答保持 USER 不变
        # （M51/M52 token 统计依赖零破坏）。
        from llm_loop.feedback.honesty import PROGRAM_FEEDBACK_PREFIXES

        _pf_source = (
            MessageSource.SYSTEM
            if final_answer.startswith(PROGRAM_FEEDBACK_PREFIXES)
            else MessageSource.USER
        )
        sess.messages.append(
            Message(
                role="assistant",
                content=final_answer,
                source=_pf_source,
                # M51/M52: 模型 + 本轮 run token 消耗持久化（web/feishu 页脚数据源）
                model_used=model_used,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                tokens_cache_hit=tokens_cache_hit,
                llm_ms=llm_ms_total,
                ttft_ms=ttft_first_ms or 0.0,
            )
            if final_answer
            else Message(role="assistant", content="（无回答输出）", source=_pf_source)
        )
        # M20 THK-04: 最终回答轮 assistant 消息也回传思考链（官方"后续所有请求"语义，防下一轮 400）
        if final_answer and resp is not None and resp.reasoning_content:
            last = sess.messages[-1]
            last.reasoning_content = resp.reasoning_content
        # D1: 最终回答消息事件（fail-open）
        self._append_message_event(sess, sess.messages[-1])
        # M12 深化 T65: run 完成里程碑自我评估提醒（仅提示不强制，EVAL-03；追加后随会话保存）
        self._check_eval_trigger(sess, rounds, milestone=True)
        # T39: 会话保存异常 → 如实标注 + 不抛穿（程序故障不影响 AI 发挥）
        try:
            self.session.save(sess)
        except Exception as exc:  # noqa: BLE001
            logger.warning("会话保存失败（fail-open）: %s", exc)
            self._record_program_fault("session_persist")
            recovery_note = self._persist_with_recovery_note(
                target_type="session",
                source_id=sess.session_id,
                write_fn=lambda: self.session.save(sess),
                payload=self._session_payload(sess),
                trigger_point="loop_end_save",
            )
            extra = f" {recovery_note}" if recovery_note else ""
            _run_end_reason = "session_save_failed"
            final_answer = (
                f"{final_answer}\n\n[程序异常] 会话保存失败（{type(exc).__name__}: {exc}）。"
                f"本次回答仍有效，但历史可能未持久化。{extra}"
            )
        self._phase("done")
        # EVO-20260817-cef296f8 L1b: 耗尽注入的 system 消息 run 结束后标记 consumed
        # （[轮次决策请求]/[已达轮数上限] 不在 _INJECTED_SYSTEM_PREFIXES，注入后进请求
        # system 区使前缀分叉 → 后续所有 run 持续 MISS；run 内 AI 决策需可见，run 结束
        # 后消费掉，下个 run 构建时跳过 → 前缀恢复稳定。fail-open 不影响 run。）
        try:
            for m in sess.messages:
                if m.role != "system":
                    continue
                c = m.content or ""
                if c.startswith("[轮次决策请求]") or c.startswith("[已达轮数上限]"):
                    md = dict(m.metadata or {})
                    if not md.get("consumed"):
                        md["consumed"] = True
                        m.metadata = md
        except Exception:  # noqa: BLE001 — 消费标记失败不阻断 run
            logger.warning("耗尽消息消费标记异常（fail-open）", exc_info=True)
        # EVO-20260817-72fcd94a L3: 缓存健康闭环（fail-open；实现在 _BuildMixin）
        final_answer = self._post_run_cache_health(
            final_answer, sess, tokens_in, tokens_cache_hit, model_used
        )
        # P1-1(2026-08-15): run 末事件日志滚动检查钩子（大小/天数触发；fail-open 不阻断）
        self._check_event_rotate(session_id)
        # H-UI: 循环结束（状态条可收尾）
        self._notify_action("done")

        # P0-1: 记忆访问统计（decay_score/access_count/last_access_at）落盘——
        # search() 仅更新内存，此处每轮 run 完成批量持久化（低频，避免每轮检索全量写盘）
        try:
            if self.memory is not None:
                self.memory.flush()
        except Exception as exc:  # noqa: BLE001 — 统计落盘失败不阻断 run
            logger.warning("记忆统计落盘失败（fail-open）: %s", exc)
            recovery_note = self._persist_with_recovery_note(
                target_type="memory_stats",
                source_id="memory",
                write_fn=lambda: self.memory.flush() if self.memory is not None else None,
                payload=self._memory_payload(),
                trigger_point="memory_flush",
            )
            if recovery_note:
                logger.warning("记忆统计恢复通道: %s", recovery_note)

        # DSH 借鉴(2026-08-17): run 生命周期结束事件（对齐 DSH turn/end reason）——
        # 统一出口落盘，结束原因/轮数/token 汇总/耗时一次可查（fail-open 不阻断）
        try:
            self._event_append(
                session_id,
                "run.end",
                {
                    "session_id": session_id,
                    "reason": _run_end_reason,
                    "rounds": rounds,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "cache_hit": tokens_cache_hit,
                    "duration_ms": int((time.monotonic() - _run_started_at) * 1000),
                    "model_used": model_used,
                    "truncated": truncation_noted,
                    "answer_preview": (final_answer or "")[:200],
                    **self._kpi_snapshot(),
                },
            )
        except Exception:  # noqa: BLE001 — run.end 失败 fail-open（不影响返回）
            logger.debug("run.end 事件写入失败（fail-open）")

        # EVO-20260820-5bf342ae ②: 长回答落盘（实现抽 events.py _persist_long_answer,
        # 防 engine 膨胀守卫 1136——2026-08-21 内联版触顶后抽取）
        final_answer = self._persist_long_answer(session_id, final_answer or "")

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
        )

    # M53 拆分: 模型路由辅助方法族 → llm_loop/core/loop/routing.py（_RoutingMixin）
    # 迁移注释保留（test_silent_pass_cleanup 源码断言）: 模型标签 resolve 失败时回退裸名（fail-open），
    # 行为与迁移前一致；有 pool 时经注册表 resolve 为全限定 ref。
    # 已随迁方法（经 Mixin 混入后实例可调用，签名/语义不变）:
    #   _default_model_label / _current_context_limit / _check_context_fit / _planned_model_label / _effective_history_budget
    # 估算常量 _CHARS_PER_TOKEN_EST/_CONTEXT_SAFETY_MARGIN 经模块级 re-export 保持原路径可导入。

    # M53 拆分: 工具辅助方法 → llm_loop/core/loop/tool_exec.py（_ToolExecMixin）
    # 已随迁方法（经 Mixin 混入后实例可调用，签名/语义不变）:
    #   _schema_to_param / _resp_summary / _record_tool_history
    # 模块级函数 _json_dumps_args/_tool_args_summary 经模块级 re-export 保持原路径可导入。

    # 生命周期/持久化包装已迁至 lifecycle.py（_LifecycleMixin）。

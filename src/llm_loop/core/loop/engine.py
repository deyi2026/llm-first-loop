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
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from llm_loop.config import Settings

# M53 拆分: 职责 mixin（signals 信号检查 / runtime 运行时参数 / fallback 模型降级链 / routing 模型路由 / overflow overflow 处理 / tool_exec 工具执行）
from llm_loop.core.loop.archive import _ArchiveMixin
from llm_loop.core.loop.fallback import _FallbackMixin
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
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.prompt import build_system_prompt
from llm_loop.core.run_context import current_session_id as _current_session_id
from llm_loop.core.session import SessionStore
from llm_loop.event_log.model import build_message_payload
from llm_loop.feedback.honesty import (
    max_iterations_decision_message,
    max_iterations_feedback,
    max_iterations_warning_message,
    stagnation_feedback,
)
from llm_loop.feedback.validator import DeclarationValidator, build_discrepancy_feedback
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.events import ArchitectureEvent, ArchitectureEventType
from llm_loop.introspection.status import ArchitectureStatusProvider
from llm_loop.llm.client import LLMClient, StreamDelta
from llm_loop.llm.errors import LLMError
from llm_loop.memory.extract import extract_memory_blocks, memory_blocks_to_entries
from llm_loop.memory.retrieve import build_memory_messages
from llm_loop.memory.store import MemoryStore
from llm_loop.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

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

class LoopEngine(_RunStateMixin, _SignalsMixin, _RuntimeParamsMixin, _FallbackMixin, _RoutingMixin, _OverflowMixin, _ToolExecMixin, _ArchiveMixin):
    """五阶段核心循环控制器."""

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
        # P0-5(2026-08-15): per-session 运行状态表（审计发现 #7 可重入修复）——
        # 停滞指纹/overflow 计数/预警标志/快照节流/breakdown 按 session_id 分桶，
        # 跨会话并发 run 不再共享污染。属性 shim（下方）保持既有读写接口不变。
        self._run_states: dict[str, _RunState] = {}
        self._run_states_guard = threading.Lock()
        # P0-5: 每会话 in-memory Session 绑定表（switch_model 等按 contextvar 解析
        # 本会话 sess，避免并发 run 互踩 override 回调；会话数级内存占用，不实清理）
        self._run_sessions: dict[str, Any] = {}
        # P0-5: 最近活跃会话（out-of-run 时属性 shim 的回退锚点，保持 run 后复查语义）
        self._last_active_sid: str = ""
        # EVO-20260811-9ccdec97: 会话状态快照节流（上次快照注入时的消息数）—— P0-5 起经 shim 入 per-session 桶
        self._last_snapshot_count = 0
        # R4 增强: overflow 反馈注入次数（同一 run 内最多注入 1 次后让 AI 决策，第二次直接结束）
        self._overflow_reinject_count = 0
        # M50: CLI --model 启动参数装配通道（cli.py 注入，_run_single/_run_interactive 消费）
        self._cli_startup_model: str | None = None
        # H-UI(2026-08-14): 动作观察者（实时 UI 状态条：thinking/tool_call/tool_result/answer/done）
        # None = 不通知（零回归）；观察者异常 fail-open 不影响主循环
        self._action_observer: Callable[[str, dict], None] | None = None

    def set_action_observer(self, fn: Callable[[str, dict], None] | None) -> None:
        """H-UI: 注入/移除动作观察者.

        事件: ("thinking", {"round": N}) / ("tool_call", {"tool_name", "args_summary"})
        / ("tool_result", {"tool_name", "status"}) / ("answer", {}) / ("done", {})。
        观察者同步调用（引擎线程内），异常 fail-open；传 None 移除。
        """
        self._action_observer = fn

    def _record_program_fault(self, kind: str) -> None:
        """R2/A6: 程序故障计数（fail-open 聚合，AI 经 architecture_status 感知）."""
        try:
            if self.status is not None:
                self.status.record_program_fault(kind)
        except Exception:  # noqa: BLE001 — 计数失败 fail-open
            pass

    def _notify_action(self, event_type: str, **payload) -> None:
        """动作事件通知（fail-open：观察者异常/缺失均不阻断主循环）."""
        fn = self._action_observer
        if fn is None:
            return
        try:
            fn(event_type, payload)
        except Exception:  # noqa: BLE001 — 观察者异常不影响 AI 发挥
            logger.debug("动作观察者异常（fail-open）: %s", event_type)

    # ── D1 事件源化辅助（fail-open：禁用/异常如实记录，不抛穿主循环）──

    def _event_append(self, session_id: str, event_type: str, payload: dict) -> None:
        """D1 事件写入（fail-open：未注入/禁用/异常均如实 warning，不抛穿主循环）."""
        store = getattr(self, "_event_store", None)
        if store is None or getattr(store, "enabled", False) is False:
            return
        try:
            store.append(session_id, event_type, payload)
        except Exception as exc:  # noqa: BLE001 — 事件写入失败不阻断循环（fail-open）
            logger.warning("事件写入失败（fail-open）: %s", exc)
            self._record_program_fault("event_write")

    def _ensure_session_created(self, sess) -> None:
        """会话首次落库时生成 session.created（顶层字段快照，缺失如实置空）."""
        store = getattr(self, "_event_store", None)
        if store is None or getattr(store, "enabled", False) is False:
            return
        try:
            if store.exists(sess.session_id):
                return
            payload = {
                "version": sess.to_dict().get("version", 4),
                "title": sess.title,
                "created_at": sess.created_at,
                "updated_at": sess.updated_at,
                "status": sess.status,
                "parent_id": sess.parent_id,
                "branch_id": sess.branch_id,
                "branch_summary": sess.branch_summary,
                "model_override": sess.model_override,
                "pinned": sess.pinned,
                "channel": sess.channel,
            }
            store.append(sess.session_id, "session.created", payload)
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.warning("session.created 事件写入失败（fail-open）: %s", exc)

    def _append_message_event(self, sess, msg: Message) -> None:
        """消息落库点事件（payload 与 Session.to_dict() 消息字段逐一对齐）."""
        store = getattr(self, "_event_store", None)
        if store is None or getattr(store, "enabled", False) is False:
            return
        try:
            store.append(
                sess.session_id,
                "message.appended",
                build_message_payload(
                    index=len(sess.messages) - 1,
                    role=msg.role,
                    content=msg.content,
                    source=msg.source.value,
                    tool_call_id=msg.tool_call_id,
                    status=msg.status.value if msg.status else None,
                    tool_name=msg.tool_name,
                    error_detail=msg.error_detail,
                    tool_calls=msg.tool_calls,
                    reasoning_content=msg.reasoning_content,
                    metadata=msg.metadata,
                ),
            )
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.warning("message.appended 事件写入失败（fail-open）: %s", exc)

    def _resolve_msg_seq(self, session_id: str, msg: Message) -> int | None:
        """尽力定位消息在会话中的序号（tool_call_id 优先，其次内容匹配；失败如实 None）.

        P1-7(2026-08-15, 性能): 压缩归档对每条消息调用本方法（大会话数百次），
        原实现每次 session.load 读盘——优先用 run 中已绑定的内存会话（P0-5
        _run_sessions），miss 才回退磁盘 load（零行为差异，快 2-3 个数量级）。
        """
        try:
            sess = self._run_sessions.get(session_id) or self.session.load(session_id)
            for i, m in enumerate(sess.messages):
                if msg.tool_call_id and m.tool_call_id == msg.tool_call_id:
                    return i
            for i, m in enumerate(sess.messages):
                if m.role == msg.role and m.content == msg.content:
                    return i
        except Exception:  # noqa: BLE001 — 定位失败如实 None
            pass
        return None

    # ── 阶段记录（架构自省）──
    def _phase(self, phase: str) -> None:
        if self.status:
            self.status.record_phase(phase)

    def _record_action(self, phase: str, action_type: str, detail: str) -> None:
        if self.status:
            self.status.record_action(phase, action_type, detail)

    def _report(
        self,
        event_type: ArchitectureEventType,
        fact: str,
        reason: str,
        suggestion: str,
    ) -> Message | None:
        """推送式架构上报（冷却去重）；返回可注入消息或 None."""
        if self.status is None or not self.status.enabled:
            return None
        event = ArchitectureEvent(
            event_type=event_type, fact=fact, reason=reason, suggestion=suggestion
        )
        if self.status.report_event(event):
            return self.status.build_report_message(event)
        return None

    # ── 主入口 ──
    def run_stream(
        self, session_id: str, user_text: str, model: str | None = None
    ) -> Iterator[StreamDelta]:
        """单条用户消息的完整循环（流式）：逐 content delta yield，结束返回 LoopResult.

        model: 可选，本次对话覆盖使用的 LLM 模型（None 用装配模型，Web 模型切换用）。
        与 run 共享同一核心，唯一差异是每轮 LLM 调用处走 chat_stream 并外泄 delta。

        P0-5: contextvar 在包装层 set/reset——run 存续期（含客户端断连 GeneratorExit）
        当前执行上下文归属本会话；结束后复位，避免残留泄漏到复用线程的无关代码。
        run 后可读性由 `_run_state()` 的 `_last_active_sid` 回退保留（测试复查语义）。
        """
        # SSE/ASGI 消费方可能在不同 Context 中驱动本生成器（Token.reset 要求同一
        # Context，跨 Context 抛 ValueError）——改用 值快照 + set 还原（set 不挑 Context）。
        _prev_sid = _current_session_id.get()
        _current_session_id.set(session_id)
        try:
            return (yield from self._run_stream_inner(session_id, user_text, model))
        finally:
            _current_session_id.set(_prev_sid)

    def _run_stream_inner(
        self, session_id: str, user_text: str, model: str | None = None
    ) -> Iterator[StreamDelta]:
        """run_stream 的循环本体（P0-5 包装层拆出；逻辑与拆分前逐行一致）."""
        # P0-5: 记录最近活跃会话（out-of-run 的属性 shim 回退锚点，保持测试复查语义）
        self._last_active_sid = session_id
        tool_trace: list[dict] = []
        # EVO-20260814-aab7eb0b P2: 每次 run/run_stream 重置实时停滞检测状态（跨会话不泄漏）
        self._stagnation_state = {"fp": None, "count": 0, "reminded": False}
        # HARNESS-04(2026-08-14): 上下文预算预警——每次 run 独立判断（上下文随 run 累积）
        self._context_warning_injected = False

        # 会话恢复（重启继续对话，DFX-REL-03）
        sess = self.session.load(session_id)
        if not self.session.exists(session_id):
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
        self._phase("ingress")

        final_answer = ""
        verification_note: str | None = None
        truncation_noted = False
        rounds = 0
        self._reset_overflow_state()  # R4 增强: 每次 run 重置 overflow 注入计数
        model_used = ""  # M51: 本轮实际使用的模型标签（每轮 LLM 调用时刷新）
        tokens_in = 0  # M52: 本次 run 累计 prompt tokens
        tokens_out = 0  # M52: 本次 run 累计 completion tokens
        resp: Any = None  # M20 THK-04: 最终回答轮思考链来源（LLM 异常/停滞路径为 None）

        while True:
            rounds += 1
            if self.runtime is not None:
                self.runtime.reset_round()
            # H-UI: 每轮思考开始（实时状态条）
            self._notify_action("thinking", round=rounds)
            self._phase("comprehension")
            if self.status:
                self.status.record_llm_round()

            # ── 理解：记忆检索 + 上下文构造 ──
            memory_msgs: list[Message] = []
            try:
                memory_msgs = build_memory_messages(
                    user_text,
                    self.memory,
                    top_k=self._runtime_memory_top_k(),  # M57 配置面收敛: 动态优先（AI 可调）
                    semantic_retriever=self.semantic_retriever,  # M11 T45: 语义路径接线
                )
            except Exception as exc:  # noqa: BLE001 — 记忆失败不阻塞（FR-MEM-03）
                memory_msgs = [self._fault_feedback("memory", exc)]
                self._record_program_fault("memory")

            # M54: 模型窗口感知的主动压缩 — 先定模型标签, 再按其窗口收紧历史预算
            planned_label = self._planned_model_label(model, sess)
            effective_budget = self._effective_history_budget(planned_label)
            if effective_budget < self._runtime_history_budget():
                self._record_action(
                    "understand.build_messages",
                    "model_aware_budget",
                    f"{planned_label}: {self._runtime_history_budget()}→{effective_budget}",
                )
            messages = self._build_llm_messages(sess, memory_msgs, max_chars=effective_budget, model=model)
            if len(messages) < len(sess.messages) + len(memory_msgs) + 1:
                truncation_noted = True
            tool_schemas = self.registry.schemas(lazy=self.settings.tool_schema_lazy)
            tools_param = [self._schema_to_param(t) for t in tool_schemas]

            # R1: 计算组件级占用分解（含 tool_schema_chars，供 architecture_status.context_usage.breakdown 注入）
            # 口径: **实际发送载荷**（构建后 messages）而非原始会话——已压缩归档的历史
            # 不再计入"当前占用"（旧口径在本地慢模型收紧预算后会把占用虚高数十倍，
            # 误导 [预算预警]/AI 压缩决策）。_last_build_info 保留（其他消费方兼容）。
            from llm_loop.core.history import compute_breakdown_from_dicts

            self._last_breakdown = compute_breakdown_from_dicts(
                messages,
                tool_schema_chars=len(_json_dumps_args({"tools": tools_param})),
                budget=effective_budget,
            )

            # ── 行动：LLM 决策 ──
            self._phase("action.llm_decide")
            # M53 拆分: 路由决策 + 上下文守卫 → _RoutingMixin._route_model（move 语义，行为零变化）
            routing = self._route_model(model, sess, messages, tools_param)
            llm_client = routing.llm_client
            model_used = routing.model_used
            chat_model_arg = routing.chat_model_arg
            if routing.final_answer_override is not None:
                final_answer = routing.final_answer_override
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
                        "reasoning_effort": str(getattr(self.settings, "reasoning_effort", "")),
                        "tools_count": len(tools_param),
                        "history_chars": sum(len(str(m.get("content", ""))) for m in messages),
                        "budget": effective_budget,
                    },
                )
            except Exception:  # noqa: BLE001 — 快照失败 fail-open（不影响主循环）
                logger.debug("request.meta 事件写入失败（fail-open）")
            try:
                stream_fn = getattr(llm_client, "chat_stream", None)
                if stream_fn is not None:
                    it = stream_fn(
                        messages=messages,
                        tools=tools_param,
                        timeout_s=self._runtime_timeout(),
                        model=chat_model_arg,
                    )
                    partial_parts: list[str] = []  # P1-6: 流式部分回答累积（断连落盘用）
                    while True:
                        try:
                            d = next(it)
                            if getattr(d, "text", ""):
                                partial_parts.append(d.text)
                            yield d
                        except StopIteration as exc:
                            resp = exc.value
                            break
                        except GeneratorExit:
                            # P1-6(2026-08-15，审计发现 #17)：客户端断连——部分回答如实
                            # 落会话（中断标注不伪装完整）并立即保存，闭合"事件日志已追加
                            # 而 session JSON 未保存"的双轨漂移。
                            self._on_stream_disconnect(sess, partial_parts)
                            raise
                else:
                    # 无 chat_stream 的客户端（如测试 FakeLLM）→ 同步 chat（不 yield，行为与 run 一致）
                    resp = llm_client.chat(
                        messages=messages,
                        tools=tools_param,
                        timeout_s=self._runtime_timeout(),
                        model=chat_model_arg,
                    )
            except LLMError as exc:
                self._record_action("action.llm_decide", "llm_error", str(exc)[:200])
                if self.status:
                    self.status.record_exception("llm_call", exc)
                self._record_program_fault("llm_call")
                # M53 拆分: overflow 如实反馈（不自动重试/不自动压缩，决策权归 AI）
                # → _OverflowMixin._handle_overflow（move 语义，行为零变化）
                overflow_action, overflow_final = self._handle_overflow(exc, sess, model_used)
                if overflow_action == "reinject":
                    continue  # 首次注入 system 消息让 AI 自主决策
                if overflow_action == "end" and overflow_final is not None:
                    final_answer = overflow_final
                    break
                # ── M49（design §5.4）: 降级逻辑 ──
                # 仅当当前模型为默认装配（sess.model_override is None 且 per-call override 也为 None）
                # 才沿 fallback 链尝试；会话显式 override（含用户/AI 经 switch_model 选择）=
                # 严格模式,失败直接如实反馈不降级（design §5.4 行为规则表核心）。
                # 4xx (非 429) 不降级：请求本身有问题,换模型无用（design §5.4 行为表注）。
                is_default_assembled = (
                    sess.model_override is None and chat_model_arg is None
                )
                if is_default_assembled and self._is_fallback_eligible_error(exc):
                    fallback_resp, inject_msgs, fallback_ref = self._try_fallback_chain(
                        messages=messages,
                        tools=tools_param,
                        timeout_s=self._runtime_timeout(),
                        primary_error=exc,
                        session_id=sess.session_id,
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
                    else:
                        # 链全失败 → 已注入汇总提示, 走原异常如实反馈路径
                        from llm_loop.feedback.honesty import llm_error_text

                        final_answer = llm_error_text(exc)
                        break
                else:
                    # 严格模式 / 非降级错误 → 如实反馈（DFX-REL-02）
                    from llm_loop.feedback.honesty import llm_error_text

                    final_answer = llm_error_text(exc)
                    break

            self._record_action("action.llm_decide", "llm_response", self._resp_summary(resp))
            # M52: 聚合本轮 token 用量（含 fallback 成功响应；0 = provider 未提供）
            tokens_in += resp.prompt_tokens
            tokens_out += resp.completion_tokens

            # 无工具调用 → 最终回答 → 真诚回答阶段
            if not resp.tool_calls:
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
                                role="system",
                                content=f"[声明提醒] 你的最终回答中存在与工具回执不符的完成声明，请知悉（不影响本次输出，后续请如实声明）。\n{verification_note}",
                                source=MessageSource.SYSTEM,
                                metadata={"injected_system": True},  # P1-7: 推送式注入标记
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
            if (
                not self._context_warning_injected
                and _ratio is not None
                and _ratio >= 0.8
            ):
                self._context_warning_injected = True
                _used = (_bd or {}).get("total", {}).get("chars", 0)
                _budget_chars = (_bd or {}).get("budget", 0)
                _pct = round(_ratio * 100)
                warning = Message(
                    role="system",
                    content=(
                        f"[预算预警] 当前上下文占用已达预算的 {_pct}%"
                        f"（约 {_used:,}/{_budget_chars:,} 字符）。程序不会自动压缩历史；"
                        f"是否压缩归档/收尾由你自主决策（RULE-AI-00）。"
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

        sess.messages.append(
            Message(role="assistant", content=final_answer, source=MessageSource.USER)
            if final_answer
            else Message(role="assistant", content="（无回答输出）", source=MessageSource.USER)
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
            final_answer = (
                f"{final_answer}\n\n[程序异常] 会话保存失败（{type(exc).__name__}: {exc}）。"
                f"本次回答仍有效，但历史可能未持久化。{extra}"
            )
        self._phase("done")
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
            reasoning_content=resp.reasoning_content if resp is not None else None,
        )

    def run(self, session_id: str, user_text: str, model: str | None = None) -> LoopResult:
        """单条用户消息的完整循环（run_stream 的同步聚合包装，签名/返回不变）.

        model: 可选，本次对话覆盖使用的 LLM 模型（None 用装配模型，Web 模型切换用）。
        """
        it = self.run_stream(session_id, user_text, model)
        while True:
            try:
                next(it)
            except StopIteration as exc:
                return exc.value

    def run_single(self, user_text: str, model: str | None = None) -> LoopResult:
        """B5(2026-08-14) 一次性便捷入口：自动创建新会话并执行完整循环.

        外部嵌入（examples/01 模式）无需手动 session.create()；等价于
        `run(create(), text)`。会话按正常路径落盘（可 list/search 追溯）。
        """
        session_id = self.session.create()
        return self.run(session_id, user_text, model=model)

    def close(self) -> None:
        """P2-4(2026-08-15): 释放底层 LLM 客户端连接（httpx）.

        优先关闭 llm_pool（默认 client + provider 缓存一次全部释放）；
        pool 未装配（None）时关闭装配默认 client（self.llm）。
        duck-typing getattr 防御（无 close 的可注入实现跳过）；
        幂等（可重复调用，httpx.Client.close 幂等）+ fail-open
        （关闭异常记 warning 不抛穿，避免影响停机流程）。
        """
        target = self.llm_pool if self.llm_pool is not None else self.llm
        closer = getattr(target, "close", None)
        if closer is None:
            return
        try:
            closer()
        except Exception as exc:  # noqa: BLE001 — 关闭失败 fail-open
            logger.warning("LLM 客户端关闭失败（fail-open）: %s", exc)

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

    def _build_llm_messages(
        self, sess, memory_msgs: list[Message], max_chars: int | None = None,
        model: str | None = None,  # P1-7: per-call 模型覆盖（判定本地 provider 跳过推送式注入）
    ) -> list[dict]:
        """构造提交 LLM 的消息序列（system prompt + 记忆注入 + 历史 + 压缩另存）.

        M54: max_chars 可覆盖默认预算（模型窗口感知压缩）；None = 运行时预算（零回归）。
        P1-10: 窗口锚定——按 provider 固定历史起点（只追加不挤旧, 超预算优先降级中段),
        前缀稳定命中引擎/服务端缓存; 锚点写入 sess.history_anchors 随会话持久化。
        """
        planned_label = self._planned_model_label(model, sess)
        provider_id = planned_label.partition("/")[0] or "default"
        anchors = sess.history_anchors or {}
        sess_anchor = int(anchors.get(provider_id, 0) or 0)
        system_prompt = build_system_prompt()
        # 记忆消息作为前置注入
        base = [m for m in memory_msgs] + list(sess.messages)
        prefix_len = len(memory_msgs)
        # EVO-20260811-9ccdec97: 会话状态快照节流——每间隔注入状态帧（定位锚点，fail-open）
        # M58 配置面收敛: 间隔走 runtime（动态优先，AI 可调）
        # P1-10: 仅无锚时注入（锚定后快照为推送式注入（已打标被跳过提交）, 且避免锚点换算复杂化）
        if sess_anchor == 0:
            try:
                interval = self._runtime_extract_interval()
                if len(sess.messages) - self._last_snapshot_count >= interval:
                    evo_summary = None
                    if self.evolution_store is not None and hasattr(self.evolution_store, "summary"):
                        try:
                            s = self.evolution_store.summary()
                            evo_summary = s if isinstance(s, dict) else None
                        except Exception:
                            evo_summary = None
                    snapshot = Message(
                        role="system",
                        content=build_session_snapshot_text(
                            len(sess.messages), self.memory.count(), evo_summary
                        ),
                        source=MessageSource.SYSTEM,
                        metadata={"injected_system": True},  # P1-7: 快照=推送式注入（本地 provider 下不进提交）
                    )
                    base.insert(0, snapshot)
                    prefix_len += 1
                    self._last_snapshot_count = len(sess.messages)
            except Exception:
                import logging

                logging.getLogger(__name__).warning("会话状态快照注入失败（fail-open）", exc_info=True)
        from llm_loop.core.history import build_history_messages

        archive_sink = None
        if self.archive is not None:
            archive_sink = self._archive_sink
        # R1: 存构建中间值，供主循环在 tools_param 构造后计算 breakdown（含 tool_schema_chars）
        effective_budget = max_chars if max_chars is not None else self._runtime_history_budget()
        self._last_build_info = {
            "base": base,
            "system_prompt": system_prompt,
            "memory_msgs": memory_msgs,
            "budget": effective_budget,
        }
        # P1-10: 锚点相对传入列表 = 会话锚点 + 前置（memory/快照）长度
        anchor_arg = sess_anchor + prefix_len if sess_anchor > 0 else 0
        anchor_box: list[int] = []
        built = build_history_messages(
            base,
            system_prompt,
            max_chars=max_chars if max_chars is not None else self._runtime_history_budget(),
            session_id=sess.session_id,
            archive_sink=archive_sink,
            # RULE-AI-00: 不再传 summarizer（压缩路径不自动 LLM 摘要，AI 主动触发）
            layer_tool_trim=getattr(self.settings, "tool_trim_enabled", False),  # EVO-20260811-7baa2737: 历史分层降级
            tool_trim_age=getattr(self.settings, "tool_trim_age", 0),  # R3: 0=自适应
            tool_trim_threshold=getattr(self.settings, "tool_trim_threshold", 8000),  # EVO-A: 降级长度阈值（默认 8000）
            reasoning_tail=getattr(self.settings, "reasoning_tail", 2),  # M66 思考链瘦身
            # P1-7: provider（inject_system_notices=false）跳过推送式注入 → system 前缀静态 → 引擎缓存命中
            skip_injected_system=not self._provider_inject_notices(planned_label),
            # P1-10: 窗口锚定
            history_anchor=anchor_arg,
            anchor_out=anchor_box,
        )
        # P1-10: 锚点推进持久化（换算回会话索引, clamp 防御）
        if anchor_box:
            new_anchor = anchor_box[0] - prefix_len
            new_anchor = max(0, min(len(sess.messages), new_anchor))
            # 2026-08-16 锚点推进对齐工具轮边界（现场：tool_call_id is not found 根因）：
            # 锚点不得落在声明↔回执组内——若锚点处是 tool 回执（其声明在锚点前），
            # 拉回至该轮声明起点（整组保留，防孤儿回执）。
            while 0 < new_anchor < len(sess.messages) and sess.messages[new_anchor].role == "tool":
                new_anchor -= 1
            if sess.history_anchors is None:
                sess.history_anchors = {}
            sess.history_anchors[provider_id] = new_anchor
        return built

    def _persist_with_recovery_note(
        self,
        *,
        target_type: str,
        source_id: str,
        write_fn: Any,
        payload: str,
        trigger_point: str,
    ) -> str:
        """P2-2: 调 RecoveryChannel.persist_with_recovery 并返回标注文本.

        self.recovery 为 None 时返回空串（零回归）。
        """
        if self.recovery is None:
            return ""
        try:
            receipt = self.recovery.persist_with_recovery(
                target_type=target_type,
                source_id=source_id,
                write_fn=write_fn,
                payload=payload,
                trigger_point=trigger_point,
            )
        except Exception:  # noqa: BLE001 — 恢复通道自身失败不中断主循环
            logger.warning("恢复通道异常（fail-open）", exc_info=True)
            return "[恢复通道异常] 重试/备份均未完成"
        if receipt.status == "retried_ok":
            return f"[恢复通道] 已重试 {receipt.retries} 次后成功落盘"
        if receipt.status == "backed_up":
            return f"[恢复通道] 重试 {receipt.retries} 次仍失败，已备份 {receipt.backup_id}"
        return f"[恢复通道] 重试 {receipt.retries} 次仍失败，备份也失败: {receipt.error}"

    def _session_payload(self, sess: Any) -> str:
        """构造会话 JSON 原文（备份用，不摘要/改写/压缩）."""
        import json as _json

        return _json.dumps(sess.to_dict(), ensure_ascii=False, indent=2)

    def _memory_payload(self) -> str:
        """构造记忆索引 JSON 原文（备份用，不摘要/改写/压缩）."""
        import json as _json

        if self.memory is None:
            return "[]"
        return _json.dumps(
            [e.to_dict() for e in self.memory._entries],  # noqa: SLF001
            ensure_ascii=False,
            indent=2,
        )

    def _fault_feedback(self, component: str, exc: Exception) -> Message:
        """程序辅助组件故障增强反馈（M12 T49; M17 FR-REVIEW-AI-03 拆至 loop_feedback.py）."""
        from llm_loop.feedback.loop_feedback import build_fault_feedback_message

        return build_fault_feedback_message(
            component,
            exc,
            fault_classifier=self.fault_classifier,
            selfheal_budget=self.selfheal_budget,
            audit_dir=self.settings.audit_dir,
        )

    def _set_session_override(self, sess, value: str | None) -> None:
        """M48（design §5.3）: switch_model 调用的会话 override 写入回调.

        直接修改 in-memory sess（引用已加载的 Session 对象）, loop 末 self.session.save(sess)
        会自动持久化。失败由 tools_model.run_switch_model 内部捕获并如实回执。
        """
        sess.model_override = value
        if self.correction_ctx is not None:
            self.correction_ctx.session_model_override = value

    def _resolve_session_binding(self, session_id: str):
        """P0-5: 按会话解析 switch_model 绑定（getter/setter），供 registry_model 经
        contextvar 定位本会话 sess——并发 run 各自写自己的 Session 对象.
        会话不在活跃绑定表（非 run 期间调用）→ None，调用方回退 ctx 环境字段.
        """
        with self._run_states_guard:
            sess = self._run_sessions.get(session_id)
        if sess is None:
            return None
        return (
            lambda: sess.model_override,
            lambda value: self._set_session_override(sess, value),
        )

    def _check_event_rotate(self, session_id: str) -> None:
        """P1-1: run 末事件日志滚动检查（fail-open；未接线/未启用零行为）."""
        store = self._event_store
        if store is None:
            return
        try:
            store.check_rotate(session_id)
        except Exception:  # noqa: BLE001 — 滚动检查失败不影响 run 结果
            logger.warning("事件日志滚动检查失败（fail-open）: sid=%s", session_id, exc_info=True)

    def _on_stream_disconnect(self, sess, partial_parts: list[str]) -> None:
        """P1-6(2026-08-15，审计发现 #17)：LLM 流式中客户端断连（GeneratorExit）的落盘处理.

        部分回答如实落会话（中断标注，不伪装完整）+ 事件双轨同步 + 立即保存——
        闭合"事件日志已追加而 session JSON 未保存"的双轨漂移。保存失败 fail-open。
        """
        partial = "".join(partial_parts).strip()
        note = "\n[对话已中断] 客户端断连，以上为不完整部分回答（如实标注，可能截断于任意位置）。"
        content = (partial + note) if partial else "[对话已中断] 客户端断连，本回合未产生回答内容。"
        msg = Message(role="assistant", content=content, source=MessageSource.SYSTEM)
        sess.messages.append(msg)
        try:
            self._append_message_event(sess, msg)  # 双轨：事件同步（fail-open 内置）
            self.session.save(sess)
        except Exception:  # noqa: BLE001 — 断连保存失败不抛穿（生成器关闭路径）
            logger.warning("断连会话保存失败（fail-open）: sid=%s", sess.session_id, exc_info=True)

    def _remember(self, final_answer: str, session_id: str, sess) -> None:
        """解析最终回答的记忆块并落盘（FR-MEM-01/03，失败不阻塞）."""
        if not final_answer.strip():
            return
        try:
            blocks = extract_memory_blocks(final_answer)
            if not blocks:
                return
            entries, failures = memory_blocks_to_entries(
                blocks,
                session_id=session_id,
                message_id=str(len(sess.messages)),
            )
            for e in entries:
                e.deposit_path = "inline"  # T33: 即时沉淀标记
                self.memory.save_entry(e)
            if failures:
                logger.warning(
                    "记忆块解析失败 %d 条（如实记录，不丢弃回答）: %s", len(failures), failures[:2]
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("记忆沉淀失败（不阻塞主循环）: %s", exc)

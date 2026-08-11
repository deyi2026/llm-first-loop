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
from dataclasses import dataclass, field
from typing import Any

from llm_loop.config import Settings
from llm_loop.core.message import Message, MessageSource, ToolResult
from llm_loop.core.prompt import build_system_prompt
from llm_loop.core.session import SessionStore
from llm_loop.feedback.honesty import (
    max_iterations_feedback,
)
from llm_loop.feedback.validator import DeclarationValidator, build_discrepancy_feedback
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.events import ArchitectureEvent, ArchitectureEventType
from llm_loop.introspection.status import ArchitectureStatusProvider, ToolHistoryItem
from llm_loop.llm.client import LLMClient, LLMResponse
from llm_loop.llm.errors import LLMError
from llm_loop.memory.extract import extract_memory_blocks, memory_blocks_to_entries
from llm_loop.memory.retrieve import build_memory_messages
from llm_loop.memory.store import MemoryStore
from llm_loop.tools.registry import ToolRegistry, tool_result_to_message

logger = logging.getLogger(__name__)


def _json_dumps_args(arguments: dict) -> str:
    """工具参数序列化为 JSON 字符串（FC 协议 function.arguments 要求）."""
    import json as _json

    try:
        return _json.dumps(arguments, ensure_ascii=False)
    except TypeError:
        return "{}"


@dataclass
class LoopResult:
    """一次 run() 的完整结果（如实交付用户，design.md §2.2.2.3）."""

    session_id: str
    final_answer: str
    verification_note: str | None = None  # 声明-回执校验差异说明
    rounds: int = 0
    tool_calls: list[dict] = field(default_factory=list)  # 工具声明轨迹（审计）
    truncated: bool = False


class LoopEngine:
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
    def run(self, session_id: str, user_text: str, model: str | None = None) -> LoopResult:
        """单条用户消息的完整循环（消息进→理解→行动→真诚回答→记住）.

        model: 可选，本次对话覆盖使用的 LLM 模型（None 用装配模型，Web 模型切换用）。
        """
        tool_trace: list[dict] = []

        # 会话恢复（重启继续对话，DFX-REL-03）
        sess = self.session.load(session_id)
        if not self.session.exists(session_id):
            try:
                self.session.save(sess)
            except Exception:  # noqa: BLE001 — T39: 存储故障不阻断
                logger.warning("初始会话保存失败（fail-open）", exc_info=True)
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

        # ── 消息进：构造用户消息并落库 ──
        user_msg = Message(role="user", content=user_text, source=MessageSource.USER)
        sess.messages.append(user_msg)
        self._phase("ingress")

        final_answer = ""
        verification_note: str | None = None
        truncation_noted = False
        rounds = 0
        resp: Any = None  # M20 THK-04: 最终回答轮思考链来源（LLM 异常/停滞路径为 None）

        while True:
            rounds += 1
            if self.runtime is not None:
                self.runtime.reset_round()
            self._phase("comprehension")
            if self.status:
                self.status.record_llm_round()

            # ── 理解：记忆检索 + 上下文构造 ──
            memory_msgs: list[Message] = []
            try:
                memory_msgs = build_memory_messages(
                    user_text,
                    self.memory,
                    top_k=self.settings.memory_top_k,
                    semantic_retriever=self.semantic_retriever,  # M11 T45: 语义路径接线
                )
            except Exception as exc:  # noqa: BLE001 — 记忆失败不阻塞（FR-MEM-03）
                memory_msgs = [self._fault_feedback("memory", exc)]

            messages = self._build_llm_messages(sess, memory_msgs)
            if len(messages) < len(sess.messages) + len(memory_msgs) + 1:
                truncation_noted = True
            tool_schemas = self.registry.schemas(lazy=self.settings.tool_schema_lazy)
            tools_param = [self._schema_to_param(t) for t in tool_schemas]

            # ── 行动：LLM 决策 ──
            self._phase("action.llm_decide")
            # M48（design §5.3）: 路由决策——
            # - per-call Web model（run() 参数）优先级最高（Web 临时覆盖，ephemeral），用默认 client + chat(model=...)
            # - 否则按会话级 model_override 经 pool 路由（switch_model 设置，持久生效）
            # - pool 未装配（None）→ 用默认 client（零回归）
            chat_model_arg = model  # per-call Web override（None 表示不覆盖）
            if chat_model_arg is None and self.llm_pool is not None:
                # 会话级 override 路由：取 switch_model 写入的覆盖
                try:
                    llm_client = self.llm_pool.get_client(sess.model_override)
                except ValueError as exc:
                    # resolve 失败（override 在 refresh_config 后失效等）：如实反馈，走默认 client
                    self._record_action("action.llm_decide", "pool_resolve_failed", str(exc)[:200])
                    llm_client = self.llm
            else:
                llm_client = self.llm
            try:
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
                # 如实反馈异常（DFX-REL-02），不再伪造；M18 AA15: 统一三件套文本
                from llm_loop.feedback.honesty import llm_error_text

                final_answer = llm_error_text(exc)
                break

            self._record_action("action.llm_decide", "llm_response", self._resp_summary(resp))

            # 无工具调用 → 最终回答 → 真诚回答阶段
            if not resp.tool_calls:
                self._phase("honest_answer")
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
                            )
                            sess.messages.append(reminder)
                break

            # ── 行动：执行工具（tool_calls）──
            self._phase("action.tool_loop")
            # 约束 C1 配对: 先把 LLM 声明追加为 assistant 消息（带 tool_calls），
            # 后续 tool 回执才有前置声明（严格 API 要求，否则 400）
            if resp.tool_calls:
                assistant_decl = Message(
                    role="assistant",
                    content=resp.content or "",
                    source=MessageSource.USER,
                    tool_calls=[
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": _json_dumps_args(tc.arguments),
                            },
                        }
                        for tc in resp.tool_calls
                    ],
                    reasoning_content=resp.reasoning_content,  # M20 THK-04: 工具轮回传思考链
                )
                sess.messages.append(assistant_decl)
            for tc in resp.tool_calls:
                if not tc.id:
                    # 约束 C1: 缺 id 声明不可执行，如实注入反馈（AI-first 三件套）
                    msg = Message(
                        role="system",
                        content=(
                            f"[工具调用异常] 事实: 声明缺少 tool_call_id，无法绑定执行（工具 '{tc.name}'）。\n"
                            f"原因: 程序不伪造执行无绑定标识的声明（协议约束）。\n"
                            f"建议: 请重新声明工具调用（确保原生 tool_calls 含 id 字段）。"
                        ),
                        source=MessageSource.SYSTEM,
                    )
                    sess.messages.append(msg)
                    self._record_action("action.tool_loop", "missing_tool_call_id", tc.name)
            # EVO-20260810-750e985a: 工具并发控制（只读并行/修改串行/按声明顺序回写）
            valid_calls = [tc for tc in resp.tool_calls if tc.id]
            if valid_calls:
                results = self.registry.execute_many(valid_calls)
                for tc, result in zip(valid_calls, results, strict=False):
                    tool_trace.append({"id": tc.id, "name": tc.name, "arguments": tc.arguments})
                    self._record_tool_history(result)
                    tool_msg = tool_result_to_message(
                        result, failure_guidance_enabled=self.registry.failure_guidance_enabled
                    )
                    sess.messages.append(tool_msg)

            # ── M12 深化 T65: 自我评估触发检测（每轮末，仅提示不强制）──
            self._check_eval_trigger(sess, rounds)
            # ── M17 FR-REVIEW-AI-02: executing 演进待办提醒（每轮末，仅提示不强制）──
            self._check_evolution_executing(sess)
            # ── EVO-20260810-86e777d1: pending_review 演进弹窗提醒（每轮末）──
            self._check_pending_review(sess)

            # ── 轮数上限（如实结束，T38: 进展判断交 AI 自主，程序仅保留此硬边界）──
            if rounds >= self._runtime_max_iterations():
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
        # M12 深化 T65: run 完成里程碑自我评估提醒（仅提示不强制，EVAL-03；追加后随会话保存）
        self._check_eval_trigger(sess, rounds, milestone=True)
        # T39: 会话保存异常 → 如实标注 + 不抛穿（程序故障不影响 AI 发挥）
        try:
            self.session.save(sess)
        except Exception as exc:  # noqa: BLE001
            logger.warning("会话保存失败（fail-open）: %s", exc)
            final_answer = (
                f"{final_answer}\n\n[程序异常] 会话保存失败（{type(exc).__name__}: {exc}）。"
                "本次回答仍有效，但历史可能未持久化。"
            )
        self._phase("done")

        return LoopResult(
            session_id=session_id,
            final_answer=final_answer,
            verification_note=verification_note,
            rounds=rounds,
            tool_calls=tool_trace,
            truncated=truncation_noted,
        )

    # ── 辅助 ──
    def _build_llm_messages(self, sess, memory_msgs: list[Message]) -> list[dict]:
        """构造提交 LLM 的消息序列（system prompt + 记忆注入 + 历史 + 压缩另存）."""
        system_prompt = build_system_prompt()
        # 记忆消息作为前置注入
        base = [m for m in memory_msgs] + list(sess.messages)
        from llm_loop.core.history import build_history_messages

        archive_sink = None
        if self.archive is not None:
            archive_sink = self._archive_sink
        return build_history_messages(
            base,
            system_prompt,
            max_chars=self._runtime_history_budget(),
            session_id=sess.session_id,
            archive_sink=archive_sink,
            summarizer=self.summarizer,  # EVO-9794797e: 主动压缩（旧消息语义摘要）
        )

    def _check_eval_trigger(self, sess, rounds: int, *, milestone: bool = False) -> None:
        """自我评估触发检测（T63/T65: 每轮末 + run 完成里程碑）.

        M16 审计（FR-AUDIT-AI-04/08）: 只保留 periodic/milestone 两个确定性触发；
        M17 FR-REVIEW-AI-03: 检测逻辑搬移至 introspection/loop_signals.py（薄壳委托）。
        命中且冷却通过 → 注入 [自我评估提醒]（仅提示不强制，EVAL-03；决策权归 LLM）。
        """
        if self.loop_signal_detector is None:
            return
        event = self.loop_signal_detector.check_eval_trigger(sess, rounds, milestone=milestone)
        if event is None:
            return
        msg = self._report(
            event.event_type, fact=event.fact, reason=event.reason, suggestion=event.suggestion
        )
        if msg is not None:
            sess.messages.append(msg)

    def _check_evolution_executing(self, sess) -> None:
        """M17 FR-REVIEW-AI-02: executing 演进待办提醒（每轮末，仅提示不强制）.

        复用 EventReporter 冷却（key 含 fact 前缀去重）；无 executing / 读取失败 → 不注入。
        """
        if self.loop_signal_detector is None or self.status is None or not self.status.enabled:
            return
        event = self.loop_signal_detector.check_evolution_executing(self.evolution_store)
        if event is None:
            return
        msg = self._report(
            event.event_type, fact=event.fact, reason=event.reason, suggestion=event.suggestion
        )
        if msg is not None:
            sess.messages.append(msg)

    def _check_pending_review(self, sess) -> None:
        """EVO-20260810-86e777d1: pending_review 演进弹窗提醒（每轮末，仅提示不强制）.

        复用 EventReporter 冷却；无 pending_review / 读取失败 → 不注入。
        """
        if self.loop_signal_detector is None or self.status is None or not self.status.enabled:
            return
        event = self.loop_signal_detector.check_pending_review(self.evolution_store)
        if event is None:
            return
        msg = self._report(
            event.event_type, fact=event.fact, reason=event.reason, suggestion=event.suggestion
        )
        if msg is not None:
            sess.messages.append(msg)

    def _runtime_max_iterations(self) -> int:
        """轮数上限（PARAM-01: 动态优先、静态兜底）."""
        if self.runtime is not None:
            return self.runtime.max_iterations
        return self.settings.max_iterations

    def _runtime_history_budget(self) -> int:
        """上下文注入预算（PARAM-01: 动态优先、静态兜底）."""
        if self.runtime is not None:
            return self.runtime.history_max_chars
        return self.settings.history_max_chars

    def _runtime_timeout(self) -> float | None:
        """LLM 调用超时（PARAM-01: 动态优先、静态兜底）."""
        if self.runtime is not None:
            return self.runtime.llm_timeout_s
        return None

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

    def _archive_sink(self, session_id: str, msg: Message) -> None:
        """压缩另存回调（T22）: 将被丢弃的消息原文完整另存到 ArchiveStore."""
        if self.archive is None:
            return
        try:
            entry = self.archive.archive(
                session_id,
                role=msg.role,
                source=msg.source.value,
                content=msg.content,
                tool_name=msg.tool_name,
                tool_call_id=msg.tool_call_id,
                status=msg.status.value if msg.status else None,
            )
            # T28: LLM 摘要（SUMMARY_MODE 配置；off 走确定性，sync/async 由 Summarizer 处理）
            if self.summarizer is not None and entry is not None:
                self.summarizer.summarize_archive(entry.id, msg.content, self.archive)
        except Exception:
            logger.warning("压缩另存/摘要失败（fail-open）", exc_info=True)

    def _schema_to_param(self, t: dict) -> dict:
        return {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }

    def _resp_summary(self, resp: LLMResponse) -> str:
        if resp.tool_calls:
            return "tool_calls=" + ",".join(t.name for t in resp.tool_calls)
        return f"content={resp.content[:80] if resp.content else '(空)'}"

    def _record_tool_history(self, result: ToolResult) -> None:
        if self.status:
            self.status.record_tool_history(
                ToolHistoryItem(
                    name=result.tool_name,
                    arguments={},
                    status=result.status,
                    summary=result.content[:120],
                    duration_ms=result.duration_ms,
                )
            )

    def _set_session_override(self, sess, value: str | None) -> None:
        """M48（design §5.3）: switch_model 调用的会话 override 写入回调.

        直接修改 in-memory sess（引用已加载的 Session 对象）, loop 末 self.session.save(sess)
        会自动持久化。失败由 tools_model.run_switch_model 内部捕获并如实回执。
        """
        sess.model_override = value
        if self.correction_ctx is not None:
            self.correction_ctx.session_model_override = value

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

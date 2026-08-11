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
    model_unavailable_text,
)
from llm_loop.feedback.validator import DeclarationValidator, build_discrepancy_feedback
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.events import ArchitectureEvent, ArchitectureEventType
from llm_loop.introspection.status import ArchitectureStatusProvider, ToolHistoryItem
from llm_loop.llm.client import LLMClient, LLMResponse
from llm_loop.llm.errors import (
    LLMError,
    LLMHTTPError,
    LLMNetworkError,
    LLMTimeoutError,
    is_overflow_error,
)
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


def format_tokens(n: int) -> str:
    """M52: token 计数人性化显示（1234 → "1.2k"）；0 = 未提供，如实返回 "0"."""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


# M53: 上下文守卫估算口径（chars/token 保守估计, 中文混合内容约 2 字符/token）
_CHARS_PER_TOKEN_EST = 2
# 安全边距: 预留 10% 给响应生成
_CONTEXT_SAFETY_MARGIN = 0.9


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
        # EVO-20260811-9ccdec97: 会话状态快照节流（上次快照注入时的消息数）
        self._last_snapshot_count = 0

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
            except Exception as exc:
                # C1（PREFERENCE_1）: 会话持久化失败如实告知 AI，不静默——消息可能未落盘
                logger.warning("初始会话保存失败（fail-open）", exc_info=True)
                sess.messages.append(self._fault_feedback("session_persistence", exc))
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
        model_used = ""  # M51: 本轮实际使用的模型标签（每轮 LLM 调用时刷新）
        tokens_in = 0  # M52: 本次 run 累计 prompt tokens
        tokens_out = 0  # M52: 本次 run 累计 completion tokens
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
                    top_k=self._runtime_memory_top_k(),  # M57 配置面收敛: 动态优先（AI 可调）
                    semantic_retriever=self.semantic_retriever,  # M11 T45: 语义路径接线
                )
            except Exception as exc:  # noqa: BLE001 — 记忆失败不阻塞（FR-MEM-03）
                memory_msgs = [self._fault_feedback("memory", exc)]

            # M54: 模型窗口感知的主动压缩 — 先定模型标签, 再按其窗口收紧历史预算
            planned_label = self._planned_model_label(model, sess)
            effective_budget = self._effective_history_budget(planned_label)
            if effective_budget < self._runtime_history_budget():
                self._record_action(
                    "understand.build_messages",
                    "model_aware_budget",
                    f"{planned_label}: {self._runtime_history_budget()}→{effective_budget}",
                )
            messages = self._build_llm_messages(sess, memory_msgs, max_chars=effective_budget)
            if len(messages) < len(sess.messages) + len(memory_msgs) + 1:
                truncation_noted = True
            tool_schemas = self.registry.schemas(lazy=self.settings.tool_schema_lazy)
            tools_param = [self._schema_to_param(t) for t in tool_schemas]

            # ── 行动：LLM 决策 ──
            self._phase("action.llm_decide")
            # M48（design §5.3）: 路由决策——
            # - per-call Web model（run() 参数）优先级最高：经池路由到对应 provider client
            #   （正确 base_url/key），并把发送给 LLM 的 model 归一化为裸模型名
            #   （M50 修复: 全限定 provider/model 不得直接透传 LLM API，否则 400）
            # - 否则按会话级 model_override 经 pool 路由（switch_model 设置，持久生效）
            # - pool 未装配（None）→ 用默认 client（零回归）
            chat_model_arg = model  # per-call Web override（None 表示不覆盖）
            if chat_model_arg is not None and self.llm_pool is not None:
                # per-call 覆盖：解析 provider/model → 对应 provider client
                try:
                    llm_client = self.llm_pool.get_client(chat_model_arg)
                    pid, resolved_model_id = self.llm_pool.registry.resolve(chat_model_arg)
                    chat_model_arg = resolved_model_id
                    model_used = f"{pid}/{resolved_model_id}"  # M51: 如实标注实际模型
                except ValueError as exc:
                    # 模型不在注册表 / 凭据缺失：如实反馈，不静默降级（PREFERENCE_1）
                    self._record_action("action.llm_decide", "pool_resolve_failed", str(exc)[:200])
                    final_answer = model_unavailable_text(chat_model_arg, exc)
                    break
            elif chat_model_arg is None and self.llm_pool is not None:
                # 会话级 override 路由：取 switch_model 写入的覆盖
                try:
                    llm_client = self.llm_pool.get_client(sess.model_override)
                    # M51: override 为全限定 ref；None 时为装配默认标签
                    model_used = sess.model_override or self._default_model_label()
                except ValueError as exc:
                    # resolve 失败（override 在 refresh_config 后失效等）：如实反馈，走默认 client
                    self._record_action("action.llm_decide", "pool_resolve_failed", str(exc)[:200])
                    llm_client = self.llm
                    model_used = self._default_model_label()
            else:
                llm_client = self.llm
                model_used = self._default_model_label()
            # ── M53: 上下文超限前置守卫 ──
            # 载荷估算超模型注册表 context 上限 → 如实拒绝, 不发注定失败的请求
            # (如 kimi/k3-256k 仅 256K 窗口, 1M 预算装配的历史必被 provider 拒绝)
            # 未知模型 context（无 pool/裸标签）→ 跳过守卫, 不阻断
            context_limit = self._current_context_limit(model_used)
            if context_limit:
                refusal = self._check_context_fit(
                    messages, tools_param, context_limit, model_used
                )
                if refusal is not None:
                    self._record_action(
                        "action.llm_decide", "context_overflow", refusal[:200]
                    )
                    final_answer = refusal
                    break
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
                # R4: overflow 如实反馈（不自动重试，决策权归 AI，避免丢信息影响大模型）
                if is_overflow_error(exc):
                    from llm_loop.feedback.honesty import overflow_feedback

                    ctx_limit = self._current_context_limit(model_used)
                    model_window = (
                        {"label": model_used, "context": ctx_limit}
                        if ctx_limit
                        else {"label": model_used, "context": None}
                    )
                    final_answer = overflow_feedback(
                        exc,
                        getattr(self, "_last_breakdown", None),
                        model_window,
                    )
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

            # ── M56 收敛（ANALYSIS-20260811-loop-strategy-branch-inventory）:
            # 每轮末信号检测统一为一次调用（自评/演进待办/待审提醒，均仅提示不强制，
            # 触发判断与决策交 AI 自主——RULE-AI-10 每轮自主检查清单）──
            self._check_loop_signals(sess, rounds)

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
            model_used=model_used,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    def _default_model_label(self) -> str:
        """M51: 装配默认模型的全限定标签（provider/model）.

        有 pool 时经注册表 resolve 为全限定 ref；无 pool / resolve 失败 → 裸模型名（零回归）.
        client 无 model 属性（如测试 FakeLLM）→ 返回空串（不伪造标签, 无 footer）.
        """
        model = getattr(self.llm, "model", "")
        if not model:
            return ""
        if self.llm_pool is not None:
            try:
                pid, mid = self.llm_pool.registry.resolve(model)
                return f"{pid}/{mid}"
            except ValueError:
                pass
        return model

    def _current_context_limit(self, model_label: str) -> int | None:
        """M53: 查询当前模型的上下文上限（注册表 ModelSpec.context 元数据）.

        model_label 为全限定 "provider/model"（M51 路由已保证）；无 pool / 裸名 / 未知 → None（守卫跳过）.
        """
        if self.llm_pool is None or not model_label or "/" not in model_label:
            return None
        pid, mid = model_label.split("/", 1)
        spec = self.llm_pool.registry.providers.get(pid)
        if spec is None or mid not in spec.models:
            return None
        context = spec.models[mid].context
        return context if context and context > 0 else None

    @staticmethod
    def _check_context_fit(
        messages: list[dict],
        tools_param: list[dict],
        context_limit: int,
        model_label: str,
    ) -> str | None:
        """M53: 载荷 vs 模型上下文上限校验.

        估算口径: JSON 序列化字符数 / 2 ≈ tokens（中文混合保守估计）+ 10% 安全边距。
        超限 → 返回如实拒绝文案（不发送请求）；未超 → None。
        """
        payload_chars = sum(len(_json_dumps_args(m)) for m in messages) + len(
            _json_dumps_args({"tools": tools_param})
        )
        est_tokens = payload_chars // _CHARS_PER_TOKEN_EST
        allowed = int(context_limit * _CONTEXT_SAFETY_MARGIN)
        if est_tokens <= allowed:
            return None
        return (
            f"[上下文超限] 本次请求载荷约 {est_tokens} tokens（按 {_CHARS_PER_TOKEN_EST} 字符/token 估算），"
            f"超过当前模型 {model_label} 的上下文上限 {context_limit}（安全边距后可用 {allowed}）。\n"
            f"建议：① /model 切换到更大窗口模型；② /new 开新会话（历史另存可经 search_archive 找回）；"
            f"③ 缩短本次输入。\n"
            f"（程序守卫：未发送请求，避免必失败调用；估算口径可能有误差，以 provider 实际判定为准）"
        )

    # ── 辅助 ──
    def _planned_model_label(self, model: str | None, sess) -> str:
        """M54: 预测本轮将使用的模型标签（仅标签解析, 不建 client）.

        与路由同序: per-call override > 会话 override > 默认装配。
        用于在构造消息前计算模型窗口感知的压缩预算。
        """
        if model is not None and self.llm_pool is not None:
            try:
                pid, mid = self.llm_pool.registry.resolve(model)
                return f"{pid}/{mid}"
            except ValueError:
                return model
        if self.llm_pool is not None and sess.model_override:
            return sess.model_override
        return self._default_model_label()

    def _effective_history_budget(self, model_label: str) -> int:
        """M54: 模型窗口感知的历史压缩预算.

        effective = min(全局预算, 模型 context × 2字符/token × 0.5 压缩系数)。
        例: k3-256k (262144 tokens) → ~26万字符（而不是全局 1M）→ 历史先压到窗口内再调用。
        无 pool / 未知模型 → 全局预算（零回归）。
        """
        global_budget = self._runtime_history_budget()
        limit = self._current_context_limit(model_label)
        if not limit:
            return global_budget
        model_budget = int(limit * _CHARS_PER_TOKEN_EST * 0.5)
        return min(global_budget, model_budget)

    def _build_llm_messages(
        self, sess, memory_msgs: list[Message], max_chars: int | None = None
    ) -> list[dict]:
        """构造提交 LLM 的消息序列（system prompt + 记忆注入 + 历史 + 压缩另存）.

        M54: max_chars 可覆盖默认预算（模型窗口感知压缩）；None = 运行时预算（零回归）。
        """
        system_prompt = build_system_prompt()
        # 记忆消息作为前置注入
        base = [m for m in memory_msgs] + list(sess.messages)
        # EVO-20260811-9ccdec97: 会话状态快照节流——每间隔注入状态帧（定位锚点，fail-open）
        # M58 配置面收敛: 间隔走 runtime（动态优先，AI 可调）
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
                )
                base.insert(0, snapshot)
                self._last_snapshot_count = len(sess.messages)
        except Exception:
            import logging

            logging.getLogger(__name__).warning("会话状态快照注入失败（fail-open）", exc_info=True)
        from llm_loop.core.history import build_history_messages

        archive_sink = None
        if self.archive is not None:
            archive_sink = self._archive_sink
        # R1: 计算组件级占用分解（供 architecture_status.context_usage.breakdown 注入）
        from llm_loop.core.history import compute_breakdown

        effective_budget = max_chars if max_chars is not None else self._runtime_history_budget()
        self._last_breakdown = compute_breakdown(
            base, system_prompt, memory_msgs, budget=effective_budget
        )
        return build_history_messages(
            base,
            system_prompt,
            max_chars=max_chars if max_chars is not None else self._runtime_history_budget(),
            session_id=sess.session_id,
            archive_sink=archive_sink,
            summarizer=self.summarizer,  # EVO-9794797e: 主动压缩（旧消息语义摘要）
            layer_tool_trim=getattr(self.settings, "tool_trim_enabled", False),  # EVO-20260811-7baa2737: 历史分层降级
            tool_trim_age=getattr(self.settings, "tool_trim_age", 0),  # R3: 0=自适应
            reasoning_tail=getattr(self.settings, "reasoning_tail", 2),  # M66 思考链瘦身
        )

    def _check_loop_signals(self, sess, rounds: int) -> None:
        """每轮末信号检测统一入口（M56 收敛，ANALYSIS-20260811）.

        合并自评触发 / executing 演进待办 / pending_review 待审三项检测为一次调用；
        均仅"事实提醒"不强制，触发判断与决策权归 AI（RULE-AI-10 每轮自主检查清单）。
        """
        self._check_eval_trigger(sess, rounds)
        self._check_evolution_executing(sess)
        self._check_pending_review(sess)

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

    def _runtime_extract_interval(self) -> int:
        """会话状态快照注入间隔（M58 配置面收敛: 动态优先、静态兜底）."""
        if self.runtime is not None:
            return self.runtime.extract_interval_msgs
        return getattr(self.settings, "extract_interval_msgs", 20) or 20

    def _runtime_memory_top_k(self) -> int:
        """记忆检索条数（M57 配置面收敛: 动态优先、静态兜底）."""
        if self.runtime is not None:
            return self.runtime.memory_top_k
        return getattr(self.settings, "memory_top_k", 5)

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
        except Exception as exc:
            # C3（PREFERENCE_1）: 压缩另存/摘要失败如实注入会话（AI 可感知，不静默——
            # 被压缩消息可能无法找回）。注入失败静默（尽力而为）。
            logger.warning("压缩另存/摘要失败（fail-open）", exc_info=True)
            from contextlib import suppress

            with suppress(Exception):
                s = self.session.load(session_id)
                s.messages.append(self._fault_feedback("archive_sink", exc))
                self.session.save(s)

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

    # ── M49（design §5.4）: 降级逻辑辅助 ──

    @staticmethod
    def _is_fallback_eligible_error(exc: LLMError) -> bool:
        """判定异常是否可触发降级（design §5.4 行为规则表）.

        可降级:
        - LLMTimeoutError (请求超时)
        - LLMNetworkError (网络不可达)
        - LLMHTTPError(status_code >= 500)（上游服务错误）
        - LLMHTTPError(status_code == 429)（限流, design §5.4 表「5xx/429」）

        不可降级（design §5.4 行为规则表注: 4xx 非 429 请求本身有问题,换模型无用）:
        - LLMHTTPError(其他 4xx)：如 400（协议错误）、401（鉴权）、403（权限）、404（端点）
        - LLMProtocolError（响应解析异常, 非网络/上游问题）

        Args:
            exc: 当前 LLM 调用抛出的异常.

        Returns:
            True 可降级, False 走如实反馈路径.
        """
        if isinstance(exc, (LLMTimeoutError, LLMNetworkError)):
            return True
        if isinstance(exc, LLMHTTPError):
            return exc.status_code == 429 or exc.status_code >= 500
        return False

    def _try_fallback_chain(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        timeout_s: float | None,
        primary_error: LLMError,
        session_id: str,
    ) -> tuple[LLMResponse | None, list[Message], str | None]:
        """沿 fallback 链尝试下一个候选（design §5.4 行为规则表 + 原则 2 如实反馈）.

        行为:
        - 调用 pool.fallback_candidates() 取得合法降级候选列表
        - 空 → 返回 (None, [], None)（调用方走原异常如实反馈路径，零回归）
        - 逐个尝试,首个成功 → 返回 (resp, [notice_msg], 成功的模型 ref)（调用方把 notice_msg 注入 sess.messages）
        - 全部失败 → 返回 (None, [summary_msg], None)（调用方把 summary_msg 注入 sess.messages + 走原异常反馈路径）

        Args:
            messages: 本轮 LLM 调用所需消息列表.
            tools: 本轮工具 schema 列表.
            timeout_s: 本轮超时（继承当前循环超时）.
            primary_error: 主调用异常（用作首个原因 + 注入消息文本）.
            session_id: 当前会话 ID（供 record_fallback / 审计关联）.

        Returns:
            (resp, [messages_to_inject]).
            resp: 首个成功的降级响应（链全失败/无候选时为 None）。
            messages_to_inject: 提示消息（降级成功提示 / 链全失败汇总；空 list = 无需注入）。
        """
        if self.llm_pool is None:
            # 池未装配（如某些测试路径）→ 不启用降级, 调用方如实反馈
            return None, [], None

        candidates = self.llm_pool.fallback_candidates()
        if not candidates:
            # MODEL_FALLBACKS 未配置/全非法 → 不启用降级（零回归路径）
            return None, [], None

        from_model = self.llm_pool.get_default_model()
        primary_reason = self._fallback_reason_label(primary_error)

        candidate_failures: list[tuple[str, str, str]] = []  # (model_ref, error_type, error_msg)
        for ref in candidates:
            try:
                client = self.llm_pool.get_client(ref)
            except ValueError as exc:
                # resolve / client_params 失败（不应当发生, pool.fallback_candidates 已预检过）
                candidate_failures.append((ref, type(exc).__name__, str(exc)[:200]))
                continue

            try:
                resp = client.chat(messages=messages, tools=tools, timeout_s=timeout_s)
            except LLMError as exc:
                # 该候选也失败, 继续尝试下一个; 记录 (model_ref, error_type, error_msg)
                candidate_failures.append((ref, type(exc).__name__, str(exc)[:200]))
                continue

            # ── 降级成功 ──
            to_model = ref
            reason = primary_reason
            self._record_action(
                "action.llm_decide",
                "fallback_success",
                f"{from_model}->{to_model}: {reason}",
            )
            notice = self._build_fallback_notice_message(
                from_model=from_model,
                to_model=to_model,
                reason=reason,
                primary_error=primary_error,
            )
            # 状态上报（architecture_status 可见降级态 + 原因, design §5.4）
            if self.status:
                self.status.record_fallback(
                    from_model=from_model,
                    to_model=to_model,
                    reason=reason,
                    session_id=session_id,
                )
            # 审计落盘
            if self.corrections is not None:
                self.corrections.audit_fallback_event(
                    from_model=from_model,
                    to_model=to_model,
                    reason=reason,
                    result_status="success",
                )
            return resp, [notice], ref

        # ── 链全失败 ──
        # 汇总提示: 包含主调用原因 + 每个候选失败原因（如实反馈, design §5.4 行为表）
        candidate_lines = [
            f"- {ref} ({etype}): {msg[:160]}" for ref, etype, msg in candidate_failures
        ]
        detail_lines = "\n".join(candidate_lines) if candidate_lines else "- (无可用候选)"
        summary = self._build_fallback_all_failed_message(
            from_model=from_model,
            primary_error=primary_error,
            candidate_lines=detail_lines,
        )
        # 审计（全失败 = result_status="all_failed"）
        if self.corrections is not None:
            self.corrections.audit_fallback_event(
                from_model=from_model,
                to_model="all_failed",
                reason=primary_reason,
                result_status="all_failed",
                detail=detail_lines,
            )
        # 状态: 不更新 record_fallback（链全失败不算"降级态"）
        return None, [summary], None

    @staticmethod
    def _fallback_reason_label(exc: LLMError) -> str:
        """将 LLM 异常映射为简短中文降级原因标注（注入消息用, 设计原则 2 如实反馈）."""
        if isinstance(exc, LLMTimeoutError):
            return "请求超时"
        if isinstance(exc, LLMNetworkError):
            return "网络不可达"
        if isinstance(exc, LLMHTTPError):
            if exc.status_code == 429:
                return "429 限流"
            return f"HTTP {exc.status_code} 上游错误"
        return type(exc).__name__

    @staticmethod
    def _build_fallback_notice_message(
        *,
        from_model: str,
        to_model: str,
        reason: str,
        primary_error: LLMError,
    ) -> Message:
        """构造降级成功提示消息（design §5.4 + 原则 2 如实反馈）.

        注入消息流后 AI 可见, 对齐 honesty.py 三件套格式（事实/原因/建议）。
        包含回执标识 [模型降级: X→Y, 原因: ...]（design §5.4 表标注, 设计要求必含）.
        """
        content = (
            f"[模型降级: {from_model}→{to_model}, 原因: {reason}] "
            f"事实: 默认模型 {from_model} 调用失败,已自动降级到 {to_model} 继续本次任务。\n"
            f"原因: {type(primary_error).__name__}: {str(primary_error)[:160]}。\n"
            f"建议: 当前任务继续使用 {to_model};如需回退默认,可用 switch_model 切换。"
        )
        return Message(
            role="system",
            content=content,
            source=MessageSource.SYSTEM,
        )

    @staticmethod
    def _build_fallback_all_failed_message(
        *,
        from_model: str,
        primary_error: LLMError,
        candidate_lines: str,
    ) -> Message:
        """构造链全失败汇总消息（design §5.4 行为规则表「链全部失败」+ 原则 2 如实反馈）."""
        content = (
            f"[模型降级] 事实: 默认模型 {from_model} 调用失败,降级链全部失败。\n"
            f"原因: 默认失败 {type(primary_error).__name__}: {str(primary_error)[:160]};\n"
            f"各候选失败:\n{candidate_lines}\n"
            f"建议: 检查网络/上游状态/降级链配置后重试。"
        )
        return Message(
            role="system",
            content=content,
            source=MessageSource.SYSTEM,
        )

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

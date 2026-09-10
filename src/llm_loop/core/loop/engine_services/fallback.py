"""FallbackService——模型降级链职责服务（R9-B5-W4-02c：_FallbackMixin 退役；宿主面显式经 self._host 标注，沿 runtime_params v4 惯例）.

P2-B: 仅对 5xx/429/超时/网络执行默认模型 availability failover；其他错误保留原事实，不推断模型质量；
沿 fallback 链尝试候选，链全部失败如实汇总（原则 2 诚实反馈）。
(mixin 时代文件级 pyright 豁免已随宿主显式标注移除；如 pyright 报错回退并登记)
"""


from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine

from llm_loop.core.message import Message, MessageSource
from llm_loop.llm.client import GuardRequestContext, LLMClient, LLMResponse
from llm_loop.llm.errors import (
    LLMError,
    LLMHTTPError,
    LLMNetworkError,
    LLMTimeoutError,
)
from llm_loop.resources.provider_calls import foreground_task_provider_chat
from llm_loop.resources.provider_settlement import (
    ProviderAttemptKind,
    ProviderCallIdentity,
)
from llm_loop.runtime.causality import exceptional_attempt_payload

logger = logging.getLogger(__name__)




class FallbackService:
    def __init__(self, host: LoopEngine) -> None:
        self._host = host

    def _reachability_begin_attempt(
        self, *, kind: str, attempt_index: int, model: str, provider: str
    ) -> str:
        """Optional observability hook; never a fallback business dependency."""
        try:
            tool_cycle = getattr(self._host, "_tool_cycle", None)
            fn = getattr(tool_cycle, "_reachability_begin_attempt", None)
            if callable(fn):
                return str(fn(
                    kind=kind, attempt_index=attempt_index,
                    model=model, provider=provider,
                ) or "")
        except Exception:  # noqa: BLE001 -- telemetry fail-open
            logger.debug("fallback reachability bind failed (fail-open)", exc_info=True)
        return ""

    def _reachability_finalize(self, outcome: str) -> None:
        """Optional observability finalize hook; no effect on retry semantics."""
        try:
            tool_cycle = getattr(self._host, "_tool_cycle", None)
            fn = getattr(tool_cycle, "_reachability_finalize", None)
            if callable(fn):
                fn(outcome)
        except Exception:  # noqa: BLE001 -- telemetry fail-open
            logger.debug("fallback reachability finalize failed (fail-open)", exc_info=True)
    # ── M49（design §5.4）: 降级逻辑辅助 ──

    @staticmethod
    def _is_fallback_eligible_error(exc: LLMError) -> bool:
        """判定异常是否可触发降级（design §5.4 行为规则表）.

        可降级:
        - LLMTimeoutError (请求超时)
        - LLMNetworkError (网络不可达)
        - LLMHTTPError(status_code >= 500)（上游服务错误）
        - LLMHTTPError(status_code == 429)（限流, design §5.4 表「5xx/429」）

        不进入 availability failover:
        - LLMHTTPError(其他 4xx)：不归类为默认 provider 的瞬时可用性故障
        - LLMProtocolError：保留原错误事实，不由程序推断另一个模型更适合任务

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

    @staticmethod
    def _merge_fallback_metadata(
        metadata: dict[str, Any], context_limit: Any, chars_per_token: float
    ) -> tuple[Any, float]:
        """把成功fallback的局部snapshot元数据合并回engine本轮响应观测。"""
        return (
            metadata.get("context_limit", context_limit),
            float(metadata.get("chars_per_token", chars_per_token)),
        )

    def _try_fallback_chain(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        timeout_s: float | None,
        primary_error: LLMError,
        session_id: str,
        from_model: str | None = None,
        run_round: int | None = None,
        metadata_out: dict[str, Any] | None = None,
        request_builder: Callable[[str, Any], tuple[list[dict], list[dict]]] | None = None,
        provider_call: ProviderCallIdentity | None = None,
        site_index_offset: int = 1,
    ) -> tuple[LLMResponse | None, list[Message], str | None]:
        """沿 fallback 链尝试下一个候选（design §5.4 行为规则表 + 原则 2 如实反馈）.

        行为:
        - 调用 pool.fallback_candidates() 取得合法降级候选列表
        - 空 → 返回 (None, [], None)（调用方走原异常如实反馈路径，零回归）
        - 逐个尝试,首个成功 → 返回 (resp, [], 成功模型 ref)；fallback fact 经 LoopResult 结构化交付
        - 全部失败 → 返回 (None, [summary_fact], None)；仅用于当前用户错误回执，不写会话 prompt

        Args:
            messages: 本轮 LLM 调用所需消息列表.
            tools: 本轮工具 schema 列表.
            timeout_s: 本轮超时（继承当前循环超时）.
            primary_error: 主调用异常（用作首个原因 + 注入消息文本）.
            session_id: 当前会话 ID（供 record_fallback / 审计关联）.

        Returns:
            (resp, [messages_to_inject]).
            resp: 首个成功的降级响应（链全失败/无候选时为 None）。
            messages_to_inject: 仅链全失败的当前用户事实；成功时恒空。
        """
        if self._host.llm_pool is None:
            # 池未装配（如某些测试路径）→ 不启用降级, 调用方如实反馈
            return None, [], None

        # 真实ModelClientPool支持不可变snapshot：候选筛选、client构造和GuardRequestContext
        # 必须绑定同一表，避免refresh夹在fallback链中造成client=A而budget/context=B。
        # 最小duck pool（测试/外部注入）没有这些API时完整保留旧接口。
        snapshot_fn = getattr(self._host.llm_pool, "registry_snapshot", None)
        resolved_fn = getattr(self._host.llm_pool, "get_resolved_client", None)
        fallback_registry: Any = None
        if callable(snapshot_fn) and callable(resolved_fn):
            fallback_registry = snapshot_fn()

        if fallback_registry is not None:
            candidates = self._host.llm_pool.fallback_candidates(registry=fallback_registry)
        else:
            candidates = self._host.llm_pool.fallback_candidates()
        if not candidates:
            # MODEL_FALLBACKS 未配置/全非法 → 不启用降级（零回归路径）
            return None, [], None

        from_model = from_model or self._host.llm_pool.get_default_model()
        primary_reason = self._fallback_reason_label(primary_error)

        candidate_failures: list[tuple[str, str, str]] = []  # (model_ref, error_type, error_msg)
        provider_attempt_index = 0  # R8: count only requests that actually reach client.chat
        for ref in candidates:
            try:
                if fallback_registry is not None and callable(resolved_fn):
                    client, provider_id, model_id = cast(
                        Any, resolved_fn(ref, registry=fallback_registry)
                    )
                else:
                    # duck pool兼容：fallback_candidates公开契约仍是规范化provider/model ref。
                    # 模型id本身允许包含"/"，因此只切第一段provider。
                    provider_id, sep, model_id = ref.partition("/")
                    if not sep or not provider_id or not model_id:
                        raise ValueError(f"非法 fallback 模型引用: {ref!r}")
                    client = self._host.llm_pool.get_client(ref)
            except ValueError as exc:
                # 候选格式 / client 构造失败：记录后继续下一个候选（fail-soft）。
                candidate_failures.append((ref, type(exc).__name__, str(exc)[:200]))
                continue

            try:
                candidate_messages = messages
                candidate_tools = tools
                if request_builder is not None:
                    # R8.21/E05: a fallback may cross provider replay protocols.
                    # Never reuse a GLM/local-projected history for DeepSeek (missing
                    # required reasoning), nor leak DeepSeek historical CoT into a
                    # provider that does not require it. Rebuild from durable session
                    # truth using the exact same immutable fallback registry snapshot.
                    try:
                        candidate_messages, candidate_tools = request_builder(
                            f"{provider_id}/{model_id}", fallback_registry
                        )
                    except Exception as exc:  # noqa: BLE001 — wrong-provider reuse is unsafe
                        candidate_failures.append(
                            (ref, "RequestBuildError", str(exc)[:200])
                        )
                        continue
                chat_kwargs: dict = {
                    "messages": candidate_messages,
                    "tools": candidate_tools,
                    "timeout_s": timeout_s,
                    "model": model_id,
                }
                if isinstance(client, LLMClient):
                    fallback_label = f"{provider_id}/{model_id}"
                    fallback_budget = (
                        self._host._effective_history_budget(
                            fallback_label, registry_snapshot=fallback_registry
                        )
                        if fallback_registry is not None
                        else self._host._effective_history_budget(fallback_label)
                    )
                    chat_kwargs["guard_context"] = GuardRequestContext(
                        session_id=session_id,
                        system_text=(
                            candidate_messages[0].get("content", "")
                            if candidate_messages
                            and candidate_messages[0].get("role") == "system"
                            else None
                        ),
                        compress_count_this_run=getattr(
                            self, "_compress_count_this_run", 0
                        ),
                        history_budget=int(fallback_budget or 0),
                        run_round=run_round,
                        provider=provider_id,
                        model=model_id,
                    )
                _site_index = int(site_index_offset) + provider_attempt_index
                _attempt_id = self._reachability_begin_attempt(
                    kind="fallback",
                    attempt_index=_site_index,
                    model=f"{provider_id}/{model_id}",
                    provider=provider_id,
                )
                with contextlib.suppress(Exception):
                    self._host._event_append(
                        session_id,
                        "request.attempt",
                        exceptional_attempt_payload(
                            attempt_id=_attempt_id,
                            kind="fallback",
                            attempt_index=_site_index,
                            round_no=int(run_round or 0),
                            client=client,
                            messages=candidate_messages,
                            tools=candidate_tools,
                            provider_call_id=getattr(provider_call, "call_id", ""),
                        ),
                    )
                provider_attempt_index += 1
                resp = foreground_task_provider_chat(
                    self._host,
                    client,
                    client.chat,
                    chat_kwargs,
                    owner_ref=(
                        f"task:{session_id}:round:{run_round}:fallback:"
                        f"{_site_index}:{_attempt_id}"
                    ),
                    provider_id=provider_id,
                    model_id=model_id,
                    provider_call=provider_call,
                    attempt_kind=ProviderAttemptKind.FALLBACK,
                    site_index=_site_index,
                )
            except LLMError as exc:
                self._reachability_finalize("provider_error")
                # 该候选也失败, 继续尝试下一个; 记录 (model_ref, error_type, error_msg)
                candidate_failures.append((ref, type(exc).__name__, str(exc)[:200]))
                continue

            # ── 降级成功 ──
            to_model = ref
            if metadata_out is not None:
                label = f"{provider_id}/{model_id}"
                metadata_out["max_output_tokens"] = max(
                    0, int(getattr(client, "max_tokens", 0) or 0)
                )
                if fallback_registry is not None:
                    metadata_out["context_limit"] = self._host._current_context_limit(
                        label, registry_snapshot=fallback_registry
                    )
                    metadata_out["chars_per_token"] = self._host._provider_chars_per_token(
                        label, registry_snapshot=fallback_registry
                    )
                else:
                    metadata_out["context_limit"] = self._host._current_context_limit(label)
                    metadata_out["chars_per_token"] = self._host._provider_chars_per_token(label)
            reason = primary_reason
            self._host._record_action(
                "action.llm_decide",
                "fallback_success",
                f"{from_model}->{to_model}: {reason}",
            )
            # 状态上报（architecture_status 可见降级态 + 原因, design §5.4）
            if self._host.status:
                self._host.status.record_fallback(
                    from_model=from_model,
                    to_model=to_model,
                    reason=reason,
                    session_id=session_id,
                )
            # 审计落盘
            if self._host.corrections is not None:
                self._host.corrections.audit_fallback_event(
                    from_model=from_model,
                    to_model=to_model,
                    reason=reason,
                    result_status="success",
                )
            # Current-user delivery fact only. It never becomes a Message or future
            # provider prompt. LoopResult/API/UI render this structured receipt.
            # LoopEngine exposes RunState, but FallbackService also has a small
            # historical duck-host test/integration surface. Receipt delivery is
            # optional there; fallback success itself must not depend on this UI fact.
            run_state_fn = getattr(self._host, "_run_state", None)
            if callable(run_state_fn):
                run_state = cast(Any, run_state_fn())
                run_state.fallback_receipt = {
                    "from": from_model,
                    "to": to_model,
                    "reason": reason,
                }
            return resp, [], ref

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
        if self._host.corrections is not None:
            self._host.corrections.audit_fallback_event(
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
            f"各候选失败:\n{candidate_lines}"
        )
        return Message(
            role="system",
            content=content,
            source=MessageSource.SYSTEM,
        )


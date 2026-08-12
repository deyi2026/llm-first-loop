"""LoopEngine 模型降级链 mixin（M53 拆分: loop.py 1087 行→按职责分文件，纯重构行为零变化）.

design §5.4 行为规则表: 可降级 5xx/429/超时/网络；4xx 非 429 不降级（换模型无用）；
沿 fallback 链尝试候选，链全部失败如实汇总（原则 2 诚实反馈）。
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (mixin 模式: self 属性来自混入类 LoopEngine.__init__，pyright 无法静态解析，故文件级关闭这两条；参数/返回类型等其余检查保留)


from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine

from llm_loop.core.message import Message, MessageSource
from llm_loop.llm.client import LLMResponse
from llm_loop.llm.errors import (
    LLMError,
    LLMHTTPError,
    LLMNetworkError,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)


class _FallbackMixin:
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
        self: LoopEngine,
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


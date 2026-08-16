"""ResultCollector 结果回收器（design.md §2.2.2.6）.

拉取远端产出并转换为本地 ToolResult。至少一次回收（失败重试+审计，spec §4.2.4）。
结果经脱敏钩子链处理（复用现有脱敏机制）。结果体积超阈值截断并标注原始体积
（spec §5.4.1.5）。status 映射：succeeded→success, failed→failure, timeout→timeout,
cancelled→blocked。
"""

from __future__ import annotations

import logging

from llm_loop.codearts.audit import _redact
from llm_loop.codearts.client import (
    CallTimeoutError,
    ClientError,
    CodeArtsClient,
    ConnectionTimeoutError,
    RetryableError,
)
from llm_loop.codearts.models import (
    Credential,
    ExecutionHandle,
    ExecutionResult,
    ResultStatus,
)
from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.event_log.model import EVENT_CODEARTS_COLLECTED
from llm_loop.event_log.store import EventStore

logger = logging.getLogger(__name__)

# ResultStatus → ToolResultStatus 映射
_STATUS_MAP: dict[ResultStatus, ToolResultStatus] = {
    ResultStatus.SUCCEEDED: ToolResultStatus.SUCCESS,
    ResultStatus.FAILED: ToolResultStatus.FAILURE,
    ResultStatus.TIMEOUT: ToolResultStatus.TIMEOUT,
    ResultStatus.CANCELLED: ToolResultStatus.BLOCKED,
}


class ResultCollector:
    """结果回收器（至少一次回收 + 脱敏 + 截断 + ToolResult 转换）."""

    def __init__(
        self,
        client: CodeArtsClient,
        event_store: EventStore,
        *,
        result_max_bytes: int = 1048576,
        max_retries: int = 3,
    ) -> None:
        self._client = client
        self._event_store = event_store
        self._result_max_bytes = result_max_bytes
        self._max_retries = max_retries

    def collect(
        self,
        handle: ExecutionHandle,
        credential: Credential,
        *,
        tool_call_id: str = "",
        tool_name: str = "codearts_dispatch",
    ) -> ToolResult:
        """回收远端结果并转换为 ToolResult（至少一次回收，失败重试）."""
        last_exc: Exception | None = None
        result: ExecutionResult | None = None
        failed_attempts = 0

        for attempt in range(self._max_retries + 1):
            try:
                result = self._client.fetch_result(handle, credential)
                break
            except (ConnectionTimeoutError, CallTimeoutError) as exc:
                last_exc = exc
                failed_attempts = attempt + 1
            except (ClientError, RetryableError) as exc:
                last_exc = exc
                failed_attempts = attempt + 1
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                failed_attempts = attempt + 1

        if result is None:
            # 回收失败重试耗尽：回执部分结果（已知状态 + 失败原因）
            reason = f"{type(last_exc).__name__}: {last_exc}" if last_exc else "未知原因"
            self._append_collected_event(handle, ResultStatus.FAILED, 0, False, 0, 0)
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"CodeArts 结果回收失败（重试 {failed_attempts} 次）: {reason}",
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                error_detail=reason,
            )

        # 脱敏处理
        final_answer = _redact(result.final_answer)
        log_summary = _redact(result.execution_log_summary)

        # 结果体积截断
        original_bytes = len(final_answer.encode("utf-8"))
        truncated = original_bytes > self._result_max_bytes
        retained_bytes = original_bytes
        if truncated:
            # 按字节截断（避免截断多字节字符中段）
            encoded = final_answer.encode("utf-8")[: self._result_max_bytes]
            final_answer = encoded.decode("utf-8", errors="ignore")
            retained_bytes = len(final_answer.encode("utf-8"))
            final_answer += (
                f"\n\n[结果已截断（原始 {original_bytes} 字节，保留 {retained_bytes} 字节）]"
            )

        # 状态映射
        tool_status = _STATUS_MAP.get(result.status, ToolResultStatus.FAILURE)

        # 构造回执内容
        content_parts = [final_answer]
        if log_summary:
            content_parts.append(f"\n[执行日志摘要]\n{log_summary}")
        if result.metrics:
            metrics_str = ", ".join(f"{k}={v}" for k, v in result.metrics.items())
            content_parts.append(f"\n[度量] {metrics_str}")
        if result.artifacts:
            arts = ", ".join(f"{a.name}({a.type})" for a in result.artifacts)
            content_parts.append(f"\n[制品] {arts}")
        if result.failure_reason and tool_status != ToolResultStatus.SUCCESS:
            content_parts.append(f"\n[失败原因] {result.failure_reason}")

        content = "\n".join(content_parts)

        # 事件落盘
        self._append_collected_event(
            handle, result.status, original_bytes, truncated, original_bytes, retained_bytes
        )

        return ToolResult(
            status=tool_status,
            content=content,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            error_detail=result.failure_reason if tool_status != ToolResultStatus.SUCCESS else None,
        )

    def _append_collected_event(
        self,
        handle: ExecutionHandle,
        status: ResultStatus,
        final_answer_chars: int,
        truncated: bool,
        original_bytes: int,
        retained_bytes: int,
    ) -> None:
        """落盘 codearts.collected 事件（fail-open）."""
        self._event_store.append(
            handle.session_id,
            EVENT_CODEARTS_COLLECTED,
            {
                "handle_id": handle.handle_id,
                "session_id": handle.session_id,
                "trace_id": handle.trace_id,
                "status": status.value,
                "final_answer_chars": final_answer_chars,
                "truncated": truncated,
                "original_bytes": original_bytes,
                "retained_bytes": retained_bytes,
            },
        )

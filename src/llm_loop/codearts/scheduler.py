"""CodeArtsScheduler 调度器门面（design.md §2.2.2.1）.

编排委派全链路：检查装配 → 并发上限 → 风险判定 → 凭证获取 → 触发执行 →
句柄登记 → 状态同步 → 结果回收 → 回执。全链路 fail-open 包裹：任意异常转
ToolResult 不抛穿主循环（spec §5.4.2.4）。

declare_capability() 如实暴露适用场景与局限性（spec §5.5），不夸大能力不隐瞒局限。
recover_in_flight() 供进程重启时接管在途委派（spec §4.2.2）。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from llm_loop.codearts.audit import AuditLogger
from llm_loop.codearts.client import (
    ApiVersionMismatchError,
    CallTimeoutError,
    ClientError,
    CodeArtsClient,
    ConnectionTimeoutError,
    RetryableError,
)
from llm_loop.codearts.collector import ResultCollector
from llm_loop.codearts.config import CodeArtsSettings
from llm_loop.codearts.credential import (
    CredentialError,
    CredentialProvider,
    CredentialRefreshError,
)
from llm_loop.codearts.handle import HandleRegistry
from llm_loop.codearts.models import (
    AuditAction,
    AuditResult,
    DispatchTask,
    HandleStatus,
    RiskLevel,
)
from llm_loop.codearts.risk import RiskClassifier
from llm_loop.codearts.sync import StateSynchronizer
from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.event_log.model import EVENT_CODEARTS_CANCELLED
from llm_loop.event_log.store import EventStore
from llm_loop.tools.safety import CatastrophicGuard

logger = logging.getLogger(__name__)


class CodeArtsScheduler:
    """CodeArts 调度器门面（编排全链路 + fail-open 包裹）."""

    def __init__(
        self,
        *,
        config: CodeArtsSettings,
        credential_provider: CredentialProvider,
        client: CodeArtsClient,
        handle_registry: HandleRegistry,
        state_synchronizer: StateSynchronizer,
        result_collector: ResultCollector,
        risk_classifier: RiskClassifier,
        audit_logger: AuditLogger,
        event_store: EventStore,
        safety_guard: CatastrophicGuard,
        approval_callback: Callable[[str, str], bool] | None,
    ) -> None:
        self._config = config
        self._credential_provider = credential_provider
        self._client = client
        self._handle_registry = handle_registry
        self._state_synchronizer = state_synchronizer
        self._result_collector = result_collector
        self._risk_classifier = risk_classifier
        self._audit_logger = audit_logger
        self._event_store = event_store
        self._safety_guard = safety_guard
        self._approval_callback = approval_callback
        # 监控指标（spec §4.4.1）
        self._metrics = {
            "dispatch_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "blocked_count": 0,
            "error_count": 0,
            "timeout_count": 0,
            "in_flight": 0,
            "retry_count": 0,
            "credential_refresh_count": 0,
        }

    def dispatch(self, task: DispatchTask, *, session_id: str) -> ToolResult:
        """委派任务给 CodeArts 子 Agent 执行（主入口，全链路 fail-open 包裹）."""
        self._metrics["dispatch_count"] += 1
        trace_id = task.trace_id or str(uuid.uuid4())
        now = AuditLogger.now_iso()

        try:
            # ① 检查装配
            if not self._config.enabled:
                return self._result(
                    ToolResultStatus.ERROR,
                    "CodeArts 集成未装配（总开关关闭）",
                    tool_call_id="",
                )

            # ② 并发上限
            if self._handle_registry.is_full():
                self._metrics["blocked_count"] += 1
                in_flight = self._handle_registry.in_flight_count()
                return self._result(
                    ToolResultStatus.BLOCKED,
                    f"CodeArts 在途任务已满（{in_flight}/{self._config.max_concurrent}）",
                    tool_call_id="",
                )

            # ③ 风险判定
            risk = self._risk_classifier.classify(task)
            if risk.local_blocked:
                self._metrics["blocked_count"] += 1
                self._audit(task, AuditAction.DISPATCH, AuditResult.BLOCKED, now, 0)
                return self._result(
                    ToolResultStatus.BLOCKED,
                    f"委派任务含禁止动作，已拦截（灾难性安全硬边界）: {risk.local_block_reason}",
                    tool_call_id="",
                )
            if risk.level == RiskLevel.CATASTROPHIC and self._config.approval_required:
                # 高风险动作审批
                if self._approval_callback is not None:
                    try:
                        approved = bool(self._approval_callback(task.task_description, risk.reason))
                    except Exception:  # noqa: BLE001 — 回调异常 fail-closed
                        approved = False
                    self._audit_approval(task, approved, now)
                    if not approved:
                        self._metrics["blocked_count"] += 1
                        return self._result(
                            ToolResultStatus.BLOCKED,
                            f"高风险动作需人工审批，已拒绝: {risk.reason}",
                            tool_call_id="",
                        )
                else:
                    # 无人值守路径 fail-closed
                    self._audit_approval(task, False, now)
                    self._metrics["blocked_count"] += 1

                    return self._result(
                        ToolResultStatus.BLOCKED,
                        f"高风险动作需人工审批，无人值守模式默认拒绝: {risk.reason}",
                        tool_call_id="",
                    )

            # ④ 凭证获取
            try:
                credential = self._credential_provider.get(self._config.region)
            except CredentialRefreshError as exc:
                self._metrics["error_count"] += 1
                return self._result(
                    ToolResultStatus.ERROR,
                    f"CodeArts 凭证刷新失败: {exc}",
                    tool_call_id="",
                )
            except CredentialError as exc:
                self._metrics["error_count"] += 1
                return self._result(
                    ToolResultStatus.ERROR,
                    f"CodeArts 凭证失效: {exc}",
                    tool_call_id="",
                )

            # ⑤ 触发执行
            try:
                handle = self._client.trigger_execution(
                    task, credential, region=self._config.region
                )
            except ApiVersionMismatchError as exc:
                self._metrics["error_count"] += 1
                self._audit(task, AuditAction.DISPATCH, AuditResult.FAILURE, now, 0)
                return self._result(
                    ToolResultStatus.ERROR,
                    f"CodeArts API 版本不兼容: {exc}",
                    tool_call_id="",
                )
            except ConnectionTimeoutError as exc:
                self._metrics["error_count"] += 1
                self._audit(task, AuditAction.DISPATCH, AuditResult.FAILURE, now, 0)
                return self._result(
                    ToolResultStatus.ERROR,
                    f"CodeArts 端点不可达: {self._config.endpoint} ({exc})",
                    tool_call_id="",
                )
            except CallTimeoutError as exc:
                self._metrics["timeout_count"] += 1
                self._audit(task, AuditAction.DISPATCH, AuditResult.FAILURE, now, 0)
                return self._result(
                    ToolResultStatus.TIMEOUT,
                    f"CodeArts 触发执行调用超时: {exc}",
                    tool_call_id="",
                )
            except ClientError as exc:
                self._metrics["failure_count"] += 1
                self._audit(task, AuditAction.DISPATCH, AuditResult.FAILURE, now, 0)
                return self._result(
                    ToolResultStatus.FAILURE,
                    f"CodeArts 拒绝执行: {exc}",
                    tool_call_id="",
                )
            except RetryableError as exc:
                self._metrics["error_count"] += 1
                self._audit(task, AuditAction.DISPATCH, AuditResult.FAILURE, now, 0)
                return self._result(
                    ToolResultStatus.ERROR,
                    f"CodeArts 触发失败（重试 {self._config.max_retries} 次耗尽）: {exc}",
                    tool_call_id="",
                )

            # ⑥ 成功：句柄登记 + 事件落盘 + 审计 + 启动状态同步
            from dataclasses import replace

            handle = replace(handle, session_id=session_id, trace_id=trace_id)
            self._handle_registry.register(handle, session_id=session_id, trace_id=trace_id)
            self._audit(task, AuditAction.DISPATCH, AuditResult.SUCCESS, now, 200)
            self._metrics["in_flight"] = self._handle_registry.in_flight_count()

            # 启动状态同步（终态回调中回收结果）
            def _on_terminal(status: HandleStatus) -> None:
                self._handle_registry.release(handle.handle_id)
                self._metrics["in_flight"] = self._handle_registry.in_flight_count()
                if status == HandleStatus.SUCCEEDED:
                    self._metrics["success_count"] += 1
                elif status == HandleStatus.FAILED:
                    self._metrics["failure_count"] += 1
                elif status == HandleStatus.TIMEOUT:
                    self._metrics["timeout_count"] += 1
                elif status == HandleStatus.UNKNOWN:
                    self._metrics["error_count"] += 1

            self._state_synchronizer.start(handle, on_terminal=_on_terminal)

            return self._result(
                ToolResultStatus.SUCCESS,
                f"CodeArts 委派已建立（handle_id={handle.handle_id}, trace_id={trace_id}）。"
                f"远端执行中，状态同步已启动，终态结果经事件日志回收。",
                tool_call_id="",
            )

        except Exception as exc:  # noqa: BLE001 — fail-open 不抛穿主循环
            self._metrics["error_count"] += 1
            logger.warning("CodeArts dispatch 未预期异常（fail-open）", exc_info=True)
            return self._result(
                ToolResultStatus.ERROR,
                f"CodeArts 委(派)未预期异常: {type(exc).__name__}: {exc}",
                tool_call_id="",
            )

    def query_status(self, handle_id: str) -> ToolResult:
        """查询在途委派状态."""
        handle = self._handle_registry.get(handle_id)
        if handle is None:
            return self._result(
                ToolResultStatus.FAILURE,
                f"句柄不存在: {handle_id}",
                tool_call_id="",
            )

        return self._result(
            ToolResultStatus.SUCCESS,
            f"handle_id={handle_id} status={handle.status.value} "
            f"remote_status={handle.remote_status.value} last_synced_at={handle.last_synced_at}",
            tool_call_id="",
        )

    def cancel(self, handle_id: str) -> ToolResult:
        """取消远端执行；取消失败如实标注不臆造已取消（spec §5.4.3.4）."""
        handle = self._handle_registry.get(handle_id)
        if handle is None:
            return self._result(
                ToolResultStatus.FAILURE,
                f"句柄不存在: {handle_id}",
                tool_call_id="",
            )
        try:
            credential = self._credential_provider.get(self._config.region)
            remote_cancelled = self._client.cancel_execution(handle, credential)
        except Exception as exc:  # noqa: BLE001
            return self._result(
                ToolResultStatus.FAILURE,
                f"取消失败，远端任务可能仍在执行: {type(exc).__name__}: {exc}",
                tool_call_id="",
            )
        # 事件落盘
        session_info = self._handle_registry.get_session_info(handle_id)
        sid = session_info[0] if session_info else handle.session_id
        self._event_store.append(
            sid,
            EVENT_CODEARTS_CANCELLED,
            {
                "handle_id": handle_id,
                "session_id": sid,
                "trace_id": handle.trace_id,
                "cancelled_at": datetime.now(UTC).isoformat(),
                "remote_cancelled": remote_cancelled,
            },
        )
        self._state_synchronizer.stop(handle_id)
        self._handle_registry.release(handle_id)
        if remote_cancelled:
            return self._result(
                ToolResultStatus.SUCCESS,
                f"已取消远端执行（handle_id={handle_id}）",
                tool_call_id="",
            )
        return self._result(
            ToolResultStatus.FAILURE,
            f"取消失败，远端任务可能仍在执行（handle_id={handle_id}）",
            tool_call_id="",
        )

    def declare_capability(self) -> str:
        """如实暴露适用场景与局限性（spec §5.5），不夸大能力不隐瞒局限."""
        return (
            "【CodeArts 子 Agent 调度能力声明】\n"
            "\n"
            "## 适用场景\n"
            "- 需华为云 CodeArts 平台能力的任务：流水线触发/代码检查/部署/远端仓库操作\n"
            "- 需远端执行环境的重任务（本地资源不足或需平台侧工具链）\n"
            "- 长时异步任务（经状态同步轮询驱动，不阻塞主循环）\n"
            "\n"
            "## 局限性\n"
            "- 依赖远端 CodeArts 服务可用性（端点不可达时如实回执 error）\n"
            "- 受平台配额限制（并发上限、API 限流）\n"
            "- 结果体积可能截断（超 CODEARTS_RESULT_MAX_BYTES 阈值时标注原始/保留体积）\n"
            "- 长时任务进度受事件通道可用性影响（Webhook 不可用时降级为纯轮询）\n"
            "- 状态同步有延迟（轮询间隔下限 5s，本地状态可能短暂滞后于远端）\n"
            "\n"
            "## 远端依赖声明\n"
            "- CodeArts OpenAPI 服务可用性\n"
            "- 网络连通性（本组件 ↔ CodeArts 端点）\n"
            "- 凭证有效性（AK/SK 或 IAM token）\n"
            "\n"
            "## 非完备调度声明\n"
            "- 本组件不保证 CodeArts 侧任务必然成功，仅保证调度行为与结果回收如实性\n"
            "- 本组件不承担 CodeArts 平台侧执行失败责任（由平台侧自治）\n"
            "- 本组件与本地 SubAgentRunner 互补非替代（本地轻量子任务用 spawn_subagent）\n"
            "- 禁止经 CodeArts 绕过本地灾难性安全硬边界（前置检查拦截）\n"
        )

    def recover_in_flight(self) -> int:
        """进程重启时接管在途委派（spec §4.2.2，接管时延上限 60s）."""
        recovered = self._handle_registry.recover()
        in_flight = self._handle_registry.list_in_flight()
        for handle in in_flight:
            # 对每个在途句柄重启状态同步
            def _on_terminal(status: HandleStatus, hid: str = handle.handle_id) -> None:
                self._handle_registry.release(hid)
                self._metrics["in_flight"] = self._handle_registry.in_flight_count()

            self._state_synchronizer.start(handle, on_terminal=_on_terminal)
        self._metrics["in_flight"] = self._handle_registry.in_flight_count()
        if recovered > 0:
            logger.info("CodeArts 重启接管: 恢复 %d 个在途委派", recovered)
        return recovered

    def metrics(self) -> dict[str, int]:
        """监控指标（spec §4.4.1）."""
        m = dict(self._metrics)
        m["in_flight"] = self._handle_registry.in_flight_count()
        return m

    # ── 内部辅助 ──

    @staticmethod
    def _result(status: ToolResultStatus, content: str, *, tool_call_id: str) -> ToolResult:
        return ToolResult(
            status=status,
            content=content,
            tool_call_id=tool_call_id,
            tool_name="codearts_dispatch",
        )

    def _audit(
        self,
        task: DispatchTask,
        action: AuditAction,
        result: AuditResult,
        timestamp: str,
        response_status: int,
    ) -> None:
        from llm_loop.codearts.models import AuditRecord

        self._audit_logger.log(
            AuditRecord(
                timestamp=timestamp,
                trace_id=task.trace_id,
                action=action,
                target_api=f"/{self._config.api_version}/agent/executions",
                response_status=response_status,
                credential_ref=self._config.credential_kind() + ":" + self._config.region,
                params_summary=task.task_description[:500],
                result=result,
            )
        )

    def _audit_approval(
        self, task: DispatchTask, approved: bool, timestamp: str
    ) -> None:
        from llm_loop.codearts.models import AuditRecord

        self._audit_logger.log(
            AuditRecord(
                timestamp=timestamp,
                trace_id=task.trace_id,
                action=AuditAction.APPROVAL,
                target_api="approval_gateway",
                response_status=200 if approved else 403,
                credential_ref="",
                params_summary=task.task_description[:500],
                result=AuditResult.SUCCESS if approved else AuditResult.BLOCKED,
            )
        )

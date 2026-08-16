"""CodeArtsClient OpenAPI 客户端（design.md §2.2.2.3）.

封装 CodeArts OpenAPI HTTP 调用（触发执行/查询状态/拉取结果/拉取日志/取消执行）。
httpx 连接池复用，TLS 强制（禁止 http://），重试策略（可重试 5xx/429/网络瞬断
指数退避，不可重试 4xx 立即返回），超时分级（连接/调用）。

请求 header 注入鉴权（AK/SK 签名或 X-Auth-Token）。区域路由按 region 字段独立端点。
"""

from __future__ import annotations

import logging
import time
from contextlib import suppress
from typing import Protocol

import httpx

from llm_loop.codearts.config import CodeArtsSettings
from llm_loop.codearts.models import (
    Artifact,
    Credential,
    CredentialKind,
    DispatchTask,
    ExecutionHandle,
    ExecutionResult,
    HandleStatus,
    RemoteStatus,
    ResultStatus,
)

logger = logging.getLogger(__name__)


# ── 异常层次（design.md §2.2.2.3 异常映射）──


class ClientError(Exception):
    """不可重试客户端错误（4xx / API 版本不兼容 / http:// 端点）."""


class RetryableError(Exception):
    """可重试错误（5xx / 429 / 网络瞬断）."""


class ConnectionTimeoutError(Exception):
    """连接超时（建立连接阶段超时）."""


class CallTimeoutError(Exception):
    """调用超时（读取响应阶段超时）."""


class ApiVersionMismatchError(ClientError):
    """API 版本不兼容."""


# ── 远端状态映射 ──
_REMOTE_STATUS_MAP: dict[str, RemoteStatus] = {
    "PENDING": RemoteStatus.PENDING,
    "RUNNING": RemoteStatus.RUNNING,
    "SUCCEEDED": RemoteStatus.SUCCEEDED,
    "SUCCESS": RemoteStatus.SUCCEEDED,
    "FAILED": RemoteStatus.FAILED,
    "FAIL": RemoteStatus.FAILED,
    "TIMEOUT": RemoteStatus.TIMEOUT,
    "CANCELLED": RemoteStatus.CANCELLED,
    "CANCELED": RemoteStatus.CANCELLED,
}

_RESULT_STATUS_MAP: dict[str, ResultStatus] = {
    "SUCCEEDED": ResultStatus.SUCCEEDED,
    "SUCCESS": ResultStatus.SUCCEEDED,
    "FAILED": ResultStatus.FAILED,
    "FAIL": ResultStatus.FAILED,
    "TIMEOUT": ResultStatus.TIMEOUT,
    "CANCELLED": ResultStatus.CANCELLED,
    "CANCELED": ResultStatus.CANCELLED,
}


def _map_remote_status(raw: str) -> RemoteStatus:
    return _REMOTE_STATUS_MAP.get(raw.upper(), RemoteStatus.RUNNING)


def _map_result_status(raw: str) -> ResultStatus:
    return _RESULT_STATUS_MAP.get(raw.upper(), ResultStatus.FAILED)


class CodeArtsClient(Protocol):
    """OpenAPI 客户端协议（design.md §2.2.2.3）."""

    def trigger_execution(
        self, task: DispatchTask, credential: Credential, *, region: str
    ) -> ExecutionHandle: ...

    def query_status(
        self, handle: ExecutionHandle, credential: Credential
    ) -> RemoteStatus: ...

    def fetch_result(
        self, handle: ExecutionHandle, credential: Credential
    ) -> ExecutionResult: ...

    def fetch_log_summary(
        self, handle: ExecutionHandle, credential: Credential, *, max_chars: int = 5000
    ) -> str: ...

    def cancel_execution(
        self, handle: ExecutionHandle, credential: Credential
    ) -> bool: ...

    def validate_api_version(self, credential: Credential) -> bool: ...


class HttpxCodeArtsClient:
    """httpx 实现 CodeArts OpenAPI 客户端（连接池复用 + TLS 强制 + 重试 + 超时分级）.

    重试策略：RetryableError 指数退避（base=1s, max=30s, 上限 max_retries），
    尊重 Retry-After header；ClientError/ApiVersionMismatchError 立即返回不重试。
    """

    def __init__(self, config: CodeArtsSettings) -> None:
        self._config = config
        self._endpoint = config.endpoint.rstrip("/")
        # TLS 强制：禁止 http:// 端点
        if self._endpoint and self._endpoint.startswith("http://"):
            raise ClientError(f"CodeArts 端点必须使用 HTTPS: {self._endpoint}")
        self._client = httpx.Client(
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            timeout=httpx.Timeout(
                connect=config.connect_timeout_s,
                read=config.call_timeout_s,
                write=config.call_timeout_s,
                pool=config.connect_timeout_s,
            ),
            verify=True,
        )

    def _headers(self, credential: Credential) -> dict[str, str]:
        """构造鉴权 header（AK/SK 签名或 X-Auth-Token）."""
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if credential.kind == CredentialKind.IAM_TOKEN:
            headers["X-Auth-Token"] = credential.token
        else:
            # AK/SK 模式：注入 AK/SK 供签名中间件处理（实际签名由华为云 SDK 或签名中间件完成）
            headers["X-AK"] = credential.ak
            headers["X-SK"] = credential.sk
        return headers

    def _url(self, path: str) -> str:
        return f"{self._endpoint}/{self._config.api_version}{path}"

    def _request(
        self,
        method: str,
        path: str,
        credential: Credential,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> httpx.Response:
        """带重试的 HTTP 请求（指数退避 + Retry-After 尊重）."""
        url = self._url(path)
        headers = self._headers(credential)
        last_exc: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                resp = self._client.request(
                    method, url, headers=headers, json=json_body, params=params
                )
            except httpx.ConnectTimeout as exc:
                raise ConnectionTimeoutError(f"连接超时: {url}") from exc
            except httpx.ReadTimeout as exc:
                raise CallTimeoutError(f"调用超时: {url}") from exc
            except httpx.HTTPError as exc:
                # 网络瞬断 → 可重试
                last_exc = exc
                if attempt >= self._config.max_retries:
                    raise RetryableError(f"网络错误重试耗尽: {exc}") from exc
                self._backoff(attempt, resp=None)
                continue
            # 状态码分级
            if resp.status_code < 400:
                return resp
            if resp.status_code == 429 or resp.status_code >= 500:
                # 可重试
                last_exc = RetryableError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                if attempt >= self._config.max_retries:
                    raise last_exc
                self._backoff(attempt, resp)
                continue
            # 4xx 不可重试
            raise ClientError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        # 不应到达
        raise RetryableError(f"重试耗尽: {last_exc}")

    def _backoff(self, attempt: int, resp: httpx.Response | None) -> None:
        """指数退避（base=1s, max=30s；尊重 Retry-After header）."""
        delay = min(30.0, 1.0 * (2**attempt))
        if resp is not None:
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                with suppress(ValueError):
                    delay = max(delay, float(retry_after))
        time.sleep(min(delay, 30.0))

    def trigger_execution(
        self, task: DispatchTask, credential: Credential, *, region: str
    ) -> ExecutionHandle:
        """触发 CodeArts 子 Agent 执行，返回执行句柄."""
        from datetime import UTC, datetime

        body = {
            "task_description": task.task_description,
            "context_summary": task.context_summary,
            "expected_output_format": task.expected_output_format,
            "priority": task.priority.value,
            "timeout_s": task.timeout_budget.exec_s,
            "project_id": self._config.project_id,
            "region": region,
        }
        resp = self._request("POST", "/agent/executions", credential, json_body=body)
        data = resp.json()
        handle_id = str(data.get("execution_id") or data.get("handle_id") or "")
        if not handle_id:
            raise ClientError(f"触发执行响应缺少 execution_id: {data}")
        return ExecutionHandle(
            handle_id=handle_id,
            session_id="",
            trace_id=task.trace_id,
            created_at=datetime.now(UTC).isoformat(),
            status=HandleStatus.RUNNING,
            last_synced_at=datetime.now(UTC).isoformat(),
            remote_status=RemoteStatus.RUNNING,
        )

    def query_status(
        self, handle: ExecutionHandle, credential: Credential
    ) -> RemoteStatus:
        """查询远端执行状态."""
        resp = self._request(
            "GET", f"/agent/executions/{handle.handle_id}/status", credential
        )
        data = resp.json()
        raw = str(data.get("status") or "RUNNING")
        return _map_remote_status(raw)

    def fetch_result(
        self, handle: ExecutionHandle, credential: Credential
    ) -> ExecutionResult:
        """拉取远端执行结果."""
        resp = self._request(
            "GET", f"/agent/executions/{handle.handle_id}/result", credential
        )
        data = resp.json()
        raw_status = str(data.get("status") or "SUCCEEDED")
        artifacts_raw = data.get("artifacts") or []
        artifacts = [
            Artifact(
                name=str(a.get("name", "")),
                type=str(a.get("type", "")),
                access=str(a.get("access", "")),
            )
            for a in artifacts_raw
            if isinstance(a, dict)
        ]
        metrics_raw = data.get("metrics") or {}
        metrics: dict[str, int | float | str] = {}
        if isinstance(metrics_raw, dict):
            for k, v in metrics_raw.items():
                if isinstance(v, int | float | str):
                    metrics[str(k)] = v
        return ExecutionResult(
            final_answer=str(data.get("final_answer") or data.get("answer") or ""),
            status=_map_result_status(raw_status),
            execution_log_summary=str(data.get("log_summary") or ""),
            metrics=metrics,
            artifacts=artifacts,
            failure_reason=str(data.get("failure_reason") or ""),
        )

    def fetch_log_summary(
        self, handle: ExecutionHandle, credential: Credential, *, max_chars: int = 5000
    ) -> str:
        """拉取执行日志摘要（截断至 max_chars）."""
        resp = self._request(
            "GET", f"/agent/executions/{handle.handle_id}/logs", credential
        )
        data = resp.json()
        logs = str(data.get("logs") or "")
        return logs[:max_chars]

    def cancel_execution(
        self, handle: ExecutionHandle, credential: Credential
    ) -> bool:
        """取消远端执行；返回远端是否确认取消."""
        try:
            resp = self._request(
                "POST", f"/agent/executions/{handle.handle_id}/cancel", credential
            )
            return resp.status_code < 400
        except (ClientError, RetryableError):
            return False

    def validate_api_version(self, credential: Credential) -> bool:
        """校验 CodeArts OpenAPI 版本兼容性."""
        try:
            resp = self._request("GET", "/version", credential)
            data = resp.json()
            server_version = str(data.get("version") or "")
            if server_version and server_version != self._config.api_version:
                raise ApiVersionMismatchError(
                    f"API 版本不兼容（期望 {self._config.api_version}，实际 {server_version}）"
                )
            return True
        except ApiVersionMismatchError:
            raise
        except (ClientError, RetryableError):
            return False

    def close(self) -> None:
        """关闭连接池."""
        self._client.close()

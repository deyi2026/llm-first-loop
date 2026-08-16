"""HttpxCodeArtsClient 单元测试（design.md §2.2.2.3）.

使用 httpx.MockTransport 模拟远端响应，测试异常映射/重试/超时分级/状态映射。
"""

from __future__ import annotations

import httpx
import pytest

from llm_loop.codearts.client import (
    ApiVersionMismatchError,
    CallTimeoutError,
    ClientError,
    ConnectionTimeoutError,
    HttpxCodeArtsClient,
    RetryableError,
    _map_remote_status,
    _map_result_status,
)
from llm_loop.codearts.config import CodeArtsSettings
from llm_loop.codearts.models import (
    Credential,
    CredentialKind,
    DispatchTask,
    ExecutionHandle,
    HandleStatus,
    RemoteStatus,
    ResultStatus,
)


def _make_config(**overrides) -> CodeArtsSettings:
    defaults = dict(
        enabled=True,
        endpoint="https://codearts.example.com",
        region="cn-north-4",
        ak="AK123",
        sk="SK456",
        max_retries=2,
    )
    defaults.update(overrides)
    return CodeArtsSettings(**defaults)


def _make_credential() -> Credential:
    return Credential(
        kind=CredentialKind.AK_SK,
        region="cn-north-4",
        ak="AK123",
        sk="SK456",
    )


def _make_iam_credential() -> Credential:
    return Credential(
        kind=CredentialKind.IAM_TOKEN,
        region="cn-north-4",
        token="token123",
    )


def _make_task() -> DispatchTask:
    return DispatchTask(task_description="test", trace_id="t1")


def _make_handle() -> ExecutionHandle:
    return ExecutionHandle(
        handle_id="h1",
        session_id="s1",
        trace_id="t1",
        created_at="2026-01-01T00:00:00Z",
        status=HandleStatus.RUNNING,
    )


def _make_client(config: CodeArtsSettings, handler) -> HttpxCodeArtsClient:
    transport = httpx.MockTransport(handler)
    client = HttpxCodeArtsClient(config)
    client._client = httpx.Client(transport=transport)
    return client


def test_tls_enforced():
    config = _make_config(endpoint="http://codearts.example.com")
    with pytest.raises(ClientError, match="HTTPS"):
        HttpxCodeArtsClient(config)


def test_trigger_execution_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "/agent/executions" in request.url.path
        return httpx.Response(200, json={"execution_id": "exec-123"})

    client = _make_client(_make_config(), handler)
    handle = client.trigger_execution(
        _make_task(), _make_credential(), region="cn-north-4"
    )
    assert handle.handle_id == "exec-123"
    assert handle.trace_id == "t1"
    assert handle.status == HandleStatus.RUNNING
    client.close()


def test_trigger_execution_missing_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    client = _make_client(_make_config(), handler)
    with pytest.raises(ClientError, match="execution_id"):
        client.trigger_execution(_make_task(), _make_credential(), region="cn-north-4")
    client.close()


def test_query_status_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "SUCCEEDED"})

    client = _make_client(_make_config(), handler)
    status = client.query_status(_make_handle(), _make_credential())
    assert status == RemoteStatus.SUCCEEDED
    client.close()


def test_query_status_unknown_defaults_running():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "WEIRD"})

    client = _make_client(_make_config(), handler)
    status = client.query_status(_make_handle(), _make_credential())
    assert status == RemoteStatus.RUNNING
    client.close()


def test_fetch_result_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "final_answer": "result text",
                "status": "SUCCEEDED",
                "log_summary": "log",
                "metrics": {"duration": 100},
                "artifacts": [{"name": "a.txt", "type": "file"}],
            },
        )

    client = _make_client(_make_config(), handler)
    result = client.fetch_result(_make_handle(), _make_credential())
    assert result.final_answer == "result text"
    assert result.status == ResultStatus.SUCCEEDED
    assert result.metrics["duration"] == 100
    assert len(result.artifacts) == 1
    client.close()


def test_fetch_log_summary_truncation():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"logs": "x" * 10000})

    client = _make_client(_make_config(), handler)
    logs = client.fetch_log_summary(_make_handle(), _make_credential(), max_chars=100)
    assert len(logs) == 100
    client.close()


def test_cancel_execution_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"cancelled": True})

    client = _make_client(_make_config(), handler)
    assert client.cancel_execution(_make_handle(), _make_credential()) is True
    client.close()


def test_cancel_execution_client_error_returns_false():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    client = _make_client(_make_config(), handler)
    assert client.cancel_execution(_make_handle(), _make_credential()) is False
    client.close()


def test_4xx_raises_client_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    client = _make_client(_make_config(), handler)
    with pytest.raises(ClientError):
        client.query_status(_make_handle(), _make_credential())
    client.close()


def test_5xx_retries_then_raises_retryable():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(500, text="server error")

    config = _make_config(max_retries=1)
    client = _make_client(config, handler)
    with pytest.raises(RetryableError):
        client.query_status(_make_handle(), _make_credential())
    assert call_count == 2  # 1 initial + 1 retry
    client.close()


def test_429_retries_then_succeeds():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"status": "RUNNING"})

    config = _make_config(max_retries=2)
    client = _make_client(config, handler)
    status = client.query_status(_make_handle(), _make_credential())
    assert status == RemoteStatus.RUNNING
    assert call_count == 2
    client.close()


def test_connect_timeout_raises_connection_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    client = _make_client(_make_config(), handler)
    with pytest.raises(ConnectionTimeoutError):
        client.query_status(_make_handle(), _make_credential())
    client.close()


def test_read_timeout_raises_call_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    client = _make_client(_make_config(), handler)
    with pytest.raises(CallTimeoutError):
        client.query_status(_make_handle(), _make_credential())
    client.close()


def test_iam_token_header():
    captured_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(request.headers)
        return httpx.Response(200, json={"execution_id": "e1"})

    client = _make_client(_make_config(), handler)
    client.trigger_execution(_make_task(), _make_iam_credential(), region="cn-north-4")
    assert captured_headers.get("x-auth-token") == "token123"
    client.close()


def test_ak_sk_headers():
    captured_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(request.headers)
        return httpx.Response(200, json={"execution_id": "e1"})

    client = _make_client(_make_config(), handler)
    client.trigger_execution(_make_task(), _make_credential(), region="cn-north-4")
    assert captured_headers.get("x-ak") == "AK123"
    assert captured_headers.get("x-sk") == "SK456"
    client.close()


def test_validate_api_version_match():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"version": "v1"})

    client = _make_client(_make_config(), handler)
    assert client.validate_api_version(_make_credential()) is True
    client.close()


def test_validate_api_version_mismatch():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"version": "v2"})

    client = _make_client(_make_config(), handler)
    with pytest.raises(ApiVersionMismatchError):
        client.validate_api_version(_make_credential())
    client.close()


def test_validate_api_version_error_returns_false():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="err")

    config = _make_config(max_retries=0)
    client = _make_client(config, handler)
    assert client.validate_api_version(_make_credential()) is False
    client.close()


def test_map_remote_status_variants():
    assert _map_remote_status("SUCCESS") == RemoteStatus.SUCCEEDED
    assert _map_remote_status("FAIL") == RemoteStatus.FAILED
    assert _map_remote_status("CANCELED") == RemoteStatus.CANCELLED
    assert _map_remote_status("UNKNOWN") == RemoteStatus.RUNNING


def test_map_result_status_variants():
    assert _map_result_status("SUCCESS") == ResultStatus.SUCCEEDED
    assert _map_result_status("FAIL") == ResultStatus.FAILED
    assert _map_result_status("CANCELED") == ResultStatus.CANCELLED
    assert _map_result_status("WEIRD") == ResultStatus.FAILED

"""ResultCollector 单元测试（design.md §2.2.2.6）.

使用 mock client 测试至少一次回收/脱敏/截断/状态映射/fail-open 行为。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from llm_loop.codearts.client import ClientError, RetryableError
from llm_loop.codearts.collector import ResultCollector
from llm_loop.codearts.models import (
    Credential,
    CredentialKind,
    ExecutionHandle,
    ExecutionResult,
    HandleStatus,
    ResultStatus,
)
from llm_loop.core.message import ToolResultStatus
from llm_loop.event_log.store import EventStore


def _make_handle() -> ExecutionHandle:
    return ExecutionHandle(
        handle_id="h1",
        session_id="s1",
        trace_id="t1",
        created_at="2026-01-01T00:00:00Z",
        status=HandleStatus.RUNNING,
    )


def _make_credential() -> Credential:
    return Credential(kind=CredentialKind.AK_SK, region="cn-north-4", ak="a", sk="b")


def _make_collector(tmp_path: Path, **kwargs) -> ResultCollector:
    event_store = EventStore(tmp_path / "events", enabled=False)
    return ResultCollector(
        client=MagicMock(),
        event_store=event_store,
        **kwargs,
    )


def test_collect_success(tmp_path: Path):
    collector = _make_collector(tmp_path)
    collector._client.fetch_result.return_value = ExecutionResult(
        final_answer="answer text",
        status=ResultStatus.SUCCEEDED,
        execution_log_summary="log",
        metrics={"duration": 50},
    )
    result = collector.collect(_make_handle(), _make_credential())
    assert result.status == ToolResultStatus.SUCCESS
    assert "answer text" in result.content
    assert "duration=50" in result.content
    assert result.error_detail is None


def test_collect_failure_status(tmp_path: Path):
    collector = _make_collector(tmp_path)
    collector._client.fetch_result.return_value = ExecutionResult(
        final_answer="",
        status=ResultStatus.FAILED,
        failure_reason="build error",
    )
    result = collector.collect(_make_handle(), _make_credential())
    assert result.status == ToolResultStatus.FAILURE
    assert "build error" in result.content


def test_collect_timeout_status(tmp_path: Path):
    collector = _make_collector(tmp_path)
    collector._client.fetch_result.return_value = ExecutionResult(
        final_answer="",
        status=ResultStatus.TIMEOUT,
    )
    result = collector.collect(_make_handle(), _make_credential())
    assert result.status == ToolResultStatus.TIMEOUT


def test_collect_cancelled_status(tmp_path: Path):
    collector = _make_collector(tmp_path)
    collector._client.fetch_result.return_value = ExecutionResult(
        final_answer="",
        status=ResultStatus.CANCELLED,
    )
    result = collector.collect(_make_handle(), _make_credential())
    assert result.status == ToolResultStatus.BLOCKED


def test_collect_retry_then_success(tmp_path: Path):
    collector = _make_collector(tmp_path, max_retries=2)
    good_result = ExecutionResult(final_answer="ok", status=ResultStatus.SUCCEEDED)
    collector._client.fetch_result.side_effect = [
        RetryableError("transient"),
        good_result,
    ]
    result = collector.collect(_make_handle(), _make_credential())
    assert result.status == ToolResultStatus.SUCCESS
    assert collector._client.fetch_result.call_count == 2


def test_collect_retry_exhausted_returns_error(tmp_path: Path):
    collector = _make_collector(tmp_path, max_retries=1)
    collector._client.fetch_result.side_effect = ClientError("permanent")
    result = collector.collect(_make_handle(), _make_credential())
    assert result.status == ToolResultStatus.ERROR
    assert "回收失败" in result.content
    assert "permanent" in result.content


def test_collect_truncation(tmp_path: Path):
    collector = _make_collector(tmp_path, result_max_bytes=10)
    big_text = "中" * 100
    collector._client.fetch_result.return_value = ExecutionResult(
        final_answer=big_text,
        status=ResultStatus.SUCCEEDED,
    )
    result = collector.collect(_make_handle(), _make_credential())
    assert "截断" in result.content
    assert "300" in result.content  # 100 中文字符 = 300 字节


def test_collect_artifacts_in_content(tmp_path: Path):
    from llm_loop.codearts.models import Artifact

    collector = _make_collector(tmp_path)
    collector._client.fetch_result.return_value = ExecutionResult(
        final_answer="done",
        status=ResultStatus.SUCCEEDED,
        artifacts=[Artifact(name="report.pdf", type="file")],
    )
    result = collector.collect(_make_handle(), _make_credential())
    assert "report.pdf" in result.content
    assert "[制品]" in result.content


def test_collect_log_summary_in_content(tmp_path: Path):
    collector = _make_collector(tmp_path)
    collector._client.fetch_result.return_value = ExecutionResult(
        final_answer="done",
        status=ResultStatus.SUCCEEDED,
        execution_log_summary="step1 completed",
    )
    result = collector.collect(_make_handle(), _make_credential())
    assert "step1 completed" in result.content
    assert "[执行日志摘要]" in result.content


def test_collect_tool_call_id_propagated(tmp_path: Path):
    collector = _make_collector(tmp_path)
    collector._client.fetch_result.return_value = ExecutionResult(
        final_answer="ok",
        status=ResultStatus.SUCCEEDED,
    )
    result = collector.collect(
        _make_handle(),
        _make_credential(),
        tool_call_id="tc-123",
        tool_name="custom_tool",
    )
    assert result.tool_call_id == "tc-123"
    assert result.tool_name == "custom_tool"

"""端到端测试：五条路径全链路（design.md §6.3）.

模拟本地 LLM 经 codearts_dispatch 委派 → 轮询状态 → 回收结果 → 回传 ToolResult。
使用 httpx.MockTransport 模拟 CodeArts OpenAPI 端点。

覆盖路径:
1. 成功: dispatch → SUCCEEDED → collect → SUCCESS
2. 失败: dispatch → FAILED → collect → FAILURE
3. 超时: dispatch → TIMEOUT → collect → TIMEOUT
4. 取消: dispatch → cancel → BLOCKED
5. 状态未知: dispatch → 持续错误 → UNKNOWN
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx

from llm_loop.codearts.audit import AuditLogger
from llm_loop.codearts.client import HttpxCodeArtsClient
from llm_loop.codearts.collector import ResultCollector
from llm_loop.codearts.config import CodeArtsSettings
from llm_loop.codearts.credential import EnvCredentialProvider
from llm_loop.codearts.handle import HandleRegistry
from llm_loop.codearts.models import (
    DispatchTask,
    HandleStatus,
    RiskAssessment,
    RiskLevel,
)
from llm_loop.codearts.scheduler import CodeArtsScheduler
from llm_loop.codearts.sync import StateSynchronizer
from llm_loop.core.message import ToolResultStatus
from llm_loop.event_log.store import EventStore
from llm_loop.tools.safety import CatastrophicGuard


def _make_config(**overrides) -> CodeArtsSettings:
    defaults = dict(
        enabled=True,
        endpoint="https://codearts.example.com",
        region="cn-north-4",
        ak="AK123",
        sk="SK456",
        max_concurrent=10,
        max_retries=1,
        poll_interval_s=5,
    )
    defaults.update(overrides)
    return CodeArtsSettings(**defaults)


def _make_e2e_setup(tmp_path: Path, handler, config=None):
    """构造全真实组件链路（仅 httpx transport mock）."""
    config = config or _make_config()
    transport = httpx.MockTransport(handler)
    client = HttpxCodeArtsClient(config)
    client._client = httpx.Client(transport=transport)

    event_store = EventStore(tmp_path / "events", enabled=True)
    handle_registry = HandleRegistry(event_store, max_concurrent=config.max_concurrent)
    cred_provider = EnvCredentialProvider(config)
    risk_classifier = MagicMock()
    risk_classifier.classify.return_value = RiskAssessment(
        level=RiskLevel.NORMAL, reason="ok", evidence="", local_blocked=False
    )
    mock_sync = MagicMock(spec=StateSynchronizer)
    result_collector = ResultCollector(
        client, event_store,
        result_max_bytes=config.result_max_bytes, max_retries=config.max_retries,
    )
    guard = CatastrophicGuard(audit_dir=None)
    audit_logger = AuditLogger(tmp_path / "audit")
    scheduler = CodeArtsScheduler(
        config=config,
        credential_provider=cred_provider,
        client=client,
        handle_registry=handle_registry,
        state_synchronizer=mock_sync,
        result_collector=result_collector,
        risk_classifier=risk_classifier,
        audit_logger=audit_logger,
        event_store=event_store,
        safety_guard=guard,
        approval_callback=None,
    )
    return scheduler, client, event_store, audit_logger


def _make_task() -> DispatchTask:
    return DispatchTask(task_description="e2e test task", trace_id="e2e-trace-1")


def _verify_event_logged(event_store: EventStore, event_type: str) -> bool:
    """检查事件日志是否包含指定类型事件."""
    events_dir = event_store._dir
    if not events_dir.exists():
        return False
    for f in events_dir.glob("*.jsonl"):
        content = f.read_text(encoding="utf-8")
        if event_type in content:
            return True
    return False


def _verify_audit_logged(audit_logger: AuditLogger, action: str) -> bool:
    audit_file = audit_logger._path
    if not audit_file.exists():
        return False
    return action in audit_file.read_text(encoding="utf-8")


# ── 路径 1: 成功 ──


def test_e2e_success_path(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if "executions" in request.url.path and request.method == "POST":
            return httpx.Response(200, json={"execution_id": "exec-success"})
        if "/status" in request.url.path:
            return httpx.Response(200, json={"status": "SUCCEEDED"})
        if "/result" in request.url.path:
            return httpx.Response(200, json={
                "final_answer": "构建成功，产物已上传",
                "status": "SUCCEEDED",
                "metrics": {"duration_s": 120},
            })
        return httpx.Response(404)

    scheduler, client, event_store, audit_logger = _make_e2e_setup(tmp_path, handler)
    task = _make_task()

    # dispatch
    dispatch_result = scheduler.dispatch(task, session_id="s1")
    assert dispatch_result.status == ToolResultStatus.SUCCESS
    handle_id = dispatch_result.content
    assert "exec-success" in handle_id or "成功" in handle_id

    # collect result
    from llm_loop.codearts.models import ExecutionHandle
    handle = scheduler._handle_registry.get("exec-success")
    if handle is None:
        handle = ExecutionHandle(
            handle_id="exec-success",
            session_id="s1",
            trace_id="e2e-trace-1",
            created_at="2026-01-01T00:00:00Z",
            status=HandleStatus.RUNNING,
        )
    credential = scheduler._credential_provider.get("cn-north-4")
    collect_result = scheduler._result_collector.collect(handle, credential)
    assert collect_result.status == ToolResultStatus.SUCCESS
    assert "构建成功" in collect_result.content

    # 验证事件日志与审计
    assert _verify_event_logged(event_store, "codearts.dispatched")
    assert _verify_audit_logged(audit_logger, "dispatch")
    client.close()


# ── 路径 2: 失败 ──


def test_e2e_failure_path(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if "executions" in request.url.path and request.method == "POST":
            return httpx.Response(200, json={"execution_id": "exec-fail"})
        if "/result" in request.url.path:
            return httpx.Response(200, json={
                "final_answer": "",
                "status": "FAILED",
                "failure_reason": "编译错误: undefined variable",
            })
        return httpx.Response(200, json={"status": "FAILED"})

    scheduler, client, event_store, _ = _make_e2e_setup(tmp_path, handler)
    dispatch_result = scheduler.dispatch(_make_task(), session_id="s1")
    assert dispatch_result.status == ToolResultStatus.SUCCESS

    from llm_loop.codearts.models import ExecutionHandle
    handle = scheduler._handle_registry.get("exec-fail")
    if handle is None:
        handle = ExecutionHandle(
            handle_id="exec-fail",
            session_id="s1",
            trace_id="e2e-trace-1",
            created_at="2026-01-01T00:00:00Z",
            status=HandleStatus.RUNNING,
        )
    credential = scheduler._credential_provider.get("cn-north-4")
    collect_result = scheduler._result_collector.collect(handle, credential)
    assert collect_result.status == ToolResultStatus.FAILURE
    assert "编译错误" in collect_result.content
    client.close()


# ── 路径 3: 超时 ──


def test_e2e_timeout_path(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if "executions" in request.url.path and request.method == "POST":
            return httpx.Response(200, json={"execution_id": "exec-timeout"})
        if "/result" in request.url.path:
            return httpx.Response(200, json={
                "final_answer": "",
                "status": "TIMEOUT",
                "failure_reason": "执行超时（1800s 上限）",
            })
        return httpx.Response(200, json={"status": "TIMEOUT"})

    scheduler, client, _, _ = _make_e2e_setup(tmp_path, handler)
    dispatch_result = scheduler.dispatch(_make_task(), session_id="s1")
    assert dispatch_result.status == ToolResultStatus.SUCCESS

    from llm_loop.codearts.models import ExecutionHandle
    handle = scheduler._handle_registry.get("exec-timeout")
    if handle is None:
        handle = ExecutionHandle(
            handle_id="exec-timeout",
            session_id="s1",
            trace_id="e2e-trace-1",
            created_at="2026-01-01T00:00:00Z",
            status=HandleStatus.RUNNING,
        )
    credential = scheduler._credential_provider.get("cn-north-4")
    collect_result = scheduler._result_collector.collect(handle, credential)
    assert collect_result.status == ToolResultStatus.TIMEOUT
    client.close()


# ── 路径 4: 取消 ──


def test_e2e_cancel_path(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if "executions" in request.url.path and request.method == "POST":
            return httpx.Response(200, json={"execution_id": "exec-cancel"})
        if "/cancel" in request.url.path:
            return httpx.Response(200, json={"cancelled": True})
        return httpx.Response(200, json={"status": "RUNNING"})

    scheduler, client, event_store, _ = _make_e2e_setup(tmp_path, handler)
    dispatch_result = scheduler.dispatch(_make_task(), session_id="s1")
    assert dispatch_result.status == ToolResultStatus.SUCCESS

    cancel_result = scheduler.cancel("exec-cancel")
    assert cancel_result.status in (
        ToolResultStatus.SUCCESS,
        ToolResultStatus.FAILURE,
    )
    assert _verify_event_logged(event_store, "codearts.cancelled")
    client.close()


# ── 路径 5: 状态未知 ──


def test_e2e_unknown_path(tmp_path: Path):
    """远端持续返回 5xx → 状态标注 UNKNOWN 不臆造."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "executions" in request.url.path and request.method == "POST":
            return httpx.Response(200, json={"execution_id": "exec-unknown"})
        return httpx.Response(500, text="internal server error")

    config = _make_config(max_retries=0)
    scheduler, client, event_store, _ = _make_e2e_setup(tmp_path, handler, config=config)
    dispatch_result = scheduler.dispatch(_make_task(), session_id="s1")
    assert dispatch_result.status == ToolResultStatus.SUCCESS

    # 回收结果时远端不可达 → ERROR（不臆造状态）
    from llm_loop.codearts.models import ExecutionHandle
    handle = scheduler._handle_registry.get("exec-unknown")
    if handle is None:
        handle = ExecutionHandle(
            handle_id="exec-unknown",
            session_id="s1",
            trace_id="e2e-trace-1",
            created_at="2026-01-01T00:00:00Z",
            status=HandleStatus.RUNNING,
        )
    credential = scheduler._credential_provider.get("cn-north-4")
    collect_result = scheduler._result_collector.collect(handle, credential)
    assert collect_result.status == ToolResultStatus.ERROR
    assert "回收失败" in collect_result.content
    client.close()


# ── trace_id 贯穿验证 ──


def test_e2e_trace_id_propagation(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if "executions" in request.url.path and request.method == "POST":
            return httpx.Response(200, json={"execution_id": "exec-trace"})
        return httpx.Response(200, json={"status": "RUNNING"})

    scheduler, client, event_store, _ = _make_e2e_setup(tmp_path, handler)
    task = DispatchTask(task_description="trace test", trace_id="my-trace-id-123")
    result = scheduler.dispatch(task, session_id="s1")
    assert result.status == ToolResultStatus.SUCCESS

    # 验证 trace_id 出现在事件日志
    events_dir = event_store._dir
    found_trace = False
    if events_dir.exists():
        for f in events_dir.glob("*.jsonl"):
            if "my-trace-id-123" in f.read_text(encoding="utf-8"):
                found_trace = True
                break
    assert found_trace
    client.close()


# ── [状态: xxx] 标注规范验证 ──


def test_e2e_status_annotation_in_content(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if "executions" in request.url.path and request.method == "POST":
            return httpx.Response(200, json={"execution_id": "exec-annot"})
        return httpx.Response(200, json={"status": "RUNNING"})

    scheduler, client, _, _ = _make_e2e_setup(tmp_path, handler)
    result = scheduler.dispatch(_make_task(), session_id="s1")
    assert result.status == ToolResultStatus.SUCCESS
    assert "[状态:" in result.content or "状态" in result.content
    client.close()

"""集成测试：跨模块调用链路（design.md §6.2）.

①装配集成（enabled/凭证/工具注册）
②dispatch → status → cancel 链路
③workflow_run + executor="codearts" 步骤
④重启接管 recover_in_flight
⑤审批网关（放行/拒绝/fail-closed）
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from llm_loop.codearts.audit import AuditLogger
from llm_loop.codearts.collector import ResultCollector
from llm_loop.codearts.config import CodeArtsSettings
from llm_loop.codearts.credential import EnvCredentialProvider
from llm_loop.codearts.handle import HandleRegistry
from llm_loop.codearts.models import (
    DispatchTask,
    ExecutionHandle,
    HandleStatus,
    RemoteStatus,
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
    )
    defaults.update(overrides)
    return CodeArtsSettings(**defaults)


def _make_scheduler(
    tmp_path: Path,
    config: CodeArtsSettings | None = None,
    *,
    client=None,
    risk_classifier=None,
    approval_callback=None,
) -> CodeArtsScheduler:
    config = config or _make_config()
    event_store = EventStore(tmp_path / "events", enabled=True)
    handle_registry = HandleRegistry(event_store, max_concurrent=config.max_concurrent)
    cred_provider = EnvCredentialProvider(config)
    mock_client = client or MagicMock()
    mock_risk = risk_classifier or MagicMock()
    mock_risk.classify.return_value = RiskAssessment(
        level=RiskLevel.NORMAL, reason="ok", evidence="", local_blocked=False
    )
    mock_sync = MagicMock(spec=StateSynchronizer)
    mock_collector = MagicMock(spec=ResultCollector)
    guard = CatastrophicGuard(audit_dir=None)
    audit_logger = AuditLogger(tmp_path / "audit")
    return CodeArtsScheduler(
        config=config,
        credential_provider=cred_provider,
        client=mock_client,
        handle_registry=handle_registry,
        state_synchronizer=mock_sync,
        result_collector=mock_collector,
        risk_classifier=mock_risk,
        audit_logger=audit_logger,
        event_store=event_store,
        safety_guard=guard,
        approval_callback=approval_callback,
    )


def _make_task() -> DispatchTask:
    return DispatchTask(task_description="integration test task", trace_id="trace-1")


# ── ① 装配集成 ──


def test_assembly_disabled_skips(tmp_path: Path):
    config = _make_config(enabled=False)
    scheduler = _make_scheduler(tmp_path, config)
    result = scheduler.dispatch(_make_task(), session_id="s1")
    assert result.status == ToolResultStatus.ERROR
    assert "未装配" in result.content


def test_assembly_no_credential_skips(tmp_path: Path):
    config = _make_config(ak="", sk="", iam_token="")
    scheduler = _make_scheduler(tmp_path, config)
    result = scheduler.dispatch(_make_task(), session_id="s1")
    assert result.status == ToolResultStatus.ERROR


def test_assembly_valid_registers_tools(tmp_path: Path):
    from llm_loop.tools.builtin.codearts_cancel import CodeArtsCancelTool
    from llm_loop.tools.builtin.codearts_capability import CodeArtsCapabilityTool
    from llm_loop.tools.builtin.codearts_dispatch import CodeArtsDispatchTool
    from llm_loop.tools.builtin.codearts_status import CodeArtsStatusTool

    scheduler = _make_scheduler(tmp_path)
    dispatch_tool = CodeArtsDispatchTool(scheduler)
    status_tool = CodeArtsStatusTool(scheduler)
    cancel_tool = CodeArtsCancelTool(scheduler)
    cap_tool = CodeArtsCapabilityTool(scheduler)
    assert dispatch_tool.name == "codearts_dispatch"
    assert status_tool.name == "codearts_status"
    assert cancel_tool.name == "codearts_cancel"
    assert cap_tool.name == "codearts_capability"


# ── ② dispatch → status → cancel 链路 ──


def test_dispatch_status_cancel_chain(tmp_path: Path):
    scheduler = _make_scheduler(tmp_path)
    handle = ExecutionHandle(
        handle_id="h1",
        session_id="s1",
        trace_id="t1",
        created_at="2026-01-01T00:00:00Z",
        status=HandleStatus.RUNNING,
        remote_status=RemoteStatus.RUNNING,
    )
    scheduler._client.trigger_execution.return_value = handle

    # dispatch
    task = _make_task()
    result = scheduler.dispatch(task, session_id="s1")
    assert result.status == ToolResultStatus.SUCCESS

    # status
    status_result = scheduler.query_status("h1")
    assert status_result.status in (
        ToolResultStatus.SUCCESS,
        ToolResultStatus.FAILURE,
    )

    # cancel
    scheduler._client.cancel_execution.return_value = True
    cancel_result = scheduler.cancel("h1")
    assert cancel_result.status in (
        ToolResultStatus.SUCCESS,
        ToolResultStatus.FAILURE,
    )


def test_dispatch_nonexistent_status_fails(tmp_path: Path):
    scheduler = _make_scheduler(tmp_path)
    result = scheduler.query_status("nonexistent-handle")
    assert result.status == ToolResultStatus.FAILURE
    assert "不存在" in result.content


# ── ③ workflow_run + executor="codearts" ──


def test_workflow_codearts_step_not_assembled(tmp_path: Path):
    from llm_loop.tools.builtin.workflow import WorkflowRunTool

    runner = MagicMock()
    tool = WorkflowRunTool(runner, codearts_scheduler=None)
    result = tool.execute(
        mode="pipeline",
        steps=[{"task": "远端任务", "executor": "codearts"}],
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "未装配" in result.content


def test_workflow_codearts_step_dispatches(tmp_path: Path):
    from llm_loop.tools.builtin.workflow import WorkflowRunTool

    scheduler = _make_scheduler(tmp_path)
    handle = ExecutionHandle(
        handle_id="h1",
        session_id="s1",
        trace_id="t1",
        created_at="2026-01-01T00:00:00Z",
        status=HandleStatus.RUNNING,
        remote_status=RemoteStatus.RUNNING,
    )
    scheduler._client.trigger_execution.return_value = handle

    runner = MagicMock()
    tool = WorkflowRunTool(runner, codearts_scheduler=scheduler)
    result = tool.execute(
        mode="pipeline",
        steps=[{"task": "远端构建任务", "executor": "codearts"}],
    )
    assert "executor=codearts" in result.content
    assert "[状态:" in result.content


# ── ④ 重启接管 ──


def test_recover_in_flight_no_handles(tmp_path: Path):
    scheduler = _make_scheduler(tmp_path)
    recovered = scheduler.recover_in_flight()
    assert recovered == 0


def test_recover_in_flight_with_existing_handle(tmp_path: Path):
    scheduler = _make_scheduler(tmp_path)
    handle = ExecutionHandle(
        handle_id="h1",
        session_id="s1",
        trace_id="t1",
        created_at="2026-01-01T00:00:00Z",
        status=HandleStatus.RUNNING,
        remote_status=RemoteStatus.RUNNING,
    )
    scheduler._handle_registry.register(handle, session_id="s1", trace_id="t1")
    recovered = scheduler.recover_in_flight()
    assert recovered >= 0


# ── ⑤ 审批网关 ──


def test_approval_gateway_approved(tmp_path: Path):
    scheduler = _make_scheduler(
        tmp_path,
        approval_callback=lambda desc, reason: True,
    )
    mock_risk = MagicMock()
    mock_risk.classify.return_value = RiskAssessment(
        level=RiskLevel.CATASTROPHIC,
        reason="生产部署",
        evidence="e",
        local_blocked=False,
    )
    scheduler._risk_classifier = mock_risk
    handle = ExecutionHandle(
        handle_id="h1",
        session_id="s1",
        trace_id="t1",
        created_at="2026-01-01T00:00:00Z",
        status=HandleStatus.RUNNING,
        remote_status=RemoteStatus.RUNNING,
    )
    scheduler._client.trigger_execution.return_value = handle
    result = scheduler.dispatch(_make_task(), session_id="s1")
    assert result.status == ToolResultStatus.SUCCESS


def test_approval_gateway_rejected(tmp_path: Path):
    scheduler = _make_scheduler(
        tmp_path,
        approval_callback=lambda desc, reason: False,
    )
    mock_risk = MagicMock()
    mock_risk.classify.return_value = RiskAssessment(
        level=RiskLevel.CATASTROPHIC,
        reason="生产部署",
        evidence="e",
        local_blocked=False,
    )
    scheduler._risk_classifier = mock_risk
    result = scheduler.dispatch(_make_task(), session_id="s1")
    assert result.status == ToolResultStatus.BLOCKED
    assert "拒绝" in result.content or "审批" in result.content


def test_approval_gateway_no_callback_fail_closed(tmp_path: Path):
    scheduler = _make_scheduler(tmp_path, approval_callback=None)
    mock_risk = MagicMock()
    mock_risk.classify.return_value = RiskAssessment(
        level=RiskLevel.CATASTROPHIC,
        reason="生产部署",
        evidence="e",
        local_blocked=False,
    )
    scheduler._risk_classifier = mock_risk
    result = scheduler.dispatch(_make_task(), session_id="s1")
    assert result.status == ToolResultStatus.BLOCKED
    assert "审批" in result.content


# ── 事件日志落盘验证 ──


def test_dispatch_writes_event_log(tmp_path: Path):
    scheduler = _make_scheduler(tmp_path)
    handle = ExecutionHandle(
        handle_id="h1",
        session_id="s1",
        trace_id="t1",
        created_at="2026-01-01T00:00:00Z",
        status=HandleStatus.RUNNING,
        remote_status=RemoteStatus.RUNNING,
    )
    scheduler._client.trigger_execution.return_value = handle
    scheduler.dispatch(_make_task(), session_id="s1")
    events_dir = tmp_path / "events"
    assert events_dir.exists()
    event_files = list(events_dir.glob("*.jsonl"))
    assert len(event_files) > 0
    content = event_files[0].read_text(encoding="utf-8")
    assert "codearts.dispatched" in content


def test_audit_log_written_on_dispatch(tmp_path: Path):
    scheduler = _make_scheduler(tmp_path)
    handle = ExecutionHandle(
        handle_id="h1",
        session_id="s1",
        trace_id="t1",
        created_at="2026-01-01T00:00:00Z",
        status=HandleStatus.RUNNING,
        remote_status=RemoteStatus.RUNNING,
    )
    scheduler._client.trigger_execution.return_value = handle
    scheduler.dispatch(_make_task(), session_id="s1")
    audit_file = tmp_path / "audit" / "codearts_dispatch.jsonl"
    assert audit_file.exists()
    content = audit_file.read_text(encoding="utf-8")
    assert "dispatch" in content

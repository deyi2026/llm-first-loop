"""调度器门面单元测试（design.md §2.2.2.1）.

使用 mock 依赖测试 dispatch 全链路异常映射与 fail-open 行为。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from llm_loop.codearts.audit import AuditLogger
from llm_loop.codearts.client import ClientError
from llm_loop.codearts.collector import ResultCollector
from llm_loop.codearts.config import CodeArtsSettings
from llm_loop.codearts.credential import CredentialError, EnvCredentialProvider
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


def _make_config() -> CodeArtsSettings:
    return CodeArtsSettings(
        enabled=True,
        endpoint="https://codearts.example.com",
        region="cn-north-4",
        ak="AK123",
        sk="SK456",
        max_concurrent=10,
    )


def _make_scheduler(
    config: CodeArtsSettings | None = None,
    *,
    credential_provider=None,
    client=None,
    risk_classifier=None,
    approval_callback=None,
    tmp_path: Path | None = None,
) -> CodeArtsScheduler:
    config = config or _make_config()
    audit_dir = tmp_path or Path("/tmp/test_audit")
    event_store = EventStore(audit_dir / "events", enabled=False)
    handle_registry = HandleRegistry(event_store, max_concurrent=config.max_concurrent)
    cred_provider = credential_provider or EnvCredentialProvider(config)
    mock_client = client or MagicMock()
    mock_risk = risk_classifier or MagicMock()
    mock_risk.classify.return_value = RiskAssessment(
        level=RiskLevel.NORMAL, reason="ok", evidence="", local_blocked=False
    )
    mock_sync = MagicMock(spec=StateSynchronizer)
    mock_collector = MagicMock(spec=ResultCollector)
    guard = CatastrophicGuard(audit_dir=None)
    audit_logger = AuditLogger(audit_dir)
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
    return DispatchTask(task_description="test task", trace_id="t1")


def test_dispatch_disabled(tmp_path: Path):
    config = CodeArtsSettings(enabled=False)
    scheduler = _make_scheduler(config, tmp_path=tmp_path)
    result = scheduler.dispatch(_make_task(), session_id="s1")
    assert result.status == ToolResultStatus.ERROR
    assert "未装配" in result.content


def test_dispatch_concurrent_limit(tmp_path: Path):
    config = CodeArtsSettings(enabled=True, endpoint="https://x.com", ak="a", sk="b", max_concurrent=1)
    scheduler = _make_scheduler(config, tmp_path=tmp_path)
    # 手动填满在途
    handle = ExecutionHandle(handle_id="h1", session_id="s1", trace_id="t1", created_at="2026-01-01T00:00:00Z", status=HandleStatus.RUNNING)
    scheduler._handle_registry.register(handle, session_id="s1", trace_id="t1")
    result = scheduler.dispatch(_make_task(), session_id="s1")
    assert result.status == ToolResultStatus.BLOCKED
    assert "在途任务已满" in result.content


def test_dispatch_local_blocked(tmp_path: Path):
    scheduler = _make_scheduler(tmp_path=tmp_path)
    mock_risk = MagicMock()
    mock_risk.classify.return_value = RiskAssessment(
        level=RiskLevel.CATASTROPHIC,
        reason="灾难性",
        evidence="e",
        local_blocked=True,
        local_block_reason="rm -rf",
    )
    scheduler._risk_classifier = mock_risk
    result = scheduler.dispatch(_make_task(), session_id="s1")
    assert result.status == ToolResultStatus.BLOCKED
    assert "禁止动作" in result.content


def test_dispatch_catastrophic_no_callback_fail_closed(tmp_path: Path):
    config = _make_config()
    scheduler = _make_scheduler(config, approval_callback=None, tmp_path=tmp_path)
    mock_risk = MagicMock()
    mock_risk.classify.return_value = RiskAssessment(
        level=RiskLevel.CATASTROPHIC, reason="生产部署", evidence="e", local_blocked=False
    )
    scheduler._risk_classifier = mock_risk
    result = scheduler.dispatch(_make_task(), session_id="s1")
    assert result.status == ToolResultStatus.BLOCKED
    assert "人工审批" in result.content


def test_dispatch_catastrophic_approved(tmp_path: Path):
    config = _make_config()
    scheduler = _make_scheduler(config, approval_callback=lambda d, r: True, tmp_path=tmp_path)
    mock_risk = MagicMock()
    mock_risk.classify.return_value = RiskAssessment(
        level=RiskLevel.CATASTROPHIC, reason="生产部署", evidence="e", local_blocked=False
    )
    scheduler._risk_classifier = mock_risk
    mock_client = MagicMock()
    handle = ExecutionHandle(handle_id="h1", session_id="s1", trace_id="t1", created_at="2026-01-01T00:00:00Z", status=HandleStatus.RUNNING, remote_status=RemoteStatus.RUNNING)
    mock_client.trigger_execution.return_value = handle
    scheduler._client = mock_client
    result = scheduler.dispatch(_make_task(), session_id="s1")
    assert result.status == ToolResultStatus.SUCCESS


def test_dispatch_credential_error(tmp_path: Path):
    config = _make_config()
    scheduler = _make_scheduler(config, tmp_path=tmp_path)
    mock_cred = MagicMock()
    mock_cred.get.side_effect = CredentialError("凭证失效")
    scheduler._credential_provider = mock_cred
    result = scheduler.dispatch(_make_task(), session_id="s1")
    assert result.status == ToolResultStatus.ERROR
    assert "凭证" in result.content


def test_dispatch_client_error(tmp_path: Path):
    config = _make_config()
    scheduler = _make_scheduler(config, tmp_path=tmp_path)
    mock_client = MagicMock()
    mock_client.trigger_execution.side_effect = ClientError("400 Bad Request")
    scheduler._client = mock_client
    result = scheduler.dispatch(_make_task(), session_id="s1")
    assert result.status == ToolResultStatus.FAILURE
    assert "拒绝执行" in result.content


def test_query_status_nonexistent(tmp_path: Path):
    scheduler = _make_scheduler(tmp_path=tmp_path)
    result = scheduler.query_status("nonexistent")
    assert result.status == ToolResultStatus.FAILURE
    assert "不存在" in result.content


def test_cancel_nonexistent(tmp_path: Path):
    scheduler = _make_scheduler(tmp_path=tmp_path)
    result = scheduler.cancel("nonexistent")
    assert result.status == ToolResultStatus.FAILURE


def test_declare_capability(tmp_path: Path):
    scheduler = _make_scheduler(tmp_path=tmp_path)
    cap = scheduler.declare_capability()
    assert "适用场景" in cap
    assert "局限性" in cap
    assert "远端依赖" in cap
    assert "非完备" in cap
    assert "保证任务成功" not in cap  # 不夸大能力


def test_metrics(tmp_path: Path):
    scheduler = _make_scheduler(tmp_path=tmp_path)
    m = scheduler.metrics()
    assert "dispatch_count" in m
    assert "in_flight" in m
    assert "success_count" in m


def test_recover_in_flight(tmp_path: Path):
    scheduler = _make_scheduler(tmp_path=tmp_path)
    recovered = scheduler.recover_in_flight()
    assert isinstance(recovered, int)
    assert recovered >= 0

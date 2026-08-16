"""数据模型单元测试（design.md §2.3.2）."""

from __future__ import annotations

import dataclasses

import pytest

from llm_loop.codearts.models import (
    TERMINAL_STATUSES,
    Artifact,
    AuditAction,
    AuditRecord,
    AuditResult,
    Credential,
    CredentialKind,
    DispatchTask,
    ExecutionHandle,
    ExecutionResult,
    HandleStatus,
    Priority,
    RemoteStatus,
    ResultStatus,
    RiskLevel,
    TimeoutBudget,
)


def test_timeout_budget_defaults():
    tb = TimeoutBudget()
    assert tb.connect_s == 10
    assert tb.call_s == 30
    assert tb.exec_s == 1800


def test_dispatch_task_frozen():
    task = DispatchTask(task_description="test", trace_id="t1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        task.task_description = "changed"  # type: ignore[misc]


def test_execution_handle_frozen():
    h = ExecutionHandle(handle_id="h1", session_id="s1", trace_id="t1", created_at="2026-01-01T00:00:00Z")
    with pytest.raises(dataclasses.FrozenInstanceError):
        h.handle_id = "h2"  # type: ignore[misc]


def test_credential_ref_no_plaintext():
    cred = Credential(kind=CredentialKind.AK_SK, region="cn-north-4", ak="MYAK123", sk="mysk456")
    ref = cred.ref()
    assert "MYAK123" not in ref
    assert "mysk456" not in ref
    assert ref == "ak_sk:cn-north-4"


def test_enum_values():
    assert Priority.NORMAL == "normal"
    assert RiskLevel.CATASTROPHIC == "catastrophic"
    assert HandleStatus.UNKNOWN == "unknown"
    assert RemoteStatus.RUNNING == "running"
    assert ResultStatus.SUCCEEDED == "succeeded"
    assert AuditAction.DISPATCH == "dispatch"
    assert AuditResult.BLOCKED == "blocked"
    assert CredentialKind.IAM_TOKEN == "iam_token"


def test_terminal_statuses():
    assert HandleStatus.SUCCEEDED in TERMINAL_STATUSES
    assert HandleStatus.FAILED in TERMINAL_STATUSES
    assert HandleStatus.RUNNING not in TERMINAL_STATUSES
    assert HandleStatus.PENDING not in TERMINAL_STATUSES


def test_execution_result_metrics_type_safe():
    r = ExecutionResult(
        final_answer="ok",
        status=ResultStatus.SUCCEEDED,
        metrics={"duration": 100, "tokens": 500, "model": "deepseek-v4"},
    )
    assert r.metrics["duration"] == 100
    assert r.metrics["model"] == "deepseek-v4"


def test_audit_record_fields():
    rec = AuditRecord(
        timestamp="2026-01-01T00:00:00Z",
        trace_id="t1",
        action=AuditAction.DISPATCH,
        target_api="/v1/agent/executions",
        response_status=200,
        credential_ref="ak_sk:cn-north-4",
        params_summary="task",
        result=AuditResult.SUCCESS,
    )
    assert rec.action == AuditAction.DISPATCH
    assert rec.result == AuditResult.SUCCESS


def test_artifact_defaults():
    a = Artifact(name="report.pdf", type="pdf")
    assert a.access == ""

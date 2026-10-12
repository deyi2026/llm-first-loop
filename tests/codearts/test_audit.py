"""审计记录器单元测试（design.md §2.2.2.8）."""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.codearts.audit import AuditLogger
from llm_loop.codearts.models import AuditAction, AuditRecord, AuditResult


def test_audit_log_writes_jsonl(tmp_path: Path):
    logger = AuditLogger(tmp_path)
    rec = AuditRecord(
        timestamp="2026-01-01T00:00:00Z",
        trace_id="t1",
        action=AuditAction.DISPATCH,
        target_api="/v1/agent/executions",
        response_status=200,
        credential_ref="ak_sk:cn-north-4",
        params_summary="task description",
        result=AuditResult.SUCCESS,
    )
    logger.log(rec)
    audit_file = tmp_path / "codearts_dispatch.jsonl"
    assert audit_file.exists()
    lines = audit_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["action"] == "dispatch"
    assert data["result"] == "success"


def test_audit_no_credential_plaintext(tmp_path: Path, monkeypatch):
    # 设置一个敏感环境变量
    monkeypatch.setenv("CODEARTS_AK", "AKIAIOSFODNN7EXAMPLE")
    monkeypatch.setenv("CODEARTS_SK", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    logger = AuditLogger(tmp_path)
    rec = AuditRecord(
        timestamp="2026-01-01T00:00:00Z",
        trace_id="t1",
        action=AuditAction.DISPATCH,
        target_api="/v1/agent/executions",
        response_status=200,
        credential_ref="ak_sk:cn-north-4",
        params_summary="task with AKIAIOSFODNN7EXAMPLE and wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        result=AuditResult.SUCCESS,
    )
    logger.log(rec)
    audit_file = tmp_path / "codearts_dispatch.jsonl"
    content = audit_file.read_text(encoding="utf-8")
    assert "AKIAIOSFODNN7EXAMPLE" not in content
    assert "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" not in content


def test_audit_fail_open_on_dir_not_writable(tmp_path: Path):
    logger = AuditLogger(tmp_path / "nonexistent" / "deep")
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
    # 应不抛异常（fail-open）
    logger.log(rec)

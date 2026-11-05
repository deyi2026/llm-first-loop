"""merge queue / S1 gate 工具面的失败口径与纯函数边界（RULE-AI-35 实测应拦输入）."""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection import registry_merge_queue
from llm_loop.introspection.tools_merge_queue import (
    run_lane_gate_check,
    run_lane_queue_confirm,
    run_lane_queue_status,
)


class _Host:
    def __init__(self, audit_dir: Path | None) -> None:
        self.audit_dir = str(audit_dir) if audit_dir is not None else None
        self.ctx = None


def test_tool_defs_exposed() -> None:
    names = [d["name"] for d in registry_merge_queue.tool_defs()]
    assert names == [
        "lane_queue_submit",
        "lane_queue_status",
        "lane_merge_advice",
        "lane_queue_confirm",
        "lane_gate_check",
    ]


def test_unknown_tool_returns_none() -> None:
    assert registry_merge_queue.execute("nope", {}, _Host(None)) is None


def test_queue_status_without_audit_dir_degraded() -> None:
    result = run_lane_queue_status(None, _Host(None), {})
    assert result.status is ToolResultStatus.FAILURE
    assert "store_unavailable" in result.content


def test_gate_check_requires_evidence() -> None:
    result = run_lane_gate_check(None, _Host(None), {})
    assert result.status is ToolResultStatus.FAILURE
    assert "missing_param" in result.content


def test_gate_check_blocks_when_main_broken() -> None:
    """应拦输入被拦: main broken 必须 verdict=fail 并指名 s1_01。"""
    evidence = {
        "lane": {"lane_id": "lane-x", "paths": ["src/x.py"]},
        "main": {"head_sha": "a" * 40, "broken": True},
        "now_iso": "2026-11-05T10:00:00",
    }
    result = run_lane_gate_check(None, _Host(None), {"evidence": evidence})
    assert result.status is ToolResultStatus.SUCCESS
    assert '"verdict": "fail"' in result.content
    assert "s1_01" in result.content


def test_gate_check_rollback_denied_by_default() -> None:
    """开关默认关: 即使部署 sha 与 main head 一致也不放行自动回滚。"""
    evidence = {
        "lane": {"lane_id": "lane-x"},
        "main": {"head_sha": "a" * 40},
        "deployment": {"target_sha": "a" * 40},
    }
    result = run_lane_gate_check(
        None, _Host(None), {"evidence": evidence, "rollback": True}
    )
    assert result.status is ToolResultStatus.SUCCESS
    assert '"allow": false' in result.content


def test_confirm_rejects_bad_action() -> None:
    result = run_lane_queue_confirm(
        None, _Host(None), {"lane_id": "lane-x", "action": "bogus"}
    )
    assert result.status is ToolResultStatus.FAILURE
    assert "missing_param" in result.content

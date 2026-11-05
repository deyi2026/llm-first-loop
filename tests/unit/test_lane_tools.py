"""lane_* 工具的失败口径与门禁（A10 无凭证不合 / A9 CAS 回执）."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.tools_lane import (
    run_lane_close,
    run_lane_merge_request,
    run_lane_open,
    run_lane_update,
)


class _Host:
    def __init__(self, audit_dir: Path) -> None:
        self.audit_dir = str(audit_dir)
        self.ctx = None


@pytest.fixture()
def host(tmp_path: Path) -> _Host:
    return _Host(tmp_path)


def _open(host: _Host, **kw):
    args = {"branch": "fix/x", "worktree": "/tmp/wt-x", "goal_id": "goal-9", "paths": ["src/x.py"]}
    args.update(kw)
    return run_lane_open(None, host, args)


def _lane_id(result) -> str:
    for token in result.content.split():
        if token.startswith("lane_id="):
            return token.split("=", 1)[1]
    raise AssertionError(f"no lane_id in: {result.content}")


def test_open_requires_mandatory_params(host: _Host) -> None:
    result = run_lane_open(None, host, {"branch": "fix/x"})
    assert result.status is ToolResultStatus.FAILURE
    assert "missing_param" in result.content


def test_merge_request_blocked_without_verify_ref(host: _Host) -> None:
    lane_id = _lane_id(_open(host))
    result = run_lane_merge_request(None, host, {"lane_id": lane_id, "expected_version": 1})
    assert result.status is ToolResultStatus.FAILURE
    assert "verify_required" in result.content


def test_merge_request_passes_after_verify_ref(host: _Host) -> None:
    lane_id = _lane_id(_open(host))
    updated = run_lane_update(
        None, host, {"lane_id": lane_id, "expected_version": 1, "verify_ref": "evidence://v1/abc"}
    )
    assert updated.status is ToolResultStatus.SUCCESS
    result = run_lane_merge_request(None, host, {"lane_id": lane_id, "expected_version": 2})
    assert result.status is ToolResultStatus.SUCCESS
    assert "status=verifying" in result.content


def test_cas_conflict_receipt_carries_current_version(host: _Host) -> None:
    lane_id = _lane_id(_open(host))
    run_lane_update(None, host, {"lane_id": lane_id, "expected_version": 1, "head_sha": "a" * 40})
    stale = run_lane_update(None, host, {"lane_id": lane_id, "expected_version": 1, "head_sha": "b" * 40})
    assert stale.status is ToolResultStatus.FAILURE
    assert "current=2" in stale.content


def test_close_requires_reason(host: _Host) -> None:
    lane_id = _lane_id(_open(host))
    result = run_lane_close(None, host, {"lane_id": lane_id, "expected_version": 1, "reason": " "})
    assert result.status is ToolResultStatus.FAILURE
    assert "reason" in result.content


def test_second_main_lane_for_same_goal_is_rejected(host: _Host) -> None:
    _open(host)
    result = _open(host, branch="fix/y", worktree="/tmp/wt-y")
    assert result.status is ToolResultStatus.FAILURE
    assert "constraint_violation" in result.content

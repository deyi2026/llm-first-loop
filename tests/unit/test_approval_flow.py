"""T5a(2026-08-14) 人工审批流测试（零 LLM 零网络）.

覆盖: 无回调拦截即拒（fail-closed 零回归）/ 回调批准放行 / 回调拒绝 BLOCKED /
回调异常 fail-closed 拒绝 / 灾难性安全硬阻断不可审批 / 审计落盘（approved/
rejected/no_callback）/ 运行时注入移除 / CLI 审批 prompt 无终端拒绝。
"""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.registry import ToolRegistry


def _registry(*, exec_mode: str = "blocked", audit_path: Path | None = None) -> ToolRegistry:
    reg = ToolRegistry(exec_mode=exec_mode, approval_audit_path=audit_path)
    reg.register(ExecuteCommandTool())
    return reg


def _reg_execute(reg: ToolRegistry, name: str = "execute_command", args: dict | None = None):
    return reg.execute(ToolCall(id="tc-1", name=name, arguments=args or {"command": "echo hi"}))


# ── 无回调 fail-closed（零回归）──


def test_no_callback_blocked_as_before(tmp_path):
    """无审批回调 → 拦截即拒绝（与 T5a 前行为一致，零回归）."""
    reg = _registry(exec_mode="blocked", audit_path=tmp_path / "audit" / "approval.jsonl")
    r = _reg_execute(reg)
    assert r.status == ToolResultStatus.BLOCKED
    assert "人工执行" in r.error_detail
    # no_callback 审计落盘
    recs = [
        json.loads(line)
        for line in (tmp_path / "audit" / "approval.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert recs[-1]["decision"] == "no_callback"


def test_no_exec_mode_unchanged(tmp_path):
    """未启用 EXEC_MODE 分级 → 审批完全不介入（零回归）."""
    reg = _registry(exec_mode="", audit_path=tmp_path / "approval.jsonl")
    assert _reg_execute(reg).status == ToolResultStatus.SUCCESS
    assert not (tmp_path / "approval.jsonl").exists()


# ── 回调批准 / 拒绝 ──


def test_callback_approve_allows_execution(tmp_path):
    """人工批准 → 放行执行，回执 SUCCESS."""
    reg = _registry(exec_mode="blocked", audit_path=tmp_path / "approval.jsonl")
    reg.set_approval_callback(lambda name, summary: True)
    r = _reg_execute(reg)
    assert r.status == ToolResultStatus.SUCCESS


def test_callback_reject_blocks(tmp_path):
    """人工拒绝 → BLOCKED + 标注人工拒绝."""
    reg = _registry(exec_mode="blocked", audit_path=tmp_path / "approval.jsonl")
    reg.set_approval_callback(lambda name, summary: False)
    r = _reg_execute(reg)
    assert r.status == ToolResultStatus.BLOCKED
    assert "人工审批未通过" in r.content


def test_callback_receives_tool_and_args(tmp_path):
    """回调收到工具名与参数摘要（可展示给人工）."""
    reg = _registry(exec_mode="blocked", audit_path=tmp_path / "approval.jsonl")
    seen: list[tuple[str, str]] = []

    def cb(name, summary):
        seen.append((name, summary))
        return True

    reg.set_approval_callback(cb)
    _reg_execute(reg, args={"command": "rm -rf /tmp/x"})
    assert seen and seen[0][0] == "execute_command"
    assert "rm -rf /tmp/x" in seen[0][1]


def test_callback_exception_fail_closed(tmp_path):
    """回调异常 → 拒绝（fail-closed，不静默放行）."""
    reg = _registry(exec_mode="blocked", audit_path=tmp_path / "approval.jsonl")

    def boom(name, summary):
        raise RuntimeError("终端异常")

    reg.set_approval_callback(boom)
    r = _reg_execute(reg)
    assert r.status == ToolResultStatus.BLOCKED


def test_approval_audit_records_decision(tmp_path):
    """审计含 approved/rejected 与参数摘要（不含密钥场景由摘要截断保证）."""
    audit = tmp_path / "approval.jsonl"
    reg = _registry(exec_mode="blocked", audit_path=audit)
    reg.set_approval_callback(lambda n, s: True)
    _reg_execute(reg, args={"command": "ls -la"})
    reg.set_approval_callback(lambda n, s: False)
    _reg_execute(reg, args={"command": "rm x"})
    lines = [
        line for line in audit.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    recs = [json.loads(line) for line in lines]
    assert [r["decision"] for r in recs] == ["approved", "rejected"]
    assert recs[0]["tool"] == "execute_command"
    assert "ls -la" in recs[0]["args_summary"]


def test_callback_removal_restores_fail_closed(tmp_path):
    """set_approval_callback(None) 移除 → 恢复拦截即拒."""
    reg = _registry(exec_mode="blocked")
    reg.set_approval_callback(lambda n, s: True)
    assert _reg_execute(reg).status == ToolResultStatus.SUCCESS
    reg.set_approval_callback(None)
    assert _reg_execute(reg).status == ToolResultStatus.BLOCKED


# ── 灾难性安全硬阻断不可审批 ──


def test_catastrophic_guard_not_approvable(tmp_path):
    """灾难性安全硬阻断优先于审批（审批只对 EXEC_MODE 拦截生效）."""
    reg = _registry(exec_mode="", audit_path=tmp_path / "approval.jsonl")
    reg.set_approval_callback(lambda n, s: True)  # 即使批准也不放行
    r = reg.execute(
        ToolCall(
            id="tc-x",
            name="execute_command",
            arguments={"command": "rm -rf /"},
        )
    )
    assert r.status == ToolResultStatus.BLOCKED
    assert "安全硬阻断" in r.content
    assert not (tmp_path / "approval.jsonl").exists()  # 未进审批通道


# ── CLI 审批 prompt（无终端 fail-closed）──


def test_cli_approval_prompt_no_terminal():
    """stdin 无终端（EOF）→ 拒绝（fail-closed）."""
    import io
    import sys
    from unittest import mock

    from llm_loop.cli import _cli_approval_prompt

    with mock.patch.object(sys, "stdin", io.StringIO("")):
        assert _cli_approval_prompt("execute_command", "cmd") is False


def test_cli_approval_prompt_yes():
    """终端输入 y → 批准."""
    from unittest import mock

    from llm_loop.cli import _cli_approval_prompt

    with mock.patch("builtins.input", return_value="y"):
        assert _cli_approval_prompt("execute_command", "cmd") is True
    with mock.patch("builtins.input", return_value="n"):
        assert _cli_approval_prompt("execute_command", "cmd") is False

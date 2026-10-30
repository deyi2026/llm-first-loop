"""P1-a 命令通道写侧闸的测试（DESIGN-20261030 §16）.

覆盖三层：
1. **判定层**（core/command_scope_guard）：应拦输入必须被拦、放行必须放行、
   已知残余必须显式断言（不假装已拦）。
2. **强制层**（tools/builtin/execute_command）：受限 child 的越权写命令被
   程序级拒绝，且**没有真的执行**。
3. **审计层**（core/write_scope）：未验证路径进 scope_unverified，观测面可见。

门禁自证伪（DESIGN §15.6 教训）：把闸打成空实现后，"应拦输入"用例必须变红——
否则这些用例测的是空转，不是拦截。
"""

from __future__ import annotations

import pytest

from llm_loop.core.command_scope_guard import CommandScopeDecision, check_command_scope
from llm_loop.core.run_context import current_write_scope
from llm_loop.core.write_scope import (
    WriteScope,
    write_scope_audit_reset,
    write_scope_audit_snapshot,
)

WS = "/tmp/llm-p1a-guard-ws"


def _scope(paths=("src/**",), mode="allow", declared=True) -> WriteScope:
    return WriteScope(paths=tuple(paths), mode=mode, declared=declared)


def _check(command: str, scope: WriteScope | None = None, workdir: str = ""):
    return check_command_scope(
        command,
        scope=_scope() if scope is None else scope,
        workspace_root=WS,
        workdir=workdir,
    )


def _tool():
    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool

    return ExecuteCommandTool()


# ── 判定层：应拦输入（RULE-AI-35：每条门禁都要有"应拦输入"实测）───────────

BLOCKED_CASES = [
    ("rm /etc/passwd", "write_target_outside_scope"),
    ("rm -rf /", "write_target_outside_scope"),
    ("rm ../escape.txt", "write_target_outside_scope"),
    ("rm docs/notes.md", "write_target_not_in_allow_list"),
    ("rm $TARGET", "unverifiable_write_target"),
    ("rm *.py", "unverifiable_write_target"),
    ("touch /tmp/x", "write_target_outside_scope"),
    ("echo hi > /tmp/out.txt", "write_target_outside_scope"),
    ("echo hi > ../out.txt", "write_target_outside_scope"),
    ("git commit -m x", "implicit_write_target"),
    ("git add src/x.py", "implicit_write_target"),
    ("xargs rm", "implicit_write_target"),
    ("find . -exec rm {} ;", "unverifiable_write_target"),
    ("sudo rm /etc/x", "write_target_outside_scope"),
    ("sh -c 'rm /etc/x'", "write_target_outside_scope"),
    ("cd /tmp && touch x", "unverifiable_write_target"),
    ("mktemp", "implicit_write_target"),
]


@pytest.mark.parametrize("command,expected_reason", BLOCKED_CASES)
def test_blocked_write_commands_are_rejected(command: str, expected_reason: str) -> None:
    decision = _check(command)
    assert decision.allowed is False, command
    assert decision.reason == expected_reason, (command, decision.reason, decision.detail)


ALLOWED_CASES = [
    "ls -la",
    "cat src/x.py",
    "git status",
    "git log --oneline -3",
    "pytest -q",
    "rm src/x.py",
    "echo hi > src/out.txt",
]


@pytest.mark.parametrize("command", ALLOWED_CASES)
def test_read_only_and_in_scope_writes_are_allowed(command: str) -> None:
    decision = _check(command)
    assert decision.allowed is True, (command, decision.reason, decision.detail)


def test_undeclared_scope_allows_everything() -> None:
    """未受限会话零行为变化：父会话的命令不受本闸影响。"""
    assert check_command_scope("rm /etc/passwd", scope=None, workspace_root=WS).allowed
    undeclared = check_command_scope(
        "rm /etc/passwd", scope=_scope(declared=False), workspace_root=WS
    )
    assert undeclared.allowed is True


def test_explicit_readonly_scope_blocks_every_write() -> None:
    decision = _check("rm src/x.py", scope=_scope(paths=()))
    assert decision.allowed is False
    assert decision.reason == "write_target_not_in_allow_list"


def test_deny_mode_blocks_denied_path() -> None:
    decision = _check("rm src/secret/a.txt", scope=_scope(paths=("src/secret/**",), mode="deny"))
    assert decision.allowed is False
    assert decision.reason == "write_target_denied_by_deny_list"


def test_interpreter_payload_is_documented_residual() -> None:
    """解释器任意代码是 P1-a 的已知残余——显式断言，不假装已拦。

    P1-b（剔除整个命令工具）能挡住这一条；P1-a 选了灵活性，故残余必须被写进
    文档并被测试钉住，而不是靠"闸应该能挡住"的误解。
    """
    decision = _check("python -c \"open('/etc/x','w')\"")
    assert decision.allowed is True


def test_read_side_out_of_scope_literal_is_audited_not_blocked() -> None:
    decision = _check("cat /etc/passwd")
    assert decision.allowed is True
    assert any("/etc/passwd" in item for item in decision.unverified)


def test_explicit_relative_out_of_scope_is_audited() -> None:
    decision = _check("cat ../../etc/passwd")
    assert decision.allowed is True
    assert any("../../etc/passwd" in item for item in decision.unverified)


def test_unparsable_command_is_rejected_fail_closed() -> None:
    decision = _check("echo 'unclosed")
    assert decision.allowed is False
    assert decision.reason == "unparsable_command"


# ── 强制层：受限 child 的越权写命令被程序级拒绝，且没有真的执行 ────────────


def test_restricted_child_out_of_scope_write_is_rejected_and_not_executed(tmp_path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("x", encoding="utf-8")
    tool = _tool()
    scope = WriteScope(paths=("src/**",), mode="allow", declared=True)
    token = current_write_scope.set(scope)
    try:
        result = tool.execute(command=f"rm {victim}")
    finally:
        current_write_scope.reset(token)
    assert result.error_type == "write_scope_violation", result.content
    assert victim.exists(), "被拒的命令不得真的执行"


def test_restricted_child_read_only_command_is_not_blocked() -> None:
    tool = _tool()
    scope = WriteScope(paths=("src/**",), mode="allow", declared=True)
    token = current_write_scope.set(scope)
    try:
        result = tool.execute(command="echo hello-p1a")
    finally:
        current_write_scope.reset(token)
    assert result.error_type != "write_scope_violation"
    assert "hello-p1a" in (result.content or "")


def test_unrestricted_session_command_behavior_unchanged() -> None:
    tool = _tool()
    result = tool.execute(command="echo hello-unrestricted")
    assert result.error_type != "write_scope_violation"
    assert "hello-unrestricted" in (result.content or "")


def test_self_falsification_disabled_gate_actually_executes_write(tmp_path, monkeypatch) -> None:
    """门禁自证伪：闸被关掉后命令应**真的执行**。

    否则"应拦输入"用例测的是空转——这正是 DESIGN §15.6 记录的门禁自欺形态。
    """
    import llm_loop.tools.builtin.execute_command as ec_mod

    victim = tmp_path / "victim.txt"
    victim.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        ec_mod, "check_command_scope", lambda *a, **k: CommandScopeDecision(True)
    )
    tool = _tool()
    scope = WriteScope(paths=("src/**",), mode="allow", declared=True)
    token = current_write_scope.set(scope)
    try:
        tool.execute(command=f"rm {victim}")
    finally:
        current_write_scope.reset(token)
    assert not victim.exists(), "闸关掉后写命令应真的发生（否则应拦用例测的是空转）"


# ── 审计层：未验证路径进 scope_unverified ──────────────────────────────────


def test_scope_unverified_is_recorded_in_audit_snapshot() -> None:
    write_scope_audit_reset()
    tool = _tool()
    scope = WriteScope(paths=("src/**",), mode="allow", declared=True)
    token = current_write_scope.set(scope)
    try:
        tool.execute(command="cat /etc/passwd")
    finally:
        current_write_scope.reset(token)
    snapshot = write_scope_audit_snapshot()
    assert snapshot["scope_unverified_count"] >= 1
    assert any("/etc/passwd" in item["path"] for item in snapshot["scope_unverified"])
    write_scope_audit_reset()

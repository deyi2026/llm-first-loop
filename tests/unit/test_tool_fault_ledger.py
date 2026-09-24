"""B 最小闭环（工具故障可追溯）单测.

覆盖四件：status.record_tool_fault 落盘 / registry post_result observer
（失败与成功均通知、观察者异常 fail-open）/ execute_command python 解释器
指纹（词级匹配覆盖 `cd X && python3 …` 形态）/ job_output 终态零输出提示。
"""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.introspection.status import ArchitectureStatusProvider
from llm_loop.tools.builtin.execute_command import (
    ExecuteCommandTool,
    _python_interpreter_fact,
)
from llm_loop.tools.builtin.job_output import JobOutputTool
from llm_loop.tools.registry import ToolRegistry


def test_record_tool_fault_writes_ledger(tmp_path: Path):
    """非异常形态的工具故障 → exception_log.jsonl 落盘 + 内存列表（与 record_exception 同构）."""
    provider = ArchitectureStatusProvider(audit_dir=tmp_path, enabled=True)
    provider.record_tool_fault("execute_command", "timeout", "exit=none dur=60000ms cmd=sleep 99")
    provider.record_tool_fault("job_output", "failure", "[任务不存在或无权访问] job_id=x")
    ledger = tmp_path / "exception_log.jsonl"
    assert ledger.exists(), "台账文件应已写入"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["phase"] == "tool.execute_command"
    assert rows[0]["error_type"] == "tool_timeout"
    assert "sleep 99" in rows[0]["error_message"]
    assert rows[1]["phase"] == "tool.job_output"
    assert rows[1]["error_type"] == "tool_failure"


def test_record_tool_fault_failopen(tmp_path: Path, monkeypatch):
    """台账自身异常绝不外抛（工具主流程不受影响）."""
    provider = ArchitectureStatusProvider(audit_dir=tmp_path, enabled=True)
    monkeypatch.setattr(
        provider, "_write_audit", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("disk gone"))
    )
    provider.record_tool_fault("t", "failure", "x")  # 不应抛
    assert provider._exception_log[-1].error_type == "tool_failure"


def test_registry_notifies_observers_on_failure_and_success():
    """execute 收口点通知观察者：失败/成功均通知（过滤语义归观察者）；异常观察者 fail-open."""
    registry = ToolRegistry(tool_timeout_s=10.0)
    registry.register(ExecuteCommandTool(timeout_s=5.0))
    seen: list[tuple[str, str]] = []
    registry.add_post_result_observer(lambda name, result: seen.append((name, str(result.status))))
    boom_calls: list[str] = []

    def _boom(_name, _result):
        boom_calls.append(_name)
        raise RuntimeError("observer bug")

    registry.add_post_result_observer(_boom)

    r_fail = registry.execute(
        ToolCall(id="c1", name="execute_command", arguments={"command": "exit 3"})
    )
    assert r_fail.status == ToolResultStatus.FAILURE
    assert seen[-1] == ("execute_command", "failure")
    assert boom_calls, "异常观察者也应被调用过（fail-open 而非跳过）"

    r_ok = registry.execute(
        ToolCall(id="c2", name="execute_command", arguments={"command": "echo ok-fault-ledger"})
    )
    assert r_ok.status == ToolResultStatus.SUCCESS
    assert seen[-1] == ("execute_command", "success")


def test_execute_command_attaches_python_fingerprint(tmp_path: Path):
    """词级含 python3 的命令回执附 [py] 指纹行（覆盖 `cd X && python3 …` 非裸形态）."""
    tool = ExecuteCommandTool(timeout_s=10.0)
    result = tool.execute(
        command=f"cd {tmp_path} && python3 -c 'raise SystemExit(3)'", workdir=str(tmp_path)
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "[py] python3=" in result.content, "非裸 python3 故障命令应附解释器指纹"
    # 纯成功（退出码 0、无 runtime_fact）不附——保住"成功回执=纯 stdout"契约
    result_ok = tool.execute(
        command=f"cd {tmp_path} && python3 -c 'print(1)'", workdir=str(tmp_path)
    )
    assert result_ok.status == ToolResultStatus.SUCCESS
    assert "[py]" not in result_ok.content

    # 非命令词形态（如文件名里含 python3）不误报词级匹配
    assert _python_interpreter_fact("cat notes-python3.txt", {"PATH": "/usr/bin"}) == ""
    assert _python_interpreter_fact(
        "cd /x && python3 -m pytest", {"PATH": "/usr/bin"}
    ).startswith("[py] python3=")


def test_job_output_terminal_zero_output_hint(monkeypatch):
    """终态 + 0 行输出 → 回执附 [空输出提示]（管道 tail/swallow 形态如实标注）."""
    fake_snapshot = {
        "state": "completed",
        "exit_code": 0,
        "output": [],
        "command": "pytest | tail -3",
        "local_handle": True,
        "durable": True,
    }

    class _FakeRegistry:
        def snapshot(self, job_id, session_id=None):
            return fake_snapshot if job_id == "j-zero" else None

    monkeypatch.setattr(
        "llm_loop.tools.builtin.job_output.JobRegistry.instance",
        classmethod(lambda cls: _FakeRegistry()),
    )
    result = JobOutputTool().execute(job_id="j-zero")
    assert result.status == ToolResultStatus.SUCCESS
    assert "[空输出提示]" in result.content
    # 非终态（running）零输出不附提示
    fake_snapshot["state"] = "running"
    fake_snapshot["output"] = []
    result2 = JobOutputTool().execute(job_id="j-zero")
    assert "[空输出提示]" not in result2.content


# ── A-①（EVO-20260924-40755734）: 前置拦截同样入故障台账 ──


def test_preblock_unknown_tool_and_bad_args_enter_ledger():
    """执行前拒绝（工具不存在 / 参数非 dict）不再绕过观察者."""
    registry = ToolRegistry(tool_timeout_s=10.0)
    registry.register(ExecuteCommandTool(timeout_s=5.0))
    seen: list[tuple[str, str]] = []
    registry.add_post_result_observer(lambda name, result: seen.append((name, str(result.status))))
    r1 = registry.execute(ToolCall(id="c1", name="no_such_tool", arguments={}))
    assert r1.status == ToolResultStatus.FAILURE
    assert "[工具不存在]" in r1.content
    r2 = registry.execute(ToolCall(id="c2", name="execute_command", arguments=["not", "dict"]))
    assert r2.status == ToolResultStatus.FAILURE
    assert "[参数错误]" in r2.content
    assert seen.count(("no_such_tool", "failure")) == 1
    assert seen.count(("execute_command", "failure")) == 1


def test_preblock_missing_tool_call_id_enters_ledger():
    """tool_call_id 兜底拒绝也入账（_preblock 直接路径）."""
    registry = ToolRegistry(tool_timeout_s=10.0)
    seen: list[str] = []
    registry.add_post_result_observer(lambda name, result: seen.append(name))
    registry.execute(ToolCall(id="", name="execute_command", arguments={}))
    assert seen == ["execute_command"]


def test_preblock_safety_hard_block_enters_ledger(tmp_path: Path):
    """灾难性安全硬阻断（BLOCKED）同样入账——真实安全层 + 前置拦截全链路."""
    registry = ToolRegistry(tool_timeout_s=10.0)
    registry.register(ExecuteCommandTool(timeout_s=5.0))
    provider = ArchitectureStatusProvider(audit_dir=tmp_path, enabled=True)

    def _fault_observer(tool_name: str, result) -> None:
        st = getattr(result, "status", None)
        if st == ToolResultStatus.SUCCESS:
            return
        provider.record_tool_fault(
            tool_name, str(getattr(st, "value", st)), str(getattr(result, "content", "") or "")[:200]
        )

    registry.add_post_result_observer(_fault_observer)
    blocked_seen: list[str] = []
    registry.add_post_result_observer(
        lambda name, result: blocked_seen.append(str(result.status))
    )
    r = registry.execute(
        ToolCall(id="c1", name="execute_command", arguments={"command": "rm -rf /"})
    )
    assert r.status == ToolResultStatus.BLOCKED
    assert "[安全硬阻断]" in r.content
    assert "blocked" in blocked_seen
    ledger = tmp_path / "exception_log.jsonl"
    assert ledger.exists(), "安全硬阻断应已写入 exception_log"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["phase"] == "tool.execute_command"
    assert rows[-1]["error_type"] == "tool_blocked"


# ── A-④（EVO-20260924-40755734）: 同形态故障 ≥N 次自动提醒 ──


def test_tool_fault_repeat_alert_at_threshold(tmp_path: Path):
    """同签名第 3 次记 tool_fault_repeat 台账；之后不再重复提醒."""
    provider = ArchitectureStatusProvider(audit_dir=tmp_path, enabled=True)
    for _ in range(3):
        provider.record_tool_fault("tool.web_fetch", "failure", "403 blocked")
    ledger = tmp_path / "exception_log.jsonl"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    repeats = [r for r in rows if r["error_type"] == "tool_fault_repeat"]
    assert len(repeats) == 1
    assert "同形态故障达 3 次" in repeats[0]["error_message"]
    # 第 4、5 次不再追加 repeat 记录（每签名一次）
    provider.record_tool_fault("tool.web_fetch", "failure", "403 blocked")
    provider.record_tool_fault("tool.web_fetch", "failure", "403 blocked")
    rows2 = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len([r for r in rows2 if r["error_type"] == "tool_fault_repeat"]) == 1
    # 不同签名独立计数（未达阈值无 repeat）
    provider.record_tool_fault("tool.read_file", "failure", "miss")
    rows3 = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert all(r["phase"] != "tool.read_file" or r["error_type"] != "tool_fault_repeat" for r in rows3)

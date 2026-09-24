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

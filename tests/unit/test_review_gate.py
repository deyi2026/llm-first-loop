"""EVO-20261014-7ba73d88: push/publish/全量测试 review gate 闸提示。

锁定：触发面分类确定性、回执注入一行（satisfied/exempted/none 自声明位）、
review_gate_probe 事件落盘（模型声明 vs 机器事实并排）、只提醒不阻断、
探测器 fail-open。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from llm_loop.tools.review_gate import (
    classify_review_gate_command,
    make_review_gate_probe,
    review_gate_note,
)


def test_gate_triggers_on_git_push_variants() -> None:
    assert classify_review_gate_command("git push") == "git_push"
    assert classify_review_gate_command("git push origin main") == "git_push"
    assert (
        classify_review_gate_command("git push --force-with-lease origin t")
        == "git_push"
    )
    assert classify_review_gate_command("/usr/bin/git push origin main") == "git_push"
    assert classify_review_gate_command("git -C repo push origin main") == "git_push"
    assert classify_review_gate_command("cd repo && git push origin main") == "git_push"


def test_gate_triggers_on_full_pytest_only() -> None:
    assert classify_review_gate_command("pytest") == "full_test"
    assert classify_review_gate_command("python -m pytest -q") == "full_test"
    assert classify_review_gate_command(".venv/bin/python -m pytest") == "full_test"
    # 收窄后不触发（子集不算全量闸面）。
    assert classify_review_gate_command("pytest tests/unit/test_a.py") is None
    assert classify_review_gate_command("pytest -k fence") is None
    assert classify_review_gate_command("pytest src/x.py::test_y") is None
    assert classify_review_gate_command("pytest -m slow") is None


def test_gate_non_triggers() -> None:
    assert classify_review_gate_command("git status") is None
    assert classify_review_gate_command("grep push file.txt") is None
    assert classify_review_gate_command("ls") is None
    assert classify_review_gate_command("") is None
    # 误报形态（独立审查 subagent_859ec7d661bf C 项）：非命令位置出现关键词。
    assert classify_review_gate_command("echo git push") is None
    assert classify_review_gate_command("grep pytest README.md") is None
    assert classify_review_gate_command("git log --grep push") is None
    assert classify_review_gate_command("cat pytest.txt") is None


def test_review_gate_note_one_line_with_declaration_slots() -> None:
    note = review_gate_note(
        "git_push", "last_verdict=PASS（本会话已落盘 VERDICT 回执）", action_label="git push"
    )
    assert note.count("\n") == 0
    assert note.startswith("[RULE-AI-28 闸]")
    assert "satisfied / exempted:<类型> / none" in note
    assert "last_verdict=PASS" in note
    assert "只提醒不阻断" in note


@dataclass
class _FakeEvent:
    type: str = "message.appended"
    payload: dict = field(default_factory=dict)


class _FakeStore:
    def __init__(self, events, enabled=True):
        self.events = events
        self.enabled = enabled
        self.appended = []

    def read(self, sid):
        return list(self.events)

    def append(self, sid, event_type, payload):
        self.appended.append((sid, event_type, payload))


def test_probe_finds_last_verdict_receipt_and_writes_event() -> None:
    events = [
        _FakeEvent(payload={"role": "user", "content": "go"}),
        _FakeEvent(payload={"role": "tool", "content": "... VERDICT: PASS\n理由若干"}),
        _FakeEvent(payload={"role": "assistant", "content": "VERDICT: FAIL"}),
    ]
    store = _FakeStore(events)
    audit_calls = []

    def audit(action_type: str, detail_text: str, sid: str) -> None:
        audit_calls.append((action_type, detail_text, sid))

    recorder = make_review_gate_probe(store, lambda: "sess-1", audit)
    fact = recorder({"action_kind": "git_push", "tool": "execute_command"})
    assert fact.startswith("last_verdict=PASS")
    # review_gate_probe 事件：模型声明位 + 机器事实并排。
    assert len(store.appended) == 1
    sid, etype, payload = store.appended[0]
    assert sid == "sess-1" and etype == "review_gate_probe"
    assert payload["action_kind"] == "git_push"
    assert payload["machine_fact"] == fact
    assert "model_declaration" in payload
    # 同步落 action_trace 审计流（event_stream 统一视图可检索）。
    assert len(audit_calls) == 1
    at, dt, asid = audit_calls[0]
    assert at == "review_gate_probe" and asid == "sess-1"
    assert "git_push" in dt and "machine_fact" in dt


def test_probe_reports_none_found_when_no_verdict() -> None:
    store = _FakeStore([_FakeEvent(payload={"role": "tool", "content": "ok"})])
    recorder = make_review_gate_probe(store, lambda: "sess-1")
    fact = recorder({"action_kind": "full_test", "tool": "execute_command"})
    assert fact.startswith("none_found")
    assert store.appended and store.appended[0][1] == "review_gate_probe"


def test_probe_fail_open_on_errors() -> None:
    class _Boom:
        enabled = True

        def read(self, sid):
            raise RuntimeError("disk gone")

        def append(self, *a, **k):
            raise RuntimeError("append gone")

    recorder = make_review_gate_probe(_Boom(), lambda: "sess-1")
    fact = recorder({"action_kind": "git_push", "tool": "execute_command"})
    assert fact.startswith("unknown")
    # 未注入 event_store / 空 sid：同样 fail-open。
    recorder2 = make_review_gate_probe(None, lambda: "")
    assert recorder2({"action_kind": "git_push"}).startswith("unknown")


def test_execute_command_gate_line_injected(tmp_path: Path) -> None:
    """execute_command 回执注入闸提示行（无 recorder 时机器事实为 unknown）。"""
    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool

    tool = ExecuteCommandTool(timeout_s=10, review_gate_recorder=None)
    line = tool._review_gate_line("git push origin main")
    assert line.startswith("[RULE-AI-28 闸]")
    assert "git push" in line and "unknown（未注入探测器）" in line
    # 非触发面返回空串（不注入）。
    assert tool._review_gate_line("git status") == ""


def test_execute_command_full_test_receipt_carries_gate(tmp_path: Path) -> None:
    """全量 pytest 命令的成功回执必须携带闸提示行（只提醒，不改变退出语义）。"""
    from llm_loop.core.message import ToolResultStatus
    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool

    tool = ExecuteCommandTool(timeout_s=30)
    # 用 echo 模拟 pytest 不行——分类按命令文本。直接跑真 pytest --version？
    # 该命令含 pytest 且无收窄 → full_test 触发；--version 只打印版本，退出 0。
    result = tool.execute(command="pytest --version", workdir=str(tmp_path))
    assert result.status == ToolResultStatus.SUCCESS
    assert "[RULE-AI-28 闸]" in result.content
    assert "全量 pytest" in result.content


def test_service_control_publish_gate_line() -> None:
    from llm_loop.tools.builtin.service_control import ServiceControlTool

    tool = ServiceControlTool.__new__(ServiceControlTool)
    tool._review_gate_recorder = None
    line = tool._review_gate_line()
    assert line.startswith("[RULE-AI-28 闸]")
    assert "service_control publish" in line
    assert "unknown（未注入探测器）" in line

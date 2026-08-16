"""路径 I 修复循环测试（tasks.md §7.1 验收）."""

from __future__ import annotations

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.task_quality.fix_loop import FixLoopTool


class _FakeRegistry:
    """registry 桩: 按轮次返回预设检查结果."""

    def __init__(self, results_by_round: dict[int, str]):
        self._results = results_by_round
        self.calls = []
        self._round = 0

    def execute(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        self._round += 1
        content = self._results.get(self._round, "5 passed")
        status = ToolResultStatus.SUCCESS if "passed" in content else ToolResultStatus.FAILURE
        return ToolResult(status=status, content=content, tool_call_id=call.id, tool_name="execute_command")


class _FakeSubAgent:
    """子代理桩: 记录任务，返回预设回答."""

    def __init__(self, answer="已修复"):
        self._answer = answer
        self.tasks = []

    def run(self, task, context="", depth=0, max_rounds=None):
        self.tasks.append(task)
        from types import SimpleNamespace
        return SimpleNamespace(final_answer=self._answer, refused=False)


class _FakeStore:
    def __init__(self):
        self.events = []

    def append(self, sid, etype, payload):
        self.events.append((etype, payload))
        return None


def _tool(registry, sub=None, **kw):
    return FixLoopTool(registry=registry, subagent_runner=sub, **kw)


def test_pass_first_round():
    """检查通过: 1 轮 SUCCESS + 循环通过标注."""
    reg = _FakeRegistry({1: "5 passed"})
    t = _tool(reg)
    r = t.execute(check_command="pytest tests/")
    assert r.status.value == "success"
    assert "循环通过" in r.content
    assert "1 轮" in r.content
    assert len(reg.calls) == 1


def test_fail_then_pass_two_rounds():
    """检查失败 1 轮后通过: 2 轮成功（子代理修复介入）."""
    reg = _FakeRegistry({1: "1 failed", 2: "5 passed"})
    sub = _FakeSubAgent()
    t = _tool(reg, sub)
    r = t.execute(check_command="pytest tests/")
    assert r.status.value == "success"
    assert "2 轮" in r.content
    assert len(sub.tasks) == 1  # 子代理修复 1 次


def test_fuse_after_same_error_3_times():
    """连续 3 次同一错误: 熔断 + FAILURE 含熔断原因."""
    reg = _FakeRegistry({i: "1 failed\nFAILED tests/test_x.py::test_a - AssertionError" for i in range(1, 4)})
    sub = _FakeSubAgent("修复尝试")
    t = _tool(reg, sub)
    r = t.execute(check_command="pytest tests/", fuse_count=3)
    assert r.status.value == "failure"
    assert "熔断" in r.content
    assert "连续 3 次" in r.content


def test_limit_reached_unfixed():
    """达上限未修复: FAILURE 含未修复项清单."""
    reg = _FakeRegistry({i: "1 failed" for i in range(1, 3)})  # max_rounds=2
    sub = _FakeSubAgent()
    t = _tool(reg, sub, default_max_rounds=2)
    r = t.execute(check_command="pytest tests/")
    assert r.status.value == "failure"
    assert "达上限" in r.content
    assert "未修复项" in r.content
    assert len(sub.tasks) == 2  # 每轮都尝试修复


def test_orchestration_error_honest():
    """编排异常: ERROR 不抛穿主循环."""

    class _Boom:
        def execute(self, call):
            raise RuntimeError("boom")

    t = _tool(_Boom())
    r = t.execute(check_command="pytest tests/")
    assert r.status.value == "error"
    assert "修复循环异常" in r.content


def test_tools_go_through_registry():
    """循环内工具调用经 ToolRegistry（调用记录含 execute_command）."""
    reg = _FakeRegistry({1: "1 failed", 2: "5 passed"})
    t = _tool(reg, _FakeSubAgent())
    t.execute(check_command="pytest tests/")
    assert all(c.name == "execute_command" for c in reg.calls)
    assert len(reg.calls) == 2


def test_no_auto_code_change():
    """程序不自动改代码: 工具只编排，修复动作在子代理任务文本中."""
    reg = _FakeRegistry({1: "1 failed", 2: "5 passed"})
    sub = _FakeSubAgent()
    t = _tool(reg, sub)
    r = t.execute(check_command="pytest tests/", fix_hint="修复断言")
    assert r.status.value == "success"
    # 子代理收到修复任务（edit_file 由子代理 LLM 调，非 FixLoopTool 直接改码）
    assert any("修复" in task for task in sub.tasks)
    # FixLoopTool 本身未调用 edit_file
    assert all(c.name == "execute_command" for c in reg.calls)


def test_events_round_and_terminated():
    """每轮事件落盘: round + terminated 可回放."""
    store = _FakeStore()
    reg = _FakeRegistry({1: "1 failed", 2: "5 passed"})
    t = _tool(reg, _FakeSubAgent(), event_store=store, session_id="s1")
    t.execute(check_command="pytest tests/")
    types = [e[0] for e in store.events]
    assert "task.fix_loop.round" in types
    assert "task.fix_loop.terminated" in types
    term = next(e for e in store.events if e[0] == "task.fix_loop.terminated")
    assert term[1]["final_status"] == "passed"
    assert term[1]["trace_id"]


def test_trace_id_consistent():
    """trace_id 贯穿事件."""
    store = _FakeStore()
    reg = _FakeRegistry({1: "1 failed", 2: "5 passed"})
    t = _tool(reg, _FakeSubAgent(), event_store=store)
    r = t.execute(check_command="pytest tests/")
    # 从回执提取 trace
    assert "trace=" in r.content
    # 所有事件 trace_id 一致
    traces = {e[1].get("trace_id") for e in store.events}
    assert len(traces) == 1


def test_fix_loop_disabled_via_enabled_fn():
    """D3 动态开关: enabled_fn=False → 回执未启用."""
    reg = _FakeRegistry({1: "5 passed"})
    t = _tool(reg, _FakeSubAgent(), enabled_fn=lambda: False)
    r = t.execute(check_command="pytest tests/")
    assert r.status.value == "failure"
    assert "未启用" in r.content
    assert len(reg.calls) == 0  # 未执行任何检查


def test_fix_loop_enabled_via_enabled_fn():
    """D3 动态开关: enabled_fn=True → 正常执行."""
    reg = _FakeRegistry({1: "5 passed"})
    t = _tool(reg, _FakeSubAgent(), enabled_fn=lambda: True)
    r = t.execute(check_command="pytest tests/")
    assert r.status.value == "success"

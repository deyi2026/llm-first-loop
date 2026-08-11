"""工具并发控制测试（EVO-20260810-750e985a）.

只读并行 / 修改串行 / 结果按声明顺序回写。直接装配 ToolRegistry + 假工具，
零真实 LLM、零真实网络；sleep 计时验证并发与串行。
"""

import time
from threading import Lock

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.tools.registry import ToolRegistry


class _FakeTool:
    """假工具：execute 返回字符串（registry 包装为 success）或抛异常."""

    def __init__(self, name: str, fn=None):
        self.name = name
        self.description = f"{name} 假工具"
        self.parameters = {"type": "object", "properties": {}}
        self._fn = fn

    def execute(self, **kwargs):
        if self._fn is not None:
            return self._fn(**kwargs)
        return f"{self.name}:ok"


def _reg():
    reg = ToolRegistry()
    reg.register(_FakeTool("read_file", fn=lambda **k: (_lock_enter("r") or "read:ok")))
    return reg


# 用事件/计时验证并发
_lock = Lock()
_active = 0
_max_active = 0


def _tracked_sleep(name: str, seconds: float):
    global _active, _max_active
    with _lock:
        _active += 1
        _max_active = max(_max_active, _active)
    try:
        time.sleep(seconds)
        return f"{name}:ok"
    finally:
        with _lock:
            _active -= 1


def _tool(name: str, fn) -> _FakeTool:
    return _FakeTool(name, fn=fn)


def _reset_counters():
    global _active, _max_active
    _active = 0
    _max_active = 0


def test_execute_many_order_preserved():
    """结果严格按声明顺序回写（混合只读+修改，与完成先后无关）."""
    reg = ToolRegistry()
    reg.register(_FakeTool("read_file"))
    reg.register(_FakeTool("web_fetch"))
    reg.register(_FakeTool("execute_command"))

    calls = [
        ToolCall(id="c1", name="execute_command", arguments={"command": "echo 1"}),
        ToolCall(id="c2", name="read_file", arguments={"path": "a.txt"}),
        ToolCall(id="c3", name="web_fetch", arguments={"url": "http://x"}),
    ]
    results = reg.execute_many(calls)
    # 顺序 = 声明顺序（c1/c2/c3），而非完成顺序
    assert [r.tool_call_id for r in results] == ["c1", "c2", "c3"]
    assert results[0].status == ToolResultStatus.SUCCESS
    assert results[1].status == ToolResultStatus.SUCCESS


def test_execute_many_readonly_parallel():
    """只读工具并行：两个 0.25s 只读工具总耗时 < 0.45s（并行，非串行 0.5s）."""
    _reset_counters()
    reg = ToolRegistry()
    reg.register(_tool("read_file", fn=lambda **k: _tracked_sleep("read", 0.25)))
    reg.register(_tool("web_fetch", fn=lambda **k: _tracked_sleep("fetch", 0.25)))
    calls = [
        ToolCall(id="r1", name="read_file", arguments={}),
        ToolCall(id="r2", name="web_fetch", arguments={}),
    ]
    start = time.perf_counter()
    reg.execute_many(calls)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.45, f"只读应并行（实测 {elapsed:.3f}s）"
    assert _max_active >= 2, f"应观察到并发（max_active={_max_active}）"


def test_execute_many_mutating_serial():
    """修改类串行：两个 0.25s 修改类工具总耗时 >= 0.45s（串行 0.5s）."""
    _reset_counters()
    reg = ToolRegistry()
    reg.register(_tool("execute_command", fn=lambda **k: _tracked_sleep("cmd1", 0.25)))
    reg.register(_tool("write_file", fn=lambda **k: _tracked_sleep("write", 0.25)))
    calls = [
        ToolCall(id="m1", name="execute_command", arguments={"command": "echo"}),  # 修改类（非只读集合）
        ToolCall(id="m2", name="write_file", arguments={}),
    ]
    start = time.perf_counter()
    reg.execute_many(calls)
    elapsed = time.perf_counter() - start
    assert elapsed >= 0.45, f"修改类应串行（实测 {elapsed:.3f}s）"
    assert _max_active <= 1, f"修改类不应并发（max_active={_max_active}）"


def test_execute_many_missing_id_filled():
    """结果 tool_call_id 兜底为声明 id（约束 C1 绑定）."""
    reg = ToolRegistry()
    reg.register(_FakeTool("read_file"))
    calls = [ToolCall(id="c_x", name="read_file", arguments={})]
    results = reg.execute_many(calls)
    assert results[0].tool_call_id == "c_x"

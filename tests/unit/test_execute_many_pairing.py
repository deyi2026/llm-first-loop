"""execute_many 配对健壮性测试（防 KeyError 传导, 2026-08-14 修复）.

背景: 飞书桥进程报 KeyError: 'call_00_...'（execute_many 内 by_id[c.id] 索引未命中）,
根因: 工具返回的 ToolResult.tool_call_id 与声明 id 不一致 → 写入键错位 → 读取 KeyError.
修复: ① EditFileTool 补 execute 方法（框架约定）; ② _run_with_timeout 强制绑定声明 id;
      ③ execute_many 缺键构造 [程序异常] 占位（兜底不崩）.
"""

from __future__ import annotations

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.tools.builtin.edit_file import EditFileTool
from llm_loop.tools.registry import ToolRegistry


def _mk_call(cid: str, name: str = "read_file") -> ToolCall:
    return ToolCall(id=cid, name=name, arguments={})


def test_edit_file_execute_delegate(tmp_path):
    """EditFileTool 必须提供框架约定 execute(**kwargs) 入口（修复缺 execute 方法）."""
    f = tmp_path / "a.txt"
    f.write_text("hello\n", encoding="utf-8")
    r = EditFileTool().execute(path=str(f), old_string="hello", new_string="hi")
    assert r.status.value == "success"
    assert f.read_text(encoding="utf-8") == "hi\n"


def test_execute_many_missing_key_returns_placeholder(monkeypatch):
    """execute_many 对键错位/缺失的结果返回 [程序异常] 占位而非抛 KeyError."""
    reg = ToolRegistry()
    calls = [_mk_call("call_A"), _mk_call("call_B")]

    def broken_execute(self, call: ToolCall) -> ToolResult:
        # 模拟执行路径丢失: call_B 的结果带错位 tool_call_id（写键错位）
        if call.id == "call_B":
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="ok",
                tool_call_id="call_WRONG",
                tool_name=call.name,
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="ok",
            tool_call_id=call.id,
            tool_name=call.name,
        )

    monkeypatch.setattr(ToolRegistry, "execute", broken_execute)
    results = reg.execute_many(calls)
    # 声明顺序保持（约束 C4）
    assert [r.tool_call_id for r in results] == ["call_A", "call_B"]
    assert results[0].status.value == "success"
    # call_B 缺键 → 占位 error（不抛 KeyError、不伪造成功）
    assert results[1].status.value == "error"
    assert "[程序异常] 工具执行结果丢失" in results[1].content


def test_execute_many_normal_order_preserved(tmp_path, build_test_engine):
    """回归: 正常场景结果严格按声明顺序回写（真实注册工具、真实文件）."""
    f = tmp_path / "a.txt"
    f.write_text("hello\n", encoding="utf-8")
    engine, _ = build_test_engine([])
    reg = engine.registry
    calls = [
        ToolCall(id="c1", name="read_file", arguments={"path": str(f)}),
        ToolCall(id="c2", name="read_file", arguments={"path": str(f)}),
        ToolCall(id="c3", name="read_file", arguments={"path": str(f)}),
    ]
    results = reg.execute_many(calls)
    assert [r.tool_call_id for r in results] == ["c1", "c2", "c3"]
    assert all(r.status.value == "success" for r in results)

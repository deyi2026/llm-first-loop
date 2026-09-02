"""EVO-20260902-loopbreaker 集成回归: 真实 registry 路径下第 3 次同指纹调用执行前拦截."""

from __future__ import annotations

from llm_loop.core.message import ToolCall


def _tc(i: int) -> ToolCall:
    return ToolCall(id=f"c{i}", name="read_file", arguments={"path": "/tmp/loopbreaker-probe.txt"})


def test_execute_tools_pre_blocks_third_identical_call(build_test_engine):
    engine, _fake = build_test_engine(
        [
            {"content": "", "tool_calls": [_tc(1)]},
            {"content": "", "tool_calls": [_tc(2)]},
            {"content": "", "tool_calls": [_tc(3)]},  # 第 3 次同指纹 → 执行前拦截，不触 registry
            {"content": "done", "tool_calls": []},
        ]
    )
    sid = engine.session.create()
    engine.run(sid, "连续三次读同一文件")

    msgs = engine.session.load(sid).messages
    by_id = {m.tool_call_id: m for m in msgs if m.role == "tool" and m.tool_call_id}
    assert set(by_id) == {"c1", "c2", "c3"}, "声明与回执成对（对账不变量）"
    assert "已拦截" in by_id["c3"].content and "blocked" in by_id["c3"].content
    assert "未执行" in by_id["c3"].content, "拦截回执须如实标注未执行"
    assert "blocked" not in by_id["c1"].content and "blocked" not in by_id["c2"].content


def test_blocked_receipt_does_not_break_pairing(build_test_engine):
    """拦截回执同样计入对账: 声明数 = 放行结果数 + 拦截回执数（无孤儿）."""
    engine, _fake = build_test_engine(
        [
            {"content": "", "tool_calls": [_tc(1)]},
            {"content": "", "tool_calls": [_tc(2)]},
            {"content": "", "tool_calls": [_tc(3)]},
            {"content": "done", "tool_calls": []},
        ]
    )
    sid = engine.session.create()
    engine.run(sid, "对账检查")
    msgs = engine.session.load(sid).messages
    declared = {
        tc["id"] for m in msgs if m.role == "assistant" for tc in (m.tool_calls or [])
    }
    answered = {m.tool_call_id for m in msgs if m.role == "tool" and m.tool_call_id}
    assert declared == answered, f"孤儿: {declared - answered}"

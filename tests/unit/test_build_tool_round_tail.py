"""单元测试: 工具轮极小窗口尾部保留（_tool_round_zero_tail, 2026-08-24）.

语义: [最近用户指令 + 最近完整协议配对组]（中间轮次裁剪）——
两项硬约束:
1. C1 协议: 声明↔回执必须同窗（多回执截断 → 孤儿回执 → 400）
2. 聊天模板: llama.cpp Qwen 模板要求载荷含 user 消息（缺 user → 500）
"""

from __future__ import annotations

from llm_loop.core.loop.build import _tool_round_zero_tail
from llm_loop.core.message import Message, MessageSource


def _msg(role: str, content: str = "", tool_calls=None, tool_call_id: str = "") -> Message:
    return Message(
        role=role,
        content=content,
        source=MessageSource.USER,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
    )


def _assistant_with_calls(ids: list[str]) -> Message:
    calls = [
        {"id": cid, "name": "read_file", "arguments": {"path": "/tmp/x"}} for cid in ids
    ]
    return _msg("assistant", "声明工具调用", tool_calls=calls)


def _assert_has_user_and_pairing(tail: list[Message]) -> None:
    """模板硬约束: 载荷必须含 user 消息 + 完整配对组."""
    assert any(m.role == "user" for m in tail), "载荷必须含 user 消息（Qwen 模板 500 防护）"
    assert tail[-1].role == "tool", "末尾必须为 tool 回执"
    assert any(m.role == "assistant" and m.tool_calls for m in tail), "必须含工具声明"


def test_keeps_user_and_full_multi_result_pairing_group():
    """user + 并行 3 工具调用 + 3 回执 → [user, 声明, 全部回执]（不截断配对）."""
    msgs = [
        _msg("user", "旧任务"),
        _msg("user", "当前任务：检查服务"),
        _assistant_with_calls(["a", "b", "c"]),
        _msg("tool", "[结果 a]", tool_call_id="a"),
        _msg("tool", "[结果 b]", tool_call_id="b"),
        _msg("tool", "[结果 c]", tool_call_id="c"),
    ]
    tail = _tool_round_zero_tail(msgs)
    assert len(tail) == 5  # 最近 user + 声明 + 3 回执（旧 user 被裁剪）
    assert tail[0].role == "user" and tail[0].content == "当前任务：检查服务"
    assert tail[1].role == "assistant" and tail[1].tool_calls
    assert [m.tool_call_id for m in tail[2:]] == ["a", "b", "c"]
    _assert_has_user_and_pairing(tail)


def test_keeps_partial_results_group():
    """回执部分到达 → 保留已到达部分（防声明↔回执分离）+ user."""
    msgs = [
        _msg("user", "旧任务"),
        _msg("user", "当前任务"),
        _assistant_with_calls(["a", "b"]),
        _msg("tool", "[结果 a]", tool_call_id="a"),
    ]
    tail = _tool_round_zero_tail(msgs)
    assert len(tail) == 3
    assert tail[0].role == "user"
    assert tail[1].tool_calls is not None
    assert tail[2].tool_call_id == "a"
    _assert_has_user_and_pairing(tail)


def test_keeps_trailing_user_after_results():
    """回执后出现新 user（中断恢复/新 run 续跑）→ 最近 user 在配对组之后时整段保留（按时间序）."""
    msgs = [
        _assistant_with_calls(["a"]),
        _msg("tool", "[结果 a]", tool_call_id="a"),
        _msg("user", "[系统注记] 已恢复，请继续"),
    ]
    tail = _tool_round_zero_tail(msgs)
    assert len(tail) == 3
    assert tail[0].role == "assistant" and tail[0].tool_calls
    assert tail[1].role == "tool"
    assert tail[2].role == "user"  # 注记在尾部（时间序, 不重复前置）


def test_no_tool_calls_keeps_last_user():
    """无工具声明 → 保留最近 user（模板约束优先）."""
    msgs = [_msg("user", "1"), _msg("user", "2"), _msg("user", "3")]
    tail = _tool_round_zero_tail(msgs)
    assert tail == msgs[2:]


def test_no_user_falls_back_pairing_group():
    """异常会话（无 user）→ 配对组兜底（保协议）."""
    msgs = [_assistant_with_calls(["a"]), _msg("tool", "[结果 a]", tool_call_id="a")]
    tail = _tool_round_zero_tail(msgs)
    assert len(tail) == 2
    assert tail[0].tool_calls and tail[1].role == "tool"


def test_single_message_unchanged():
    """单条消息 / 空 → 不越界."""
    msgs = [_msg("user", "1")]
    assert _tool_round_zero_tail(msgs) == msgs
    assert _tool_round_zero_tail([]) == []

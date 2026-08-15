"""P1-10 锚点对齐工具轮边界（2026-08-16 现场：tool_call_id is not found 根因）.

根因：history_anchor 落在声明↔回执组内（声明 idx22，回执 idx26，锚=26）→ 声明被裁、
回执变孤儿 → Kimi/DeepSeek 等 API 拒绝（invalid_request_error: tool_call_id is not found）。
"""

from __future__ import annotations

from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource


def _session_with_tool_round() -> list[Message]:
    """声明(idx22) + 4 回执(idx23-26)，前 22 条普通消息."""
    msgs = [Message(role="user" if i % 2 == 0 else "assistant", content=f"消息{i}", source=MessageSource.USER) for i in range(22)]
    # 声明：2 个 tool_calls（idx22）
    msgs.append(
        Message(
            role="assistant",
            content="",
            source=MessageSource.USER,
            tool_calls=[
                {"id": "tc-a", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
                {"id": "tc-b", "type": "function", "function": {"name": "web_fetch", "arguments": "{}"}},
            ],
        )
    )
    for tid in ("tc-a", "tc-b"):
        msgs.append(Message(role="tool", content=f"回执{tid}", source=MessageSource.USER, tool_call_id=tid))
    return msgs


def test_anchor_inside_tool_round_no_orphan():
    """锚点落在回执处（idx24）→ 裁后窗口不得含无声明孤儿回执."""
    msgs = _session_with_tool_round()
    out = build_history_messages(msgs, "sys", 100000, history_anchor=24)
    declared = {
        str(tc.get("id") or "")
        for m in out
        if m.get("role") == "assistant" and m.get("tool_calls")
        for tc in m["tool_calls"]
    }
    for m in out:
        if m.get("role") == "tool":
            rid = str(m.get("tool_call_id") or "")
            assert rid in declared, f"孤儿回执残留: {rid}"


def test_anchor_before_declaration_keeps_pair():
    """锚点在声明前（idx21）→ 声明与回执均保留（配对完整）."""
    msgs = _session_with_tool_round()
    out = build_history_messages(msgs, "sys", 100000, history_anchor=21)
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in out)
    declared = {
        str(tc.get("id") or "")
        for m in out
        if m.get("role") == "assistant" and m.get("tool_calls")
        for tc in m["tool_calls"]
    }
    assert "tc-a" in declared and "tc-b" in declared

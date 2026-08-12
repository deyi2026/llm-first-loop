"""M66 思考链瘦身（reasoning_tail）测试.

历史中仅保留最近 N 轮 assistant 思考链（reasoning_content）；更早轮次提交时省略
（内容/工具调用完整保留，仅提交视图瘦身）；最近一轮 THK-04 回传不受影响。
"""

from __future__ import annotations

from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource


def _assistant_msgs(n: int = 3) -> list[Message]:
    return [
        Message(
            role="assistant",
            content=f"A{i}",
            reasoning_content=f"R{i}",
            source=MessageSource.SYSTEM,
        )
        for i in range(1, n + 1)
    ]


def _assistant_dicts(out: list[dict]) -> list[dict]:
    return [m for m in out if m.get("role") == "assistant"]


def test_reasoning_tail_keeps_recent_only():
    """reasoning_tail=2: 仅最近 2 轮保留思考链，更早轮省略（内容完整保留）."""
    out = build_history_messages(_assistant_msgs(3), "", max_chars=10**6, reasoning_tail=2)
    dicts = _assistant_dicts(out)
    assert len(dicts) == 3
    assert dicts[0].get("reasoning_content") is None  # 最旧轮省略
    assert dicts[1]["reasoning_content"] == "R2"
    assert dicts[2]["reasoning_content"] == "R3"
    # 内容完整保留（不丢事实）
    assert [m["content"] for m in dicts] == ["A1", "A2", "A3"]


def test_reasoning_tail_zero_keeps_all():
    """reasoning_tail=0: 全部保留（向后兼容）."""
    out = build_history_messages(_assistant_msgs(3), "", max_chars=10**6, reasoning_tail=0)
    dicts = _assistant_dicts(out)
    assert [m.get("reasoning_content") for m in dicts] == ["R1", "R2", "R3"]


def test_reasoning_tail_default_two():
    """默认 reasoning_tail=2（优化生效）：3 轮历史时最旧轮思考链省略."""
    out = build_history_messages(_assistant_msgs(3), "", max_chars=10**6)
    dicts = _assistant_dicts(out)
    assert dicts[0].get("reasoning_content") is None
    assert dicts[1]["reasoning_content"] == "R2"


def test_reasoning_tail_recent_round_with_tool_calls_kept():
    """最近轮带 tool_calls 的思考链必须保留（M20 THK-04: 携带 tools 必须回传）."""
    from llm_loop.core.message import ToolCall

    msgs = _assistant_msgs(3)
    msgs[-1] = Message(
        role="assistant",
        content="A3",
        reasoning_content="R3",
        source=MessageSource.SYSTEM,
        tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "x"})],
    )
    out = build_history_messages(msgs, "", max_chars=10**6, reasoning_tail=1)
    dicts = _assistant_dicts(out)
    # 最近轮（带 tool_calls）reasoning 保留；更早轮省略
    assert dicts[-1]["reasoning_content"] == "R3"
    assert dicts[-1].get("tool_calls") is not None
    assert dicts[0].get("reasoning_content") is None

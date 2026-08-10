"""单元测试: 上下文构造与压缩另存（T18/T22 / FR-MSG-03 / spec 5.2.3-2）.

T22 验收: 超长时"另存提取重要信息"再注入精简内容（无静默丢弃），
压缩标注含"可查 search_archive"指引。
"""

from __future__ import annotations

from typing import Literal

from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource

_Role = Literal["user", "assistant", "tool", "system"]


def _m(role: _Role, content: str) -> Message:
    return Message(role=role, content=content, source=MessageSource.USER)


def test_history_order_preserved():
    """FR-MSG-03: 保序提交."""
    msgs = [_m("user", "第一条"), _m("assistant", "回答1"), _m("user", "第二条")]
    out = build_history_messages(msgs, system_prompt="SYS", max_chars=100000)
    roles = [m["role"] for m in out]
    assert roles == ["system", "user", "assistant", "user"]
    assert out[1]["content"] == "第一条"
    assert out[3]["content"] == "第二条"


def test_history_compression_archives_oldest():
    """T22: 超长时最旧消息被另存（archive_sink 收到）+ 注入压缩标注."""
    archived: list[Message] = []
    msgs = [_m("user", "A" * 1000), _m("user", "B" * 1000), _m("user", "C" * 10)]

    def sink(session_id: str, msg: Message) -> None:
        archived.append(msg)

    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=600, session_id="s1", archive_sink=sink
    )
    # 被压缩的旧消息全部另存（信息零丢失）
    assert len(archived) >= 1
    assert all(a.content for a in archived)  # 原文完整
    # 注入压缩标注（含 search_archive 指引）
    assert any("[上下文压缩]" in str(m.get("content", "")) for m in out)
    assert any("search_archive" in str(m.get("content", "")) for m in out)
    # 最新消息保留
    contents = [m.get("content", "") for m in out if m["role"] != "system"]
    assert any("C" in c for c in contents)


def test_history_single_oversize_message_archived():
    """T22: 单条消息即超限 → 全文另存 + 精简注入 + 压缩标注."""
    archived: list[Message] = []
    msgs = [_m("user", "A" * 5000)]

    def sink(session_id: str, msg: Message) -> None:
        archived.append(msg)

    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=2000, session_id="s1", archive_sink=sink
    )
    assert len(archived) == 1
    assert len(archived[0].content) == 5000  # 原文完整另存
    body = [m for m in out if m["role"] != "system"][0]["content"]
    assert len(body) < 2100
    assert "search_archive" in body


def test_history_within_budget_no_compression():
    """预算内 → 全保留无压缩标注."""
    msgs = [_m("user", "你好"), _m("assistant", "你好呀")]
    out = build_history_messages(msgs, system_prompt="SYS", max_chars=10000)
    assert len(out) == 3
    assert not any("[上下文压缩]" in str(m.get("content", "")) for m in out)


def test_reasoning_content_kept_after_trim():
    """M20 THK-04: 单条超限压缩后 reasoning_content 保留（回传链不因截断断裂）."""
    from llm_loop.core.history import build_history_messages
    from llm_loop.core.message import Message, MessageSource

    long_msg = Message(
        role="assistant",
        content="x" * 5000,
        source=MessageSource.USER,
        reasoning_content="思考链保留",
    )
    out = build_history_messages([long_msg], system_prompt="", max_chars=2000)
    found = [
        d for d in out if d.get("role") == "assistant" and d.get("content", "").startswith("x")
    ]
    assert found, "压缩后应保留 assistant 消息"
    assert found[0].get("reasoning_content") == "思考链保留"

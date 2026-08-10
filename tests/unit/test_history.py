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


def _tool_pair(prefix: str, n_calls: int = 2) -> list[Message]:
    """构造 assistant(tool_calls) + n 条 tool 响应的配对组（协议合法序列）."""
    msgs: list[Message] = []
    calls = []
    for k in range(n_calls):
        tid = f"{prefix}_call_{k}"
        calls.append({"id": tid, "name": "web_fetch", "arguments": "{}"})
    msgs.append(Message(role="assistant", content=f"调用 {prefix}", source=MessageSource.USER, tool_calls=calls))
    for k in range(n_calls):
        msgs.append(Message(role="tool", content=f"结果 {prefix}_{k}", source=MessageSource.TOOL, tool_call_id=f"{prefix}_call_{k}"))
    return msgs


def test_compression_keeps_tool_pairs_atomic():
    """M40 修复: 压缩保留端——assistant(tool_calls) 与其 tool 响应同组保留（协议不断裂）."""
    # 构造: 旧配对组（大字符，将触发归档）+ 新配对组（保留）+ 最新 user
    msgs = []
    for k in range(8):
        msgs.extend(_tool_pair(f"old{k}", 2))  # 旧配对组（8 组 × 3 条，约 24 条大消息）
    msgs.extend(_tool_pair("new", 2))  # 新配对组（保留）
    msgs.append(_m("user", "最新问题"))
    # 预算仅够最新部分 → 触发压缩
    out = build_history_messages(msgs, system_prompt="SYS", max_chars=2000)
    roles = [d["role"] for d in out]
    # 校验: assistant(tool_calls) 后的 tool 消息数 == 该 assistant 的 tool_calls 数（协议配对）
    i = 0
    n = len(out)
    while i < n:
        d = out[i]
        if d["role"] == "assistant" and d.get("tool_calls"):
            n_calls = len(d["tool_calls"])
            j = i + 1
            while j < n and out[j]["role"] == "tool":
                j += 1
            tool_count = j - (i + 1)
            assert tool_count == n_calls, f"assistant(tool_calls={n_calls}) 后 tool 消息数 {tool_count} 不匹配"
            i = j
        else:
            i += 1


def test_compression_archives_tool_pairs_atomic():
    """M40 修复: 压缩归档端——被归档的 assistant(tool_calls) 与其 tool 响应整组归档（无残留 tool 消息）."""
    archived: list[Message] = []
    msgs = []
    for k in range(10):
        msgs.extend(_tool_pair(f"old{k}", 2))
    msgs.append(_m("user", "最新问题"))

    def sink(session_id: str, msg: Message) -> None:
        archived.append(msg)

    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=600, session_id="s1", archive_sink=sink
    )
    roles = [d["role"] for d in out]
    # 归档端的 assistant(tool_calls) 也应与其 tool 响应同组归档（不残留孤 tool）
    arch_roles = [m.role for m in archived]
    for idx, r in enumerate(arch_roles):
        if r == "assistant":
            # 该 assistant 带 tool_calls → 其后必须归档了对应的 tool 响应（整组归档）
            assert any(t == "tool" for t in arch_roles[idx:]), "归档端 assistant(tool_calls) 无对应 tool 响应"
    # 保留端配对校验
    i = 0
    n = len(out)
    while i < n:
        d = out[i]
        if d["role"] == "assistant" and d.get("tool_calls"):
            n_calls = len(d["tool_calls"])
            j = i + 1
            while j < n and out[j]["role"] == "tool":
                j += 1
            assert (j - (i + 1)) == n_calls, "保留端 assistant(tool_calls) 与 tool 响应数不匹配"
            i = j
        else:
            i += 1

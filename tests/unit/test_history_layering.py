"""历史分层重发测试（EVO-20260811-7baa2737）.

旧的长 tool 消息（距最新 >= age 条 且 content > threshold）降级为首尾摘要，
原文归档（信息零丢失）；最近上下文完整保留；默认参数零回归。
"""
from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource


def _tool_msg(content: str, name: str = "read_file") -> Message:
    return Message(
        role="tool", content=content, source=MessageSource.TOOL,
        tool_call_id="c1", tool_name=name,
    )


def _user(content: str) -> Message:
    return Message(role="user", content=content, source=MessageSource.USER)


def test_budget_in_layer_trims_old_long_tool():
    """预算内：距最新 >= age 条的旧长 tool 消息降级（含首尾/检索指引），原文归档."""
    archived: list[Message] = []
    # tool 消息在 idx0，距最新 = 24 条（>= age=20）→ 触发降级
    msgs = [_tool_msg("D" * 5000)] + [_user(f"问题{i}") for i in range(24)]
    sink = lambda sid, m: archived.append(m)  # noqa: E731
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=100000, session_id="s1",
        archive_sink=sink, layer_tool_trim=True,
    )
    contents = [str(m.get("content", "")) for m in out]
    assert any("工具输出已分层" in c for c in contents)  # 降级注入
    assert any("search_archive" in c for c in contents)  # 检索指引
    assert any("问题23" in c for c in contents)  # 最新消息完整
    assert len(archived) == 1 and len(archived[0].content) == 5000  # 原文完整归档


def test_recent_tool_not_trimmed():
    """距最新消息 < age 条的 tool 消息保留完整（保护最近上下文）."""
    msgs = [_user("问题0"), _tool_msg("E" * 5000), _user("最新问题")]
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=100000, session_id="s1",
        layer_tool_trim=True,
    )
    contents = [str(m.get("content", "")) for m in out]
    assert not any("工具输出已分层" in c for c in contents)
    assert any("EEEEE" in c for c in contents)  # 完整保留


def test_short_tool_not_trimmed():
    """短 tool 消息不降级."""
    msgs = [_tool_msg("S" * 100), _user("问题1"), _user("最新问题")]
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=100000, session_id="s1",
        layer_tool_trim=True,
    )
    contents = [str(m.get("content", "")) for m in out]
    assert not any("工具输出已分层" in c for c in contents)


def test_default_off_zero_regression():
    """默认 layer_tool_trim=False → 行为不变（不降级）."""
    msgs = [_tool_msg("D" * 5000), _user("问题1"), _user("最新问题")]
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=100000, session_id="s1"
    )
    contents = [str(m.get("content", "")) for m in out]
    assert not any("工具输出已分层" in c for c in contents)
    assert any("DDDDD" in c for c in contents)


def test_compression_path_layering_non_interfering():
    """压缩路径：分层开关不干扰压缩主流程（归档 + 压缩标注正常，短 tool 消息不误伤）.

    注: 超预算时旧长 tool 消息会被"最旧先压"整组归档（不进保留组），
    分层降级主战场在预算内主动瘦身；此处验证压缩路径下开关开启无副作用。
    """
    archived: list[Message] = []
    msgs = [
        _tool_msg("G" * 3000),
        _user("q" * 500),
        _user("最新问题"),
    ]
    sink = lambda sid, m: archived.append(m)  # noqa: E731
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=1500, session_id="s1",
        archive_sink=sink, layer_tool_trim=True,
    )
    contents = [str(m.get("content", "")) for m in out]
    assert any("[上下文压缩]" in c for c in contents)  # 压缩标注正常
    assert any("最新问题" in c for c in contents)  # 最新消息保留
    assert len(archived) >= 1  # 归档正常

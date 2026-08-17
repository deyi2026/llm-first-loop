"""单元测试: 统一消息结构与工具消息严格性（T18 / FR-MSG / 约束 C1-C2）."""

from __future__ import annotations

from llm_loop.core.message import (
    Message,
    MessageSource,
    ToolResult,
    ToolResultStatus,
)


def test_message_roles_homogeneous():
    """FR-MSG-01: user/tool/assistant 同构承载."""
    for role in ("user", "assistant", "tool"):
        m = Message(role=role, content="内容", source=MessageSource.USER)
        assert m.role == role
        assert m.content == "内容"


def test_message_source_enum():
    """FR-MSG-04: 来源标识."""
    assert MessageSource.USER.value == "user"
    assert MessageSource.TOOL.value == "tool"
    assert MessageSource.MEMORY.value == "memory"
    assert MessageSource.SYSTEM.value == "system"


def test_tool_message_strictness():
    """约束 C1/C2: tool 消息必须带非空 tool_call_id 与 content."""
    tr = ToolResult(
        status=ToolResultStatus.SUCCESS,
        content="读取结果",
        tool_call_id="call_1",
        tool_name="read_file",
    )
    m = tr.to_message()
    assert m.role == "tool"
    assert m.tool_call_id == "call_1"
    assert m.content  # 非空（约束 C2）
    assert m.status == ToolResultStatus.SUCCESS


def test_tool_message_empty_content_filled():
    """约束 C2: 空结果构造如实说明文本."""
    tr = ToolResult(
        status=ToolResultStatus.SUCCESS,
        content="",
        tool_call_id="call_2",
        tool_name="execute_command",
    )
    m = tr.to_message()
    assert m.content.strip()


def test_tool_message_error_detail_preserved():
    """FR-FBK-02: 错误完整透传."""
    tr = ToolResult(
        status=ToolResultStatus.ERROR,
        content="[执行异常] FileNotFoundError: no such file",
        tool_call_id="call_3",
        tool_name="read_file",
        error_type="FileNotFoundError",
        error_detail="Traceback...\nFileNotFoundError: no such file",
    )
    m = tr.to_message()
    assert "错误详情" in m.content
    assert m.error_detail and "Traceback" in m.error_detail


def test_tool_message_to_llm_dict():
    """tool 消息协议形态: role/tool_call_id/content + 状态前置标注（T21）."""
    tr = ToolResult(
        status=ToolResultStatus.SUCCESS,
        content="ok",
        tool_call_id="call_4",
        tool_name="web_fetch",
    )
    d = tr.to_message().to_llm_dict()
    assert d["role"] == "tool"
    assert d["tool_call_id"] == "call_4"
    # AI-first（T21）: content 前置显式状态标注
    assert "[状态: success]" in d["content"]
    assert "ok" in d["content"]


def test_assistant_reasoning_content_roundtrip():
    """M20 THK-04: assistant 消息带 reasoning_content → to_llm_dict 含该键；None → 无键."""
    m1 = Message(
        role="assistant",
        content="答",
        source=MessageSource.USER,
        tool_calls=[
            {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
        ],
        reasoning_content="思考过程",
    )
    d = m1.to_llm_dict()
    assert d["reasoning_content"] == "思考过程"
    assert d["tool_calls"] == m1.tool_calls
    # None → 无该键（零回归）
    m2 = Message(role="assistant", content="答", source=MessageSource.USER)
    assert "reasoning_content" not in m2.to_llm_dict()


def test_message_ts_default_and_roundtrip():
    """消息时间戳: 构造默认当前时间；asdict 序列化含 ts；旧 JSON 无 ts 兼容为 0."""
    import time as _time
    from dataclasses import asdict

    from llm_loop.core.session import _message_from_dict

    m = Message(role="user", content="hi", source=MessageSource.USER)
    # 默认 ts = 创建时刻（允许微小偏差）
    assert 0 < m.ts <= _time.time() + 1

    # 序列化含 ts
    d = asdict(m)
    assert d["ts"] == m.ts

    # 反序列化保留
    m2 = _message_from_dict(d)
    assert m2.ts == m.ts

    # 旧 JSON 无 ts → 0（web 端时间显示兜底，不显示）
    m3 = _message_from_dict({"role": "user", "content": "x", "source": "user"})
    assert m3.ts == 0.0

    # 显式 ts 透传
    m4 = _message_from_dict({"role": "user", "content": "x", "source": "user", "ts": 1750000000.5})
    assert m4.ts == 1750000000.5


def test_session_to_dict_persists_ts():
    """Session.to_dict 落盘序列化必须含 ts（端到端回归: ts-e2e 抓到的丢字段 bug）."""
    from llm_loop.core.session import Session, _message_from_dict

    m = Message(role="user", content="hi", source=MessageSource.USER)
    assert m.ts > 0
    s = Session(session_id="sess-ts-persist", messages=[m])
    msgs = s.to_dict()["messages"]
    assert msgs[0]["ts"] == m.ts
    # 与 _message_from_dict 回读闭环
    m2 = _message_from_dict(msgs[0])
    assert m2.ts == m.ts

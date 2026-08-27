"""方向 B 配对自检（2026-08-24 主区故障）.

根因：DeepSeek/OpenAI 协议要求 tool 回执必须紧跟（并响应）某条带 tool_calls 的
assistant 消息；孤立/多余 tool 回执（前无匹配声明 / id 不匹配）→ API 400
"Messages with role 'tool' must be a response to a preceding message with
'tool_calls'"。原 validate/repair 只覆盖方向 A（声明缺回执），方向 B 为盲区，
本测试固化修复行为（_pairing_direction_b_orphans 统一判定 + 提交视图丢弃）。
"""

from __future__ import annotations

from llm_loop.core.history import (
    _pairing_direction_b_orphans,
    build_history_messages,
    validate_tool_call_pairing,
)
from llm_loop.core.message import Message, MessageSource


def _m(role, content="", tc=None, tcid=None):
    return Message(
        role=role,
        content=content,
        source=MessageSource.TOOL if role == "tool" else MessageSource.USER,
        tool_calls=tc,
        tool_call_id=tcid,
    )


def _build(msgs):
    return build_history_messages(
        msgs,
        "sys",
        100000,
        compact_ratio=1.0,
        session_id="t",
        archive_sink=None,
        summarizer=None,
        layer_tool_trim=False,
        tool_trim_threshold=8000,
        tool_trim_age=0,
        reasoning_tail=2,
        skip_injected_system=True,
        history_anchor=0,
        anchor_out=[],
        head_keep_chars=0,
        _append_summary_enabled=False,
    )


def test_orphan_receipt_following_valid_pair_is_dropped():
    """声明1个+回执1条+多余回执(无匹配声明) → 构建后多余回执被丢弃，无孤立泄漏."""
    msgs = [
        _m("user", "q"),
        _m("assistant", "", tc=[{"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]),
        _m("tool", "r1", tcid="c1"),
        _m("tool", "orphan", tcid="c_orphan"),  # 多余
        _m("assistant", "ok"),
    ]
    out = _build(msgs)
    assert validate_tool_call_pairing(out) == [], f"构建后仍违规: {validate_tool_call_pairing(out)}"
    tools = [m.get("content") for m in out if m.get("role") == "tool"]
    assert "orphan" not in tools, f"多余回执未被丢弃: {tools}"


def test_orphan_receipt_at_head_is_dropped():
    """首条即 tool 回执（前无任何声明）→ 被丢弃，仅剩 system+user."""
    msgs = [_m("tool", "head_orphan", tcid="x0"), _m("user", "hi")]
    out = _build(msgs)
    assert validate_tool_call_pairing(out) == []
    assert not any(m.get("role") == "tool" for m in out), f"首条孤立回执未被丢弃: {out}"


def test_normal_pair_unchanged():
    """正常声明+回执配对 → 零回归（保留完整）."""
    msgs = [
        _m("user", "a"),
        _m("assistant", "", tc=[{"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]),
        _m("tool", "r1", tcid="c1"),
    ]
    out = _build(msgs)
    assert validate_tool_call_pairing(out) == []
    assert sum(1 for m in out if m.get("role") == "tool") == 1


def test_extra_receipt_beyond_declared_is_dropped():
    """声明2个+回执3条 → 第3条(无匹配声明)被丢弃，保留2条合法回执."""
    msgs = [
        _m("user", "q"),
        _m(
            "assistant",
            "",
            tc=[
                {"id": "a", "type": "function", "function": {"name": "x", "arguments": "{}"}},
                {"id": "b", "type": "function", "function": {"name": "y", "arguments": "{}"}},
            ],
        ),
        _m("tool", "ra", tcid="a"),
        _m("tool", "rb", tcid="b"),
        _m("tool", "extra", tcid="zz"),
    ]
    out = _build(msgs)
    assert validate_tool_call_pairing(out) == []
    tools = [m.get("content") for m in out if m.get("role") == "tool"]
    assert tools == ["ra", "rb"], f"期望保留 ra,rb 实际: {tools}"


def test_orphan_detector_id_semantics():
    """_pairing_direction_b_orphans: id 精确判定——不匹配声明的回执被标为孤儿."""
    msgs = [
        _m("assistant", "", tc=[{"id": "a", "type": "function", "function": {"name": "x", "arguments": "{}"}}]),
        _m("tool", "ra", tcid="a"),
        _m("tool", "wrong_id", tcid="nope"),
    ]
    d = [m.to_llm_dict() for m in msgs]
    orphans = _pairing_direction_b_orphans(d)
    assert len(orphans) == 1, f"期望 1 个孤儿, 实际 {orphans}"
    assert d[sorted(orphans)[0]].get("tool_call_id") == "nope"


def test_nonempty_mismatched_id_is_orphan_and_repaired_with_declared_id():
    """两个不同非空 id 不得位置兜底；错回执丢弃并为声明补占位。"""
    msgs = [
        _m("assistant", "", tc=[{"id": "a", "type": "function", "function": {"name": "x", "arguments": "{}"}}]),
        _m("tool", "wrong", tcid="WRONG"),
    ]
    d = [m.to_llm_dict() for m in msgs]
    assert _pairing_direction_b_orphans(d) == {1}
    violations = validate_tool_call_pairing(d)
    assert violations, "非空 tool_call_id 错配必须报违规"
    out = _build(msgs)
    assert validate_tool_call_pairing(out) == []
    tools = [m for m in out if m.get("role") == "tool"]
    assert len(tools) == 1
    assert tools[0].get("tool_call_id") == "a"
    assert "工具回执缺失" in str(tools[0].get("content", ""))


def test_empty_receipt_id_keeps_positional_compatibility():
    """存量空 tool_call_id 仍可按位置与非空声明兼容配对。"""
    msgs = [
        _m("assistant", "", tc=[{"id": "a", "type": "function", "function": {"name": "x", "arguments": "{}"}}]),
        _m("tool", "legacy", tcid=""),
    ]
    d = [m.to_llm_dict() for m in msgs]
    assert _pairing_direction_b_orphans(d) == set()
    assert validate_tool_call_pairing(d) == []

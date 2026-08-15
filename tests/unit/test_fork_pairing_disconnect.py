"""P1-6(2026-08-15): fork 工具轮边界对齐 + 配对空 id 修复 + 断连保存（审计 #15/#16/#17）.

#15 fork 点在 assistant(tool_calls) 与其 tool 回执之间切开 → 分支继承孤儿声明，
    下次运行被配对修复伪造 `[程序异常]` 回执（或 API 400）。修复：fork 点向前
    对齐到完整工具轮边界。
#16 配对自检/补齐漏计空 tool_call_id 回执 → 多补占位（额外 tool 消息无声明 → 400）。
    修复：按 id 配对 + 空 id 位置兜底。
#17 LLM 流式中 GeneratorExit（客户端断连）跳过 loop 末 session.save → 事件日志
    已追加而 session JSON 未保存的双轨漂移。修复：run_stream 包装层 finally 补保存。
"""

from __future__ import annotations

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore
from llm_loop.event_log.fork import fork_session
from llm_loop.event_log.store import EventStore


def _tool_session(ss: SessionStore) -> str:
    """构造含完整工具轮的会话: user, assistant(tc c1,c2), tool c1, tool c2, assistant 文本."""
    sid = ss.create()
    ss.append(sid, Message(role="user", content="查文件", source=MessageSource.USER))
    ss.append(sid, Message(
        role="assistant", content="", source=MessageSource.SYSTEM,
        tool_calls=[{"id": "c1", "name": "read_file", "arguments": {}},
                    {"id": "c2", "name": "read_file", "arguments": {}}],
    ))
    ss.append(sid, Message(role="tool", content="r1", source=MessageSource.TOOL, tool_call_id="c1"))
    ss.append(sid, Message(role="tool", content="r2", source=MessageSource.TOOL, tool_call_id="c2"))
    ss.append(sid, Message(role="assistant", content="完成", source=MessageSource.SYSTEM))
    return sid


def test_fork_snaps_back_from_tool_round_midpoint(tmp_path):
    """fork 点在工具轮中间（声明后/回执后未满）→ 向前收到该 assistant 之前."""
    es = EventStore(str(tmp_path / "event_logs"), enabled=True)
    ss = SessionStore(str(tmp_path / "sessions"), event_store=es)
    sid = _tool_session(ss)

    # fp=2：切在 assistant(tc) 之后、c1 回执之前 → 收到 1（不含孤儿声明）
    report = fork_session(es, ss, sid, fork_point=2)
    assert report.success
    assert report.snapped_fork_point == 1, f"未对齐工具轮边界: {report.snapped_fork_point}"
    branch = ss.load(report.new_session_id)
    assert len(branch.messages) == 1
    assert branch.messages[0].role == "user"

    # fp=3：切在 c1 回执之后（c2 回执缺失）→ 同样收到 1
    report2 = fork_session(es, ss, sid, fork_point=3)
    assert report2.snapped_fork_point == 1

    # fp=4：完整工具轮（两回执齐）→ 不动
    report3 = fork_session(es, ss, sid, fork_point=4)
    assert report3.snapped_fork_point == 4
    branch3 = ss.load(report3.new_session_id)
    assert len(branch3.messages) == 4


def test_fork_full_inherits_all(tmp_path):
    """零回归：不指定 fork 点继承全部（含完整工具轮）."""
    es = EventStore(str(tmp_path / "event_logs"), enabled=True)
    ss = SessionStore(str(tmp_path / "sessions"), event_store=es)
    sid = _tool_session(ss)
    report = fork_session(es, ss, sid)
    assert report.success
    assert report.snapped_fork_point is None  # 未指定 fork 点 → 无对齐动作
    branch = ss.load(report.new_session_id)
    assert len(branch.messages) == 5


# ── #16 配对：空 id 回计 ──
def test_pairing_empty_id_receipt_counts():
    """空 tool_call_id 回执按位置兜底配对——不再漏计导致多补占位（多补会 400）."""
    from llm_loop.core.history import _repair_tool_call_pairing, validate_tool_call_pairing

    msgs = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "read_file"}},
            {"id": "c2", "function": {"name": "read_file"}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "r1"},
        {"role": "tool", "tool_call_id": "", "content": "r2"},  # 空 id 回执（存量会话存在）
    ]
    assert validate_tool_call_pairing(msgs) == [], f"空 id 回执被漏计: {validate_tool_call_pairing(msgs)}"
    out = _repair_tool_call_pairing(msgs)
    tool_msgs = [m for m in out if m.get("role") == "tool"]
    assert len(tool_msgs) == 2, f"多补了占位（额外 tool 消息无声明 → API 400）: {len(tool_msgs)}"
    assert not any("[程序异常]" in m.get("content", "") for m in tool_msgs)


def test_pairing_still_fills_genuine_gap():
    """零回归：真实缺回执仍按声明 id 补占位."""
    from llm_loop.core.history import _repair_tool_call_pairing, validate_tool_call_pairing

    msgs = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "read_file"}},
            {"id": "c2", "function": {"name": "read_file"}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "r1"},
    ]
    assert validate_tool_call_pairing(msgs), "真缺口未报违规"
    out = _repair_tool_call_pairing(msgs)
    tool_msgs = [m for m in out if m.get("role") == "tool"]
    assert len(tool_msgs) == 2
    assert tool_msgs[1]["tool_call_id"] == "c2"
    assert "[程序异常]" in tool_msgs[1]["content"]


# ── #17 断连保存 ──
def test_generator_exit_saves_session(build_test_engine):
    """LLM 流式中客户端断连（生成器 close → GeneratorExit）→ 会话快照仍落盘.

    修复前：GeneratorExit 跳过 loop 末 save → 事件日志已追加而 JSON 未保存（双轨漂移）。
    修复后：部分回答如实落会话（中断标注，不伪装完整）+ 立即保存。
    """
    import itertools

    from llm_loop.llm.client import LLMResponse, StreamDelta

    def chat_stream(messages, tools, **kw):  # noqa: ARG001 — 永不结束的长回答流
        for i in itertools.count():
            yield StreamDelta(text=f"片段{i} ")
        return LLMResponse(content="（不会到达）", tool_calls=[], provider="fake")

    engine, fake = build_test_engine([])
    fake.chat_stream = chat_stream
    sid = engine.session.create()
    gen = engine.run_stream(sid, "开始长回答")
    deltas = []
    for i, d in enumerate(gen):
        deltas.append(d)
        if i >= 2:
            gen.close()  # 客户端断连
            break
    assert deltas, "未收到任何 delta"
    stored = engine.session.load(sid)
    # 断连后会话 JSON 已保存：用户消息 + 部分回答（assistant 消息，中断标注）在盘中
    assert any(m.role == "user" and m.content == "开始长回答" for m in stored.messages)
    assistant_msgs = [m for m in stored.messages if m.role == "assistant"]
    assert assistant_msgs, "断连时 assistant 部分回答未随保存落盘（双轨漂移未闭合）"
    assert "片段0" in assistant_msgs[-1].content
    assert "中断" in assistant_msgs[-1].content or "不完整" in assistant_msgs[-1].content

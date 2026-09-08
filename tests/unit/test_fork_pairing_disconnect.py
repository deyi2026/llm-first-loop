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
    修复后：仅模型真实 partial 落 assistant；断连事实走 metadata/event + 立即保存。
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
    # 断连后会话 JSON 已保存：用户消息 + 模型真实 partial 在盘中。
    assert any(m.role == "user" and m.content == "开始长回答" for m in stored.messages)
    assistant_msgs = [m for m in stored.messages if m.role == "assistant"]
    assert assistant_msgs, "断连时 assistant 部分回答未随保存落盘（双轨漂移未闭合）"
    assert "片段0" in assistant_msgs[-1].content
    assert "[对话已中断]" not in assistant_msgs[-1].content
    assert "不完整部分回答" not in assistant_msgs[-1].content
    assert (assistant_msgs[-1].metadata or {}).get("llm_interrupted") is True
    assert (assistant_msgs[-1].metadata or {}).get("answer_origin") == "model"


def test_generator_exit_partial_resumes_once_before_next_human_ingress(build_test_engine):
    """Client-disconnect partial is exact one-shot continuity, not a completed answer."""
    import itertools

    from llm_loop.llm.client import LLMResponse, StreamDelta

    def chat_stream(messages, tools, **kw):  # noqa: ARG001
        for i in itertools.count():
            yield StreamDelta(text=f"PARTIAL-{i} ")
        return LLMResponse(content="never", tool_calls=[], provider="fake")

    engine, fake = build_test_engine([])
    fake.chat_stream = chat_stream
    sid = engine.session.create()
    gen = engine.run_stream(sid, "FIRST-QUESTION")
    for i, _delta in enumerate(gen):
        if i >= 1:
            gen.close()
            break

    stored = engine.session.load(sid)
    partial_rows = [m for m in stored.messages if (m.metadata or {}).get("llm_interrupted")]
    assert partial_rows and "PARTIAL-0" in partial_rows[-1].content

    fake.chat_stream = None
    fake._responses = [{"content": "SECOND-ANSWER"}]
    result = engine.run(sid, "SECOND-QUESTION")
    assert result.final_answer == "SECOND-ANSWER"
    wire = fake.calls[-1]["messages"]
    joined = "\n".join(str(m.get("content") or "") for m in wire)
    assert "FIRST-QUESTION" in joined
    assert "SECOND-QUESTION" in joined
    partial_wire = [
        m
        for m in wire
        if m.get("role") == "assistant" and "PARTIAL-" in str(m.get("content") or "")
    ]
    assert len(partial_wire) == 1
    assert "PARTIAL-0" in partial_wire[0]["content"]
    assert "截断标注" not in partial_wire[0]["content"]
    assert wire[-2] == partial_wire[0]
    assert wire[-1] == {"role": "user", "content": "SECOND-QUESTION"}
    assert not any(
        m.get("role") == "assistant" and "PARTIAL-" in str(m.get("content") or "")
        for m in wire[:-2]
    )
    stored_after = engine.session.load(sid)
    assert any(
        (m.metadata or {}).get("llm_interrupted") and "PARTIAL-0" in m.content
        for m in stored_after.messages
    )


def test_hard_restart_open_stream_checkpoint_is_first_class_recent_continuity(
    build_test_engine, tmp_path
):
    """A process-death checkpoint with no run.end resumes immediately on next ingress."""
    engine, fake = build_test_engine([{"content": "RESUMED-ANSWER"}])
    es = EventStore(str(tmp_path / "restart-events"), enabled=True)
    engine._event_store = es  # noqa: SLF001 — integration-test durable source
    sid = engine.session.create()
    engine.session.append(
        sid, Message(role="user", content="ORIGINAL-TASK", source=MessageSource.USER)
    )
    es.append(
        sid,
        "llm.partial_checkpoint",
        {
            "round": 7,
            "provider": "glm",
            "model": "glm/glm-5.3",
            "text_tail": "MODEL-PARTIAL",
            "reasoning_tail": "MODEL-REASONING",
            "text_chars": 13,
            "reasoning_chars": 15,
            "partial_sha256": "a" * 64,
        },
    )

    result = engine.run(sid, "继续")
    assert result.final_answer == "RESUMED-ANSWER"
    wire = fake.calls[-1]["messages"]
    assert wire[-2] == {
        "role": "assistant",
        "content": "MODEL-PARTIAL",
        "reasoning_content": "MODEL-REASONING",
    }
    assert wire[-1] == {"role": "user", "content": "继续"}
    assert all("截断标注" not in str(m.get("content") or "") for m in wire)


def test_hard_restart_uses_full_sidecar_reasoning_not_bounded_event_tail(
    build_test_engine, tmp_path, monkeypatch
):
    """Long in-flight reasoning resumes from the hash-verified full snapshot."""
    engine, fake = build_test_engine([{"content": "RESUMED-FULL"}])
    es = EventStore(str(tmp_path / "full-restart-events"), enabled=True)
    engine._event_store = es  # noqa: SLF001
    sid = engine.session.create()
    engine.session.append(
        sid, Message(role="user", content="ORIGINAL", source=MessageSource.USER)
    )
    sess = engine.session.load(sid)
    monkeypatch.setenv("INTERRUPT_TEXT_TAIL_CHARS", "9")
    monkeypatch.setenv("INTERRUPT_REASONING_TAIL_CHARS", "11")
    text = "TEXT-" * 300
    reasoning = "REASON-" * 2000
    engine._on_llm_partial_checkpoint(  # noqa: SLF001
        sess,
        text_parts=[text],
        reasoning_parts=[reasoning],
        round_no=4,
        provider="deepseek",
        model="deepseek/deepseek-v4-flash",
    )
    event = [e for e in es.read(sid) if e.type == "llm.partial_checkpoint"][-1]
    assert event.payload["text_tail"] == text[-9:]
    assert event.payload["reasoning_tail"] == reasoning[-11:]

    result = engine.run(sid, "继续")
    assert result.final_answer == "RESUMED-FULL"
    wire = fake.calls[-1]["messages"]
    assert wire[-2]["role"] == "assistant"
    assert wire[-2]["content"] == text
    assert wire[-2]["reasoning_content"] == reasoning
    assert wire[-1] == {"role": "user", "content": "继续"}


def test_first_stream_delta_is_checkpointed_before_stream_can_be_killed(
    build_test_engine, tmp_path
):
    """The first yielded model bytes already have a durable restart checkpoint."""
    from llm_loop.llm.client import LLMResponse, StreamDelta

    def chat_stream(messages, tools, **kw):  # noqa: ARG001
        yield StreamDelta(text="FIRST-TEXT", reasoning="FIRST-THINK")
        yield StreamDelta(text="SECOND-TEXT", reasoning="SECOND-THINK")
        return LLMResponse(content="done", tool_calls=[], provider="fake")

    engine, fake = build_test_engine([])
    es = EventStore(str(tmp_path / "live-checkpoint-events"), enabled=True)
    engine._event_store = es  # noqa: SLF001
    fake.chat_stream = chat_stream
    sid = engine.session.create()
    gen = engine.run_stream(sid, "TASK")

    first = next(gen)
    assert first.text == "FIRST-TEXT"
    rows = [e for e in es.read(sid) if e.type == "llm.partial_checkpoint"]
    assert rows, "first streamed delta must already be restart-recoverable"
    assert rows[-1].payload["text_tail"] == "FIRST-TEXT"
    assert rows[-1].payload["reasoning_tail"] == "FIRST-THINK"
    gen.close()


def test_settled_partial_checkpoint_is_not_resurrected(build_test_engine, tmp_path):
    """A checkpoint before a durable run.end is historical, never stale-resumed."""
    engine, fake = build_test_engine([{"content": "NEW-ANSWER"}])
    es = EventStore(str(tmp_path / "settled-events"), enabled=True)
    engine._event_store = es  # noqa: SLF001
    sid = engine.session.create()
    engine.session.append(
        sid, Message(role="user", content="OLD-TASK", source=MessageSource.USER)
    )
    es.append(
        sid,
        "llm.partial_checkpoint",
        {
            "round": 1,
            "provider": "glm",
            "model": "glm/glm-5.3",
            "text_tail": "STALE-PARTIAL",
            "reasoning_tail": "STALE-THINK",
            "partial_sha256": "b" * 64,
        },
    )
    es.append(
        sid,
        "run.end",
        {
            "reason": "llm_error",
            "rounds": 1,
            "tokens_in": 0,
            "tokens_out": 0,
            "cache_hit": 0,
            "duration_ms": 1,
            "model_used": "glm/glm-5.3",
            "truncated": False,
            "answer_preview": "",
        },
    )

    result = engine.run(sid, "新的问题")
    assert result.final_answer == "NEW-ANSWER"
    wire = fake.calls[-1]["messages"]
    joined = "\n".join(str(m.get("content") or "") for m in wire)
    assert "STALE-PARTIAL" not in joined
    assert "STALE-THINK" not in "\n".join(str(m.get("reasoning_content") or "") for m in wire)
    assert wire[-1] == {"role": "user", "content": "新的问题"}


def test_engine_adjacent_user_reply_rehydrates_retired_previous_model_turn(
    build_test_engine, tmp_path
):
    """Resolved-episode retirement must not erase the model question the user answers next."""
    from llm_loop.memory.episode import EpisodeStore

    engine, fake = build_test_engine(
        [
            {"content": "你更看重速度还是精度？", "reasoning_content": "ASK-THINK"},
            {"content": "那就优先精度。"},
        ]
    )
    engine.episode_store = EpisodeStore(tmp_path / "episodes")
    sid = engine.session.create()

    first = engine.run(sid, "帮我选方案")
    assert first.final_answer == "你更看重速度还是精度？"
    stored = engine.session.load(sid)
    assert stored.messages[-1].metadata.get("resolved_episode_ref"), (
        "precondition: current lifecycle has retired the completed prior turn"
    )

    second = engine.run(sid, "更看重精度")
    assert second.final_answer == "那就优先精度。"
    wire = fake.calls[-1]["messages"]
    assert wire[-2]["role"] == "assistant"
    assert wire[-2]["content"] == "你更看重速度还是精度？"
    assert "reasoning_content" not in wire[-2]
    assert wire[-1] == {"role": "user", "content": "更看重精度"}

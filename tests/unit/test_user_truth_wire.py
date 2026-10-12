"""INJECTION-GOVERNANCE R6: user-truth semantic tail + wire invariant."""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.injection_labels import InjectionLayer, origin_metadata, render_program_appendix
from llm_loop.core.message import Message, MessageSource


def _human(text: str) -> Message:
    return Message(
        role="user",
        content=text,
        source=MessageSource.USER,
        metadata=origin_metadata(InjectionLayer.USER_INSTRUCTION),
    )


def _program(text: str) -> Message:
    return Message(
        role="user",
        content=render_program_appendix(text, InjectionLayer.STATUS),
        source=MessageSource.USER,
        metadata=origin_metadata(InjectionLayer.STATUS),
    )


def _tail_user_run(messages: list[dict]) -> int:
    n = 0
    for m in reversed(messages):
        if m.get("role") != "user":
            break
        n += 1
    return n


def test_current_ingress_user_truth_allows_program_after_but_not_tool_followup() -> None:
    from llm_loop.core.user_truth_wire import current_ingress_user_truth

    msgs = [_human("exact user"), _program("status")]
    assert current_ingress_user_truth(msgs, 0) == "exact user"

    msgs.append(
        Message(
            role="assistant",
            content="",
            source=MessageSource.SYSTEM,
            tool_calls=[
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        )
    )
    assert current_ingress_user_truth(msgs, 0) is None


def test_current_ingress_user_truth_rejects_program_turn_ref() -> None:
    from llm_loop.core.user_truth_wire import current_ingress_user_truth

    msgs = [_human("real"), _program("not human")]
    assert current_ingress_user_truth(msgs, 1) is None


def test_build_initial_round_envelope_ends_with_exact_user_truth(tmp_path: Path) -> None:
    from tests.unit.test_injection_fingerprint import _arm_all_slots, _build, _engine

    engine, sess = _engine(tmp_path)
    engine._run_state().current_turn_ref = 0
    truth = sess.messages[0].content
    memory_msgs = _arm_all_slots(engine, sess)
    out = _build(engine, sess, memory_msgs)

    assert _tail_user_run(out) == 1
    envelope = out[-1]
    assert envelope["role"] == "user"
    assert envelope["content"].endswith(truth)
    assert envelope["content"] == truth
    assert "[程序附录·非用户输入]" not in envelope["content"]
    assert sum(m.get("content") == truth for m in out) == 1


def test_build_tool_followup_does_not_reappend_user_truth(tmp_path: Path) -> None:
    from tests.unit.test_injection_fingerprint import _build, _engine

    engine, sess = _engine(tmp_path)
    engine._run_state().current_turn_ref = 0
    truth = sess.messages[0].content
    sess.messages.append(
        Message(
            role="assistant",
            content="",
            source=MessageSource.SYSTEM,
            tool_calls=[
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        )
    )
    sess.messages.append(
        Message(
            role="tool",
            content="tool result",
            source=MessageSource.TOOL,
            tool_call_id="c1",
            tool_name="read_file",
        )
    )

    out = _build(engine, sess, [])

    assert sum(str(m.get("content") or "") == truth for m in out) == 1
    assistant_idx = next(i for i, m in enumerate(out) if m.get("tool_calls"))
    assert out[assistant_idx + 1].get("role") == "tool"
    assert out[assistant_idx + 1].get("tool_call_id") == "c1"


def test_build_compact_initial_round_keeps_exact_truth_as_semantic_tail(tmp_path: Path) -> None:
    from tests.unit.test_injection_fingerprint import _engine

    engine, sess = _engine(tmp_path)
    current = sess.messages[0]
    old: list[Message] = []
    for i in range(4):
        old.append(Message(role="user", content=f"old-u{i}-" + "U" * 600, source=MessageSource.USER))
        old.append(Message(role="assistant", content=f"old-a{i}-" + "A" * 600, source=MessageSource.SYSTEM))
    sess.messages = old + [current]
    engine._run_state().current_turn_ref = len(sess.messages) - 1

    out = engine._build_llm_messages(
        sess, [], max_chars=1800, planned_label="zhipu/glm-5"
    )

    assert engine._last_history_compacted is True
    assert out[-1]["role"] == "user"
    assert str(out[-1]["content"]).endswith(current.content)
    # R8.17（b2b18d9 retire compact runtime prompt status）: 压缩运行时状态
    # （"[上下文压缩] 已归档 N 条…"替身）不再投影进提交视图——压缩后尾部 user
    # 为裸 truth（无程序附录帧时不再构造 program_text+SEPARATOR+truth 信封）。
    # 核心语义不变: exact truth 逐字保留于语义尾位、不被替身替换。
    assert str(out[-1]["content"]) == current.content
    assert _tail_user_run(out) == 1


def test_build_oversized_current_user_is_never_replaced_by_compact_surrogate(tmp_path: Path) -> None:
    """R6 chooses explicit over-budget pressure over silently changing the user's task."""
    from tests.unit.test_injection_fingerprint import _engine

    engine, sess = _engine(tmp_path)
    truth = "X" * 5000
    sess.messages[0].content = truth
    engine._run_state().current_turn_ref = 0

    out = engine._build_llm_messages(
        sess, [], max_chars=1200, planned_label="zhipu/glm-5"
    )

    assert engine._last_history_compacted is True
    assert out[-1]["role"] == "user"
    assert out[-1]["content"] == truth
    assert float(out[-1].get("_message_time_ts") or 0.0) > 0
    assert sum(len(str(m.get("content") or "")) for m in out) > 1200
    assert not any("本消息已压缩" in str(m.get("content") or "") for m in out)

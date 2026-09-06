from __future__ import annotations

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.recent_continuity import apply_recent_continuity_suffix


def _user(text: str) -> Message:
    return Message(role="user", content=text, source=MessageSource.USER)


def _model(text: str, *, reasoning: str | None = None, resolved: bool = False) -> Message:
    metadata = {
        "answer_origin": "model",
        "run_end_reason": "completed",
        "episode_resolution_candidate": True,
    }
    if resolved:
        metadata.update(
            {
                "resolved_episode_ref": "episode:s:0:test",
                "episode_state": "resolved",
            }
        )
    return Message(
        role="assistant",
        content=text,
        source=MessageSource.USER,
        reasoning_content=reasoning,
        metadata=metadata,
    )


def test_resolved_previous_model_answer_is_rehydrated_for_adjacent_user_turn() -> None:
    previous_user = _user("请判断 A 还是 B")
    previous_assistant = _model("你更看重速度还是精度？", reasoning="THINK", resolved=True)
    current_user = _user("更看重精度")
    session = [previous_user, previous_assistant, current_user]
    # R8.5 default provider view may already have retired the completed prior episode.
    built = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "更看重精度"},
    ]

    out, info = apply_recent_continuity_suffix(
        built,
        session_messages=session,
        current_turn_ref=2,
    )

    assert info["source"] == "recent_model_assistant"
    assert out[-2]["role"] == "assistant"
    assert out[-2]["content"] == "你更看重速度还是精度？"
    assert out[-2]["reasoning_content"] == "THINK"
    assert out[-1] == {"role": "user", "content": "更看重精度"}


def test_current_user_is_final_even_if_dynamic_material_was_appended_after_it() -> None:
    previous_user = _user("Q")
    previous_assistant = _model("请补充版本号")
    current_user = _user("v3")
    session = [previous_user, previous_assistant, current_user]
    built = [
        {"role": "system", "content": "SYS"},
        previous_assistant.to_llm_dict(),
        {"role": "user", "content": "v3"},
        {"role": "user", "content": "[program status]"},
    ]

    out, info = apply_recent_continuity_suffix(
        built,
        session_messages=session,
        current_turn_ref=2,
    )

    assert info["moved_after_user"] == 1
    assert out[-2]["content"] == "请补充版本号"
    assert out[-1] == {"role": "user", "content": "v3"}
    assert out[-3] == {"role": "user", "content": "[program status]"}


def test_interruption_resume_wins_and_contains_no_program_annotation() -> None:
    previous_user = _user("继续分析")
    interrupted_storage = Message(
        role="assistant",
        content="PARTIAL\n[截断标注] reason=llm_error",
        source=MessageSource.SYSTEM,
        reasoning_content="OLD-THINK",
        metadata={"llm_interrupted": True, "answer_origin": "program"},
    )
    current_user = _user("继续")
    session = [previous_user, interrupted_storage, current_user]
    built = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "继续"},
    ]
    resume = {
        "source": "open_stream_checkpoint",
        "text_tail": "MODEL-PARTIAL",
        "reasoning_tail": "MODEL-REASONING",
    }

    out, info = apply_recent_continuity_suffix(
        built,
        session_messages=session,
        current_turn_ref=2,
        interruption_resume=resume,
    )

    assert info["source"] == "open_stream_checkpoint"
    assert out[-2] == {
        "role": "assistant",
        "content": "MODEL-PARTIAL",
        "reasoning_content": "MODEL-REASONING",
    }
    assert "截断标注" not in out[-2]["content"]
    assert out[-1] == {"role": "user", "content": "继续"}


def test_provider_truncation_resume_exposes_factual_runtime_state_before_exact_partial() -> None:
    previous_user = _user("分析这个问题")
    interrupted_storage = Message(
        role="assistant",
        content="MODEL-PARTIAL",
        source=MessageSource.USER,
        metadata={
            "llm_interrupted": True,
            "provider_truncated": True,
            "answer_origin": "model",
        },
    )
    current_user = _user("继续")
    session = [previous_user, interrupted_storage, current_user]
    built = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "继续"},
    ]
    resume = {
        "source": "persisted_provider_truncated",
        "text_tail": "MODEL-PARTIAL",
        "reasoning_tail": "",
        "provider_truncated": True,
        "finish_reason": "length",
    }

    out, info = apply_recent_continuity_suffix(
        built,
        session_messages=session,
        current_turn_ref=2,
        interruption_resume=resume,
    )

    assert info["runtime_fact"] is True
    assert out[0]["role"] == "system"
    assert out[0]["content"] == "SYS"
    assert out[-2] == {"role": "assistant", "content": "MODEL-PARTIAL"}
    assert out[-1]["role"] == "user"
    assert out[-1]["content"].startswith("继续\n\n[provider_runtime_fact—not_human_text]\n")
    assert '"previous_assistant_output_truncated":true' in out[-1]["content"]
    assert '"previous_assistant_output_complete":false' in out[-1]["content"]
    assert '"partial_output_persisted":true' in out[-1]["content"]
    assert '"finish_reason":"length"' in out[-1]["content"]


def test_does_not_reach_past_immediately_previous_human_turn() -> None:
    old_user = _user("OLD-Q")
    old_assistant = _model("OLD-A")
    previous_user = _user("NEW-Q")
    current_user = _user("NEW-DETAIL")
    session = [old_user, old_assistant, previous_user, current_user]
    built = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "NEW-Q"},
        {"role": "user", "content": "NEW-DETAIL"},
    ]

    out, info = apply_recent_continuity_suffix(
        built,
        session_messages=session,
        current_turn_ref=3,
    )

    assert info["source"] == "current_user_only"
    assert all(item.get("content") != "OLD-A" for item in out)
    assert out[-1]["content"] == "NEW-DETAIL"


def test_tool_round_after_current_user_is_never_reordered() -> None:
    """Recent focus is first-build only; assistant(tool_calls)->tool order is authority."""
    previous_user = _user("OLD-Q")
    previous_assistant = _model("OLD-A", resolved=True)
    current_user = _user("查一下")
    tool_decl = Message(
        role="assistant",
        content="",
        source=MessageSource.USER,
        tool_calls=[{"id": "tc-1", "name": "read_file", "arguments": {"path": "x"}}],
        metadata={"answer_origin": "model"},
    )
    tool_result = Message(
        role="tool",
        content="RESULT",
        source=MessageSource.TOOL,
        tool_call_id="tc-1",
        tool_name="read_file",
    )
    session = [previous_user, previous_assistant, current_user, tool_decl, tool_result]
    built = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "查一下"},
        tool_decl.to_llm_dict(),
        tool_result.to_llm_dict(),
    ]

    out, info = apply_recent_continuity_suffix(
        built,
        session_messages=session,
        current_turn_ref=2,
        interruption_resume={
            "source": "open_stream_checkpoint",
            "text_tail": "STALE-PARTIAL",
            "reasoning_tail": "STALE-THINK",
        },
    )

    assert info == {"applied": False, "reason": "turn_already_advanced"}
    assert out == built
    assert out[-2]["role"] == "assistant" and out[-2]["tool_calls"]
    assert out[-1]["role"] == "tool" and out[-1]["tool_call_id"] == "tc-1"



def test_short_continue_keeps_only_immediately_recent_model_context() -> None:
    """“继续”只获得最近交互结构；旧 assistant 任务不得被 recent-continuity 复活。"""
    old_user = _user("处理旧的 fail-closed 补丁")
    old_assistant = _model("下一步建议直接落补丁", resolved=True)
    recent_user = _user("先不动代码，只分析安全边界")
    recent_assistant = _model("我保持只分析。要继续审查这条边界吗？", resolved=True)
    current_user = _user("继续")
    session = [old_user, old_assistant, recent_user, recent_assistant, current_user]
    built = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "继续"},
    ]

    out, info = apply_recent_continuity_suffix(
        built, session_messages=session, current_turn_ref=4
    )

    assert info["source"] == "recent_model_assistant"
    assert out[-2]["role"] == "assistant"
    assert out[-2]["content"] == "我保持只分析。要继续审查这条边界吗？"
    assert out[-1] == {"role": "user", "content": "继续"}
    assert all(item.get("content") != "下一步建议直接落补丁" for item in out)

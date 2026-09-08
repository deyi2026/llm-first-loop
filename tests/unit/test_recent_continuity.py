from __future__ import annotations

from llm_loop.core.message import Message, MessageSource, ToolResultStatus
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

    assert info["source"] == "recent_assistant_only"
    assert info["dialogue_pairs"] == 0
    assert info["assistant_context"] == 1
    assert info["historical_user_messages"] == 0
    assert out[-2] == {"role": "assistant", "content": "你更看重速度还是精度？"}
    assert "reasoning_content" not in out[-2]
    assert out[-1] == {"role": "user", "content": "更看重精度"}
    assert all(item.get("content") != "请判断 A 还是 B" for item in out)


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
    assert {"role": "user", "content": "[program status]"} in out[:-2]
    assert all(item.get("content") != "Q" for item in out)


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


def test_tool_round_keeps_prior_assistant_before_current_user_without_reordering_protocol() -> None:
    """Sticky assistant adjacency preserves prefix while tool protocol keeps native order."""
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

    assert info["source"] == "recent_assistant_sticky"
    assert info["historical_user_messages"] == 0
    assert [item["role"] for item in out] == ["system", "assistant", "user", "assistant", "tool"]
    assert out[1] == {"role": "assistant", "content": "OLD-A"}
    assert out[2] == {"role": "user", "content": "查一下"}
    assert out[-2]["role"] == "assistant" and out[-2]["tool_calls"]
    assert out[-1]["role"] == "tool" and out[-1]["tool_call_id"] == "tc-1"
    assert all(item.get("content") != "STALE-PARTIAL" for item in out)
    assert all("reasoning_content" not in item for item in out if item.get("content") == "OLD-A")



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

    assert info["source"] == "recent_assistant_only"
    assert info["dialogue_pairs"] == 0
    assert info["assistant_context"] == 1
    assert info["historical_user_messages"] == 0
    assert out[-2]["content"] == "我保持只分析。要继续审查这条边界吗？"
    assert out[-1] == {"role": "user", "content": "继续"}
    assert all(item.get("content") != "处理旧的 fail-closed 补丁" for item in out)
    assert all(item.get("content") != "下一步建议直接落补丁" for item in out)
    assert all(item.get("content") != "先不动代码，只分析安全边界" for item in out)


def test_interruption_resume_preserves_provider_native_replay_marker() -> None:
    """Crash recovery must not discard exact provider-native replay already captured."""
    previous_user = _user("inspect")
    current_user = _user("continue")
    session = [previous_user, current_user]
    replay = {
        "provider": "minimax",
        "fields": {
            "reasoning_details": [
                {"type": "reasoning.text", "text": "plan", "signature": "sig-1"}
            ]
        },
    }
    built = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "continue"},
    ]

    out, info = apply_recent_continuity_suffix(
        built,
        session_messages=session,
        current_turn_ref=1,
        interruption_resume={
            "source": "open_stream_checkpoint",
            "text_tail": "MODEL-PARTIAL",
            "reasoning_tail": "plan",
            "provider": "minimax",
            "model": "minimax/MiniMax-M3",
            "provider_replay": replay,
        },
    )

    assert info["source"] == "open_stream_checkpoint"
    assert out[-2]["content"] == "MODEL-PARTIAL"
    assert out[-2]["_provider_replay"] == replay
    assert out[-1] == {"role": "user", "content": "continue"}


def test_attachment_bearing_current_user_keeps_interruption_continuity() -> None:
    """Attachment wire projection must not make the current human structurally invisible."""
    previous_user = _user("inspect")
    current_user = Message(
        role="user",
        content="continue with this file",
        source=MessageSource.USER,
        metadata={
            "attachments": [
                {
                    "ref": "attachment://abc",
                    "filename": "facts.txt",
                    "content_type": "text/plain",
                    "media_type": "text",
                    "size_bytes": 3,
                    "sha256": "abc123",
                    "excerpt_kind": "text",
                    "excerpt": "XYZ",
                }
            ]
        },
    )
    session = [previous_user, current_user]
    current_wire = current_user.to_llm_dict()
    assert current_wire["content"] != current_user.content
    built = [
        {"role": "system", "content": "SYS"},
        current_wire,
    ]

    out, info = apply_recent_continuity_suffix(
        built,
        session_messages=session,
        current_turn_ref=1,
        interruption_resume={
            "source": "open_stream_checkpoint",
            "text_tail": "MODEL-PARTIAL",
            "reasoning_tail": "MODEL-REASONING",
        },
    )

    assert info["source"] == "open_stream_checkpoint"
    assert out[-2] == {
        "role": "assistant",
        "content": "MODEL-PARTIAL",
        "reasoning_content": "MODEL-REASONING",
    }
    assert out[-1] == current_wire
    assert "[attachment_facts]" in out[-1]["content"]


def test_attachment_projection_survives_provider_truncation_runtime_fact() -> None:
    """Ephemeral truncation provenance appends after, never replaces, attachment facts."""
    previous_user = _user("inspect")
    current_user = Message(
        role="user",
        content="continue",
        source=MessageSource.USER,
        metadata={
            "attachments": [
                {
                    "ref": "attachment://abc",
                    "filename": "facts.txt",
                    "content_type": "text/plain",
                    "media_type": "text",
                    "size_bytes": 3,
                    "sha256": "abc123",
                    "excerpt_kind": "text",
                    "excerpt": "XYZ",
                }
            ]
        },
    )
    current_wire = current_user.to_llm_dict()
    out, info = apply_recent_continuity_suffix(
        [{"role": "system", "content": "SYS"}, current_wire],
        session_messages=[previous_user, current_user],
        current_turn_ref=1,
        interruption_resume={
            "source": "persisted_provider_truncated",
            "text_tail": "PARTIAL",
            "reasoning_tail": "",
            "provider_truncated": True,
            "finish_reason": "length",
        },
    )

    assert info["runtime_fact"] is True
    assert out[-2] == {"role": "assistant", "content": "PARTIAL"}
    assert out[-1]["content"].startswith(current_wire["content"])
    assert "[attachment_facts]" in out[-1]["content"]
    assert "[provider_runtime_fact—not_human_text]" in out[-1]["content"]
    assert current_user.content == "continue"


def test_current_turn_capability_fact_does_not_hide_current_human_identity() -> None:
    """Known factual wire suffixes do not replace the durable human-message identity."""
    previous_user = _user("inspect")
    current_user = _user("continue")
    current_wire = current_user.to_llm_dict()
    current_wire["content"] += (
        "\n[能力边界事实]\n"
        "tool=browser_exec; available=false; reason=runtime_unhealthy"
    )

    out, info = apply_recent_continuity_suffix(
        [{"role": "system", "content": "SYS"}, current_wire],
        session_messages=[previous_user, current_user],
        current_turn_ref=1,
        interruption_resume={
            "source": "open_stream_checkpoint",
            "text_tail": "PARTIAL",
            "reasoning_tail": "",
        },
    )

    assert info["source"] == "open_stream_checkpoint"
    assert out[-2] == {"role": "assistant", "content": "PARTIAL"}
    assert out[-1] == current_wire


def test_failure_then_retry_tool_protocol_is_never_reordered_by_recent_continuity() -> None:
    """Failure+retry protocol order is storage/wire truth once the current turn advanced."""
    from llm_loop.core.history import validate_tool_call_pairing

    previous_user = _user("old")
    current_user = _user("inspect")
    first_decl = Message(
        role="assistant",
        content="",
        source=MessageSource.USER,
        tool_calls=[
            {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
        ],
        metadata={"answer_origin": "model"},
    )
    failed = Message(
        role="tool",
        content="TOOL_ERROR: FileNotFoundError",
        source=MessageSource.TOOL,
        tool_call_id="c1",
        tool_name="read_file",
        status=ToolResultStatus.FAILURE,
    )
    retry_decl = Message(
        role="assistant",
        content="",
        source=MessageSource.USER,
        tool_calls=[
            {"id": "c2", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
        ],
        metadata={"answer_origin": "model"},
    )
    success = Message(
        role="tool",
        content="OK",
        source=MessageSource.TOOL,
        tool_call_id="c2",
        tool_name="read_file",
        status=ToolResultStatus.SUCCESS,
    )
    session = [previous_user, current_user, first_decl, failed, retry_decl, success]
    built = [
        {"role": "system", "content": "SYS"},
        current_user.to_llm_dict(),
        first_decl.to_llm_dict(),
        failed.to_llm_dict(),
        retry_decl.to_llm_dict(),
        success.to_llm_dict(),
    ]

    out, info = apply_recent_continuity_suffix(
        built,
        session_messages=session,
        current_turn_ref=1,
        interruption_resume={
            "source": "open_stream_checkpoint",
            "text_tail": "STALE",
            "reasoning_tail": "",
        },
    )

    assert info == {"applied": False, "reason": "turn_already_advanced"}
    assert out == built
    assert validate_tool_call_pairing(out) == []
    assert [row.get("tool_call_id") for row in out if row.get("role") == "tool"] == ["c1", "c2"]


def test_recent_continuity_does_not_repromote_older_human_tasks_for_cross_turn_reference() -> None:
    """Older resolved human text stays retrieval-only; only adjacent assistant is rehydrated."""
    url_user = _user("https://example.test/context-layer")
    url_assistant = _model("这篇文章讲的是 Context Layer。", resolved=True)
    analysis_user = _user("是的，你分析这个技术的可行性。")
    analysis_assistant = _model("Context Layer 技术整体可行，核心是缓存、合并与上下文裁剪。", resolved=True)
    compare_user = _user("和我们项目的技术相比呢？")
    compare_assistant = _model("我需要先了解你们项目。", resolved=True)
    agent_user = _user("你现在在用的这个 AI Agent 架构啊。")
    agent_assistant = _model("当前是 LFL Agent 架构。", resolved=True)
    current_user = _user("我们的这个上下文管理和他的项目比较。")
    session = [
        url_user,
        url_assistant,
        analysis_user,
        analysis_assistant,
        compare_user,
        compare_assistant,
        agent_user,
        agent_assistant,
        current_user,
    ]
    # Resolved-episode projection has retired every completed pair.
    built = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": current_user.content},
    ]

    out, info = apply_recent_continuity_suffix(
        built,
        session_messages=session,
        current_turn_ref=8,
    )

    assert info["dialogue_pairs"] == 0
    assert info["assistant_context"] == 1
    assert info["historical_user_messages"] == 0
    contents = [item.get("content") for item in out]
    for historical_user in (url_user, analysis_user, compare_user, agent_user):
        assert historical_user.content not in contents
    assert url_assistant.content not in contents
    assert analysis_assistant.content not in contents
    assert compare_assistant.content not in contents
    assert agent_assistant.content in contents
    assert out[-2] == {"role": "assistant", "content": agent_assistant.content}
    assert out[-1] == {"role": "user", "content": current_user.content}


def test_recent_assistant_projection_keeps_only_latest_answer_under_char_budget() -> None:
    old_user = _user("OLD-U-" + "x" * 20000)
    old_assistant = _model("OLD-A-" + "y" * 20000, resolved=True)
    recent_user = _user("RECENT-U")
    recent_assistant = _model("RECENT-A", resolved=True)
    current_user = _user("CURRENT")
    session = [old_user, old_assistant, recent_user, recent_assistant, current_user]
    built = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "CURRENT"}]

    out, info = apply_recent_continuity_suffix(
        built, session_messages=session, current_turn_ref=4
    )

    assert info["dialogue_pairs"] == 0
    assert info["assistant_context"] == 1
    contents = [item.get("content") for item in out]
    assert "RECENT-U" not in contents
    assert "RECENT-A" in contents
    assert old_user.content not in contents
    assert old_assistant.content not in contents


def test_unresolved_human_turn_blocks_reaching_older_completed_dialogue() -> None:
    old_user = _user("OLD-Q")
    old_assistant = _model("OLD-A", resolved=True)
    unresolved_user = _user("UNRESOLVED-Q")
    current_user = _user("CURRENT-Q")
    session = [old_user, old_assistant, unresolved_user, current_user]
    built = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "CURRENT-Q"}]

    out, info = apply_recent_continuity_suffix(
        built, session_messages=session, current_turn_ref=3
    )

    assert info["dialogue_pairs"] == 0
    assert info["source"] == "current_user_only"
    assert all(item.get("content") not in {"OLD-Q", "OLD-A"} for item in out)


def test_resolved_human_task_is_not_repromoted_in_swarmforge_followup() -> None:
    """Regression: a short SwarmForge follow-up must not resurrect old llama tasks."""
    health_user = _user("做下健康检查，你看看要检查哪些纬度")
    health_assistant = _model("健康检查完成。llama.cpp 已安装。", resolved=True)
    link_user = _user("https://example.test/swarmforge")
    wrong_link_assistant = _model("检查完了，llama 已经装好了。", resolved=True)
    correction_user = _user("跟前面没关系，你单独分析这个头条链接内容。")
    analysis_assistant = _model(
        "SwarmForge 是多 Agent 编排平台。需要的话，我可以核实 GitHub 作者和许可证。",
        reasoning="OLD-HIDDEN-REASONING",
        resolved=True,
    )
    current_user = _user("需要")
    session = [
        health_user, health_assistant, link_user, wrong_link_assistant,
        correction_user, analysis_assistant, current_user,
    ]
    built = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "需要"}]

    out, info = apply_recent_continuity_suffix(
        built, session_messages=session, current_turn_ref=6
    )

    assert info["source"] == "recent_assistant_only"
    assert info["historical_user_messages"] == 0
    assert out[-2] == {
        "role": "assistant",
        "content": analysis_assistant.content,
    }
    assert "reasoning_content" not in out[-2]
    assert out[-1] == {"role": "user", "content": "需要"}
    visible = "\n".join(str(item.get("content") or "") for item in out)
    assert "做下健康检查" not in visible
    assert "跟前面没关系" not in visible
    assert "https://example.test/swarmforge" not in visible
    assert "OLD-HIDDEN-REASONING" not in visible

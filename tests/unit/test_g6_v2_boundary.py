"""P1-B factual capability-boundary and schema-discovery behavior."""

from __future__ import annotations

from llm_loop.core.message import Message, MessageSource, ToolCall, ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_session_id


def _assistant_declaration(tc: ToolCall) -> Message:
    return Message(
        role="assistant",
        content="",
        source=MessageSource.SYSTEM,
        tool_calls=[
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": "{}"},
            }
        ],
    )


def test_unavailable_fact_is_current_turn_only(build_test_engine, monkeypatch):
    import llm_loop.tools.eligibility as eligibility
    from llm_loop.tools.eligibility import ToolHealth

    engine, _ = build_test_engine([{"content": "unused"}])
    monkeypatch.setattr(
        eligibility,
        "runtime_tool_health",
        lambda name: (
            ToolHealth(
                state="quarantined", reason_code="test_missing", preferred_next=("execute_command",)
            )
            if name == "spawn_subagent"
            else ToolHealth(state="ready")
        ),
    )
    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.messages.append(Message(role="user", content="第一话轮", source=MessageSource.USER))
    ref = 0
    tc = ToolCall(id="call_g6", name="read_file", arguments={"path": "x"})
    sess.messages.append(_assistant_declaration(tc))
    result = ToolResult(
        status=ToolResultStatus.SUCCESS,
        content="producer",
        tool_call_id=tc.id,
        tool_name=tc.name,
        capability_requirements=("spawn_subagent",),
    )
    tok = current_session_id.set(sid)
    try:
        engine._run_state().current_turn_ref = ref
        engine._tool_cycle._record_single_receipt(sess, tc, result, [], round_index=1)
        stored = sess.messages[-1]
        assert "能力边界事实" not in stored.content
        wire1 = engine._build_llm_messages(sess, [], max_chars=200000, planned_label="fake-model")
        assert (
            "[能力边界事实]" in next(m for m in wire1 if m.get("tool_call_id") == tc.id)["content"]
        )
        sess.messages.append(
            Message(role="assistant", content="旧轮完成", source=MessageSource.SYSTEM)
        )
        sess.messages.append(Message(role="user", content="第二话轮", source=MessageSource.USER))
        engine._run_state().current_turn_ref = len(sess.messages) - 1
        wire2 = engine._build_llm_messages(sess, [], max_chars=200000, planned_label="fake-model")
        assert (
            "能力边界事实"
            not in next(m for m in wire2 if m.get("tool_call_id") == tc.id)["content"]
        )
    finally:
        current_session_id.reset(tok)


def test_exact_schema_lookup_does_not_change_provider_surface(build_test_engine, monkeypatch):
    import llm_loop.tools.eligibility as eligibility
    from llm_loop.tools.eligibility import ToolHealth

    monkeypatch.setattr(eligibility, "runtime_tool_health", lambda _name: ToolHealth(state="ready"))
    from llm_loop.tools.registry import GetToolSchemaTool

    engine, _ = build_test_engine([{"content": "unused"}])
    if "get_tool_schema" not in engine.registry.names():
        engine.registry.register(GetToolSchemaTool(engine.registry))
    sid = engine.session.create()
    tok = current_session_id.set(sid)
    try:
        schemas = engine.registry.schemas()
        before = engine._tool_cycle._project_tool_schemas_for_round(
            schemas, planned_label="x", user_text="继续", session_messages=[], logical_round=1
        )
        lookup = engine.registry.get("get_tool_schema").execute(tool_name="spawn_subagent")
        assert lookup.status is ToolResultStatus.SUCCESS
        assert not hasattr(lookup, "promotion_signal")
        after = engine._tool_cycle._project_tool_schemas_for_round(
            schemas, planned_label="x", user_text="继续", session_messages=[], logical_round=2
        )
        assert [r["name"] for r in before] == [r["name"] for r in after]
    finally:
        current_session_id.reset(tok)


def test_boundary_bytes_count_in_history_budget():
    from llm_loop.core.history import _capability_boundary_block, _wire_size

    msg = Message(
        role="tool",
        content="tool-result",
        source=MessageSource.TOOL,
        tool_call_id="call_budget",
        tool_name="read_file",
        metadata={
            "capability_boundary_turn_ref": 7,
            "capability_unavailable": [
                {
                    "tool_name": "playwright_exec",
                    "reason_code": "missing_runtime",
                    "replacement": ["web_search", "web_fetch"],
                }
            ],
        },
    )
    base = _wire_size(msg, current_turn_ref=None)
    block = _capability_boundary_block(msg, 7)
    assert block.startswith("\n[能力边界事实]")
    assert _wire_size(msg, current_turn_ref=7) == base + len(block)
    assert _wire_size(msg, current_turn_ref=8) == base

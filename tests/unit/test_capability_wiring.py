"""P1-B production wiring: stable tools + factual boundaries."""

from __future__ import annotations

from dataclasses import dataclass

from llm_loop.core.message import Message, MessageSource, ToolCall, ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_session_id, current_tool_discovery_scope
from llm_loop.tools.eligibility import ToolHealth
from llm_loop.tools.registry import GetToolSchemaTool, ToolRegistry


@dataclass
class _Tool:
    name: str

    @property
    def description(self):
        return self.name

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return ToolResult(
            status=ToolResultStatus.SUCCESS, content="ok", tool_call_id="", tool_name=self.name
        )


def _wire_names(fake):
    return [t["function"]["name"] for t in fake.calls[-1]["tools"]]


def test_current_user_cancel_words_do_not_programmatically_select_tools(
    build_test_engine, monkeypatch
):
    import llm_loop.tools.eligibility as eligibility

    monkeypatch.setattr(eligibility, "runtime_tool_health", lambda _name: ToolHealth(state="ready"))
    engine, fake = build_test_engine([{"content": "a"}, {"content": "b"}])
    for name in ("job_output", "job_kill", "schedule_cancel"):
        if name not in engine.registry.names():
            engine.registry.register(_Tool(name))
    sid = engine.session.create()
    engine.run(sid, "普通问题")
    before = _wire_names(fake)
    engine.run(sid, "取消后台任务")
    after = _wire_names(fake)
    assert after == before
    assert "job_kill" in after


def test_receipt_capability_fact_does_not_mutate_next_surface(build_test_engine, monkeypatch):
    import llm_loop.tools.eligibility as eligibility

    monkeypatch.setattr(eligibility, "runtime_tool_health", lambda _name: ToolHealth(state="ready"))
    engine, _ = build_test_engine([{"content": "unused"}])
    if "job_output" not in engine.registry.names():
        engine.registry.register(_Tool("job_output"))
    sid = engine.session.create()
    sess = engine.session.load(sid)
    schemas = engine.registry.schemas()
    first = engine._tool_cycle._project_tool_schemas_for_round(
        schemas, planned_label="x", user_text="x", session_messages=sess.messages, logical_round=1
    )
    tc = ToolCall(id="c1", name="read_file", arguments={"path": "x"})
    sess.messages.append(
        Message(
            role="assistant",
            content="",
            source=MessageSource.SYSTEM,
            tool_calls=[
                {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": "{}"}}
            ],
        )
    )
    result = ToolResult(
        status=ToolResultStatus.SUCCESS,
        content="producer",
        tool_call_id=tc.id,
        tool_name=tc.name,
        capability_requirements=("job_output",),
    )
    tok = current_session_id.set(sid)
    try:
        engine._run_state().current_turn_ref = 0
        engine._tool_cycle._record_single_receipt(sess, tc, result, [], round_index=1)
    finally:
        current_session_id.reset(tok)
    second = engine._tool_cycle._project_tool_schemas_for_round(
        schemas,
        planned_label="x",
        user_text="继续",
        session_messages=sess.messages,
        logical_round=2,
    )
    assert [r["name"] for r in first] == [r["name"] for r in second]


def test_explicit_discovery_scope_remains_a_real_delegation_boundary():
    reg = ToolRegistry()
    reg.register(_Tool("a"))
    reg.register(_Tool("b"))
    schema = GetToolSchemaTool(reg)
    token = current_tool_discovery_scope.set(frozenset({"a"}))
    try:
        catalog = schema.execute(tool_name="*")
        assert "- a [ready]" in catalog.content
        assert "- b [ready]" not in catalog.content
        denied = schema.execute(tool_name="b")
        assert denied.status is ToolResultStatus.FAILURE
        assert "当前执行域不可用" in denied.content
    finally:
        current_tool_discovery_scope.reset(token)


def test_runtime_unhealthy_receipt_requirement_renders_factual_boundary(
    build_test_engine, monkeypatch
):
    import llm_loop.tools.eligibility as eligibility

    engine, _ = build_test_engine([{"content": "unused"}])

    def health(name):
        if name == "spawn_subagent":
            return ToolHealth(
                state="quarantined", reason_code="missing", preferred_next=("execute_command",)
            )
        return ToolHealth(state="ready")

    monkeypatch.setattr(eligibility, "runtime_tool_health", health)
    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.messages.append(Message(role="user", content="u", source=MessageSource.USER))
    tc = ToolCall(id="c", name="read_file", arguments={"path": "x"})
    sess.messages.append(
        Message(
            role="assistant",
            content="",
            source=MessageSource.SYSTEM,
            tool_calls=[
                {
                    "id": "c",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        )
    )
    result = ToolResult(
        status=ToolResultStatus.SUCCESS,
        content="producer",
        tool_call_id="c",
        tool_name="read_file",
        capability_requirements=("spawn_subagent",),
    )
    tok = current_session_id.set(sid)
    try:
        engine._run_state().current_turn_ref = 0
        engine._tool_cycle._record_single_receipt(sess, tc, result, [], round_index=1)
        stored = sess.messages[-1]
        assert stored.metadata["capability_unavailable"][0]["tool_name"] == "spawn_subagent"
        wire = engine._build_llm_messages(sess, [], max_chars=200000, planned_label="fake-model")
        tool_wire = next(m for m in wire if m.get("tool_call_id") == "c")
        assert "[能力边界事实]" in tool_wire["content"]
        assert "available=false" in tool_wire["content"]
    finally:
        current_session_id.reset(tok)

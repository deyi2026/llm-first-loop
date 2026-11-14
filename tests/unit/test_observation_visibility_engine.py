"""End-to-end FakeLLM safety: legitimate changing observations are not stopped."""

from __future__ import annotations

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus


class _ChangingStatusProbe:
    name = "changing_status_probe"
    description = "Read a changing in-memory status; no external effects."
    parameters = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.executions = 0

    def execute(self, **_kwargs) -> ToolResult:
        self.executions += 1
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"status_version={self.executions}",
            tool_call_id="",
            tool_name=self.name,
        )


def test_legitimate_same_argument_polling_with_new_versions_still_proceeds(build_test_engine):
    engine, fake = build_test_engine(
        [
            {"tool_calls": [ToolCall(id="poll-1", name="changing_status_probe", arguments={})]},
            {"tool_calls": [ToolCall(id="poll-2", name="changing_status_probe", arguments={})]},
            {"content": "状态变化已确认"},
        ]
    )
    probe = _ChangingStatusProbe()
    engine.registry.register(probe)
    sid = engine.session.create()
    result = engine.run(sid, "请连续观察两次状态变化")
    assert result.final_answer == "状态变化已确认"
    assert result.run_incomplete is False
    assert probe.executions == 2
    assert len(fake.calls) == 3
    assert any(
        m.get("role") == "tool" and "status_version=1" in str(m.get("content"))
        for m in fake.calls[1]["messages"]
    )
    assert any(
        m.get("role") == "tool" and "status_version=2" in str(m.get("content"))
        for m in fake.calls[2]["messages"]
    )

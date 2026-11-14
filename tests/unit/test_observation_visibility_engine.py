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


def test_guard_internal_fault_blocks_provider_and_marks_run_incomplete(
    build_test_engine, tmp_path, monkeypatch
):
    source = tmp_path / "large-observation.txt"
    source.write_text("unique-observation\n" + "content-" * 800, encoding="utf-8")
    engine, fake = build_test_engine(
        [
            {"tool_calls": [ToolCall(id="fault-1", name="read_file", arguments={"path": str(source)})]},
            {"content": "must not be emitted"},
        ]
    )
    object.__setattr__(engine.settings, "history_max_chars", 300)

    def _raise_during_rebuild(*_args, **_kwargs):
        raise RuntimeError("synthetic read-only projection fault")

    monkeypatch.setattr(engine, "_build_conservative_active_run_messages", _raise_during_rebuild)
    result = engine.run(engine.session.create(), "读取后必须依据真实回执回答")
    assert len(fake.calls) == 1, "guard failure must block second provider attempt"
    assert result.run_incomplete is True
    assert "observation_guard_fault" in result.final_answer
    assert "provider_sent=false" in result.final_answer

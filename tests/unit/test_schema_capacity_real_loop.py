"""A real LoopEngine must not starve a 32K model with 101 tool schemas.

Fake Provider, temporary source file, no network or external model call.
"""

from __future__ import annotations

from llm_loop.core.message import ToolCall
from llm_loop.event_log.store import EventStore
from llm_loop.tools.eligibility import runtime_tool_health
from llm_loop.tools.registry import GetToolSchemaTool


class _InertTool:
    description = "schema only"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, name: str) -> None:
        self.name = name

    def execute(self, **_kwargs):
        raise AssertionError("schema-only tool must never execute")


def test_real_loop_recovers_after_large_observation_with_101_tools(
    build_test_engine, tmp_path, monkeypatch
):
    source = tmp_path / "source.txt"
    source.write_text("TOOL_OBSERVATION_" + "a" * 5120, encoding="utf-8")
    engine, fake = build_test_engine([
        {"tool_calls": [ToolCall(id="capacity-1", name="read_file", arguments={"path": str(source)})]},
        {"content": "verified completion"},
    ])
    if "get_tool_schema" not in engine.registry.names():
        engine.registry.register(GetToolSchemaTool(engine.registry))
    eligible = [
        row for row in engine.registry.schemas(lazy=engine.settings.tool_schema_lazy)
        if row["name"] != "convergence_decide" and runtime_tool_health(row["name"]).available
    ]
    for i in range(101 - len(eligible)):
        engine.registry.register(_InertTool(f"schema_padding_{i:03d}"))
    fake.max_tokens = 32768

    def tokenizer(tools):
        # Reproduce authoritative 28,863-token large schema surface. A genuine
        # whole-surface index has no inline parameter properties and costs less.
        if any((row.get("function") or {}).get("parameters", {}).get("properties") for row in tools):
            return 28863
        return 4000

    fake.count_tool_schema_tokens = tokenizer
    monkeypatch.setattr(engine, "_effective_history_budget", lambda *_a, **_kw: 79979)
    monkeypatch.setattr(
        engine, "_effective_history_budget_detail",
        lambda *_a, **_kw: {
            "allowed_input_tokens": 32768,
            "projection_chars_per_token": 0.9,
            "effective_budget": 79979,
            "limited_by": "model_window",
        },
    )
    engine._event_store = EventStore(tmp_path / "events", enabled=True)
    sid = engine.session.create()
    result = engine.run(sid, "Read the source once, then report")
    assert result.final_answer == "verified completion"
    assert result.run_incomplete is False
    assert len(fake.calls) == 2
    names = [[row["function"]["name"] for row in call["tools"]] for call in fake.calls]
    assert len(names[0]) == len(names[1]) == 101
    assert names[0] == names[1]
    assert "get_tool_schema" in names[0]
    assert all(row["function"]["parameters"] == {"type": "object"} for row in fake.calls[0]["tools"])
    second_observations = [
        row["content"] for row in fake.calls[1]["messages"] if row.get("role") == "tool"
    ]
    assert any("TOOL_OBSERVATION_" in text and len(text) >= 5130 for text in second_observations)
    events = engine._event_store.read_cached(sid)
    assert sum(event.type == "tool.execution.finished" for event in events) == 1
    assert any(
        event.type == "request.schema_capacity"
        and event.payload.get("mode") == "index_80"
        and event.payload.get("original_schema_tokens") == 28863
        and event.payload.get("selected_schema_tokens") == 4000
        for event in events
    )

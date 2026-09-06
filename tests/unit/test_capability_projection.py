"""P1-B stable tool-surface projection tests."""

from __future__ import annotations

from dataclasses import dataclass

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.tools.eligibility import ToolHealth


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


def _names(rows):
    return [str(row.get("name", "")) for row in rows]


def test_projection_is_independent_of_user_text_and_history(build_test_engine, monkeypatch):
    import llm_loop.tools.eligibility as eligibility

    monkeypatch.setattr(eligibility, "runtime_tool_health", lambda _name: ToolHealth(state="ready"))
    engine, _ = build_test_engine([{"content": "unused"}])
    for name in ("web_fetch", "schedule", "job_kill"):
        if name not in engine.registry.names():
            engine.registry.register(_Tool(name))
    schemas = engine.registry.schemas(lazy=engine.settings.tool_schema_lazy)
    a = engine._tool_cycle._project_tool_schemas_for_round(
        schemas, planned_label="model-a", user_text="本地写作", session_messages=[], logical_round=1
    )
    b = engine._tool_cycle._project_tool_schemas_for_round(
        schemas,
        planned_label="model-b",
        user_text="取消后台任务并抓网页",
        session_messages=[
            {"role": "tool", "metadata": {"tool_recovery": {"preferred_next": ["schedule"]}}}
        ],
        logical_round=2,
    )
    assert _names(a) == _names(b) == _names(schemas)


def test_projection_only_removes_runtime_unhealthy(build_test_engine, monkeypatch):
    import llm_loop.tools.eligibility as eligibility

    engine, _ = build_test_engine([{"content": "unused"}])
    engine.registry.register(_Tool("a_ready"))
    engine.registry.register(_Tool("b_bad"))

    def health(name):
        return (
            ToolHealth(state="quarantined", reason_code="missing")
            if name == "b_bad"
            else ToolHealth(state="ready")
        )

    monkeypatch.setattr(eligibility, "runtime_tool_health", health)
    schemas = engine.registry.schemas()
    out = engine._tool_cycle._project_tool_schemas_for_round(
        schemas, planned_label="x", user_text="b_bad", session_messages=[], logical_round=1
    )
    assert "a_ready" in _names(out)
    assert "b_bad" not in _names(out)
    assert engine._tool_cycle._last_tool_eligibility["quarantined_names"] == ["b_bad"]

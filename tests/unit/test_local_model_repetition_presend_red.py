"""Incident-budget pre-send RED: a completed tool observation cannot disappear.

No real Provider is called. FakeLLM captures the exact messages/tools that the
current LoopEngine hands to its client on the next logical round. This is a
code-level test, not a reconstruction of historical HTTP request bytes.
"""

from __future__ import annotations

import json

from llm_loop.core.loop.engine_services.routing import RoutingService
from llm_loop.core.message import ToolCall


class _InertSchemaTool:
    description = "Offline schema reservation probe; never executed."
    parameters = {"type": "object", "properties": {}}

    def __init__(self, name: str) -> None:
        self.name = name

    def execute(self, **_kwargs):
        raise AssertionError("schema-only tool must never be executed")


def _install_incident_budget(engine, fake, monkeypatch) -> None:
    """Exact incident budget bridge, while retaining real reservation code."""
    from llm_loop.tools.eligibility import runtime_tool_health

    existing = [
        row for row in engine.registry.schemas(lazy=engine.settings.tool_schema_lazy)
        if row["name"] != "convergence_decide" and runtime_tool_health(row["name"]).available
    ]
    assert len(existing) < 101
    for i in range(101 - len(existing)):
        engine.registry.register(_InertSchemaTool(f"incident_schema_{i:03d}"))
    projected = [
        row for row in engine.registry.schemas(lazy=engine.settings.tool_schema_lazy)
        if row["name"] != "convergence_decide" and runtime_tool_health(row["name"]).available
    ]
    assert len(projected) == 101

    # Authoritative tokenizer observation from frozen incident EventLog. This
    # does NOT claim the synthetic schemas are the historical 101 schemas.
    fake.max_tokens = 32768
    fake.count_tool_schema_tokens = lambda tools: (
        28659 if len(tools) == 101 else -1
    )
    budget = {
        "allowed_input_tokens": 32768,
        "projection_chars_per_token": 0.9,
        "projection_density_source": "configured_fallback",
        "projection_density_samples": 0,
        "effective_budget": 79979,
        "limited_by": "model_window",
    }
    monkeypatch.setattr(engine, "_effective_history_budget", lambda *_a, **_k: 79979)
    monkeypatch.setattr(
        engine, "_effective_history_budget_detail", lambda *_a, **_k: dict(budget)
    )
    # Avoid test-specific safety-fuse behavior substituting for actual visibility.
    object.__setattr__(engine.settings, "max_iterations", 3)


def test_incident_65536_32768_101_tools_reserves_3698_chars():
    budget = {"allowed_input_tokens": 32768, "projection_chars_per_token": 0.9}
    projected = RoutingService.reserve_tool_schema_from_history_budget(
        79979, budget, 85949, tool_schema_tokens=28659
    )
    assert projected == 3698
    assert budget["tool_schema_reserve_tokens"] == 28659
    assert budget["effective_history_budget_tokens"] == 4109
    assert budget["tool_schema_reserve_source"] == "authoritative_tokenizer"


def test_completed_tool_exchange_must_be_visible_or_second_send_blocked(
    build_test_engine, tmp_path, monkeypatch
):
    """RED: first real read is archived, but its complete result is not delivered.

    GREEN requires either a complete paired assistant->tool exchange in the
    second provider view, an independently verified model-visible exact-ref,
    or an explicit pre-send HOLD. In this fixture no exact-ref is provisioned.
    """
    marker = "INCIDENT_UNIQUE_OBSERVATION_9f78"
    source = tmp_path / "incident-observation.txt"
    source.write_text(marker + "\n" + ("payload-" * 800), encoding="utf-8")
    tool_id = "incident-call-001"
    engine, fake = build_test_engine(
        [
            {"tool_calls": [ToolCall(id=tool_id, name="read_file", arguments={"path": str(source)})]},
            {"content": "I can now proceed."},
        ]
    )
    _install_incident_budget(engine, fake, monkeypatch)
    projected_budgets: list[int | None] = []
    original_build = engine._build_llm_messages

    def _record_real_build(*args, **kwargs):
        projected_budgets.append(kwargs.get("max_chars"))
        return original_build(*args, **kwargs)

    monkeypatch.setattr(engine, "_build_llm_messages", _record_real_build)

    sid = engine.session.create()
    result = engine.run(sid, "请读取指定文件并依据实际内容作答")
    saved = engine.session.load(sid)
    tool_messages = [
        m for m in saved.messages if m.role == "tool" and m.tool_call_id == tool_id
    ]
    assert len(tool_messages) == 1, "real read must complete exactly once"
    assert marker in tool_messages[0].content, "the original observation must be durable"
    assert len(tool_messages[0].content) > 3698, "fixture must actually force compaction"
    assert fake.calls, "first Provider call must be simulated"
    assert len(fake.calls[0]["tools"]) == 101
    assert len(projected_budgets) >= 2
    assert projected_budgets[0] == projected_budgets[1] == 3698

    if len(fake.calls) == 1:
        # A pre-send HOLD is acceptable, but not a fake success or silent stop.
        assert "context_capacity_unavailable" in result.final_answer
        assert "provider_sent=false" in result.final_answer
        return

    assert len(fake.calls) == 2, "unexpected extra provider attempt"
    second = fake.calls[1]["messages"]
    assert len(fake.calls[1]["tools"]) == 101
    assert not any("evidence://" in json.dumps(m, ensure_ascii=False) for m in second), (
        "this fixture has no owner-scoped exact-ref; if one appears, its authority "
        "must be tested instead of assuming visibility"
    )
    # The source tool result is not a mere hint; a paired exact exchange is
    # required unless a verified owner-scoped evidence ref was projected.
    has_tool = any(
        m.get("role") == "tool"
        and m.get("tool_call_id") == tool_id
        and marker in str(m.get("content", ""))
        for m in second
    )
    has_call = any(
        m.get("role") == "assistant"
        and any(
            (tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)) == tool_id
            for tc in m.get("tool_calls", [])
        )
        for m in second
    )
    assert has_tool and has_call, (
        "RED: completed tool exchange disappeared from second Provider view; "
        "no authorized exact-ref is provisioned in this fixture, so send must HOLD"
    )

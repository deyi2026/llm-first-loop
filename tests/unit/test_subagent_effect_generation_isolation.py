"""Subagent effect tools must not inherit the parent run generation.

Production repro (2026-10-14): the web runtime seeds ``current_run_generation``
for the parent run (BackgroundRunner). ``spawn_subagent`` workers copy that
context, so every child tool binding carried ``origin_run_generation=<parent>``
while ``run_generation_authority`` looks the generation up for the **child**
session id (never registered) -> ``"" != parent`` -> every effect tool
(execute_command et al.) returned unauthorized with a misleading
"run lease fenced" message. Disk lease truth stayed perfectly healthy
(acquire -> renew -> settle completed).

Contract: child sessions do not participate in the parent run-generation CAS;
their effect authority is the R1 fleet lease fence. The tests below simulate
the production contextvar state (non-empty parent generation) which the
existing fleet tests never covered (they run with the default empty
generation, which is why they stayed green).
"""

from __future__ import annotations

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_run_generation, current_session_id
from llm_loop.core.session import SessionStore
from llm_loop.core.tool_execution_journal import current_effect_mutation_authority
from llm_loop.event_log.store import EventStore
from llm_loop.fleet.coordinator import ProjectCoordinator
from llm_loop.llm.client import LLMResponse
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.registry import ToolRegistry


def _coordinator(tmp_path, owner="parent-1") -> ProjectCoordinator:
    return ProjectCoordinator(
        fleet_dir=tmp_path / "fleet",
        project_id="proj-1",
        physical_root=str(tmp_path / "proj"),
        repo_head="abc123",
        owner_id=owner,
    )


def _runner(tmp_path, llm, coordinator) -> SubAgentRunner:
    events = EventStore(tmp_path / "events", enabled=True)
    store = SessionStore(tmp_path / "sessions", event_store=events)
    return SubAgentRunner(  # type: ignore[arg-type]
        llm=llm,
        registry=ToolRegistry(),
        session_store=store,
        project_coordinator=coordinator,
        fleet_lease_ttl_seconds=300.0,
    )


class _SeqLLM:
    def __init__(self, responses) -> None:
        self._responses = list(responses)

    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        if not self._responses:
            return LLMResponse(content="done", tool_calls=[], provider="fake")
        return self._responses.pop(0)


class _EffectProbeTool:
    """Effect-aware probe: mirrors what execute_command does before mutating."""

    name = "effect_probe"
    description = "probe effect mutation authority"

    def __init__(self, seen: dict) -> None:
        self._seen = seen

    def execute(self, **kwargs):  # noqa: ANN003
        with current_effect_mutation_authority() as allowed:
            self._seen["allowed"] = bool(allowed)
            return ToolResult(
                status=ToolResultStatus.SUCCESS if allowed else ToolResultStatus.UNAUTHORIZED,
                content=f"allowed={allowed}",
                tool_call_id="",
                tool_name=self.name,
            )


def _run_parent_with_generation(runner, task: str, generation: str):
    """Simulate production: parent run has a seeded run generation."""
    tok_s = current_session_id.set("parent-run-1")
    tok_g = current_run_generation.set(generation)
    try:
        return runner.run(task, depth=0)
    finally:
        current_run_generation.reset(tok_g)
        current_session_id.reset(tok_s)


def test_child_effect_tool_allowed_under_parent_run_generation(tmp_path) -> None:
    coord = _coordinator(tmp_path)
    seen: dict = {}
    llm = _SeqLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="c1", name="effect_probe", arguments={})],
                provider="fake",
            ),
            LLMResponse(content="done", tool_calls=[], provider="fake"),
        ]
    )
    runner = _runner(tmp_path, llm, coordinator=coord)
    runner.registry.register(_EffectProbeTool(seen))

    result = _run_parent_with_generation(runner, "child with effect tool", "parent-gen-1")

    assert result.outcome == "completed", "generation mismatch must not stop the run"
    assert seen.get("allowed") is True, (
        "effect tools in the child must not inherit the parent run generation: "
        "run_generation_authority would look up the generation for the child "
        "session id (never registered) and refuse every mutation"
    )


def test_child_effect_tool_allowed_with_empty_generation(tmp_path) -> None:
    """Legacy/direct path (empty generation) keeps the pre-existing behaviour."""
    coord = _coordinator(tmp_path)
    seen: dict = {}
    llm = _SeqLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="c1", name="effect_probe", arguments={})],
                provider="fake",
            ),
            LLMResponse(content="done", tool_calls=[], provider="fake"),
        ]
    )
    runner = _runner(tmp_path, llm, coordinator=coord)
    runner.registry.register(_EffectProbeTool(seen))

    result = _run_parent_with_generation(runner, "child with effect tool", "")

    assert result.outcome == "completed"
    assert seen.get("allowed") is True

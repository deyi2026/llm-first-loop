"""Deterministic fake-only qualification for P4-LIVE G2-S5 scope enforcement."""

from __future__ import annotations

from contextvars import Context
from dataclasses import dataclass

from evals.smc_semantic_logic_p4_live.green2_s5_red_contracts import (
    exact_canary_scope,
    probe_canary_scope_authority,
    probe_discovery,
    probe_execution,
    probe_provider_projection,
)
from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_tool_discovery_scope
from llm_loop.tools.p4_live_scope import (
    P4_LIVE_CANARY_TOOL_SCOPE,
    p4_live_canary_tool_scope,
)
from llm_loop.tools.registry import GetToolSchemaTool, ToolRegistry

LEGACY_BROWSER_MUTATIONS = {
    "browser_action",
    "browser_semantic_execute",
    "browser_semantic_operation",
}


@dataclass
class _Tool:
    name: str
    calls: int = 0

    @property
    def description(self) -> str:
        return self.name

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs) -> ToolResult:
        del kwargs
        self.calls += 1
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="ok",
            tool_call_id="",
            tool_name=self.name,
        )


def _wire_names(fake) -> set[str]:
    return {tool["function"]["name"] for tool in fake.calls[-1]["tools"]}


def test_s5_structural_channels_are_green() -> None:
    provider = probe_provider_projection()
    discovery = probe_discovery()
    execution = probe_execution()
    canary = probe_canary_scope_authority()
    assert (provider.state, provider.code) == ("green", "contract_present")
    assert (discovery.state, discovery.code) == (
        "green_prerequisite",
        "discovery_scope_already_enforced",
    )
    assert (execution.state, execution.code) == ("green", "contract_present")
    assert (canary.state, canary.code) == ("green", "contract_present")


def test_s5_exact_canary_scope_matches_frozen_12_tool_surface() -> None:
    assert exact_canary_scope() == P4_LIVE_CANARY_TOOL_SCOPE
    assert len(P4_LIVE_CANARY_TOOL_SCOPE) == 12
    assert LEGACY_BROWSER_MUTATIONS.isdisjoint(P4_LIVE_CANARY_TOOL_SCOPE)
    assert {
        "browser_perceive",
        "browser_wait_scope_url",
        "browser_wait_scope_ready",
        "browser_wait_scope_count",
        "browser_wait_object_state",
        "browser_wait_object_text",
        "get_tool_schema",
    }.issubset(P4_LIVE_CANARY_TOOL_SCOPE)
    assert {
        "browser_semantic_click",
        "browser_semantic_fill",
        "browser_semantic_select",
        "browser_semantic_scroll",
        "browser_semantic_navigate",
    }.issubset(P4_LIVE_CANARY_TOOL_SCOPE)


def test_s5_main_provider_projection_is_exact_canary_scope(build_test_engine) -> None:
    engine, fake = build_test_engine([{"content": "done"}])
    for name in sorted(P4_LIVE_CANARY_TOOL_SCOPE | LEGACY_BROWSER_MUTATIONS):
        if name not in engine.registry.names():
            engine.registry.register(_Tool(name))
    sid = engine.session.create()
    with p4_live_canary_tool_scope():
        engine.run(sid, "deterministic scope qualification")
    assert _wire_names(fake) == set(P4_LIVE_CANARY_TOOL_SCOPE)


def test_s5_get_tool_schema_catalog_and_exact_lookup_share_canary_scope() -> None:
    reg = ToolRegistry()
    for name in sorted(P4_LIVE_CANARY_TOOL_SCOPE | LEGACY_BROWSER_MUTATIONS):
        reg.register(_Tool(name))
    schema = GetToolSchemaTool(reg)
    with p4_live_canary_tool_scope():
        catalog = schema.execute(tool_name="*")
        assert catalog.status is ToolResultStatus.SUCCESS
        for name in P4_LIVE_CANARY_TOOL_SCOPE:
            assert f"- {name} [" in catalog.content
        for name in LEGACY_BROWSER_MUTATIONS:
            assert f"- {name} [" not in catalog.content
            denied = schema.execute(tool_name=name)
            assert denied.status is ToolResultStatus.FAILURE
            assert "当前执行域不可用" in denied.content
        allowed = schema.execute(tool_name="browser_semantic_click")
        assert allowed.status is ToolResultStatus.SUCCESS


def test_s5_registry_execution_cannot_bypass_canary_scope() -> None:
    reg = ToolRegistry()
    allowed = _Tool("browser_semantic_click")
    legacy = _Tool("browser_action")
    reg.register(allowed)
    reg.register(legacy)
    with p4_live_canary_tool_scope():
        ok = reg.execute(ToolCall(id="allowed", name=allowed.name, arguments={}))
        denied = reg.execute(ToolCall(id="legacy", name=legacy.name, arguments={}))
    assert ok.status is ToolResultStatus.SUCCESS
    assert allowed.calls == 1
    assert denied.status is ToolResultStatus.FAILURE
    assert "当前执行域不可用" in denied.content
    assert legacy.calls == 0


def test_s5_scope_none_preserves_full_registry_discovery_schema_and_execution() -> None:
    reg = ToolRegistry()
    first = _Tool("browser_semantic_click")
    legacy = _Tool("browser_action")
    reg.register(first)
    reg.register(legacy)
    schema = GetToolSchemaTool(reg)
    assert current_tool_discovery_scope.get() is None
    assert reg.names_for_current_scope() == ["browser_action", "browser_semantic_click"]
    assert {row["name"] for row in reg.schemas_for_current_scope()} == {
        "browser_action",
        "browser_semantic_click",
    }
    catalog = schema.execute(tool_name="*")
    assert "browser_action" in catalog.content
    result = reg.execute(ToolCall(id="legacy-none", name="browser_action", arguments={}))
    assert result.status is ToolResultStatus.SUCCESS
    assert legacy.calls == 1


def test_s5_scope_context_restores_outer_scope_and_contexts_do_not_leak() -> None:
    outer = current_tool_discovery_scope.set(frozenset({"outer"}))
    try:
        with p4_live_canary_tool_scope() as active:
            assert active == P4_LIVE_CANARY_TOOL_SCOPE
            assert current_tool_discovery_scope.get() == P4_LIVE_CANARY_TOOL_SCOPE
        assert current_tool_discovery_scope.get() == frozenset({"outer"})
    finally:
        current_tool_discovery_scope.reset(outer)

    reg = ToolRegistry()
    reg.register(_Tool("a"))
    reg.register(_Tool("b"))

    def scoped_a() -> tuple[list[str], bool]:
        token = current_tool_discovery_scope.set(frozenset({"a"}))
        try:
            result = reg.execute(ToolCall(id="blocked-b", name="b", arguments={}))
            return reg.names_for_current_scope(), result.status is ToolResultStatus.FAILURE
        finally:
            current_tool_discovery_scope.reset(token)

    context_a = Context()
    assert context_a.run(scoped_a) == (["a"], True)
    assert current_tool_discovery_scope.get() is None
    assert reg.names_for_current_scope() == ["a", "b"]

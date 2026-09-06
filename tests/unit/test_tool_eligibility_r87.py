from __future__ import annotations

from dataclasses import dataclass

import pytest

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.tools.eligibility import ToolHealth, runtime_tool_health
from llm_loop.tools.recovery import ToolRecoveryAdvice, classify_tool_recovery, web_fetch_preflight
from llm_loop.tools.registry import GetToolSchemaTool, ToolRegistry, tool_result_to_message


class _FakeMcpConn:
    def __init__(self, tools: list[object]) -> None:
        self._tools = tools
        self.closed = False

    def connect(self) -> list[object]:
        return self._tools

    def close(self) -> None:
        self.closed = True


@dataclass
class _FakeTool:
    name: str
    calls: int = 0

    @property
    def description(self) -> str:
        return f"description for {self.name}"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        self.calls += 1
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="ok",
            tool_call_id="",
            tool_name=self.name,
        )


def _wire_tool_names(call: dict) -> list[str]:
    return [str(t.get("function", {}).get("name", "")) for t in call.get("tools", [])]


def test_runtime_health_is_mechanical_dependency_fact(monkeypatch):
    import llm_loop.tools.eligibility as eligibility

    monkeypatch.setattr(eligibility.importlib.util, "find_spec", lambda name: None)
    assert runtime_tool_health("read_file") == ToolHealth(state="ready")
    health = runtime_tool_health("playwright_exec")
    assert health.available is False
    assert health.reason_code == "playwright_python_dependency_missing"


def test_engine_surface_does_not_depend_on_user_semantics(build_test_engine, monkeypatch):
    import llm_loop.tools.eligibility as eligibility

    monkeypatch.setattr(eligibility, "runtime_tool_health", lambda _name: ToolHealth(state="ready"))
    engine, fake = build_test_engine([{"content": "one"}, {"content": "two"}])
    for name in ("web_fetch", "schedule", "submit_evolution", "job_output", "job_kill"):
        if name not in engine.registry.names():
            engine.registry.register(_FakeTool(name))
    sid = engine.session.create()

    engine.run(sid, "只整理本地代码")
    first = _wire_tool_names(fake.calls[-1])
    engine.run(sid, "取消后台任务，然后分析 https://example.com")
    second = _wire_tool_names(fake.calls[-1])

    assert second == first
    for name in ("web_fetch", "schedule", "submit_evolution", "job_output", "job_kill"):
        assert name in first
    assert engine._tool_cycle._last_tool_eligibility["mode"] == "stable_runtime_health"


def test_engine_surface_removes_only_runtime_unhealthy(build_test_engine, monkeypatch):
    import llm_loop.tools.eligibility as eligibility

    engine, fake = build_test_engine([{"content": "done"}])
    engine.registry.register(_FakeTool("healthy_extra"))
    engine.registry.register(_FakeTool("unhealthy_extra"))

    def _health(name: str) -> ToolHealth:
        if name == "unhealthy_extra":
            return ToolHealth(state="quarantined", reason_code="test_missing_dependency")
        return ToolHealth(state="ready")

    monkeypatch.setattr(eligibility, "runtime_tool_health", _health)
    sid = engine.session.create()
    engine.run(sid, "任意文本都不应决定工具面")
    names = _wire_tool_names(fake.calls[-1])
    assert "healthy_extra" in names
    assert "unhealthy_extra" not in names
    info = engine._tool_cycle._last_tool_eligibility
    assert info["quarantined_names"] == ["unhealthy_extra"]


def test_get_tool_schema_is_discovery_only_and_reports_health(monkeypatch):
    import llm_loop.tools.eligibility as eligibility

    monkeypatch.setattr(eligibility.importlib.util, "find_spec", lambda name: None)
    reg = ToolRegistry()
    reg.register(_FakeTool("read_file"))
    reg.register(_FakeTool("playwright_exec"))
    tool = GetToolSchemaTool(reg)

    catalog = tool.execute(tool_name="*")
    assert catalog.status == ToolResultStatus.SUCCESS
    assert "read_file [ready]" in catalog.content
    assert "playwright_exec [quarantined]" in catalog.content

    search = tool.execute(tool_name="?playwright")
    assert search.status == ToolResultStatus.SUCCESS
    assert "playwright_exec" in search.content and "read_file" not in search.content

    exact = tool.execute(tool_name="playwright_exec")
    assert exact.status == ToolResultStatus.SUCCESS
    assert "runtime_health=quarantined" in exact.content
    assert not hasattr(exact, "promotion_signal")


def test_retired_selection_modes_are_not_settings_or_config(monkeypatch):
    from llm_loop.config import Settings, load_settings

    for env in ("TOOL_ELIGIBILITY_MODE", "TOOL_PROMOTION_MODE", "CAPABILITY_REQUIREMENTS_MODE"):
        monkeypatch.setenv(env, "enforce")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    settings = load_settings()
    for name in ("tool_eligibility_mode", "tool_promotion_mode", "capability_requirements_mode"):
        assert not hasattr(settings, name)
        assert name not in settings.to_status_dict()
    assert not hasattr(Settings, "tool_eligibility_mode")


@pytest.mark.parametrize(
    "url",
    [
        "https://m.toutiao.com/article/1234567890123456789/",
        "https://m.toutiao.com/i1234567890123456789/",
        "https://www.toutiao.com/x?group_id=1234567890123456789",
    ],
)
def test_web_fetch_preflight_allows_toutiao_site_adapter_urls(url):
    assert web_fetch_preflight(url) is None


def test_web_fetch_preflight_routes_unsupported_toutiao_without_retry():
    advice = web_fetch_preflight("https://m.toutiao.com/search/?keyword=test")
    assert advice is not None
    assert advice.failure_class == "known_domain_anti_bot"
    assert advice.retry_same_tool == "no"
    assert advice.preferred_skill == "web-fetch-fast"
    assert advice.preferred_next == ("skill_load:web-fetch-fast",)


@pytest.mark.parametrize(
    ("content", "status", "failure_class", "retry"),
    [
        (
            "httpx HTTP 403（已轮换 3 个 UA）",
            ToolResultStatus.FAILURE,
            "anti_bot_or_access_reject",
            "no",
        ),
        ("httpx HTTP 404", ToolResultStatus.FAILURE, "url_not_found", "no"),
        ("httpx 仅取到 JS 壳", ToolResultStatus.FAILURE, "javascript_shell_or_anti_bot", "no"),
        ("httpx 超时", ToolResultStatus.TIMEOUT, "transient_transport_or_server", "once"),
    ],
)
def test_web_fetch_failure_classes(content, status, failure_class, retry):
    advice = classify_tool_recovery(
        ToolResult(status=status, content=content, tool_call_id="x", tool_name="web_fetch")
    )
    assert advice is not None
    assert advice.failure_class == failure_class
    assert advice.retry_same_tool == retry


def test_registry_preflight_does_not_execute_known_bad_web_fetch_domain():
    reg = ToolRegistry()
    tool = _FakeTool("web_fetch")
    reg.register(tool)
    result = reg.execute(
        ToolCall(id="call-1", name="web_fetch", arguments={"url": "https://www.toutiao.com/a"})
    )
    assert result.status == ToolResultStatus.FAILURE
    assert tool.calls == 0
    assert result.recovery_advice is not None
    assert result.recovery_advice.preferred_skill == "web-fetch-fast"


def test_typed_recovery_replaces_generic_failure_guidance(monkeypatch):
    monkeypatch.setenv("LFL_TOOL_GUIDANCE", "on")
    advice = ToolRecoveryAdvice(
        failure_class="url_not_found",
        retry_same_tool="no",
        preferred_next=("web_search",),
        reason="find canonical URL",
    )
    result = ToolResult(
        status=ToolResultStatus.FAILURE,
        content="HTTP 404",
        tool_call_id="call-1",
        tool_name="web_fetch",
        recovery_advice=advice,
        guidance_extra="[经验参考] stale generic advice",
    )
    msg = tool_result_to_message(result)
    assert "class=url_not_found" in msg.content
    assert "retry_same_tool=no" in msg.content
    assert "stale generic advice" not in msg.content
    assert msg.metadata["tool_recovery"]["preferred_next"] == ["web_search"]


def test_mcp_zero_capability_closes_connection_and_registers_nothing(monkeypatch):
    import json

    import llm_loop.tools.mcp_client as mcp

    conn = _FakeMcpConn([])
    monkeypatch.setattr(mcp, "McpConnection", lambda spec: conn)
    registry = ToolRegistry()
    raw = json.dumps([{"name": "empty", "command": "fake"}])
    assert mcp.register_mcp_tools(registry, raw) == []
    assert conn.closed is True
    assert not any(name.startswith("mcp_empty_") for name in registry.names())


def test_mcp_nonempty_list_but_zero_valid_registrations_closes_connection(monkeypatch):
    import json

    import llm_loop.tools.mcp_client as mcp

    conn = _FakeMcpConn([mcp.McpToolDef(name="bad", description="bad", input_schema={})])
    monkeypatch.setattr(mcp, "McpConnection", lambda spec: conn)
    registry = ToolRegistry()
    monkeypatch.setattr(
        registry, "register", lambda tool: (_ for _ in ()).throw(ValueError("reject"))
    )
    raw = json.dumps([{"name": "empty-after-validation", "command": "fake"}])
    assert mcp.register_mcp_tools(registry, raw) == []
    assert conn.closed is True

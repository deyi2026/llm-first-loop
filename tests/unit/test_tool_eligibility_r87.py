from __future__ import annotations

from dataclasses import dataclass

import pytest

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.tools.eligibility import CORE_TOOL_ORDER, project_tool_schemas
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


def _schemas(*names: str) -> list[dict]:
    return [
        {"name": name, "description": f"desc {name}", "parameters": {"type": "object"}}
        for name in names
    ]


def test_simple_task_projects_only_core_from_available_names():
    names = tuple(CORE_TOOL_ORDER) + ("web_fetch", "schedule", "playwright_exec")
    result = project_tool_schemas(_schemas(*names), user_text="请修改这个文件", mode="enforce")
    assert result.visible_names == tuple(CORE_TOOL_ORDER)
    assert "web_fetch" not in result.visible_names
    assert "schedule" not in result.visible_names


def test_url_task_adds_web_fetch_after_stable_core():
    names = tuple(CORE_TOOL_ORDER) + ("web_fetch", "schedule")
    result = project_tool_schemas(
        _schemas(*names), user_text="分析 https://example.com/a", mode="enforce"
    )
    assert result.visible_names[: len(CORE_TOOL_ORDER)] == tuple(CORE_TOOL_ORDER)
    assert result.visible_names[-1] == "web_fetch"
    assert "schedule" not in result.visible_names


def test_recovery_metadata_reopens_required_hidden_tool():
    names = tuple(CORE_TOOL_ORDER) + ("retry_tool",)
    messages = [
        {
            "role": "tool",
            "metadata": {
                "tool_recovery": {
                    "preferred_next": ["retry_tool", "web_search"],
                }
            },
        }
    ]
    result = project_tool_schemas(
        _schemas(*names), user_text="继续", session_messages=messages, mode="enforce"
    )
    assert "retry_tool" in result.visible_names
    assert result.recovery_names == ("retry_tool", "web_search")


def test_playwright_is_quarantined_when_python_dependency_missing(monkeypatch):
    import llm_loop.tools.eligibility as eligibility

    monkeypatch.setattr(eligibility.importlib.util, "find_spec", lambda name: None)
    names = tuple(CORE_TOOL_ORDER) + ("playwright_exec",)
    result = project_tool_schemas(
        _schemas(*names), user_text="用 playwright 做浏览器脚本", mode="enforce"
    )
    assert "playwright_exec" not in result.visible_names
    assert result.quarantined_names == ("playwright_exec",)


def test_web_fetch_preflight_routes_toutiao_without_retry():
    advice = web_fetch_preflight("https://m.toutiao.com/article/123/")
    assert advice is not None
    assert advice.failure_class == "known_domain_anti_bot"
    assert advice.retry_same_tool == "no"
    assert advice.preferred_skill == "web-fetch-fast"
    assert advice.preferred_next == ("skill_load:web-fetch-fast",)


@pytest.mark.parametrize(
    ("content", "status", "failure_class", "retry"),
    [
        ("httpx HTTP 403（已轮换 3 个 UA）", ToolResultStatus.FAILURE, "anti_bot_or_access_reject", "no"),
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
    monkeypatch.setenv("LFL_TOOL_GUIDANCE", "on")  # R9-P0-01 批 2/3：on 态机制测试钉住前提
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
    assert "检查参数/路径/网络后重试" not in msg.content
    assert "stale generic advice" not in msg.content
    assert msg.metadata["tool_recovery"]["preferred_next"] == ["web_search"]


def test_get_tool_schema_supports_on_demand_catalog_and_search(monkeypatch):
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
    assert "playwright_exec" in search.content
    assert "read_file" not in search.content

    exact = tool.execute(tool_name="playwright_exec")
    assert exact.status == ToolResultStatus.SUCCESS
    assert "runtime_health=quarantined" in exact.content


def test_tool_eligibility_mode_parser_defaults_enforce_and_fails_bounded(monkeypatch):
    from llm_loop.config import _env_tool_eligibility_mode

    monkeypatch.delenv("TOOL_ELIGIBILITY_MODE", raising=False)
    assert _env_tool_eligibility_mode("TOOL_ELIGIBILITY_MODE") == "enforce"
    monkeypatch.setenv("TOOL_ELIGIBILITY_MODE", "shadow")
    assert _env_tool_eligibility_mode("TOOL_ELIGIBILITY_MODE") == "shadow"
    monkeypatch.setenv("TOOL_ELIGIBILITY_MODE", "nonsense")
    assert _env_tool_eligibility_mode("TOOL_ELIGIBILITY_MODE") == "enforce"


def _wire_tool_names(call: dict) -> list[str]:
    return [str(t.get("function", {}).get("name", "")) for t in call.get("tools", [])]


def test_engine_enforce_projects_web_fetch_only_when_current_task_needs_it(build_test_engine):
    engine, fake = build_test_engine([{"content": "done"}, {"content": "done2"}])
    engine.registry.register(_FakeTool("web_fetch"))
    engine.registry.register(_FakeTool("schedule"))
    object.__setattr__(engine.settings, "tool_eligibility_mode", "enforce")

    sid = engine.session.create()
    engine.run(sid, "先整理本地代码")
    first = _wire_tool_names(fake.calls[0])
    assert "web_fetch" not in first
    assert "schedule" not in first

    engine.run(sid, "再分析 https://example.com/article")
    second = _wire_tool_names(fake.calls[-1])
    assert "web_fetch" in second
    assert "schedule" not in second


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


def test_engine_shadow_and_off_preserve_legacy_tool_surface(build_test_engine):
    engine, fake = build_test_engine([{"content": "shadow"}, {"content": "off"}])
    engine.registry.register(_FakeTool("web_fetch"))
    engine.registry.register(_FakeTool("schedule"))
    sid = engine.session.create()

    object.__setattr__(engine.settings, "tool_eligibility_mode", "shadow")
    engine.run(sid, "只整理本地代码")
    shadow_names = _wire_tool_names(fake.calls[-1])
    assert "web_fetch" in shadow_names
    assert "schedule" in shadow_names
    assert engine._tool_cycle._last_tool_eligibility["configured_mode"] == "shadow"
    assert engine._tool_cycle._last_tool_eligibility["applied"] is False

    object.__setattr__(engine.settings, "tool_eligibility_mode", "off")
    engine.run(sid, "继续整理本地代码")
    off_names = _wire_tool_names(fake.calls[-1])
    assert "web_fetch" in off_names
    assert "schedule" in off_names
    assert engine._tool_cycle._last_tool_eligibility["configured_mode"] == "off"
    assert engine._tool_cycle._last_tool_eligibility["applied"] is False


def test_enforce_ignores_legacy_prefix_index_representation(build_test_engine):
    engine, fake = build_test_engine([{"content": "done"}])
    object.__setattr__(engine.settings, "tool_eligibility_mode", "enforce")
    object.__setattr__(engine.settings, "prefix_layered", True)

    sid = engine.session.create()
    engine.run(sid, "读取本地文件")
    tools = fake.calls[-1]["tools"]
    read_file = next(t for t in tools if t["function"]["name"] == "read_file")
    props = read_file["function"]["parameters"].get("properties", {})
    assert "path" in props


def test_generic_writing_request_does_not_open_web_fetch():
    names = tuple(CORE_TOOL_ORDER) + ("web_fetch",)
    result = project_tool_schemas(_schemas(*names), user_text="帮我写一篇文章", mode="enforce")
    assert "web_fetch" not in result.visible_names


def test_mcp_nonempty_list_but_zero_valid_registrations_closes_connection(monkeypatch):
    import json

    import llm_loop.tools.mcp_client as mcp

    conn = _FakeMcpConn([mcp.McpToolDef(name="bad", description="bad", input_schema={})])
    monkeypatch.setattr(mcp, "McpConnection", lambda spec: conn)

    registry = ToolRegistry()
    monkeypatch.setattr(registry, "register", lambda tool: (_ for _ in ()).throw(ValueError("reject")))
    raw = json.dumps([{"name": "empty-after-validation", "command": "fake"}])
    assert mcp.register_mcp_tools(registry, raw) == []
    assert conn.closed is True

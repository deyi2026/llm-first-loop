"""T13：纯 resources/prompts 服务器可用（P2-B，FR-11 / §7.1 / §10.1）.

- tools/list=0 但宣告 resources/prompts：连接保活（不再 no-capability 隔离）。
- mcp_resource_read / mcp_prompt_get 模型工具：binding_id 路由、清单发现、
  类型/角色/来源保留（text 原文、blob digest 指针、非文本块指针）。
- 能力门控：未宣告能力 → 如实"仅提供未支持能力"，不称服务器无能力。
- 生命周期：config 移除 → 路由卸载 + 连接关闭；能力消失 → 绑定清理。
- 分页聚合与循环游标防护；legacy 握手捕获 capabilities。
"""

from __future__ import annotations

import json

from llm_loop.tools.mcp_client import (
    McpConnection,
    McpPromptGetTool,
    McpResourceReadTool,
    McpServerSpec,
    refresh_mcp_tools,
    register_mcp_tools,
)
from llm_loop.tools.mcp_protocol import McpProtocolError
from llm_loop.tools.registry import ToolRegistry
from tests.fixtures.fake_mcp_legacy_sse_server import FakeMcpLegacySseServer


def _spec(srv: FakeMcpLegacySseServer, name: str = "pure") -> McpServerSpec:
    return McpServerSpec(name=name, command="", type="sse", url=srv.sse_url)


def test_pure_resource_server_kept_alive_and_routers_registered() -> None:
    """T13 主链路：tools=0 + resources/prompts 宣告 → 保活 + 路由工具在册."""
    with FakeMcpLegacySseServer() as srv:
        registry = ToolRegistry()
        raw = json.dumps([{"name": "pure", "type": "sse", "url": srv.sse_url}])
        registered = register_mcp_tools(registry, raw)
        assert "mcp_resource_read" in registered
        assert "mcp_prompt_get" in registered
        read_tool = registry.get("mcp_resource_read")
        assert isinstance(read_tool, McpResourceReadTool)
        assert "pure" in read_tool.bindings
        prompt_tool = registry.get("mcp_prompt_get")
        assert isinstance(prompt_tool, McpPromptGetTool)


def test_resource_read_model_view_preserves_type_source_and_digest() -> None:
    """模型视图：uri/mimeType 保留；text 原文；blob → digest 指针."""
    with FakeMcpLegacySseServer() as srv:
        registry = ToolRegistry()
        raw = json.dumps([{"name": "pure", "type": "sse", "url": srv.sse_url}])
        register_mcp_tools(registry, raw)
        tool = registry.get("mcp_resource_read")

        listing = tool.execute(binding_id="pure", list=True)
        assert listing.status.value == "success"
        assert "memo://alpha" in listing.content and "memo://{topic}" in listing.content

        read = tool.execute(binding_id="pure", uri="memo://alpha")
        assert read.status.value == "success"
        assert "uri=memo://alpha" in read.content
        assert "内容-of-memo://alpha" in read.content

        blob = tool.execute(binding_id="pure", uri="bin://logo")
        assert "blob=" in blob.content and "sha256=" in blob.content
        assert "aGVsbG8" not in blob.content  # base64 不入上下文


def test_prompt_get_preserves_roles_and_non_text_pointers() -> None:
    """模型视图：角色保留；text 原文；image/resource 块 → 类型 + digest 指针."""
    with FakeMcpLegacySseServer() as srv:
        registry = ToolRegistry()
        raw = json.dumps([{"name": "pure", "type": "sse", "url": srv.sse_url}])
        register_mcp_tools(registry, raw)
        tool = registry.get("mcp_prompt_get")

        listing = tool.execute(binding_id="pure", list=True)
        assert "review" in listing.content

        got = tool.execute(binding_id="pure", name="review", arguments={"lang": "Python"})
        assert got.status.value == "success"
        assert "（描述: 评审提示（demo））" in got.content
        assert "[user] 用 Python 评审以下补丁" in got.content
        assert "[assistant] <非文本块 type=image" in got.content
        assert "[user] <非文本块 type=resource" in got.content


def test_capability_gating_honest_error_and_bad_binding() -> None:
    """门控：未宣告 → 仅提供未支持能力（非无能力）；未知 binding 如实报错."""
    with FakeMcpLegacySseServer() as srv:
        registry = ToolRegistry()
        raw = json.dumps([{"name": "pure", "type": "sse", "url": srv.sse_url}])
        register_mcp_tools(registry, raw)
        tool = registry.get("mcp_resource_read")

        bad_binding = tool.execute(binding_id="ghost", uri="memo://x")
        assert bad_binding.status.value == "error"
        assert "未知或已失效的 binding_id" in bad_binding.content

        # 连接直接调用：缺 uri 参数如实报错
        missing = tool.execute(binding_id="pure")
        assert missing.status.value == "error"
        assert "缺 uri" in missing.content

        # capability 缺失：对宣告裁剪的连接（直接构造），报"仅提供未支持能力"
        conn = McpConnection(_spec(srv, name="stripped"))
        conn.connect()

        class _NoTools:
            """剥掉 resources 宣告的 profile 视图（直接改 profile.capabilities）."""

        conn.profile.capabilities = {k: v for k, v in conn.profile.capabilities.items() if k != "resources"}
        try:
            conn.list_resources()
            raise AssertionError("未宣告 resources 未被拒绝")
        except McpProtocolError as exc:
            assert "仅提供未支持能力" in str(exc)
        conn.close()


def test_pagination_aggregation_and_cursor_loop_guard() -> None:
    """分页：两页聚合；循环游标 → 如实报分页异常."""
    with FakeMcpLegacySseServer() as srv:
        conn = McpConnection(_spec(srv))
        conn.connect()
        resources = conn.list_resources()
        assert [r["uri"] for r in resources] == ["memo://alpha", "memo://beta"]
        # 循环游标：篡改下一页响应？以直接调用构造循环（nextCursor 恒定）
        original = conn.transport.send_request
        state = {"calls": 0}

        def looping(_request, timeout):
            state["calls"] += 1
            return {"resources": [{"uri": f"memo://loop{state['calls']}"}], "nextCursor": "p2"}

        conn.transport.send_request = looping  # type: ignore[method-assign]
        try:
            conn.list_resources()
            raise AssertionError("循环游标未触发防护")
        except McpProtocolError as exc:
            assert "分页超过" in str(exc)
        finally:
            conn.transport.send_request = original  # type: ignore[method-assign]
        conn.close()


def test_config_removed_drops_routes_and_closes_connection() -> None:
    """生命周期：config 移除 → 路由卸载、连接关闭、McpTool 无残留."""
    with FakeMcpLegacySseServer() as srv:
        registry = ToolRegistry()
        raw = json.dumps([{"name": "pure", "type": "sse", "url": srv.sse_url}])
        register_mcp_tools(registry, raw)
        tool = registry.get("mcp_resource_read")
        conn = tool.bindings["pure"]
        registered2, unregistered2 = refresh_mcp_tools(registry, "[]")  # 配置清空
        # 路由绑定清除且连接关闭
        assert "pure" not in tool.bindings
        assert conn._closed is True
        # 工具本体保留（可服务其他服务器），路由为空
        after = tool.execute(binding_id="pure", uri="memo://alpha")
        assert after.status.value == "error"


def test_refresh_keeps_pure_server_alive_and_rebinds() -> None:
    """刷新：纯资源服务器仍保活；旧绑定连接被替换关闭（不泄漏）."""
    with FakeMcpLegacySseServer() as srv:
        registry = ToolRegistry()
        raw = json.dumps([{"name": "pure", "type": "sse", "url": srv.sse_url}])
        register_mcp_tools(registry, raw)
        tool = registry.get("mcp_resource_read")
        old_conn = tool.bindings["pure"]
        refresh_mcp_tools(registry, raw)
        new_conn = tool.bindings["pure"]
        assert new_conn is not old_conn
        assert old_conn._closed is True
        assert new_conn._closed is False
        result = tool.execute(binding_id="pure", uri="memo://beta")
        assert result.status.value == "success"

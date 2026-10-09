"""P1-B 余项：HTTP 常驻订阅 + connection_epoch 代际丢弃 + registry 目录 epoch.

设计 §7.3：
- HTTP 常驻 subscriptions/listen（X-Subscription-Id + GET 常驻流）→
  tools/list_changed 观察（stale / list_revision / catalog epoch 推进）
- 连接代际：重连递增；旧代通道晚到通知按代际丢弃并记 adapter 事件；
  请求 id 跨重连绝不重置
- catalog epoch：register / refresh / 配置清理 / list_changed 均推进
"""

import json
import time

import pytest

from llm_loop.tools.mcp_client import (
    McpConnection,
    McpServerSpec,
    _reset_catalog_state_for_tests,
    adapter_events,
    catalog_epoch,
    refresh_mcp_tools,
    register_mcp_tools,
)
from llm_loop.tools.registry import ToolRegistry
from tests.fixtures.fake_mcp_http_server import FakeMcpHttpServer


def _http(name: str, url: str) -> McpServerSpec:
    return McpServerSpec(name=name, type="http", url=url)


def _wait_for(predicate, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


@pytest.fixture()
def modern_http():
    server = FakeMcpHttpServer("modern")
    yield server
    server.close()


def test_http_persistent_subscription_marks_stale(modern_http):
    """HTTP 常驻订阅：list_changed 经 GET 流上送 → stale + list_revision + catalog epoch."""
    _reset_catalog_state_for_tests()
    conn = McpConnection(_http("srv", modern_http.url), call_timeout=10, probe_timeout_s=2)
    tools = conn.connect()
    assert tools, "应拉到工具清单（游标分页）"
    assert conn.connection_epoch == 1
    try:
        # 常驻订阅已建立（fixture 侧 GET 流挂上）
        assert _wait_for(lambda: modern_http.subscription_count() == 1)
        epoch_before = catalog_epoch()
        modern_http.state.emit_list_changed()
        assert _wait_for(lambda: conn.stale), "list_changed 应经常驻流上送并置 stale"
        assert conn.list_revision == 1
        assert catalog_epoch() > epoch_before, "list_changed 必须推进 registry 目录 epoch"
    finally:
        conn.close()
    assert _wait_for(lambda: modern_http.subscription_count() == 0), "关闭后订阅应清理"


def test_old_generation_notification_dropped_with_adapter_event(modern_http):
    """旧代通知按代际丢弃（adapter 事件留痕）；当代通知照常生效."""
    _reset_catalog_state_for_tests()
    conn = McpConnection(_http("srv", modern_http.url), call_timeout=10, probe_timeout_s=2)
    conn.connect()
    try:
        assert conn.connection_epoch == 1
        before = catalog_epoch()
        conn._on_notification("notifications/tools/list_changed", {}, generation=0)  # 旧代
        assert conn.stale is False, "旧代通知不得套用到新代目录状态"
        assert conn.list_revision == 0
        assert catalog_epoch() == before, "被丢弃的通知不应推进目录 epoch"
        assert any(e["kind"] == "stale_generation_notification" for e in adapter_events()), (
            "代际丢弃必须记录 adapter 事件"
        )
        conn._on_notification("notifications/tools/list_changed", {}, generation=1)  # 当代
        assert conn.stale is True
        assert conn.list_revision == 1
    finally:
        conn.close()


def test_epoch_and_id_namespace_across_reconnect(modern_http):
    """重连递增 epoch（并回填 transport.generation）；请求 id 命名空间绝不重置."""
    conn = McpConnection(_http("srv", modern_http.url), call_timeout=10, probe_timeout_s=2)
    conn.connect()
    assert conn.connection_epoch == 1
    assert conn.transport.generation == 1
    id_before = conn._next_msg_id()
    conn.close()
    conn.connect()
    try:
        assert conn.connection_epoch == 2
        assert conn.transport.generation == 2
        id_after = conn._next_msg_id()
        assert id_after > id_before, "请求 id 跨重连单调递增、绝不重置（§7.3）"
    finally:
        conn.close()


def test_catalog_epoch_bumps_on_register_refresh_and_removal(modern_http):
    """registry 目录 epoch：注册/热刷新/配置移除均推进（P1-C 装配失效判据）."""
    _reset_catalog_state_for_tests()
    assert catalog_epoch() == 0
    registry = ToolRegistry()
    raw = json.dumps([{"name": "srv", "type": "http", "url": modern_http.url}])
    registered = register_mcp_tools(registry, raw)
    assert registered, "现代 HTTP fixture 工具应注册成功"
    assert catalog_epoch() >= 1

    epoch_mid = catalog_epoch()
    refresh_mcp_tools(registry, raw)
    assert catalog_epoch() > epoch_mid, "热刷新注册成功必须推进目录 epoch"

    epoch_before = catalog_epoch()
    refresh_mcp_tools(registry, json.dumps([]))  # 配置移除 → 精确清理
    assert catalog_epoch() > epoch_before, "配置移除清理必须推进目录 epoch"
    assert not any(name.startswith("mcp_srv") for name in registry.names()), "MCP 工具应全部卸载"

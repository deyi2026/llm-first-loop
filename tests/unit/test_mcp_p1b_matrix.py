"""P1-B 集成矩阵：双时代 × 双传输 + 恢复语义 + 身份隔离.

设计文档 §11 P1-B 退出条件对齐：现代及旧版协议矩阵、身份隔离、运行恢复。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.tools.mcp_client import (
    McpConnection,
    McpNotDispatchedError,
    McpServerSpec,
    parse_servers,
    register_mcp_tools,
)
from llm_loop.tools.registry import ToolRegistry
from tests.fixtures.fake_mcp_http_server import FakeMcpHttpServer

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_LEGACY = _FIXTURES / "fake_mcp_server.py"
_MODERN = _FIXTURES / "fake_mcp_modern_server.py"


def _stdio(fixture: Path, name: str, extra_env: dict[str, str] | None = None) -> McpServerSpec:
    return McpServerSpec(name=name, command=sys.executable, args=[str(fixture)], env=extra_env or {})


def _http(name: str, url: str) -> McpServerSpec:
    return McpServerSpec(name=name, type="http", url=url)


@pytest.fixture()
def modern_http():
    server = FakeMcpHttpServer(mode="modern")
    yield server
    server.close()


@pytest.fixture()
def legacy_http():
    server = FakeMcpHttpServer(mode="legacy")
    yield server
    server.close()


# ── stdio 现代 ────────────────────────────────────────────────────────
def test_stdio_modern_era_discover_pagination_and_meta():
    conn = McpConnection(_stdio(_MODERN, "mod"), call_timeout=10, probe_timeout_s=2)
    tools = conn.connect()
    try:
        assert conn.profile is not None and conn.profile.is_modern
        assert conn.profile.version == "2026-07-28"
        assert conn.profile.server_supported_versions == ["2026-07-28"]
        # 分页聚合：每页 2 条，共 3 个工具（旧实现丢 nextCursor 后续页）
        assert [t.name for t in tools] == ["echo", "get_last_meta", "bump_list"]
        # 逐请求 _meta：服务器如实回显其收到的 _meta
        seen = json.loads(conn.call_tool("get_last_meta", {})["content"][0]["text"])
        assert seen["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
        assert seen["io.modelcontextprotocol/clientInfo"]["name"] == "llm-first-loop"
        assert conn.call_tool("echo", {"text": "x"})["content"][0]["text"] == "echo:x"
    finally:
        conn.close()


def test_stdio_modern_unsupported_version_retries_without_legacy_fallback(monkeypatch):
    """首次探测被 UnsupportedProtocolVersionError 拒 → 按列表重试一次，绝不回退 initialize."""
    monkeypatch.setenv("FAKE_MODERN_REJECT_FIRST", "1")
    spec = McpServerSpec(
        name="mod2",
        command=sys.executable,
        args=[str(_MODERN)],
        env={"FAKE_MODERN_REJECT_FIRST": "1"},
    )
    conn = McpConnection(spec, call_timeout=10, probe_timeout_s=2)
    tools = conn.connect()
    try:
        assert conn.profile is not None and conn.profile.is_modern
        assert conn.profile.version == "2026-07-28"
        assert len(tools) == 3
    finally:
        conn.close()


def test_stdio_modern_list_changed_marks_stale():
    conn = McpConnection(_stdio(_MODERN, "mod3"), call_timeout=10, probe_timeout_s=2)
    conn.connect()
    try:
        assert not conn.stale and conn.list_revision == 0
        conn.call_tool("bump_list", {})
        for _ in range(40):
            if conn.stale:
                break
            time.sleep(0.05)
        assert conn.stale and conn.list_revision == 1
        # stale 后重拉：目录已增长（subscriptions/listen 通知驱动的惰性刷新依据）
        assert len(conn._list_all_tools()) == 4
    finally:
        conn.close()


def test_stdio_modern_process_death_recovery_replays_once():
    """现代 stdio 进程意外退出 → 未派发 → 重启重协商重放（无握手状态可丢）."""
    conn = McpConnection(_stdio(_MODERN, "mod4"), call_timeout=10, probe_timeout_s=2)
    conn.connect()
    try:
        assert conn.transport._proc is not None
        conn.transport._proc.kill()
        conn.transport._proc.wait()
        result = conn.call_tool("echo", {"text": "after-death"})
        assert result["content"][0]["text"] == "echo:after-death"
        assert conn.profile is not None and conn.profile.is_modern  # era 复现（服务器属性）
    finally:
        conn.close()


def test_stdio_legacy_silent_probe_falls_back_within_budget():
    """对 server/discover 静默的旧服务器：探测超时回退 initialize，总等待不翻倍."""
    conn = McpConnection(
        McpServerSpec(
            name="silent_legacy",
            command=sys.executable,
            args=["-c", _SILENT_PROBE_LEGACY],
        ),
        call_timeout=1.0,
        probe_timeout_s=0.5,
    )
    t0 = time.monotonic()
    tools = conn.connect()
    elapsed = time.monotonic() - t0
    try:
        assert conn.profile is not None and not conn.profile.is_modern
        assert conn.profile.version == "2025-11-25"
        assert [t.name for t in tools] == ["echo"]
        assert elapsed < 3.0
    finally:
        conn.close()


_SILENT_PROBE_LEGACY = """
import json, sys
for line in sys.stdin:
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    m, mid = msg.get("method"), msg.get("id")
    if m == "server/discover":
        continue  # 静默：era 探测只能靠超时回退
    if m == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "serverInfo": {"name": "silent-legacy", "version": "1"}}}), flush=True)
    elif m == "tools/list":
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": {"tools": [
            {"name": "echo", "description": "", "inputSchema": {"type": "object"}}]}}), flush=True)
    elif m == "tools/call":
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": {
            "isError": False, "content": [{"type": "text", "text": "echo:"}]}}), flush=True)
"""


# ── HTTP 现代 ─────────────────────────────────────────────────────────
def test_http_modern_era_headers_and_sse(modern_http):
    """现代 HTTP：era 探测成功；每请求必需头由服务器强制校验；SSE 响应解析."""
    conn = McpConnection(_http("hm", modern_http.url), call_timeout=10, probe_timeout_s=2)
    tools = conn.connect()
    try:
        assert conn.profile is not None and conn.profile.is_modern
        assert conn.profile.http_session_id is None  # 现代无会话
        assert [t.name for t in tools] == ["echo", "get_seen", "boom"]  # 分页聚合
        # SSE 响应（服务器先推通知帧再推响应；通知不破坏解析）
        assert conn.call_tool("echo", {"text": "s"})["content"][0]["text"] == "echo:s"
        seen = json.loads(conn.call_tool("get_seen", {})["content"][0]["text"])
        assert seen["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
    finally:
        conn.close()


def test_http_modern_is_error_maps_failure(modern_http):
    conn = McpConnection(_http("hm2", modern_http.url), call_timeout=10, probe_timeout_s=2)
    conn.connect()
    try:
        assert conn.call_tool("boom", {})["isError"] is True
    finally:
        conn.close()


def test_http_modern_connection_refused_is_not_dispatched():
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    conn = McpConnection(_http("dead", f"http://127.0.0.1:{port}/mcp"), call_timeout=5, probe_timeout_s=1)
    with pytest.raises(McpNotDispatchedError):
        conn.connect()


# ── HTTP 旧时代 ───────────────────────────────────────────────────────
def test_http_legacy_fallback_session_and_call(legacy_http):
    """旧时代 HTTP：discover 404/-32601 → initialize 回退；会话头捕获并生效."""
    conn = McpConnection(_http("hl", legacy_http.url), call_timeout=10, probe_timeout_s=2)
    tools = conn.connect()
    try:
        assert conn.profile is not None and not conn.profile.is_modern
        assert conn.profile.version == "2025-11-25"
        assert conn.profile.http_session_id == "sess-1"
        assert [t.name for t in tools] == ["echo", "get_seen", "boom"]
        assert conn.call_tool("echo", {"text": "y"})["content"][0]["text"] == "echo:y"
    finally:
        conn.close()


def test_http_legacy_session_404_rehandshake_replays_once(legacy_http):
    """会话被服务器终结（404=请求未被处理）→ 重握手 + 重放一次（typed 恢复语义）."""
    conn = McpConnection(_http("hl2", legacy_http.url), call_timeout=10, probe_timeout_s=2)
    conn.connect()
    try:
        old_session = conn.profile.http_session_id
        legacy_http.state.kill_next_session.set()
        result = conn.call_tool("echo", {"text": "re"})
        assert result["content"][0]["text"] == "echo:re"
        assert conn.profile.http_session_id not in (None, old_session)
    finally:
        conn.close()


# ── 配置解析 ─────────────────────────────────────────────────────────
def test_parse_servers_http_and_stdio_entries():
    raw = json.dumps(
        [
            {"name": "s1", "command": "x"},
            {"name": "h1", "type": "http", "url": "http://127.0.0.1:9/mcp", "headers": {"Authorization": "Bearer t"}},
            {"name": "bad", "type": "http"},
            {"name": "weird", "type": "grpc"},
        ]
    )
    specs = parse_servers(raw)
    assert [s.name for s in specs] == ["s1", "h1"]
    assert specs[1].type == "http" and specs[1].url.endswith("/mcp")
    assert specs[1].headers == {"Authorization": "Bearer t"}
    assert specs[0].type == "stdio"


# ── 身份隔离（跨传输真实双服务器）────────────────────────────────────
def test_identity_isolation_across_transports(modern_http):
    """stdio 与 HTTP 服务器归一同名（dup.a / dup_a）→ digest 消歧，互不覆盖，均可执行."""
    raw = json.dumps(
        [
            {"name": "dup.a", "command": sys.executable, "args": [str(_LEGACY)]},
            {"name": "dup_a", "type": "http", "url": modern_http.url},
        ]
    )
    registry = ToolRegistry()
    registered = register_mcp_tools(registry, raw)
    try:
        # 2 服务器 × 3 工具；mcp_dup_a_echo 基础名只有一方可用，另一方带 digest 后缀
        assert len(registered) == 6
        base = [n for n in registered if n == "mcp_dup_a_echo"]
        suffixed = [n for n in registered if n.startswith("mcp_dup_a_echo_")]
        assert len(base) + len(suffixed) == 2
        for name in base + suffixed:
            r = registry.execute(ToolCall(id="c1", name=name, arguments={"text": "iso"}))
            assert r.status == ToolResultStatus.SUCCESS
            assert "echo:iso" in r.content
    finally:
        from llm_loop.tools.mcp_client import _close_server_conns

        _close_server_conns(registry, "dup.a")
        _close_server_conns(registry, "dup_a")


def test_register_mixed_transports_end_to_end(modern_http, legacy_http):
    raw = json.dumps(
        [
            {"name": "lstd", "command": sys.executable, "args": [str(_LEGACY)]},
            {"name": "mstd", "command": sys.executable, "args": [str(_MODERN)]},
            {"name": "mhttp", "type": "http", "url": modern_http.url},
            {"name": "lhttp", "type": "http", "url": legacy_http.url},
            {"name": "off", "command": "x", "enabled": False},
        ]
    )
    registry = ToolRegistry()
    registered = register_mcp_tools(registry, raw)
    try:
        assert len(registered) == 12  # 4 服务器 × 3 工具（禁用服务器不注册）
        r = registry.execute(ToolCall(id="c2", name="mcp_mstd_echo", arguments={"text": "m"}))
        assert r.status == ToolResultStatus.SUCCESS and "echo:m" in r.content
        r = registry.execute(ToolCall(id="c3", name="mcp_lhttp_echo", arguments={"text": "l"}))
        assert r.status == ToolResultStatus.SUCCESS and "echo:l" in r.content
    finally:
        from llm_loop.tools.mcp_client import _close_server_conns

        for server in ("lstd", "mstd", "mhttp", "lhttp"):
            _close_server_conns(registry, server)


def test_http_modern_sse_hang_is_outcome_unknown(modern_http):
    """SSE 打开后服务器挂起：读流超时 → McpOutcomeUnknownError（不重放）."""
    from llm_loop.tools.mcp_client import McpOutcomeUnknownError

    conn = McpConnection(_http("hz", modern_http.url), call_timeout=1.0, probe_timeout_s=2)
    conn.connect()
    try:
        t0 = time.monotonic()
        with pytest.raises(McpOutcomeUnknownError, match="结果未知"):
            conn.call_tool("hang_sse", {})
        assert time.monotonic() - t0 < 5.0  # 单次等待，不翻倍
    finally:
        conn.close()

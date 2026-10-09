"""T04：legacy HTTP+SSE 显式旧传输（P2-B，设计 §3/§12.2）.

- 显式入口：仅 spec type="sse" 使用该传输；缺 url 如实跳过。
- 跨 origin endpoint：fail-closed 拒绝；凭证（Authorization）只出现在
  同 origin 请求上（凭证不越 origin）。
- 会话失效（POST 404）→ 置 session_id=None 走既有重握手路径，重建流。
- 断流（POST 已受理后关流）→ 已派发、结果未知，不自动重放。
- 通知经 SSE 流上送 notification_handler。
"""

from __future__ import annotations

import json
import logging

from llm_loop.tools.mcp_client import McpConnection, McpServerSpec, parse_servers
from llm_loop.tools.mcp_protocol import McpOutcomeUnknownError, McpProtocolError
from llm_loop.tools.mcp_transport import LegacySseTransport, McpHttpError
from tests.fixtures.fake_mcp_legacy_sse_server import FakeMcpLegacySseServer

logger = logging.getLogger(__name__)


def _spec(srv: FakeMcpLegacySseServer, **kw) -> McpServerSpec:
    base = {
        "name": "legacy-demo",
        "type": "sse",
        "url": srv.sse_url,
        "headers": {"Authorization": "Bearer secret-token"},
    }
    base.update(kw)
    return McpServerSpec(
        name=base["name"],
        command="",
        type=base["type"],
        url=base["url"],
        headers=base.get("headers") or {},
        credential_ref=base.get("credential_ref"),
        enabled=base.get("enabled", True),
    )


def test_explicit_spec_entry_and_missing_url_skipped() -> None:
    """显式入口：type=sse 解析为 spec；缺 url 的条目如实跳过（不猜）."""
    raw = json.dumps(
        [
            {"name": "s1", "type": "sse", "url": "http://127.0.0.1:1/sse", "headers": {"A": "b"}},
            {"name": "s2", "type": "sse"},
            {"name": "s3", "type": "stdio", "command": "echo"},
        ]
    )
    specs = parse_servers(raw)
    assert [s.name for s in specs] == ["s1", "s3"]
    assert specs[0].type == "sse"
    assert specs[0].url == "http://127.0.0.1:1/sse"
    assert specs[0].headers == {"A": "b"}


def test_roundtrip_initialize_and_resources_over_stream() -> None:
    """同 origin 全链路：initialize/tools/resources 经 SSE 流往返."""
    with FakeMcpLegacySseServer() as srv:
        conn = McpConnection(_spec(srv))
        tools = conn.connect()
        assert tools == []  # tools/list=0
        assert conn.profile is not None
        assert conn.profile.supports("resources")
        assert conn.profile.supports("prompts")
        resources = conn.list_resources()
        assert {r["uri"] for r in resources} == {"memo://alpha", "memo://beta"}
        templates = conn.list_resource_templates()
        assert templates[0]["uriTemplate"] == "memo://{topic}"
        conn.close()


def test_cross_origin_endpoint_rejected_credentials_never_leave() -> None:
    """跨 origin endpoint → fail-closed；POST 从未发生（凭证不越 origin）."""
    with FakeMcpLegacySseServer() as srv:
        srv.state.endpoint_override = "http://evil.example:9527/msg?sessionId=evil"
        transport = LegacySseTransport(
            "evil-demo", srv.sse_url, headers={"Authorization": "Bearer secret-token"}
        )
        try:
            transport.send_request(
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, 5.0
            )
            raise AssertionError("跨 origin endpoint 未被拒绝")
        except McpProtocolError as exc:
            assert "跨 origin" in str(exc)
        finally:
            transport.close()
        # 凭证只出现在同 origin 的 GET 建流上；无任何 POST 发出
        assert any(s["kind"] == "GET" and s["auth"] == "Bearer secret-token" for s in srv.state.seen)
        assert all(s["kind"] == "GET" for s in srv.state.seen)


def test_session_404_invalidates_and_reestablishes_stream() -> None:
    """POST 404 → McpHttpError(404)；session_id=None 后重建流继续可用（重握手路径）."""
    with FakeMcpLegacySseServer() as srv:
        transport = LegacySseTransport("sess-demo", srv.sse_url)
        r = transport.send_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, 5.0)
        assert r == {"tools": [], "nextCursor": None}
        srv.state.posts_before_404 = srv.state.post_count  # 下一次 POST 起 404
        try:
            transport.send_request({"jsonrpc": "2.0", "id": 2, "method": "prompts/list", "params": {}}, 5.0)
            raise AssertionError("404 未如实抛出")
        except McpHttpError as exc:
            assert exc.status == 404
        # 会话失效路径：置 None 作废流；下次请求重建（新流新端点）后成功
        transport.session_id = None
        srv.state.posts_before_404 = None
        r2 = transport.send_request({"jsonrpc": "2.0", "id": 3, "method": "prompts/list", "params": {}}, 5.0)
        assert r2["prompts"][0]["name"] == "review"
        transport.close()


def test_stream_drop_yields_outcome_unknown_not_replay() -> None:
    """POST 已受理后关流 → 结果未知（已派发，不自动重放）."""
    with FakeMcpLegacySseServer() as srv:
        transport = LegacySseTransport("drop-demo", srv.sse_url)
        transport.send_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, 5.0)
        srv.state.drop_stream_ids = {2}
        try:
            transport.send_request({"jsonrpc": "2.0", "id": 2, "method": "resources/list", "params": {}}, 5.0)
            raise AssertionError("断流未按结果未知收尾")
        except McpOutcomeUnknownError:
            pass
        finally:
            transport.close()


def test_server_notification_reaches_handler() -> None:
    """SSE 流上的服务器通知经 notification_handler 上送（含 generation）."""
    with FakeMcpLegacySseServer() as srv:
        received: list[tuple[str, dict]] = []
        transport = LegacySseTransport("notif-demo", srv.sse_url)
        transport.notification_handler = lambda method, params, gen: received.append((method, params))
        transport.send_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, 5.0)
        srv.state.emit_notification("notifications/message", {"level": "warning", "data": "x"})
        import time

        for _ in range(50):
            if received:
                break
            time.sleep(0.1)
        assert received and received[0][0] == "notifications/message"
        transport.close()


def test_endpoint_missing_event_times_out_honestly() -> None:
    """建流后无 endpoint 事件 → 如实失败（不猜端点、不静默降级）."""
    import http.server
    import threading

    class NoEndpoint(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            import time

            for _ in range(60):  # 只发注释，永不发 endpoint
                self.wfile.write(b": warmup\n\n")
                self.wfile.flush()
                time.sleep(0.5)

        def log_message(self, *a) -> None:  # noqa: N802
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), NoEndpoint)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        host, port = server.server_address[:2]
        transport = LegacySseTransport("quiet", f"http://{host}:{port}/sse")
        transport.ENDPOINT_WAIT_TIMEOUT_S = 1.0
        try:
            transport.send_request({"jsonrpc": "2.0", "id": 1, "method": "x", "params": {}}, 2.0)
            raise AssertionError("缺 endpoint 未如实失败")
        except McpProtocolError as exc:
            assert "endpoint" in str(exc)
        finally:
            transport.close()
    finally:
        server.shutdown()

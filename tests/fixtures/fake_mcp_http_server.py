"""进程内 Streamable HTTP 测试服务器（现代 2026-07-28 / 旧时代 2025-11-25）.

- modern：单端点 POST；校验 Mcp-Method / MCP-Protocol-Version（须与
  params._meta 一致）/ tools/call 的 Mcp-Name；server/discover 返回
  DiscoverResult；未知版本 → 400 + JSON-RPC UnsupportedProtocolVersionError
  （data.supported，无 id）；未知方法 → 404 + -32601；通知 → 202；
  tools/call 以 SSE 返回（先推一个通知帧再推响应，锻炼客户端 SSE 解析）。
- legacy：initialize → 200 JSON + Mcp-Session-Id；后续请求须带会话头，
  失效 → 404（客户端应重握手重放一次）；tools/call SSE；通知 → 202。
- 分页：tools/list 每页 2 个（nextCursor 循环）。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MODERN_VERSION = "2026-07-28"
LEGACY_VERSION = "2025-11-25"
META_VERSION = "io.modelcontextprotocol/protocolVersion"


class _State:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.session_counter = 0
        self.valid_sessions: set[str] = set()
        self.kill_next_session = threading.Event()
        self.seen: dict[str, dict[str, Any]] = {"last_meta": {}, "headers": {}}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: _State

    def log_message(self, *args: Any) -> None:  # 静默
        return

    # ── 工具 ──
    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _send_json(self, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_rpc_error(self, status: int, code: int, message: str, data: Any = None, mid: Any = None) -> None:
        err: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        self._send_json(status, {"jsonrpc": "2.0", "id": mid, "error": err})

    def _send_sse(self, frames: list[dict[str, Any]]) -> None:
        chunks = []
        for frame in frames:
            payload = json.dumps(frame, ensure_ascii=False)
            chunks.append(f"data: {payload}\n\n")
        body = "".join(chunks).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "echo",
                "description": "http fixture echo",
                "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
            },
            {
                "name": "get_seen",
                "description": "http fixture last seen meta/headers",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "boom",
                "description": "http fixture isError",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]

    def _page(self, cursor: Any) -> dict[str, Any]:
        items = self._tools()
        idx = {"p2": 2}.get(cursor, 0)
        result: dict[str, Any] = {"tools": items[idx : idx + 2]}
        if idx + 2 < len(items):
            result["nextCursor"] = "p2"
        return result

    # ── 入口 ──
    def do_POST(self) -> None:  # noqa: N802
        msg = self._read_body()
        method = msg.get("method")
        mid = msg.get("id")
        state = self.state
        state.seen["headers"] = {k.lower(): v for k, v in self.headers.items()}
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        if isinstance(params.get("_meta"), dict):
            state.seen["last_meta"] = params["_meta"]

        if self.state.mode == "modern":
            self._handle_modern(msg, method, mid, params)
            return
        self._handle_legacy(msg, method, mid, params)

    # ── 现代 ──
    def _handle_modern(self, msg: dict, method: Any, mid: Any, params: dict) -> None:
        header_version = self.headers.get("MCP-Protocol-Version")
        header_method = self.headers.get("Mcp-Method")
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        body_version = meta.get(META_VERSION)
        if method == "subscriptions/listen":
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not isinstance(mid, int):
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if header_version != MODERN_VERSION or body_version != MODERN_VERSION:
            self._send_rpc_error(
                400,
                -32070,
                "UnsupportedProtocolVersionError: server does not support requested version",
                {"supported": [MODERN_VERSION]},
                mid=None,
            )
            return
        if header_method != str(method or ""):
            self._send_rpc_error(400, -32072, "HeaderMismatch: Mcp-Method must match body method", mid=mid)
            return
        if method == "server/discover":
            self._send_json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "supportedVersions": [MODERN_VERSION],
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake-http-modern", "version": "1.0"},
                    },
                },
            )
            return
        if method == "tools/list":
            self._send_json(200, {"jsonrpc": "2.0", "id": mid, "result": self._page(params.get("cursor"))})
            return
        if method == "tools/call":
            name = params.get("name")
            header_name = self.headers.get("Mcp-Name")
            if header_name != str(name or ""):
                self._send_rpc_error(400, -32072, "HeaderMismatch: Mcp-Name must match params.name", mid=mid)
                return
            if name == "echo":
                text = (params.get("arguments") or {}).get("text", "")
                self._send_sse(
                    [
                        {"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info"}},
                        {
                            "jsonrpc": "2.0",
                            "id": mid,
                            "result": {"isError": False, "content": [{"type": "text", "text": f"echo:{text}"}]},
                        },
                    ]
                )
                return
            if name == "hang_sse":
                # SSE 打开后挂起：锻炼客户端"读流超时=结果未知"映射
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(b"data: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/message\",\"params\":{}}\n\n")
                self.wfile.flush()
                import time as _t

                _t.sleep(30)
                return
            if name == "get_seen":
                self._send_sse(
                    [
                        {
                            "jsonrpc": "2.0",
                            "id": mid,
                            "result": {
                                "isError": False,
                                "content": [{"type": "text", "text": json.dumps(self.state.seen["last_meta"], ensure_ascii=False)}],
                            },
                        }
                    ]
                )
                return
            if name == "boom":
                self._send_sse(
                    [
                        {
                            "jsonrpc": "2.0",
                            "id": mid,
                            "result": {"isError": True, "content": [{"type": "text", "text": "http boom"}]},
                        }
                    ]
                )
                return
            self._send_rpc_error(400, -32602, f"Unknown tool: {name}", mid=mid)
            return
        self._send_rpc_error(404, -32601, f"Method not found: {method}", mid=mid)

    # ── 旧时代 ──
    def _handle_legacy(self, msg: dict, method: Any, mid: Any, params: dict) -> None:
        state = self.state
        if method == "initialize":
            state.session_counter += 1
            session = f"sess-{state.session_counter}"
            state.valid_sessions.add(session)
            self._send_json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "protocolVersion": LEGACY_VERSION,
                        "capabilities": {},
                        "serverInfo": {"name": "fake-http-legacy", "version": "1.0"},
                    },
                },
                headers={"Mcp-Session-Id": session},
            )
            return
        if method == "server/discover":
            # 旧时代服务器对未知方法的签名：404 + -32601（客户端据此回退 initialize）
            self._send_rpc_error(404, -32601, "Method not found: server/discover", mid=mid)
            return
        session = self.headers.get("Mcp-Session-Id")
        if state.kill_next_session.is_set():
            state.valid_sessions.discard(session)
            state.kill_next_session.clear()
        if session not in state.valid_sessions:
            self._send_rpc_error(404, -32001, "Session terminated", mid=mid)
            return
        if not isinstance(mid, int):
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if method == "tools/list":
            self._send_json(200, {"jsonrpc": "2.0", "id": mid, "result": self._page(params.get("cursor"))})
            return
        if method == "tools/call":
            name = params.get("name")
            if name == "echo":
                text = (params.get("arguments") or {}).get("text", "")
                self._send_sse(
                    [
                        {"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info"}},
                        {
                            "jsonrpc": "2.0",
                            "id": mid,
                            "result": {"isError": False, "content": [{"type": "text", "text": f"echo:{text}"}]},
                        },
                    ]
                )
                return
            if name == "boom":
                self._send_sse(
                    [
                        {
                            "jsonrpc": "2.0",
                            "id": mid,
                            "result": {"isError": True, "content": [{"type": "text", "text": "http boom"}]},
                        }
                    ]
                )
                return
            self._send_rpc_error(400, -32602, f"Unknown tool: {name}", mid=mid)
            return
        self._send_rpc_error(404, -32601, f"Method not found: {method}", mid=mid)


class FakeMcpHttpServer:
    """测试内嵌 HTTP MCP 服务器（线程化；url 属性即端点）."""

    def __init__(self, mode: str) -> None:
        assert mode in ("modern", "legacy")
        state = _State(mode)
        handler_class = type(f"Handler_{mode}", (Handler,), {"state": state})
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        self.state = state
        self.thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self.thread.start()
        host, port = self._httpd.server_address[:2]
        self.url = f"http://{host}:{port}/mcp"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self.thread.join(timeout=3)

"""进程内 legacy HTTP+SSE 测试服务器（旧时代官方流式形态，P2-B / T04）.

- GET /sse：text/event-stream 常驻流；首个 ``endpoint`` 事件下发消息端点
  （默认相对路径 ``/message?sessionId=…``；``endpoint_override`` 可注入
  跨 origin 恶意端点，锻炼 fail-closed 拒绝）。
- POST /message?sessionId=…：受理 JSON-RPC（202 Accepted）；响应帧经对应
  SSE 流回送（``event: message``）。响应也可以 direct JSON（200）——
  ``direct_json=True`` 切换，锻炼非 202 兜底。
- 方法：initialize（capabilities 含 resources/prompts、tools 空）、
  tools/list（空）、resources/list（两页 cursor）、resources/templates/list、
  resources/read（text/blob）、prompts/list、prompts/get（text + image +
  resource 块）、未知方法 → JSON-RPC -32601 错误帧（客户端 era 探测用）。
- 故障注入：``drop_stream_ids``（收下 POST 后关流不回，锻炼结果未知）、
  ``posts_before_404``（N 次 POST 后 404，锻炼会话失效重建）、
  ``endpoint_override``（跨 origin 拒绝）、``seen``（GET/POST 头与请求
  记录，供"凭证不越 origin"断言）。
- ``emit_notification(method, params)`` 向活跃流推送服务器通知。
"""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

LEGACY_VERSION = "2025-03-26"
BLOB_BYTES = b"\x00\x01\x02\xfflegacy-sse-blob"


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.streams: dict[str, queue.Queue[str | None]] = {}
        self.session_counter = 0
        # 故障注入
        self.endpoint_override: str | None = None
        self.drop_stream_ids: set[int] = set()
        self.posts_before_404: int | None = None
        self.direct_json: bool = False
        # 观测
        self.seen: list[dict[str, Any]] = []
        self.post_count = 0

    def emit_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        frame = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        self._broadcast(f"data: {json.dumps(frame)}\n\n")

    def _broadcast(self, payload: str) -> None:
        with self.lock:
            streams = list(self.streams.values())
        for q in streams:
            q.put(payload)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: _State

    def log_message(self, *args: Any) -> None:  # 静默
        return

    # ── SSE 流 ──
    def do_GET(self) -> None:
        if not self.path.startswith("/sse"):
            self.send_error(404)
            return
        state = self.state
        sid = f"s{state.session_counter}"
        state.session_counter += 1
        frames: queue.Queue[str | None] = queue.Queue()
        with state.lock:
            state.streams[sid] = frames
        state.seen.append({"kind": "GET", "path": self.path, "auth": self.headers.get("Authorization")})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        endpoint = state.endpoint_override or f"/message?sessionId={sid}"
        self.wfile.write(f"event: endpoint\ndata: {endpoint}\n\n".encode())
        self.wfile.flush()
        try:
            while True:
                try:
                    item = frames.get(timeout=1)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                if item is None:
                    break
                self.wfile.write(item.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with state.lock:
                state.streams.pop(sid, None)

    # ── 消息端点 ──
    def _reply_202(self) -> None:
        self.send_response(202)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        state = self.state
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(400)
            return
        state.post_count += 1
        state.seen.append(
            {
                "kind": "POST",
                "path": self.path,
                "auth": self.headers.get("Authorization"),
                "method": body.get("method"),
                "id": body.get("id"),
            }
        )
        if state.posts_before_404 is not None and state.post_count > state.posts_before_404:
            payload = json.dumps(
                {"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32001, "message": "session gone"}}
            )
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload.encode())
            return
        # 找到对应流
        sid = ""
        if "sessionId=" in self.path:
            sid = self.path.split("sessionId=", 1)[1].split("&", 1)[0]
        with state.lock:
            frames = state.streams.get(sid)
        if frames is None:
            self.send_error(404)
            return
        msg_id = body.get("id")
        if msg_id in state.drop_stream_ids:
            # 收下请求后直接关流（不回响应）：锻炼"已派发、结果未知"
            with state.lock:
                state.streams.pop(sid, None)
            frames.put(None)
            self._reply_202()
            return
        if "method" in body and msg_id is None:
            self._reply_202()  # 通知：受理即可
            return
        result = self._dispatch(str(body.get("method") or ""), body.get("params") or {})
        response = (
            {"jsonrpc": "2.0", "id": msg_id, "result": result}
            if result is not None
            else {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"method not found: {body.get('method')}"},
            }
        )
        payload = json.dumps(response)
        if state.direct_json:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload.encode())
            return
        self._reply_202()
        frames.put(f"event: message\ndata: {payload}\n\n")

    # ── 方法 ──
    def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if method == "initialize":
            return {
                "protocolVersion": LEGACY_VERSION,
                "capabilities": {
                    "resources": {"subscribe": True},
                    "prompts": {},
                    "tools": {},
                },
                "serverInfo": {"name": "pure-sse", "version": "1.0"},
            }
        if method == "tools/list":
            return {"tools": [], "nextCursor": None}
        if method == "resources/list":
            if not params.get("cursor"):
                return {
                    "resources": [
                        {
                            "uri": "memo://alpha",
                            "name": "alpha",
                            "description": "第一页",
                            "mimeType": "text/plain",
                        }
                    ],
                    "nextCursor": "p2",
                }
            return {
                "resources": [
                    {
                        "uri": "memo://beta",
                        "name": "beta",
                        "description": "第二页",
                        "mimeType": "text/plain",
                    }
                ],
                "nextCursor": None,
            }
        if method == "resources/templates/list":
            return {
                "resourceTemplates": [
                    {"uriTemplate": "memo://{topic}", "name": "memo", "description": "按主题"}
                ],
                "nextCursor": None,
            }
        if method == "resources/read":
            uri = str(params.get("uri") or "")
            if uri.startswith("bin://"):
                import base64

                return {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/octet-stream",
                            "blob": base64.b64encode(BLOB_BYTES).decode("ascii"),
                        }
                    ]
                }
            return {
                "contents": [
                    {"uri": uri, "mimeType": "text/plain", "text": f"内容-of-{uri}"}
                ]
            }
        if method == "prompts/list":
            return {
                "prompts": [
                    {
                        "name": "review",
                        "description": "评审提示",
                        "arguments": [{"name": "lang", "description": "语言", "required": True}],
                    }
                ],
                "nextCursor": None,
            }
        if method == "prompts/get":
            lang = (params.get("arguments") or {}).get("lang", "?")
            return {
                "description": "评审提示（demo）",
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": f"用 {lang} 评审以下补丁"}},
                    {
                        "role": "assistant",
                        "content": {
                            "type": "image",
                            "mimeType": "image/png",
                            "data": "aGk=",
                        },
                    },
                    {
                        "role": "user",
                        "content": {
                            "type": "resource",
                            "resource": {"uri": "memo://beta", "mimeType": "text/plain"},
                        },
                    },
                ],
            }
        return None


class FakeMcpLegacySseServer:
    """上下文管理器：启动/停止进程内 legacy SSE 服务器."""

    def __init__(self) -> None:
        self.state = _State()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def sse_url(self) -> str:
        assert self._httpd is not None, "服务器未启动"
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}/sse"

    def __enter__(self) -> FakeMcpLegacySseServer:
        handler = type("BoundHandler", (Handler,), {"state": self.state})
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()

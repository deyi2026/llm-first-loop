"""Loopback pages for the v0.6-A read-only typed-wait FCR smoke."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class FixtureServer:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("fixture server not started")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/"

    def __enter__(self) -> FixtureServer:
        task_id = self.task_id

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *args: Any) -> None:
                del args

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/state":
                    body = json.dumps({"task_id": task_id, "ok": True}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path != "/":
                    self.send_error(404)
                    return
                if task_id == "scope_ready":
                    html = """<!doctype html><html><head><title>Scope wait</title></head>
<body><main aria-label="Scope wait fixture"><p>Read-only scope fixture</p></main></body></html>"""
                elif task_id == "object_enabled":
                    html = """<!doctype html><html><head><title>Object wait</title></head>
<body><main><button id="ready" aria-label="Ready control" disabled>Ready control</button></main>
<script>setTimeout(() => { document.getElementById('ready').disabled = false; }, 8000);</script>
</body></html>"""
                else:
                    self.send_error(500)
                    return
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

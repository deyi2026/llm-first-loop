"""Real delayed loopback responses must survive the legacy one-second poll cap."""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from llm_loop.resources.task_budget_dispatch import bind_task_budget
from llm_loop.resources.task_budget_process_transport import (
    IsolatedTransportProfile,
    bind_isolated_provider_transport,
)
from tests.unit.test_task_budget_process_transport import _isolated_children
from tests.unit.test_task_budget_transport_stop import _budget, _real_client


@pytest.mark.parametrize("pause_phase", ["headers", "body"])
def test_isolated_request_survives_response_pause_over_one_second(
    tmp_path: Path, pause_phase: str,
) -> None:
    requests: list[int] = []
    body = (
        b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        b'data: [DONE]\n\n'
    )

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args: Any) -> None:
            pass

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler interface
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append(1)
            if pause_phase == "headers":
                time.sleep(1.3)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.flush()
                if pause_phase == "body":
                    time.sleep(1.3)
                self.wfile.write(body)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    host = threading.Thread(target=server.serve_forever, daemon=True)
    host.start()
    budget = _budget(tmp_path)
    client = _real_client(server.server_port)
    client.timeout_s = 120.0
    try:
        with bind_task_budget(budget), bind_isolated_provider_transport(
            IsolatedTransportProfile()
        ):
            reply = client.chat(messages=[{"role": "user", "content": "local"}], tools=[])
        assert reply.content == "ok"
        assert requests == [1]
        assert not _isolated_children()
    finally:
        client.close()
        budget.request_stop(reason="test_cleanup")
        server.shutdown()
        server.server_close()
        host.join(timeout=1.0)

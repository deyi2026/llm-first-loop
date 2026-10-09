"""I5-C: authenticated loopback TLS/HTTP1 physical-stop evidence only.

No external provider or proxy traffic. Test-only certificates are generated
at runtime in pytest's temporary directory, never checked into the repo.
"""

from __future__ import annotations

import shutil
import ssl
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from llm_loop.llm.client import LLMClient
from llm_loop.resources.task_budget_dispatch import (
    cancel_active_task_budget,
    register_active_task_budget,
    unregister_active_task_budget,
)
from tests.unit.test_task_budget_transport_stop import _budget, _in_thread


@pytest.fixture(scope="module")
def _test_cert(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    openssl = shutil.which("openssl")
    assert openssl is not None, "I5-C TLS qualification requires openssl"
    directory = tmp_path_factory.mktemp("i5c-loopback-cert")
    cert, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run(  # noqa: S603 - literal binary from PATH; no dynamic shell
        [
            openssl, "req", "-x509", "-newkey", "rsa:2048", "-sha256",
            "-nodes", "-days", "1", "-subj", "/CN=localhost",
            "-addext", "subjectAltName=IP:127.0.0.1,DNS:localhost",
            "-keyout", str(key), "-out", str(cert),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=6,
    )
    return cert, key


class _TlsState:
    def __init__(self) -> None:
        self.response_started = threading.Event()
        self.peer_closed = threading.Event()
        self.requests = 0


@contextmanager
def _loopback_https(cert: Path, key: Path) -> Iterator[tuple[_TlsState, int]]:
    state = _TlsState()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args: object) -> None:
            pass

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler
            state.requests += 1
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b": tls-connected\n\n")
            self.wfile.flush()
            state.response_started.set()
            self.connection.settimeout(3)
            try:
                if self.rfile.read(1) == b"":
                    state.peer_closed.set()
            except (OSError, ValueError):
                # SSL EOF/reset is also a socket-level teardown fact.
                state.peer_closed.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


@pytest.mark.parametrize("protocol", ["openai", "anthropic", "google", "lms-chat"])
def test_tls_verified_http1_stop_exits_reader_and_keeps_unknown(
    tmp_path: Path, _test_cert: tuple[Path, Path], protocol: str,
) -> None:
    cert, key = _test_cert
    execution = _budget(tmp_path)
    register_active_task_budget(execution)
    try:
        with _loopback_https(cert, key) as (peer, port):
            client = LLMClient(
                api_key="k", base_url=f"https://127.0.0.1:{port}/v1",
                model="glm-5.3", provider="glm", wire_protocol=protocol,
                timeout_s=8, max_tokens=16, thinking_mode=False, retry_disconnect=0,
            )
            client._client.close()
            trusted = ssl.create_default_context(cafile=str(cert))
            client._client = httpx.Client(
                verify=trusted, trust_env=False, http2=False, timeout=8,
            )
            try:
                worker, done, outcome = _in_thread(client, execution)
                assert peer.response_started.wait(2), "TLS handshake or POST did not finish"
                assert cancel_active_task_budget("session-A", "run-A", reason="user_stop")
                assert done.wait(1), "TLS SSLSocket read was not physically interrupted"
                assert peer.peer_closed.wait(1), "TLS peer did not see connection termination"
                worker.join(timeout=0.2)
                assert outcome == ["TaskBudgetDeniedError"]
                assert peer.requests == 1
            finally:
                client.close()
    finally:
        unregister_active_task_budget(execution)
    report = execution.store.report(execution.budget_id)
    assert report["phase"] == "stop_requested"
    assert report["physical_quiescence_verified"] is False
    assert len(report["outstanding_or_unknown"]) == 1
    assert next(iter(execution.store.read(execution.budget_id)["reservations"].values()))["phase"] == "unknown"

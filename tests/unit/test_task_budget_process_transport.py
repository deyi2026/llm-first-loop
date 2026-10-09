"""I5-D: per-attempt OS process exit under real loopback HTTP blocking.

Zero public Provider traffic. A locally owned independent child performs
one real HTTP POST and cannot access its parent's TaskBudget ledger.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from llm_loop.llm.client import LLMClient
from llm_loop.resources.task_budget_dispatch import (
    bind_task_budget,
    cancel_active_task_budget,
    register_active_task_budget,
    unregister_active_task_budget,
)
from llm_loop.resources.task_budget_process_transport import (
    IsolatedTransportProfile,
    bind_isolated_provider_transport,
)
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError
from tests.unit.test_task_budget_transport_stop import _budget, _local_sse, _real_client
from tests.unit.test_task_budget_unqualified_transports import _no_forward_connect_server


def _run_isolated(
    client: LLMClient, budget: object, profile: IsolatedTransportProfile,
) -> tuple[threading.Thread, threading.Event, list[str]]:
    done = threading.Event()
    outcome: list[str] = []

    def run() -> None:
        try:
            with bind_task_budget(budget), bind_isolated_provider_transport(profile):
                client.chat(messages=[{"role": "user", "content": "local"}], tools=[])
            outcome.append("unexpected_success")
        except Exception as exc:  # noqa: BLE001 - exact test outcome only
            outcome.append(type(exc).__name__)
        finally:
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, done, outcome


def _isolated_children() -> list[multiprocessing.Process]:
    return [
        p for p in multiprocessing.active_children()
        if p.name == "task-budget-provider-isolate"
    ]


@pytest.mark.parametrize("protocol", ["openai", "anthropic", "google", "lms-chat"])
def test_real_sse_stop_kills_exact_worker_and_keeps_unknown(
    tmp_path: Path, protocol: str,
) -> None:
    budget = _budget(tmp_path)
    register_active_task_budget(budget)
    try:
        with _local_sse("hold") as (peer, port):
            client = _real_client(port, protocol=protocol)
            try:
                worker, done, outcome = _run_isolated(
                    client, budget, IsolatedTransportProfile()
                )
                assert peer.started.wait(5), "child did not complete the local HTTP POST"
                children = _isolated_children()
                assert len(children) == 1
                active_pid = children[0].pid
                assert isinstance(active_pid, int)
                started = time.monotonic()
                assert cancel_active_task_budget("session-A", "run-A", reason="user_stop")
                assert done.wait(2.0), "reader still blocked in child transport"
                assert peer.peer_closed.wait(2.0), "local network peer did not see EOF"
                assert time.monotonic() - started < 3
                worker.join(timeout=0.2)
                assert outcome == ["TaskBudgetDeniedError"]
                assert peer.requests == 1
                assert not any(child.pid == active_pid for child in _isolated_children())
            finally:
                client.close()
    finally:
        # If an assertion fails, do not strand an off-process Provider call.
        if not budget._local_stop.is_set():
            budget.request_stop(reason="test_cleanup")
        unregister_active_task_budget(budget)
    report = budget.store.report(budget.budget_id)
    assert report["phase"] == "stop_requested"
    assert report["physical_quiescence_verified"] is False
    assert len(report["outstanding_or_unknown"]) == 1
    assert next(iter(budget.store.read(budget.budget_id)["reservations"].values()))["phase"] == "unknown"


def test_stop_terminates_child_before_response_headers(tmp_path: Path) -> None:
    budget = _budget(tmp_path)
    with _local_sse("no_headers") as (peer, port):
        client = _real_client(port)
        try:
            worker, done, outcome = _run_isolated(client, budget, IsolatedTransportProfile())
            assert peer.started.wait(5)
            start = time.monotonic()
            budget.request_stop(reason="user_stop")
            assert done.wait(1.8), "pre-response child was not terminated"
            assert peer.peer_closed.wait(2)
            assert time.monotonic() - start < 2.4
            worker.join(timeout=0.2)
            assert outcome == ["TaskBudgetDeniedError"]
        finally:
            client.close()
    report = budget.store.report(budget.budget_id)
    assert report["phase"] == "stop_requested"
    assert len(report["outstanding_or_unknown"]) == 1
    assert report["physical_quiescence_verified"] is False


def test_stop_terminates_connect_worker_without_proxy_forwarding(tmp_path: Path) -> None:
    budget = _budget(tmp_path)
    with _no_forward_connect_server() as (proxy, port):
        # The listener acknowledges the CONNECT request but never returns
        # a tunnel or forwards a byte to the specified target.
        client = LLMClient(
            api_key="k", base_url="https://127.0.0.1:1/v1", model="glm-5.3",
            provider="glm", wire_protocol="openai", thinking_mode=False,
            trust_env=False, retry_disconnect=0, timeout_s=8,
        )
        try:
            worker, done, outcome = _run_isolated(
                client, budget,
                IsolatedTransportProfile(proxy=f"http://127.0.0.1:{port}"),
            )
            assert proxy.accepted.wait(5)
            assert proxy.request_line.startswith(b"CONNECT 127.0.0.1:1")
            budget.request_stop(reason="user_stop")
            assert done.wait(2), "CONNECT worker survived parent Stop"
            assert proxy.peer_closed.wait(2)
            worker.join(timeout=0.2)
            assert outcome == ["TaskBudgetDeniedError"]
        finally:
            client.close()
    report = budget.store.report(budget.budget_id)
    assert len(report["outstanding_or_unknown"]) == 1
    assert report["physical_quiescence_verified"] is False


def test_no_budget_rejects_isolated_profile_before_network() -> None:
    client = _real_client(1)
    try:
        with bind_isolated_provider_transport(IsolatedTransportProfile()), pytest.raises(
            TaskBudgetDeniedError, match="isolated_transport_requires_budget"
        ):
            client.chat(messages=[{"role": "user", "content": "x"}], tools=[])
    finally:
        client.close()
    assert not _isolated_children()


def test_profile_rejects_implicit_tls_bypass_and_nonlocal_plain_http() -> None:
    with pytest.raises(ValueError, match="tls_verify_required"):
        IsolatedTransportProfile(verify=False)


def test_scope_not_leaked_to_sibling_thread_and_isolation_is_explicit(tmp_path: Path) -> None:
    assert not _isolated_children()
    budget = _budget(tmp_path)
    with bind_task_budget(budget), bind_isolated_provider_transport(
        IsolatedTransportProfile()
    ):
        # Python ContextVars intentionally do NOT propagate to new raw
        # threads. The parent must explicitly qualify the Run thread.
        observed: list[object] = []
        from llm_loop.resources.task_budget_process_transport import _ISOLATED_PROFILE

        peer = threading.Thread(target=lambda: observed.append(_ISOLATED_PROFILE.get()))
        peer.start()
        peer.join(timeout=1)
        assert observed == [None]


def test_full_sse_response_preserves_usage_shape_and_exact_content(tmp_path: Path) -> None:
    budget = _budget(tmp_path)
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args: object) -> None:
            pass

        def do_POST(self) -> None:  # noqa: N802
            requests.append(self.path)
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            line = (
                b'data: {"model":"glm-5.3","choices":[{"delta":{"content":"hello"},'
                b'"finish_reason":"stop"}],"usage":{"prompt_tokens":2,'
                b'"completion_tokens":1}}\n\n'
                b"data: [DONE]\n\n"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(line)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(line)
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    host = threading.Thread(target=server.serve_forever, daemon=True)
    host.start()
    try:
        client = _real_client(server.server_port)
        try:
            with bind_task_budget(budget), bind_isolated_provider_transport(
                IsolatedTransportProfile()
            ):
                output = client.chat(messages=[{"role": "user", "content": "x"}], tools=[])
            assert output.content == "hello"
            assert output.prompt_tokens == 2
            assert output.completion_tokens == 1
        finally:
            client.close()
    finally:
        server.shutdown()
        server.server_close()
        host.join(timeout=1)
    assert requests == ["/v1/chat/completions"]
    assert _isolated_children() == []
    # Full local response is still NOT a verified remote money settlement.
    report = budget.store.report(budget.budget_id)
    assert report["physical_quiescence_verified"] is False
    assert len(report["outstanding_or_unknown"]) == 1


def test_stop_run_a_never_terminates_sibling_run_b(tmp_path: Path) -> None:
    a = _budget(tmp_path / "a", session_id="session-A", run_generation="run-A")
    b = _budget(tmp_path / "b", session_id="session-B", run_generation="run-B")
    register_active_task_budget(a)
    register_active_task_budget(b)
    try:
        with _local_sse("hold") as (peer_a, port_a), _local_sse("hold") as (peer_b, port_b):
            client_a, client_b = _real_client(port_a), _real_client(port_b)
            try:
                worker_a, done_a, outcome_a = _run_isolated(
                    client_a, a, IsolatedTransportProfile()
                )
                worker_b, done_b, outcome_b = _run_isolated(
                    client_b, b, IsolatedTransportProfile()
                )
                assert peer_a.started.wait(5) and peer_b.started.wait(5)
                children = _isolated_children()
                assert len(children) == 2
                assert cancel_active_task_budget("session-A", "run-A", reason="user_stop")
                assert done_a.wait(2)
                assert not done_b.wait(0.2), "run-A Stop improperly killed run-B"
                assert not peer_b.peer_closed.is_set()
                assert cancel_active_task_budget("session-B", "run-B", reason="user_stop")
                assert done_b.wait(2)
                assert peer_a.peer_closed.wait(2)
                assert peer_b.peer_closed.wait(2)
                worker_a.join(timeout=0.2)
                worker_b.join(timeout=0.2)
                assert outcome_a == outcome_b == ["TaskBudgetDeniedError"]
            finally:
                for budget in (a, b):
                    if not budget._local_stop.is_set():
                        budget.request_stop(reason="test_cleanup")
                client_a.close()
                client_b.close()
    finally:
        unregister_active_task_budget(a)
        unregister_active_task_budget(b)
    assert _isolated_children() == []
    for budget in (a, b):
        report = budget.store.report(budget.budget_id)
        assert len(report["outstanding_or_unknown"]) == 1
        assert report["physical_quiescence_verified"] is False


def test_worker_unexpected_exit_does_not_mark_remote_settlement(tmp_path: Path) -> None:
    budget = _budget(tmp_path)
    with _local_sse("hold") as (peer, port):
        client = _real_client(port)
        try:
            worker, done, outcome = _run_isolated(
                client, budget, IsolatedTransportProfile()
            )
            assert peer.started.wait(5)
            children = _isolated_children()
            assert len(children) == 1
            children[0].kill()
            assert done.wait(3)
            worker.join(timeout=0.2)
            assert outcome == ["LLMNetworkError"]
        finally:
            if not budget._local_stop.is_set():
                budget.request_stop(reason="test_cleanup")
            client.close()
    report = budget.store.report(budget.budget_id)
    assert len(report["outstanding_or_unknown"]) == 1
    assert report["physical_quiescence_verified"] is False


def test_open_failure_surfaces_worker_exception_kind(tmp_path: Path) -> None:
    """Incident 2026-10-09 14:14: the worker sent type(exc).__name__ but the
    parent discarded it, leaving an unattributable open failure."""
    import socket

    import httpx

    from llm_loop.resources.task_budget_process_transport import (
        IsolatedTransportError,
        isolated_provider_stream,
    )

    budget = _budget(tmp_path)
    with socket.create_server(("127.0.0.1", 0)) as listener:
        closed_port = listener.getsockname()[1]
    with bind_task_budget(budget), bind_isolated_provider_transport(
        IsolatedTransportProfile()
    ), httpx.Client() as http, pytest.raises(
        IsolatedTransportError
    ) as excinfo, isolated_provider_stream(
        http, "POST", f"http://127.0.0.1:{closed_port}/v1/chat/completions",
        json={"model": "glm-5.3"}, headers={}, timeout=5.0,
    ):
        pytest.fail("a closed loopback port must fail to open")
    assert str(excinfo.value) == "isolated_transport_open_failed:ConnectError"
    assert not _isolated_children()


def test_midstream_worker_error_surfaces_exception_kind(tmp_path: Path) -> None:
    import http.server
    import threading

    import httpx

    from llm_loop.resources.task_budget_process_transport import (
        IsolatedTransportError,
        isolated_provider_stream,
    )

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args: object) -> None:
            pass

        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", "64")
            self.end_headers()
            self.wfile.write(b"data: truncated\n\n")
            self.wfile.flush()
            self.close_connection = True

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    budget = _budget(tmp_path)
    try:
        with bind_task_budget(budget), bind_isolated_provider_transport(
            IsolatedTransportProfile()
        ), httpx.Client() as http, pytest.raises(
            IsolatedTransportError
        ) as excinfo, isolated_provider_stream(
            http, "POST",
            f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
            json={"model": "glm-5.3"}, headers={}, timeout=5.0,
        ) as response:
            response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)
    assert str(excinfo.value) == "isolated_transport_worker_error:RemoteProtocolError"
    assert not _isolated_children()


def test_explicit_loopback_proxy_carries_one_sse_attempt(tmp_path: Path) -> None:
    """End-to-end over loopback: the worker egresses ONLY through the
    explicit profile proxy, and the full SSE round-trip still succeeds."""
    import select
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlsplit

    budget = _budget(tmp_path)
    connects: list[str] = []

    class OriginHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args: object) -> None:
            pass

        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = (
                b'data: {"model":"glm-5.3","choices":[{"delta":{"content":"via-proxy"},'
                b'"finish_reason":"stop"}],"usage":{"prompt_tokens":3,'
                b'"completion_tokens":1}}\n\ndata: [DONE]\n\n'
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

    origin = ThreadingHTTPServer(("127.0.0.1", 0), OriginHandler)
    origin.daemon_threads = True
    origin_thread = threading.Thread(target=origin.serve_forever, daemon=True)
    origin_thread.start()

    listener = socket.create_server(("127.0.0.1", 0))

    def proxy_worker() -> None:
        while True:
            try:
                conn, _peer = listener.accept()
            except OSError:
                return
            try:
                head = b""
                while b"\r\n\r\n" not in head:
                    chunk = conn.recv(4096)
                    if not chunk:
                        raise ConnectionError("proxy client vanished")
                    head += chunk
                request_line = head.split(b"\r\n", 1)[0].decode("latin1")
                method, absolute, _version = request_line.split(" ", 2)
                parts = urlsplit(absolute)
                upstream = socket.create_connection(
                    (parts.hostname, parts.port or 80), timeout=5,
                )
                connects.append(f"{parts.hostname}:{parts.port}")
                origin_form = f"{method} {parts.path or '/'} HTTP/1.1\r\n".encode()
                upstream.sendall(origin_form + head.split(b"\r\n", 1)[1])
                pair = [conn, upstream]
                while pair:
                    readable, _w, _e = select.select(pair, [], [], 10)
                    if not readable:
                        break
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            pair = []
                            break
                        (upstream if source is conn else conn).sendall(data)
                upstream.close()
            except OSError:
                pass
            finally:
                conn.close()

    proxy_thread = threading.Thread(target=proxy_worker, daemon=True)
    proxy_thread.start()
    client = _real_client(origin.server_port)
    try:
        with bind_task_budget(budget), bind_isolated_provider_transport(
            IsolatedTransportProfile(
                proxy=f"http://127.0.0.1:{listener.getsockname()[1]}"
            )
        ):
            output = client.chat(
                messages=[{"role": "user", "content": "via proxy"}], tools=[],
            )
        assert output.content == "via-proxy"
        assert output.prompt_tokens == 3
    finally:
        client.close()
        listener.close()
        origin.shutdown()
        origin.server_close()
        origin_thread.join(timeout=1.0)
    assert connects == [f"127.0.0.1:{origin.server_port}"]
    assert not _isolated_children()

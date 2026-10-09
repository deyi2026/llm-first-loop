"""I5-C negative qualification: no false physical-close claim for H2/DNS/CONNECT.

The CONNECT fixture accepts only a local request and NEVER forwards traffic.
The DNS fixture intercepts Python resolution before any external lookup.
"""

from __future__ import annotations

import socket
import socketserver
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from llm_loop.llm.client import LLMClient, _iter_task_budget_checked_lines
from llm_loop.resources.task_budget_dispatch import bind_task_budget, checked_provider_attempt
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError
from tests.unit.test_task_budget_transport_stop import _budget, _in_thread


@pytest.mark.parametrize("version", [b"HTTP/2", b"HTTP/3"])
def test_bound_multiplexed_response_denies_before_reading_sse(
    tmp_path: Path, version: bytes,
) -> None:
    budget = _budget(tmp_path)

    class FakeMultiplexedResponse:
        extensions = {"http_version": version}
        reads = 0

        def iter_lines(self) -> Iterator[str]:
            self.reads += 1
            yield "data: not safe to deliver"

    response = FakeMultiplexedResponse()
    with bind_task_budget(budget), pytest.raises(
        TaskBudgetDeniedError, match="multiplexed_transport_unqualified"
    ), checked_provider_attempt():
        list(_iter_task_budget_checked_lines(response))  # type: ignore[arg-type]
    assert response.reads == 0
    report = budget.store.report(budget.budget_id)
    assert report["phase"] == "stop_requested"
    assert report["physical_quiescence_verified"] is False
    assert len(report["outstanding_or_unknown"]) == 1


def test_unbound_http2_preserves_legacy_stream_semantics() -> None:
    response = httpx.Response(
        200, content=b"data: normal\n\n",
        extensions={"http_version": b"HTTP/2"},
    )
    assert "data: normal" in list(_iter_task_budget_checked_lines(response))


def test_dns_resolution_stall_is_not_misreported_as_physical_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = _budget(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = socket.getaddrinfo

    def blocked_resolution(host: str | bytes, *args: object, **kwargs: object):
        if host not in ("blocked.invalid", b"blocked.invalid"):
            return original(host, *args, **kwargs)
        entered.set()
        assert release.wait(2.0), "test harness DNS stall release did not run"
        raise socket.gaierror(socket.EAI_NONAME, "injected local resolver failure")

    client = LLMClient(
        api_key="k", base_url="https://blocked.invalid/v1", provider="glm",
        model="glm-5.3", timeout_s=8, max_tokens=16, thinking_mode=False,
        trust_env=False, retry_disconnect=0,
    )
    try:
        with monkeypatch.context() as patch:
            patch.setattr(socket, "getaddrinfo", blocked_resolution)
            worker, done, outcome = _in_thread(client, budget)
            assert entered.wait(1.2), "expected intercepted resolver was not entered"
            budget.request_stop(reason="user_stop")
            # Python's synchronous resolver is not cancellable by an HTTPX
            # idle I/O deadline or a post-response socket shutdown handle.
            assert not done.wait(0.15)
            release.set()
            assert done.wait(2)
            worker.join(timeout=0.2)
            assert outcome and outcome != ["unexpected_success"]
    finally:
        release.set()
        client.close()
    report = budget.store.report(budget.budget_id)
    assert report["phase"] == "stop_requested"
    assert report["physical_quiescence_verified"] is False
    assert len(report["outstanding_or_unknown"]) == 1


class _ConnectOnlyState:
    def __init__(self) -> None:
        self.accepted = threading.Event()
        self.peer_closed = threading.Event()
        self.request_line = b""


@contextmanager
def _no_forward_connect_server() -> Iterator[tuple[_ConnectOnlyState, int]]:
    state = _ConnectOnlyState()

    class ConnectOnly(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            self.request.settimeout(3)
            received = b""
            while b"\r\n\r\n" not in received and len(received) < 8192:
                chunk = self.request.recv(1024)
                if not chunk:
                    return
                received += chunk
            state.request_line = received.split(b"\r\n", 1)[0]
            state.accepted.set()
            # No HTTP CONNECT success response; absolutely no relay target.
            try:
                if self.request.recv(1) == b"":
                    state.peer_closed.set()
            except (OSError, ValueError):
                state.peer_closed.set()

    class LocalServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = LocalServer(("127.0.0.1", 0), ConnectOnly)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_stalled_connect_proxy_waits_for_timeout_not_fake_stop_ack(tmp_path: Path) -> None:
    budget = _budget(tmp_path)
    with _no_forward_connect_server() as (proxy, port):
        client = LLMClient(
            api_key="k", base_url="https://127.0.0.1:443/v1",
            provider="glm", model="glm-5.3", timeout_s=8,
            max_tokens=16, thinking_mode=False, trust_env=False,
            retry_disconnect=0,
        )
        client._client.close()
        client._client = httpx.Client(
            proxy=f"http://127.0.0.1:{port}", verify=False,
            trust_env=False, timeout=8,
        )
        try:
            worker, done, outcome = _in_thread(client, budget)
            assert proxy.accepted.wait(1.5)
            assert proxy.request_line.startswith(b"CONNECT 127.0.0.1:443")
            budget.request_stop(reason="user_stop")
            assert not done.wait(0.1), "CONNECT pre-response lacks an abort handle"
            assert done.wait(2), "bounded HTTPX timeout did not end CONNECT stall"
            worker.join(timeout=0.2)
            assert outcome and outcome != ["unexpected_success"]
            assert proxy.peer_closed.wait(1)
        finally:
            client.close()
    report = budget.store.report(budget.budget_id)
    assert report["phase"] == "stop_requested"
    assert report["physical_quiescence_verified"] is False
    assert len(report["outstanding_or_unknown"]) == 1

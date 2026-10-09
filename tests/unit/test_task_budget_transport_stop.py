"""I5-B: real loopback HTTP/1 SSE exit, never an actual Provider API."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from llm_loop.llm.client import LLMClient
from llm_loop.resources.task_budget_contracts import (
    TaskBudgetCapabilities,
    TaskBudgetGrant,
    TaskBudgetLimits,
    TaskBudgetMember,
)
from llm_loop.resources.task_budget_dispatch import (
    TaskBudgetExecution,
    active_task_budget,
    bind_task_budget,
    cancel_active_task_budget,
    register_active_task_budget,
    unregister_active_task_budget,
)
from llm_loop.resources.task_budget_store import TaskBudgetStore
from llm_loop.resources.task_budget_transport import (
    _physical_abort,
    budgeted_transport_timeout,
)


def _budget(
    tmp_path: Path, *, expires_in: float = 15.0,
    session_id: str = "session-A", run_generation: str = "run-A",
) -> TaskBudgetExecution:
    store = TaskBudgetStore(tmp_path / "ledger")
    grant = TaskBudgetGrant(
        budget_id="physical-local-sse",
        issuer="offline-operator",
        authority_source="offline-fixture",
        workspace_scope="offline-scope",
        session_id=session_id,
        human_turn_ref="human-A",
        surface="offline_test",
        profile="I5B-loopback",
        policy_version="I5-B-v1",
        deadline_epoch_s=time.time() + expires_in,
        limits=TaskBudgetLimits(
            logical_calls=1, physical_attempts=1, rounds=1, tool_invocations=0,
        ),
        capabilities=TaskBudgetCapabilities(allowed_tools=frozenset()),
    )
    row = store.issue_root(grant, root_run_generation=run_generation, ingress_kind="web")
    row = store.activate(grant.budget_id, expected_revision=row["revision"])
    member = TaskBudgetMember.from_dict(row["members"][grant.budget_id])
    return TaskBudgetExecution(store=store, budget_id=grant.budget_id, member=member)


class _LocalState:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.peer_closed = threading.Event()
        self.requests = 0


@contextmanager
def _local_sse(mode: str):
    state = _LocalState()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args: Any) -> None:
            pass

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler interface
            state.requests += 1
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if mode != "no_headers":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(b": ready\n\n")
                self.wfile.flush()
            state.started.set()
            if mode == "drip":
                for _ in range(150):
                    try:
                        self.wfile.write(b": still-here\n\n")
                        self.wfile.flush()
                    except (OSError, ValueError):
                        state.peer_closed.set()
                        return
                    time.sleep(0.03)
                return
            self.connection.settimeout(5)
            try:
                if self.rfile.read(1) == b"":
                    state.peer_closed.set()
            except (ConnectionResetError, BrokenPipeError):
                state.peer_closed.set()
            except TimeoutError:
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)


def _real_client(port: int, *, protocol: str = "openai") -> LLMClient:
    client = LLMClient(
        api_key="k", base_url=f"http://127.0.0.1:{port}/v1",
        model="glm-5.3", provider="glm", wire_protocol=protocol,
        timeout_s=8.0, max_tokens=12, thinking_mode=False, retry_disconnect=0,
    )
    client._client.close()
    client._client = httpx.Client(timeout=8.0, trust_env=False)
    return client


def _in_thread(client: LLMClient, execution: TaskBudgetExecution):
    finished = threading.Event()
    result: list[str] = []

    def run() -> None:
        try:
            with bind_task_budget(execution):
                client.chat(messages=[{"role": "user", "content": "local"}], tools=[])
            result.append("unexpected_success")
        except Exception as exc:  # noqa: BLE001 - evidence captures exact physical outcome
            result.append(type(exc).__name__)
        finally:
            finished.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, finished, result


@pytest.mark.parametrize("protocol", ["openai", "anthropic", "google", "lms-chat"])
def test_owner_stop_physically_exits_blocked_sse_and_retains_unknown(
    tmp_path: Path, protocol: str,
) -> None:
    execution = _budget(tmp_path)
    register_active_task_budget(execution)
    try:
        with _local_sse("hold") as (server, port):
            client = _real_client(port, protocol=protocol)
            try:
                worker, finished, outcome = _in_thread(client, execution)
                assert server.started.wait(2), "Provider did not reach physical POST"
                # Test the exact BackgroundRunner cancellation handoff, not
                # an in-memory flag or a synthetic exception in the iterator.
                start = time.monotonic()
                assert cancel_active_task_budget("session-A", "run-A", reason="user_stop")
                assert finished.wait(1.0), "blocked HTTP reader remained alive after Stop"
                assert server.peer_closed.wait(1.0), "local peer did not see physical disconnect"
                assert time.monotonic() - start < 2.0
                worker.join(timeout=0.2)
                assert outcome == ["TaskBudgetDeniedError"]
                assert server.requests == 1
            finally:
                client.close()
    finally:
        unregister_active_task_budget(execution)
    report = execution.store.report(execution.budget_id)
    assert report["phase"] == "stop_requested"
    assert report["physical_quiescence_verified"] is False
    assert len(report["outstanding_or_unknown"]) == 1
    row = execution.store.read(execution.budget_id)
    assert list(row["reservations"].values())[0]["phase"] == "unknown"
    assert active_task_budget() is None


def test_foreign_run_stop_cannot_close_owners_socket(tmp_path: Path) -> None:
    execution = _budget(tmp_path)
    register_active_task_budget(execution)
    try:
        with _local_sse("hold") as (server, port):
            client = _real_client(port)
            try:
                worker, finished, outcome = _in_thread(client, execution)
                assert server.started.wait(2)
                assert not cancel_active_task_budget("other", "run-A", reason="wrong")
                assert not cancel_active_task_budget("session-A", "other", reason="wrong")
                assert not finished.wait(0.15), "foreign Stop disrupted owner socket"
                assert cancel_active_task_budget("session-A", "run-A", reason="user_stop")
                assert finished.wait(1.0)
                assert outcome == ["TaskBudgetDeniedError"]
                worker.join(timeout=0.2)
            finally:
                client.close()
    finally:
        unregister_active_task_budget(execution)


def test_two_live_runs_stop_only_own_http_sockets(tmp_path: Path) -> None:
    a = _budget(tmp_path / "A", session_id="session-A", run_generation="run-A")
    b = _budget(tmp_path / "B", session_id="session-B", run_generation="run-B")
    register_active_task_budget(a)
    register_active_task_budget(b)
    try:
        with _local_sse("hold") as (server_a, port_a), _local_sse("hold") as (server_b, port_b):
            client_a, client_b = _real_client(port_a), _real_client(port_b)
            try:
                worker_a, done_a, outcome_a = _in_thread(client_a, a)
                worker_b, done_b, outcome_b = _in_thread(client_b, b)
                assert server_a.started.wait(2) and server_b.started.wait(2)
                assert cancel_active_task_budget("session-A", "run-A", reason="user_stop")
                assert done_a.wait(1.0)
                assert not done_b.wait(0.15)
                assert not server_b.peer_closed.is_set()
                assert cancel_active_task_budget("session-B", "run-B", reason="user_stop")
                assert done_b.wait(1.0)
                worker_a.join(timeout=0.2)
                worker_b.join(timeout=0.2)
                assert outcome_a == outcome_b == ["TaskBudgetDeniedError"]
                assert server_a.peer_closed.wait(1.0)
                assert server_b.peer_closed.wait(1.0)
            finally:
                client_a.close()
                client_b.close()
    finally:
        unregister_active_task_budget(a)
        unregister_active_task_budget(b)
    assert len(a.store.report(a.budget_id)["outstanding_or_unknown"]) == 1
    assert len(b.store.report(b.budget_id)["outstanding_or_unknown"]) == 1


def test_budget_deadline_aborts_sse_even_when_peer_drips(tmp_path: Path) -> None:
    execution = _budget(tmp_path, expires_in=0.55)
    with _local_sse("drip") as (server, port):
        client = _real_client(port)
        try:
            worker, finished, outcome = _in_thread(client, execution)
            assert server.started.wait(2)
            start = time.monotonic()
            assert finished.wait(1.8), "continuous drip hid budget deadline"
            assert time.monotonic() - start < 1.8
            worker.join(timeout=0.2)
            assert outcome == ["TaskBudgetDeniedError"]
            assert server.requests == 1
        finally:
            client.close()
    report = execution.store.report(execution.budget_id)
    assert len(report["outstanding_or_unknown"]) == 1
    assert report["physical_quiescence_verified"] is False
    assert report["phase"] == "stop_requested"


def test_preheaders_network_read_is_bounded_but_not_false_remote_ack(tmp_path: Path) -> None:
    execution = _budget(tmp_path)
    with _local_sse("no_headers") as (server, port):
        client = _real_client(port)
        try:
            start = time.monotonic()
            worker, finished, outcome = _in_thread(client, execution)
            assert server.started.wait(2)
            assert finished.wait(2.3), "response-header read ignored budgeted timeout cap"
            assert time.monotonic() - start < 2.3
            worker.join(timeout=0.2)
            assert outcome != ["unexpected_success"]
            assert server.requests == 1
        finally:
            client.close()
    report = execution.store.report(execution.budget_id)
    assert report["physical_quiescence_verified"] is False
    assert len(report["outstanding_or_unknown"]) == 1


def test_owner_stop_during_preheader_wait_is_bounded_and_unknown(tmp_path: Path) -> None:
    execution = _budget(tmp_path)
    with _local_sse("no_headers") as (server, port):
        client = _real_client(port)
        try:
            worker, finished, outcome = _in_thread(client, execution)
            assert server.started.wait(2)
            execution.request_stop(reason="user_stop")
            assert finished.wait(2.2), "preheader stall ignored bounded read timeout"
            worker.join(timeout=0.2)
            assert outcome != ["unexpected_success"]
            assert server.requests == 1
        finally:
            client.close()
    report = execution.store.report(execution.budget_id)
    assert report["phase"] == "stop_requested"
    assert len(report["outstanding_or_unknown"]) == 1
    assert report["physical_quiescence_verified"] is False


def test_durable_stop_failure_still_aborts_socket_and_keeps_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _budget(tmp_path)
    with _local_sse("hold") as (server, port):
        client = _real_client(port)
        try:
            worker, finished, outcome = _in_thread(client, execution)
            assert server.started.wait(2)

            def failed_persist(*_args: Any, **_kwargs: Any) -> None:
                raise OSError("injected ledger write uncertainty")

            monkeypatch.setattr(execution.store, "request_stop", failed_persist)
            with pytest.raises(OSError, match="injected ledger write uncertainty"):
                execution.request_stop(reason="user_stop")
            assert finished.wait(1.0)
            assert server.peer_closed.wait(1.0)
            worker.join(timeout=0.2)
            assert outcome == ["TaskBudgetDeniedError"]
        finally:
            client.close()
    report = execution.store.report(execution.budget_id)
    # Cannot invent successful durable Stop or remote settlement.
    assert report["phase"] == "active"
    assert len(report["outstanding_or_unknown"]) == 1
    assert report["physical_quiescence_verified"] is False


def test_unbound_http_timeout_contract_is_unchanged(tmp_path: Path) -> None:
    assert budgeted_transport_timeout(8.0) == 8.0
    execution = _budget(tmp_path)
    with bind_task_budget(execution):
        timeout = budgeted_transport_timeout(8.0)
        assert isinstance(timeout, httpx.Timeout)
        assert timeout.read == timeout.connect == timeout.write == timeout.pool == 1.0
    assert active_task_budget() is None


def test_http2_multiplexed_socket_is_not_force_closed() -> None:
    class _FakeSocket:
        def __init__(self) -> None:
            self.shutdowns = 0

        def shutdown(self, _how: int) -> None:
            self.shutdowns += 1

    sock = _FakeSocket()
    response = SimpleNamespace(extensions={
        "http_version": b"HTTP/2",
        "network_stream": SimpleNamespace(get_extra_info=lambda _: sock),
    })
    supported, abort = _physical_abort(response)
    assert supported is False
    abort()
    assert sock.shutdowns == 0

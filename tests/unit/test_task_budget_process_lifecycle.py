"""I5-D: verified TLS child cancellation and parent-lifetime death fence."""

from __future__ import annotations

import multiprocessing
import os
import time
from multiprocessing.connection import Connection
from pathlib import Path

import pytest

from llm_loop.llm.client import LLMClient
from llm_loop.resources.task_budget_dispatch import (
    cancel_active_task_budget,
    register_active_task_budget,
    unregister_active_task_budget,
)
from llm_loop.resources.task_budget_process_transport import (
    IsolatedTransportProfile,
    _process_one_http_request,
)
from tests.unit.test_task_budget_process_transport import _isolated_children, _run_isolated
from tests.unit.test_task_budget_tls_transport import _loopback_https
from tests.unit.test_task_budget_tls_transport import _test_cert as _shared_cert_fixture
from tests.unit.test_task_budget_transport_stop import _budget, _local_sse


@pytest.fixture(scope="module")
def i5d_tls_certificate(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Explicit dependency; pytest_plugins in a test module is order-sensitive.

    Clean I5-D HEAD reproduces 4 missing-fixture errors when the whole
    budget matrix is collected together. Reuse the fixture factory directly
    instead of depending on test-module plugin discovery order.
    """
    return _shared_cert_fixture.__wrapped__(tmp_path_factory)


@pytest.mark.parametrize("protocol", ["openai", "anthropic", "google", "lms-chat"])
def test_verified_tls_worker_stop_is_physical_and_unknown(
    tmp_path: Path, i5d_tls_certificate: tuple[Path, Path], protocol: str,
) -> None:
    cert, key = i5d_tls_certificate
    budget = _budget(tmp_path)
    register_active_task_budget(budget)
    try:
        with _loopback_https(cert, key) as (peer, port):
            client = LLMClient(
                api_key="k", base_url=f"https://127.0.0.1:{port}/v1",
                provider="glm", model="glm-5.3", wire_protocol=protocol,
                timeout_s=8, thinking_mode=False, retry_disconnect=0,
            )
            try:
                worker, done, outcome = _run_isolated(
                    client, budget, IsolatedTransportProfile(verify=str(cert)),
                )
                assert peer.response_started.wait(5)
                assert cancel_active_task_budget("session-A", "run-A", reason="user_stop")
                assert done.wait(2)
                assert peer.peer_closed.wait(2)
                worker.join(timeout=0.2)
                assert outcome == ["TaskBudgetDeniedError"]
                assert peer.requests == 1
            finally:
                client.close()
    finally:
        if not budget._local_stop.is_set():
            budget.request_stop(reason="test_cleanup")
        unregister_active_task_budget(budget)
    report = budget.store.report(budget.budget_id)
    assert report["phase"] == "stop_requested"
    assert report["physical_quiescence_verified"] is False
    assert len(report["outstanding_or_unknown"]) == 1
    assert _isolated_children() == []


def _owned_child_launcher(control: Connection, port: int) -> None:
    """Fixture subprocess exits abruptly while it has a live HTTP child."""
    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    child = ctx.Process(
        target=_process_one_http_request,
        args=(
            sender, "POST", f"http://127.0.0.1:{port}/v1/chat/completions",
            {"messages": []}, {"Content-Type": "application/json"},
            12.0, True, None,
        ),
        name="task-budget-provider-isolate", daemon=True,
    )
    child.start()
    sender.close()
    receiver.close()
    control.send(child.pid)
    control.recv()  # Main test observed a real POST before triggering death.
    os._exit(0)  # abrupt parent death; isolated child sentinel must fire


def test_parent_crash_forces_orphan_worker_to_exit() -> None:
    with _local_sse("hold") as (peer, port):
        ctx = multiprocessing.get_context("spawn")
        owner_conn, child_conn = ctx.Pipe()
        owner = ctx.Process(
            target=_owned_child_launcher, args=(child_conn, port),
            name="i5d-test-owner", daemon=False,
        )
        owner.start()
        child_conn.close()
        try:
            assert owner_conn.poll(5)
            pid = owner_conn.recv()
            assert isinstance(pid, int)
            assert peer.started.wait(5)
            owner_conn.send("exit_now")
            owner.join(timeout=3)
            assert owner.exitcode == 0
            assert peer.peer_closed.wait(3), "orphan still owns network after parent death"
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                pytest.fail("ownerless Provider worker remained alive")
        finally:
            owner_conn.close()
            if owner.is_alive():
                owner.terminate()
                owner.join(timeout=1)

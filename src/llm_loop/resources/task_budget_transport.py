"""I5-B: bounded, opt-in cancellation of a budget-owned Provider stream.

This is *local transport* control, not proof that a remote provider stopped
work or billing. An outstanding physical reservation remains UNKNOWN.
No-budget traffic continues to use the original HTTP timeout and iterator.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from llm_loop.resources.task_budget_dispatch import TaskBudgetExecution, active_task_budget
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError

_BOUND_IO_TIMEOUT_S = 1.0
_WATCH_INTERVAL_S = 0.10


def budgeted_transport_timeout(value: float) -> float | httpx.Timeout:
    """Bound each connect/TLS/read/write wait for *explicit* budgets only.

    HTTPX timeouts cannot guarantee interruption of every OS resolver, TLS
    handshake, HTTP/2 shared connection, or proxy. Those are separate hold
    conditions; this helper does not claim a general hard wall-clock bound.
    """
    if active_task_budget() is None:
        return value
    return httpx.Timeout(min(_BOUND_IO_TIMEOUT_S, value))


def _physical_abort(resp: httpx.Response) -> tuple[bool, Any]:
    """Obtain an *exclusive HTTP/1* response's network socket when exposed.

    No global httpx.Client.close(): a Run must never cancel a sibling's
    pooled/multiplexed connection. If HTTPX does not expose a safe socket,
    the physical abort remains unqualified and the short read timeout is
    merely a bounded fallback (not a cancellation acknowledgement).
    """
    extensions = getattr(resp, "extensions", {})
    if not isinstance(extensions, dict) or extensions.get("http_version") not in (
        b"HTTP/1.0", b"HTTP/1.1"
    ):
        return False, lambda: None
    stream = extensions.get("network_stream")
    get_info = getattr(stream, "get_extra_info", None)
    if not callable(get_info):
        return False, lambda: None
    try:
        sock = get_info("socket")
    except (OSError, ValueError):
        return False, lambda: None
    if not isinstance(sock, socket.socket):
        return False, lambda: None

    def abort() -> None:
        # Shutdown wakes a read blocked in another thread on tested HTTP/1
        # sockets. The owner thread then exits the stream context and closes.
        sock.shutdown(socket.SHUT_RDWR)

    return True, abort


@contextmanager
def watched_budget_response(
    budget: TaskBudgetExecution, resp: httpx.Response
) -> Iterator[bool]:
    """Watch exact Run stop/deadline while its HTTP response is being read.

    The boolean reports only whether a raw HTTP/1 abort handle existed, not
    that close succeeded, no bytes were sent, or provider usage is settled.
    """
    supported, abort = _physical_abort(resp)
    done = threading.Event()

    def monitor() -> None:
        while not done.wait(_WATCH_INTERVAL_S):
            try:
                budget._get_validated()
            except TaskBudgetDeniedError as exc:
                if exc.reason == "deadline_expired":
                    try:
                        budget.request_stop(reason="deadline_expired")
                    except Exception:  # noqa: BLE001 - local revocation survives uncertain persistence
                        # Do not mark the provider settled or claim a durable
                        # stop if the filesystem/CAS write was uncertain.
                        budget._local_stop.set()
                        budget.abort_active_transports()
                else:
                    budget._local_stop.set()
                    budget.abort_active_transports()
                return
            except OSError:
                # Ledger unavailable: fail closed locally without making up
                # a remote ACK or a successful durable ledger transition.
                budget._local_stop.set()
                budget.abort_active_transports()
                return

    with budget.track_transport(abort):
        thread = threading.Thread(
            target=monitor, daemon=True, name="task-budget-transport-stop"
        )
        thread.start()
        try:
            yield supported
        finally:
            done.set()
            thread.join(timeout=2 * _WATCH_INTERVAL_S)

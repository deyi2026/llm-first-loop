"""I5-D experimental per-attempt Provider process boundary.

The process owns exactly one HTTP transport. The parent alone owns the
TaskBudget CAS/Run/Stop authority. A killed child proves local process exit,
NOT a remote Provider stop or billing settlement. This is explicitly bound
by trusted Python code; default-OFF and existing budget paths are unchanged.
"""

from __future__ import annotations

import base64
import binascii
import json
import multiprocessing
import os
import re
import threading
from collections.abc import Iterator
from contextlib import closing, contextmanager, suppress
from multiprocessing.connection import Connection
from typing import Any

import httpx

from llm_loop.resources.task_budget_dispatch import active_task_budget, has_dispatched_attempt
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError
from llm_loop.resources.task_budget_transport_context import (
    _ISOLATED_PROFILE,
    IsolatedTransportProfile,
    active_authorized_provider_proxy,
    bind_isolated_provider_transport,
)

__all__ = [
    "IsolatedTransportError", "IsolatedTransportProfile",
    "bind_isolated_provider_transport", "isolated_provider_stream",
]

_POLL_SECONDS = 0.025
_REAP_SECONDS = 0.35
_FRAME_MAX = 262_144
_BODY_CHUNK = 16_384
_KIND_RE = re.compile(r"[A-Za-z0-9_.]{1,64}\Z")


def _worker_error_code(code: str, kind: object) -> str:
    """Surface the worker's exception class so an open failure is attributable.

    The class name is type-only evidence; it can never carry credentials,
    URLs, or message bodies across the process boundary. Production incident
    2026-10-09 14:14: the kind was discarded here, leaving only a generic
    isolated_transport_open_failed that no one could attribute.
    """
    if isinstance(kind, str) and _KIND_RE.fullmatch(kind):
        return f"{code}:{kind}"
    return code


class IsolatedTransportError(httpx.TransportError):
    """A worker/IPC failure is never a remote completion receipt."""


def _encode_frame(event: str, **values: Any) -> bytes:
    data = json.dumps(
        {"event": event, **values}, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    if len(data) > _FRAME_MAX:
        raise ValueError("isolated_transport_ipc_frame_too_large")
    return data


def _process_one_http_request(
    sender: Connection, method: str, url: str, payload: dict[str, Any],
    headers: dict[str, str], timeout: float, verify: bool | str,
    proxy: str | None,
) -> None:
    """Spawn-safe worker entrypoint: one outbound POST, no budget authority.

    Headers and credentials travel only over the multiprocessing launch pipe,
    never as command-line arguments or environment variables.
    """
    # The worker must also die when its parent disappears mid-DNS or TLS:
    # a lost Web process cannot leave an unowned Provider stream running.
    parent = multiprocessing.parent_process()
    if parent is None:
        with suppress(OSError, ValueError):
            sender.send_bytes(_encode_frame("error", kind="missing_parent"))
        sender.close()
        return
    done = threading.Event()

    def watch_parent() -> None:
        while not done.wait(0.05):
            if not parent.is_alive():
                os._exit(76)  # exit this child only, not the host process

    threading.Thread(
        target=watch_parent, daemon=True, name="task-budget-parent-lifetime",
    ).start()
    try:
        if method != "POST":
            raise ValueError("method_not_qualified")
        with httpx.Client(
            verify=verify, proxy=proxy, trust_env=False, http2=False,
            timeout=httpx.Timeout(timeout), follow_redirects=False,
        ) as client, client.stream(
            method, url, json=payload, headers=headers,
            timeout=httpx.Timeout(timeout),
        ) as response:
            sender.send_bytes(_encode_frame(
                "headers", status=response.status_code,
                headers=list(response.headers.multi_items()),
                http_version=response.extensions.get("http_version", b"").decode(
                    "ascii", "replace"
                ),
            ))
            for body in response.iter_raw(chunk_size=_BODY_CHUNK):
                if body:
                    sender.send_bytes(_encode_frame(
                        "body", data=base64.b64encode(body).decode("ascii"),
                    ))
            sender.send_bytes(_encode_frame("end"))
    except Exception as exc:  # noqa: BLE001 - worker communicates type only
        with suppress(OSError, ValueError):
            sender.send_bytes(_encode_frame("error", kind=type(exc).__name__))
    finally:
        done.set()
        sender.close()


class _Attempt:
    """Single-use parent-side controller of an exclusive OS worker process."""

    def __init__(
        self, *, budget: Any, method: str, url: str, payload: dict[str, Any],
        headers: dict[str, str], timeout: float, profile: IsolatedTransportProfile,
    ) -> None:
        ctx = multiprocessing.get_context("spawn")
        receiver, sender = ctx.Pipe(duplex=False)
        self.receiver = receiver
        self._sender = sender
        self.budget = budget
        self.process = ctx.Process(
            target=_process_one_http_request,
            args=(
                sender, method, url, payload, headers, timeout,
                profile.verify, profile.proxy,
            ),
            name="task-budget-provider-isolate",
            daemon=True,
        )
        self._cancelled = threading.Event()
        self._started = False
        self._done = False

    def abort(self) -> None:
        self._cancelled.set()
        if self.process.pid is not None and self.process.is_alive():
            self.process.terminate()

    def start(self) -> None:
        try:
            self.process.start()
            self._started = True
        finally:
            # The parent must not hold the child's sender descriptor or EOF
            # after a crashed child could be hidden by the duplicate handle.
            self._sender.close()
        if self._cancelled.is_set():
            self.abort()
        self.budget._get_validated()

    def next_frame(self) -> dict[str, Any]:
        while True:
            self.budget._get_validated()
            if self._cancelled.is_set():
                raise TaskBudgetDeniedError("local_run_stop_requested")
            if self.receiver.poll(_POLL_SECONDS):
                try:
                    raw = self.receiver.recv_bytes(_FRAME_MAX)
                    packet = json.loads(raw)
                except (EOFError, OSError, ValueError, UnicodeError) as exc:
                    # Stop can close the IPC pipe before the reader has seen
                    # the local budget latch; preserve the authoritative
                    # denial rather than translating it into a network error.
                    self.budget._get_validated()
                    raise IsolatedTransportError("isolated_transport_ipc_failed") from exc
                if not isinstance(packet, dict) or not isinstance(packet.get("event"), str):
                    raise IsolatedTransportError("isolated_transport_ipc_invalid")
                self.budget._get_validated()
                return packet
            if self._started and not self.process.is_alive():
                # Drain any data only if poll says available; otherwise a
                # process death without END/ERROR cannot claim completion.
                self.budget._get_validated()
                raise IsolatedTransportError("isolated_transport_worker_exited")

    def reap(self) -> None:
        self._cancelled.set()
        try:
            # start() can fail *after* obtaining a PID. Do not strand that
            # partial-start worker merely because start() did not return.
            if self.process.pid is not None:
                self.process.join(timeout=_REAP_SECONDS)
                if self.process.is_alive():
                    self.process.terminate()
                    self.process.join(timeout=_REAP_SECONDS)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join(timeout=_REAP_SECONDS)
                if self.process.is_alive():
                    raise IsolatedTransportError("isolated_transport_unreaped_worker")
        finally:
            self._sender.close()
            self.receiver.close()


class _BodyStream(httpx.SyncByteStream):
    def __init__(self, attempt: _Attempt) -> None:
        self.attempt = attempt

    def __iter__(self) -> Iterator[bytes]:
        while True:
            event = self.attempt.next_frame()
            if event["event"] == "end":
                return
            if event["event"] == "error":
                raise IsolatedTransportError(_worker_error_code(
                    "isolated_transport_worker_error", event.get("kind"),
                ))
            if event["event"] != "body" or not isinstance(event.get("data"), str):
                raise IsolatedTransportError("isolated_transport_unexpected_frame")
            try:
                yield base64.b64decode(event["data"], validate=True)
            except (ValueError, binascii.Error) as exc:
                raise IsolatedTransportError("isolated_transport_body_invalid") from exc

    def close(self) -> None:
        # The enclosing scope reaps the worker. Do not close any shared client.
        self.attempt.abort()


@contextmanager
def isolated_provider_stream(
    client: httpx.Client, method: str, url: str, *,
    json: dict[str, Any], headers: dict[str, str],
    timeout: float | httpx.Timeout,
) -> Iterator[httpx.Response]:
    """Experimental transport surface for LLMClient's four SSE protocols."""
    profile = _ISOLATED_PROFILE.get()
    if profile is None:
        # Exact original path, including the caller-supplied deadline/headers.
        with client.stream(method, url, json=json, headers=headers, timeout=timeout) as resp:
            yield resp
        return
    budget = active_task_budget()
    if budget is None:
        raise TaskBudgetDeniedError("isolated_transport_requires_budget")
    snapshot = budget._get_validated()
    if snapshot["grant"]["profile"] in {
        "web-glm-one-physical-attempt-v3", "web-glm-knowledge-consumption-v1",
    }:
        if not has_dispatched_attempt(budget):
            raise TaskBudgetDeniedError("positive_send_without_dispatched_cas_reservation")
        if (
            profile.verify is not True
            or profile.proxy not in (None, active_authorized_provider_proxy())
            or json.get("model") != "glm-5.3"
        ):
            raise TaskBudgetDeniedError("positive_transport_unqualified")
        # Guard the final actual outbound URL too, not just LLMClient's
        # pre-transport observation. No redirects or trusted-env proxies.
        budget.assert_provider_target(
            provider_id="glm", model_id="glm-5.3", wire_protocol="openai",
            target_url=url,
        )
    url_obj = httpx.URL(url)
    if method != "POST" or url_obj.scheme not in {"http", "https"} or not url_obj.host:
        raise TaskBudgetDeniedError("isolated_transport_endpoint_unqualified")
    if url_obj.scheme == "http" and url_obj.host not in {"127.0.0.1", "localhost", "::1"}:
        raise TaskBudgetDeniedError("isolated_transport_plain_http_requires_loopback")
    wire_timeout = timeout.read if isinstance(timeout, httpx.Timeout) else timeout
    if wire_timeout is None or not 0 < float(wire_timeout) <= 60:
        raise TaskBudgetDeniedError("isolated_transport_timeout_unqualified")

    attempt = _Attempt(
        budget=budget, method=method, url=url, payload=json, headers=headers,
        timeout=float(wire_timeout), profile=profile,
    )
    # Register before start(): an overlapping Stop can latch cancellation
    # even before a PID exists, then kill immediately after spawn returns.
    try:
        with budget.track_transport(attempt.abort):
            attempt.start()
            opening = attempt.next_frame()
            if opening["event"] == "error":
                raise IsolatedTransportError(_worker_error_code(
                    "isolated_transport_open_failed", opening.get("kind"),
                ))
            if opening["event"] != "headers":
                raise IsolatedTransportError("isolated_transport_missing_headers")
            version = opening.get("http_version")
            if (
                not isinstance(version, str)
                or version not in {"HTTP/1.0", "HTTP/1.1"}
                or not isinstance(opening.get("status"), int)
                or not isinstance(opening.get("headers"), list)
            ):
                raise IsolatedTransportError("isolated_transport_unqualified_response")
            response = httpx.Response(
                status_code=opening["status"],
                headers=opening["headers"],
                request=httpx.Request(method, url),
                stream=_BodyStream(attempt),
                extensions={"http_version": version.encode(), "lfl_isolated": True},
            )
            # httpx.Response does not implement the context-manager protocol;
            # the original httpx.Client.stream() owns that behavior.
            with closing(response):
                yield response
    finally:
        # Even rejection while registering the Stop callback must close
        # both IPC endpoints; an unstarted process is safe to reap.
        attempt.reap()

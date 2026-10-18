"""Pump the existing native runner on the input-owning CLI thread."""
from __future__ import annotations

import queue
import signal
import threading
import time
from typing import Any

from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.terminal.presentation import Presenter


def run_turn(
    engine: Any, sid: str, text: str, view: Presenter, approval: Any = None, *,
    interactive: bool = False,
) -> int:
    runner = getattr(engine, "runner", None)
    if runner is None or not runner.enabled:
        return _synchronous_turn(engine, sid, text, view)
    interrupt = threading.Event()
    sigint_received = threading.Event()
    if approval is not None:
        approval.interrupt = interrupt
    previous = None
    previous_term = None
    terminated = threading.Event()
    main_thread = threading.current_thread() is threading.main_thread()
    handle = None
    events = None
    # Install signal ownership before starting the background worker: start() can
    # launch a real external tool immediately, and SIGTERM must not hit the default
    # process-kill action in the small startup window.
    if main_thread:
        previous = signal.signal(signal.SIGINT, lambda *_: (sigint_received.set(), interrupt.set()))
        previous_term = signal.signal(signal.SIGTERM, lambda *_: (terminated.set(), interrupt.set()))
    try:
        try:
            handle, events = runner.start(sid, text, ingress=issue_ingress("cli"))
        except Exception as exc:  # noqa: BLE001 - no run admitted; stable structured failure
            if terminated.is_set():
                return view.error("Run start was interrupted by SIGTERM; settlement is unknown.",
                                  "termination_pending", 143)
            if sigint_received.is_set():
                return view.error("Run start was interrupted by SIGINT; no run handle was returned.",
                                  "interrupted", 1 if interactive else 130)
            return view.error(f"{type(exc).__name__}: {exc}", "run_start_failed")
        if handle is None or events is None:
            return view.error("Session is busy; no run was attached or started.", "session_busy")
        view.started(sid, handle.run_generation)
        return _pump(
            runner, handle, events, view, interrupt, approval, terminated,
            sigint_received=sigint_received, interactive=interactive,
        )
    except BrokenPipeError:
        if handle is not None:
            runner.cancel(sid, expected_run_generation=handle.run_generation)
        view.notice("Output pipe closed; cancellation requested. Delivery/resource settlement is unknown.")
        return 1
    finally:
        if main_thread:
            signal.signal(signal.SIGINT, previous)
            signal.signal(signal.SIGTERM, previous_term)
        if events is not None:
            runner.unsubscribe(sid, events)


def _pump(runner: Any, handle: Any, events: Any, view: Presenter,
          interrupt: threading.Event, approval: Any, terminated: threading.Event | None = None, *,
          sigint_received: threading.Event | None = None, interactive: bool = False) -> int:
    requested = False
    deadline = None
    while True:
        # Only SIGTERM starts a hard cleanup deadline: SIGINT waits for the core's
        # actual terminal fact so interactive cancellation cannot overlap a new run.
        if terminated is not None and terminated.is_set() and deadline is None:
            deadline = time.monotonic() + 5
        if deadline is not None and time.monotonic() >= deadline:
            return view.error("SIGTERM cleanup deadline reached; external settlement is unknown.",
                              "termination_pending", 143)
        if interrupt.is_set():
            interrupt.clear()
            if not requested:
                accepted = runner.cancel(handle.session_id, expected_run_generation=handle.run_generation)
                requested = True
                view.event("cancel_requested", accepted=accepted)
                view.notice("Cancellation requested for this run; waiting for its terminal outcome.")
            else:
                view.notice("Still waiting for the owned run to settle; resource closure is not yet confirmed.")
        if approval is not None:
            approval.service()
        try:
            item = events.get(timeout=0.1)
        except queue.Empty:
            continue
        kind = item.get("type")
        if kind == "delta":
            view.delta(item["delta"])
        elif kind == "done":
            exit_code = None
            if deadline is not None or (terminated is not None and terminated.is_set()):
                exit_code = 143
            elif sigint_received is not None and sigint_received.is_set() and not interactive:
                exit_code = 130
            return view.finish(item["result"], exit_code=exit_code)
        elif kind == "error":
            if terminated is not None and terminated.is_set():
                return view.error(
                    "Run errored while SIGTERM cleanup was pending; external settlement is unknown.",
                    "termination_pending", 143,
                )
            if sigint_received is not None and sigint_received.is_set():
                return view.error(
                    "Run was interrupted by SIGINT before a normal terminal result; external settlement is unknown.",
                    "interrupted", 1 if interactive else 130,
                )
            return view.error(item.get("error", "Run failed"), item.get("error_code", "run_error"))


def _synchronous_turn(engine: Any, sid: str, text: str, view: Presenter) -> int:
    """Compatibility for explicit RUNNER_BACKGROUND=0; no second scheduler."""
    view.started(sid, "")
    try:
        stream = getattr(engine, "run_stream", None)
        if stream is None:
            result = engine.run(sid, text, ingress=issue_ingress("cli"))
        else:
            iterator = stream(sid, text, ingress=issue_ingress("cli"))
            while True:
                try:
                    view.delta(next(iterator))
                except StopIteration as stop:
                    result = stop.value
                    break
        return view.finish(result)
    except KeyboardInterrupt:
        return view.error("Interrupted; external resource closure is unconfirmed.", "interrupted", 130)
    except Exception as exc:  # noqa: BLE001 - report actual failure, never pretend completion
        return view.error(f"{type(exc).__name__}: {exc}")

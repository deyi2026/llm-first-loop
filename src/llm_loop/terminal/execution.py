"""Pump the existing native runner on the input-owning CLI thread."""
from __future__ import annotations

import queue
import signal
import threading
import time
from typing import Any

from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.terminal.presentation import Presenter


def run_turn(engine: Any, sid: str, text: str, view: Presenter, approval: Any = None) -> int:
    runner = getattr(engine, "runner", None)
    if runner is None or not runner.enabled:
        return _synchronous_turn(engine, sid, text, view)
    try:
        handle, events = runner.start(sid, text, ingress=issue_ingress("cli"))
    except Exception as exc:  # noqa: BLE001 - no run admitted; stable structured failure
        return view.error(f"{type(exc).__name__}: {exc}", "run_start_failed")
    if handle is None or events is None:
        return view.error("Session is busy; no run was attached or started.", "session_busy")
    view.started(sid, handle.run_generation)
    interrupt = threading.Event()
    if approval is not None:
        approval.interrupt = interrupt
    previous = None
    previous_term = None
    terminated = threading.Event()
    main_thread = threading.current_thread() is threading.main_thread()
    if main_thread:
        previous = signal.signal(signal.SIGINT, lambda *_: interrupt.set())
        previous_term = signal.signal(signal.SIGTERM, lambda *_: (terminated.set(), interrupt.set()))
    try:
        return _pump(runner, handle, events, view, interrupt, approval, terminated)
    except BrokenPipeError:
        runner.cancel(sid, expected_run_generation=handle.run_generation)
        view.notice("Output pipe closed; cancellation requested. Delivery/resource settlement is unknown.")
        return 1
    finally:
        if main_thread:
            signal.signal(signal.SIGINT, previous)
            signal.signal(signal.SIGTERM, previous_term)
        runner.unsubscribe(sid, events)


def _pump(runner: Any, handle: Any, events: Any, view: Presenter,
          interrupt: threading.Event, approval: Any, terminated: threading.Event | None = None) -> int:
    requested = False
    deadline = None
    while True:
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
            return view.finish(item["result"], exit_code=143 if deadline is not None else None)
        elif kind == "error":
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

"""Main-run wait regressions from the 2026-10-13 repeated-wait incident."""

from __future__ import annotations

import contextvars
import threading
from types import SimpleNamespace

from llm_loop.core import run_context as rc
from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.core.message import ToolCall
from llm_loop.core.run_context import current_session_id
from llm_loop.llm.client import LLMResponse, StreamDelta
from llm_loop.tools.builtin import wait as wait_module
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.builtin.job_registry import JobRegistry
from llm_loop.tools.builtin.wait import WaitTool


def _clock(monkeypatch):
    clock = SimpleNamespace(now=0.0)

    def advance(seconds):
        clock.now += seconds

    monkeypatch.setattr(wait_module, "time", SimpleNamespace(
        monotonic=lambda: clock.now, sleep=advance,
    ))
    monkeypatch.setattr(
        WaitTool, "_pause", lambda self, stop, completion, seconds: advance(seconds),
        raising=False,
    )
    return clock


def test_main_engine_wait_accumulates_across_dispatch(build_test_engine, monkeypatch):
    _clock(monkeypatch)
    engine, _ = build_test_engine([
        {"tool_calls": [ToolCall(id="w1", name="wait", arguments={"seconds": 120})]},
        {"tool_calls": [ToolCall(id="w2", name="wait", arguments={"seconds": 120})]},
        {"content": "ok"},
    ])
    engine.registry.register(WaitTool())
    sid = engine.session.create()
    engine.run(sid, "wait twice")
    results = [m.content for m in engine.session.load(sid).messages if m.tool_name == "wait"]
    assert len(results) == 2
    assert "累计 120s" in results[0]
    assert "累计 240s" in results[1]
    assert "/ 600s" not in results[1], "child lease budget must not be claimed for main"


def test_main_stop_before_wait_registration_is_not_lost(build_test_engine, monkeypatch):
    engine, _ = build_test_engine([
        {"tool_calls": [ToolCall(id="w", name="wait", arguments={"seconds": 3})]},
        {"content": "ok"},
    ])
    tool = WaitTool()
    engine.registry.register(tool)
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    original = tool.execute
    receipts = []

    def held_execute(**kwargs):
        entered.set()
        assert release.wait(5)
        result = original(**kwargs)
        receipts.append(result)
        return result

    monkeypatch.setattr(tool, "execute", held_execute)
    handle, _ = runner.start(sid, "wait", terminal_callback=lambda *_: done.set())
    assert handle is not None
    try:
        assert entered.wait(10)
        assert runner.cancel(sid)
        release.set()
        assert done.wait(1.5), "accepted main Stop must wake without waiting three seconds"
        assert receipts and "cancelled" in receipts[0].content
    finally:
        release.set()
        done.wait(5)


def test_completed_owned_job_returns_without_sleep(monkeypatch):
    clock = _clock(monkeypatch)
    registry = JobRegistry()
    monkeypatch.setattr(JobRegistry, "_instance", registry)
    job_id = registry.create(None, "exit 7", session_id="owner")
    entry = registry.get(job_id)
    assert entry is not None
    entry.done, entry.exit_code = True, 7
    token = current_session_id.set("owner")
    try:
        result = WaitTool().execute(seconds=120, job_id=job_id)
    finally:
        current_session_id.reset(token)
    assert "wake_reason=job_terminal" in result.content
    assert "state=failed" in result.content and "exit=7" in result.content
    assert clock.now == 0


def test_fail_fast_preserves_pipeline_failure_before_trailing_echo():
    result = ExecuteCommandTool().execute(
        command="false | cat; echo done", fail_fast=True,
    )
    assert result.status.value == "failure"
    assert "\ndone" not in result.content


def test_job_exit_wakes_active_wait_and_keeps_failed_exit_code(monkeypatch):
    registry = JobRegistry()
    monkeypatch.setattr(JobRegistry, "_instance", registry)
    token = current_session_id.set("owner")
    try:
        started = ExecuteCommandTool().execute(
            command="sleep 0.2; false | cat; echo done",
            run_in_background=True, fail_fast=True,
        )
        assert started.status.value == "success"
        job_id = started.content.split("job_id=")[1].split()[0]
        result = WaitTool().execute(seconds=5, job_id=job_id)
        assert result.status.value == "success", "observing a failed process is a successful read"
        assert "wake_reason=job_terminal" in result.content
        assert "state=failed" in result.content and "exit=1" in result.content
        snapshot = registry.snapshot(job_id, session_id="owner")
        assert snapshot is not None and snapshot["exit_code"] == 1
        assert all("done" not in line for line in snapshot["output"])
    finally:
        registry.cancel_session("owner")
        current_session_id.reset(token)


def test_wait_timeout_reports_running_without_cancelling_job(monkeypatch):
    _clock(monkeypatch)
    registry = JobRegistry()
    monkeypatch.setattr(JobRegistry, "_instance", registry)
    job_id = registry.create(None, "held", session_id="owner")
    token = current_session_id.set("owner")
    try:
        result = WaitTool().execute(seconds=1, job_id=job_id)
    finally:
        current_session_id.reset(token)
    assert "wake_reason=timeout" in result.content and "state=running" in result.content
    entry = registry.get(job_id)
    assert entry is not None and not entry.killed


def test_cross_session_and_unbound_job_wait_cannot_observe(monkeypatch):
    clock = _clock(monkeypatch)
    registry = JobRegistry()
    monkeypatch.setattr(JobRegistry, "_instance", registry)
    job_id = registry.create(None, "private", session_id="owner")
    for sid in ("other", ""):
        token = current_session_id.set(sid)
        try:
            result = WaitTool().execute(seconds=120, job_id=job_id)
        finally:
            current_session_id.reset(token)
        assert result.status.value == "failure"
        assert "private" not in result.content
    assert clock.now == 0


def test_orphaned_job_is_unobservable_without_reclaim(monkeypatch):
    clock = _clock(monkeypatch)
    registry = JobRegistry()
    monkeypatch.setattr(JobRegistry, "_instance", registry)
    monkeypatch.setattr(registry, "snapshot", lambda *_a, **_k: {
        "session_id": "owner", "state": "orphaned", "local_handle": False,
    })
    token = current_session_id.set("owner")
    try:
        result = WaitTool().execute(seconds=120, job_id="durable-only")
    finally:
        current_session_id.reset(token)
    assert "wake_reason=job_unobservable" in result.content
    assert "state=orphaned" in result.content
    assert clock.now == 0


def test_kill_request_is_not_process_exit(monkeypatch):
    _clock(monkeypatch)
    registry = JobRegistry()
    monkeypatch.setattr(JobRegistry, "_instance", registry)
    job_id = registry.create(None, "held", session_id="owner")
    entry = registry.get(job_id)
    assert entry is not None
    entry.killed = True
    token = current_session_id.set("owner")
    try:
        result = WaitTool().execute(seconds=1, job_id=job_id)
    finally:
        current_session_id.reset(token)
    assert "wake_reason=timeout" in result.content
    assert "state=killed" in result.content and "exit=None" in result.content


def test_generation_scoped_cancel_cleans_wait_registration(monkeypatch):
    tool = WaitTool()
    paused, release = threading.Event(), threading.Event()
    pause = tool._pause
    results = []

    def held_pause(stop, completion, seconds):
        paused.set()
        assert release.wait(5)
        pause(stop, completion, seconds)

    monkeypatch.setattr(tool, "_pause", held_pause)
    sid_token = current_session_id.set("owner")
    gen_token = rc.current_run_generation.set("old")
    ctx = contextvars.copy_context()
    current_session_id.reset(sid_token)
    rc.current_run_generation.reset(gen_token)
    worker = threading.Thread(target=lambda: ctx.run(
        lambda: results.append(tool.execute(seconds=10)),
    ))
    worker.start()
    try:
        assert paused.wait(3)
        tool.terminate_session("owner", run_generation="new")
        event = next(iter(tool._active[("owner", "old")]))
        assert not event.is_set(), "late Stop for another generation must not wake this wait"
        tool.terminate_session("owner", run_generation="old")
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        assert "wake_reason=cancelled" in results[0].content
        assert tool._active == {}
    finally:
        tool.terminate_session("owner", run_generation="old")
        release.set()
        worker.join(3)


def test_parallel_child_waits_cannot_double_spend_remaining_budget(monkeypatch):
    tool = WaitTool()
    carrier = rc.WaitBudget(580)
    paused, release = threading.Event(), threading.Event()
    pause = tool._pause

    def held_pause(stop, completion, seconds):
        paused.set()
        assert release.wait(5)
        pause(stop, completion, seconds)

    monkeypatch.setattr(tool, "_pause", held_pause)
    budget_token = rc.child_wait_budget_used.set(carrier)
    sid_token = current_session_id.set("child")
    ctx = contextvars.copy_context()
    worker = threading.Thread(target=lambda: ctx.run(tool.execute, seconds=20))
    worker.start()
    try:
        assert paused.wait(3)
        other = tool.execute(seconds=1)
        assert other.status.value == "blocked", "in-flight reservation consumes the same lease"
        tool.terminate_session("child")
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        assert carrier.reserved == 0 and carrier.used < 600
    finally:
        tool.terminate_session("child")
        release.set()
        worker.join(3)
        current_session_id.reset(sid_token)
        rc.child_wait_budget_used.reset(budget_token)


def test_cross_context_resume_keeps_accounting_and_restores_caller(build_test_engine, monkeypatch):
    _clock(monkeypatch)
    engine, fake = build_test_engine([])
    seen = []

    def chat_stream(**_kwargs):
        for text in ("A", "B"):
            seen.append(rc.current_wait_budget.get())
            WaitTool().execute(seconds=1)
            yield StreamDelta(text=text)
        return LLMResponse(content="AB", tool_calls=[], provider="fake")

    fake.chat_stream = chat_stream
    sid = engine.session.create()
    stream = engine.run_stream(sid, "wait across contexts")
    for ctx in (contextvars.Context(), contextvars.Context()):
        ctx.run(next, stream)
        assert ctx.run(rc.current_wait_budget.get) is None
        assert ctx.run(rc.current_wait_cancel_check.get) is None
    stream.close()
    assert seen[0] is not None and seen[0] is seen[1]
    assert seen[0].used == 2


def test_default_shell_and_explicit_error_handler_keep_existing_semantics():
    default = ExecuteCommandTool().execute(command="false | cat; echo done")
    handled = ExecuteCommandTool().execute(command="false || echo recovered", fail_fast=True)
    assert default.status.value == "success" and "\ndone" in default.content
    assert handled.status.value == "success" and "\nrecovered" in handled.content

def test_old_child_checker_does_not_borrow_next_sync_run_stop(build_test_engine):
    engine, fake = build_test_engine([])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()
    inherited = []
    observed = []

    def first_stream(**_kwargs):
        inherited.append(contextvars.copy_context())
        yield StreamDelta(text="first")
        return LLMResponse(content="first", tool_calls=[], provider="fake")

    fake.chat_stream = first_stream
    stream = engine.run_stream(sid, "old parent run")
    next(stream)
    stream.close()
    assert not runner.is_sync_active(sid)

    # An async child may outlive its parent's completed generator and retain
    # the old dispatch Context. Its own cancellation Event is still unset.
    child_ctx = inherited[0]
    child_ctx.run(rc.child_cancel_event.set, threading.Event())

    def second_stream(**_kwargs):
        assert runner.cancel(sid)
        checker = rc.current_wait_cancel_check.get()
        assert checker is not None
        observed.append((
            child_ctx.run(WaitTool._cancelled, threading.Event()),
            checker(),
        ))
        yield StreamDelta(text="second")
        return LLMResponse(content="second", tool_calls=[], provider="fake")

    fake.chat_stream = second_stream
    result = engine.run(sid, "next sync run")
    assert result.cancel_reason == "user_stop"
    assert observed == [(False, True)], "old child must not read the next run's Stop"

def test_sync_wait_checker_revalidates_generation_after_cancel_read(build_test_engine, monkeypatch):
    engine, fake = build_test_engine([])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    captured = []

    def chat_stream(**_kwargs):
        captured.append((rc.current_wait_cancel_check.get(), rc.current_run_generation.get()))
        yield StreamDelta(text="capture")
        return LLMResponse(content="capture", tool_calls=[], provider="fake")

    fake.chat_stream = chat_stream
    sid = engine.session.create()
    engine.run(sid, "capture old run")
    checker, old_generation = captured[0]
    assert checker is not None
    authority = {"generation": old_generation}
    monkeypatch.setattr(engine.session, "active_run_generation", lambda _sid: authority["generation"])

    def next_run_stop(_sid):
        # Old run retirement + next-run Stop occurs between separate authority reads.
        authority["generation"] = "next-run-generation"
        return True

    monkeypatch.setattr(runner, "is_cancelled", next_run_stop)
    assert checker() is False, "a generation observation before cancellation is insufficient"

"""Review completion must wake its parent before any status poll mints a permit."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from llm_loop.core import scheduler
from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_session_id, current_wait_cancel_check
from llm_loop.core.session import SessionStore
from llm_loop.event_log.store import EventStore
from llm_loop.factory import review_terminal_predicate
from llm_loop.llm.client import LLMClient, LLMResponse
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.registry import ToolRegistry
from llm_loop.tools.review_host_admission import (
    HostReviewAdmission,
    ReviewAdmissionTool,
    _source_snapshot,
)
from tests.unit.test_review_host_admission import _repo


def _start_review(tmp_path: Path, verdict: str = "PASS"):
    repo = _repo(tmp_path)
    sha, _ = _source_snapshot(str(repo))
    release = threading.Event()
    events = EventStore(tmp_path / "events", enabled=True)

    class GatedLLM:
        def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
            assert release.wait(5), "test did not release reviewer"
            if verdict == "ERROR":
                raise RuntimeError("test reviewer failed")
            return LLMResponse(
                content=f"VERDICT: {verdict}\nP0=0 P1=0 P2=0\nSHA256: {sha}",
                tool_calls=[], provider="fake",
            )

    llm = cast(LLMClient, GatedLLM())
    runner = SubAgentRunner(
        llm=llm, registry=ToolRegistry(),
        session_store=SessionStore(tmp_path / "sessions", event_store=events),
        max_iterations=1, llm_resolver=lambda model: llm,
    )
    host = HostReviewAdmission()
    host.attach_runner(runner)
    host.attach_event_store(events)
    issued = host.start("owner", "full_test", workdir=str(repo), command="pytest -q")
    assert issued["accepted"], issued
    return host, runner, issued["child_id"], release, events


@pytest.mark.parametrize(("verdict", "qualification"), [
    ("PASS", "PASS"), ("REVISE", "REVISE"), ("ERROR", "UNAVAILABLE"),
])
@pytest.mark.parametrize("live_alias", [False, True])
def test_real_child_wakes_schedule_without_prior_status(
    tmp_path, monkeypatch, verdict, qualification, live_alias,
):
    host, runner, child, release, events = _start_review(tmp_path, verdict)
    worker = child
    if live_alias:
        row = host._records.pop(child)
        child = "stable-review-ref"
        host._records[child] = replace(row, child_id=child, live_child_id=worker)
    store = scheduler.ScheduleStore(tmp_path / "schedule.json")
    monkeypatch.setitem(
        scheduler._EVENT_PREDICATES, "review_terminal",
        lambda ref: review_terminal_predicate(ref, _authority=host),
    )
    sid = store.add(
        "Read the review status", after=3600, wake=True, wake_grant=object(),
        session_id="owner", event_predicate="review_terminal", predicate_ref=child,
    )
    try:
        assert store.claim_due("scheduler") == []
        release.set()
        # Observe the real worker's completion event; never poll the admission tool.
        assert runner._handles[worker].done_event.wait(3)
        assert host._records[child].state == "running"
        claimed = store.claim_due("scheduler")
        assert [entry.sid for entry in claimed] == [sid]
        assert claimed[0].event_won == "event"
        assert store.claim_due("other-scheduler") == []
        assert not host._records[child].granted
        assert not [e for e in events.read("owner") if e.type == "review_admission_qualified"]
        assert host.poll("owner", child)["qualification"] == qualification
    finally:
        release.set()


def test_status_wait_returns_completed_review_and_verified_receipt(tmp_path):
    host, runner, child, release, events = _start_review(tmp_path)
    timer = threading.Timer(0.05, release.set)
    token = current_session_id.set("owner")
    timer.start()
    try:
        result = ReviewAdmissionTool(host).execute(action="status", child_id=child, wait_seconds=1)
        data = json.loads(result.content)
        assert data["qualification"] == "PASS"
        assert runner._handles[child].done_event.is_set()
        assert len([e for e in events.read("owner") if e.type == "review_admission_qualified"]) == 1
    finally:
        release.set()
        timer.join()
        current_session_id.reset(token)


def test_status_wait_times_out_with_latest_pending_then_reads_completion(tmp_path):
    host, runner, child, release, _ = _start_review(tmp_path)
    try:
        start = time.monotonic()
        assert host.poll("owner", child, wait_seconds=0.03)["qualification"] == "pending"
        assert time.monotonic() - start < 1
        assert not host._records[child].granted
        release.set()
        assert runner._handles[child].done_event.wait(3)
        assert host.poll("owner", child, wait_seconds=1)["qualification"] == "PASS"
    finally:
        release.set()


def test_wait_checks_parent_stop_without_cancelling_reviewer(tmp_path):
    host, runner, child, release, _ = _start_review(tmp_path)
    token = current_wait_cancel_check.set(lambda: True)
    try:
        start = time.monotonic()
        assert host.poll("owner", child, wait_seconds=1)["qualification"] == "pending"
        assert time.monotonic() - start < 0.5
        assert not runner._handles[child].cancel_requested
    finally:
        release.set()
        current_wait_cancel_check.reset(token)


@pytest.mark.parametrize("wait", [-1, 31, float("nan"), float("inf"), True, "bad"])
def test_status_wait_rejects_invalid_bound(wait):
    result = ReviewAdmissionTool(HostReviewAdmission()).execute(
        action="status", child_id="unknown", wait_seconds=wait,
    )
    assert result.status.value == "failure"
    assert "wait_seconds" in result.content


def test_completion_observation_rejects_foreign_and_lost_handles(tmp_path):
    host, runner, child, release, _ = _start_review(tmp_path)
    try:
        release.set()
        assert runner._handles[child].done_event.wait(3)
        assert runner.review_finished_current(child, "foreign") is False
        assert runner.review_finished_current("missing", "owner") is False
        assert runner.review_finished_current(child, "owner") is True
        fresh = SubAgentRunner(
            llm=runner.llm, registry=ToolRegistry(), session_store=runner.session_store,
        )
        host.attach_runner(fresh)
        assert review_terminal_predicate(child, _authority=host) is False
        assert not host._records[child].granted
    finally:
        release.set()


def test_multiple_status_calls_run_together_and_preserve_order(monkeypatch):
    registry = ToolRegistry()
    barrier = threading.Barrier(2)

    def execute(call):
        assert current_session_id.get() == "owner"
        barrier.wait(timeout=2)
        return ToolResult(
            status=ToolResultStatus.SUCCESS, content=call.arguments["child_id"],
            tool_call_id=call.id, tool_name=call.name,
        )

    monkeypatch.setattr(registry, "execute", execute)
    calls = [ToolCall(id=child, name="review_admission", arguments={
        "action": "status", "child_id": child, "wait_seconds": 1,
    }) for child in ("child-a", "child-b")]
    token = current_session_id.set("owner")
    try:
        assert [r.content for r in registry.execute_many(calls)] == ["child-a", "child-b"]
    finally:
        current_session_id.reset(token)


@pytest.mark.parametrize("actions", [("start", "status"), ("status", "status")])
def test_mixed_or_duplicate_review_calls_remain_serial(monkeypatch, actions):
    registry = ToolRegistry()
    caller = threading.get_ident()

    def execute(call):
        assert threading.get_ident() == caller
        return ToolResult(
            status=ToolResultStatus.SUCCESS, content=call.arguments["action"],
            tool_call_id=call.id, tool_name=call.name,
        )

    monkeypatch.setattr(registry, "execute", execute)
    calls = [ToolCall(id=str(i), name="review_admission", arguments={
        "action": action, "child_id": "same-child",
    }) for i, action in enumerate(actions)]
    assert [r.content for r in registry.execute_many(calls)] == list(actions)

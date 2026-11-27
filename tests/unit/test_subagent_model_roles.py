from __future__ import annotations

import threading
import time

import pytest

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.core.session import SessionStore
from llm_loop.event_log.store import EventStore
from llm_loop.llm.client import LLMResponse
from llm_loop.llm.errors import LLMHTTPError, LLMNetworkError, LLMTimeoutError
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool
from llm_loop.tools.builtin.subagent_result import SubAgentResultTool
from llm_loop.tools.registry import ToolRegistry


class DecisionClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat(self, messages, tools, **kwargs):
        self.calls.append((messages, tools))
        assert tools == []
        if isinstance(self.response, Exception):
            raise self.response
        if callable(self.response):
            return self.response()
        return self.response


def _response(text="decision", observed="actual-model"):
    return LLMResponse(content=text, tool_calls=[], provider="fake", observed_model=observed,
                       prompt_tokens=12, completion_tokens=3)


def _runner(tmp_path, candidates, explicit=None):
    store = SessionStore(tmp_path / "sessions", event_store=EventStore(tmp_path / "events", enabled=True))
    default = DecisionClient(_response("must not use default"))
    runner = SubAgentRunner(llm=default, registry=ToolRegistry(), session_store=store,
                            llm_resolver=explicit, role_clients_resolver=candidates)
    return runner, default


def _settle(runner, child_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        ok, detail, snapshot = runner.result_current(child_id, wait_seconds=0.1)
        assert ok, detail
        if snapshot["state"] != "running":
            assert snapshot["result"] is not None
            return snapshot["result"]
    raise AssertionError("child did not settle")


@pytest.fixture(autouse=True)
def parent_context():
    token = current_session_id.set("parent-role-test")
    try:
        yield
    finally:
        current_session_id.reset(token)


@pytest.mark.parametrize("role,error,reason", [
    ("planning", LLMHTTPError("busy", status_code=429, provider="glm", provider_code="1305"), "provider_busy"),
    ("router", LLMTimeoutError("timeout"), "timeout"),
    ("router", LLMNetworkError("network"), "network"),
])
def test_role_tool_to_real_child_fallback_and_durable_receipt(tmp_path, role, error, reason):
    first, second = DecisionClient(error), DecisionClient(_response())
    runner, default = _runner(tmp_path, lambda r: (("p/first", first), ("q/second", second)) if r == role else ())
    tool = SpawnSubAgentTool(runner)
    result = tool.execute(task="decide from supplied facts", model_role=role)
    assert result.status == ToolResultStatus.SUCCESS, result.content
    import re
    child_id = re.search(r"child_id=(\S+)", result.content).group(1)
    final = _settle(runner, child_id)
    assert final.outcome == "completed"
    assert final.final_answer == "decision"
    assert final.model_role == role
    assert [a["model"] for a in final.model_attempts] == ["p/first", "q/second"]
    assert final.model_attempts[0]["reason"] == reason
    assert final.model_attempts[1]["observed_model"] == "actual-model"
    assert final.tokens_in == 12 and final.tokens_out == 3
    assert len(first.calls) == len(second.calls) == 1 and not default.calls
    assert first.calls[0][0] == second.calls[0][0]
    receipt = SubAgentResultTool(runner).execute(child_id=child_id)
    assert "[模型角色]" in receipt.content and "q/second" in receipt.content
    # A restart reconstructs the same receipt and cannot expand the role into a followup.
    restarted = SubAgentRunner(llm=default, registry=ToolRegistry(), session_store=runner.session_store)
    recovered = _settle(restarted, child_id)
    assert recovered.model_attempts == final.model_attempts
    assert restarted.followup_current(child_id, "execute something")[0] is False


def test_explicit_model_is_strict_and_does_not_consume_role_candidates(tmp_path):
    explicit = DecisionClient(LLMTimeoutError("timeout"))
    def no_role(_role):
        raise AssertionError("explicit model must not consult role candidates")
    runner, default = _runner(tmp_path, no_role, explicit=lambda ref: explicit)
    started = runner.start(task="decide", model_role="planning", model="p/explicit")
    final = _settle(runner, started["child_id"])
    assert final.outcome == "failed"
    assert [a["model"] for a in final.model_attempts] == ["p/explicit"]
    assert len(explicit.calls) == 1 and not default.calls


def test_role_unconfigured_and_review_authority_and_tool_scope_fail_closed(tmp_path):
    runner, default = _runner(tmp_path, lambda role: ())
    for kwargs in ({"model_role": "planning"}, {"model_role": "reviewer"},
                   {"model_role": "router", "review_isolated": True},
                   {"model_role": "router", "required_tools": ["execute_command"]},
                   {"model_role": "router", "fs_isolation": True}):
        assert not runner.start(task="decide", **kwargs)["accepted"]
    assert not default.calls
    assert runner.active_children("parent-role-test") == []


@pytest.mark.parametrize("bad", [LLMHTTPError("bad request", status_code=400),
                                 LLMResponse(content="", tool_calls=[ToolCall(id="x", name="execute_command", arguments={})]),
                                 LLMResponse(content="partial", tool_calls=[], truncated=True)])
def test_nonretryable_or_tool_response_never_replays_or_executes(tmp_path, bad):
    first, backup = DecisionClient(bad), DecisionClient(_response())
    runner, _ = _runner(tmp_path, lambda role: (("p/first", first), ("q/backup", backup)))
    started = runner.start(task="decide", model_role="router")
    final = _settle(runner, started["child_id"])
    assert final.outcome == "failed" and not final.tool_calls
    assert len(first.calls) == 1 and not backup.calls


def test_inflight_role_snapshot_frozen_next_decision_uses_new_candidates(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def blocked():
        entered.set()
        assert release.wait(4)
        raise LLMTimeoutError("timeout")
    first, old, new = DecisionClient(blocked), DecisionClient(_response("old")), DecisionClient(_response("new"))
    candidates = [("p/first", first), ("q/old", old)]
    runner, _ = _runner(tmp_path, lambda role: tuple(candidates))
    started = runner.start(task="decide", model_role="planning")
    try:
        assert entered.wait(2)
        candidates[:] = [("q/new", new)]
        assert not runner.send_current_message(started["child_id"], "steer")[0]
    finally:
        release.set()
    assert _settle(runner, started["child_id"]).final_answer == "old"
    next_child = runner.start(task="new decision", model_role="planning")
    assert _settle(runner, next_child["child_id"]).final_answer == "new"
    assert len(old.calls) == len(new.calls) == 1


@pytest.mark.parametrize("limit,expected", [(1, 1), (2, 2)])
def test_role_attempt_budget_and_exhaustion(tmp_path, limit, expected):
    clients = [DecisionClient(LLMTimeoutError("timeout")) for _ in range(3)]
    runner, default = _runner(tmp_path, lambda role: tuple((f"p/m{i}", c) for i, c in enumerate(clients)))
    started = runner.start(task="decide", model_role="router", max_rounds=limit)
    final = _settle(runner, started["child_id"])
    assert final.outcome == "failed" and len(final.model_attempts) == expected
    assert sum(len(c.calls) for c in clients) == expected and not default.calls


def test_role_account_billing_is_not_fallback(tmp_path):
    first = DecisionClient(LLMHTTPError("billing", status_code=429, provider="glm", provider_code="1113"))
    backup = DecisionClient(_response())
    runner, _ = _runner(tmp_path, lambda role: (("p/first", first), ("q/backup", backup)))
    final = _settle(runner, runner.start(task="decide", model_role="planning")["child_id"])
    assert final.outcome == "failed"
    assert final.model_attempts[0]["reason"] == "account_billing"
    assert not backup.calls

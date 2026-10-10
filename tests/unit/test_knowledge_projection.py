"""Thin host-facing projection: run, ingress and provider boundaries remain exact."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from llm_loop.core.loop.engine_services.knowledge_runtime import (
    _paired_tool_trace,
    project_execution_knowledge,
)
from llm_loop.core.message import Message, MessageSource, ToolResult, ToolResultStatus
from llm_loop.core.trace_leak.ingress_token import (
    current_ingress_session_id,
    current_ingress_token,
    issue_ingress,
)
from llm_loop.introspection.knowledge_advisor import KnowledgeAdvisor


def _records(*, kind, **_unused):
    rows = {
        "method": [{"method_ref": "method:repair", "status": "candidate",
                    "name": "repair broken pytest tests"}],
        "experience": [{"experience_ref": "experience:verified",
                        "record_kind": "experience", "status": "active",
                        "verification_state": "verified",
                        "summary": "repair broken tests"}],
        "lesson": [{"experience_ref": "experience:unverified",
                   "record_kind": "lesson", "status": "active",
                   "verification_state": "unverified", "summary": "pytest failure"}],
    }
    return rows[kind]


@dataclass
class _State:
    current_turn_ref: int = 0
    active_run_ingress_message: Message | None = None
    knowledge_runtime: object | None = None
    knowledge_turn_identity: str = ""


@dataclass
class _Host:
    mode: str
    sessions: str = "web-one"
    state: _State = field(default_factory=_State)
    events: list[tuple] = field(default_factory=list)
    search_calls: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.settings = SimpleNamespace(tool_runtime=SimpleNamespace(
            knowledge_advisor_mode=self.mode,
            knowledge_advisor_sessions=self.sessions,
        ))
        def search(**kw):
            self.search_calls.append(kw["kind"])
            return _records(**kw)
        self.corrections = SimpleNamespace(
            build_knowledge_advisor=lambda mode: KnowledgeAdvisor(search, mode=mode),
        )

    def _run_state(self):
        return self.state

    def _event_append(self, *args):
        self.events.append(args)


def _session(channel: str = "web", content: str = "repair broken pytest tests"):
    turn = Message(
        role="user", content=content, source=MessageSource.USER,
        metadata={"ingress_channel": channel, "ingress_entry": channel,
                  "origin_layer": "user_instruction", "program_origin": False},
    )
    return SimpleNamespace(session_id="web-one", messages=[turn]), turn


@pytest.fixture(autouse=True)
def _authenticated_web_context():
    token = current_ingress_token.set(issue_ingress("web"))
    identity = current_ingress_session_id.set("web-one")
    try:
        yield
    finally:
        current_ingress_session_id.reset(identity)
        current_ingress_token.reset(token)


def _call(id: str, *, tool="execute_command", args=None):
    return Message(
        role="assistant", content="", source=MessageSource.USER,
        tool_calls=[{"id": id, "type": "function",
                     "function": {"name": tool, "arguments": args or "{}"}}],
    )


def test_off_mode_preserves_exact_wire_and_zero_reads() -> None:
    host = _Host("off")
    sess, turn = _session()
    host.state.active_run_ingress_message = turn
    original = [{"role": "system", "content": "authority"},
                {"role": "user", "content": turn.content}]
    returned = project_execution_knowledge(
        host, sess, original, logical_round=1, history_budget=5000,
    )
    assert returned is original
    assert not host.events and not host.search_calls
    assert len(sess.messages) == 1


def test_web_allowlist_low_risk_injects_reference_only_into_wire() -> None:
    host = _Host("canary")
    sess, turn = _session()
    host.state.active_run_ingress_message = turn
    baseline = [{"role": "user", "content": turn.content}]
    projected = project_execution_knowledge(
        host, sess, baseline, logical_round=1, history_budget=5000,
    )
    assert len(baseline) == 1 and len(sess.messages) == 1
    assert len(projected) == 1 and "[资料·记忆/经验]" in projected[-1]["content"]
    assert projected[-1]["role"] == "user"  # no second tail user / GLM 1210
    assert projected[-1]["content"].startswith(turn.content + "\n\n")
    assert baseline[0]["content"] == turn.content
    assert host.search_calls == ["method", "experience", "lesson"]
    assert host.state.knowledge_turn_identity == "web-one:turn:0"
    assert project_execution_knowledge(
        host, sess, baseline, logical_round=2, history_budget=5000,
    ) is baseline


def test_non_web_ingress_shadow_only_even_if_session_id_matches() -> None:
    for channel in ["feishu", "cli", "", "delegated"]:
        host = _Host("canary")
        sess, turn = _session(channel)
        host.state.active_run_ingress_message = turn
        original = [{"role": "user", "content": turn.content}]
        assert project_execution_knowledge(
            host, sess, original, logical_round=1, history_budget=5000,
        ) is original
        assert host.search_calls and len(host.events) == 1


def test_unknown_session_or_high_risk_never_injects() -> None:
    for sessions, content in [
        ("web-someone-else", "repair broken pytest tests"),
        ("web-one", "publish production deployment after repairing tests"),
    ]:
        host = _Host("canary", sessions=sessions)
        sess, turn = _session(content=content)
        host.state.active_run_ingress_message = turn
        original = [{"role": "user", "content": turn.content}]
        assert project_execution_knowledge(
            host, sess, original, logical_round=1, history_budget=5000,
        ) is original


def test_metadata_alone_never_grants_canary_prompt_eligibility() -> None:
    host = _Host("canary")
    sess, turn = _session()
    host.state.active_run_ingress_message = turn
    saved = current_ingress_token.set(None)
    try:
        original = [{"role": "user", "content": turn.content}]
        assert project_execution_knowledge(
            host, sess, original, logical_round=1, history_budget=5000,
        ) is original
        assert host.events and host.search_calls
    finally:
        current_ingress_token.reset(saved)


def test_other_session_credential_cannot_consume_current_session_canary() -> None:
    host = _Host("canary")
    sess, turn = _session()
    host.state.active_run_ingress_message = turn
    token = current_ingress_session_id.set("different-session")
    try:
        original = [{"role": "user", "content": turn.content}]
        assert project_execution_knowledge(
            host, sess, original, logical_round=1, history_budget=5000,
        ) is original
    finally:
        current_ingress_session_id.reset(token)


def test_actual_session_tool_pair_drives_failure_learning_and_second_reference() -> None:
    host = _Host("canary")
    sess, turn = _session()
    host.state.active_run_ingress_message = turn
    baseline = [{"role": "user", "content": turn.content}]
    assert len(project_execution_knowledge(
        host, sess, baseline, logical_round=1, history_budget=5000,
    )) == 1
    sess.messages.append(_call("bad", args='{"command":"pytest -q"}'))
    failure = ToolResult(
        status=ToolResultStatus.FAILURE, content="fixture missing",
        tool_name="execute_command", tool_call_id="bad",
    ).to_message()
    sess.messages.append(failure)
    trace, receipts = _paired_tool_trace(sess.messages, 0)
    assert len(trace) == len(receipts) == 1
    assert trace[0]["id"] == "bad" and trace[0]["status"] == "failure"
    projected = project_execution_knowledge(
        host, sess, baseline, logical_round=2, history_budget=5000,
    )
    assert len(projected) == 1 and "[资料·记忆/经验]" in projected[-1]["content"]
    assert [name for _sid, name, _payload in host.events].count(
        "knowledge.failure_observed"
    ) == 1
    assert project_execution_knowledge(
        host, sess, baseline, logical_round=3, history_budget=5000,
    ) is baseline


def test_fake_or_unpaired_tool_result_cannot_trigger_learning() -> None:
    sess, turn = _session()
    host = _Host("canary")
    host.state.active_run_ingress_message = turn
    sess.messages.append(ToolResult(
        status=ToolResultStatus.FAILURE, content="not real",
        tool_name="execute_command", tool_call_id="no-declaration",
    ).to_message())
    assert _paired_tool_trace(sess.messages, 0) == ([], [])
    project_execution_knowledge(
        host, sess, [{"role": "user", "content": turn.content}],
        logical_round=2, history_budget=5000,
    )
    assert not any(name == "knowledge.failure_observed" for _, name, _ in host.events)


def test_new_human_ingress_resets_run_local_observer() -> None:
    host = _Host("canary")
    sess, turn = _session()
    host.state.active_run_ingress_message = turn
    baseline = [{"role": "user", "content": turn.content}]
    project_execution_knowledge(host, sess, baseline, logical_round=1, history_budget=5000)
    first_tracker = host.state.knowledge_runtime
    newer = Message(
        role="user", content="repair another broken pytest test",
        source=MessageSource.USER, metadata={"ingress_channel": "web"},
    )
    sess.messages.append(newer)
    host.state.current_turn_ref = 1
    host.state.active_run_ingress_message = newer
    project_execution_knowledge(host, sess, baseline, logical_round=1, history_budget=5000)
    assert host.state.knowledge_runtime is not first_tracker
    assert host.state.knowledge_turn_identity == "web-one:turn:1"

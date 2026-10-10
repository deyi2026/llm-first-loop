"""Predeployment gates for exact provider wire, run identity and evidence."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import cast

from llm_loop.core.loop.engine_services.knowledge_runtime import (
    KnowledgeRun,
    _paired_tool_trace,
    project_execution_knowledge,
)
from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_run_generation
from llm_loop.core.trace_leak.ingress_token import (
    current_ingress_session_id,
    current_ingress_token,
    issue_ingress,
)
from llm_loop.introspection.corrections import CorrectionToolRegistry
from llm_loop.introspection.knowledge_advisor import KnowledgeAdvisor
from llm_loop.llm.client import LLMResponse, provider_structure_violations
from tests.unit.test_err1210_recovery import _mk, _resp
from tests.unit.test_knowledge_projection import _Host, _session


def _hits(*, kind: str, **_kw):
    if kind == "method":
        return [{"method_ref": "method:repair", "status": "candidate",
                 "name": "diagnose pytest failure"}]
    if kind == "lesson":
        return [{"experience_ref": "experience:EXPERIENCE-example",
                 "record_kind": "lesson", "status": "active",
                 "verification_state": "unverified", "summary": "pytest fix"}]
    return []


def test_web_wire_uses_single_tail_user_and_preserves_ingress_marker():
    host = _Host("canary")
    sess, turn = _session()
    host.state.active_run_ingress_message = turn
    base = [
        {"role": "system", "content": "trusted system"},
        {"role": "user", "content": turn.content, "_active_run_ingress_ref": "0"},
    ]
    prior = [dict(m) for m in base]
    credential = current_ingress_token.set(issue_ingress("web"))
    sid = current_ingress_session_id.set("web-one")
    try:
        out = project_execution_knowledge(
            host, sess, base, logical_round=1, history_budget=5000,
        )
    finally:
        current_ingress_session_id.reset(sid)
        current_ingress_token.reset(credential)
    assert out is not base and base == prior
    assert len(out) == len(base)
    assert out[-1]["_active_run_ingress_ref"] == "0"
    assert out[-1]["content"].startswith(turn.content + "\n\n")
    assert out[-1]["content"].count("[资料·记忆/经验]") == 1
    assert provider_structure_violations(
        out, expected_active_ingress_ref="0",
    ) == []
    assert len(sess.messages) == 1


def test_after_tool_result_a_single_reference_user_is_structurally_valid():
    host = _Host("canary")
    sess, turn = _session()
    host.state.active_run_ingress_message = turn
    base = [
        {"role": "system", "content": "trusted system"},
        {"role": "user", "content": turn.content, "_active_run_ingress_ref": "0"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {
                "name": "read_file", "arguments": '{"path":"/tmp/test"}',
            }},
        ]},
        {"role": "tool", "content": "failed", "tool_call_id": "c1"},
    ]
    receipt = ToolResult(
        status=ToolResultStatus.FAILURE, content="failed",
        tool_call_id="c1", tool_name="read_file",
    ).to_message()
    from llm_loop.core.message import Message, MessageSource

    declared = Message(
        role="assistant", content="", source=MessageSource.USER,
        tool_calls=base[2]["tool_calls"],
    )
    sess.messages.extend([declared, receipt])
    # Observing the confirmed failure at round 2 is itself allowed; the
    # assertion is that the wire remains structurally valid without replay.
    credential = current_ingress_token.set(issue_ingress("web"))
    sid = current_ingress_session_id.set("web-one")
    try:
        out = project_execution_knowledge(
            host, sess, base, logical_round=2, history_budget=5000,
        )
    finally:
        current_ingress_session_id.reset(sid)
        current_ingress_token.reset(credential)
    assert len(out) == len(base) + 1
    assert out[-1]["role"] == "user"
    assert provider_structure_violations(
        out, expected_active_ingress_ref="0",
    ) == []
    assert len([m for m in sess.messages if m.role == "tool"]) == 1


def test_same_session_and_turn_with_new_generation_does_not_borrow_old_run():
    host = _Host("canary")
    sess, turn = _session()
    host.state.active_run_ingress_message = turn
    base = [{"role": "user", "content": turn.content}]
    credential = current_ingress_token.set(issue_ingress("web"))
    sid = current_ingress_session_id.set("web-one")
    gen_a = current_run_generation.set("generation-a")
    try:
        project_execution_knowledge(
            host, sess, base, logical_round=1, history_budget=5000,
        )
        first = host.state.knowledge_runtime
        assert host.state.knowledge_turn_identity.endswith(":run:generation-a")
        current_run_generation.set("generation-b")
        project_execution_knowledge(
            host, sess, base, logical_round=1, history_budget=5000,
        )
        assert host.state.knowledge_runtime is not first
        assert host.state.knowledge_turn_identity.endswith(":run:generation-b")
    finally:
        current_run_generation.reset(gen_a)
        current_ingress_session_id.reset(sid)
        current_ingress_token.reset(credential)


def test_search_successful_zero_hits_never_claims_hydration():
    events = []
    run = KnowledgeRun(
        advisor=KnowledgeAdvisor(_hits, mode="shadow"),
        session_id="sid", run_ref="sid:turn:0",
        event_append=lambda *a: events.append(a),
    )
    args = {"kind": "method", "query": "method:nonexistent"}
    trace = [{"id": "c1", "name": "search_records",
              "status": "success", "arguments": args}]
    fake_miss = ToolResult(
        status=ToolResultStatus.SUCCESS, tool_call_id="c1",
        tool_name="search_records",
        content="[search_records] 未找到匹配 'method:nonexistent' 的记录（不伪造结果）。",
    ).to_message()
    run.observe_receipts(trace, [fake_miss])
    assert not run._hydrated_refs
    assert not any(t == "knowledge.hydration_observed" for _, t, _ in events)
    # Mismatched tool id/name must be ignored before marking as seen.
    from llm_loop.core.message import Message, MessageSource

    declaration = Message(
        role="assistant", content="", source=MessageSource.USER,
        tool_calls=[{"id": "same", "type": "function",
                     "function": {"name": "search_records", "arguments": "{}"}}],
    )
    bad = ToolResult(
        status=ToolResultStatus.FAILURE, tool_call_id="same",
        tool_name="read_file", content="not a search receipt",
    ).to_message()
    good = ToolResult(
        status=ToolResultStatus.SUCCESS, tool_call_id="same",
        tool_name="search_records", content="[search_records] 未找到匹配。",
    ).to_message()
    projected, results = _paired_tool_trace(
        [declaration, bad, good], -1,
    )
    assert len(projected) == len(results) == 1
    assert projected[0]["name"] == "search_records"


def test_real_loop_engine_fake_provider_end_to_end_canary_wire(tmp_path, monkeypatch):
    engine, fake = _mk(tmp_path, monkeypatch, responses=[_resp("完成")])
    session_id = engine.session.create()
    engine.settings = replace(
        engine.settings,
        tool_runtime=replace(
            engine.settings.tool_runtime,
            knowledge_advisor_mode="canary",
            knowledge_advisor_sessions=session_id,
        ),
    )
    engine.corrections = cast(
        CorrectionToolRegistry,
        SimpleNamespace(build_knowledge_advisor=lambda mode: KnowledgeAdvisor(_hits, mode=mode)),
    )
    result = engine.run(
        session_id, "repair broken pytest unit tests",
        ingress=issue_ingress("web"),
    )
    assert result.final_answer == "完成"
    assert len(fake.calls) == 1
    wire = fake.calls[0]["messages"]
    assert wire[-1]["role"] == "user"
    assert "[资料·记忆/经验]" in wire[-1]["content"]
    assert sum(1 for m in wire[-2:] if m["role"] == "user") == 1
    saved = engine.session.load(session_id)
    assert len(saved.messages) <= 3
    assert not any("[资料·记忆/经验]" in m.content for m in saved.messages)


def test_real_engine_failure_retrieval_occurs_before_next_provider_request(
    tmp_path, monkeypatch,
):
    """A real failed read_file tool must never be retried by the advisor."""
    missing = tmp_path / "missing-file.txt"
    engine, fake = _mk(
        tmp_path, monkeypatch,
        responses=[
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="read-missing", name="read_file",
                        arguments={"path": str(missing)},
                    ),
                ],
                provider="fake",
            ),
            _resp("根据实际失败回执继续完成"),
        ],
    )
    sid = engine.session.create()
    engine.settings = replace(
        engine.settings,
        tool_runtime=replace(
            engine.settings.tool_runtime,
            knowledge_advisor_mode="canary",
            knowledge_advisor_sessions=sid,
        ),
    )
    engine.corrections = cast(
        CorrectionToolRegistry,
        SimpleNamespace(build_knowledge_advisor=lambda mode: KnowledgeAdvisor(_hits, mode=mode)),
    )
    result = engine.run(
        sid, "repair broken pytest unit tests",
        ingress=issue_ingress("web"),
    )
    assert "根据实际失败回执继续完成" in result.final_answer
    assert len(fake.calls) == 2
    assert fake.calls[0]["messages"][-1]["content"].count("[资料·记忆/经验]") == 1
    second = fake.calls[1]["messages"]
    assert second[-1]["content"].count("[资料·记忆/经验]") == 1
    assert second[-1]["role"] == "user"
    assert all(
        not (
            a.get("role") == "assistant"
            and any(
                tc.get("id") == "read-missing" for tc in a.get("tool_calls", [])
            )
        )
        for a in second[-1:]
    )
    assert not missing.exists()
    stored = engine.session.load(sid)
    assert not any("[资料·记忆/经验]" in m.content for m in stored.messages)

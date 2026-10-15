"""Canary consumption receipts must preserve evidence and knowledge authority."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import cast

import pytest

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.registry_experience import execute
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.tools_experience import run_save_experience
from tests.unit.test_knowledge_runtime import _run


def _experience(tmp_path):
    store = ExperienceStore(tmp_path / "experiences")
    text = run_save_experience(
        store, title="canary diagnosis", scenario="pytest diagnosis",
        solution="currentness verification: run pytest",
        record_kind="lesson", verification_state="unverified",
    )
    ref = text.split("experience_ref=")[1].split()[0]
    return store, ref


def test_experience_use_receipt_does_not_mutate_or_promote_source(tmp_path):
    store, ref = _experience(tmp_path)
    before = {p.name: p.read_bytes() for p in (tmp_path / "experiences").glob("*.md")}
    result = execute("refine_experience", {
        "action": "record_use", "experience_id": ref, "use_decision": "adapted",
        "note": "当前任务需先验证条件", "evidence_refs": ["tool:probe"],
    }, cast(RegistryHost, SimpleNamespace(experience_store=store)))
    assert result is not None and result.status is ToolResultStatus.SUCCESS
    data = json.loads(result.content.split("\n", 1)[1])
    assert data["ref"] == ref and data["decision"] == "adapted"
    assert data["verification_state"] == "unverified"
    assert data["task_benefit"] == "not_evaluated"
    assert {p.name: p.read_bytes() for p in (tmp_path / "experiences").glob("*.md")} == before


@pytest.mark.parametrize("ref, decision", [
    ("experience:missing", "applied"), ("../../outside", "rejected"),
    ("", "adapted"), ("experience:missing", "pass"),
])
def test_invalid_experience_declaration_is_not_success(tmp_path, ref, decision):
    result = execute("refine_experience", {
        "action": "record_use", "experience_id": ref, "use_decision": decision,
    }, cast(RegistryHost, SimpleNamespace(experience_store=ExperienceStore(tmp_path / "experiences"))))
    assert result is not None and result.status is ToolResultStatus.FAILURE


def test_wire_facts_require_the_exact_prepared_reference_bytes():
    run, events = _run()
    reference, refs = run.before_provider(
        query="repair broken pytest unit tests", round_no=1,
        trace=[], tool_messages=[], available_history_chars=5000,
    )
    assert reference and refs
    before = list(events)
    payload = {"messages": [{"role": "user", "content": "task\n\n" + reference}]}
    facts = run.provider_reference_facts(payload)
    assert len(facts) == 1 and facts[0]["refs"] == list(refs)
    assert facts[0]["reference_chars"] == len(reference)
    assert len(facts[0]["reference_sha256"]) == 64
    assert run.provider_reference_facts({"messages": [{"role": "user", "content": refs[0]}]}) == []
    assert run.provider_reference_facts({"messages": [{"role": "user", "content": reference[:-1]}]}) == []
    assert events == before  # preparing is not proof of transport/delivery


def test_terminal_consumption_observes_last_tool_and_deduplicates():
    run, events = _run()
    declaration = {
        "schema": "experience-use/v1", "ref": "experience:EXPERIENCE-example",
        "decision": "not_applicable", "record_kind": "lesson",
        "verification_state": "unverified", "task_benefit": "not_evaluated",
    }
    args = {"action": "record_use", "experience_id": declaration["ref"],
            "use_decision": "not_applicable"}
    trace = [{"id": "last", "name": "refine_experience",
              "arguments": args, "status": "success"}]
    receipt = ToolResult(
        status=ToolResultStatus.SUCCESS, tool_name="refine_experience",
        tool_call_id="last", content="[refine_experience] use declaration\n" + json.dumps(declaration),
    ).to_message()
    for _ in range(2):
        run.finish(trace=trace, tool_messages=[receipt], reason="cancelled",
                   rounds=1, tokens_in=17, tokens_out=2, duration_ms=40,
                   model_used="fixture/model", run_incomplete=True)
    rows = [p for _, t, p in events if t == "knowledge.experience_declaration"]
    assert len(rows) == 1 and rows[0]["decision"] == "not_applicable"
    assert rows[0]["hydration_observed"] is False
    endings = [p for _, t, p in events if t == "knowledge.run_outcome"]
    assert len(endings) == 1 and endings[0]["reason"] == "cancelled"
    assert endings[0]["task_benefit"] == "not_evaluated"


def test_unconfirmed_experience_tool_success_never_counts_as_adoption():
    run, events = _run()
    trace = [{"id": "bad", "name": "refine_experience", "status": "success",
              "arguments": {"action": "record_use", "experience_id": "experience:missing",
                            "use_decision": "applied"}}]
    receipt = ToolResult(status=ToolResultStatus.SUCCESS, tool_call_id="bad",
                         tool_name="refine_experience", content="not confirmed").to_message()
    run.observe_receipts(trace, [receipt])
    assert not any(t == "knowledge.experience_declaration" for _, t, _ in events)

def test_real_http_payload_and_prepared_journal_facts_match(monkeypatch):
    from contextlib import contextmanager

    import httpx

    from llm_loop.llm.client import GuardRequestContext, LLMClient
    from llm_loop.resources.provider_settlement import ProviderCallSettlementJournal

    run, _ = _run()
    reference, refs = run.before_provider(
        query="repair broken pytest unit tests", round_no=1,
        trace=[], tool_messages=[], available_history_chars=5000,
    )
    prepared = []
    requests = []

    class Recorder:
        @contextmanager
        def transport_attempt(self, **kwargs):
            prepared.append(ProviderCallSettlementJournal._normalize_prepared(kwargs["prepared"]))
            yield

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=b'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')

    client = LLMClient(
        api_key="fixture-key", base_url="https://fixture.invalid/v1",
        model="glm-5.3", provider="glm", guard_enabled=False,
        transport_observer=Recorder(),
    )
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handle))
    try:
        response = client.chat(
            [{"role": "user", "content": "task\n\n" + reference}], tools=[],
            guard_context=GuardRequestContext(
                session_id="web-one", knowledge_reference_probe=run.provider_reference_facts,
            ),
        )
    finally:
        client.close()
    assert response.content == "OK" and len(requests) == len(prepared) == 1
    assert reference in requests[0]["messages"][-1]["content"]
    assert prepared[0]["knowledge_references"] == run.provider_reference_facts(requests[0])
    assert prepared[0]["knowledge_references"][0]["refs"] == list(refs)


def test_actual_status_prefixed_hydration_receipt_is_observed():
    run, events = _run()
    ref = "experience:EXPERIENCE-example"
    args = {"kind": "lesson", "query": ref}
    receipt = ToolResult(
        status=ToolResultStatus.SUCCESS, tool_call_id="read", tool_name="search_records",
        content="[search_records] 命中 1 条\nexperience_ref=" + ref + "\nbody=complete lesson",
    ).to_message()
    run.observe_receipts([{
        "id": "read", "name": "search_records", "arguments": args, "status": "success",
    }], [receipt])
    assert ref in run._hydrated_refs
    assert sum(t == "knowledge.hydration_observed" for _, t, _ in events) == 1


def test_real_engine_terminal_outcome_is_recorded_without_live_provider(tmp_path, monkeypatch):
    from dataclasses import replace

    from llm_loop.core.trace_leak.ingress_token import issue_ingress
    from llm_loop.introspection.corrections import CorrectionToolRegistry
    from llm_loop.introspection.knowledge_advisor import KnowledgeAdvisor
    from tests.unit.test_err1210_recovery import _mk, _resp
    from tests.unit.test_knowledge_predeploy_gates import _hits

    engine, fake = _mk(tmp_path, monkeypatch, responses=[_resp("done")])
    sid = engine.session.create()
    engine.settings = replace(
        engine.settings, tool_runtime=replace(
            engine.settings.tool_runtime, knowledge_advisor_mode="canary",
            knowledge_advisor_sessions=sid,
        ),
    )
    engine.corrections = cast(
        CorrectionToolRegistry,
        SimpleNamespace(build_knowledge_advisor=lambda mode: KnowledgeAdvisor(_hits, mode=mode)),
    )
    events = []
    original = engine._event_append

    def capture(*args, **kwargs):
        events.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(engine, "_event_append", capture)
    result = engine.run(sid, "repair broken pytest unit tests", ingress=issue_ingress("web"))
    assert result.final_answer == "done" and len(fake.calls) == 1
    outcomes = [args[2] for args in events if args[1] == "knowledge.run_outcome"]
    assert len(outcomes) == 1 and outcomes[0]["task_benefit"] == "not_evaluated"
    assert outcomes[0]["reason"] == "completed"
    # v0.8 producer 字段（P0b 机会分母/join 主键）：run_outcome 记实际 mode，
    # run.end 的 knowledge_run_ref 与 run_outcome 的 run_ref 可靠 join。
    assert outcomes[0]["advisor_mode"] == "canary"
    run_ends = [args[2] for args in events if args[1] == "run.end"]
    assert len(run_ends) == 1
    assert run_ends[0]["knowledge_run_ref"] == outcomes[0]["run_ref"]
    assert run_ends[0]["knowledge_advisor_mode"] == "canary"

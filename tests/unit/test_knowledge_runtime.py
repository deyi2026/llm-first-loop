"""Execution-time knowledge reference and factual learning feedback contract."""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.loop.engine_services.knowledge_runtime import KnowledgeRun
from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.knowledge_advisor import KnowledgeAdvisor
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.tools_experience import run_save_experience
from llm_loop.methods.store import MethodStore


def _search(*, kind: str, **_unused):
    rows = {
        "method": [{"method_ref": "method:repair", "name": "repair broken tests",
                    "status": "candidate", "content_hash": "method-sha"}],
        "experience": [{"experience_ref": "experience:verified",
                        "record_kind": "experience", "summary": "repair broken tests",
                        "status": "active", "verification_state": "verified"}],
        "lesson": [{"experience_ref": "experience:unverified",
                   "record_kind": "lesson", "summary": "repair test failure",
                   "status": "active", "verification_state": "unverified"}],
    }
    return rows[kind]


def _result(call_id: str, name: str, status: ToolResultStatus, content: str = ""):
    return ToolResult(
        status=status, content=content or f"actual {name} {status.value} receipt",
        tool_name=name, tool_call_id=call_id,
    ).to_message()


def _run(mode="canary", *, sessions=frozenset({"web-one"}), sink=None):
    events = [] if sink is None else sink
    run = KnowledgeRun(
        advisor=KnowledgeAdvisor(_search, mode=mode),
        session_id="web-one", run_ref="web-one:turn:1",
        event_append=lambda sid, typ, payload: events.append((sid, typ, payload)),
        canary_sessions=sessions,
    )
    return run, events


def test_first_decision_reference_only_in_allowlisted_low_risk() -> None:
    run, events = _run()
    msg, refs = run.before_provider(
        query="repair broken pytest unit tests", round_no=1,
        trace=[], tool_messages=[], available_history_chars=5000,
    )
    assert set(refs) == {"method:repair", "experience:verified", "experience:unverified"}
    assert "[资料·记忆/经验]" in msg
    assert "candidate" in msg and "unverified" in msg
    assert [e[1] for e in events] == ["knowledge.discovery", "knowledge.reference_prepared"]
    assert events[0][2]["applicability"] == "not_evaluated"
    assert events[1][2]["provider_delivery"] == "not_confirmed"
    assert run.before_provider(
        query="repair broken pytest unit tests", round_no=2,
        trace=[], tool_messages=[], available_history_chars=5000,
    ) == ("", ())


def test_off_mode_no_events_and_no_retrieval() -> None:
    run, events = _run(mode="off")
    assert run.before_provider(
        query="repair broken pytest unit tests", round_no=1,
        trace=[], tool_messages=[], available_history_chars=5000,
    ) == ("", ())
    assert not events


def test_shadow_and_unallowlisted_canary_never_project_to_provider() -> None:
    for mode, allow in [("shadow", frozenset({"web-one"})), ("canary", frozenset())]:
        run, events = _run(mode, sessions=allow)
        msg, refs = run.before_provider(
            query="repair broken pytest unit tests", round_no=1,
            trace=[], tool_messages=[], available_history_chars=5000,
        )
        assert msg == "" and refs
        assert [e[1] for e in events] == ["knowledge.discovery"]


def test_high_risk_or_insufficient_budget_never_injects_reference() -> None:
    for query, budget in [
        ("publish production deployment after tests", 5000),
        ("repair broken pytest unit tests", 10),
    ]:
        run, events = _run()
        msg, _ = run.before_provider(
            query=query, round_no=1, trace=[], tool_messages=[],
            available_history_chars=budget,
        )
        assert msg == ""
        assert [e[1] for e in events] == ["knowledge.discovery"]


def test_actual_paired_tool_failure_retrieves_once_before_next_decision() -> None:
    run, events = _run()
    query = "repair broken pytest unit tests"
    first, _ = run.before_provider(
        query=query, round_no=1, trace=[], tool_messages=[], available_history_chars=5000,
    )
    assert first
    trace = [{"id": "tool-1", "name": "execute_command",
              "status": "failure", "arguments": {"command": "pytest -q"}}]
    msg, refs = run.before_provider(
        query=query, round_no=2, trace=trace,
        tool_messages=[_result("tool-1", "execute_command", ToolResultStatus.FAILURE)],
        available_history_chars=5000,
    )
    assert msg and refs
    assert sum(event[1] == "knowledge.failure_observed" for event in events) == 1
    assert sum(event[1] == "knowledge.discovery" for event in events) == 2
    assert run.before_provider(
        query=query, round_no=3, trace=trace,
        tool_messages=[_result("tool-1", "execute_command", ToolResultStatus.FAILURE)],
        available_history_chars=5000,
    ) == ("", ())
    assert sum(event[1] == "knowledge.failure_observed" for event in events) == 1


def test_unpaired_or_mismatched_receipt_cannot_create_fake_failure() -> None:
    for message in [
        None,
        _result("tool-1", "execute_command", ToolResultStatus.SUCCESS),
        _result("different-id", "execute_command", ToolResultStatus.FAILURE),
    ]:
        run, events = _run()
        trace = [{"id": "tool-1", "name": "execute_command",
                  "status": "failure", "arguments": {}}]
        run.observe_receipts(trace, [message] if message is not None else [])
        assert not events
        assert run._first_failure is None


def test_model_method_declaration_is_not_objective_task_benefit() -> None:
    run, events = _run()
    trace = [{"id": "method-1", "name": "method_manage", "status": "success",
              "arguments": {"action": "record_use", "method_ref": "method:repair",
                            "use_decision": "applied"}}]
    run.observe_receipts(trace, [_result("method-1", "method_manage", ToolResultStatus.SUCCESS)])
    rows = [e[2] for e in events if e[1] == "knowledge.method_declaration"]
    assert len(rows) == 1
    assert rows[0]["decision"] == "applied"
    assert rows[0]["task_benefit"] == "not_evaluated"


def test_failure_followed_by_success_does_not_claim_recovery_proven() -> None:
    run, events = _run()
    trace = [
        {"id": "bad", "name": "execute_command", "status": "failure", "arguments": {}},
        {"id": "good", "name": "execute_command", "status": "success", "arguments": {}},
    ]
    messages = [
        _result("bad", "execute_command", ToolResultStatus.FAILURE),
        _result("good", "execute_command", ToolResultStatus.SUCCESS),
    ]
    run.observe_receipts(trace, messages)
    assert [e[1] for e in events] == [
        "knowledge.failure_observed", "knowledge.followup_tool_observed",
    ]
    assert events[-1][2]["recovery_proven"] is False
    run.observe_receipts(trace, messages)
    assert len(events) == 2


def test_true_lesson_save_receipt_linked_to_failure_without_fake_verification() -> None:
    run, events = _run()
    trace = [
        {"id": "bad", "name": "execute_command", "status": "failure", "arguments": {}},
        {"id": "saved", "name": "save_experience", "status": "success",
         "arguments": {"record_kind": "lesson", "verification_state": "unverified"}},
    ]
    run.observe_receipts(trace, [
        _result("bad", "execute_command", ToolResultStatus.FAILURE),
        _result(
            "saved", "save_experience", ToolResultStatus.SUCCESS,
            "[save_experience] 已沉淀 EXPERIENCE-20261008-repair.md "
            "experience_ref=experience:EXPERIENCE-20261008-repair status=active "
            "record_kind=lesson verification_state=unverified",
        ),
    ])
    recorded = [e[2] for e in events if e[1] == "knowledge.learning_saved"]
    assert len(recorded) == 1
    assert recorded[0]["first_failed_call_id"] == "bad"
    assert recorded[0]["record_kind"] == "lesson"
    assert recorded[0]["ref"] == "experience:EXPERIENCE-20261008-repair"
    assert recorded[0]["independently_validated"] is False


def test_conflict_or_uncertain_save_never_counted_as_learning_saved() -> None:
    for content in [
        "[save_experience] 文件冲突: already exists",
        "[save_experience] 提交结果不确定: experience:EXPERIENCE-20261008-repair",
        "[save_experience] 确定未提交: fsync failed",
    ]:
        run, events = _run()
        run.observe_receipts(
            [{"id": "c", "name": "save_experience", "status": "success",
              "arguments": {"record_kind": "lesson", "verification_state": "unverified"}}],
            [_result("c", "save_experience", ToolResultStatus.SUCCESS, content)],
        )
        assert not any(e[1] == "knowledge.learning_saved" for e in events)
        assert len(events) == 1 and events[0][1] == "knowledge.learning_unconfirmed"


def test_mismatched_tool_name_cannot_infer_failure() -> None:
    run, events = _run()
    run.observe_receipts(
        [{"id": "same", "name": "execute_command", "status": "failure", "arguments": {}}],
        [_result("same", "read_file", ToolResultStatus.FAILURE)],
    )
    assert not events and run._first_failure is None


def test_event_store_failure_does_not_block_advice_or_tool_processing() -> None:
    run = KnowledgeRun(
        advisor=KnowledgeAdvisor(_search, mode="canary"),
        session_id="web-one", run_ref="r",
        event_append=lambda *_args: (_ for _ in ()).throw(OSError("event store offline")),
        canary_sessions=frozenset({"web-one"}),
    )
    msg, refs = run.before_provider(
        query="repair broken pytest unit tests", round_no=1, trace=[],
        tool_messages=[], available_history_chars=5000,
    )
    assert msg and refs
    run.observe_receipts(
        [{"id": "bad", "name": "execute_command", "status": "failure", "arguments": {}}],
        [_result("bad", "execute_command", ToolResultStatus.FAILURE)],
    )


def test_end_to_end_failed_tool_lesson_saved_then_retrieved_next_run(tmp_path: Path) -> None:
    """Real Candidate + failed receipt + Lesson save + next-run recall; no provider."""
    store = ExperienceStore(tmp_path / "experiences")
    methods = MethodStore(tmp_path / "methods")
    body = "\n".join(
        f"## {section}\nInspect pytest fixture environment before repeating failed tests."
        for section in (
            "Trigger", "Discriminator", "Short path",
            "Stop conditions", "Verification", "Counterexamples",
        )
    )
    candidate = methods.save_candidate(
        name="pytest fixture environment repair",
        description="Diagnose missing pytest fixture environment inputs",
        body=body,
    )
    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit", method_store=methods, experience_store=store,
    )
    original_events: list[tuple] = []
    first_run = KnowledgeRun(
        advisor=KnowledgeAdvisor(searcher.search, mode="canary"),
        session_id="web-original", run_ref="web-original:turn:1",
        event_append=lambda *args: original_events.append(args),
        canary_sessions=frozenset({"web-original"}),
    )
    query = "pytest fixture environment repair tests failed"
    _first_body, first_refs = first_run.before_provider(
        query=query, round_no=1, trace=[], tool_messages=[],
        available_history_chars=5000,
    )
    assert candidate.method_ref in first_refs
    first_run.observe_receipts(
        [{"id": "bad", "name": "execute_command", "status": "failure",
          "arguments": {"command": "pytest -q"}}],
        [_result("bad", "execute_command", ToolResultStatus.FAILURE)],
    )
    saved = run_save_experience(
        store, title="pytest fixture misses environment contract",
        scenario="pytest fixture environment repair tests failed before target logic",
        solution="未验证假设：pytest fixture 环境不完整；当前性验证：先检查必要环境变量",
        root_cause="not yet established",
        record_kind="lesson", verification_state="unverified",
        evidence="", tags=["pytest", "fixture", "environment"],
        source={"episode_ref": "episode:fixture:test", "tool_call_id": "bad"},
        body="复现：使用独立 fixture 测试确认缺失的具体字段",
    )
    assert saved.startswith("[save_experience] 已沉淀 "), saved
    first_run.observe_receipts(
        [{"id": "saved", "name": "save_experience", "status": "success",
          "arguments": {"record_kind": "lesson", "verification_state": "unverified"}}],
        [_result("saved", "save_experience", ToolResultStatus.SUCCESS, saved)],
    )
    learning_events = [
        payload for _sid, event, payload in original_events
        if event == "knowledge.learning_saved"
    ]
    assert len(learning_events) == 1
    saved_ref = learning_events[0]["ref"]
    assert saved_ref.startswith("experience:EXPERIENCE-")
    assert learning_events[0]["first_failed_call_id"] == "bad"
    assert not learning_events[0]["independently_validated"]
    next_run = KnowledgeRun(
        advisor=KnowledgeAdvisor(searcher.search, mode="canary"),
        session_id="web-next", run_ref="web-next:turn:1",
        event_append=lambda *_args: None,
        canary_sessions=frozenset({"web-next"}),
    )
    body, refs = next_run.before_provider(
        query=query, round_no=1,
        trace=[], tool_messages=[], available_history_chars=5000,
    )
    assert saved_ref in refs and candidate.method_ref in refs
    assert "unverified" in body
    assert "not yet established" not in body  # cannot inline unverified root cause
